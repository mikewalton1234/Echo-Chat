"""Central Socket.IO abuse guardrails for Hui Chat.

These helpers are deliberately dependency-light so they work in tests and in the
split realtime handler modules. They cover the controls that are easy to miss
when adding a new Socket.IO event:

* payload byte ceilings before expensive parsing / DB work;
* per-event sliding-window rate limits;
* conservative connection/session ceilings;
* low-detail audit messages for denied realtime traffic.

The limits are still backed by Hui Chat's existing simple in-process limiter.
Public beta startup already requires shared Redis-backed HTTP limits; these
Socket.IO guards provide a second line of defence and clear static coverage.
"""

from __future__ import annotations

import json
from typing import Any

from flask import request
from flask_socketio import emit, disconnect

from security import get_request_ip, log_audit_event, parse_rate_limit_value, simple_rate_limit
from realtime.state import get_connected_session, user_sids


_DEFAULT_MAX_EVENT_PAYLOAD_BYTES = 64 * 1024
_DEFAULT_SOCKET_EVENT_LIMIT = 180
_DEFAULT_SOCKET_EVENT_WINDOW = 60


def _setting_int(settings: dict[str, Any] | None, key: str, default: int, *, minimum: int = 0, maximum: int = 10_000_000) -> int:
    settings = settings or {}
    try:
        value = int(settings.get(key, default))
    except Exception:
        value = int(default)
    return max(int(minimum), min(int(maximum), int(value)))


def _payload_size_bytes(data: Any) -> int:
    """Best-effort canonical serialized size for a Socket.IO payload."""
    try:
        return len(json.dumps(data, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8"))
    except Exception:
        return len(str(data).encode("utf-8", errors="ignore"))


def socket_payload_guard(
    settings: dict[str, Any] | None,
    event_name: str,
    data: Any,
    *,
    username: str | None = None,
    default_max_bytes: int = _DEFAULT_MAX_EVENT_PAYLOAD_BYTES,
) -> tuple[bool, dict[str, Any] | None]:
    """Reject overlarge Socket.IO event payloads before expensive handling."""
    max_bytes = _setting_int(
        settings,
        "socketio_event_max_payload_bytes",
        int(default_max_bytes),
        minimum=1024,
        maximum=1024 * 1024,
    )
    size = _payload_size_bytes(data)
    if size <= max_bytes:
        return True, None
    actor = str(username or "unknown").strip() or "unknown"
    try:
        log_audit_event(actor, "socket_payload_denied", str(event_name or "socket"), f"{size}>{max_bytes}")
    except Exception:
        pass
    return False, {"success": False, "error": "payload_too_large", "max_bytes": max_bytes}


def socket_event_rate_guard(
    settings: dict[str, Any] | None,
    event_name: str,
    *,
    username: str | None = None,
    ip: str | None = None,
    default_limit: int = _DEFAULT_SOCKET_EVENT_LIMIT,
    default_window: int = _DEFAULT_SOCKET_EVENT_WINDOW,
) -> tuple[bool, dict[str, Any] | None]:
    """Apply a generic per-user/per-IP Socket.IO event rate limit."""
    settings = settings or {}
    limit, window = parse_rate_limit_value(
        settings.get("socketio_event_rate_limit") or settings.get("socket_event_rate_limit"),
        default_limit=default_limit,
        default_window=default_window,
    )
    actor = str(username or "").strip()
    if actor:
        key = f"socketio:event:{event_name}:user:{actor}"
    else:
        ip = ip or get_request_ip(request)
        key = f"socketio:event:{event_name}:ip:{ip}"
    ok, retry = simple_rate_limit(key, limit=limit, window_sec=window)
    if ok:
        return True, None
    try:
        log_audit_event(actor or str(ip or "unknown"), "socket_event_rate_limited", str(event_name or "socket"), f"retry_after={retry:.2f}")
    except Exception:
        pass
    return False, {"success": False, "error": "rate_limited", "retry_after": retry}


def socket_event_guard(
    settings: dict[str, Any] | None,
    event_name: str,
    data: Any,
    *,
    username: str | None = None,
    default_max_bytes: int = _DEFAULT_MAX_EVENT_PAYLOAD_BYTES,
    default_limit: int = _DEFAULT_SOCKET_EVENT_LIMIT,
    default_window: int = _DEFAULT_SOCKET_EVENT_WINDOW,
) -> dict[str, Any] | None:
    """Combined payload + rate guard. Return an error payload or None."""
    ok, payload = socket_payload_guard(settings, event_name, data, username=username, default_max_bytes=default_max_bytes)
    if not ok:
        return payload
    ok, payload = socket_event_rate_guard(
        settings,
        event_name,
        username=username,
        default_limit=default_limit,
        default_window=default_window,
    )
    if not ok:
        return payload
    return None


def socket_connect_guard(
    settings: dict[str, Any] | None,
    *,
    username: str,
    auth_session_id: str | None,
    sid: str,
) -> bool:
    """Rate-limit connect storms and cap duplicate browser sessions per user."""
    settings = settings or {}
    username = str(username or "").strip()
    sid = str(sid or "").strip()
    auth_session_id = str(auth_session_id or "").strip()
    ip = get_request_ip(request)

    limit, window = parse_rate_limit_value(
        settings.get("socketio_connect_rate_limit") or "30 per minute",
        default_limit=30,
        default_window=60,
    )
    for key in (f"socketio:connect:ip:{ip}", f"socketio:connect:user:{username}"):
        ok, retry = simple_rate_limit(key, limit=limit, window_sec=window)
        if not ok:
            try:
                log_audit_event(username or ip, "socket_connect_rate_limited", None, f"retry_after={retry:.2f}")
            except Exception:
                pass
            try:
                emit("force_logout", {"success": False, "error": "realtime_connect_rate_limited", "retry_after": retry}, to=sid)
            except Exception:
                pass
            try:
                disconnect(sid=sid)
            except Exception:
                pass
            return False

    max_user = _setting_int(settings, "socketio_max_sessions_per_user", 8, minimum=1, maximum=128)
    max_auth = _setting_int(settings, "socketio_max_sessions_per_auth_session", 4, minimum=1, maximum=64)
    try:
        existing_sids = [s for s in user_sids(username) if str(s) != sid]
    except Exception:
        existing_sids = []

    if len(existing_sids) >= max_user:
        try:
            log_audit_event(username, "socket_session_limit_denied", None, f"user_sessions={len(existing_sids)} max={max_user}")
        except Exception:
            pass
        try:
            emit("force_logout", {"success": False, "error": "too_many_realtime_sessions", "max_sessions": max_user}, to=sid)
        except Exception:
            pass
        try:
            disconnect(sid=sid)
        except Exception:
            pass
        return False

    if auth_session_id:
        same_auth = []
        for existing_sid in existing_sids:
            try:
                sess = get_connected_session(existing_sid) or {}
            except Exception:
                sess = {}
            if str(sess.get("auth_session_id") or "").strip() == auth_session_id:
                same_auth.append(existing_sid)
        if len(same_auth) >= max_auth:
            try:
                log_audit_event(username, "socket_auth_session_limit_denied", None, f"auth_sessions={len(same_auth)} max={max_auth}")
            except Exception:
                pass
            try:
                emit("force_logout", {"success": False, "error": "too_many_realtime_tabs", "max_tabs": max_auth}, to=sid)
            except Exception:
                pass
            try:
                disconnect(sid=sid)
            except Exception:
                pass
            return False

    return True
