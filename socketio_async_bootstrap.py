from __future__ import annotations

"""Shared Socket.IO async bootstrap helpers.

This module centralizes early runtime decisions around Eventlet so HuiChat does
not monkey-patch multiple times from different entrypoints.

Policy:
- ``HUI_SOCKETIO_ASYNC=auto`` defaults to ``threading``.
- ``HUI_SOCKETIO_ASYNC=eventlet`` explicitly opts into Eventlet.
- Eventlet monkey-patching happens at module import time so entrypoints can
  import this helper before Flask/Werkzeug and avoid late-patching warnings.
"""

import os
import warnings

HUI_SOCKETIO_ASYNC = (os.environ.get("HUI_SOCKETIO_ASYNC", "auto") or "auto").strip().lower()
_EVENTLET_REQUESTED = HUI_SOCKETIO_ASYNC == "eventlet"
_EVENTLET_ERROR: Exception | None = None
EVENTLET_AVAILABLE = False


def _bootstrap_eventlet_if_requested() -> bool:
    global EVENTLET_AVAILABLE, _EVENTLET_ERROR

    if not _EVENTLET_REQUESTED:
        return False

    try:
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", category=DeprecationWarning, module=r"eventlet(\\..*)?")
            import eventlet  # type: ignore

        eventlet.monkey_patch()
        EVENTLET_AVAILABLE = True
        return True
    except Exception as exc:  # pragma: no cover - depends on optional runtime dependency state
        _EVENTLET_ERROR = exc
        EVENTLET_AVAILABLE = False
        return False


_bootstrap_eventlet_if_requested()


def get_eventlet_error() -> Exception | None:
    return _EVENTLET_ERROR


def eventlet_requested() -> bool:
    return _EVENTLET_REQUESTED


def _patch_socketio_base_manager() -> None:
    """Patch BaseManager.pre_disconnect to tolerate a missing namespace.

    When always_connect=True (Hui Chat's setting), python-socketio sends the
    CONNECT packet immediately and then invokes the connect handler.  If the
    handler rejects the connection *after* the client has already disconnected,
    basic_disconnect() will have already removed the namespace from self.rooms.
    The subsequent pre_disconnect() call then raises KeyError: '/' on:

        return self.rooms[namespace][None].get(sid)

    The fix: catch that KeyError and return None, which is the correct sentinel
    value (no eio_sid to clean up) for a session that was never fully registered.
    """
    try:
        from socketio.base_manager import BaseManager

        _orig = BaseManager.pre_disconnect

        def _safe_pre_disconnect(self, sid, namespace):  # type: ignore[override]
            if namespace not in self.pending_disconnect:
                self.pending_disconnect[namespace] = []
            self.pending_disconnect[namespace].append(sid)
            try:
                return self.rooms[namespace][None].get(sid)
            except KeyError:
                # Namespace was removed before pre_disconnect ran (race between
                # always_connect send and client-side disconnect with polling).
                return None

        BaseManager.pre_disconnect = _safe_pre_disconnect  # type: ignore[method-assign]
    except Exception as exc:  # pragma: no cover
        import logging
        logging.warning("Could not patch socketio BaseManager.pre_disconnect: %s", exc)


_patch_socketio_base_manager()
