"""Retention and redaction helpers for IP address and user-agent metadata.

EchoChat keeps recent IP/UA metadata useful for account-security diagnostics, but
older rows should not retain raw device/network identifiers indefinitely. These
helpers replace old values with stable, non-reversible hash labels and scrub old
audit-log details that accidentally include raw `ip=` / `ua=` strings.
"""

from __future__ import annotations

import hashlib
import ipaddress
import re
from datetime import datetime, timezone, timedelta
from typing import Any

from database import get_db

_HASH_PREFIX = "echash:v1:"
_AUDIT_REDACT_MARKER = "privacy-retained"
_IPV4_RE = re.compile(r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])")
_IPV6_RE = re.compile(r"(?<![\w:])(?:[A-Fa-f0-9]{0,4}:){2,7}[A-Fa-f0-9]{0,4}(?![\w:])")
_IP_FIELD_RE = re.compile(r"\bip=([^\s,;]+)", re.IGNORECASE)
_UA_FIELD_RE = re.compile(r"\bua=([^\n\r]+)", re.IGNORECASE)


def _truthy(value: Any, default: bool = True) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def privacy_retention_enabled(settings: dict | None = None) -> bool:
    settings = settings or {}
    return _truthy(settings.get("privacy_retention_enabled"), True)


def ip_user_agent_retention_days(settings: dict | None = None) -> int:
    settings = settings or {}
    try:
        days = int(settings.get("privacy_ip_user_agent_retention_days", 30))
    except Exception:
        days = 30
    return max(0, min(days, 3650))


def audit_detail_retention_days(settings: dict | None = None) -> int:
    settings = settings or {}
    try:
        days = int(settings.get("privacy_audit_detail_retention_days", 90))
    except Exception:
        days = 90
    return max(0, min(days, 3650))


def _hash_salt(settings: dict | None = None) -> str:
    settings = settings or {}
    return str(settings.get("secret_key") or settings.get("jwt_secret") or "echochat-local-retention-salt")


