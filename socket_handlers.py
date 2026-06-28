#!/usr/bin/env python3
"""
socket_handlers.py

PostgreSQL‐adapted Socket.IO event handlers for Echo Chat Server.
All SQLite usages have been replaced with get_db() (PostgreSQL via psycopg2).
"""

import json
import re
import time
import uuid
import threading
from collections import deque

from flask import request
from socket_auth import jwt_required, get_jwt_identity, get_jwt
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
    close_db,
    get_custom_room_meta,
    can_user_access_custom_room,
    can_user_join_custom_room,
    touch_custom_room_activity,
    consume_room_invites,
    set_room_message_expiry,
    get_room_message_expiry,
    get_auth_session_state,
    revoke_auth_session,
    touch_auth_session_activity,
    _official_room_names_from_json,
)
from security import log_audit_event
from realtime.socket_abuse import socket_connect_guard, socket_event_guard
from permissions import check_user_permission
from moderation import is_user_sanctioned, mute_user
from account_status import account_can_authenticate, account_status_error_code, account_status_reason, is_effectively_shadowbanned
from room_name_policy import validate_room_name_format
from echo_voice_protocol import echo_voice_room_capacity, echo_voice_room_limit

# Shared in-memory state is centralized in realtime.state so handler modules can be split safely.
from realtime.state import (
    _SEND_HISTORY,
    CONNECTED_USERS, CONNECTED_USERS_LOCK,
    TYPING_STATUS, TYPING_STATUS_LOCK, TYPING_EXPIRY_SECONDS,
    P2P_FILE_SESSIONS, P2P_FILE_RECENT_TRANSFER_IDS, P2P_FILE_SESSIONS_LOCK,
    VOICE_DM_SESSIONS, VOICE_DM_SESSIONS_LOCK,
    MESSAGE_REACTIONS, MESSAGE_REACTIONS_LOCK,
    VOICE_ROOMS, VOICE_ROOMS_LOCK,
    VOICE_INVITE_LAST,
    ALLOWED_REACTION_EMOJIS,
    ROOM_SLOWMODE_CACHE as _ROOM_SLOWMODE_CACHE,
    ROOM_SLOWMODE_CACHE_LOCK as _ROOM_SLOWMODE_CACHE_LOCK,
    set_room_slowmode_cache as _set_room_slowmode_cache,
    connected_room_targets,
    live_room_counts as shared_live_room_counts,
    room_users as shared_room_users,
    user_sids as shared_user_sids,
)




# Shared in-memory rate limits for private group socket actions.
# These must live at module scope because _group_rl() is defined inside
# register_socketio_handlers() but is exported into split realtime modules
# through the helper context.
_GROUP_RATE: dict[str, deque] = {}
_GROUP_RATE_LOCK = threading.Lock()


