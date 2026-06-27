"""Health/status endpoint helpers for Echo-Chat.

The public probe endpoint must stay tiny, unauthenticated, and non-sensitive.
It should be safe for reverse proxies, uptime monitors, and load balancers.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.parse import urlparse

try:  # APP_VERSION is operationally useful but not required for health.
    from constants import APP_VERSION
except Exception:  # pragma: no cover - defensive import fallback
    APP_VERSION = "unknown"

HEALTH_DEFAULT_PATH = "/health"
_RESERVED_EXACT_PATHS = {
    "/",
    "/chat",
    "/login",
    "/register",
    "/logout",
    "/forgot-password",
    "/upload",
    "/token/refresh",
}
_RESERVED_PREFIXES = (
    "/admin",
    "/auth/",
    "/static/",
    "/socket.io/",
    "/reset-password",
    "/moderation",
)
_SAFE_PATH_RE = re.compile(r"^/[A-Za-z0-9._~!$&'()*+,;=:@%/-]{1,160}$")


def normalize_public_probe_path(value: Any, default: str = HEALTH_DEFAULT_PATH) -> str:
    """Return a safe Flask route for public health/status probes.

    Accepts either ``healthz`` or ``/healthz``. If an operator accidentally
    pastes a full URL, only the URL path is used. Dangerous, dynamic, malformed,
    or app-reserved paths fall back to ``default`` so startup cannot be broken by
    a hand-edited config file.
    """

    fallback = str(default or HEALTH_DEFAULT_PATH).strip() or HEALTH_DEFAULT_PATH
    if not fallback.startswith("/"):
        fallback = f"/{fallback}"

    raw = str(value or fallback).strip() or fallback
    if "://" in raw:
        try:
            parsed = urlparse(raw)
            raw = parsed.path or fallback
        except Exception:
            raw = fallback

    # Drop accidental query/fragment pieces from copied URLs or proxy docs.
    raw = raw.split("?", 1)[0].split("#", 1)[0].strip()
    if not raw.startswith("/"):
        raw = f"/{raw}"
    raw = re.sub(r"/{2,}", "/", raw)
    if len(raw) > 1:
        raw = raw.rstrip("/")

    lower = raw.lower()
    if (
        not _SAFE_PATH_RE.match(raw)
        or "<" in raw
        or ">" in raw
        or "\\" in raw
        or lower in _RESERVED_EXACT_PATHS
        or any(lower == prefix.rstrip("/") or lower.startswith(prefix) for prefix in _RESERVED_PREFIXES)
    ):
        return fallback
    return raw


def build_health_payload(
    get_db_func: Callable[[], Any],
    shared_state_summary_func: Callable[[], dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], int]:
    """Build a minimal, non-sensitive health payload.

    Database failure is treated as unhealthy because most Echo-Chat features need
    PostgreSQL. Shared state/Redis being disabled is reported as a check value,
    but it does not make a single-worker LAN server unhealthy.
    """

    db_ok = True
    try:
        conn = get_db_func()
        with conn.cursor() as cur:
            cur.execute("SELECT 1;")
            cur.fetchone()
    except Exception:
        db_ok = False

    shared_state = {"enabled": False}
    if shared_state_summary_func is not None:
        try:
            shared_state = shared_state_summary_func() or {"enabled": False}
            if not isinstance(shared_state, dict):
                shared_state = {"enabled": False}
        except Exception:
            shared_state = {"enabled": False, "error": True}

    payload = {
        "ok": bool(db_ok),
        "status": "ok" if db_ok else "degraded",
        "checks": {
            "database": "ok" if db_ok else "down",
            "shared_state": "ok" if shared_state.get("enabled") else "disabled",
        },
        "version": APP_VERSION,
        "time": datetime.now(timezone.utc).isoformat(),
    }
    return payload, 200 if db_ok else 503
