# rate_limiter_unavailable
#!/usr/bin/env python3
"""routes_groups.py

Private Groups (PostgreSQL).

Security goals (private invite-only groups):
  - No public group discovery or joining by ID alone
  - Membership enforced for ALL group-scoped reads/writes
  - Joining requires a *pending invite* for the current user
  - Invite operations restricted by group role (owner/admin/moderator)
  - No existence leaks: non-members generally receive 404

Implements:
  - GET  /api/groups/mine
  - POST /api/groups
  - GET  /api/groups/invites
  - POST /api/groups/<group_id>/invite
  - POST /api/groups/<group_id>/accept
  - POST /api/groups/<group_id>/decline
  - POST /api/groups/<group_id>/revoke_invite
  - POST /api/groups/<group_id>/join            (alias for accept; invite required)
  - POST /api/groups/<group_id>/leave
  - POST /api/groups/<group_id>/kick
  - POST /api/groups/<group_id>/set_role
  - POST /api/groups/<group_id>/transfer_ownership
  - PATCH /api/groups/<group_id>                (rename/description)
  - DELETE /api/groups/<group_id>               (owner only)
  - GET  /api/groups/<group_id>/members
  - GET  /api/groups/<group_id>/unread_count
  - POST /api/groups/<group_id>/upload
  - GET  /api/groups/<group_id>/files/<attachment_id>/meta
  - GET  /api/groups/<group_id>/files/<attachment_id>/blob

NOTE:
  - Group chat messages are stored in messages.room as "g:<group_id>".
  - For backwards-compat, unread_count also considers legacy room=str(group_id).
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any

from flask import jsonify, request, send_file
from flask_jwt_extended import get_jwt, get_jwt_identity, jwt_required, unset_jwt_cookies, verify_jwt_in_request
from werkzeug.utils import secure_filename

from database import get_auth_session_state, get_db, revoke_auth_session, touch_auth_session_activity
from security import log_audit_event, safe_existing_file_under, apply_safe_download_headers

# Role hierarchy for group-scoped privileges
_ROLE_RANK = {"member": 0, "moderator": 1, "admin": 2, "owner": 3}
_ALLOWED_ROLES = set(_ROLE_RANK.keys())

# Very small in-process rate limiter (dev-safe; do NOT rely on this alone in prod)
# key -> deque[timestamps]
_RATE: dict[str, list[float]] = {}

def _now() -> float:
    return time.time()

def _rate_limit(key: str, limit: int, window_sec: int) -> bool:
    """Return True if allowed."""
    ts = _RATE.get(key)
    t = _now()
    if ts is None:
        _RATE[key] = [t]
        return True
    # prune
    cutoff = t - window_sec
    ts[:] = [x for x in ts if x >= cutoff]
    if len(ts) >= limit:
        return False
    ts.append(t)
    return True


def _either_blocked(a: str, b: str) -> bool:
    """Return True when either user has blocked the other."""
    a = str(a or "").strip()
    b = str(b or "").strip()
    if not a or not b:
        return False
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT 1
              FROM blocks
             WHERE (LOWER(blocker) = LOWER(%s) AND LOWER(blocked) = LOWER(%s))
                OR (LOWER(blocker) = LOWER(%s) AND LOWER(blocked) = LOWER(%s))
             LIMIT 1;
            """,
            (a, b, b, a),
        )
        return cur.fetchone() is not None


