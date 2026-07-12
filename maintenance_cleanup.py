"""Background retention and cleanup helpers for Hui Chat.

These helpers are intentionally import-safe for the standalone janitor process:
they only depend on the low-level DB connection facade and do not require a
Flask request/app context.
"""

from __future__ import annotations

import logging
import os
import re
import time
from pathlib import Path
from typing import Any

from database import _acquire_conn, _release_conn
from security import safe_existing_file_under


def _truthy(value: Any, default: bool = True) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _coerce_days(settings: dict | None, key: str, default: int, *, minimum: int = 0, maximum: int = 3650) -> int:
    settings = settings or {}
    try:
        value = int(settings.get(key, default))
    except Exception:
        value = default
    return max(minimum, min(value, maximum))


def _coerce_limit(limit: Any, default: int = 500) -> int:
    try:
        value = int(limit)
    except Exception:
        value = default
    return max(1, min(value, 10000))


def _delete_limited(cur, sql: str, params: tuple) -> int:
    cur.execute(sql, params)
    row = cur.fetchone()
    try:
        return int(row[0] or 0) if row else 0
    except Exception:
        return 0




def _coerce_minutes(settings: dict | None, key: str, default: int, *, minimum: int = 0, maximum: int = 525600) -> int:
    settings = settings or {}
    try:
        value = int(settings.get(key, default))
    except Exception:
        value = default
    return max(minimum, min(value, maximum))


def _upload_root(settings: dict | None, key: str, default_tail: str) -> str:
    settings = settings or {}
    raw = settings.get(key) or os.path.join(os.getcwd(), "uploads", default_tail)
    return str(Path(raw).expanduser().resolve())


def _unlink_under_root(root: str, stored_path: str | None) -> bool:
    safe_path = safe_existing_file_under(root, stored_path or "")
    if not safe_path:
        return False
    try:
        os.remove(safe_path)
        return True
    except FileNotFoundError:
        return False
    except Exception:
        logging.exception("failed to remove retained private-file blob under %s", root)
        return False


_PRIVATE_FILE_ID_RE = re.compile(r"^[0-9a-f]{32}$")


def _empty_orphan_blob_result() -> dict[str, int]:
    return {
        "scanned": 0,
        "candidates": 0,
        "deleted": 0,
        "skipped_young": 0,
        "skipped_known": 0,
        "skipped_bad_name": 0,
        "skipped_symlink": 0,
        "skipped_unsafe": 0,
        "errors": 0,
    }


def _collect_old_private_blob_candidates(root: str, *, max_files: int, grace_minutes: int) -> tuple[dict[str, int], dict[str, str]]:
    """Return old generated ``*.bin`` blobs that still need DB confirmation.

    This collector is deliberately conservative: only immediate files with the
    same 32-lowercase-hex naming scheme used by the encrypted private-file
    upload endpoints are candidates.  Symlinks, oddly named files, directories,
    and young files are never deleted by the janitor.
    """
    result = _empty_orphan_blob_result()
    candidates: dict[str, str] = {}
    try:
        root_path = Path(root).expanduser().resolve()
        if not root_path.is_dir():
            return result, candidates
        cutoff = time.time() - (max(0, int(grace_minutes)) * 60)
        for path in sorted(root_path.glob("*.bin")):
            if result["scanned"] >= max_files:
                break
            result["scanned"] += 1
            try:
                file_id = path.stem
                if not _PRIVATE_FILE_ID_RE.fullmatch(file_id):
                    result["skipped_bad_name"] += 1
                    continue
                if path.is_symlink() or not path.is_file():
                    result["skipped_symlink"] += 1
                    continue
                try:
                    stat = path.stat()
                except FileNotFoundError:
                    continue
                if stat.st_mtime > cutoff:
                    result["skipped_young"] += 1
                    continue
                safe_path = safe_existing_file_under(root_path, path)
                if not safe_path:
                    result["skipped_unsafe"] += 1
                    continue
                candidates[file_id] = safe_path
            except FileNotFoundError:
                continue
            except Exception:
                result["errors"] += 1
                logging.exception("failed to inspect orphan private-file blob candidate: %s", path)
    except Exception:
        result["errors"] += 1
        logging.exception("orphan private-file blob scan failed for %s", root)
    result["candidates"] = len(candidates)
    return result, candidates


