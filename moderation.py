#!/usr/bin/env python3
"""moderation.py

Moderation helpers (PostgreSQL).

Writes sanctions to user_sanctions and audit events to audit_log.
SQLite support has been removed.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import ipaddress
from typing import Optional

from database import get_db
from security import log_audit_event


_MAX_REASON_LEN = 500
_MAX_SANCTION_TYPE_LEN = 160


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _clean_username(username: str) -> str:
    return str(username or "").strip()


def _clean_sanction_type(sanction_type: str) -> str:
    clean = str(sanction_type or "").strip().lower()
    if not clean:
        raise ValueError("sanction_type is required")
    if len(clean) > _MAX_SANCTION_TYPE_LEN:
        raise ValueError(f"sanction_type must be <= {_MAX_SANCTION_TYPE_LEN} characters")
    return clean


def _clean_reason(reason: str | None) -> str | None:
    if reason is None:
        return None
    clean = str(reason or "").strip()
    if not clean:
        return None
    return clean[:_MAX_REASON_LEN]


def _expires_from_duration(duration_minutes: int | None) -> datetime | None:
    if duration_minutes is None:
        return None
    minutes = int(duration_minutes)
    if minutes <= 0:
        raise ValueError("duration_minutes must be positive or None")
    return _utcnow() + timedelta(minutes=minutes)



def _clean_ip_address(ip: str | None) -> str:
    """Normalize an IP address for sanction storage/lookup."""
    raw = str(ip or "").strip().strip("[]")
    if not raw or raw.lower() == "unknown":
        return ""
    try:
        return str(ipaddress.ip_address(raw))
    except Exception:
        return ""


def get_active_ip_sanction_detail(ip: str | None) -> tuple[str | None, datetime | None]:
    """Return ``(reason, expires_at)`` for the newest active IP ban.

    IP bans are stored in ``user_sanctions.username`` using the normalized IP
    address and ``sanction_type='ip_ban'``.  This helper keeps that legacy table
    shape but makes future-login/socket enforcement explicit and reusable.
    """
    clean_ip = _clean_ip_address(ip)
    if not clean_ip:
        return None, None
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT reason, expires_at
              FROM user_sanctions
             WHERE username = %s
               AND sanction_type = 'ip_ban'
               AND (expires_at IS NULL OR expires_at > NOW())
             ORDER BY created_at DESC, id DESC
             LIMIT 1;
            """,
            (clean_ip,),
        )
        row = cur.fetchone()
    if not row:
        return None, None
    return (_clean_reason(row[0]), row[1])


def is_ip_sanctioned(ip: str | None) -> bool:
    """Return True when a normalized IP currently has an active ``ip_ban``."""
    clean_ip = _clean_ip_address(ip)
    if not clean_ip:
        return False
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT 1
              FROM user_sanctions
             WHERE username = %s
               AND sanction_type = 'ip_ban'
               AND (expires_at IS NULL OR expires_at > NOW())
             LIMIT 1;
            """,
            (clean_ip,),
        )
        return cur.fetchone() is not None


def add_ip_sanction(
    ip: str | None,
    reason: str | None = None,
    duration_minutes: int | None = None,
    actor: str = "system",
) -> datetime | None:
    """Create an IP ban using the existing sanctions table."""
    clean_ip = _clean_ip_address(ip)
    if not clean_ip:
        raise ValueError("valid IP address is required")
    return add_sanction(clean_ip, "ip_ban", reason, duration_minutes, actor=actor)


def expire_ip_sanctions(
    ip: str | None,
    actor: str = "system",
    reason: str = "IP ban cleared by admin",
) -> int:
    """Expire active IP bans while preserving the moderation history rows."""
    clean_ip = _clean_ip_address(ip)
    if not clean_ip:
        raise ValueError("valid IP address is required")
    return expire_sanctions(clean_ip, "ip_ban", actor=actor, reason=reason)

def add_sanction(
    username: str,
    sanction_type: str,
    reason: str | None = None,
    duration_minutes: int | None = None,
    actor: str = "system",
) -> datetime | None:
    """Create a moderation sanction and audit it.

    ``duration_minutes=None`` creates a permanent sanction.  The username match
    used by all readers is case-insensitive, but we preserve the display casing
    supplied by the caller for admin history.

    Returns the calculated ``expires_at`` value.
    """
    clean_username = _clean_username(username)
    if not clean_username:
        raise ValueError("username is required")
    clean_type = _clean_sanction_type(sanction_type)
    clean_reason = _clean_reason(reason)
    expires_at = _expires_from_duration(duration_minutes)

    conn = get_db()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO user_sanctions (username, sanction_type, reason, expires_at)
            VALUES (%s, %s, %s, %s);
            """,
            (clean_username, clean_type, clean_reason, expires_at),
        )
    conn.commit()

    detail = f"reason={clean_reason or ''}; duration_minutes={duration_minutes}; expires_at={expires_at}"
    log_audit_event(str(actor or "system"), f"sanction:{clean_type}", clean_username, detail)
    return expires_at