def register_socketio_handlers(socketio, settings):
    """
    Registers all Socket.IO event handlers. Uses PostgreSQL via get_db() for persistence.
    """

    # Shared realtime state is configured in server_init.create_app() so startup
    # can fail loudly for scaled deployments instead of hiding Redis failures.

    def _user_sids(username: str) -> list[str]:
        """Return all active Socket.IO session IDs for a given username."""
        try:
            return list(shared_user_sids(username))
        except Exception:
            with CONNECTED_USERS_LOCK:
                return [sid for sid, u in CONNECTED_USERS.items() if u.get("username") == username]

    def _emit_to_user(username: str, event: str, payload) -> bool:
        """Emit an event to all connected sessions for a username. Returns True if delivered."""
        sids = _user_sids(username)
        for sid in sids:
            emit(event, payload, to=sid)
        return bool(sids)


    def _socket_event_guard(username: str, event_name: str, data=None, *, default_max_bytes: int = 65536, default_limit: int = 180, default_window: int = 60):
        """Central Socket.IO payload/rate guard exported to split modules."""
        return socket_event_guard(
            settings,
            event_name,
            data,
            username=username,
            default_max_bytes=default_max_bytes,
            default_limit=default_limit,
            default_window=default_window,
        )

    def _socket_connect_guard(username: str, auth_session_id: str | None, sid: str) -> bool:
        """Central Socket.IO connect-storm/session-count guard."""
        return socket_connect_guard(settings, username=username, auth_session_id=auth_session_id, sid=sid)

    def _is_blocked(blocker: str, blocked: str) -> bool:
        """True if `blocker` has blocked `blocked` (case-insensitive)."""
        blocker = str(blocker or "").strip()
        blocked = str(blocked or "").strip()
        if not blocker or not blocked:
            return False
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT 1
                  FROM blocks
                 WHERE LOWER(blocker) = LOWER(%s)
                   AND LOWER(blocked) = LOWER(%s)
                 LIMIT 1;
                """,
                (blocker, blocked),
            )
            return cur.fetchone() is not None

    def _either_blocked(a: str, b: str) -> bool:
        """True if either direction is blocked."""
        return _is_blocked(a, b) or _is_blocked(b, a)

    def _resolve_canonical_username(raw_username: str | None) -> str | None:
        """Return the canonical stored username for a login name, or None if absent.

        Uses a case-insensitive lookup so DM-style entry points do not create
        ghost deliveries or offline queue rows for casing variants / typos.
        """
        username = str(raw_username or "").strip()
        if not username:
            return None
        conn = get_db()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT username FROM users WHERE LOWER(username)=LOWER(%s) LIMIT 1;",
                    (username,),
                )
                row = cur.fetchone()
                return str(row[0]) if row and row[0] else None
        finally:
            try:
                close_db()
            except Exception:
                pass

    def _resolve_idle_logout_seconds() -> float | None:
        idle_hours = settings.get("idle_logout_hours", 8)
        try:
            idle_hours = float(idle_hours) if idle_hours is not None else 8.0
        except Exception:
            idle_hours = 8.0
        return (idle_hours * 3600.0) if idle_hours and idle_hours > 0 else None

    def _socket_session_failure_message(error: str) -> str:
        code = str(error or "session_revoked").strip().lower()
        if code == "idle_timeout":
            return "Your session expired from inactivity. Please sign in again."
        if code == "missing_session":
            return "Your session is missing realtime auth state. Please sign in again."
        if code == "session_check_failed":
            return "Realtime session validation failed. Please sign in again."
        if code == "unauthorized":
            return "You need to sign in again before using realtime features."
        return "Your session was revoked. Please sign in again."

    def _socket_session_failure_payload(error: str, username: str | None = None) -> dict:
        code = str(error or "session_revoked").strip() or "session_revoked"
        payload = {"success": False, "error": code, "reason": _socket_session_failure_message(code), "code": code}
        if username:
            payload["username"] = username
        return payload

    def _require_account_auth_allowed(username: str | None) -> tuple[bool, str | None, str, str]:
        """Gate realtime sessions on effective account lifecycle status."""
        clean = str(username or "").strip()
        if not clean:
            return False, None, "unauthorized", "You need to sign in again before using realtime features."
        return account_can_authenticate(clean)

    def _account_status_socket_payload(username: str, status: str | None, code: str, reason: str) -> dict:
        return {
            "success": False,
            "error": code or "account_not_active",
            "code": code or "account_not_active",
            "reason": reason or account_status_reason(status),
            "account_status": status,
            "username": username,
        }


    def _is_effectively_shadowbanned(username: str | None) -> bool:
        try:
            return bool(is_effectively_shadowbanned(str(username or "").strip()))
        except Exception:
            return False

    def _require_live_socket_session(*, touch_activity: bool = False, disconnect_on_failure: bool = True):
        username = None
        try:
            username = str(get_jwt_identity() or "").strip()
        except Exception:
            username = None
        try:
            claims = get_jwt() or {}
        except Exception:
            claims = {}
        auth_session_id = str(claims.get("sid") or "").strip()

        failure_code = None
        state = None
        if not username:
            failure_code = "unauthorized"
        elif not auth_session_id:
            failure_code = "missing_session"
        else:
            try:
                state = get_auth_session_state(auth_session_id)
            except Exception:
                failure_code = "session_check_failed"
            if failure_code is None:
                if state is None or state.get("revoked_at") is not None:
                    failure_code = "session_revoked"
                else:
                    allowed, account_status, account_code, account_reason = _require_account_auth_allowed(username)
                    if not allowed:
                        try:
                            revoke_auth_session(auth_session_id, reason=account_code or "account_not_active")
                        except Exception:
                            pass
                        payload = _account_status_socket_payload(username, account_status, account_code, account_reason)
                        if disconnect_on_failure:
                            try:
                                emit("force_logout", payload, to=request.sid)
                            except Exception:
                                pass
                            try:
                                disconnect(sid=request.sid)
                            except Exception:
                                pass
                        return None, None, None, payload
                    max_idle_seconds = _resolve_idle_logout_seconds()
                    if max_idle_seconds is not None:
                        last_activity = state.get("last_activity")
                        if last_activity is not None:
                            from datetime import datetime, timezone
                            now = datetime.now(timezone.utc)
                            idle_for = (now - last_activity).total_seconds()
                            if idle_for > max_idle_seconds:
                                try:
                                    revoke_auth_session(auth_session_id, reason="idle_timeout")
                                except Exception:
                                    pass
                                failure_code = "idle_timeout"

        if failure_code is not None:
            payload = _socket_session_failure_payload(failure_code, username=username)
            if disconnect_on_failure:
                try:
                    emit("force_logout", payload, to=request.sid)
                except Exception:
                    pass
                try:
                    disconnect(sid=request.sid)
                except Exception:
                    pass
            return None, None, None, payload

        try:
            if touch_activity and auth_session_id:
                touch_auth_session_activity(auth_session_id)
        except Exception:
            payload = _socket_session_failure_payload("session_touch_failed", username=username)
            if disconnect_on_failure:
                try:
                    emit("force_logout", payload, to=request.sid)
                except Exception:
                    pass
                try:
                    disconnect(sid=request.sid)
                except Exception:
                    pass
            return None, None, None, payload

        return username, auth_session_id, state, None

    def _reject_if_stale_socket_session(*, touch_activity: bool = False, disconnect_on_failure: bool = True):
        _username, _auth_session_id, _state, rejection = _require_live_socket_session(
            touch_activity=touch_activity,
            disconnect_on_failure=disconnect_on_failure,
        )
        if rejection is None:
            return None
        try:
            event_name = str((getattr(request, "event", None) or {}).get("message") or "")
        except Exception:
            event_name = ""
        if event_name == "connect":
            return False
        return rejection


    # ───────────────────────────────────────────────────────────────────────
    # Live room counts (computed from active sessions)
    #
    # More reliable than DB member_count because Socket.IO events can execute
    # outside a normal Flask request lifecycle (no Flask app context), and
    # users may have multiple tabs. We count UNIQUE usernames per room.
    # ───────────────────────────────────────────────────────────────────────
    def _live_room_counts() -> dict[str, int]:
        try:
            return dict(shared_live_room_counts())
        except Exception:
            per_room: dict[str, set[str]] = {}
            with CONNECTED_USERS_LOCK:
                for _sid, sess in CONNECTED_USERS.items():
                    try:
                        r = sess.get("room")
                        u = sess.get("username")
                    except Exception:
                        continue
                    if not r or not u:
                        continue
                    per_room.setdefault(str(r), set()).add(str(u))
            return {room: len(users) for room, users in per_room.items()}
    
    def _emit_room_counts_snapshot(*, to_sid: str | None = None) -> None:
        payload = {"counts": _live_room_counts(), "ts": time.time()}
        try:
            if to_sid:
                emit("room_counts", payload, to=to_sid)
            else:
                socketio.emit("room_counts", payload)
        except Exception:
            pass
    
    
    # Live room user lists (computed from active sessions)
    def _live_room_users(room: str) -> list[str]:
        room = str(room or "").strip()
        if not room:
            return []
        try:
            return list(shared_room_users(room))
        except Exception:
            users: set[str] = set()
            with CONNECTED_USERS_LOCK:
                for _sid, sess in CONNECTED_USERS.items():
                    try:
                        if str(sess.get("room") or "") != room:
                            continue
                        u = sess.get("username")
                        if u:
                            users.add(str(u))
                    except Exception:
                        continue
            return sorted(users)

    def _emit_room_users_snapshot(room: str, *, to_sid: str | None = None) -> dict:
        """Emit and return a bounded, de-duplicated users-panel snapshot."""
        room_name = str(room or "").strip()
        payload = {"room": room_name, "users": [], "count": 0, "ts": time.time(), "source": "live_roster"}
        try:
            users = set()
            for raw in _live_room_users(room_name):
                name = str(raw or "").strip()
                if name:
                    users.add(name)

            # Self-heal a stale roster edge case: if the caller is already
            # recorded in this room locally but the shared roster lookup has not
            # caught up yet, never send that caller an impossible empty roster.
            current_user = ""
            self_healed_empty_roster = False
            if to_sid:
                try:
                    from realtime.state import get_connected_session
                    sess = get_connected_session(to_sid)
                    if sess and str(sess.get("room") or "").strip() == room_name:
                        caller = str(sess.get("username") or "").strip()
                        if caller:
                            current_user = caller
                            self_healed_empty_roster = not bool(users)
                            users.add(caller)
                except Exception:
                    pass

            sorted_users = sorted(users, key=lambda u: u.lower())
            payload.update({
                "users": sorted_users,
                "count": len(sorted_users),
                "current_user": current_user,
                "self_healed_empty_roster": bool(self_healed_empty_roster),
            })
            if to_sid:
                emit("room_users", payload, to=to_sid)
            else:
                socketio.emit("room_users", payload, room=room_name)
        except Exception:
            try:
                if to_sid:
                    emit("room_users", payload, to=to_sid)
            except Exception:
                pass
        return payload

    def _active_sanction_detail(username: str, sanction_type: str) -> tuple[str | None, str | None]:
        """Return (reason, expires_at_iso) for the most recent active sanction of this type."""
        try:
            conn = get_db()
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT reason, expires_at
                      FROM user_sanctions
                     WHERE username = %s
                       AND sanction_type = %s
                       AND (expires_at IS NULL OR expires_at > NOW())
                     ORDER BY created_at DESC
                     LIMIT 1;
                    """,
                    (username, sanction_type),
                )
                row = cur.fetchone()
            if not row:
                return None, None
            reason = row[0]
            expires_at = row[1]
            exp_iso = None
            try:
                exp_iso = expires_at.isoformat() if expires_at else None
            except Exception:
                exp_iso = None
            return (str(reason).strip() if reason else None), exp_iso
        except Exception:
            return None, None

    def _format_sanction_message(username: str, sanction_type: str, base: str) -> str:
        reason, exp_iso = _active_sanction_detail(username, sanction_type)
        msg = base
        if reason:
            msg += f" Reason: {reason}"
        if exp_iso:
            msg += f" Until: {exp_iso}"
        return msg

    def _require_not_sanctioned(username: str, action: str) -> tuple[bool, str | None]:
        """Gate actions on sanctions.

        Returns (ok, error_message).
        """
        if is_user_sanctioned(username, "ban"):
            return False, "You are banned."
        if action in {"send", "dm", "voice"} and is_user_sanctioned(username, "mute"):
            return False, "You are muted."
        if action == "join" and is_user_sanctioned(username, "kick"):
            return False, "You are temporarily kicked."
        return True, None


    # ------------------------------------------------------------------
    # In-memory session registries (P2P file transfer + 1:1 voice calls)
    # ------------------------------------------------------------------
    _ID_RE = re.compile(r"^[a-zA-Z0-9_.\-]{8,80}$")

    def _valid_id(val) -> bool:
        try:
            return bool(val) and bool(_ID_RE.match(str(val)))
        except Exception:
            return False

    def _sanitize_file_meta(meta: dict) -> dict:
        meta = meta or {}
        name = str(meta.get("name") or "").strip()
        if name:
            name = name[:200]

        mime = str(meta.get("mime") or meta.get("type") or "").strip()
        if mime:
            mime = mime[:100]

        size_raw = meta.get("size")
        size = None
        try:
            if size_raw is not None:
                size = int(size_raw)
        except Exception:
            size = None

        out = {}
        if name:
            out["name"] = name
        if mime:
            out["mime"] = mime
        if size is not None:
            out["size"] = size
        return out

    def _safe_p2p_int_setting(name: str, default: int, *, min_value: int = 1, max_value: int = 86400) -> int:
        try:
            val = int(settings.get(name, default))
        except Exception:
            val = int(default)
        return max(int(min_value), min(int(max_value), val))

    def _mark_p2p_transfer_id_closed(transfer_id, ttl: int | None = None) -> None:
        if not _valid_id(transfer_id):
            return
        ttl_seconds = int(ttl or _safe_p2p_int_setting("p2p_file_recent_id_ttl_seconds", 300, min_value=30, max_value=3600))
        P2P_FILE_RECENT_TRANSFER_IDS[str(transfer_id)] = time.time() + ttl_seconds

    def _p2p_transfer_id_recently_used(transfer_id) -> bool:
        if not _valid_id(transfer_id):
            return False
        now = time.time()
        expires = P2P_FILE_RECENT_TRANSFER_IDS.get(str(transfer_id))
        if not expires:
            return False
        try:
            if float(expires) > now:
                return True
        except Exception:
            pass
        P2P_FILE_RECENT_TRANSFER_IDS.pop(str(transfer_id), None)
        return False

    def _cleanup_p2p_file_sessions() -> None:
        ttl = _safe_p2p_int_setting("p2p_file_session_ttl_seconds", 900, min_value=30, max_value=86400)
        now = time.time()
        with P2P_FILE_SESSIONS_LOCK:
            stale = [
                tid for tid, s in P2P_FILE_SESSIONS.items()
                if (now - float(s.get("updated", s.get("created", now)))) > ttl
            ]
            for tid in stale:
                try:
                    del P2P_FILE_SESSIONS[tid]
                    _mark_p2p_transfer_id_closed(tid)
                except Exception:
                    pass
            expired_recent = [tid for tid, expires in P2P_FILE_RECENT_TRANSFER_IDS.items() if float(expires or 0) <= now]
            for tid in expired_recent:
                P2P_FILE_RECENT_TRANSFER_IDS.pop(tid, None)

    def _cleanup_voice_dm_sessions() -> None:
        invite_ttl = float(settings.get("voice_dm_invite_ttl_seconds", 90) or 90)
        active_ttl = float(settings.get("voice_dm_active_ttl_seconds", 3600) or 3600)
        now = time.time()
        with VOICE_DM_SESSIONS_LOCK:
            stale = []
            for cid, s in VOICE_DM_SESSIONS.items():
                state = str(s.get("state") or "")
                updated = float(s.get("updated", s.get("created", now)))
                ttl = invite_ttl if state == "invited" else active_ttl
                if (now - updated) > ttl:
                    stale.append(cid)
            for cid in stale:
                try:
                    del VOICE_DM_SESSIONS[cid]
                except Exception:
                    pass

    def _voice_dm_end_for_users(a: str, b: str, call_id: str, reason: str) -> None:
        # Best-effort notify both sides (other side will ignore if not in UI state).
        payload = {"sender": a, "call_id": call_id, "reason": reason}
        _emit_to_user(b, "voice_dm_end", payload)


    # ------------------------------------------------------------------
    # Voice helpers (in-memory roster)
    # ------------------------------------------------------------------
    def _voice_room_users(room: str) -> list[str]:
        with VOICE_ROOMS_LOCK:
            users = VOICE_ROOMS.get(room) or set()
            return sorted(users)

    def _voice_room_add(room: str, username: str) -> tuple[bool, str | None, list[str]]:
        """Add user to Echo Voice roster. Returns (ok, error, roster)."""
        max_peers = echo_voice_room_limit(settings)
        with VOICE_ROOMS_LOCK:
            s = VOICE_ROOMS.setdefault(room, set())
            if username in s:
                return True, None, sorted(s)
            if max_peers > 0 and len(s) >= max_peers:
                return False, "Voice room is full.", sorted(s)
            s.add(username)
            return True, None, sorted(s)

    def _voice_room_remove(room: str, username: str) -> bool:
        with VOICE_ROOMS_LOCK:
            s = VOICE_ROOMS.get(room)
            if not s or username not in s:
                return False
            s.discard(username)
            if not s:
                try:
                    del VOICE_ROOMS[room]
                except Exception:
                    pass
            return True


    # ------------------------------------------------------------------
    # Presence / status helpers
    # ------------------------------------------------------------------
    _ALLOWED_PRESENCE = {"online", "away", "busy", "invisible"}

    def _normalize_presence(val):
        """Normalize/validate presence strings. Returns a valid value or None."""
        if val is None:
            return None
        v = str(val).strip().lower()
        if v in {"available", "default"}:
            v = "online"
        if v in {"offline", "appear_offline", "appear-offline"}:
            v = "invisible"
        return v if v in _ALLOWED_PRESENCE else None

    def _sanitize_custom_status(val):
        """Trim + clamp to 128 chars. Returns None for empty/whitespace."""
        if val is None:
            return None
        s = str(val).strip()
        if not s:
            return None
        if len(s) > 128:
            return s[:128]
        return s

    def _public_presence_snapshot_from_row(username, online, presence_status, custom_status, last_seen, avatar_url=None):
        username = str(username or "").strip()
        pres = _normalize_presence(presence_status) or "online"
        # Server-side live session tracking is the source of truth for whether a user
        # is actually online. The DB flag is best-effort and can get stuck after
        # crashes, reloads, or missed disconnect cleanup.
        effective_online = bool(shared_user_sids(username)) if username else bool(online)
        visible_online = effective_online and pres != "invisible"
        visible_presence = "offline" if not visible_online else pres
        visible_custom = custom_status if visible_online else None
        ls = None if effective_online else (last_seen.isoformat() if last_seen else None)
        return {
            "username": username,
            "online": bool(visible_online),
            "presence": str(visible_presence),
            "custom_status": visible_custom,
            "last_seen": ls,
            "avatar_url": str(avatar_url or "").strip(),
        }

    def _get_user_presence_row(username: str):
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT online, presence_status, custom_status, last_seen, avatar_url
                  FROM users
                 WHERE username = %s;
                """,
                (username,),
            )
            row = cur.fetchone()
        if not row:
            return {"online": False, "presence_status": "offline", "custom_status": None, "last_seen": None, "avatar_url": ""}
        db_online, presence_status, custom_status, last_seen, avatar_url = row
        effective_online = bool(shared_user_sids(username)) if username else bool(db_online)
        return {
            "online": effective_online,
            "presence_status": _normalize_presence(presence_status) or "online",
            "custom_status": custom_status,
            "last_seen": None if effective_online else last_seen,
            "avatar_url": avatar_url or "",
        }

    def _public_presence_snapshot(username: str):
        row = _get_user_presence_row(username)
        return _public_presence_snapshot_from_row(
            username,
            row.get("online"),
            row.get("presence_status"),
            row.get("custom_status"),
            row.get("last_seen"),
            row.get("avatar_url"),
        )

    def _public_presence_for_user(username: str):
        """Compatibility alias exported to split social handlers.

        Friend-request acceptance and pair refresh code expect this helper name
        when pushing the new friend's current public presence snapshot.
        """
        return _public_presence_snapshot(username)

    def _self_presence_snapshot(username: str):
        row = _get_user_presence_row(username)
        return {
            "presence": row.get("presence_status") or "online",
            "custom_status": row.get("custom_status") or "",
        }

    def _broadcast_presence_to_friends(username: str) -> None:
        """Send the viewer-safe presence snapshot to all of the user's friends."""
        try:
            friends = get_friends_for_user(username) or []
            snap = _public_presence_snapshot(username)
            for f in friends:
                _emit_to_user(f, "friend_presence_update", snap)
        except Exception:
            return

    def _room_locked(room: str) -> bool:
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT locked FROM room_locks WHERE room = %s;",
                (room,),
            )
            row = cur.fetchone()
        return bool(row and row[0])

    def _room_readonly(room: str) -> bool:
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT readonly FROM room_readonly WHERE room = %s;",
                (room,),
            )
            row = cur.fetchone()
        return bool(row and row[0])

    # Slowmode cache + per-user last-sent tracking
    # room -> (seconds, fetched_at_epoch).  The cache is shared through realtime.state
    # so HTTP admin changes take effect immediately in Socket.IO enforcement.
    # (username, room) -> last_sent_epoch
    _SLOWMODE_LAST_SENT: dict[tuple[str, str], float] = {}
    _SLOWMODE_LAST_SENT_LOCK = threading.Lock()

    def _room_slowmode_seconds(room: str) -> int:
        """Return slowmode interval in seconds for a room (0 => off).

        Backed by the room_slowmode table; falls back to settings['room_slowmode_default_sec']
        if no row exists. Cached briefly to reduce DB pressure.
        """
        try:
            ttl = float(settings.get('room_slowmode_cache_ttl_sec') or 10)
        except Exception:
            ttl = 10.0
        now = time.time()
        with _ROOM_SLOWMODE_CACHE_LOCK:
            hit = _ROOM_SLOWMODE_CACHE.get(room)
            if hit and (now - float(hit[1])) < ttl:
                try:
                    return int(hit[0])
                except Exception:
                    return 0

        sec = 0
        has_room_override = False
        try:
            conn = get_db()
            with conn.cursor() as cur:
                cur.execute('SELECT seconds FROM room_slowmode WHERE room = %s;', (room,))
                row = cur.fetchone()
            if row and row[0] is not None:
                has_room_override = True
                sec = int(row[0])
        except Exception:
            sec = 0
            has_room_override = False

        # Only use the global default when the room has no explicit row.
        # A row with seconds=0 means an admin intentionally disabled slowmode for this room.
        if not has_room_override and sec <= 0:
            try:
                sec = int(settings.get('room_slowmode_default_sec') or 0)
            except Exception:
                sec = 0

        sec = max(0, min(int(sec), 3600))
        try:
            _set_room_slowmode_cache(room, sec)
        except Exception:
            with _ROOM_SLOWMODE_CACHE_LOCK:
                _ROOM_SLOWMODE_CACHE[room] = (sec, now)
        return sec


    def _push_room_policy_state(room: str, set_by: str | None = None) -> None:
        """Emit per-user room policy state to all connected members of a room."""
        room = (room or '').strip()
        if not room:
            return

        try:
            locked = _room_locked(room)
        except Exception:
            locked = False
        try:
            readonly = _room_readonly(room)
        except Exception:
            readonly = False
        try:
            slow = _room_slowmode_seconds(room)
        except Exception:
            slow = 0

        # Snapshot targets without holding the lock during emits
        targets: list[tuple[str, str]] = []
        try:
            targets = list(connected_room_targets(room))
        except Exception:
            try:
                with CONNECTED_USERS_LOCK:
                    for sid, u in CONNECTED_USERS.items():
                        if (u or {}).get("room") != room:
                            continue
                        uname = (u or {}).get("username")
                        if uname:
                            targets.append((sid, uname))
            except Exception:
                targets = []

        for sid, uname in targets:
            # Per-user override rules (RBAC)
            try:
                bypass_lock = bool(
                    check_user_permission(uname, "admin:basic")
                    or check_user_permission(uname, "room:lock")
                )
            except Exception:
                bypass_lock = False
            try:
                bypass_ro = bool(
                    check_user_permission(uname, "admin:basic")
                    or check_user_permission(uname, "room:readonly")
                )
            except Exception:
                bypass_ro = False

            can_send = (not locked or bypass_lock) and (not readonly or bypass_ro)
            block_reason = None
            if not can_send:
                if readonly and not bypass_ro:
                    block_reason = "read_only"
                elif locked and not bypass_lock:
                    block_reason = "locked"
                else:
                    block_reason = "blocked"

            payload = {
                "room": room,
                "locked": bool(locked),
                "readonly": bool(readonly),
                "slowmode_seconds": int(slow or 0),
                "can_send": bool(can_send),
                "can_override_lock": bool(bypass_lock),
                "can_override_readonly": bool(bypass_ro),
                "block_reason": block_reason,
            }
            if set_by:
                payload["set_by"] = set_by

            try:
                emit("room_policy_state", payload, to=sid)
            except Exception:
                pass

    def _store_offline_pm(sender: str, receiver: str, cipher: str) -> None:
        """Persist ciphertext for later delivery (server never decrypts)."""
        receiver = _resolve_canonical_username(receiver)
        if not receiver:
            try:
                print(f"[offline_pms] dropped_invalid_receiver sender={sender!r} receiver={receiver!r}")
            except Exception:
                pass
            return
        if _either_blocked(sender, receiver):
            try:
                print(f"[offline_pms] dropped_blocked_pair sender={sender!r} receiver={receiver!r}")
            except Exception:
                pass
            return
        conn = get_db()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO offline_messages (sender, receiver, message, delivered)
                    VALUES (%s, %s, %s, FALSE);
                    """,
                    (sender, receiver, cipher),
                )
            conn.commit()
        except Exception as e:
            print(f"[DB ERROR] store_offline_pm: {e}")
        finally:
            # Socket.IO handlers do not reliably trigger Flask teardown hooks.
            # Ensure pooled connections are returned promptly to avoid pool exhaustion.
            try:
                close_db()
            except Exception:
                pass


    def _emit_missed_pm_summary(username: str, sid: str | None = None) -> None:
        """Send per-sender counts of offline PMs that have not been delivered yet."""
        conn = get_db()
        target_sid = sid or request.sid
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT sender, COUNT(*)::int AS cnt, MAX(timestamp) AS last_ts
                      FROM offline_messages
                     WHERE LOWER(receiver) = LOWER(%s)
                       AND delivered = FALSE
                       AND NOT EXISTS (
                           SELECT 1 FROM blocks b
                            WHERE (LOWER(b.blocker) = LOWER(offline_messages.receiver) AND LOWER(b.blocked) = LOWER(offline_messages.sender))
                               OR (LOWER(b.blocker) = LOWER(offline_messages.sender) AND LOWER(b.blocked) = LOWER(offline_messages.receiver))
                       )
                     GROUP BY sender
                     ORDER BY last_ts DESC;
                    """,
                    (username,),
                )
                rows = cur.fetchall() or []

            merged = {}
            for sender, cnt, last_ts in rows:
                try:
                    epoch = float(last_ts.timestamp()) if last_ts else None
                except Exception:
                    epoch = None
                canonical_sender = _resolve_canonical_username(sender) or sender
                key = str(canonical_sender or "").strip().lower()
                if not key:
                    continue
                entry = merged.get(key)
                if entry is None:
                    merged[key] = {"sender": canonical_sender, "count": int(cnt), "last_ts": epoch}
                else:
                    entry["count"] += int(cnt)
                    if epoch is not None and (entry.get("last_ts") is None or epoch > entry.get("last_ts")):
                        entry["last_ts"] = epoch

            items = sorted(merged.values(), key=lambda it: (it.get("last_ts") or 0), reverse=True)
            total = sum(int(it.get("count") or 0) for it in items)
            emit("missed_pm_summary", {"items": items, "total": total, "generated_at": time.time()}, to=target_sid)
        except Exception as e:
            print(f"[DB ERROR] missed_pm_summary: {e}")
            try:
                emit("missed_pm_summary", {"items": [], "total": 0, "generated_at": time.time()}, to=target_sid)
            except Exception:
                pass
        finally:
            # Ensure pooled connections are returned for Socket.IO contexts.
            try:
                close_db()
            except Exception:
                pass

    def _emit_missed_pm_summary_to_user(username: str) -> int:
        """Refresh missed-PM counts in every active tab for a user.

        Fetch/ACK can happen in one browser tab while the same account has
        another tab open. Pushing the updated summary to all current Socket.IO
        sessions keeps dock bubbles from resurrecting stale offline-PM counts.
        """
        delivered = 0
        for sid in _user_sids(username):
            try:
                _emit_missed_pm_summary(username, sid)
                delivered += 1
            except Exception:
                pass
        return delivered

    def _group_rl(key: str, limit: int, window_sec: int) -> bool:
        now = time.time()
        with _GROUP_RATE_LOCK:
            dq = _GROUP_RATE.get(key)
            if dq is None:
                dq = deque()
                _GROUP_RATE[key] = dq
            cutoff = now - window_sec
            while dq and dq[0] < cutoff:
                dq.popleft()
            if len(dq) >= limit:
                return False
            dq.append(now)
            return True

    def _parse_rate_limit(val, *, default_limit: int = 60, default_window: int = 60) -> tuple[int, int]:
        """Parse a human-friendly rate limit value.

        Accepts either a bare integer (treated as per-minute), or strings like:
          - '60 per minute'
          - '10/sec', '10 per second'
          - '120/hour', '120 per hour'
          - '30@10' (30 per 10 seconds)

        Returns: (limit, window_seconds)
        """
        try:
            if val is None:
                return int(default_limit), int(default_window)
            if isinstance(val, bool):
                return int(default_limit), int(default_window)
            if isinstance(val, (int, float)):
                lim = int(val)
                return (lim if lim > 0 else int(default_limit)), 60
            if isinstance(val, str):
                s = val.strip().lower()
                import re
                m = re.search(r'(\d+)', s)
                lim = int(m.group(1)) if m else int(default_limit)
                window = 60
                if 'per second' in s or '/sec' in s or s.endswith('sec'):
                    window = 1
                elif 'per minute' in s or '/min' in s or 'minute' in s or s.endswith('min'):
                    window = 60
                elif 'per hour' in s or '/hour' in s or 'hour' in s:
                    window = 3600
                if '@' in s:
                    a, b = s.split('@', 1)
                    m1 = re.search(r'(\d+)', a)
                    m2 = re.search(r'(\d+)', b)
                    if m1:
                        lim = int(m1.group(1))
                    if m2:
                        window = max(1, int(m2.group(1)))
                return (lim if lim > 0 else int(default_limit)), int(window)
        except Exception:
            pass
        return int(default_limit), int(default_window)

    # ───────────────────────────────────────────────────────────────────────────
    # Anti-abuse guardrails (rooms + DMs + file offers)
    #   - per-user rate limiting (burst windows)
    #   - optional per-user hourly quotas (admin-set via /admin/set_user_quota)
    #   - auto-mute when a user repeatedly hits limits
    # ───────────────────────────────────────────────────────────────────────────

    _RATE: dict[str, deque] = {}
    _RATE_LOCK = threading.Lock()

    # Short switch cooldown for room-hopping abuse. This is intentionally
    # separate from the wider join-rate window so a modified client cannot
    # rapidly churn leave/join notifications, room counts, and custom-room
    # activity touches while still staying under the broader join limit.
    _ROOM_SWITCH_LAST: dict[str, float] = {}
    _ROOM_SWITCH_LOCK = threading.Lock()

    _ABUSE_STRIKES: dict[str, deque] = {}
    _ABUSE_LOCK = threading.Lock()

    _AUTO_MUTE_LAST: dict[str, float] = {}
    _AUTO_MUTE_LAST_LOCK = threading.Lock()

    _QUOTA_CACHE: dict[str, tuple[int | None, float]] = {}
    _QUOTA_CACHE_LOCK = threading.Lock()

    # Duplicate-message heuristics (plaintext only)
    _DUP_MSG: dict[tuple[str, str], deque] = {}
    _DUP_LOCK = threading.Lock()

    # Friend request target spread (anti-harassment)
    _FR_TARGETS: dict[str, deque] = {}
    _FR_LOCK = threading.Lock()

    # Room-existence cache (reduce DB hits when checking room creation policy)
    _ROOM_EXISTS_CACHE: dict[str, tuple[bool, float]] = {}
    _ROOM_EXISTS_LOCK = threading.Lock()

    def _rl(key: str, limit: int, window_sec: int) -> tuple[bool, float]:
        """Sliding-window rate limiter.

        Returns (ok, retry_after_seconds).
        """
        now = time.time()
        try:
            limit = int(limit)
        except Exception:
            limit = 0
        try:
            window_sec = int(window_sec)
        except Exception:
            window_sec = 0

        if limit <= 0 or window_sec <= 0:
            return True, 0.0

        with _RATE_LOCK:
            dq = _RATE.get(key)
            if dq is None:
                dq = deque()
                _RATE[key] = dq
            cutoff = now - window_sec
            while dq and dq[0] < cutoff:
                dq.popleft()
            if len(dq) >= limit:
                retry = (dq[0] + window_sec) - now
                return False, max(0.0, float(retry))
            dq.append(now)
            return True, 0.0

    def _get_user_quota_per_hour(username: str) -> int | None:
        """Return messages/hour quota if explicitly set for the user, else None.

        This is intentionally opt-in: default is unlimited unless an admin sets a quota.
        Cached briefly to avoid DB hits on every message.
        """
        now = time.time()
        try:
            ttl = float(settings.get('quota_cache_ttl_sec') or 60)
        except Exception:
            ttl = 60.0

        with _QUOTA_CACHE_LOCK:
            hit = _QUOTA_CACHE.get(username)
            if hit and (now - float(hit[1])) < ttl:
                return hit[0]

        limit = None
        try:
            conn = get_db()
            with conn.cursor() as cur:
                cur.execute('SELECT messages_per_hour FROM user_quotas WHERE username = %s;', (username,))
                row = cur.fetchone()
            if row and row[0] is not None:
                limit = int(row[0])
        except Exception:
            limit = None

        with _QUOTA_CACHE_LOCK:
            _QUOTA_CACHE[username] = (limit, now)
        return limit

    def _abuse_strike(username: str, reason: str) -> bool:
        """Record a limit-hit strike; may auto-mute if configured.

        Returns True if an auto-mute was triggered.
        """
        now = time.time()
        try:
            max_strikes = int(settings.get('antiabuse_strikes_before_mute') or 6)
        except Exception:
            max_strikes = 6
        try:
            strike_window = int(settings.get('antiabuse_strike_window_sec') or 30)
        except Exception:
            strike_window = 30
        try:
            mute_minutes = int(settings.get('antiabuse_auto_mute_minutes') or 2)
        except Exception:
            mute_minutes = 2

        if max_strikes <= 0 or strike_window <= 0 or mute_minutes <= 0:
            return False

        with _ABUSE_LOCK:
            dq = _ABUSE_STRIKES.get(username)
            if dq is None:
                dq = deque()
                _ABUSE_STRIKES[username] = dq
            cutoff = now - strike_window
            while dq and dq[0] < cutoff:
                dq.popleft()
            dq.append(now)
            count = len(dq)

        if count < max_strikes:
            return False

        # Avoid re-applying mute repeatedly within the same window
        with _AUTO_MUTE_LAST_LOCK:
            last = float(_AUTO_MUTE_LAST.get(username, 0.0) or 0.0)
            if (now - last) < strike_window:
                return False
            _AUTO_MUTE_LAST[username] = now

        try:
            if not is_user_sanctioned(username, 'mute'):
                mute_user(username, reason=f'Auto-mute: {reason}', duration_minutes=mute_minutes, actor='system')
                _emit_to_user(username, 'notification', f'🚫 You were auto-muted for {mute_minutes} minutes (spam/abuse guard).')
        except Exception:
            pass

        return True

    def _room_exists(room: str) -> bool:
        """Check if a room exists (cached)."""
        now = time.time()
        try:
            ttl = float(settings.get('room_exists_cache_ttl_sec') or 10)
        except Exception:
            ttl = 10.0

        with _ROOM_EXISTS_LOCK:
            hit = _ROOM_EXISTS_CACHE.get(room)
            if hit and (now - float(hit[1])) < ttl:
                return bool(hit[0])

        exists = False
        try:
            conn = get_db()
            with conn.cursor() as cur:
                cur.execute('SELECT 1 FROM chat_rooms WHERE name = %s LIMIT 1;', (room,))
                exists = bool(cur.fetchone())
        except Exception:
            exists = False

        if not exists:
            try:
                official_names = _official_room_names_from_json()
            except Exception:
                official_names = []
            if any(str(name).strip().lower() == str(room).strip().lower() for name in (official_names or [])):
                try:
                    create_room_if_missing(room, room_kind='official')
                    exists = True
                except Exception:
                    exists = False

        # Cache only positive lookups. Negative caching can block immediate joins
        # right after a room is created via the REST API.
        if exists:
            with _ROOM_EXISTS_LOCK:
                _ROOM_EXISTS_CACHE[room] = (True, now)
        return exists

    _URL_TOKEN_RE = re.compile(r'(https?://|www\.)', re.IGNORECASE)
    _MAGNET_RE = re.compile(r'magnet:\?', re.IGNORECASE)
    _MENTION_RE = re.compile(r'@[a-zA-Z0-9_.-]{2,32}')

    def _antiabuse_plaintext_checks(username: str, room: str, message: str) -> tuple[bool, str | None]:
        """Heuristic spam checks for *plaintext* room messages.

        This is intentionally conservative to avoid false positives.
        """
        # Link / magnet / mention limits
        try:
            max_links = int(settings.get('max_links_per_message') or 0)
        except Exception:
            max_links = 0
        try:
            max_magnets = int(settings.get('max_magnets_per_message') or 0)
        except Exception:
            max_magnets = 0
        try:
            max_mentions = int(settings.get('max_mentions_per_message') or 0)
        except Exception:
            max_mentions = 0

        if max_links > 0:
            lc = len(_URL_TOKEN_RE.findall(message))
            if lc > max_links:
                _abuse_strike(username, 'link_spam')
                return False, f'Too many links (max {max_links})'

        if max_magnets > 0:
            mc = len(_MAGNET_RE.findall(message))
            if mc > max_magnets:
                _abuse_strike(username, 'magnet_spam')
                return False, f'Too many magnet links (max {max_magnets})'

        if max_mentions > 0:
            ment = len(_MENTION_RE.findall(message))
            if ment > max_mentions:
                _abuse_strike(username, 'mention_spam')
                return False, f'Too many mentions (max {max_mentions})'

        # Duplicate message heuristic (same message repeated rapidly in same room)
        try:
            win = int(settings.get('dup_msg_window_sec') or 0)
        except Exception:
            win = 0
        try:
            mx = int(settings.get('dup_msg_max') or 0)
        except Exception:
            mx = 0
        try:
            minlen = int(settings.get('dup_msg_min_length') or 0)
        except Exception:
            minlen = 0
        norm = bool(settings.get('dup_msg_normalize', True))

        if win > 0 and mx > 0 and len(message) >= max(1, minlen):
            msg = message
            if norm:
                msg = re.sub(r'\s+', ' ', msg.strip().lower())
            sig = hash(msg)
            now = time.time()
            key = (username, room)
            with _DUP_LOCK:
                dq = _DUP_MSG.get(key)
                if dq is None:
                    dq = deque()
                    _DUP_MSG[key] = dq
                cutoff = now - win
                while dq and dq[0][0] < cutoff:
                    dq.popleft()
                dq.append((now, sig))
                count = sum(1 for ts, s in dq if s == sig)
            if count > mx:
                if _abuse_strike(username, 'dup_msg'):
                    return False, 'Auto-muted for spamming. Try again later.'
                return False, f'Duplicate message spam (slow down)'

        return True, None

    def _friend_req_target_spread_ok(from_user: str, to_user: str) -> tuple[bool, str | None]:
        """Limit how many *unique* friend request targets a user can hit in a window."""
        try:
            mx = int(settings.get('friend_req_unique_targets_max') or 0)
        except Exception:
            mx = 0
        try:
            win = int(settings.get('friend_req_unique_targets_window_sec') or 0)
        except Exception:
            win = 0
        if mx <= 0 or win <= 0:
            return True, None

        now = time.time()
        with _FR_LOCK:
            dq = _FR_TARGETS.get(from_user)
            if dq is None:
                dq = deque()
                _FR_TARGETS[from_user] = dq
            cutoff = now - win
            while dq and dq[0][0] < cutoff:
                dq.popleft()
            dq.append((now, to_user))
            uniq = {t for _, t in dq}
            if len(uniq) > mx:
                _abuse_strike(from_user, 'friendreq_spread')
                return False, f'Too many different targets in a short time (max {mx} per {win}s)'
        return True, None

    def _validate_room_name(room: str) -> tuple[bool, str | None]:
        """Basic room name validation to prevent abuse."""
        return validate_room_name_format(room, settings=settings)


    # ───────────────────────────────────────────────────────────────────────────
    # Autoscaled public rooms (Lobby -> Lobby (2) -> ...)
    # Accept both "Lobby(2)" and "Lobby (2)". Canonical form is "Lobby (2)".
    # ───────────────────────────────────────────────────────────────────────────

    _ROOM_SHARD_RE = re.compile(r"^(?P<base>.+?)\s*\(\s*(?P<n>\d+)\s*\)\s*$")

    def _parse_room_shard(name: str) -> tuple[str, int] | None:
        s = (name or "").strip()
        m = _ROOM_SHARD_RE.match(s)
        if not m:
            return None
        base = (m.group("base") or "").strip()
        try:
            n = int(m.group("n"))
        except Exception:
            return None
        if not base or n < 2:
            return None
        return base, n

    def _canonical_room_name(name: str) -> str:
        s = (name or "").strip()
        p = _parse_room_shard(s)
        if not p:
            return s
        base, n = p
        return f"{base} ({n})"

    def _private_custom_shard_base(name: str) -> str | None:
        """Return base room when name is a stale shard of a private custom room."""
        p = _parse_room_shard(name)
        if not p:
            return None
        base, _n = p
        try:
            meta = get_custom_room_meta(base)
        except Exception:
            # If the base lookup fails, hide the shard rather than risking a
            # stale private-room shard leak.
            return base
        if meta and meta.get("is_private"):
            return base
        return None

    def _private_custom_room_visibility_denied(room: str, username: str) -> tuple[bool, str]:
        """Fail-closed private custom-room guard used by room list/count actions.

        Visibility is intentionally broader than join access: a pending invite
        may reveal the room in invite-aware UI so the user can accept or decline
        it, but the Socket.IO join path below still requires accepted membership.
        """
        shard_base = _private_custom_shard_base(room)
        if shard_base:
            return True, "Private invite-only rooms do not use generated sub-rooms."
        try:
            meta = get_custom_room_meta(room)
        except Exception:
            # Fail closed so transient metadata/database errors cannot leak an
            # invite-only custom room through room lists or counts.
            return True, "Private room (invite required)."
        if meta and meta.get("is_private"):
            try:
                if not can_user_access_custom_room(room, username):
                    return True, "Private room (invite required)."
            except Exception:
                return True, "Private room (invite required)."
        return False, ""

    def _private_custom_room_access_denied(room: str, username: str) -> tuple[bool, str]:
        """Fail-closed private custom-room guard used by room join/action paths.

        Direct joins to invite-only rooms are blocked unless the caller is the
        creator or has an accepted persisted private-room membership.  Pending
        custom_room_invites rows are visibility-only and must be accepted before
        entry; otherwise a guessed room name plus a stale pending invite could
        bypass the explicit accept step.
        """
        shard_base = _private_custom_shard_base(room)
        if shard_base:
            return True, "Private invite-only rooms do not use generated sub-rooms."
        try:
            meta = get_custom_room_meta(room)
        except Exception:
            # Fail closed so transient metadata/database errors cannot leak an
            # invite-only custom room through joins or room actions.
            return True, "Private room (invite required)."
        if meta and meta.get("is_private"):
            try:
                if not can_user_join_custom_room(room, username):
                    return True, "Private room invite must be accepted first."
            except Exception:
                return True, "Private room (invite required)."
        return False, ""

    def _autoscale_enabled() -> bool:
        return bool(settings.get("autoscale_rooms_enabled", True))

    def _autoscale_capacity() -> int:
        try:
            cap = int(settings.get("autoscale_room_capacity", 30))
        except Exception:
            cap = 30
        return max(2, min(cap, 5000))

    def _autoscale_live_count(live: dict, room: str) -> int:
        try:
            return max(0, int((live or {}).get(str(room or "").strip(), 0) or 0))
        except Exception:
            return 0

    def _autoscale_first_available_room(base: str, live: dict, cap: int) -> tuple[str, bool]:
        """Return the first not-full shard, creating only the next sequential shard.

        This prevents modified clients from forcing skipped overflow rooms such as
        ``Introductions (99)``. A new overflow room is only created after the base
        and every previous shard are at capacity.
        """
        clean_base = _canonical_room_name(base)
        if not clean_base or not _room_exists(clean_base):
            return clean_base, False

        if _autoscale_live_count(live, clean_base) < cap:
            return clean_base, False

        for i in range(2, 500):
            candidate = f"{clean_base} ({i})"
            if _room_exists(candidate):
                if _autoscale_live_count(live, candidate) < cap:
                    return candidate, False
                continue

            # Because candidates are scanned in order, the first missing shard is
            # the only shard this join is allowed to create. Earlier existing
            # shards were already confirmed full above.
            create_autoscaled_room_if_missing(candidate, clean_base)
            return candidate, bool(_room_exists(candidate))

        # Fallback: if a deployment somehow reaches the shard ceiling, keep the
        # request bounded instead of inventing unbounded room names.
        return clean_base, False

    def _select_autoscaled_room(requested_room: str) -> tuple[str, bool]:
        """Return (actual_room, created_new).

        Public-room autosplit is sequential and capacity-driven:
        - base room with space stays as the base room;
        - full base room routes to the first existing shard with space;
        - only the next missing shard may be created;
        - direct shard requests are honored only when that shard exists and has
          space, otherwise they route through the same sequential selector.
        """
        req = _canonical_room_name(requested_room)

        # Never autoscale custom rooms. Private/invite-only custom rooms must not
        # be silently routed to a generated shard such as "Room (2)" because that
        # shard would not have the custom-room metadata and could bypass privacy
        # enforcement. Public custom rooms also keep their exact name so owner
        # controls, TTL cleanup, and invite/member metadata remain attached.
        try:
            parsed_for_meta = _parse_room_shard(req)
            meta_name = parsed_for_meta[0] if parsed_for_meta else req
            if get_custom_room_meta(meta_name):
                return req, False
        except Exception:
            return req, False

        if not _autoscale_enabled():
            return req, False

        cap = _autoscale_capacity()
        live = {}
        try:
            live = _live_room_counts() or {}
        except Exception:
            live = {}

        parsed = _parse_room_shard(req)
        if parsed:
            base, _n = parsed
            if not _room_exists(base):
                return req, False
            if _room_exists(req) and _autoscale_live_count(live, req) < cap:
                return req, False
            # Missing shards and full existing shards route through the same
            # sequential selector. This prevents skipped fake overflow creation
            # and keeps clicks on a full visible shard moving forward.
            return _autoscale_first_available_room(base, live, cap)

        return _autoscale_first_available_room(req, live, cap)

    def _join_rate_ok(username: str) -> tuple[bool, float]:
        lim, win = _parse_rate_limit(settings.get('room_join_rate_limit'), default_limit=15, default_window=30)
        try:
            win = int(settings.get('room_join_rate_window_sec') or win)
        except Exception:
            pass
        return _rl(f'join:{username}', lim, win)

    def _room_switch_cooldown_ok(username: str, previous_room: str | None, next_room: str | None) -> tuple[bool, float]:
        """Limit rapid room-to-room switching from modified clients.

        _join_rate_ok() is the broad flood window. This helper adds a small
        per-user cooldown only when the user is already in one room and is
        switching to a different room. First joins and idempotent re-joins to
        the same room are not delayed.
        """
        user = str(username or '').strip()
        prev = str(previous_room or '').strip()
        nxt = str(next_room or '').strip()
        if not user or not prev or not nxt or prev == nxt:
            return True, 0.0
        try:
            cooldown = int(settings.get('room_switch_cooldown_sec') or 1)
        except Exception:
            cooldown = 1
        cooldown = max(0, min(cooldown, 30))
        if cooldown <= 0:
            return True, 0.0

        now = time.time()
        with _ROOM_SWITCH_LOCK:
            last = float(_ROOM_SWITCH_LAST.get(user, 0.0) or 0.0)
            retry = (last + cooldown) - now
            if retry > 0:
                return False, max(0.0, float(retry))
            _ROOM_SWITCH_LAST[user] = now
            return True, 0.0

    def _room_create_rate_ok(username: str) -> tuple[bool, float]:
        lim, win = _parse_rate_limit(settings.get('room_create_rate_limit'), default_limit=5, default_window=300)
        try:
            win = int(settings.get('room_create_rate_window_sec') or win)
        except Exception:
            pass
        return _rl(f'roomcreate:{username}', lim, win)

    def _friend_req_rate_ok(username: str) -> tuple[bool, float]:
        lim, win = _parse_rate_limit(settings.get('friend_req_rate_limit'), default_limit=5, default_window=60)
        try:
            win = int(settings.get('friend_req_rate_window_sec') or win)
        except Exception:
            pass
        return _rl(f'friendreq:{username}', lim, win)

    def _socket_action_rate_ok(
        username: str,
        action: str,
        rate_key: str,
        window_key: str | None,
        *,
        default_limit: int,
        default_window: int,
        strike_reason: str | None = None,
    ) -> tuple[bool, float, bool]:
        """Apply a configurable per-user Socket.IO action rate limit.

        Returns (ok, retry_after_seconds, auto_muted). Use this for low-cost but
        high-churn control events such as typing, reactions, room-count polling,
        room-radio controls, and waves. These events are cheap individually but
        can become abuse vectors when a modified client loops them.
        """
        actor = str(username or '').strip() or 'anonymous'
        bucket = str(action or 'socket').strip() or 'socket'
        lim, win = _parse_rate_limit(settings.get(rate_key), default_limit=default_limit, default_window=default_window)
        if window_key:
            try:
                win = int(settings.get(window_key) or win)
            except Exception:
                pass
        ok, retry = _rl(f'sockact:{bucket}:{actor}', lim, win)
        if ok:
            return True, 0.0, False
        auto_muted = False
        if strike_reason:
            auto_muted = bool(_abuse_strike(actor, strike_reason))
        return False, float(retry or 0.0), auto_muted

    def _get_user_id_by_username(username: str) -> int | None:
        try:
            conn = get_db()
            with conn.cursor() as cur:
                cur.execute("SELECT id FROM users WHERE username = %s;", (username,))
                row = cur.fetchone()
            return int(row[0]) if row else None
        except Exception:
            return None

    def _is_group_member(group_id: int, user_id: int) -> bool:
        try:
            conn = get_db()
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM group_members WHERE group_id = %s AND user_id = %s;",
                    (group_id, user_id),
                )
                return cur.fetchone() is not None
        except Exception:
            return False

    def _is_group_muted(group_id: int, username: str) -> bool:
        try:
            conn = get_db()
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM group_mutes WHERE group_id = %s AND LOWER(username) = LOWER(%s);",
                    (group_id, username),
                )
                return cur.fetchone() is not None
        except Exception:
            return False

    def _group_room(group_id: int) -> str:
        return f"group_{group_id}"

    def _group_store_room(group_id: int) -> str:
        return f"g:{group_id}"

    def _format_group_history_rows(rows, *, require_e2ee: bool, allow_legacy: bool):
        """Convert DB rows -> wire-safe history items.

        We never emit plaintext group history when require_e2ee is enabled unless
        allow_legacy_plaintext_history is explicitly set.
        """
        out = []
        for r in rows or []:
            try:
                mid = int(r[0])
                sender = r[1]
                msg = r[2]
                is_enc = bool(r[3])
                ts = r[4]
            except Exception:
                continue

            item = {
                "message_id": mid,
                "sender": sender,
                "is_encrypted": is_enc,
                "timestamp": ts.isoformat() if hasattr(ts, "isoformat") else str(ts),
            }

            if is_enc:
                # message column stores the envelope string
                item["cipher"] = msg
                item["message"] = "🔒 Encrypted message"
            else:
                if require_e2ee and not allow_legacy:
                    item["message"] = "⚠️ Legacy plaintext message hidden"
                    item["hidden_legacy"] = True
                else:
                    item["message"] = msg

            out.append(item)
        return out

    def _format_room_history_rows(rows, require_e2ee: bool, allow_legacy_plaintext: bool):
        """Normalize DB rows into payloads the room UI already knows how to render."""
        out = []
        for r in (rows or []):
            mid, sender, msg, is_enc, ts = r
            item = {
                "message_id": int(mid),
                "username": sender,
                "timestamp": ts.isoformat() if hasattr(ts, "isoformat") else None,
            }
            if bool(is_enc):
                item["cipher"] = msg
                item["message"] = "🔒 Encrypted message"
                item["encrypted"] = True
            else:
                if require_e2ee and not allow_legacy_plaintext:
                    item["message"] = "⚠️ Legacy plaintext message hidden"
                    item["legacy_hidden"] = True
                else:
                    item["message"] = msg
                item["encrypted"] = False
            out.append(item)
        return out

    def _voice_dm_require_active(sender: str, to: str, call_id: str):
        _cleanup_voice_dm_sessions()
        with VOICE_DM_SESSIONS_LOCK:
            sess = VOICE_DM_SESSIONS.get(call_id)
            if not sess:
                return None, {"success": False, "error": "Unknown/expired call"}
            if {sess.get("caller"), sess.get("callee")} != {sender, to}:
                return None, {"success": False, "error": "Not a participant"}
            if str(sess.get("state") or "") != "active":
                return None, {"success": False, "error": "Call not active"}
            sess["updated"] = time.time()
            return sess, None


    # ───────────────────────────────────────────────────────────────────
    # Register split handler modules (see realtime/*.py)
    # ───────────────────────────────────────────────────────────────────
    from types import SimpleNamespace
    ctx = SimpleNamespace(**{k: v for k, v in locals().items() if k.startswith("_") and callable(v)})
    from realtime import dm, presence_social, rooms, groups, files, voice, admin
    dm.register(socketio, settings, ctx)
    presence_social.register(socketio, settings, ctx)
    rooms.register(socketio, settings, ctx)
    groups.register(socketio, settings, ctx)
    files.register(socketio, settings, ctx)
    voice.register(socketio, settings, ctx)
    admin.register(socketio, settings, ctx)