def _delete_confirmed_orphan_private_blobs(root: str, result: dict[str, int], candidates: dict[str, str], existing_ids: set[str], *, grace_minutes: int) -> dict[str, int]:
    """Delete candidate blobs only after a fresh DB lookup says they are absent."""
    try:
        root_path = Path(root).expanduser().resolve()
        cutoff = time.time() - (max(0, int(grace_minutes)) * 60)
        for file_id, safe_path in sorted(candidates.items()):
            if file_id in existing_ids:
                result["skipped_known"] += 1
                continue
            try:
                path = Path(safe_path)
                if path.is_symlink() or not path.is_file():
                    result["skipped_symlink"] += 1
                    continue
                # Re-check the file stayed under the configured root and stayed old
                # between candidate collection and deletion.
                safe_again = safe_existing_file_under(root_path, path)
                if not safe_again:
                    result["skipped_unsafe"] += 1
                    continue
                if Path(safe_again).stat().st_mtime > cutoff:
                    result["skipped_young"] += 1
                    continue
                os.remove(safe_again)
                result["deleted"] += 1
            except FileNotFoundError:
                continue
            except Exception:
                result["errors"] += 1
                logging.exception("failed to delete confirmed orphan private-file blob: %s", safe_path)
    except Exception:
        result["errors"] += 1
        logging.exception("confirmed orphan private-file blob deletion failed for %s", root)
    return result

def cleanup_expired_auth_artifacts(settings: dict | None = None, *, limit: int = 500) -> dict:
    """Delete stale auth/session/reset-token rows that no longer serve security.

    The janitor already privacy-retains old IP/UA values.  This function handles
    rows that are safe to remove entirely:
      - expired, revoked, or replaced JWT rows older than the token-retention TTL
      - revoked auth-session rows older than the session-retention TTL
      - orphan auth-session/token rows for users that no longer exist
      - used/expired password-reset-token rows older than the reset-token TTL

    It never deletes active tokens/sessions for existing users.
    """

    settings = settings or {}
    result = {
        "ok": True,
        "enabled": _truthy(settings.get("cleanup_expired_auth_enabled"), True),
        "deleted": {
            "auth_tokens": 0,
            "auth_sessions": 0,
            "orphan_auth_tokens": 0,
            "orphan_auth_sessions": 0,
            "password_reset_tokens": 0,
        },
    }
    if not result["enabled"]:
        result["skipped"] = "auth cleanup disabled"
        return result

    limit = _coerce_limit(limit)
    token_days = _coerce_days(settings, "auth_token_retention_days", 30, minimum=1)
    session_days = _coerce_days(settings, "revoked_session_retention_days", 30, minimum=1)
    reset_days = _coerce_days(settings, "password_reset_token_retention_days", 7, minimum=1)
    orphan_days = _coerce_days(settings, "orphan_auth_retention_days", 1, minimum=0)
    orphan_cleanup = _truthy(settings.get("cleanup_orphan_auth_enabled"), True)

    result["retention_days"] = {
        "auth_tokens": token_days,
        "revoked_sessions": session_days,
        "password_reset_tokens": reset_days,
        "orphan_auth": orphan_days,
    }
    result["orphan_cleanup_enabled"] = bool(orphan_cleanup)

    conn, from_pool = _acquire_conn()
    try:
        with conn.cursor() as cur:
            result["deleted"]["auth_tokens"] = _delete_limited(
                cur,
                """
                WITH doomed AS (
                    SELECT jti
                      FROM auth_tokens
                     WHERE (
                               expires_at IS NOT NULL
                           AND expires_at < (CURRENT_TIMESTAMP - (%s || ' days')::interval)
                           )
                        OR (
                               (revoked_at IS NOT NULL OR replaced_by IS NOT NULL)
                           AND COALESCE(revoked_at, last_used_at, expires_at, created_at)
                               < (CURRENT_TIMESTAMP - (%s || ' days')::interval)
                           )
                     ORDER BY COALESCE(revoked_at, expires_at, last_used_at, created_at) ASC
                     LIMIT %s
                ), deleted AS (
                    DELETE FROM auth_tokens t
                     USING doomed d
                     WHERE t.jti = d.jti
                     RETURNING 1
                )
                SELECT COUNT(*) FROM deleted;
                """,
                (token_days, token_days, limit),
            )

            result["deleted"]["auth_sessions"] = _delete_limited(
                cur,
                """
                WITH doomed AS (
                    SELECT session_id
                      FROM auth_sessions
                     WHERE revoked_at IS NOT NULL
                       AND revoked_at < (CURRENT_TIMESTAMP - (%s || ' days')::interval)
                     ORDER BY revoked_at ASC
                     LIMIT %s
                ), deleted AS (
                    DELETE FROM auth_sessions s
                     USING doomed d
                     WHERE s.session_id = d.session_id
                     RETURNING 1
                )
                SELECT COUNT(*) FROM deleted;
                """,
                (session_days, limit),
            )

            if orphan_cleanup:
                result["deleted"]["orphan_auth_tokens"] = _delete_limited(
                    cur,
                    """
                    WITH doomed AS (
                        SELECT t.jti
                          FROM auth_tokens t
                         WHERE NOT EXISTS (
                                   SELECT 1 FROM users u
                                    WHERE LOWER(u.username) = LOWER(t.username)
                               )
                           AND COALESCE(t.last_used_at, t.expires_at, t.created_at)
                               < (CURRENT_TIMESTAMP - (%s || ' days')::interval)
                         ORDER BY COALESCE(t.last_used_at, t.expires_at, t.created_at) ASC
                         LIMIT %s
                    ), deleted AS (
                        DELETE FROM auth_tokens t
                         USING doomed d
                         WHERE t.jti = d.jti
                         RETURNING 1
                    )
                    SELECT COUNT(*) FROM deleted;
                    """,
                    (orphan_days, limit),
                )
                result["deleted"]["orphan_auth_sessions"] = _delete_limited(
                    cur,
                    """
                    WITH doomed AS (
                        SELECT s.session_id
                          FROM auth_sessions s
                         WHERE NOT EXISTS (
                                   SELECT 1 FROM users u
                                    WHERE LOWER(u.username) = LOWER(s.username)
                               )
                           AND COALESCE(s.revoked_at, s.last_activity_at, s.last_seen_at, s.created_at)
                               < (CURRENT_TIMESTAMP - (%s || ' days')::interval)
                         ORDER BY COALESCE(s.revoked_at, s.last_activity_at, s.last_seen_at, s.created_at) ASC
                         LIMIT %s
                    ), deleted AS (
                        DELETE FROM auth_sessions s
                         USING doomed d
                         WHERE s.session_id = d.session_id
                         RETURNING 1
                    )
                    SELECT COUNT(*) FROM deleted;
                    """,
                    (orphan_days, limit),
                )

            result["deleted"]["password_reset_tokens"] = _delete_limited(
                cur,
                """
                WITH doomed AS (
                    SELECT id
                      FROM password_reset_tokens
                     WHERE (used_at IS NOT NULL OR expires_at < CURRENT_TIMESTAMP)
                       AND COALESCE(used_at, expires_at, created_at)
                           < (CURRENT_TIMESTAMP - (%s || ' days')::interval)
                     ORDER BY COALESCE(used_at, expires_at, created_at) ASC
                     LIMIT %s
                ), deleted AS (
                    DELETE FROM password_reset_tokens p
                     USING doomed d
                     WHERE p.id = d.id
                     RETURNING 1
                )
                SELECT COUNT(*) FROM deleted;
                """,
                (reset_days, limit),
            )
        conn.commit()
        return result
    except Exception as exc:
        try:
            conn.rollback()
        except Exception:
            pass
        result["ok"] = False
        result["error"] = type(exc).__name__
        logging.exception("cleanup_expired_auth_artifacts failed")
        return result
    finally:
        _release_conn(conn, from_pool)