def _hash_label(value: Any, kind: str, settings: dict | None = None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.startswith(_HASH_PREFIX):
        return text
    norm = text
    if kind == "ip":
        try:
            norm = str(ipaddress.ip_address(text))
        except Exception:
            norm = text.lower()
    digest = hashlib.sha256((str(_hash_salt(settings)) + "\n" + kind + "\n" + norm).encode("utf-8", "ignore")).hexdigest()[:20]
    return f"{_HASH_PREFIX}{kind}:{digest}"


def retained_ip(value: Any, settings: dict | None = None) -> str | None:
    return _hash_label(value, "ip", settings)


def retained_user_agent(value: Any, settings: dict | None = None) -> str | None:
    return _hash_label(value, "ua", settings)


def is_retained_value(value: Any) -> bool:
    return isinstance(value, str) and value.startswith(_HASH_PREFIX)


def redact_testlab_token_text(text: Any) -> str:
    """Redact randomized Test Lab tokens from log/audit text."""
    raw = str(text or "")
    raw = re.sub(r"/admin/test_lab/[A-Za-z0-9_\-]{24,}(/?)", r"/admin/test_lab/<redacted>\1", raw)
    raw = re.sub(r"/admin/test-lab/[A-Za-z0-9_\-]{24,}(/?)", r"/admin/test-lab/<redacted>\1", raw)
    return raw


def redact_audit_details(details: Any, settings: dict | None = None) -> str | None:
    if details is None:
        return None
    text = redact_testlab_token_text(str(details))
    if not text:
        return text

    def repl_ip_field(match: re.Match) -> str:
        return "ip=" + str(retained_ip(match.group(1), settings) or _AUDIT_REDACT_MARKER)

    def repl_ua_field(match: re.Match) -> str:
        return "ua=" + str(retained_user_agent(match.group(1), settings) or _AUDIT_REDACT_MARKER)

    text = _IP_FIELD_RE.sub(repl_ip_field, text)
    text = _UA_FIELD_RE.sub(repl_ua_field, text)
    text = _IPV4_RE.sub(lambda m: str(retained_ip(m.group(0), settings) or _AUDIT_REDACT_MARKER), text)
    text = _IPV6_RE.sub(lambda m: str(retained_ip(m.group(0), settings) or _AUDIT_REDACT_MARKER), text)
    return text


def privacy_retention_counts(settings: dict | None = None) -> dict:
    days = ip_user_agent_retention_days(settings)
    audit_days = audit_detail_retention_days(settings)
    enabled = privacy_retention_enabled(settings)
    counts = {
        "enabled": bool(enabled),
        "ip_user_agent_retention_days": days,
        "audit_detail_retention_days": audit_days,
        "auth_sessions_raw_old": 0,
        "auth_tokens_raw_old": 0,
        "password_reset_tokens_raw_old": 0,
        "audit_details_raw_old": 0,
    }
    if not enabled or days <= 0:
        return counts
    conn = get_db()
    with conn.cursor() as cur:
        try:
            cur.execute(
                """
                SELECT COUNT(*) FROM auth_sessions
                 WHERE COALESCE(last_activity_at, last_seen_at, created_at) < (CURRENT_TIMESTAMP - (%s || ' days')::interval)
                   AND ((ip_address IS NOT NULL AND ip_address <> '' AND ip_address NOT LIKE 'echash:v1:%%')
                    OR  (user_agent IS NOT NULL AND user_agent <> '' AND user_agent NOT LIKE 'echash:v1:%%'));
                """,
                (days,),
            )
            counts["auth_sessions_raw_old"] = int(cur.fetchone()[0] or 0)
        except Exception:
            counts["auth_sessions_raw_old"] = None
        try:
            cur.execute(
                """
                SELECT COUNT(*) FROM auth_tokens
                 WHERE COALESCE(last_used_at, created_at) < (CURRENT_TIMESTAMP - (%s || ' days')::interval)
                   AND ((ip_address IS NOT NULL AND ip_address <> '' AND ip_address NOT LIKE 'echash:v1:%%')
                    OR  (user_agent IS NOT NULL AND user_agent <> '' AND user_agent NOT LIKE 'echash:v1:%%'));
                """,
                (days,),
            )
            counts["auth_tokens_raw_old"] = int(cur.fetchone()[0] or 0)
        except Exception:
            counts["auth_tokens_raw_old"] = None
        try:
            cur.execute(
                """
                SELECT COUNT(*) FROM password_reset_tokens
                 WHERE created_at < (CURRENT_TIMESTAMP - (%s || ' days')::interval)
                   AND ((request_ip IS NOT NULL AND request_ip <> '' AND request_ip NOT LIKE 'echash:v1:%%')
                    OR  (user_agent IS NOT NULL AND user_agent <> '' AND user_agent NOT LIKE 'echash:v1:%%'));
                """,
                (days,),
            )
            counts["password_reset_tokens_raw_old"] = int(cur.fetchone()[0] or 0)
        except Exception:
            counts["password_reset_tokens_raw_old"] = None
        if audit_days > 0:
            try:
                cur.execute(
                    """
                    SELECT COUNT(*) FROM audit_log
                     WHERE timestamp < (CURRENT_TIMESTAMP - (%s || ' days')::interval)
                       AND details IS NOT NULL
                       AND details <> ''
                       AND details NOT LIKE '%%echash:v1:%%'
                       AND (details ~* 'ip=' OR details ~* 'ua=' OR details ~ E'(?:[0-9]{1,3}\\.){3}[0-9]{1,3}');
                    """,
                    (audit_days,),
                )
                counts["audit_details_raw_old"] = int(cur.fetchone()[0] or 0)
            except Exception:
                counts["audit_details_raw_old"] = None
    return counts


def apply_privacy_retention(settings: dict | None = None, *, limit: int = 500) -> dict:
    """Hash raw IP/UA metadata older than the configured retention windows."""
    settings = settings or {}
    result = {"ok": True, "enabled": privacy_retention_enabled(settings), "updated": {}}
    days = ip_user_agent_retention_days(settings)
    audit_days = audit_detail_retention_days(settings)
    if not result["enabled"] or days <= 0:
        result["ok"] = True
        result["skipped"] = "privacy retention disabled"
        return result

    conn = get_db()
    total_updates: dict[str, int] = {}

    def update_table(table: str, id_col: str, ip_col: str, ua_col: str, time_expr: str) -> None:
        updated = 0
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT {id_col}, {ip_col}, {ua_col}
                  FROM {table}
                 WHERE {time_expr} < (CURRENT_TIMESTAMP - (%s || ' days')::interval)
                   AND (({ip_col} IS NOT NULL AND {ip_col} <> '' AND {ip_col} NOT LIKE 'echash:v1:%%')
                    OR  ({ua_col} IS NOT NULL AND {ua_col} <> '' AND {ua_col} NOT LIKE 'echash:v1:%%'))
                 ORDER BY {time_expr} ASC
                 LIMIT %s;
                """,
                (days, int(limit)),
            )
            rows = cur.fetchall() or []
            for row in rows:
                row_id, ip_value, ua_value = row
                cur.execute(
                    f"UPDATE {table} SET {ip_col}=%s, {ua_col}=%s WHERE {id_col}=%s;",
                    (retained_ip(ip_value, settings), retained_user_agent(ua_value, settings), row_id),
                )
                updated += 1
        total_updates[table] = updated

    update_table("auth_sessions", "session_id", "ip_address", "user_agent", "COALESCE(last_activity_at, last_seen_at, created_at)")
    update_table("auth_tokens", "jti", "ip_address", "user_agent", "COALESCE(last_used_at, created_at)")
    update_table("password_reset_tokens", "id", "request_ip", "user_agent", "created_at")

    audit_updated = 0
    if audit_days > 0:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, details
                  FROM audit_log
                 WHERE timestamp < (CURRENT_TIMESTAMP - (%s || ' days')::interval)
                   AND details IS NOT NULL
                   AND details <> ''
                   AND details NOT LIKE '%%echash:v1:%%'
                   AND (details ~* 'ip=' OR details ~* 'ua=' OR details ~ E'(?:[0-9]{1,3}\\.){3}[0-9]{1,3}')
                 ORDER BY timestamp ASC
                 LIMIT %s;
                """,
                (audit_days, int(limit)),
            )
            for row_id, details in cur.fetchall() or []:
                redacted = redact_audit_details(details, settings)
                if redacted != details:
                    cur.execute("UPDATE audit_log SET details=%s WHERE id=%s;", (redacted, row_id))
                    audit_updated += 1
    total_updates["audit_log"] = audit_updated
    conn.commit()
    result["updated"] = total_updates
    return result
