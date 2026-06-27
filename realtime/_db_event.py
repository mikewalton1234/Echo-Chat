"""Helpers to ensure Socket.IO event handlers always release Flask g DB connections."""
from __future__ import annotations

from functools import wraps
from database import close_db

def socket_event_db_cleanup(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        finally:
            try:
                close_db()
            except Exception:
                pass
    return wrapper