def cleanup_revoked_private_files(settings: dict | None = None, *, limit: int = 500) -> dict:
    """Remove revoked encrypted DM/group file rows and their ciphertext blobs.

    This cleanup intentionally targets only rows already marked revoked and older
    than the configured retention period.  The server never decrypts these files;
    deletion is strictly a storage/retention operation.  DB rows are deleted
    first and committed, then disk blobs are best-effort removed under the
    configured private upload roots.  If a file unlink fails, the orphan-blob
    scanner can remove it later without risking active DB references.
    """
    settings = settings or {}
    result = {
        "ok": True,
        "enabled": _truthy(settings.get("cleanup_revoked_private_files_enabled"), True),
        "retention_days": _coerce_days(settings, "revoked_private_file_retention_days", 7, minimum=1),
        "deleted_rows": {"dm_files": 0, "group_files": 0},
        "deleted_blobs": {"dm_files": 0, "group_files": 0},
        "missing_blobs": {"dm_files": 0, "group_files": 0},
    }
    if not result["enabled"]:
        result["skipped"] = "revoked private-file cleanup disabled"
        return result

    limit = _coerce_limit(limit)
    days = int(result["retention_days"])
    dm_root = _upload_root(settings, "dm_upload_root", "dm_files")
    group_root = _upload_root(settings, "group_upload_root", "group_files")
    selected: dict[str, list[tuple[str, str]]] = {"dm_files": [], "group_files": []}

    conn, from_pool = _acquire_conn()
    try:
        with conn.cursor() as cur:
            for table in ("dm_files", "group_files"):
                cur.execute(
                    f"""
                    SELECT file_id, storage_path
                      FROM {table}
                     WHERE COALESCE(revoked, FALSE) = TRUE
                       AND COALESCE(uploaded_at, CURRENT_TIMESTAMP) < (CURRENT_TIMESTAMP - (%s || ' days')::interval)
                     ORDER BY COALESCE(uploaded_at, CURRENT_TIMESTAMP) ASC
                     LIMIT %s;
                    """,
                    (days, limit),
                )
                rows = [(str(r[0]), str(r[1] or "")) for r in (cur.fetchall() or [])]
                selected[table] = rows
                if rows:
                    ids = [r[0] for r in rows]
                    cur.execute(f"DELETE FROM {table} WHERE file_id = ANY(%s);", (ids,))
                    result["deleted_rows"][table] = int(cur.rowcount or 0)
        conn.commit()
    except Exception as exc:
        try:
            conn.rollback()
        except Exception:
            pass
        result["ok"] = False
        result["error"] = type(exc).__name__
        logging.exception("cleanup_revoked_private_files failed")
        return result
    finally:
        _release_conn(conn, from_pool)

    for table, root in (("dm_files", dm_root), ("group_files", group_root)):
        for _file_id, storage_path in selected.get(table, []):
            if _unlink_under_root(root, storage_path):
                result["deleted_blobs"][table] += 1
            else:
                result["missing_blobs"][table] += 1
    return result


