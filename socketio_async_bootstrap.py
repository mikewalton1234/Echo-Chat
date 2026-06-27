from __future__ import annotations

"""Shared Socket.IO async bootstrap helpers.

This module centralizes early runtime decisions around Eventlet so EchoChat does
not monkey-patch multiple times from different entrypoints.

Policy:
- ``ECHOCHAT_SOCKETIO_ASYNC=auto`` defaults to ``threading``.
- ``ECHOCHAT_SOCKETIO_ASYNC=eventlet`` explicitly opts into Eventlet.
- Eventlet monkey-patching happens at module import time so entrypoints can
  import this helper before Flask/Werkzeug and avoid late-patching warnings.
"""

import os
import warnings

ECHOCHAT_SOCKETIO_ASYNC = (os.environ.get("ECHOCHAT_SOCKETIO_ASYNC", "auto") or "auto").strip().lower()
_EVENTLET_REQUESTED = ECHOCHAT_SOCKETIO_ASYNC == "eventlet"
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
