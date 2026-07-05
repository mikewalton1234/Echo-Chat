# antiabuse_exempt_staff compatibility: settings.get("antiabuse_exempt_staff", True)
"""Socket.IO handlers: files.

Auto-split from the legacy monolithic socket_handlers.py.
"""

import json
import re
import time
import uuid
import urllib.parse
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
    can_user_join_custom_room,
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

    def _p2p_bool_setting(name: str, default: bool = False) -> bool:
        raw = settings.get(name, default)
        if isinstance(raw, bool):
            return raw
        if raw is None:
            return bool(default)
        if isinstance(raw, (int, float)):
            return bool(raw)
        val = str(raw).strip().lower()
        if val in {"1", "true", "yes", "y", "on", "enabled"}:
            return True
        if val in {"0", "false", "no", "n", "off", "disabled", "none", "null", ""}:
            return False
        return bool(default)

    def _p2p_int_setting(name: str, default: int, *, min_value: int = 1, max_value: int = 10_000_000_000) -> int:
        try:
            val = int(settings.get(name, default))
        except Exception:
            val = int(default)
        return max(int(min_value), min(int(max_value), val))

    def _p2p_disabled() -> bool:
        return _p2p_bool_setting("disable_file_transfer_globally", False) or not _p2p_bool_setting("p2p_file_enabled", True)

    def _p2p_file_signal_limit():
        lim, win = _parse_rate_limit(settings.get("p2p_file_signal_rate_limit"), default_limit=600, default_window=60)
        win = _p2p_int_setting("p2p_file_signal_rate_window_sec", int(win or 60), min_value=1, max_value=3600)
        return lim, win


    def _p2p_upload_sanction_denial(username: str, *, role: str = "participant") -> str | None:
        """Return an error when a P2P file participant is upload-sanctioned.

        P2P uses browser-to-browser data channels, so the server cannot inspect
        the final payload after signaling succeeds. Treat an upload sanction as a
        full P2P-file participation ban, not just an offer/sender ban.
        """
        if is_user_sanctioned(username, "upload"):
            return "Uploads are disabled for this account" if role == "sender" else "File transfer is disabled for this account"
        return None

    def _p2p_participants_upload_allowed(a: str, b: str) -> tuple[bool, str | None]:
        """Require both P2P participants to be free of upload sanctions."""
        if _p2p_upload_sanction_denial(a):
            return False, "File transfer is disabled for this account"
        if _p2p_upload_sanction_denial(b):
            return False, "The other user cannot use file transfer"
        return True, None

    def _drop_p2p_file_session_for_pair(transfer_id, a, b) -> bool:
        """Remove an active P2P file session for this exact user pair."""
        if not _valid_id(transfer_id):
            return False
        with P2P_FILE_SESSIONS_LOCK:
            sess = P2P_FILE_SESSIONS.get(str(transfer_id))
            if not sess:
                return False
            if {sess.get("a"), sess.get("b")} != {a, b}:
                return False
            try:
                del P2P_FILE_SESSIONS[str(transfer_id)]
                try:
                    _mark_p2p_transfer_id_closed(transfer_id)
                except Exception:
                    pass
                return True
            except Exception:
                return False

    @socketio.on("p2p_file_offer")
    @jwt_required()
    def handle_p2p_file_offer(data):
        sender = get_jwt_identity()
        rejection = _reject_if_stale_socket_session(touch_activity=True)
        if rejection is not None:
            return rejection
        guard = _socket_event_guard(sender, "p2p_file_offer", data, default_max_bytes=65536, default_limit=120, default_window=60)
        if guard is not None:
            return guard

        if _p2p_disabled():
            return {"success": False, "error": "File sharing is disabled"}

        # Rate limit signalling to prevent abuse/spam.
        lim, win = _p2p_file_signal_limit()
        okrl, retry = _rl(f"p2p_sig:{sender}", lim, win)
        if not okrl:
            return {"success": False, "error": "Rate limited", "retry_after": retry}

        to = _resolve_canonical_username((data or {}).get("to"))
        transfer_id = (data or {}).get("transfer_id")
        offer = (data or {}).get("offer")
        meta = _sanitize_file_meta((data or {}).get("meta") or {})

        if not to or not transfer_id or not offer:
            return {"success": False, "error": "Missing fields"}

        if not _valid_id(transfer_id):
            return {"success": False, "error": "Invalid transfer_id"}

        try:
            if _p2p_transfer_id_recently_used(transfer_id):
                return {"success": False, "error": "transfer_id was recently used"}
        except Exception:
            pass

        ok, err = _require_not_sanctioned(sender, action="dm")
        if not ok:
            return {"success": False, "error": err}
        denied = _p2p_upload_sanction_denial(sender, role="sender")
        if denied:
            return {"success": False, "error": denied}

        if to == sender:
            return {"success": False, "error": "Cannot signal yourself"}

        denied = _p2p_upload_sanction_denial(to, role="receiver")
        if denied:
            return {"success": False, "error": "The other user cannot use file transfer"}

        if _either_blocked(sender, to):
            return {"success": False, "error": "Direct message blocked"}



        # Anti-abuse: file offer signaling burst rate limiting
        lim, win = _parse_rate_limit(settings.get("file_offer_rate_limit"), default_limit=5, default_window=60)
        try:
            win = int(settings.get("file_offer_rate_window_sec") or win)
        except Exception:
            pass
        okrl, retry = _rl(f"fileoffer:{sender}", lim, win)
        if not okrl:
            if _abuse_strike(sender, "file_offer_rate"):
                return {"success": False, "error": "Auto-muted for spamming. Try again later."}
            return {"success": False, "error": f"Rate limited (wait {retry:.1f}s)"}
        _cleanup_p2p_file_sessions()

        # Basic meta sanity (avoid UI spoof / absurd numbers).  P2P direct
        # messages must use the same size ceiling as encrypted DM server upload;
        # otherwise the P2P offer can be rejected while the server fallback works.
        # Equivalent to settings.get("max_dm_file_bytes"), but parsed through
        # _p2p_int_setting so bad hand-edited values cannot crash signaling.
        max_size = _p2p_int_setting(
            "max_dm_file_bytes",
            settings.get("max_attachment_size") or 10485760,
            min_value=1,
            max_value=1024 * 1024 * 1024,
        )
        if meta.get("size") is not None:
            if meta["size"] < 0 or meta["size"] > max_size:
                return {"success": False, "error": f"File too large (max {max_size} bytes)"}

        with P2P_FILE_SESSIONS_LOCK:
            existing = P2P_FILE_SESSIONS.get(transfer_id)
            if existing:
                a = existing.get("a")
                b = existing.get("b")
                state = str(existing.get("state") or "")
                if state in {"offered", "accepted"}:
                    return {"success": False, "error": "transfer_id already in use"}
                if {a, b} != {sender, to}:
                    return {"success": False, "error": "transfer_id already in use"}
            P2P_FILE_SESSIONS[transfer_id] = {
                "a": sender,
                "b": to,
                "state": "offered",
                "created": time.time(),
                "updated": time.time(),
                "meta": meta,
            }

        delivered = _emit_to_user(to, "p2p_file_offer", {
            "sender": sender,
            "transfer_id": transfer_id,
            "offer": offer,
            "meta": meta,
        })
        if not delivered:
            # Do not retain an orphaned pending transfer if the receiver has no live
            # Socket.IO session to receive the offer. Otherwise a later random ICE/
            # answer can see a stale session and the sender waits for a transfer that
            # the receiver never knew about.
            with P2P_FILE_SESSIONS_LOCK:
                sess = P2P_FILE_SESSIONS.get(transfer_id)
                if sess and sess.get("a") == sender and sess.get("b") == to:
                    try:
                        del P2P_FILE_SESSIONS[transfer_id]
                        _mark_p2p_transfer_id_closed(transfer_id)
                    except Exception:
                        pass
        return {"success": True, "delivered": delivered}


    @socketio.on("p2p_file_answer")
    @jwt_required()
    def handle_p2p_file_answer(data):
        sender = get_jwt_identity()
        rejection = _reject_if_stale_socket_session(touch_activity=True)
        if rejection is not None:
            return rejection
        guard = _socket_event_guard(sender, "p2p_file_answer", data, default_max_bytes=65536, default_limit=180, default_window=60)
        if guard is not None:
            return guard

        if _p2p_disabled():
            return {"success": False, "error": "File sharing is disabled"}

        # Rate limit signalling to prevent abuse/spam.
        lim, win = _p2p_file_signal_limit()
        okrl, retry = _rl(f"p2p_sig:{sender}", lim, win)
        if not okrl:
            return {"success": False, "error": "Rate limited", "retry_after": retry}

        to = _resolve_canonical_username((data or {}).get("to"))
        transfer_id = (data or {}).get("transfer_id")
        answer = (data or {}).get("answer")

        if not to or not transfer_id or not answer:
            return {"success": False, "error": "Missing fields"}

        if not _valid_id(transfer_id):
            return {"success": False, "error": "Invalid transfer_id"}

        ok, err = _require_not_sanctioned(sender, action="dm")
        if not ok:
            return {"success": False, "error": err}

        ok, err = _p2p_participants_upload_allowed(sender, to)
        if not ok:
            _drop_p2p_file_session_for_pair(transfer_id, sender, to)
            return {"success": False, "error": err}

        if to == sender:
            return {"success": False, "error": "Cannot signal yourself"}

        if _either_blocked(sender, to):
            _drop_p2p_file_session_for_pair(transfer_id, sender, to)
            return {"success": False, "error": "Direct message blocked"}

        _cleanup_p2p_file_sessions()

        with P2P_FILE_SESSIONS_LOCK:
            sess = P2P_FILE_SESSIONS.get(transfer_id)
            if not sess:
                return {"success": False, "error": "Unknown/expired transfer"}
            if sess.get("b") != sender or sess.get("a") != to:
                return {"success": False, "error": "Not a participant"}
            if str(sess.get("state") or "") != "offered":
                return {"success": False, "error": "Transfer is not waiting for an answer"}
            sess["state"] = "accepted"
            sess["updated"] = time.time()

        delivered = _emit_to_user(to, "p2p_file_answer", {
            "sender": sender,
            "transfer_id": transfer_id,
            "answer": answer,
        })
        return {"success": True, "delivered": delivered}


    @socketio.on("p2p_file_ice")
    @jwt_required()
    def handle_p2p_file_ice(data):
        sender = get_jwt_identity()
        rejection = _reject_if_stale_socket_session(touch_activity=True)
        if rejection is not None:
            return rejection
        guard = _socket_event_guard(sender, "p2p_file_ice", data, default_max_bytes=65536, default_limit=180, default_window=60)
        if guard is not None:
            return guard

        if _p2p_disabled():
            return {"success": False, "error": "File sharing is disabled"}

        # Rate limit signalling to prevent abuse/spam.
        lim, win = _p2p_file_signal_limit()
        okrl, retry = _rl(f"p2p_sig:{sender}", lim, win)
        if not okrl:
            return {"success": False, "error": "Rate limited", "retry_after": retry}

        to = _resolve_canonical_username((data or {}).get("to"))
        transfer_id = (data or {}).get("transfer_id")
        candidate = (data or {}).get("candidate")

        if not to or not transfer_id or not candidate:
            return {"success": False, "error": "Missing fields"}

        if not _valid_id(transfer_id):
            return {"success": False, "error": "Invalid transfer_id"}

        ok, err = _require_not_sanctioned(sender, action="dm")
        if not ok:
            return {"success": False, "error": err}

        ok, err = _p2p_participants_upload_allowed(sender, to)
        if not ok:
            _drop_p2p_file_session_for_pair(transfer_id, sender, to)
            return {"success": False, "error": err}

        if to == sender:
            return {"success": False, "error": "Cannot signal yourself"}

        if _either_blocked(sender, to):
            _drop_p2p_file_session_for_pair(transfer_id, sender, to)
            return {"success": False, "error": "Direct message blocked"}

        _cleanup_p2p_file_sessions()

        with P2P_FILE_SESSIONS_LOCK:
            sess = P2P_FILE_SESSIONS.get(transfer_id)
            if not sess:
                return {"success": False, "error": "Unknown/expired transfer"}
            if {sess.get("a"), sess.get("b")} != {sender, to}:
                return {"success": False, "error": "Not a participant"}
            if str(sess.get("state") or "") not in {"offered", "accepted"}:
                return {"success": False, "error": "Transfer is not active"}
            sess["updated"] = time.time()

        delivered = _emit_to_user(to, "p2p_file_ice", {
            "sender": sender,
            "transfer_id": transfer_id,
            "candidate": candidate,
        })
        return {"success": True, "delivered": delivered}


    @socketio.on("p2p_file_decline")
    @jwt_required()
    def handle_p2p_file_decline(data):
        sender = get_jwt_identity()
        rejection = _reject_if_stale_socket_session(touch_activity=True)
        if rejection is not None:
            return rejection
        guard = _socket_event_guard(sender, "p2p_file_decline", data, default_max_bytes=65536, default_limit=180, default_window=60)
        if guard is not None:
            return guard

        # Rate limit signalling to prevent abuse/spam.
        lim, win = _p2p_file_signal_limit()
        okrl, retry = _rl(f"p2p_sig:{sender}", lim, win)
        if not okrl:
            return {"success": False, "error": "Rate limited", "retry_after": retry}

        to = _resolve_canonical_username((data or {}).get("to"))
        transfer_id = (data or {}).get("transfer_id")
        reason = (data or {}).get("reason") or "Declined"

        if not to or not transfer_id:
            return {"success": False, "error": "Missing fields"}

        if not _valid_id(transfer_id):
            return {"success": False, "error": "Invalid transfer_id"}

        ok, err = _require_not_sanctioned(sender, action="dm")
        if not ok:
            return {"success": False, "error": err}

        if to == sender:
            return {"success": False, "error": "Cannot signal yourself"}

        _cleanup_p2p_file_sessions()

        with P2P_FILE_SESSIONS_LOCK:
            sess = P2P_FILE_SESSIONS.get(transfer_id)
            if not sess:
                if _either_blocked(sender, to):
                    return {"success": False, "error": "Direct message blocked"}
                # still notify peer (client may be waiting) but don't treat as failure
                sess_ok = True
            else:
                if {sess.get("a"), sess.get("b")} != {sender, to}:
                    return {"success": False, "error": "Not a participant"}
                # Allow participants to decline/end a transfer even if one of them
                # blocked the other after the offer was created. Cleanup/decline is
                # not a new file send; blocking it leaves stuck transfer cards.
                try:
                    del P2P_FILE_SESSIONS[transfer_id]
                    _mark_p2p_transfer_id_closed(transfer_id)
                except Exception:
                    pass
                sess_ok = True

        delivered = _emit_to_user(to, "p2p_file_decline", {
            "sender": sender,
            "transfer_id": transfer_id,
            "reason": reason,
        })
        return {"success": True, "delivered": delivered, "session": sess_ok}

    # ------------------------------------------------------------------
    # Voice chat (WebRTC audio) signaling + room roster
    # ------------------------------------------------------------------

    def _room_file_placeholder_access(user: str, room: str):
        room = str(room or "").strip()
        if not room or len(room) > 120:
            return False, "Missing room"
        sid = request.sid
        if get_connected_room(sid) != room and not check_user_permission(user, "admin:basic"):
            return False, "Not in that room"
        try:
            meta = get_custom_room_meta(room)
        except Exception:
            meta = None
        if is_user_sanctioned(user, f"room_ban:{room}") and not check_user_permission(user, "admin:basic"):
            return False, "You are banned from this room"
        if meta and meta.get("is_private"):
            try:
                if not can_user_access_custom_room(room, user) and not check_user_permission(user, "admin:basic"):
                    return False, "No access to that room"
            except Exception:
                return False, "No access to that room"
        return True, ""

    @socketio.on("list_files_in_room")
    @jwt_required()
    def handle_list_files_in_room(data):
        payload = data or {}
        user = get_jwt_identity()
        rejection = _reject_if_stale_socket_session(touch_activity=True)
        if rejection is not None:
            return rejection
        guard = _socket_event_guard(user, "list_files_in_room", payload, default_max_bytes=4096, default_limit=30, default_window=60)
        if guard is not None:
            return guard

        room = str(payload.get("room") or "").strip()
        ok, err = _room_file_placeholder_access(user, room)
        if not ok:
            return {"success": False, "error": err}

        # Intentional placeholder: there is no room-wide file inventory table yet.
        # Do not pretend this feature is implemented or leak file metadata from
        # DM/group scopes. Clients can safely render an empty state.
        return {
            "success": True,
            "supported": False,
            "files": [],
            "count": 0,
            "message": "Room file inventory is not implemented yet.",
        }


    def _sanitize_shared_image_url(raw):
        if raw is None:
            return ""
        url = str(raw).strip()
        if not url:
            return ""
        if len(url) > 1024:
            url = url[:1024]
        if any(ch.isspace() for ch in url):
            return None
        try:
            parsed = urllib.parse.urlparse(url)
        except Exception:
            return None

        if parsed.scheme in {"http", "https"} and parsed.netloc:
            return url

        if parsed.scheme in {"", None}:
            path = str(parsed.path or "")
            allowed_local_prefixes = (
                "/media/",
                "/static/",
                "/uploads/",
            )
            if any(path.startswith(prefix) for prefix in allowed_local_prefixes):
                return url

        return None


    @socketio.on("share_image")
    @jwt_required()
    def handle_share_image(data):
        payload = data or {}
        room = payload.get("room")
        image_url = _sanitize_shared_image_url(payload.get("image_url"))
        user = get_jwt_identity()
        rejection = _reject_if_stale_socket_session(touch_activity=True)
        if rejection is not None:
            return rejection
        guard = _socket_event_guard(user, "share_image", payload, default_max_bytes=8192, default_limit=30, default_window=60)
        if guard is not None:
            return guard

        if not room or not image_url:
            return {"success": False, "error": "Missing room or image_url"}

        ok, err = _require_not_sanctioned(user, action="send")
        if not ok:
            return {"success": False, "error": err}

        sid = request.sid
        current_room = get_connected_room(sid)
        if current_room != room:
            return {"success": False, "error": "Not in that room"}

        ok_access, access_error = _room_file_placeholder_access(user, room)
        if not ok_access:
            return {"success": False, "error": access_error}

        if _room_readonly(room) and not (
            check_user_permission(user, "admin:basic") or check_user_permission(user, "room:readonly")
        ):
            return {"success": False, "error": "Room is read-only"}

        if _room_locked(room) and not (
            check_user_permission(user, "admin:basic") or check_user_permission(user, "room:lock")
        ):
            return {"success": False, "error": "Room is locked"}

        lim, win = _parse_rate_limit(settings.get("share_image_rate_limit"), default_limit=6, default_window=20)
        try:
            win = int(settings.get("share_image_rate_window_sec") or win)
        except Exception:
            pass
        okrl, retry = _rl(f"shareimg:{user}", lim, win)
        if not okrl:
            if _abuse_strike(user, "share_image_rate"):
                return {"success": False, "error": "Auto-muted for spamming. Try again later."}
            return {"success": False, "error": f"Rate limited (wait {retry:.1f}s)"}

        try:
            touch_custom_room_activity(room)
        except Exception:
            pass

        emit("notification", f"{user} shared an image", to=room)
        emit("image_shared", {"from": user, "url": image_url, "placeholder": True, "persisted": False}, to=room)
        return {"success": True}