def cleanup_orphan_private_file_blobs(settings: dict | None = None, *, limit: int = 500) -> dict:
    """Delete old unreferenced encrypted private-file blobs from upload roots.

    Only immediate generated `*.bin` children of the configured DM/group private
    upload roots are considered, and only after a grace window.  The grace window
    avoids racing an upload whose file was written before its DB row committed.

    The important safety rule is: never infer "orphan" from a partial table scan.
    The janitor first collects a bounded set of old on-disk candidate file IDs,
    then asks the matching DB table about exactly those IDs, and only deletes the
    candidates absent from that fresh lookup.
    """
    settings = settings or {}
    result = {
        "ok": True,
        "enabled": _truthy(settings.get("cleanup_orphan_private_file_blobs_enabled"), True),
        "grace_minutes": _coerce_minutes(settings, "orphan_private_file_grace_minutes", 60, minimum=5, maximum=24 * 60 * 30),
        "dm_files": _empty_orphan_blob_result(),
        "group_files": _empty_orphan_blob_result(),
    }
    if not result["enabled"]:
        result["skipped"] = "orphan private-file blob cleanup disabled"
        return result

    limit = _coerce_limit(limit)
    half_limit = max(1, limit // 2)
    roots = {
        "dm_files": _upload_root(settings, "dm_upload_root", "dm_files"),
        "group_files": _upload_root(settings, "group_upload_root", "group_files"),
    }
    candidates: dict[str, dict[str, str]] = {}
    for table, root in roots.items():
        result[table], candidates[table] = _collect_old_private_blob_candidates(
            root,
            max_files=half_limit,
            grace_minutes=int(result["grace_minutes"]),
        )

    if not any(candidates.values()):
        return result

    known: dict[str, set[str]] = {"dm_files": set(), "group_files": set()}
    conn, from_pool = _acquire_conn()
    try:
        with conn.cursor() as cur:
            for table in ("dm_files", "group_files"):
                ids = sorted(candidates.get(table, {}).keys())
                if not ids:
                    continue
                try:
                    cur.execute(f"SELECT file_id FROM {table} WHERE file_id = ANY(%s);", (ids,))
                    known[table] = {str(r[0]) for r in (cur.fetchall() or []) if r and r[0]}
                except Exception as exc:
                    # Fail closed per table.  A missing table/column, aborted
                    # transaction, or DB outage must not cause on-disk deletion.
                    try:
                        conn.rollback()
                    except Exception:
                        pass
                    result["ok"] = False
                    result[table]["db_lookup_failed"] = 1
                    result[table]["db_error"] = type(exc).__name__
                    logging.exception("orphan private-file blob DB lookup failed for %s", table)
                    known[table] = set(candidates.get(table, {}).keys())
        try:
            conn.rollback()
        except Exception:
            pass
    except Exception as exc:
        try:
            conn.rollback()
        except Exception:
            pass
        result["ok"] = False
        result["error"] = type(exc).__name__
        logging.exception("cleanup_orphan_private_file_blobs DB lookup failed")
        # No DB confirmation means no deletion.
        return result
    finally:
        _release_conn(conn, from_pool)

    for table, root in roots.items():
        if result[table].get("db_lookup_failed"):
            continue
        result[table] = _delete_confirmed_orphan_private_blobs(
            root,
            result[table],
            candidates.get(table, {}),
            known.get(table, set()),
            grace_minutes=int(result["grace_minutes"]),
        )
    return result
