"""Socket.IO handlers: admin.

Auto-split from the legacy monolithic socket_handlers.py.
"""

import json
import re
import time
import uuid
import threading
from collections import deque

from flask import request
from socket_auth import jwt_required, get_jwt_identity
from flask_socketio import join_room, leave_room, emit, disconnect

from database import (
    get_all_rooms,
    get_friends_for_user,
    create_room_if_missing,
    create_autoscaled_room_if_missing,
    increment_room_count,
    get_pending_friend_requests,
    get_blocked_users,
    get_db,
    get_custom_room_meta,
    can_user_access_custom_room,
    touch_custom_room_activity,
    consume_room_invites,
    set_room_message_expiry,
    get_room_message_expiry,
)
from security import log_audit_event
from permissions import check_user_permission
from moderation import is_user_sanctioned, mute_user

from realtime.state import *

def register(socketio, settings, ctx):
    """Register Socket.IO event handlers for this module."""
    # Make helper functions from socket_handlers available as module globals
    globals().update(ctx.__dict__)

    def _disabled_socket_admin_write(actor: str, event_name: str, *, target: str | None = None, http_route: str | None = None):
        """Fail closed for legacy Socket.IO admin writes.

        Mutating admin operations must use the canonical HTTP admin routes so
        CSRF, granular RBAC, recent admin re-authentication, privileged-target
        guards, session cleanup, policy emission, and audit logging all happen
        in one place.
        """
        target_name = str(target or "-").strip() or "-"
        details = f"{event_name} disabled; use canonical HTTP admin route"
        if http_route:
            details += f" {http_route}"
        try:
            log_audit_event(actor, "blocked_socket_admin_action", target=target_name, details=details)
        except Exception:
            pass
        payload = {
            "success": False,
            "ok": False,
            "error": "This legacy Socket.IO admin write action is disabled. Use the Admin Panel instead.",
            "code": "socket_admin_action_disabled",
            "event": event_name,
        }
        if http_route:
            payload["http_route"] = http_route
        return payload

    @socketio.on("get_usage_stats")
    @jwt_required()
    def handle_get_usage_stats(data=None):
        user = get_jwt_identity()
        rejection = _reject_if_stale_socket_session(touch_activity=True)
        if rejection is not None:
            return rejection
        guard = _socket_event_guard(user, "get_usage_stats", data, default_max_bytes=32768, default_limit=60, default_window=60)
        if guard is not None:
            return guard

        lim, win = _parse_rate_limit(settings.get("admin_socket_read_rate_limit"), default_limit=120, default_window=60)
        try:
            win = int(settings.get("admin_socket_read_rate_window_sec") or win)
        except Exception:
            pass
        okrl, retry = _rl(f"adminsock:r:{user}", lim, win)
        if not okrl:
            return {"success": False, "error": "Rate limited", "retry_after": retry}

        if not check_user_permission(user, "admin:basic"):
            return {"success": False, "error": "No permission"}
        return {"success": True}


    @socketio.on("get_audit_logs")
    @jwt_required()
    def handle_get_audit_logs(data=None):
        user = get_jwt_identity()
        rejection = _reject_if_stale_socket_session(touch_activity=True)
        if rejection is not None:
            return rejection
        guard = _socket_event_guard(user, "get_audit_logs", data, default_max_bytes=32768, default_limit=60, default_window=60)
        if guard is not None:
            return guard

        lim, win = _parse_rate_limit(settings.get("admin_socket_read_rate_limit"), default_limit=120, default_window=60)
        try:
            win = int(settings.get("admin_socket_read_rate_window_sec") or win)
        except Exception:
            pass
        okrl, retry = _rl(f"adminsock:r:{user}", lim, win)
        if not okrl:
            return {"success": False, "error": "Rate limited", "retry_after": retry}

        if not check_user_permission(user, "admin:basic"):
            return {"success": False, "error": "No permission"}
        return {"success": True}


    @socketio.on("refresh_server_settings")
    @jwt_required()
    def handle_refresh_server_settings(data=None):
        user = get_jwt_identity()
        rejection = _reject_if_stale_socket_session(touch_activity=True)
        if rejection is not None:
            return rejection
        guard = _socket_event_guard(user, "refresh_server_settings", data, default_max_bytes=32768, default_limit=60, default_window=60)
        if guard is not None:
            return guard

        lim, win = _parse_rate_limit(settings.get("admin_socket_read_rate_limit"), default_limit=120, default_window=60)
        try:
            win = int(settings.get("admin_socket_read_rate_window_sec") or win)
        except Exception:
            pass
        okrl, retry = _rl(f"adminsock:r:{user}", lim, win)
        if not okrl:
            return {"success": False, "error": "Rate limited", "retry_after": retry}

        if not check_user_permission(user, "admin:basic"):
            return {"success": False, "error": "No permission"}
        return {"success": True}


    @socketio.on("purge_user")
    @jwt_required()
    def handle_purge_user(data):
        username = (data or {}).get("username")
        admin = get_jwt_identity()
        rejection = _reject_if_stale_socket_session(touch_activity=True)
        if rejection is not None:
            return rejection
        guard = _socket_event_guard(admin, "purge_user", data, default_max_bytes=32768, default_limit=60, default_window=60)
        if guard is not None:
            return guard

        if not username:
            return {"success": False, "ok": False, "error": "Missing username", "code": "missing_username"}

        if not check_user_permission(admin, "admin:basic"):
            return {"success": False, "ok": False, "error": "Admin required", "code": "permission_denied"}

        # This legacy Socket.IO event used to be a placeholder that returned
        # success without deleting anything. Keep the event registered so old
        # clients receive a clear ACK, but force real destructive user actions
        # through the HTTP admin route where CSRF, recent admin re-auth,
        # self-target guards, privileged-target guards, cleanup, and auditing
        # are all enforced in one canonical path.
        log_audit_event(admin, "blocked_socket_admin_action", target=username, details="purge_user disabled; use POST /admin/delete_user/<username>")
        return {
            "success": False,
            "ok": False,
            "error": "This legacy Socket.IO admin action is disabled. Use the Admin Panel delete-user action instead.",
            "code": "socket_admin_action_disabled",
            "http_route": "/admin/delete_user/<username>",
        }


    @socketio.on("update_user_role")
    @jwt_required()
    def handle_update_user_role(data):
        username = (data or {}).get("username")
        role = (data or {}).get("role")
        admin = get_jwt_identity()
        rejection = _reject_if_stale_socket_session(touch_activity=True)
        if rejection is not None:
            return rejection
        guard = _socket_event_guard(admin, "update_user_role", data, default_max_bytes=32768, default_limit=60, default_window=60)
        if guard is not None:
            return guard

        if not username or not role:
            return {"success": False, "ok": False, "error": "Missing fields", "code": "missing_fields"}

        if not (check_user_permission(admin, "admin:assign_role") or check_user_permission(admin, "admin:manage_roles")):
            return {"success": False, "ok": False, "error": "No permission", "code": "permission_denied"}

        # This legacy Socket.IO event used to be a placeholder that returned
        # success without changing RBAC. Keep the event registered so old
        # clients receive a clear ACK, but force role changes through the HTTP
        # admin route where CSRF, recent admin re-auth, self-target guards,
        # privileged-target guards, session revocation, and auditing are all
        # enforced in one canonical path.
        log_audit_event(admin, "blocked_socket_admin_action", target=username, details=f"update_user_role disabled; requested role={role}; use POST /admin/assign_role/<username>")
        return {
            "success": False,
            "ok": False,
            "error": "This legacy Socket.IO admin action is disabled. Use the Admin Panel role-assignment action instead.",
            "code": "socket_admin_action_disabled",
            "http_route": "/admin/assign_role/<username>",
        }

    @socketio.on("set_message_expiry")
    @jwt_required()
    def handle_set_message_expiry(data):
        """Legacy write event disabled; use canonical admin HTTP routes."""
        room = (data or {}).get("room")
        user = get_jwt_identity()
        rejection = _reject_if_stale_socket_session(touch_activity=True)
        if rejection is not None:
            return rejection
        guard = _socket_event_guard(user, "set_message_expiry", data, default_max_bytes=32768, default_limit=60, default_window=60)
        if guard is not None:
            return guard

        if not room:
            return {"success": False, "ok": False, "error": "Missing room", "code": "missing_room"}

        if not check_user_permission(user, "room:lock"):
            return {"success": False, "ok": False, "error": "Permission denied", "code": "permission_denied"}

        return _disabled_socket_admin_write(user, "set_message_expiry", target=room)

    @socketio.on("delete_all_messages")
    @jwt_required()
    def handle_delete_all_messages(data):
        room = (data or {}).get("room")
        user = get_jwt_identity()
        rejection = _reject_if_stale_socket_session(touch_activity=True)
        if rejection is not None:
            return rejection
        guard = _socket_event_guard(user, "delete_all_messages", data, default_max_bytes=32768, default_limit=60, default_window=60)
        if guard is not None:
            return guard

        if not room:
            return {"success": False, "ok": False, "error": "Missing room", "code": "missing_room"}
        if not check_user_permission(user, "room:lock"):
            return {"success": False, "ok": False, "error": "Permission denied", "code": "permission_denied"}

        return _disabled_socket_admin_write(user, "delete_all_messages", target=room, http_route="POST /admin/clear_room/<room>")

    @socketio.on("clear_room")
    @jwt_required()
    def handle_clear_room(data):
        room = (data or {}).get("room")
        user = get_jwt_identity()
        rejection = _reject_if_stale_socket_session(touch_activity=True)
        if rejection is not None:
            return rejection
        guard = _socket_event_guard(user, "clear_room", data, default_max_bytes=32768, default_limit=60, default_window=60)
        if guard is not None:
            return guard

        if not room:
            return {"success": False, "ok": False, "error": "Missing room", "code": "missing_room"}
        if not check_user_permission(user, "room:lock"):
            return {"success": False, "ok": False, "error": "Permission denied", "code": "permission_denied"}

        return _disabled_socket_admin_write(user, "clear_room", target=room, http_route="POST /admin/clear_room/<room>")


    @socketio.on("lock_room")
    @jwt_required()
    def handle_lock_room(data):
        room = (data or {}).get("room")
        user = get_jwt_identity()
        rejection = _reject_if_stale_socket_session(touch_activity=True)
        if rejection is not None:
            return rejection
        guard = _socket_event_guard(user, "lock_room", data, default_max_bytes=32768, default_limit=60, default_window=60)
        if guard is not None:
            return guard

        if not room:
            return {"success": False, "ok": False, "error": "Missing room", "code": "missing_room"}

        if not check_user_permission(user, "room:lock"):
            return {"success": False, "ok": False, "error": "No permission", "code": "permission_denied"}

        locked = bool((data or {}).get("locked", True))
        route = "POST /admin/lock_room/<room>" if locked else "POST /admin/unlock_room/<room>"
        return _disabled_socket_admin_write(user, "lock_room", target=room, http_route=route)


    @socketio.on("set_room_readonly")
    @jwt_required()
    def handle_set_room_readonly(data):
        room = (data or {}).get("room")
        user = get_jwt_identity()
        rejection = _reject_if_stale_socket_session(touch_activity=True)
        if rejection is not None:
            return rejection
        guard = _socket_event_guard(user, "set_room_readonly", data, default_max_bytes=32768, default_limit=60, default_window=60)
        if guard is not None:
            return guard

        if not room:
            return {"success": False, "ok": False, "error": "Missing room", "code": "missing_room"}

        if not check_user_permission(user, "room:readonly"):
            return {"success": False, "ok": False, "error": "No permission", "code": "permission_denied"}

        return _disabled_socket_admin_write(user, "set_room_readonly", target=room, http_route="POST /admin/set_room_readonly/<room>")

    @socketio.on("slowmode_toggle")
    @jwt_required()
    def handle_slowmode_toggle(data):
        data = data or {}
        room = data.get("room")
        user = get_jwt_identity()
        rejection = _reject_if_stale_socket_session(touch_activity=True)
        if rejection is not None:
            return rejection
        guard = _socket_event_guard(user, "slowmode_toggle", data, default_max_bytes=32768, default_limit=60, default_window=60)
        if guard is not None:
            return guard

        if not room:
            return {"success": False, "ok": False, "error": "Missing room", "code": "missing_room"}

        if not (
            check_user_permission(user, "admin:basic")
            or check_user_permission(user, "room:lock")
        ):
            return {"success": False, "ok": False, "error": "Permission denied", "code": "permission_denied"}

        return _disabled_socket_admin_write(user, "slowmode_toggle", target=room, http_route="POST /admin/set_room_slowmode/<room>")