def _add_sanction(
    username: str,
    sanction_type: str,
    reason: str | None = None,
    duration_minutes: int | None = None,
    actor: str = "system",
) -> None:
    """Backward-compatible wrapper for older callers."""
    add_sanction(username, sanction_type, reason, duration_minutes, actor=actor)


def ban_user(
    username: str,
    reason: str = "Violation of rules",
    duration_minutes: int = 1440,
    actor: str = "system",
) -> None:
    add_sanction(username, "ban", reason, duration_minutes, actor=actor)


def mute_user(
    username: str,
    reason: str = "Spamming or abusive content",
    duration_minutes: int = 60,
    actor: str = "system",
) -> None:
    add_sanction(username, "mute", reason, duration_minutes, actor=actor)


def kick_user(
    username: str,
    reason: str = "Disruptive behavior",
    duration_minutes: int = 15,
    actor: str = "system",
) -> None:
    # Kick is modeled as a short-lived sanction.
    add_sanction(username, "kick", reason, duration_minutes, actor=actor)


def get_active_sanction_detail(username: str, sanction_type: str) -> tuple[str | None, datetime | None]:
    """Return ``(reason, expires_at)`` for the newest active matching sanction.

    This intentionally filters to active rows before ordering.  The previous
    behavior could incorrectly treat a user as clear when their newest row had
    expired but an older permanent sanction still existed.
    """
    clean_username = _clean_username(username)
    clean_type = _clean_sanction_type(sanction_type)
    if not clean_username:
        return None, None
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT reason, expires_at
              FROM user_sanctions
             WHERE LOWER(username) = LOWER(%s)
               AND sanction_type = %s
               AND (expires_at IS NULL OR expires_at > NOW())
             ORDER BY created_at DESC, id DESC
             LIMIT 1;
            """,
            (clean_username, clean_type),
        )
        row = cur.fetchone()
    if not row:
        return None, None
    return (_clean_reason(row[0]), row[1])


def is_user_sanctioned(username: str, sanction_type: str) -> bool:
    """Return True if any active sanction of the requested type exists."""
    try:
        clean_username = _clean_username(username)
        clean_type = _clean_sanction_type(sanction_type)
    except Exception:
        return False
    if not clean_username:
        return False
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT 1
              FROM user_sanctions
             WHERE LOWER(username) = LOWER(%s)
               AND sanction_type = %s
               AND (expires_at IS NULL OR expires_at > NOW())
             LIMIT 1;
            """,
            (clean_username, clean_type),
        )
        row = cur.fetchone()
    return bool(row)


def expire_sanctions(
    username: str,
    sanction_type: str | None = None,
    actor: str = "system",
    reason: str = "cleared by admin",
) -> int:
    """Expire active sanctions for a user, preserving rows for audit/history.

    If ``sanction_type`` is omitted or ``*``, all active sanctions for the user
    are expired.  Returns the number of rows updated.
    """
    clean_username = _clean_username(username)
    if not clean_username:
        raise ValueError("username is required")
    clean_type = None
    if sanction_type and str(sanction_type).strip() != "*":
        clean_type = _clean_sanction_type(str(sanction_type))

    conn = get_db()
    with conn.cursor() as cur:
        if clean_type:
            cur.execute(
                """
                UPDATE user_sanctions
                   SET expires_at = NOW()
                 WHERE LOWER(username) = LOWER(%s)
                   AND sanction_type = %s
                   AND (expires_at IS NULL OR expires_at > NOW());
                """,
                (clean_username, clean_type),
            )
        else:
            cur.execute(
                """
                UPDATE user_sanctions
                   SET expires_at = NOW()
                 WHERE LOWER(username) = LOWER(%s)
                   AND (expires_at IS NULL OR expires_at > NOW());
                """,
                (clean_username,),
            )
        count = int(getattr(cur, "rowcount", 0) or 0)
    conn.commit()
    log_audit_event(str(actor or "system"), "sanction:expire", clean_username, f"type={clean_type or '*'}; rows={count}; reason={_clean_reason(reason) or ''}")
    return count


def list_active_sanctions(username: str | None = None, limit: int = 200):
    """List active sanctions.

    If username is None or '*', returns all active sanctions (up to limit).
    Returns rows shaped as tuples: (username, sanction_type, reason, expires_at)
    """
    safe_limit = max(1, min(int(limit or 200), 1000))
    clean_username = _clean_username(username or "")
    conn = get_db()
    with conn.cursor() as cur:
        if not clean_username or clean_username == "*":
            cur.execute(
                """
                SELECT username, sanction_type, reason, expires_at
                  FROM user_sanctions
                 WHERE (expires_at IS NULL OR expires_at > NOW())
                 ORDER BY created_at DESC, id DESC
                 LIMIT %s;
                """,
                (safe_limit,),
            )
        else:
            cur.execute(
                """
                SELECT username, sanction_type, reason, expires_at
                  FROM user_sanctions
                 WHERE LOWER(username) = LOWER(%s)
                   AND (expires_at IS NULL OR expires_at > NOW())
                 ORDER BY created_at DESC, id DESC
                 LIMIT %s;
                """,
                (clean_username, safe_limit),
            )
        rows = cur.fetchall()

    return rows
