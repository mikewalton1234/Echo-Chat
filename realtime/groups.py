

def _antiabuse_duplicate_checks(*args, **kwargs):
    """Placeholder hook for duplicate fingerprint checks."""
    return True
"""Socket.IO handlers: groups.

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
from security import log_audit_event, sanitize_user_visible_text
from permissions import check_user_permission
from moderation import is_user_sanctioned, mute_user

from realtime.state import *

def register(socketio, settings, ctx):
    """Register Socket.IO event handlers for this module."""
    # Make helper functions from socket_handlers available as module globals
    globals().update(ctx.__dict__)


    def _safe_positive_int(value, default: int, *, minimum: int = 1, maximum: int = 500) -> int:
        """Parse bounded positive integer settings/socket values safely."""
        try:
            parsed = int(value)
        except Exception:
            parsed = int(default)
        if parsed < minimum:
            parsed = minimum
        if parsed > maximum:
            parsed = maximum
        return parsed

    def _utc_iso_now() -> str:
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    def _group_visible_usernames_for_sender(group_id: int, sender: str) -> list[str]:
        """Return group members that are allowed to receive this sender's event.

        Blocks are pairwise even inside shared groups: a group message/file from
        one user must not become a side-channel to a user who blocked them or
        whom they blocked.  The sender is always included so their own tab gets
        the normal echo/receipt.
        """
        actor = str(sender or "").strip()
        try:
            conn = get_db()
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT u.username
                      FROM group_members gm
                      JOIN users u ON u.id = gm.user_id
                     WHERE gm.group_id = %s
                     ORDER BY LOWER(u.username);
                    """,
                    (group_id,),
                )
                rows = cur.fetchall() or []
        except Exception:
            rows = []
        out: list[str] = []
        seen: set[str] = set()
        for row in rows:
            name = str(row[0] if isinstance(row, (tuple, list)) else row or "").strip()
            key = name.lower()
            if not name or key in seen:
                continue
            if actor and key != actor.lower() and _either_blocked(actor, name):
                continue
            out.append(name)
            seen.add(key)
        if actor and actor.lower() not in seen:
            out.append(actor)
        return out

    def _emit_group_message_block_aware(group_id: int, sender: str, payload: dict) -> int:
        delivered = 0
        for username in _group_visible_usernames_for_sender(group_id, sender):
            try:
                if _emit_to_user(username, "group_message", payload):
                    delivered += 1
            except Exception:
                continue
        return delivered

    def _is_group_cipher_envelope(value) -> bool:
        """Validate the outer ECG1 group-message envelope before relay/storage.

        Full decryption stays client-side; the server only enforces that group
        chat cannot relay arbitrary plaintext-looking values as ciphertext.
        """
        if not isinstance(value, str):
            return False
        raw = value.strip()
        if not raw.startswith("ECG1:"):
            return False
        body = raw[5:]
        if not body or len(body) > 120000:
            return False
        try:
            import base64
            decoded = base64.b64decode(body, validate=True)
            env = json.loads(decoded.decode("utf-8"))
        except Exception:
            return False
        if not isinstance(env, dict):
            return False
        if env.get("v") != 1 or env.get("alg") != "RSA-OAEP+AES-GCM":
            return False
        if not isinstance(env.get("iv"), str) or not isinstance(env.get("ct"), str):
            return False
        keys = env.get("keys")
        if not isinstance(keys, dict) or not keys:
            return False
        if len(keys) > 500:
            return False
        return all(isinstance(k, str) and k.strip() and isinstance(v, str) and v.strip() for k, v in keys.items())

    def _format_group_history_payload(group_id: int, rows, *, require_e2ee: bool, allow_legacy: bool, limit: int, before_id=None):
        rows = list(rows or [])
        history = _format_group_history_rows(rows, require_e2ee=require_e2ee, allow_legacy=allow_legacy)
        ids = []
        for item in history:
            try:
                ids.append(int(item.get("message_id")))
            except Exception:
                pass
        return {
            "success": True,
            "group_id": int(group_id),
            "history": history,
            "count": len(history),
            "limit": int(limit),
            "before_id": before_id,
            "oldest_id": min(ids) if ids else None,
            "newest_id": max(ids) if ids else None,
            "generated_at": _utc_iso_now(),
        }

    def _normalize_group_role(role) -> str:
        value = str(role or "member").strip().lower()
        return value if value in {"owner", "admin", "moderator", "member"} else "member"

    def _group_role_rank(role) -> int:
        return {"member": 0, "moderator": 1, "admin": 2, "owner": 3}.get(_normalize_group_role(role), 0)

    def _group_role_label(role) -> str:
        return {"owner": "Owner", "admin": "Admin", "moderator": "Moderator", "member": "Member"}.get(_normalize_group_role(role), "Member")

    def _group_role_capabilities(role) -> dict:
        value = _normalize_group_role(role)
        rank = _group_role_rank(value)
        return {
            "can_invite": rank >= 1,
            "can_moderate": rank >= 1,
            "can_edit_metadata": rank >= 2,
            "can_manage_roles": value == "owner",
            "can_transfer_ownership": value == "owner",
            "can_delete_group": value == "owner",
        }


    def _group_current_role(group_id: int, user_id: int) -> str:
        try:
            conn = get_db()
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT role FROM group_members WHERE group_id = %s AND user_id = %s LIMIT 1;",
                    (group_id, user_id),
                )
                row = cur.fetchone()
            return _normalize_group_role(row[0] if row else "member")
        except Exception:
            return "member"

    def _group_unread_stats(username: str, group_id: int) -> dict:
        actor = str(username or "").strip()
        total = 0
        read = 0
        try:
            conn = get_db()
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT COUNT(*) AS total_messages,
                           COUNT(*) FILTER (
                             WHERE EXISTS (
                               SELECT 1
                                 FROM message_reads mr
                                WHERE mr.message_id = m.id
                                  AND LOWER(mr.username) = LOWER(%s)
                             )
                           ) AS read_messages
                      FROM messages m
                     WHERE (m.room = %s OR m.room = %s)
                       AND NOT EXISTS (
                           SELECT 1 FROM blocks b
                            WHERE (LOWER(b.blocker) = LOWER(%s) AND LOWER(b.blocked) = LOWER(m.sender))
                               OR (LOWER(b.blocker) = LOWER(m.sender) AND LOWER(b.blocked) = LOWER(%s))
                       );
                    """,
                    (actor, _group_store_room(group_id), str(int(group_id)), actor, actor),
                )
                row = cur.fetchone() or (0, 0)
                total = int(row[0] or 0)
                read = int(row[1] or 0)
        except Exception:
            total = 0
            read = 0
        unread = max(0, total - read)
        return {"total_messages": total, "read_count": read, "unread_count": unread, "unread": unread}

    def _group_members_for_client(group_id: int, current_username: str | None = None) -> tuple[list[str], list[dict]]:
        """Return group members as both legacy username list and detailed roster rows."""
        members: list[str] = []
        details: list[dict] = []
        current_key = str(current_username or "").strip().lower()
        try:
            conn = get_db()
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT u.username, COALESCE(gm.role, 'member') AS role, gm.joined_at
                      FROM group_members gm
                      JOIN users u ON u.id = gm.user_id
                     WHERE gm.group_id = %s
                     ORDER BY
                       CASE COALESCE(gm.role, 'member')
                         WHEN 'owner' THEN 0
                         WHEN 'admin' THEN 1
                         WHEN 'moderator' THEN 2
                         ELSE 3
                       END,
                       LOWER(u.username);
                    """,
                    (group_id,),
                )
                for row in (cur.fetchall() or []):
                    username = str(row[0] or "").strip() if row else ""
                    if not username:
                        continue
                    role = _normalize_group_role(row[1] if len(row) > 1 else "member")
                    joined_at = row[2] if len(row) > 2 else None
                    members.append(username)
                    details.append({
                        "username": username,
                        "role": role,
                        "role_label": _group_role_label(role),
                        "role_rank": _group_role_rank(role),
                        "capabilities": _group_role_capabilities(role),
                        "is_self": bool(current_key and username.lower() == current_key),
                        "joined_at": joined_at.isoformat() if hasattr(joined_at, "isoformat") else (str(joined_at) if joined_at else ""),
                    })
        except Exception:
            members = []
            details = []
        return members, details

    @socketio.on("group_message")
    @jwt_required()
    def handle_group_message(data):
        sender = get_jwt_identity()
        rejection = _reject_if_stale_socket_session(touch_activity=True)
        if rejection is not None:
            return rejection
        guard = _socket_event_guard(sender, "group_message", data, default_max_bytes=131072, default_limit=90, default_window=60)
        if guard is not None:
            return guard

        data = data or {}
        try:
            group_id = int(data.get("group_id"))
        except Exception:
            return {"success": False, "error": "bad_group_id"}

        cipher = data.get("cipher")
        message = data.get("message")

        require_e2ee = bool(settings.get("require_group_e2ee", True))
        if require_e2ee and not cipher:
            return {"success": False, "error": "This group requires encrypted messages"}

        # Validate payload size/types
        if cipher:
            if not isinstance(cipher, str):
                return {"success": False, "error": "bad_cipher"}
            max_cipher_len = _safe_positive_int(settings.get("max_group_cipher_length"), 120000, minimum=256, maximum=250000)
            if len(cipher) > max_cipher_len:
                return {"success": False, "error": f"Ciphertext too large (max {max_cipher_len})"}
            if not _is_group_cipher_envelope(cipher):
                return {"success": False, "error": "bad_group_cipher_envelope"}
        else:
            if not isinstance(message, str):
                return {"success": False, "error": "bad_message"}
            max_plain_chars = _safe_positive_int(settings.get("max_group_message_chars"), 2000, minimum=1, maximum=100000)
            message = sanitize_user_visible_text(message, max_len=max_plain_chars, keep_newlines=True)
            if not message:
                return {"success": False, "error": "empty"}
            if len(message) > max_plain_chars:
                return {"success": False, "error": "too_long"}

        # Plaintext groups should reuse the same spam heuristics as rooms.
        if not cipher:
            okc, cerr = _antiabuse_plaintext_checks(sender, _group_store_room(group_id), message)
            if not okc:
                return {"success": False, "error": cerr or "Message blocked"}

        # rate limit per sender + group
        # Accept either an int (treated as per-minute) or strings like "60 per minute".
        g_lim, g_win = _parse_rate_limit(settings.get("group_msg_rate_limit"), default_limit=60, default_window=60)
        # Optional explicit override for the window (seconds)
        try:
            if settings.get("group_msg_rate_window_sec") is not None:
                g_win = int(settings.get("group_msg_rate_window_sec"))
        except Exception:
            pass
        if not _group_rl(
            f"gmsg:{sender}:{group_id}",
            limit=g_lim,
            window_sec=g_win,
        ):
            if _abuse_strike(sender, "group_rate"):
                return {"success": False, "error": "Auto-muted for spamming. Try again later."}
            return {"success": False, "error": "rate_limited"}

        user_id = _get_user_id_by_username(sender)
        if not user_id:
            return {"success": False, "error": "unauthorized"}

        if not _is_group_member(group_id, user_id):
            # Do not leak group existence
            return {"success": False}

        if _is_group_muted(group_id, sender):
            return {"success": False, "error": "muted"}

        shadowbanned_sender = False
        try:
            shadowbanned_sender = bool(_is_effectively_shadowbanned(sender))
        except Exception:
            shadowbanned_sender = False
        if shadowbanned_sender:
            message_id = uuid.uuid4().hex
            payload = {
                "group_id": group_id,
                "sender": sender,
                "message_id": message_id,
                "timestamp": _utc_iso_now(),
                "message_kind": str(data.get("message_kind") or "text")[:32],
                "shadowbanned": True,
            }
            if cipher:
                payload["cipher"] = cipher
                payload["message"] = "🔒 Encrypted message"
            else:
                payload["message"] = message
            emit("group_message", payload, to=request.sid)
            return {"success": True, "message_id": message_id, "group_id": group_id, "timestamp": payload.get("timestamp"), "message_kind": payload.get("message_kind"), "shadowbanned": True}

        # Persist message (ciphertext-only if cipher provided)
        message_id = None
        try:
            conn = get_db()
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO messages (sender, room, message, is_encrypted)
                    VALUES (%s, %s, %s, %s)
                    RETURNING id;
                    """,
                    (
                        sender,
                        _group_store_room(group_id),
                        cipher if cipher else message,
                        True if cipher else False,
                    ),
                )
                message_id = int(cur.fetchone()[0])
                cur.execute(
                    """
                    INSERT INTO message_reads (message_id, username)
                    VALUES (%s, %s)
                    ON CONFLICT (message_id, username) DO NOTHING;
                    """,
                    (message_id, sender),
                )
            conn.commit()
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            print(f"[DB ERROR] group_message insert failed: {e}")
            return {"success": False, "error": "db"}

        server_ts = _utc_iso_now()
        payload = {
            "group_id": group_id,
            "sender": sender,
            "message_id": message_id,
            "timestamp": server_ts,
            "message_kind": str(data.get("message_kind") or "text")[:32],
        }

        if cipher:
            payload["cipher"] = cipher
            payload["message"] = "🔒 Encrypted message"
        else:
            payload["message"] = message

        delivered = _emit_group_message_block_aware(group_id, sender, payload)
        return {"success": True, "message_id": message_id, "group_id": group_id, "timestamp": server_ts, "message_kind": payload.get("message_kind"), "delivered_visible_members": delivered}


    @socketio.on("join_group_chat")
    @jwt_required()
    def handle_join_group_chat(data):
        username = get_jwt_identity()
        rejection = _reject_if_stale_socket_session(touch_activity=True)
        if rejection is not None:
            return rejection
        guard = _socket_event_guard(username, "join_group_chat", data, default_max_bytes=4096, default_limit=60, default_window=60)
        if guard:
            return guard
        try:
            group_id = int((data or {}).get("group_id"))
        except Exception:
            return {"success": False}
    
        if not _group_rl(f"gjoin:{username}:{group_id}", limit=10, window_sec=30):
            if _abuse_strike(username, "group_join_rate"):
                return {"success": False, "error": "Auto-muted for spamming. Try again later."}
            return {"success": False, "error": "rate_limited"}
    
        user_id = _get_user_id_by_username(username)
        if not user_id or not _is_group_member(group_id, user_id):
            return {"success": False}  # no leaks
    
        join_room(_group_room(group_id))

        # Load recent group history (ciphertext-safe).
        history = []
        try:
            require_e2ee = bool(settings.get("require_group_e2ee", True))
            allow_legacy = bool(settings.get("allow_legacy_plaintext_room_history", settings.get("allow_legacy_plaintext_history", False)))
            limit = _safe_positive_int(settings.get("max_group_history"), 200, minimum=0, maximum=500)

            conn = get_db()
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, sender, message, is_encrypted, timestamp
                      FROM messages
                     WHERE (room = %s OR room = %s)
                       AND NOT EXISTS (
                           SELECT 1 FROM blocks b
                            WHERE (LOWER(b.blocker) = LOWER(%s) AND LOWER(b.blocked) = LOWER(messages.sender))
                               OR (LOWER(b.blocker) = LOWER(messages.sender) AND LOWER(b.blocked) = LOWER(%s))
                       )
                     ORDER BY id DESC
                     LIMIT %s;
                    """,
                    (_group_store_room(group_id), str(group_id), username, username, limit),
                )
                rows = cur.fetchall() or []
            rows.reverse()
            history = _format_group_history_rows(rows, require_e2ee=require_e2ee, allow_legacy=allow_legacy)
        except Exception:
            history = []
        try:
            conn = get_db()
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO message_reads (message_id, username)
                    SELECT id, %s
                      FROM messages
                     WHERE (room = %s OR room = %s)
                       AND NOT EXISTS (
                           SELECT 1 FROM blocks b
                            WHERE (LOWER(b.blocker) = LOWER(%s) AND LOWER(b.blocked) = LOWER(messages.sender))
                               OR (LOWER(b.blocker) = LOWER(messages.sender) AND LOWER(b.blocked) = LOWER(%s))
                       )
                     ORDER BY id DESC
                     LIMIT 500
                    ON CONFLICT (message_id, username) DO NOTHING;
                    """,
                    (username, _group_store_room(group_id), str(group_id), username, username),
                )
            conn.commit()
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
    
        # Provide member list for client-side group E2EE key wrapping and roster UI.
        members, member_details = _group_members_for_client(group_id, username)
    
        _audit_details = f"sid={request.sid}"
        try:
            log_audit_event(username, "group_socket_join", target=str(group_id), details=_audit_details)
        except Exception:
            pass
        group_name = ""
        group_role = "member"
        try:
            conn = get_db()
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT g.group_name, COALESCE(gm.role, 'member')
                      FROM groups g
                      JOIN group_members gm ON gm.group_id = g.id
                     WHERE g.id = %s AND gm.user_id = %s;
                    """,
                    (group_id, user_id),
                )
                grow = cur.fetchone()
                if grow:
                    group_name = str(grow[0] or "")
                    group_role = str(grow[1] or "member")
        except Exception:
            pass
        return {"success": True, "group_id": group_id, "group_name": group_name, "role": _normalize_group_role(group_role), "role_label": _group_role_label(group_role), "role_rank": _group_role_rank(group_role), "capabilities": _group_role_capabilities(group_role), "joined_at": _utc_iso_now(), "members": members, "member_details": member_details, "history": history, **_group_unread_stats(username, group_id)}


    @socketio.on("get_group_history")
    @jwt_required()
    def handle_get_group_history(data):
        """Fetch older group history (pagination)."""
        username = get_jwt_identity()
        rejection = _reject_if_stale_socket_session(touch_activity=True)
        if rejection is not None:
            return rejection
        guard = _socket_event_guard(username, "get_group_history", data, default_max_bytes=4096, default_limit=60, default_window=60)
        if guard:
            return guard
        data = data or {}
        try:
            group_id = int(data.get("group_id"))
        except Exception:
            return {"success": False, "error": "bad_group_id"}

        before_id = None
        try:
            if data.get("before_id") is not None:
                before_id = int(data.get("before_id"))
        except Exception:
            before_id = None

        if not _group_rl(f"ghist:{username}:{group_id}", limit=12, window_sec=30):
            return {"success": False, "error": "rate_limited"}

        user_id = _get_user_id_by_username(username)
        if not user_id or not _is_group_member(group_id, user_id):
            return {"success": False}

        require_e2ee = bool(settings.get("require_group_e2ee", True))
        allow_legacy = bool(settings.get("allow_legacy_plaintext_room_history", settings.get("allow_legacy_plaintext_history", False)))
        limit = _safe_positive_int(data.get("limit") or settings.get("max_group_history_page"), 200, minimum=1, maximum=500)

        try:
            conn = get_db()
            with conn.cursor() as cur:
                if before_id is not None:
                    cur.execute(
                        """
                        SELECT id, sender, message, is_encrypted, timestamp
                          FROM messages
                         WHERE (room = %s OR room = %s) AND id < %s
                           AND NOT EXISTS (
                               SELECT 1 FROM blocks b
                                WHERE (LOWER(b.blocker) = LOWER(%s) AND LOWER(b.blocked) = LOWER(messages.sender))
                                   OR (LOWER(b.blocker) = LOWER(messages.sender) AND LOWER(b.blocked) = LOWER(%s))
                           )
                         ORDER BY id DESC
                         LIMIT %s;
                        """,
                        (_group_store_room(group_id), str(group_id), before_id, username, username, limit),
                    )
                else:
                    cur.execute(
                        """
                        SELECT id, sender, message, is_encrypted, timestamp
                          FROM messages
                         WHERE (room = %s OR room = %s)
                           AND NOT EXISTS (
                               SELECT 1 FROM blocks b
                                WHERE (LOWER(b.blocker) = LOWER(%s) AND LOWER(b.blocked) = LOWER(messages.sender))
                                   OR (LOWER(b.blocker) = LOWER(messages.sender) AND LOWER(b.blocked) = LOWER(%s))
                           )
                         ORDER BY id DESC
                         LIMIT %s;
                        """,
                        (_group_store_room(group_id), str(group_id), username, username, limit),
                    )
                rows = cur.fetchall() or []
            rows.reverse()
            return _format_group_history_payload(group_id, rows, require_e2ee=require_e2ee, allow_legacy=allow_legacy, limit=limit, before_id=before_id)
        except Exception:
            return {"success": False, "error": "db"}
    

    @socketio.on("mark_group_read")
    @jwt_required()
    def handle_mark_group_read(data):
        """Mark visible group messages as read for the current user.

        The client may ACK one message_id or a bounded message_ids batch after
        rendering visible history.  The server still verifies membership and
        that every marked id belongs to this group storage room before inserting
        message_reads rows.
        """
        username = get_jwt_identity()
        rejection = _reject_if_stale_socket_session(touch_activity=True)
        if rejection is not None:
            return rejection
        guard = _socket_event_guard(username, "mark_group_read", data, default_max_bytes=16384, default_limit=120, default_window=60)
        if guard:
            return guard
        data = data or {}
        try:
            group_id = int(data.get("group_id"))
        except Exception:
            return {"success": False, "error": "bad_payload"}

        raw_ids = data.get("message_ids")
        if raw_ids is None:
            raw_ids = [data.get("message_id")]
        elif not isinstance(raw_ids, list):
            raw_ids = [raw_ids]

        message_ids: list[int] = []
        seen_ids: set[int] = set()
        for raw in raw_ids:
            try:
                mid = int(raw)
            except Exception:
                continue
            if mid <= 0 or mid in seen_ids:
                continue
            seen_ids.add(mid)
            message_ids.append(mid)
            if len(message_ids) >= 500:
                break

        if group_id <= 0 or not message_ids:
            return {"success": False, "error": "bad_payload"}

        if not _group_rl(f"gread:{username}:{group_id}", limit=120, window_sec=60):
            return {"success": False, "error": "rate_limited"}

        user_id = _get_user_id_by_username(username)
        if not user_id or not _is_group_member(group_id, user_id):
            return {"success": False}

        try:
            conn = get_db()
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO message_reads (message_id, username)
                    SELECT id, %s
                      FROM messages
                     -- single-message guard equivalent: WHERE id = %s AND (room = %s OR room = %s)
                     WHERE id = ANY(%s) AND (room = %s OR room = %s)
                       AND NOT EXISTS (
                           SELECT 1 FROM blocks b
                            WHERE (LOWER(b.blocker) = LOWER(%s) AND LOWER(b.blocked) = LOWER(messages.sender))
                               OR (LOWER(b.blocker) = LOWER(messages.sender) AND LOWER(b.blocked) = LOWER(%s))
                       )
                    ON CONFLICT (message_id, username) DO NOTHING;
                    """,
                    (username, message_ids, _group_store_room(group_id), str(group_id), username, username),
                )
                changed = int(cur.rowcount or 0)
            conn.commit()
            stats = _group_unread_stats(username, group_id)
            return {
                "success": True,
                "group_id": group_id,
                "message_ids": message_ids,
                "message_id": message_ids[0] if len(message_ids) == 1 else None,
                "requested": len(message_ids),
                "marked_count": changed,
                "marked": bool(changed),
                **stats,
            }
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            return {"success": False, "error": "db"}


    @socketio.on("get_group_members")
    @jwt_required()
    def handle_get_group_members(data):
        username = get_jwt_identity()
        rejection = _reject_if_stale_socket_session(touch_activity=True)
        if rejection is not None:
            return rejection
        guard = _socket_event_guard(username, "get_group_members", data, default_max_bytes=4096, default_limit=60, default_window=60)
        if guard:
            return guard
        data = data or {}
        try:
            group_id = int(data.get("group_id"))
        except Exception:
            return {"success": False, "error": "bad_group_id"}
    
        if not _group_rl(f"gmembers:{username}:{group_id}", limit=12, window_sec=30):
            return {"success": False, "error": "rate_limited"}
    
        user_id = _get_user_id_by_username(username)
        if not user_id or not _is_group_member(group_id, user_id):
            return {"success": False}
    
        members, member_details = _group_members_for_client(group_id, username)
    
        current_role = _group_current_role(group_id, user_id)
        return {"success": True, "group_id": group_id, "members": members, "member_details": member_details, "total": len(member_details), "current_role": current_role, "current_capabilities": _group_role_capabilities(current_role), "generated_at": _utc_iso_now()}
    

    @socketio.on("leave_group_chat")
    @jwt_required()
    def handle_leave_group_chat(data):
        username = get_jwt_identity()
        rejection = _reject_if_stale_socket_session(touch_activity=True)
        if rejection is not None:
            return rejection
        guard = _socket_event_guard(username, "leave_group_chat", data, default_max_bytes=4096, default_limit=90, default_window=60)
        if guard:
            return guard
        try:
            group_id = int((data or {}).get("group_id"))
        except Exception:
            return {"success": False}
        leave_room(_group_room(group_id))
        try:
            log_audit_event(username, "group_socket_leave", target=str(group_id), details=f"sid={request.sid}")
        except Exception:
            pass
        return {"success": True, "group_id": group_id, "left_at": _utc_iso_now()}


