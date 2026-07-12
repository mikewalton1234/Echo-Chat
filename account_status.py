#!/usr/bin/env python3
"""Account lifecycle status helpers for Hui Chat.

Hui Chat stores permanent lifecycle state on ``users.status`` and temporary
moderation state in ``user_sanctions``.  These helpers expose one effective
status for login/session checks and admin UI surfaces.
"""

from __future__ import annotations

from typing import Any

from db.core import get_db

ACCOUNT_STATUS_ACTIVE = "active"
ACCOUNT_STATUS_SUSPENDED = "suspended"
ACCOUNT_STATUS_DEACTIVATED = "deactivated"
ACCOUNT_STATUS_SHADOWBANNED = "shadowbanned"

ACCOUNT_STATUSES = {
    ACCOUNT_STATUS_ACTIVE,
    ACCOUNT_STATUS_SUSPENDED,
    ACCOUNT_STATUS_DEACTIVATED,
    ACCOUNT_STATUS_SHADOWBANNED,
}

_DB_LIFECYCLE_STATUSES = {
    ACCOUNT_STATUS_ACTIVE,
    ACCOUNT_STATUS_SUSPENDED,
    ACCOUNT_STATUS_DEACTIVATED,
    ACCOUNT_STATUS_SHADOWBANNED,
}


def normalize_stored_account_status(value: Any) -> str:
    """Normalize a raw ``users.status`` value without trusting hand-edited DB text."""
    status = str(value or "").strip().lower()
    if status in _DB_LIFECYCLE_STATUSES:
        return status
    return ACCOUNT_STATUS_ACTIVE


def active_sanction_exists_sql(user_sql: str, sanction_type: str) -> str:
    """Return an EXISTS expression for an active sanction on a username SQL expression."""
    safe_type = str(sanction_type or "").replace("'", "''")
    return (
        "EXISTS ("
        "SELECT 1 FROM user_sanctions us "
        f"WHERE LOWER(us.username) = LOWER({user_sql}) "
        f"AND us.sanction_type = '{safe_type}' "
        "AND (us.expires_at IS NULL OR us.expires_at > NOW())"
        ")"
    )


def effective_account_status_sql(user_alias: str = "u") -> str:
    """SQL CASE expression that maps stored status + active sanctions to one status."""
    alias = "".join(ch for ch in str(user_alias or "u") if ch.isalnum() or ch == "_") or "u"
    user_expr = f"{alias}.username"
    stored = f"LOWER(COALESCE({alias}.status, 'active'))"
    active_ban = active_sanction_exists_sql(user_expr, "ban")
    active_shadowban = active_sanction_exists_sql(user_expr, "shadowban")
    return (
        "CASE "
        f"WHEN {stored} = 'deactivated' THEN 'deactivated' "
        f"WHEN {stored} = 'suspended' OR {active_ban} THEN 'suspended' "
        f"WHEN {stored} = 'shadowbanned' OR {active_shadowban} THEN 'shadowbanned' "
        "ELSE 'active' END"
    )


def _status_from_parts(stored_status: Any, active_ban: bool, active_shadowban: bool) -> str:
    stored = normalize_stored_account_status(stored_status)
    if stored == ACCOUNT_STATUS_DEACTIVATED:
        return ACCOUNT_STATUS_DEACTIVATED
    if stored == ACCOUNT_STATUS_SUSPENDED or active_ban:
        return ACCOUNT_STATUS_SUSPENDED
    if stored == ACCOUNT_STATUS_SHADOWBANNED or active_shadowban:
        return ACCOUNT_STATUS_SHADOWBANNED
    return ACCOUNT_STATUS_ACTIVE


def get_effective_account_status(username: str) -> str | None:
    """Return active/suspended/deactivated/shadowbanned for an existing user.

    Returns ``None`` when the account does not exist. Temporary suspension is
    derived from the active ``ban`` sanction because the current admin suspend
    route stores timed suspensions in ``user_sanctions``.
    """
    clean = str(username or "").strip()
    if not clean:
        return None
    conn = get_db()
    with conn.cursor() as cur:
        try:
            cur.execute(
                """
                SELECT u.status,
                       EXISTS (
                         SELECT 1 FROM user_sanctions us
                          WHERE LOWER(us.username) = LOWER(u.username)
                            AND us.sanction_type = 'ban'
                            AND (us.expires_at IS NULL OR us.expires_at > NOW())
                       ) AS active_ban,
                       EXISTS (
                         SELECT 1 FROM user_sanctions us
                          WHERE LOWER(us.username) = LOWER(u.username)
                            AND us.sanction_type = 'shadowban'
                            AND (us.expires_at IS NULL OR us.expires_at > NOW())
                       ) AS active_shadowban
                  FROM users u
                 WHERE LOWER(u.username) = LOWER(%s)
                 LIMIT 1;
                """,
                (clean,),
            )
            row = cur.fetchone()
        except Exception:
            # Older/broken databases may be mid-migration. psycopg2 leaves the
            # transaction aborted after a failed query, so rollback before the
            # fallback lifecycle-only read.
            try:
                conn.rollback()
            except Exception:
                pass
            with conn.cursor() as fallback_cur:
                fallback_cur.execute("SELECT status FROM users WHERE LOWER(username) = LOWER(%s) LIMIT 1;", (clean,))
                row = fallback_cur.fetchone()
            if not row:
                return None
            return normalize_stored_account_status(row[0])
    if not row:
        return None
    return _status_from_parts(row[0], bool(row[1]), bool(row[2]))


def account_status_allows_auth(status: str | None) -> bool:
    """Return True when the effective account status may sign in/use sessions."""
    return str(status or "").strip().lower() in {ACCOUNT_STATUS_ACTIVE, ACCOUNT_STATUS_SHADOWBANNED}


def account_status_reason(status: str | None) -> str:
    """Human-readable reason for auth/session rejection."""
    code = str(status or "").strip().lower()
    if code == ACCOUNT_STATUS_DEACTIVATED:
        return "This account is deactivated. Contact an admin if you think this is a mistake."
    if code == ACCOUNT_STATUS_SUSPENDED:
        return "This account is suspended. Contact an admin if you think this is a mistake."
    return "This account cannot sign in right now."


def account_status_error_code(status: str | None) -> str:
    code = str(status or "").strip().lower()
    if code == ACCOUNT_STATUS_DEACTIVATED:
        return "account_deactivated"
    if code == ACCOUNT_STATUS_SUSPENDED:
        return "account_suspended"
    return "account_not_active"


def account_can_authenticate(username: str) -> tuple[bool, str | None, str, str]:
    """Return (allowed, effective_status, error_code, reason)."""
    status = get_effective_account_status(username)
    if status is None:
        return False, None, "user_not_found", "User not found."
    if account_status_allows_auth(status):
        return True, status, "", ""
    return False, status, account_status_error_code(status), account_status_reason(status)


def is_effectively_shadowbanned(username: str) -> bool:
    return get_effective_account_status(username) == ACCOUNT_STATUS_SHADOWBANNED