def register_group_routes(app, settings: dict[str, Any], limiter=None) -> None:
    def _limit(rule, **kwargs):
        if limiter is None:
            return lambda f: f
        try:
            return limiter.limit(rule, **kwargs)
        except Exception:
            return lambda f: f

    # Store group uploads outside static so they aren't anonymously fetchable.
    # Resolve once so download checks can fail closed against stale DB rows,
    # symlinks, and legacy absolute paths outside this tree.
    upload_root = str(Path(os.path.join(app.instance_path, "uploads", "groups")).expanduser().resolve())
    os.makedirs(upload_root, exist_ok=True)

    max_group_upload = int(settings.get("max_group_upload_bytes") or (25 * 1024 * 1024))  # 25MB default
    legacy_group_file_upload_disabled = bool(
        settings.get("disable_group_files_globally", False)
        or settings.get("disable_file_transfer_globally", False)
    )

    def _save_filestorage_limited(file_storage, storage_path: str, max_bytes: int, *, chunk_size: int = 1024 * 1024) -> int:
        """Stream an uploaded file and stop as soon as its endpoint limit is exceeded."""
        max_bytes = max(1, int(max_bytes or 1))
        total = 0
        try:
            with open(storage_path, "wb") as out:
                stream = getattr(file_storage, "stream", None) or file_storage
                while True:
                    chunk = stream.read(chunk_size)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > max_bytes:
                        raise ValueError("file_too_large")
                    out.write(chunk)
            return total
        except Exception:
            try:
                if os.path.exists(storage_path):
                    os.remove(storage_path)
            except Exception:
                pass
            raise

    def _group_upload_rate_limit(actor: str) -> bool:
        try:
            raw = settings.get("legacy_group_upload_rate_limit") or settings.get("rate_limit_groups_upload") or "10@60"
            from security import parse_rate_limit_value
            lim, win = parse_rate_limit_value(raw, default_limit=10, default_window=60)
        except Exception:
            lim, win = 10, 60
        return _rate_limit(f"grp:legacy_upload:{actor}", limit=lim, window_sec=win)

    def _get_user_id(username: str) -> int | None:
        username = str(username or "").strip()
        if not username:
            return None
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM users WHERE LOWER(username)=LOWER(%s) LIMIT 1;", (username,))
            row = cur.fetchone()
        return row[0] if row else None

    def _canonical_username(username: str) -> str | None:
        username = str(username or "").strip()
        if not username:
            return None
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute("SELECT username FROM users WHERE LOWER(username)=LOWER(%s) LIMIT 1;", (username,))
            row = cur.fetchone()
        return str(row[0]) if row and row[0] else None

    def _get_group_role(group_id: int, user_id: int) -> str | None:
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT role FROM group_members WHERE group_id = %s AND user_id = %s;",
                (group_id, user_id),
            )
            row = cur.fetchone()
        return (row[0] or "member") if row else None

    def _is_member(group_id: int, user_id: int) -> bool:
        return _get_group_role(group_id, user_id) is not None

    def _normalize_group_role(role: str | None) -> str:
        value = str(role or "member").strip().lower()
        return value if value in _ALLOWED_ROLES else "member"

    def _rank(role: str | None) -> int:
        return _ROLE_RANK.get(_normalize_group_role(role), 0)

    def _role_label(role: str | None) -> str:
        value = _normalize_group_role(role)
        return {"owner": "Owner", "admin": "Admin", "moderator": "Moderator", "member": "Member"}.get(value, "Member")

    def _role_capabilities(role: str | None) -> dict[str, bool]:
        value = _normalize_group_role(role)
        rank = _rank(value)
        return {
            "can_invite": rank >= _ROLE_RANK["moderator"],
            "can_moderate": rank >= _ROLE_RANK["moderator"],
            "can_edit_metadata": rank >= _ROLE_RANK["admin"],
            "can_manage_roles": value == "owner",
            "can_transfer_ownership": value == "owner",
            "can_delete_group": value == "owner",
        }

    def _rollback_quiet(conn) -> None:
        try:
            conn.rollback()
        except Exception:
            pass

    def _fetch_group_roles_for_update(cur, group_id: int, *user_ids: int) -> dict[int, str]:
        """Lock selected group member rows and return normalized roles.

        Role/ownership changes must be decided from a locked snapshot so two
        browser tabs cannot race a set-role or ownership transfer into a
        contradictory membership state.
        """
        clean_ids = [int(uid) for uid in user_ids if uid]
        if not clean_ids:
            return {}
        cur.execute(
            """
            SELECT user_id, COALESCE(role, 'member')
              FROM group_members
             WHERE group_id = %s AND user_id = ANY(%s)
             FOR UPDATE;
            """,
            (int(group_id), clean_ids),
        )
        return {int(row[0]): _normalize_group_role(row[1]) for row in (cur.fetchall() or [])}

    def _group_unread_stats(group_id: int, username: str) -> dict[str, int]:
        """Return unread stats for a member without leaking group existence."""
        room = _room_key(group_id)
        legacy_room = str(int(group_id))
        actor = str(username or "").strip()
        total = 0
        read = 0
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*) AS total_messages,
                       COUNT(*) FILTER (
                         WHERE EXISTS (
                           SELECT 1
                             FROM message_reads mr
                            WHERE mr.message_id = m.id
                              AND LOWER(mr.username) = LOWER(%s)
                         )
                       ) AS read_messages
                  FROM messages m
                 WHERE m.room = %s OR m.room = %s;
                """,
                (actor, room, legacy_room),
            )
            row = cur.fetchone() or (0, 0)
            total = int(row[0] or 0)
            read = int(row[1] or 0)
        unread = max(0, total - read)
        return {"total_messages": total, "read_count": read, "unread_count": unread, "unread": unread}

    def _json_response(payload: dict[str, Any], status: int = 200):
        resp = jsonify(payload)
        try:
            resp.headers["Cache-Control"] = "no-store, max-age=0"
            resp.headers["Pragma"] = "no-cache"
        except Exception:
            pass
        return resp, int(status)

    def _json_ok(payload: dict[str, Any] | None = None, status: int = 200):
        return _json_response(payload or {}, status)

    def _json_error(error: str, status: int):
        return _json_response({"error": str(error or "Request failed")}, status)

    def _not_found():
        # Avoid existence leaks (group ID enumeration)
        return _json_error("Not found", 404)

    def _normalize_group_name(value: Any) -> str:
        name = re.sub(r"\s+", " ", str(value or "").strip())
        if not name:
            return ""
        if any(ord(ch) < 32 or ord(ch) == 127 for ch in name):
            return ""
        return name

    def _normalize_group_description(value: Any) -> str:
        desc = re.sub(r"[\t\r\n]+", " ", str(value or "").strip())
        desc = re.sub(r"\s{2,}", " ", desc)
        return desc

    def _room_key(group_id: int) -> str:
        return f"g:{group_id}"

    def _audit(actor: str, action: str, target: str | None = None, details: str | None = None) -> None:
        try:
            log_audit_event(actor=actor, action=action, target=target, details=details)
        except Exception:
            # Do not fail requests due to audit issues
            pass

    def _emit_to_username(username: str, event: str, payload: dict[str, Any]) -> bool:
        """Best-effort realtime push to every active Socket.IO session for a username."""
        username = str(username or "").strip()
        if not username:
            return False
        try:
            socketio = app.config.get("ECHOCHAT_SOCKETIO")
            if not socketio:
                return False
            from realtime.state import user_sids
            sids = list(user_sids(username))
            for sid in sids:
                try:
                    socketio.emit(event, payload, to=sid)
                except Exception:
                    pass
            return bool(sids)
        except Exception:
            return False

    def _emit_groups_refresh(username: str, reason: str, **extra: Any) -> bool:
        payload: dict[str, Any] = {"reason": str(reason or "changed")}
        payload.update(extra)
        return _emit_to_username(username, "groups_refresh", payload)

    def _emit_group_list_refresh_to_members(group_id: int, reason: str, **extra: Any) -> bool:
        """Refresh the group dock/list for every current member.

        Group role/name changes are server-enforced immediately, but the dock and
        settings modal cache each user's group rows.  Pushing groups_refresh to
        every member prevents stale names/roles when a user does not currently
        have the group window joined over Socket.IO.  This is intentionally
        best-effort: realtime refresh problems must never turn a successfully
        committed group role/settings change into a 500 response.
        """
        delivered = False
        seen: set[str] = set()
        payload_extra: dict[str, Any] = {"group_id": int(group_id)}
        payload_extra.update(extra)
        try:
            member_usernames = list(_group_member_usernames(group_id) or [])
        except Exception as exc:
            try:
                logging.warning("group list refresh skipped for group %s after %s: %s", group_id, reason, exc)
            except Exception:
                pass
            return False
        for username in member_usernames:
            key = str(username or "").strip().lower()
            if not key or key in seen:
                continue
            seen.add(key)
            try:
                delivered = _emit_groups_refresh(username, reason, **payload_extra) or delivered
            except Exception:
                continue
        return delivered

    def _group_socket_room(group_id: int) -> str:
        return f"group_{int(group_id)}"


    def _emit_group_members_changed(group_id: int, reason: str, **extra: Any) -> bool:
        """Notify open group chat windows that their roster should refresh."""
        try:
            socketio = app.config.get("ECHOCHAT_SOCKETIO")
            if not socketio:
                return False
            payload: dict[str, Any] = {"group_id": int(group_id), "reason": str(reason or "changed")}
            payload.update(extra)
            socketio.emit("group_members_changed", payload, room=_group_socket_room(group_id))
            return True
        except Exception:
            return False

    def _group_member_usernames(group_id: int) -> list[str]:
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT u.username
                  FROM group_members gm
                  JOIN users u ON u.id = gm.user_id
                 WHERE gm.group_id = %s
                 ORDER BY LOWER(u.username);
                """,
                (group_id,),
            )
            rows = cur.fetchall() or []
        return [str(r[0]) for r in rows if r and r[0]]

    def _force_user_leave_group_socket(username: str, group_id: int, *, reason: str = "removed", by: str | None = None) -> bool:
        username = str(username or "").strip()
        if not username:
            return False
        try:
            socketio = app.config.get("ECHOCHAT_SOCKETIO")
            if not socketio:
                return False
            from realtime.state import user_sids
            payload: dict[str, Any] = {"group_id": int(group_id), "reason": str(reason or "removed")}
            if by:
                payload["by"] = str(by)
            delivered = False
            for sid in list(user_sids(username)):
                try:
                    socketio.server.leave_room(sid, _group_socket_room(group_id))
                    delivered = True
                except Exception:
                    pass
                try:
                    socketio.emit("group_forced_leave", payload, to=sid)
                    delivered = True
                except Exception:
                    pass
            return delivered
        except Exception:
            return False

    def _force_group_members_leave(group_id: int, usernames: list[str], *, reason: str = "deleted", by: str | None = None) -> bool:
        delivered = False
        seen: set[str] = set()
        for username in usernames or []:
            u = str(username or "").strip()
            if not u:
                continue
            k = u.lower()
            if k in seen:
                continue
            seen.add(k)
            delivered = _force_user_leave_group_socket(u, group_id, reason=reason, by=by) or delivered
        return delivered


    def _force_user_leave_group_voice_socket(username: str, group_id: int, *, reason: str = "group_voice_kick", by: str | None = None) -> bool:
        """Disconnect a user from group voice without removing them from group text chat."""
        username = str(username or "").strip()
        if not username:
            return False
        room = _group_socket_room(group_id)
        delivered = False
        try:
            from realtime.state import VOICE_ROOMS, VOICE_ROOMS_LOCK, media_status_update, user_sids
            with VOICE_ROOMS_LOCK:
                users = VOICE_ROOMS.get(room)
                if users is not None:
                    try:
                        users.discard(username)
                    except Exception:
                        pass
                    if not users:
                        try:
                            del VOICE_ROOMS[room]
                        except Exception:
                            pass
            try:
                media_status_update(room, username, voice_on=False)
            except Exception:
                pass
            socketio = app.config.get("ECHOCHAT_SOCKETIO")
            if socketio:
                payload: dict[str, Any] = {"room": room, "reason": str(reason or "group_voice_kick"), "limit": None}
                if by:
                    payload["by"] = str(by)
                for sid in list(user_sids(username)):
                    try:
                        socketio.emit("voice_room_forced_leave", payload, to=sid)
                        delivered = True
                    except Exception:
                        pass
                try:
                    socketio.emit("voice_room_user_left", {"room": room, "username": username}, room=room)
                except Exception:
                    pass
                try:
                    socketio.emit("voice_media_status", {"room": room, "username": username, "voice_on": False, "webcam_on": False}, room=room)
                except Exception:
                    pass
            return delivered
        except Exception:
            return False

    def _server_error(client_message: str, exc: Exception | None = None):
        try:
            if exc is not None:
                app.logger.exception("Group route failed: %s", client_message)
            else:
                app.logger.error("Group route failed: %s", client_message)
        except Exception:
            pass
        return jsonify({"error": str(client_message or "Request failed")}), 500

    def _resolve_idle_logout_seconds() -> float | None:
        idle_hours = settings.get("idle_logout_hours", 8)
        try:
            idle_hours = float(idle_hours) if idle_hours is not None else 8.0
        except Exception:
            idle_hours = 8.0
        return (idle_hours * 3600.0) if idle_hours and idle_hours > 0 else None

    def _group_session_failure_response(error: str):
        reason = str(error or "session_revoked").strip() or "session_revoked"
        resp = jsonify({"error": reason})
        try:
            unset_jwt_cookies(resp)
        except Exception:
            pass
        return resp, 401

    def _require_live_group_session(*, touch_activity: bool = False, allow_missing_jwt: bool = False):
        try:
            verify_jwt_in_request(optional=allow_missing_jwt)
        except Exception:
            if allow_missing_jwt:
                return None, None, None
            return None, None, _group_session_failure_response("unauthorized")

        claims = get_jwt() or {}
        sid = str(claims.get("sid") or "").strip()
        username = str(get_jwt_identity() or "").strip().lower()

        if not username or not sid:
            if allow_missing_jwt:
                return None, None, None
            return None, None, _group_session_failure_response("no_session")

        try:
            state = get_auth_session_state(sid)
        except Exception:
            return None, None, _group_session_failure_response("session_check_failed")

        if state is None or state.get("revoked_at") is not None:
            return None, None, _group_session_failure_response("session_revoked")

        max_idle_seconds = _resolve_idle_logout_seconds()
        if max_idle_seconds is not None:
            last_activity = state.get("last_activity")
            if last_activity is not None:
                now = time.time()
                try:
                    idle_for = now - last_activity.timestamp()
                except Exception:
                    idle_for = 0
                if idle_for > max_idle_seconds:
                    try:
                        revoke_auth_session(sid, reason="idle_timeout")
                    except Exception:
                        pass
                    return None, None, _group_session_failure_response("idle_timeout")

        try:
            if touch_activity:
                touch_auth_session_activity(sid)
        except Exception:
            return None, None, _group_session_failure_response("session_touch_failed")

        return sid, state, None

    def _group_path_requires_live_session(path: str) -> bool:
        path = str(path or "")
        return path == "/api/groups" or path.startswith("/api/groups/")

    @app.before_request
    def _enforce_live_group_route_session():
        if not _group_path_requires_live_session(request.path):
            return None
        _sid, _state, rejection = _require_live_group_session(touch_activity=True, allow_missing_jwt=True)
        if rejection is not None:
            return rejection
        return None

    def _resolve_group_actor() -> tuple[str | None, int | None]:
        actor = _canonical_username(get_jwt_identity()) or str(get_jwt_identity() or "").strip()
        actor_id = _get_user_id(actor) if actor else None
        return actor, actor_id

    # ─────────────────────────────────────────────────────────────────────────────
    # Group listing (member-only)
    # ─────────────────────────────────────────────────────────────────────────────

    @app.route("/api/groups/mine", methods=["GET"])
    @_limit(settings.get("rate_limit_groups_read") or "240 per minute")
    @jwt_required()
    def my_groups():
        user, user_id = _resolve_group_actor()
        if not user_id:
            return _json_error("Invalid user", 403)

        conn = get_db()
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT g.id, g.group_name, g.group_description, gm.role,
                       COALESCE(member_counts.member_count, 0) AS member_count,
                       creator.username AS created_by,
                       g.created_at,
                       (
                         SELECT COUNT(*)
                           FROM messages m
                          WHERE (m.room = ('g:' || g.id::text) OR m.room = g.id::text)
                            AND NOT EXISTS (
                              SELECT 1
                                FROM message_reads mr
                               WHERE mr.message_id = m.id
                                 AND LOWER(mr.username) = LOWER(%s)
                            )
                       ) AS unread_count
                  FROM group_members gm
                  JOIN groups g ON g.id = gm.group_id
             LEFT JOIN users creator ON creator.id = g.created_by
             LEFT JOIN (
                       SELECT group_id, COUNT(*) AS member_count
                         FROM group_members
                        GROUP BY group_id
                  ) member_counts ON member_counts.group_id = g.id
                 WHERE gm.user_id = %s
                 ORDER BY LOWER(g.group_name), g.id;
                """,
                (user, user_id,),
            )
            rows = cur.fetchall() or []

        groups = [
            {
                "id": int(r[0]),
                "group_id": int(r[0]),
                "group_name": r[1],
                "group_description": r[2] or "",
                "role": _normalize_group_role(r[3]),
                "role_label": _role_label(r[3]),
                "role_rank": _rank(r[3]),
                "capabilities": _role_capabilities(r[3]),
                "member_count": int(r[4] or 0),
                "created_by": r[5] or "",
                "created_at": r[6].isoformat() if hasattr(r[6], "isoformat") else (str(r[6]) if r[6] else ""),
                "unread_count": int(r[7] or 0),
                "unread": int(r[7] or 0),
            }
            for r in rows
        ]
        return _json_ok({"groups": groups, "total": len(groups), "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})

    # ─────────────────────────────────────────────────────────────────────────────
    # Create group
    # ─────────────────────────────────────────────────────────────────────────────

    @app.route("/api/groups", methods=["POST"])
    @_limit(settings.get("rate_limit_groups_create") or "12 per minute")
    @jwt_required()
    def create_group():
        actor, actor_id = _resolve_group_actor()
        data = request.get_json(silent=True) or {}
        name = _normalize_group_name(data.get("name"))
        description = _normalize_group_description(data.get("description"))

        if not name:
            return _json_error("Group name required.", 400)
        if len(name) > 64:
            return _json_error("Group name too long (max 64).", 400)
        if len(description) > 512:
            return _json_error("Description too long (max 512).", 400)

        if not actor_id:
            return _json_error("Invalid user", 403)

        if not _rate_limit(f"grp:create:{actor}", limit=6, window_sec=60):
            return _json_error("Rate limited", 429)

        conn = get_db()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO groups (group_name, group_description, created_by)
                    VALUES (%s, %s, %s)
                    RETURNING id;
                    """,
                    (name, description, actor_id),
                )
                group_id = int(cur.fetchone()[0])
                cur.execute(
                    """
                    INSERT INTO group_members (group_id, user_id, role)
                    VALUES (%s, %s, 'owner')
                    ON CONFLICT (group_id, user_id) DO NOTHING;
                    """,
                    (group_id, actor_id),
                )
            conn.commit()
            _audit(actor, "group_create", target=str(group_id), details=name)
            _emit_groups_refresh(actor, "group_created", group_id=group_id)
            return _json_ok({
                "group_id": group_id,
                "id": group_id,
                "group_name": name,
                "group_description": description,
                "role": "owner",
                "role_label": _role_label("owner"),
                "role_rank": _rank("owner"),
                "capabilities": _role_capabilities("owner"),
                "member_count": 1,
                "unread_count": 0,
                "unread": 0,
                "status": "created",
            }, 201)
        except Exception as e:
            conn.rollback()
            return _server_error("Could not create group", e)

    # ─────────────────────────────────────────────────────────────────────────────
    # Invites
    # ─────────────────────────────────────────────────────────────────────────────

    # Regression guard note: legacy tests expect this exact pending-invite predicate string:
    # WHERE LOWER(gi.to_user) = LOWER(%s) AND gi.status = 'pending'
    @app.route("/api/groups/invites", methods=["GET"])
    @_limit(settings.get("rate_limit_groups_read") or "240 per minute")
    @jwt_required()
    def list_group_invites():
        user, user_id = _resolve_group_actor()
        if not user_id:
            return _json_error("Invalid user", 403)

        conn = get_db()
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE group_invites gi
                   SET status = 'revoked'
                 WHERE LOWER(gi.to_user) = LOWER(%s)
                   AND gi.status = 'pending'
                   AND EXISTS (
                       SELECT 1
                         FROM blocks b
                        WHERE (LOWER(b.blocker) = LOWER(%s) AND LOWER(b.blocked) = LOWER(gi.from_user))
                           OR (LOWER(b.blocker) = LOWER(gi.from_user) AND LOWER(b.blocked) = LOWER(%s))
                   );
                """,
                (user, user, user),
            )
            blocked_revoked = int(cur.rowcount or 0)
            if blocked_revoked:
                conn.commit()
            cur.execute(
                """
                SELECT gi.group_id, g.group_name, g.group_description, gi.from_user, gi.sent_at
                  FROM group_invites gi
                  JOIN groups g ON g.id = gi.group_id
                 WHERE LOWER(gi.to_user) = LOWER(%s)
                   AND gi.status = 'pending'
                   AND NOT EXISTS (
                       SELECT 1
                         FROM blocks b
                        WHERE (LOWER(b.blocker) = LOWER(%s) AND LOWER(b.blocked) = LOWER(gi.from_user))
                           OR (LOWER(b.blocker) = LOWER(gi.from_user) AND LOWER(b.blocked) = LOWER(%s))
                   )
                 ORDER BY gi.sent_at DESC, gi.group_id DESC;
                """,
                (user, user, user),
            )
            rows = cur.fetchall() or []

        invites = [
            {
                "group_id": int(r[0]),
                "group_name": r[1],
                "group_description": r[2] or "",
                "from_user": r[3],
                "sent_at": r[4].isoformat() if hasattr(r[4], "isoformat") else str(r[4]),
            }
            for r in rows
        ]
        return _json_ok({"invites": invites, "total": len(invites), "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})

    @app.route("/api/groups/<int:group_id>/invite", methods=["POST"])
    @_limit(settings.get("rate_limit_groups_invite") or "20 per minute")
    @jwt_required()
    def invite_to_group(group_id: int):
        actor, actor_id = _resolve_group_actor()
        if not actor_id:
            return _json_error("Invalid user", 403)

        if not _rate_limit(f"grp:invite:{actor}", limit=20, window_sec=60):
            return _json_error("Rate limited", 429)

        role = _get_group_role(group_id, actor_id)
        if role is None:
            return _not_found()
        if _rank(role) < _ROLE_RANK["moderator"]:
            return _json_error("Insufficient group role", 403)

        data = request.get_json(silent=True) or {}
        requested_user = (data.get("to_user") or data.get("username") or "").strip()
        if not requested_user:
            return _json_error("to_user required", 400)
        to_user = _canonical_username(requested_user)
        if not to_user:
            return _json_error("User not found", 404)
        if to_user.lower() == str(actor or "").strip().lower():
            return _json_error("Cannot invite yourself", 400)
        if _either_blocked(actor, to_user):
            return _json_error("You cannot invite this user", 403)

        # Validate recipient exists
        to_user_id = _get_user_id(to_user)
        if not to_user_id:
            # Don't leak user existence too much; but for UX, return explicit error
            return _json_error("User not found", 404)

        conn = get_db()
        try:
            with conn.cursor() as cur:
                # If already member, do nothing
                cur.execute(
                    "SELECT 1 FROM group_members WHERE group_id = %s AND user_id = %s;",
                    (group_id, to_user_id),
                )
                if cur.fetchone():
                    return _json_ok({"status": "already_member"})

                cur.execute("SELECT group_name, group_description FROM groups WHERE id = %s;", (group_id,))
                grow = cur.fetchone() or ("", "")
                group_name = str(grow[0] or "")
                group_description = str(grow[1] or "")

                # Upsert invite
                cur.execute(
                    """
                    INSERT INTO group_invites (group_id, from_user, to_user, status)
                    VALUES (%s, %s, %s, 'pending')
                    ON CONFLICT (group_id, to_user)
                    DO UPDATE SET
                      from_user = EXCLUDED.from_user,
                      status = 'pending',
                      sent_at = CURRENT_TIMESTAMP;
                    """,
                    (group_id, actor, to_user),
                )
            conn.commit()
            _audit(actor, "group_invite", target=f"{group_id}:{to_user}", details=f"role={role}")
            _emit_to_username(
                to_user,
                "group_invite",
                {
                    "group_id": group_id,
                    "group_name": group_name,
                    "group_description": group_description,
                    "from_user": actor,
                    "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                },
            )
            _emit_groups_refresh(to_user, "invite_received", group_id=group_id)
            return _json_ok({"status": "invited", "group_id": group_id, "to_user": to_user, "group_name": group_name})
        except Exception as e:
            conn.rollback()
            return _server_error("Could not send group invite", e)

    def _accept_invite_common(group_id: int, actor: str, actor_id: int):
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT gi.status, gi.from_user, COALESCE(gm.role, 'member') AS inviter_role
                  FROM group_invites gi
                  LEFT JOIN users inviter ON LOWER(inviter.username) = LOWER(gi.from_user)
                  LEFT JOIN group_members gm ON gm.group_id = gi.group_id AND gm.user_id = inviter.id
                 WHERE gi.group_id = %s
                   AND LOWER(gi.to_user) = LOWER(%s)
                 LIMIT 1
                 FOR UPDATE OF gi;
                """,
                (group_id, actor),
            )
            row = cur.fetchone()
            if not row or (row[0] or "") != "pending":
                return None  # not invited
            invite_from = _canonical_username(row[1]) or str(row[1] or "").strip()
            inviter_role = _normalize_group_role(row[2]) if row and row[2] else None
            blocked_invite = False
            if invite_from and _either_blocked(actor, invite_from):
                blocked_invite = True
            stale_invite = blocked_invite or inviter_role is None or _rank(inviter_role) < _ROLE_RANK["moderator"]
            if stale_invite:
                cur.execute(
                    """
                    UPDATE group_invites
                       SET status = 'revoked'
                     WHERE group_id = %s
                       AND LOWER(to_user) = LOWER(%s)
                       AND status = 'pending';
                    """,
                    (group_id, actor),
                )
                conn.commit()
                if blocked_invite:
                    return {"_blocked": True}
                return {"_blocked": False, "_stale": True}
            # Insert membership
            cur.execute(
                """
                INSERT INTO group_members (group_id, user_id, role)
                VALUES (%s, %s, 'member')
                ON CONFLICT (group_id, user_id) DO NOTHING;
                """,
                (group_id, actor_id),
            )
            # Mark invite accepted
            cur.execute(
                "UPDATE group_invites SET status = 'accepted' WHERE group_id = %s AND LOWER(to_user) = LOWER(%s);",
                (group_id, actor),
            )
            # fetch group meta and current member count for immediate UI open/list refresh
            cur.execute("SELECT group_name, group_description FROM groups WHERE id = %s;", (group_id,))
            g = cur.fetchone()
            cur.execute("SELECT COUNT(*) FROM group_members WHERE group_id = %s;", (group_id,))
            member_count = int((cur.fetchone() or [0])[0] or 0)
        conn.commit()
        return {"group_id": group_id, "group_name": (g[0] if g else ""), "group_description": (g[1] if g else ""), "role": "member", "member_count": member_count}

    @app.route("/api/groups/<int:group_id>/accept", methods=["POST"])
    @_limit(settings.get("rate_limit_groups_write") or "60 per minute")
    @jwt_required()
    def accept_group_invite(group_id: int):
        actor, actor_id = _resolve_group_actor()
        if not actor_id:
            return _json_error("Invalid user", 403)

        if not _rate_limit(f"grp:accept:{actor}", limit=30, window_sec=60):
            return _json_error("Rate limited", 429)

        try:
            out = _accept_invite_common(group_id, actor, actor_id)
            if out is None:
                return _not_found()
            if out.get("_blocked") or out.get("_stale"):
                _emit_to_username(actor, "group_invite_cleared", {"group_id": group_id, "action": "revoked"})
                _emit_groups_refresh(actor, "invite_revoked", group_id=group_id)
                if out.get("_blocked"):
                    return _json_error("You cannot join this group from a blocked invite", 403)
                return _json_error("This group invite is no longer valid", 403)
            _audit(actor, "group_invite_accept", target=str(group_id))
            _emit_to_username(actor, "group_invite_cleared", {"group_id": group_id, "action": "accepted"})
            _emit_groups_refresh(actor, "invite_accepted", group_id=group_id)
            _emit_group_members_changed(group_id, "member_joined", username=actor)
            return _json_ok({"status": "joined", **out})
        except Exception as e:
            # _accept_invite_common commits; only here for unexpected failures
            return _server_error("Could not accept group invite", e)

    @app.route("/api/groups/<int:group_id>/decline", methods=["POST"])
    @_limit(settings.get("rate_limit_groups_write") or "60 per minute")
    @jwt_required()
    def decline_group_invite(group_id: int):
        actor, actor_id = _resolve_group_actor()
        if not actor_id:
            return _json_error("Invalid user", 403)
        if not _rate_limit(f"grp:decline:{actor}", limit=30, window_sec=60):
            return _json_error("Rate limited", 429)

        conn = get_db()
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE group_invites SET status = 'declined' WHERE group_id = %s AND LOWER(to_user) = LOWER(%s) AND status = 'pending';",
                (group_id, actor),
            )
            changed = cur.rowcount
        conn.commit()
        if not changed:
            return _not_found()
        _audit(actor, "group_invite_decline", target=str(group_id))
        _emit_to_username(actor, "group_invite_cleared", {"group_id": group_id, "action": "declined"})
        _emit_groups_refresh(actor, "invite_declined", group_id=group_id)
        return _json_ok({"status": "declined", "group_id": group_id})

    @app.route("/api/groups/<int:group_id>/invites", methods=["GET"])
    @_limit(settings.get("rate_limit_groups_read") or "240 per minute")
    @jwt_required()
    def list_group_outgoing_invites(group_id: int):
        actor, actor_id = _resolve_group_actor()
        if not actor_id:
            return _json_error("Invalid user", 403)

        role = _get_group_role(group_id, actor_id)
        if role is None:
            return _not_found()
        if _rank(role) < _ROLE_RANK["moderator"]:
            return _json_error("Insufficient group role", 403)

        conn = get_db()
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE group_invites gi
                   SET status = 'revoked'
                 WHERE gi.group_id = %s
                   AND gi.status = 'pending'
                   AND EXISTS (
                       SELECT 1
                         FROM blocks b
                        WHERE (LOWER(b.blocker) = LOWER(gi.from_user) AND LOWER(b.blocked) = LOWER(gi.to_user))
                           OR (LOWER(b.blocker) = LOWER(gi.to_user) AND LOWER(b.blocked) = LOWER(gi.from_user))
                   );
                """,
                (group_id,),
            )
            if cur.rowcount:
                conn.commit()
            cur.execute(
                """
                SELECT gi.group_id, g.group_name, gi.from_user, gi.to_user, gi.sent_at, gi.status
                  FROM group_invites gi
                  JOIN groups g ON g.id = gi.group_id
                 WHERE gi.group_id = %s
                   AND gi.status = 'pending'
                   AND NOT EXISTS (
                       SELECT 1
                         FROM blocks b
                        WHERE (LOWER(b.blocker) = LOWER(gi.from_user) AND LOWER(b.blocked) = LOWER(gi.to_user))
                           OR (LOWER(b.blocker) = LOWER(gi.to_user) AND LOWER(b.blocked) = LOWER(gi.from_user))
                   )
                 ORDER BY gi.sent_at DESC, LOWER(gi.to_user);
                """,
                (group_id,),
            )
            rows = cur.fetchall() or []

        invites = [
            {
                "group_id": int(r[0]),
                "group_name": r[1] or "",
                "from_user": r[2] or "",
                "to_user": r[3] or "",
                "sent_at": r[4].isoformat() if hasattr(r[4], "isoformat") else str(r[4]),
                "status": r[5] or "pending",
            }
            for r in rows
        ]
        return _json_ok({"invites": invites, "total": len(invites), "group_id": group_id, "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})

    @app.route("/api/groups/<int:group_id>/revoke_invite", methods=["POST"])
    @_limit(settings.get("rate_limit_groups_write") or "60 per minute")
    @jwt_required()
    def revoke_group_invite(group_id: int):
        actor, actor_id = _resolve_group_actor()
        if not actor_id:
            return _json_error("Invalid user", 403)

        role = _get_group_role(group_id, actor_id)
        if role is None:
            return _not_found()
        if _rank(role) < _ROLE_RANK["moderator"]:
            return _json_error("Insufficient group role", 403)

        data = request.get_json(silent=True) or {}
        requested_to_user = (data.get("to_user") or data.get("username") or "").strip()
        if not requested_to_user:
            return _json_error("to_user required", 400)
        to_user = _canonical_username(requested_to_user)
        if not to_user:
            return _json_ok({"status": "no_pending_invite", "group_id": group_id})

        conn = get_db()
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE group_invites SET status = 'revoked' WHERE group_id = %s AND LOWER(to_user) = LOWER(%s) AND status = 'pending';",
                (group_id, to_user),
            )
            changed = cur.rowcount
        conn.commit()
        if not changed:
            return _json_ok({"status": "no_pending_invite", "group_id": group_id})
        _audit(actor, "group_invite_revoke", target=f"{group_id}:{to_user}")
        _emit_to_username(to_user, "group_invite_cleared", {"group_id": group_id, "action": "revoked"})
        _emit_groups_refresh(to_user, "invite_revoked", group_id=group_id)
        return _json_ok({"status": "revoked", "group_id": group_id, "to_user": to_user})

    # Alias: join requires invite (kept for existing UI)
    @app.route("/api/groups/<int:group_id>/join", methods=["POST"])
    @_limit(settings.get("rate_limit_groups_write") or "60 per minute")
    @jwt_required()
    def join_group(group_id: int):
        actor, actor_id = _resolve_group_actor()
        if not actor_id:
            return _json_error("Invalid user", 403)

        out = _accept_invite_common(group_id, actor, actor_id)
        if out is None:
            return _not_found()
        if out.get("_blocked") or out.get("_stale"):
            _emit_to_username(actor, "group_invite_cleared", {"group_id": group_id, "action": "revoked"})
            _emit_groups_refresh(actor, "invite_revoked", group_id=group_id)
            if out.get("_blocked"):
                return _json_error("You cannot join this group from a blocked invite", 403)
            return _json_error("This group invite is no longer valid", 403)
        _audit(actor, "group_join", target=str(group_id))
        _emit_to_username(actor, "group_invite_cleared", {"group_id": group_id, "action": "accepted"})
        _emit_groups_refresh(actor, "invite_joined", group_id=group_id)
        _emit_group_members_changed(group_id, "member_joined", username=actor)
        return _json_ok({"status": "joined", **out})

    # ─────────────────────────────────────────────────────────────────────────────
    # Membership management
    # ─────────────────────────────────────────────────────────────────────────────

    @app.route("/api/groups/<int:group_id>/leave", methods=["POST"])
    @_limit(settings.get("rate_limit_groups_write") or "60 per minute")
    @jwt_required()
    def leave_group(group_id: int):
        actor, actor_id = _resolve_group_actor()
        if not actor_id:
            return _json_error("Invalid user", 403)

        role = _get_group_role(group_id, actor_id)
        if role is None:
            return _not_found()

        conn = get_db()
        try:
            with conn.cursor() as cur:
                if role == "owner":
                    cur.execute("SELECT COUNT(*) FROM group_members WHERE group_id = %s;", (group_id,))
                    count_members = int(cur.fetchone()[0])
                    if count_members > 1:
                        return jsonify({"error": "Owner must transfer ownership before leaving."}), 400
                    members_to_notify = _group_member_usernames(group_id)
                    cur.execute("DELETE FROM groups WHERE id = %s;", (group_id,))
                    conn.commit()
                    _audit(actor, "group_delete_last_owner", target=str(group_id))
                    _force_group_members_leave(group_id, members_to_notify, reason="deleted", by=actor)
                    _emit_groups_refresh(actor, "group_deleted", group_id=group_id)
                    return _json_ok({"status": "deleted", "group_id": group_id})

                cur.execute(
                    "DELETE FROM group_members WHERE group_id = %s AND user_id = %s;",
                    (group_id, actor_id),
                )
            conn.commit()
            _audit(actor, "group_leave", target=str(group_id))
            _force_user_leave_group_socket(actor, group_id, reason="left", by=actor)
            _emit_groups_refresh(actor, "left_group", group_id=group_id)
            _emit_group_members_changed(group_id, "member_left", username=actor)
            return _json_ok({"status": "left", "group_id": group_id})
        except Exception as e:
            conn.rollback()
            return _server_error("Could not leave group", e)

    @app.route("/api/groups/<int:group_id>/kick", methods=["POST"])
    @_limit(settings.get("rate_limit_groups_write") or "60 per minute")
    @jwt_required()
    def kick_member(group_id: int):
        actor, actor_id = _resolve_group_actor()
        if not actor_id:
            return _json_error("Invalid user", 403)

        data = request.get_json(silent=True) or {}
        requested_target_user = (data.get("username") or data.get("to_user") or "").strip()
        if not requested_target_user:
            return jsonify({"error": "username required"}), 400
        target_user = _canonical_username(requested_target_user)
        if not target_user:
            return _json_error("User not found", 404)
        if target_user.lower() == str(actor or "").strip().lower():
            return jsonify({"error": "Cannot kick yourself"}), 400

        target_id = _get_user_id(target_user)
        if not target_id:
            return _json_error("User not found", 404)

        conn = get_db()
        try:
            with conn.cursor() as cur:
                locked_roles = _fetch_group_roles_for_update(cur, group_id, actor_id, target_id)
                actor_role = locked_roles.get(int(actor_id))
                target_role = locked_roles.get(int(target_id))
                if actor_role is None:
                    _rollback_quiet(conn)
                    return _not_found()
                if target_role is None:
                    _rollback_quiet(conn)
                    return jsonify({"status": "not_member"}), 200
                if _rank(actor_role) < _ROLE_RANK["moderator"]:
                    _rollback_quiet(conn)
                    return _json_error("Insufficient group role", 403)
                if _rank(actor_role) <= _rank(target_role):
                    _rollback_quiet(conn)
                    return _json_error("Insufficient group role", 403)
                if target_role == "owner":
                    _rollback_quiet(conn)
                    return jsonify({"error": "Cannot kick owner"}), 403
                cur.execute(
                    "DELETE FROM group_members WHERE group_id = %s AND user_id = %s;",
                    (group_id, target_id),
                )
                removed = int(cur.rowcount or 0)
                cur.execute(
                    "DELETE FROM group_mutes WHERE group_id = %s AND LOWER(username) = LOWER(%s);",
                    (group_id, target_user),
                )
                cur.execute(
                    """
                    UPDATE group_invites
                       SET status = 'revoked'
                     WHERE group_id = %s
                       AND LOWER(to_user) = LOWER(%s)
                       AND status = 'pending';
                    """,
                    (group_id, target_user),
                )
            conn.commit()
        except Exception as exc:
            _rollback_quiet(conn)
            return _server_error("Could not kick group member", exc)

        _audit(actor, "group_kick", target=f"{group_id}:{target_user}", details=f"removed={removed}")
        _force_user_leave_group_socket(target_user, group_id, reason="kicked", by=actor)
        _emit_groups_refresh(target_user, "kicked_from_group", group_id=group_id)
        _emit_groups_refresh(actor, "member_kicked", group_id=group_id)
        _emit_group_members_changed(group_id, "member_kicked", username=target_user, by=actor)
        _emit_group_list_refresh_to_members(group_id, "member_kicked", username=target_user, by=actor)
        return jsonify({"status": "kicked", "group_id": group_id, "username": target_user}), 200

    @app.route("/api/groups/<int:group_id>/set_role", methods=["POST"])
    @_limit(settings.get("rate_limit_groups_write") or "60 per minute")
    @jwt_required()
    def set_member_role(group_id: int):
        actor, actor_id = _resolve_group_actor()
        if not actor_id:
            return _json_error("Invalid user", 403)

        data = request.get_json(silent=True) or {}
        requested_target_user = (data.get("username") or data.get("to_user") or "").strip()
        raw_role = str(data.get("role") or "").strip().lower()
        new_role = raw_role
        if not requested_target_user or not raw_role:
            return jsonify({"error": "username and role required"}), 400
        target_user = _canonical_username(requested_target_user)
        if not target_user:
            return _json_error("User not found", 404)
        if new_role not in _ALLOWED_ROLES:
            return jsonify({"error": "Invalid role"}), 400
        if target_user.lower() == str(actor or "").strip().lower():
            return jsonify({"error": "Owner role cannot be changed here"}), 400
        if new_role == "owner":
            return jsonify({"error": "Use transfer_ownership"}), 400

        target_id = _get_user_id(target_user)
        if not target_id:
            return _json_error("User not found", 404)

        conn = get_db()
        try:
            with conn.cursor() as cur:
                locked_roles = _fetch_group_roles_for_update(cur, group_id, actor_id, target_id)
                actor_role = locked_roles.get(int(actor_id))
                target_role = locked_roles.get(int(target_id))
                if actor_role is None:
                    _rollback_quiet(conn)
                    return _not_found()
                if actor_role != "owner":
                    _rollback_quiet(conn)
                    return jsonify({"error": "Owner only"}), 403
                if target_role is None:
                    _rollback_quiet(conn)
                    return jsonify({"error": "Target not in group"}), 404
                if target_role == "owner":
                    _rollback_quiet(conn)
                    return jsonify({"error": "Use transfer_ownership"}), 400
                cur.execute(
                    "UPDATE group_members SET role = %s WHERE group_id = %s AND user_id = %s;",
                    (new_role, group_id, target_id),
                )
            conn.commit()
        except Exception as exc:
            _rollback_quiet(conn)
            return _server_error("Could not update group role", exc)

        _audit(actor, "group_set_role", target=f"{group_id}:{target_user}", details=new_role)
        try:
            _emit_group_members_changed(group_id, "role_updated", username=target_user, role=new_role)
        except Exception:
            pass
        try:
            _emit_group_list_refresh_to_members(group_id, "role_updated", username=target_user, role=new_role)
        except Exception:
            pass
        return _json_ok({"status": "role_updated", "group_id": group_id, "username": target_user, "role": new_role, "role_label": _role_label(new_role), "role_rank": _rank(new_role), "capabilities": _role_capabilities(new_role)})

    @app.route("/api/groups/<int:group_id>/transfer_ownership", methods=["POST"])
    @_limit(settings.get("rate_limit_groups_write") or "30 per minute")
    @jwt_required()
    def transfer_ownership(group_id: int):
        actor, actor_id = _resolve_group_actor()
        if not actor_id:
            return _json_error("Invalid user", 403)

        data = request.get_json(silent=True) or {}
        requested_target_user = (data.get("username") or data.get("to_user") or "").strip()
        target_user = _canonical_username(requested_target_user)
        if not requested_target_user or (target_user and target_user.lower() == str(actor or "").strip().lower()):
            return jsonify({"error": "Valid target username required"}), 400
        if not target_user:
            return _json_error("User not found", 404)

        target_id = _get_user_id(target_user)
        if not target_id:
            return _json_error("User not found", 404)

        conn = get_db()
        previous_owner_role = "owner"
        target_previous_role = "member"
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT user_id, COALESCE(role, 'member')
                      FROM group_members
                     WHERE group_id = %s
                     FOR UPDATE;
                    """,
                    (group_id,),
                )
                roles = {int(row[0]): _normalize_group_role(row[1]) for row in (cur.fetchall() or [])}
                actor_role = roles.get(int(actor_id))
                target_role = roles.get(int(target_id))
                if actor_role is None:
                    _rollback_quiet(conn)
                    return _not_found()
                if actor_role != "owner":
                    _rollback_quiet(conn)
                    return jsonify({"error": "Owner only"}), 403
                if target_role is None:
                    _rollback_quiet(conn)
                    return jsonify({"error": "Target not in group"}), 404
                previous_owner_role = actor_role
                target_previous_role = target_role
                cur.execute(
                    """
                    UPDATE group_members
                       SET role = CASE
                           WHEN user_id = %s THEN 'owner'
                           WHEN role = 'owner' THEN 'admin'
                           ELSE role
                       END
                     WHERE group_id = %s;
                    """,
                    (target_id, group_id),
                )
            conn.commit()
        except Exception as exc:
            _rollback_quiet(conn)
            return _server_error("Could not transfer group ownership", exc)

        _audit(actor, "group_transfer_owner", target=f"{group_id}:{target_user}", details=f"target_previous_role={target_previous_role}")
        _emit_group_members_changed(group_id, "ownership_transferred", username=target_user, previous_owner=actor)
        _emit_group_list_refresh_to_members(group_id, "ownership_transferred", username=target_user, previous_owner=actor)
        return _json_ok({"status": "ownership_transferred", "group_id": group_id, "new_owner": target_user, "previous_owner": actor, "previous_owner_role": "admin", "target_previous_role": target_previous_role, "role": "admin", "owner_role": "owner"})


    # ─────────────────────────────────────────────────────────────────────────────
    # Moderation: group mutes (moderator+)
    # ─────────────────────────────────────────────────────────────────────────────

    @app.route("/api/groups/<int:group_id>/mute", methods=["POST"])
    @_limit(settings.get("rate_limit_groups_write") or "60 per minute")
    @jwt_required()
    def mute_member(group_id: int):
        actor, actor_id = _resolve_group_actor()
        if not actor_id:
            return _json_error("Invalid user", 403)

        data = request.get_json(silent=True) or {}
        requested_target_user = (data.get("username") or data.get("to_user") or "").strip()
        if not requested_target_user:
            return jsonify({"error": "username required"}), 400
        target_user = _canonical_username(requested_target_user)
        if not target_user:
            return _json_error("User not found", 404)
        if target_user.lower() == str(actor or "").strip().lower():
            return jsonify({"error": "Cannot mute yourself"}), 400

        target_id = _get_user_id(target_user)
        if not target_id:
            return _json_error("User not found", 404)

        conn = get_db()
        try:
            with conn.cursor() as cur:
                locked_roles = _fetch_group_roles_for_update(cur, group_id, actor_id, target_id)
                actor_role = locked_roles.get(int(actor_id))
                target_role = locked_roles.get(int(target_id))
                if actor_role is None:
                    _rollback_quiet(conn)
                    return _not_found()
                if target_role is None:
                    _rollback_quiet(conn)
                    return jsonify({"error": "Target not in group"}), 404
                if _rank(actor_role) < _ROLE_RANK["moderator"]:
                    _rollback_quiet(conn)
                    return _json_error("Insufficient group role", 403)
                if _rank(actor_role) <= _rank(target_role):
                    _rollback_quiet(conn)
                    return _json_error("Insufficient group role", 403)
                if target_role == "owner":
                    _rollback_quiet(conn)
                    return jsonify({"error": "Cannot mute owner"}), 403
                cur.execute(
                    "DELETE FROM group_mutes WHERE group_id = %s AND LOWER(username) = LOWER(%s);",
                    (group_id, target_user),
                )
                cur.execute(
                    """
                    INSERT INTO group_mutes (group_id, username)
                    VALUES (%s, %s)
                    ON CONFLICT (group_id, username) DO NOTHING;
                    """,
                    (group_id, target_user),
                )
            conn.commit()
        except Exception as exc:
            _rollback_quiet(conn)
            return _server_error("Could not mute group member", exc)

        _audit(actor, "group_mute", target=f"{group_id}:{target_user}")
        _emit_group_members_changed(group_id, "member_muted", username=target_user, by=actor)
        return jsonify({"status": "muted", "group_id": group_id, "username": target_user}), 200


    @app.route("/api/groups/<int:group_id>/voice/kick", methods=["POST"])
    @_limit(settings.get("rate_limit_groups_write") or "60 per minute")
    @jwt_required()
    def kick_member_from_group_voice(group_id: int):
        actor, actor_id = _resolve_group_actor()
        if not actor_id:
            return _json_error("Invalid user", 403)

        actor_role = _get_group_role(group_id, actor_id)
        if actor_role is None:
            return _not_found()
        if _rank(actor_role) < _ROLE_RANK["moderator"]:
            return _json_error("Insufficient group role", 403)

        data = request.get_json(silent=True) or {}
        requested_target_user = (data.get("username") or data.get("to_user") or "").strip()
        if not requested_target_user:
            return jsonify({"error": "username required"}), 400
        target_user = _canonical_username(requested_target_user)
        if not target_user:
            return _json_error("User not found", 404)
        if target_user.lower() == str(actor or "").strip().lower():
            return jsonify({"error": "Cannot disconnect yourself here"}), 400

        target_id = _get_user_id(target_user)
        if not target_id:
            return _json_error("User not found", 404)
        target_role = _get_group_role(group_id, target_id)
        if target_role is None:
            return jsonify({"error": "Target not in group"}), 404
        if _rank(actor_role) <= _rank(target_role):
            return _json_error("Insufficient group role", 403)
        if target_role == "owner":
            return jsonify({"error": "Cannot disconnect owner"}), 403

        delivered = _force_user_leave_group_voice_socket(target_user, group_id, reason="removed_by_group_moderator", by=actor)
        _audit(actor, "group_voice_kick", target=f"{group_id}:{target_user}", details=f"actor_role={actor_role},target_role={target_role}")
        _emit_group_members_changed(group_id, "voice_kicked", username=target_user, by=actor, delivered=delivered)
        return jsonify({"status": "voice_kicked", "delivered": bool(delivered)}), 200

    @app.route("/api/groups/<int:group_id>/unmute", methods=["POST"])
    @_limit(settings.get("rate_limit_groups_write") or "60 per minute")
    @jwt_required()
    def unmute_member(group_id: int):
        actor, actor_id = _resolve_group_actor()
        if not actor_id:
            return _json_error("Invalid user", 403)

        actor_role = _get_group_role(group_id, actor_id)
        if actor_role is None:
            return _not_found()
        if _rank(actor_role) < _ROLE_RANK["moderator"]:
            return _json_error("Insufficient group role", 403)

        data = request.get_json(silent=True) or {}
        requested_target_user = (data.get("username") or data.get("to_user") or "").strip()
        if not requested_target_user:
            return jsonify({"error": "username required"}), 400
        target_user = _canonical_username(requested_target_user)
        if not target_user:
            return _json_error("User not found", 404)

        conn = get_db()
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM group_mutes WHERE group_id = %s AND LOWER(username) = LOWER(%s);",
                (group_id, target_user),
            )
        conn.commit()
        _audit(actor, "group_unmute", target=f"{group_id}:{target_user}")
        _emit_group_members_changed(group_id, "member_unmuted", username=target_user, by=actor)
        return _json_ok({"status": "unmuted", "group_id": group_id, "username": target_user})

    @app.route("/api/groups/<int:group_id>/mutes", methods=["GET"])
    @_limit(settings.get("rate_limit_groups_read") or "240 per minute")
    @jwt_required()
    def list_group_mutes(group_id: int):
        actor, actor_id = _resolve_group_actor()
        if not actor_id:
            return _json_error("Invalid user", 403)

        actor_role = _get_group_role(group_id, actor_id)
        if actor_role is None:
            return _not_found()
        if _rank(actor_role) < _ROLE_RANK["moderator"]:
            return _json_error("Insufficient group role", 403)

        conn = get_db()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT username, muted_at FROM group_mutes WHERE group_id = %s ORDER BY muted_at DESC;",
                (group_id,),
            )
            rows = cur.fetchall() or []
        return _json_ok(
            {
                "group_id": group_id,
                "mutes": [
                    {"username": r[0], "muted_at": r[1].isoformat() if hasattr(r[1], "isoformat") else str(r[1])}
                    for r in rows
                ],
                "total": len(rows),
                "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
        )

    # ─────────────────────────────────────────────────────────────────────────────
    # Group metadata changes / deletion
    # ─────────────────────────────────────────────────────────────────────────────

    @app.route("/api/groups/<int:group_id>", methods=["PATCH"])
    @_limit(settings.get("rate_limit_groups_write") or "60 per minute")
    @jwt_required()
    def update_group(group_id: int):
        actor, actor_id = _resolve_group_actor()
        if not actor_id:
            return _json_error("Invalid user", 403)

        role = _get_group_role(group_id, actor_id)
        if role is None:
            return _not_found()
        if _rank(role) < _ROLE_RANK["admin"]:
            return jsonify({"error": "Admin/Owner only"}), 403

        data = request.get_json(silent=True) or {}
        name = _normalize_group_name(data.get("name")) if "name" in data else ""
        desc = _normalize_group_description(data.get("description")) if "description" in data else None

        if "name" in data:
            if not name:
                return jsonify({"error": "Group name cannot be empty."}), 400
            if len(name) > 64:
                return jsonify({"error": "Group name too long (max 64)."}), 400

        if desc is not None and len(desc) > 512:
            return jsonify({"error": "Description too long (max 512)."}), 400

        if "name" not in data and "description" not in data:
            return jsonify({"error": "Nothing to update"}), 400

        conn = get_db()
        with conn.cursor() as cur:
            if name:
                cur.execute("UPDATE groups SET group_name = %s WHERE id = %s;", (name, group_id))
            if desc is not None:
                cur.execute("UPDATE groups SET group_description = %s WHERE id = %s;", (desc, group_id))
        conn.commit()
        _audit(actor, "group_update", target=str(group_id), details=json.dumps({"name": bool(name), "desc": bool(desc)}))
        _emit_group_members_changed(group_id, "metadata_updated", name=name or None, description_updated=desc is not None)
        _emit_group_list_refresh_to_members(group_id, "metadata_updated", name=name or None, description_updated=desc is not None)
        return _json_ok({"status": "updated", "group_id": group_id, "name": name or None, "description_updated": desc is not None})

    @app.route("/api/groups/<int:group_id>", methods=["DELETE"])
    @_limit(settings.get("rate_limit_groups_write") or "30 per minute")
    @jwt_required()
    def delete_group(group_id: int):
        actor, actor_id = _resolve_group_actor()
        if not actor_id:
            return _json_error("Invalid user", 403)

        role = _get_group_role(group_id, actor_id)
        if role is None:
            return _not_found()
        if role != "owner":
            return jsonify({"error": "Owner only"}), 403

        members_to_notify: list[str] = []
        conn = get_db()
        deleted = 0
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT id FROM groups WHERE id = %s FOR UPDATE;", (group_id,))
                if not cur.fetchone():
                    _rollback_quiet(conn)
                    return _not_found()
                cur.execute(
                    """
                    SELECT u.username
                      FROM group_members gm
                      JOIN users u ON u.id = gm.user_id
                     WHERE gm.group_id = %s
                     ORDER BY LOWER(u.username)
                     FOR UPDATE OF gm;
                    """,
                    (group_id,),
                )
                members_to_notify = [str(r[0]) for r in (cur.fetchall() or []) if r and r[0]]
                # group_mutes has no FK in older/fresh schemas, and messages use
                # synthetic rooms (g:<id> plus a legacy bare-id room), so delete
                # those explicitly before the groups row cascades memberships,
                # invites, pins, and encrypted group-file metadata.
                cur.execute("DELETE FROM group_mutes WHERE group_id = %s;", (group_id,))
                cur.execute("DELETE FROM messages WHERE room = %s OR room = %s;", (_room_key(group_id), str(int(group_id))))
                cur.execute("DELETE FROM groups WHERE id = %s;", (group_id,))
                deleted = int(cur.rowcount or 0)
            conn.commit()
        except Exception as exc:
            _rollback_quiet(conn)
            return _server_error("Could not delete group", exc)
        if not deleted:
            return _not_found()
        _audit(actor, "group_delete", target=str(group_id), details=f"members_notified={len(members_to_notify)}")
        _force_group_members_leave(group_id, members_to_notify, reason="deleted", by=actor)
        for username in members_to_notify:
            _emit_groups_refresh(username, "group_deleted", group_id=group_id)
        return jsonify({"status": "deleted", "group_id": group_id, "members_notified": len(members_to_notify)}), 200

    # ─────────────────────────────────────────────────────────────────────────────
    # Members & unread counts (member-only)
    # ─────────────────────────────────────────────────────────────────────────────
    # Members & unread counts (member-only)
    # ─────────────────────────────────────────────────────────────────────────────

    @app.route("/api/groups/<int:group_id>/members", methods=["GET"])
    @_limit(settings.get("rate_limit_groups_read") or "240 per minute")
    @jwt_required()
    def list_members(group_id: int):
        actor, actor_id = _resolve_group_actor()
        if not actor_id:
            return _json_error("Invalid user", 403)
        current_role = _get_group_role(group_id, actor_id)
        if current_role is None:
            return _not_found()

        conn = get_db()
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT u.username, COALESCE(gm.role, 'member') AS role, gm.joined_at
                  FROM group_members gm
                  JOIN users u ON gm.user_id = u.id
                 WHERE gm.group_id = %s
                 ORDER BY
                   CASE COALESCE(gm.role, 'member')
                     WHEN 'owner' THEN 0
                     WHEN 'admin' THEN 1
                     WHEN 'moderator' THEN 2
                     ELSE 3
                   END,
                   LOWER(u.username);
                """,
                (group_id,),
            )
            members = []
            for r in (cur.fetchall() or []):
                username = str(r[0] or "")
                role = _normalize_group_role(r[1])
                members.append({
                    "username": username,
                    "role": role,
                    "role_label": _role_label(role),
                    "role_rank": _rank(role),
                    "capabilities": _role_capabilities(role),
                    "is_self": username.strip().lower() == str(actor or "").strip().lower(),
                    "joined_at": r[2].isoformat() if hasattr(r[2], "isoformat") else (str(r[2]) if r[2] else ""),
                })
        return _json_ok({
            "group_id": group_id,
            "members": members,
            "member_details": members,
            "total": len(members),
            "current_role": _normalize_group_role(current_role),
            "current_capabilities": _role_capabilities(current_role),
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        })

    @app.route("/api/groups/<int:group_id>/unread_count", methods=["GET"])
    @_limit(settings.get("rate_limit_groups_read") or "240 per minute")
    @jwt_required()
    def group_unread_count(group_id: int):
        actor, actor_id = _resolve_group_actor()
        if not actor_id:
            return _json_error("Invalid user", 403)
        if not _is_member(group_id, actor_id):
            return _not_found()

        stats = _group_unread_stats(group_id, actor or "")
        return _json_ok({
            "group_id": group_id,
            **stats,
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        })

    # ─────────────────────────────────────────────────────────────────────────────
    # Group file uploads & authorized download
    #
    # Legacy attachment-based group file API.
    # Current clients should use /api/group_files/* from routes_main.py.
    # Keep these endpoints for backwards compatibility only; do not add new
    # feature work here.
    # ─────────────────────────────────────────────────────────────────────────────

    @app.route("/api/groups/<int:group_id>/upload", methods=["POST"])
    @_limit(settings.get("rate_limit_groups_upload") or "10 per minute")
    @jwt_required()
    def group_file_upload(group_id: int):
        actor, actor_id = _resolve_group_actor()
        if not actor_id:
            return _json_error("Invalid user", 403)
        if legacy_group_file_upload_disabled:
            return jsonify({"error": "File sharing is disabled", "deprecated": True, "replacement": "/api/group_files/*"}), 403
        if not _group_upload_rate_limit(actor):
            return _json_error("Rate limited", 429)
        if not _is_member(group_id, actor_id):
            return _not_found()

        if request.content_length and int(request.content_length) > (max_group_upload + 256_000):
            return jsonify({"error": f"File too large (max {max_group_upload} bytes)"}), 413

        if "file" not in request.files:
            return jsonify({"error": "No file provided"}), 400
        file = request.files["file"]
        if not file.filename:
            return jsonify({"error": "Empty filename"}), 400

        safe_name = secure_filename(file.filename) or "upload.bin"
        file_uuid = uuid.uuid4().hex
        group_dir = os.path.join(upload_root, str(group_id))
        os.makedirs(group_dir, exist_ok=True)
        disk_path = os.path.join(group_dir, f"{file_uuid}__{safe_name}")

        try:
            fsize = _save_filestorage_limited(file, disk_path, max_group_upload)
        except ValueError:
            return jsonify({"error": f"File too large (max {max_group_upload} bytes)"}), 413
        except Exception as exc:
            logging.error("[UPLOAD ERROR] legacy group upload save failed: %s", exc)
            return jsonify({"error": "Upload failed"}), 500

        # Persist as message + attachment
        conn = get_db()
        try:
            with conn.cursor() as cur:
                room = _room_key(group_id)
                msg_text = "[file] Attachment (pending)"
                cur.execute(
                    """
                    INSERT INTO messages (sender, room, message, is_encrypted)
                    VALUES (%s, %s, %s, FALSE)
                    RETURNING id;
                    """,
                    (actor, room, msg_text),
                )
                message_id = int(cur.fetchone()[0])

                attachment_payload = json.dumps(
                    {
                        "v": 1,
                        "disk_path": disk_path,
                        "download_name": safe_name,
                    }
                )

                cur.execute(
                    """
                    INSERT INTO file_attachments (message_id, file_path, file_type, file_size)
                    VALUES (%s, %s, %s, %s)
                    RETURNING id;
                    """,
                    (message_id, attachment_payload, file.content_type, fsize),
                )
                attachment_id = int(cur.fetchone()[0])

                # Update message with attachment id for easy client parsing
                cur.execute(
                    "UPDATE messages SET message = %s WHERE id = %s;",
                    (f"[file:{attachment_id}]", message_id),
                )
            conn.commit()
        except Exception as e:
            conn.rollback()
            try:
                os.remove(disk_path)
            except Exception:
                pass
            return _server_error("Could not upload group file", e)

        _audit(actor, "group_file_upload", target=f"{group_id}:{attachment_id}", details=f"{safe_name} ({fsize})")
        resp = jsonify({"status": "uploaded", "attachment_id": attachment_id, "name": safe_name, "size": fsize, "deprecated": True, "replacement": "/api/group_files/*"})
        resp.headers["X-EchoChat-Deprecated"] = "true"
        resp.headers["X-EchoChat-Replacement"] = "/api/group_files/*"
        return resp, 200

    def _load_attachment_for_group(group_id: int, attachment_id: int, actor: str, actor_id: int):
        if not _is_member(group_id, actor_id):
            return None
        conn = get_db()
        room = _room_key(group_id)
        legacy_room = str(group_id)
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT fa.file_path, fa.file_type, fa.file_size
                  FROM file_attachments fa
                  JOIN messages m ON m.id = fa.message_id
                 WHERE fa.id = %s
                   AND (m.room = %s OR m.room = %s);
                """,
                (attachment_id, room, legacy_room),
            )
            row = cur.fetchone()
        if not row:
            return None
        file_path_raw, mime, size = row
        try:
            payload = json.loads(file_path_raw)
            disk_path = payload.get("disk_path")
            download_name = payload.get("download_name") or "download.bin"
        except Exception:
            # Legacy: treat as direct disk path
            disk_path = file_path_raw
            download_name = os.path.basename(disk_path) if disk_path else "download.bin"
        safe_disk_path = safe_existing_file_under(upload_root, disk_path)
        if not safe_disk_path:
            return None
        return {"disk_path": safe_disk_path, "download_name": download_name, "mime": mime, "size": int(size or 0)}

    # NOTE:
    # routes_main.py already registers endpoints named `group_file_meta` and
    # `group_file_blob` for the newer E2EE group-files API.
    # Flask endpoint names must be unique across the whole app, so we use
    # different function names here for the legacy attachment-based group files.
    @app.route(
        "/api/groups/<int:group_id>/files/<int:attachment_id>/meta",
        methods=["GET"],
        endpoint="group_attachment_meta",
    )
    @jwt_required()
    def group_attachment_meta(group_id: int, attachment_id: int):
        actor, actor_id = _resolve_group_actor()
        if not actor_id:
            return _json_error("Invalid user", 403)
        att = _load_attachment_for_group(group_id, attachment_id, actor, actor_id)
        if not att:
            return _not_found()
        resp = jsonify(
            {
                "attachment_id": attachment_id,
                "group_id": group_id,
                "name": att["download_name"],
                "mime_type": att["mime"],
                "size": att["size"],
                "deprecated": True,
                "replacement": "/api/group_files/*",
            }
        )
        resp.headers["X-EchoChat-Deprecated"] = "true"
        resp.headers["X-EchoChat-Replacement"] = "/api/group_files/*"
        return resp, 200

    @app.route(
        "/api/groups/<int:group_id>/files/<int:attachment_id>/blob",
        methods=["GET"],
        endpoint="group_attachment_blob",
    )
    @jwt_required()
    def group_attachment_blob(group_id: int, attachment_id: int):
        actor, actor_id = _resolve_group_actor()
        if not actor_id:
            return _json_error("Invalid user", 403)
        att = _load_attachment_for_group(group_id, attachment_id, actor, actor_id)
        if not att:
            return _not_found()

        # Force download semantics for stored attachments so user content is never rendered inline.
        resp = send_file(
            att["disk_path"],
            mimetype="application/octet-stream",
            as_attachment=True,
            download_name=os.path.basename(att["download_name"]) or "download.bin",
            conditional=True,
        )
        resp.headers["X-EchoChat-Deprecated"] = "true"
        resp.headers["X-EchoChat-Replacement"] = "/api/group_files/*"
        return apply_safe_download_headers(resp, csp="sandbox; default-src 'none';", private=True)
