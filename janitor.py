from __future__ import annotations

import logging
import threading
import time

from database import cleanup_expired_custom_rooms, cleanup_expired_room_messages, cleanup_expired_autoscaled_rooms

try:
    from privacy_retention import apply_privacy_retention
except Exception:  # pragma: no cover - optional during partial installs
    apply_privacy_retention = None

try:  # optional: lets janitor use the same live room truth as the room browser
    from realtime.state import configure_shared_state, live_room_counts, shared_state_enabled
except Exception:  # pragma: no cover - keep janitor import-safe during partial installs
    configure_shared_state = None
    live_room_counts = None
    shared_state_enabled = None


_JANITOR_LOCK = threading.Lock()
_JANITOR_THREAD: threading.Thread | None = None


def _coerce_idle_minutes(settings: dict, minute_key: str, hour_key: str, default_hours: int) -> int:
    """Resolve idle TTL in minutes, preferring minute-based settings and falling back to hours."""
    raw_minutes = settings.get(minute_key, None)
    if raw_minutes not in (None, ""):
        try:
            minutes = int(raw_minutes)
        except Exception:
            minutes = default_hours * 60
    else:
        try:
            hours = int(settings.get(hour_key, default_hours))
        except Exception:
            hours = default_hours
        minutes = hours * 60
    return max(1, min(int(minutes), 24 * 60 * 365))


def start_janitor(settings: dict, use_live_counts: bool = True):
    """Start a lightweight background cleanup loop.

    - Removes inactive/empty custom rooms (based on `custom_room_idle_minutes` or fallback hour settings)
    - Purges messages for rooms with configured expiry

    This keeps the custom-room experience ephemeral without requiring UI polling.
    """

    # Configure Redis-backed presence if available.  In-process janitors can also
    # read local Socket.IO state; dedicated janitor_runner processes only use live
    # counts when Redis shared state is active.
    try:
        if configure_shared_state is not None:
            configure_shared_state(settings)
    except Exception:
        pass

    def _loop():
        while True:
            # Re-read settings each cycle so admin changes take effect live.
            try:
                interval = int(settings.get("janitor_interval_seconds", 60))
            except Exception:
                interval = 60
            interval = max(10, min(interval, 3600))

            idle_minutes = _coerce_idle_minutes(settings, "custom_room_idle_minutes", "custom_room_idle_hours", 3)
            private_idle_minutes = _coerce_idle_minutes(settings, "custom_private_room_idle_minutes", "custom_private_room_idle_hours", max(1, idle_minutes // 60))
            debug_custom_rooms = bool(settings.get("janitor_debug_custom_rooms", False))

            try:
                autoscale_idle_min = int(settings.get("autoscale_room_idle_minutes", 30))
            except Exception:
                autoscale_idle_min = 30
            autoscale_idle_min = max(1, min(autoscale_idle_min, 24 * 60 * 7))

            live_counts_snapshot = None
            try:
                can_use_live_counts = bool(use_live_counts) or bool(shared_state_enabled and shared_state_enabled())
                if can_use_live_counts and live_room_counts is not None:
                    live_counts_snapshot = live_room_counts()
            except Exception:
                live_counts_snapshot = None

            try:
                n = cleanup_expired_custom_rooms(
                    idle_minutes=idle_minutes,
                    private_idle_minutes=private_idle_minutes,
                    debug=debug_custom_rooms,
                    live_counts=live_counts_snapshot,
                )
                if n:
                    logging.info("[JANITOR] deleted %s idle custom rooms", n)
            except Exception:
                logging.exception("[JANITOR] custom room cleanup error")

            # Cleanup empty autoscaled room shards (e.g., Lobby (2))
            try:
                if bool(settings.get("autoscale_rooms_enabled", True)):
                    n = cleanup_expired_autoscaled_rooms(idle_minutes=autoscale_idle_min)
                    if n:
                        logging.info("[JANITOR] deleted %s idle autoscaled rooms", n)
            except Exception:
                logging.exception("[JANITOR] autoscaled room cleanup error")

            try:
                deleted = cleanup_expired_room_messages()
                if deleted:
                    logging.info("[JANITOR] deleted %s expired messages", deleted)
            except Exception:
                logging.exception("[JANITOR] message expiry cleanup error")

            try:
                if apply_privacy_retention is not None:
                    retained = apply_privacy_retention(settings, limit=500)
                    updates = retained.get("updated") if isinstance(retained, dict) else None
                    if updates and any(int(v or 0) for v in updates.values()):
                        logging.info("[JANITOR] privacy-retained old IP/UA metadata: %s", updates)
            except Exception:
                logging.exception("[JANITOR] privacy retention error")

            time.sleep(interval)

    global _JANITOR_THREAD
    with _JANITOR_LOCK:
        if _JANITOR_THREAD is not None and _JANITOR_THREAD.is_alive():
            logging.info("[JANITOR] background cleanup loop already running; reusing existing thread")
            return _JANITOR_THREAD

        t = threading.Thread(target=_loop, name="echochat_janitor", daemon=True)
        t.start()
        _JANITOR_THREAD = t
        logging.info("[JANITOR] background cleanup loop started")
        return t
