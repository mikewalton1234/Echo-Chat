#!/usr/bin/env python3
"""routes_chat.py

Chat-related HTTP endpoints.

Notes:
  - The chat HTML page is served by routes_auth.py at /chat.
  - This blueprint provides API endpoints like /api/rooms.

SQLite support removed; Postgres only.
"""

from __future__ import annotations

import logging

import re
from datetime import datetime, timezone
from flask import Blueprint, jsonify, request, current_app
from flask_jwt_extended import get_jwt_identity, jwt_required

from database import (
    create_room_if_missing,
    get_db,
    is_user_verified,
    cleanup_expired_custom_rooms,
    can_user_access_custom_room,
    can_user_join_custom_room,
    record_custom_room_membership,
    get_custom_room_user_role,
    can_user_moderate_custom_room,
    get_custom_room_meta,
    revoke_custom_room_access,
)
from room_name_policy import normalize_room_name, validate_custom_room_creation_name, validate_room_name_format
from security import log_audit_event, parse_rate_limit_value, simple_rate_limit, get_request_ip
from permissions import require_admin, check_user_permission
from moderation import is_user_sanctioned
from room_catalog import (
    catalog_has_room,
    normalize_catalog_room_entry,
    official_room_names_from_catalog,
    read_official_room_catalog,
)


chat_bp = Blueprint("chat", __name__)

_ROOM_SHARD_RE = re.compile(r"^(?P<base>.+?)\s*\(\s*(?P<n>\d+)\s*\)\s*$")


def _parse_room_shard_name(name: str) -> tuple[str, int] | None:
    m = _ROOM_SHARD_RE.match(str(name or "").strip())
    if not m:
        return None
    try:
        n = int(m.group("n"))
    except Exception:
        return None
    base = str(m.group("base") or "").strip()
    if not base or n < 2:
        return None
    return base, n


def _hidden_private_custom_room_or_shard(name: str, actor: str) -> bool:
    """True when a chat_rooms row should not be exposed to this caller.

    This covers both the exact private custom room and stale generated shards
    such as "Private Room (2)" left from older builds. Shards are never valid
    entry points for custom/private rooms, so hide them for everyone.
    """
    room = str(name or "").strip()
    if not room:
        return True
    try:
        meta = get_custom_room_meta(room)
        if meta and meta.get("is_private") and not can_user_access_custom_room(room, actor):
            return True
        parsed = _parse_room_shard_name(room)
        if parsed:
            base_meta = get_custom_room_meta(parsed[0])
            if base_meta and base_meta.get("is_private"):
                return True
    except Exception:
        # Visibility checks for invite-only rooms fail closed so a database or
        # policy lookup problem cannot leak private room names through fallback
        # room-browser rows.
        return True
    return False


def _emit_to_username(username: str, event: str, payload: dict) -> bool:
    """Best-effort emit to all active Socket.IO sessions for a username.

    Used from HTTP routes that need to push realtime UX updates.
    Returns True if at least one session was targeted.
    """
    try:
        socketio = current_app.config.get("HUI_SOCKETIO")
        if not socketio:
            return False
        from realtime.state import user_sids

        sids = list(user_sids(username))

        for sid in sids:
            try:
                socketio.emit(event, payload, to=sid)
            except Exception:
                pass
        return bool(sids)
    except Exception:
        return False




def _chat_json(payload: dict, status: int = 200):
    """Return non-cacheable JSON for room/chat API state changes."""
    resp = jsonify(payload)
    resp.headers["Cache-Control"] = "no-store, max-age=0"
    return resp, status


def _fetch_custom_room_casefold(cur, room_name: str):
    """Return canonical custom-room row using case-insensitive lookup."""
    cur.execute(
        """
        SELECT name, created_by, is_private
          FROM custom_rooms
         WHERE LOWER(name)=LOWER(%s)
         LIMIT 1;
        """,
        (room_name,),
    )
    return cur.fetchone()


def _custom_room_join_access_exists_cur(cur, room_name: str, username: str, created_by: str | None = None) -> bool:
    """True when username already has accepted/private-room entry access."""
    room_name = str(room_name or "").strip()
    username = str(username or "").strip()
    if not room_name or not username:
        return False
    if created_by and str(created_by or "").strip().lower() == username.lower():
        return True
    cur.execute(
        """
        SELECT 1
          FROM custom_room_members
         WHERE LOWER(room_name)=LOWER(%s)
           AND LOWER(member_user)=LOWER(%s)
           AND (LOWER(COALESCE(role, '')) IN ('owner', 'moderator') OR invited_by IS NOT NULL)
         LIMIT 1;
        """,
        (room_name, username),
    )
    return cur.fetchone() is not None




def _is_custom_room_owner_for_manager(room_name: str, username: str, created_by: str | None = None) -> bool:
    """True only for the private custom-room owner/creator.

    F104 deliberately keeps durable member revocation narrower than active room
    kick controls.  Moderators can kick live users according to room-role rank,
    but only the room owner can remove offline/private-room access grants.
    """
    room_name = str(room_name or "").strip()
    username = str(username or "").strip()
    if not room_name or not username:
        return False
    if created_by and str(created_by or "").strip().lower() == username.lower():
        return True
    try:
        return get_custom_room_user_role(room_name, username) == "owner"
    except Exception:
        return False


def _force_leave_revoked_custom_room_member(room_name: str, username: str, actor: str) -> int:
    """Remove all live sockets for username from room after owner revokes access."""
    room_name = str(room_name or "").strip()
    target_lc = str(username or "").strip().lower()
    if not room_name or not target_lc:
        return 0
    try:
        socketio = current_app.config.get("HUI_SOCKETIO")
        if not socketio:
            return 0
        from realtime.state import connected_room_targets, update_connected_room

        affected = 0
        for sid, user in connected_room_targets(room_name):
            if str(user or "").strip().lower() != target_lc:
                continue
            try:
                socketio.emit("room_forced_leave", {"room": room_name, "reason": "access_revoked", "by": actor, "scoped": True, "member_manager": True}, to=sid)
            except Exception:
                pass
            try:
                socketio.server.leave_room(sid, room_name)
                affected += 1
            except Exception:
                pass
            try:
                update_connected_room(sid, None)
            except Exception:
                pass
        return affected
    except Exception:
        return 0

def _is_user_in_room_live(username: str, room: str) -> bool:
    """Return True if any active Socket.IO session for `username` is currently in `room`."""
    username = (username or "").strip()
    room = (room or "").strip()
    if not username or not room:
        return False
    try:
        from realtime.state import is_user_in_room
        return bool(is_user_in_room(username, room))
    except Exception:
        return False

def _is_blocked(blocker: str, blocked: str) -> bool:
    blocker = (blocker or "").strip()
    blocked = (blocked or "").strip()
    if not blocker or not blocked:
        return False
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT 1
              FROM blocks
             WHERE LOWER(blocker)=LOWER(%s)
               AND LOWER(blocked)=LOWER(%s)
             LIMIT 1;
            """,
            (blocker, blocked),
        )
        return cur.fetchone() is not None


def _either_blocked(a: str, b: str) -> bool:
    return _is_blocked(a, b) or _is_blocked(b, a)

def _room_action_denial(username: str, action: str) -> tuple[dict | None, int]:
    """Return a JSON-ish error payload/status when room/invite writes are sanctioned.

    Socket.IO has its own live-session gate, but the HTTP room browser endpoints
    are reachable with ordinary JWTs.  Keep room creation, invites, and durable
    membership writes aligned with moderation sanctions so an old browser tab or
    stale access token cannot keep creating visible room state after moderation.
    """
    user = str(username or "").strip()
    if not user:
        return {"error": "Not authenticated"}, 401
    try:
        if is_user_sanctioned(user, "ban"):
            return {"error": "You are banned.", "code": "banned"}, 403
        if action in {"create", "invite", "member_manage"} and is_user_sanctioned(user, "mute"):
            return {"error": "You are muted.", "code": "muted"}, 403
        if action in {"join", "accept_invite"} and is_user_sanctioned(user, "kick"):
            return {"error": "You are temporarily kicked.", "code": "kicked"}, 403
    except Exception:
        # Room writes are visible state changes.  If sanction lookup is unhealthy,
        # fail closed instead of allowing room/invite mutation through a broken DB path.
        return {"error": "Moderation status unavailable"}, 503
    return None, 200


def _delete_generic_room_invite_casefold(cur, room: str, actor: str):
    """Delete one visible generic room invite and return (room, invited_by).

    Generic room invites are only notification rows.  Private custom-room grants
    live in custom_room_invites and must not be consumed here.  Case-insensitive
    matching keeps invite cleanup working after username/room casing repairs.
    """
    cur.execute(
        """
        DELETE FROM room_invites i
         USING chat_rooms r
         LEFT JOIN custom_rooms cr ON LOWER(cr.name)=LOWER(r.name)
         WHERE LOWER(i.room_name)=LOWER(r.name)
           AND LOWER(i.room_name)=LOWER(%s)
           AND LOWER(i.invited_user)=LOWER(%s)
           AND (cr.name IS NULL OR cr.is_private = FALSE)
        RETURNING r.name, i.invited_by;
        """,
        (room, actor),
    )
    return cur.fetchone()

def _get_live_counts() -> dict[str, int]:
    """Best-effort live counts (unique usernames per room) from Socket.IO sessions."""
    try:
        from realtime.state import live_room_counts
        return dict(live_room_counts())
    except Exception:
        return {}


def _runtime_settings() -> dict:
    cfg = current_app.config.get("HUI_SETTINGS") or {}
    return cfg if isinstance(cfg, dict) else {}


def _custom_room_ttl_minutes(is_private: bool, settings: dict | None = None) -> int:
    """Return the effective custom-room idle TTL in minutes.

    Public and private custom rooms can use different owner settings.  The
    minute-based keys win over the old hour-based keys so countdown labels and
    janitor deletion use the same policy.
    """
    cfg = settings if isinstance(settings, dict) else _runtime_settings()
    try:
        raw_public_minutes = cfg.get("custom_room_idle_minutes", None)
        if raw_public_minutes not in (None, ""):
            public_minutes = int(raw_public_minutes)
        else:
            public_minutes = int(cfg.get("custom_room_idle_hours", 3)) * 60
    except Exception:
        public_minutes = 180
    public_minutes = max(1, min(public_minutes, 24 * 60 * 365))

    try:
        raw_private_minutes = cfg.get("custom_private_room_idle_minutes", None)
        if raw_private_minutes not in (None, ""):
            private_minutes = int(raw_private_minutes)
        else:
            private_minutes = int(cfg.get("custom_private_room_idle_hours", max(1, public_minutes // 60))) * 60
    except Exception:
        private_minutes = public_minutes
    private_minutes = max(1, min(private_minutes, 24 * 60 * 365))
    return private_minutes if is_private else public_minutes


def _iso_datetime(value) -> str | None:
    try:
        if value is None:
            return None
        if hasattr(value, "isoformat"):
            return value.isoformat()
        text = str(value or "").strip()
        return text or None
    except Exception:
        return None


def _custom_room_expiry_payload(*, is_private: bool, activity_at, activity_age_seconds, occupancy_count: int, settings: dict | None = None) -> dict:
    """Build browser/admin countdown metadata for one custom room.

    The janitor only deletes empty custom rooms.  When a room has live occupants
    we deliberately report the timer as paused so the UI does not count toward a
    deletion that will not happen while users are inside.
    """
    ttl_minutes = _custom_room_ttl_minutes(is_private, settings=settings)
    ttl_seconds = int(ttl_minutes * 60)
    try:
        age_seconds = max(0, int(float(activity_age_seconds or 0)))
    except Exception:
        age_seconds = 0
    try:
        occupancy = max(0, int(occupancy_count or 0))
    except Exception:
        occupancy = 0

    if occupancy > 0:
        return {
            "idle_ttl_minutes": ttl_minutes,
            "idle_ttl_seconds": ttl_seconds,
            "last_active_at": _iso_datetime(activity_at),
            "last_active_age_seconds": age_seconds,
            "expires_in_seconds": None,
            "expires_at": None,
            "timer_paused": True,
            "deletion_state": "occupied",
            "cleanup_occupancy_count": occupancy,
        }

    remaining = max(0, ttl_seconds - age_seconds)
    expires_at_iso = None
    try:
        if isinstance(activity_at, datetime):
            base = activity_at
            if base.tzinfo is None:
                base = base.replace(tzinfo=timezone.utc)
            expires_at_iso = datetime.fromtimestamp(base.timestamp() + ttl_seconds, tz=timezone.utc).isoformat()
    except Exception:
        expires_at_iso = None
    return {
        "idle_ttl_minutes": ttl_minutes,
        "idle_ttl_seconds": ttl_seconds,
        "last_active_at": _iso_datetime(activity_at),
        "last_active_age_seconds": age_seconds,
        "expires_in_seconds": remaining,
        "expires_at": expires_at_iso,
        "timer_paused": False,
        "deletion_state": "eligible_now" if remaining <= 0 else "counting_down",
        "cleanup_occupancy_count": 0,
    }


def _autoscale_room_capacity() -> int:
    try:
        return max(0, min(int(_runtime_settings().get("autoscale_room_capacity") or 0), 100000))
    except Exception:
        return 0


def _room_policy_rows() -> dict[str, dict]:
    """Return public room-browser policy metadata keyed by room name."""
    out: dict[str, dict] = {}
    try:
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT names.room,
                       COALESCE(l.locked, FALSE) AS locked,
                       COALESCE(ro.readonly, FALSE) AS readonly,
                       COALESCE(sm.seconds, 0) AS slowmode_seconds
                  FROM (
                        SELECT name AS room FROM chat_rooms
                        UNION
                        SELECT name AS room FROM custom_rooms
                       ) AS names
             LEFT JOIN room_locks l ON l.room = names.room
             LEFT JOIN room_readonly ro ON ro.room = names.room
             LEFT JOIN room_slowmode sm ON sm.room = names.room;
                """
            )
            for row in cur.fetchall() or []:
                name = str(row[0] or "").strip()
                if not name:
                    continue
                out[name] = {
                    "locked": bool(row[1]),
                    "readonly": bool(row[2]),
                    "slowmode_seconds": int(row[3] or 0),
                }
    except Exception:
        return {}
    return out


def _room_browser_row(name: str, live: dict[str, int], policy: dict[str, dict], *, is_custom: bool = False, is_private: bool = False, room_kind: str = "") -> dict:
    room_name = str(name or "").strip()
    count = int(live.get(room_name, 0) or 0)
    capacity = _autoscale_room_capacity()
    pol = policy.get(room_name) or {}
    return {
        "name": room_name,
        "member_count": count,
        "locked": bool(pol.get("locked")),
        "readonly": bool(pol.get("readonly")),
        "slowmode_seconds": int(pol.get("slowmode_seconds") or 0),
        "capacity": capacity,
        "full": bool(capacity and count >= capacity),
        "is_custom": bool(is_custom),
        "is_private": bool(is_private),
        "room_kind": str(room_kind or "").strip(),
    }


def _too_large_json_guard(max_bytes: int | None = None):
    """Reject unexpectedly large JSON/form bodies before parsing them.

    Flask's global MAX_CONTENT_LENGTH catches huge requests, but these small
    room/invite APIs only need a tiny JSON body. A tight per-route check reduces
    memory pressure and noisy abuse before DB work begins.
    """
    try:
        settings = _runtime_settings()
        limit = int(max_bytes or settings.get("max_chat_api_json_bytes") or 8192)
    except Exception:
        limit = 8192
    try:
        clen = int(request.content_length or 0)
    except Exception:
        clen = 0
    if clen and clen > max(1024, limit):
        return jsonify({"error": "Request too large"}), 413
    return None


def _chat_rate_limit_guard(scope: str, cfg_key: str, *, default_limit: int, default_window: int, actor: str | None = None):
    """Small in-process fallback limiter for blueprint routes.

    Flask-Limiter can still protect globally, but these room/invite actions also
    need per-user limits when Limiter is disabled or backed by memory during dev.
    """
    try:
        settings = _runtime_settings()
        cfg_value = settings.get(cfg_key) or f"{default_limit}@{default_window}"
        limit, window = parse_rate_limit_value(cfg_value, default_limit=default_limit, default_window=default_window)
        ident = str(actor or get_jwt_identity() or get_request_ip(request) or request.remote_addr or "anon").strip() or "anon"
        ok, retry = simple_rate_limit(f"route:chat:{scope}:{ident}", limit=limit, window_sec=window)
        if ok:
            return None
        return jsonify({"error": "Rate limited", "retry_after": retry}), 429
    except Exception:
        # Do not break normal chat APIs if the fallback limiter itself fails.
        return None


def _validate_room_name(name: str) -> tuple[bool, str | None]:
    return validate_room_name_format(name, settings=_runtime_settings())


def _normalize_catalog_room_entry(entry):
    return normalize_catalog_room_entry(entry)


def _read_room_catalog() -> dict:
    """Read chat_rooms.json and normalize into a stable catalog dict."""
    return read_official_room_catalog(logger=logging.getLogger(__name__))


def _catalog_json_response(catalog: dict):
    """Return catalog JSON that browsers/proxies must not cache stale."""
    resp = jsonify(catalog)
    resp.headers["Cache-Control"] = "no-store, max-age=0"
    return resp


def _catalog_has_path(catalog: dict, category: str, subcategory: str) -> bool:
    category = (category or "").strip()
    subcategory = (subcategory or "").strip()
    if not category or not subcategory:
        return False
    for c in catalog.get("categories") or []:
        if (c.get("name") or "") == category:
            for s in c.get("subcategories") or []:
                if (s.get("name") or "") == subcategory:
                    return True
    return False


def _catalog_has_roomname(catalog: dict, room_name: str) -> bool:
    """True if room_name appears in the official room catalog (case-insensitive)."""
    return catalog_has_room(catalog, room_name)


@chat_bp.route("/api/rooms", methods=["GET"])
@jwt_required(optional=True)
def api_get_rooms():
    """Return visible rooms (name + member_count).

    NOTE: We overlay Socket.IO live counts to avoid stale DB member_count drift.
    Invite-only custom rooms are intentionally hidden from callers who are not
    the owner, an invited user, or a persisted private-room member. The creator
    remains visible through a case-insensitive owner check even if JWT/user casing
    differs from the stored created_by value. This keeps the global room list
    from leaking private room names through chat_rooms while preserving creator access.
    """
    actor = get_jwt_identity() or ""
    try:
        live = _get_live_counts()
        catalog = _read_room_catalog()
        official_names: list[str] = official_room_names_from_catalog(catalog)
        policy = _room_policy_rows()
        custom_flags: dict[str, dict] = {}
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT r.name,
                       (cr.name IS NOT NULL) AS is_custom,
                       COALESCE(cr.is_private, FALSE) AS is_private,
                       COALESCE(r.room_kind, '') AS room_kind
                  FROM chat_rooms r
             LEFT JOIN custom_rooms cr ON cr.name = r.name
                 WHERE cr.name IS NULL
                    OR cr.is_private = FALSE
                    OR LOWER(cr.created_by) = LOWER(%s)
                    OR EXISTS (
                        SELECT 1 FROM custom_room_invites i
                         WHERE LOWER(i.room_name) = LOWER(r.name)
                           AND LOWER(i.invited_user) = LOWER(%s)
                    )
                    OR EXISTS (
                        SELECT 1 FROM custom_room_members m
                         WHERE LOWER(m.room_name) = LOWER(r.name)
                           AND LOWER(m.member_user) = LOWER(%s)
                           AND (LOWER(COALESCE(m.role, '')) IN ('owner', 'moderator') OR m.invited_by IS NOT NULL)
                    )
                 ORDER BY LOWER(r.name);
                """,
                (actor, actor, actor),
            )
            raw_rows = cur.fetchall() or []
            rows = []
            for r in raw_rows:
                if not r or not str(r[0]).strip():
                    continue
                name = str(r[0]).strip()
                rows.append(name)
                custom_flags[name] = {
                    "is_custom": bool(r[1]),
                    "is_private": bool(r[2]),
                    "room_kind": str(r[3] or "").strip(),
                }
        all_names = []
        seen_names: set[str] = set()
        for name in rows + official_names:
            key = str(name).strip().lower()
            if not key or key in seen_names:
                continue
            seen_names.add(key)
            all_names.append(str(name).strip())
        all_names = [name for name in all_names if not _hidden_private_custom_room_or_shard(name, actor)]
        all_names.sort(key=lambda n: n.lower())
        return jsonify({"rooms": [_room_browser_row(
            name,
            live,
            policy,
            is_custom=bool((custom_flags.get(name) or {}).get("is_custom")),
            is_private=bool((custom_flags.get(name) or {}).get("is_private")),
            room_kind=str((custom_flags.get(name) or {}).get("room_kind") or ("official" if name in official_names else "")),
        ) for name in all_names]})
    except Exception:
        return jsonify({"rooms": []})


@chat_bp.route("/api/rooms", methods=["POST"])
@require_admin
def api_create_room():
    """Create a room if missing."""
    actor = get_jwt_identity() or "unknown"
    data = request.get_json(silent=True) or {}
    name = normalize_room_name(data.get("name") or "")
    if not name:
        return jsonify({"error": "Room name required"}), 400

    try:
        # Creating official rooms must follow the same live RBAC source of
        # truth as the rest of the admin surface. Do not trust legacy
        # users.is_admin flags here because they can remain stale after role
        # changes until a background sync or manual cleanup runs.
        create_room_if_missing(name, room_kind="manual")
        return jsonify({"status": "ok", "room": name, "created_by": actor}), 201
    except Exception:
        logging.exception("chat API operation failed")
        return jsonify({"error": "Server error"}), 500


@chat_bp.route("/api/room_catalog", methods=["GET"])
@jwt_required(optional=True)
def api_room_catalog():
    """Return the official room catalog (categories/subcategories/rooms)."""
    return _catalog_json_response(_read_room_catalog())


@chat_bp.route("/api/custom_rooms", methods=["GET"])
@jwt_required()
def api_list_custom_rooms():
    """List visible custom rooms for one catalog category/subcategory.

    Private rooms are only returned if the caller is the owner, invited, or a
    persisted member. Creator visibility uses the same case-insensitive owner
    rule as the global room list. Countdown fields mirror the janitor
    custom-room cleanup policy so the browser can show an honest expiration
    label.
    """
    actor = get_jwt_identity() or ""
    guard = _chat_rate_limit_guard("custom_room_list", "rate_limit_custom_room_list", default_limit=120, default_window=60, actor=actor)
    if guard is not None:
        return guard

    category = (request.args.get("category") or "").strip()
    subcategory = (request.args.get("subcategory") or "").strip()
    if not category or not subcategory:
        return jsonify({"rooms": [], "error": "category and subcategory required"}), 400

    catalog = _read_room_catalog()
    if not _catalog_has_path(catalog, category, subcategory):
        return jsonify({"rooms": [], "error": "Invalid category/subcategory"}), 400

    cfg = _runtime_settings()
    idle_minutes = _custom_room_ttl_minutes(False, settings=cfg)
    private_idle_minutes = _custom_room_ttl_minutes(True, settings=cfg)

    # Use live Socket.IO room counts as the source of truth for custom-room
    # cleanup and countdowns.  The persisted chat_rooms.member_count counter is
    # best-effort and can drift if a browser closes without a clean disconnect.
    try:
        live = _get_live_counts()
    except Exception:
        live = {}

    try:
        cleanup_expired_custom_rooms(
            idle_minutes=idle_minutes,
            private_idle_minutes=private_idle_minutes,
            live_counts=live,
        )
    except Exception:
        pass

    try:
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT cr.name, cr.created_by, cr.is_private, cr.is_18_plus, cr.is_nsfw,
                       cr.category, cr.subcategory, cr.created_at,
                       COALESCE(cr.last_active_at, cr.created_at) AS activity_at,
                       EXTRACT(EPOCH FROM (NOW() - COALESCE(cr.last_active_at, cr.created_at))) AS activity_age_seconds,
                       COALESCE(r.member_count, 0) AS member_count,
                       COALESCE(l.locked, FALSE) AS locked,
                       COALESCE(ro.readonly, FALSE) AS readonly,
                       COALESCE(sm.seconds, 0) AS slowmode_seconds
                  FROM custom_rooms cr
                  LEFT JOIN chat_rooms r
                         ON r.name = cr.name
                  LEFT JOIN room_locks l
                         ON l.room = cr.name
                  LEFT JOIN room_readonly ro
                         ON ro.room = cr.name
                  LEFT JOIN room_slowmode sm
                         ON sm.room = cr.name
                 WHERE cr.category = %s
                   AND cr.subcategory = %s
                   AND (
                        cr.is_private = FALSE
                        OR LOWER(cr.created_by) = LOWER(%s)
                        OR EXISTS (
                            SELECT 1 FROM custom_room_invites i
                             WHERE LOWER(i.room_name) = LOWER(cr.name)
                               AND LOWER(i.invited_user) = LOWER(%s)
                        )
                        OR EXISTS (
                            SELECT 1 FROM custom_room_members m
                             WHERE LOWER(m.room_name) = LOWER(cr.name)
                               AND LOWER(m.member_user) = LOWER(%s)
                               AND (LOWER(COALESCE(m.role, '')) IN ('owner', 'moderator') OR m.invited_by IS NOT NULL)
                        )
                   )
                 ORDER BY LOWER(cr.name);
                """,
                (category, subcategory, actor, actor, actor),
            )
            rows = cur.fetchall()
        capacity = _autoscale_room_capacity()
        rooms = []
        for r in (rows or []):
            room_name = str(r[0] or "").strip()
            if not room_name:
                continue
            is_private = bool(r[2])
            count = int(live.get(room_name, 0) or 0)
            expiry = _custom_room_expiry_payload(
                is_private=is_private,
                activity_at=r[8],
                activity_age_seconds=r[9],
                occupancy_count=count,
                settings=cfg,
            )
            rooms.append({
                "name": room_name,
                "created_by": r[1],
                "is_private": is_private,
                "is_18_plus": bool(r[3]),
                "is_nsfw": bool(r[4]),
                "category": r[5] or category,
                "subcategory": r[6] or subcategory,
                "created_at": _iso_datetime(r[7]),
                "member_count": count,
                "locked": bool(r[11]),
                "readonly": bool(r[12]),
                "slowmode_seconds": int(r[13] or 0),
                "capacity": capacity,
                "full": bool(capacity and count >= capacity),
                "my_room_role": get_custom_room_user_role(room_name, actor),
                "can_room_moderate": can_user_moderate_custom_room(room_name, actor),
                **expiry,
            })
        resp = jsonify({
            "rooms": rooms,
            "category": category,
            "subcategory": subcategory,
            "idle_ttl_minutes": idle_minutes,
            "private_idle_ttl_minutes": private_idle_minutes,
        })
        resp.headers["Cache-Control"] = "no-store, max-age=0"
        return resp
    except Exception:
        logging.exception("custom room list failed")
        resp = jsonify({"rooms": [], "error": "Server error"})
        resp.headers["Cache-Control"] = "no-store, max-age=0"
        return resp, 500


@chat_bp.route("/api/custom_rooms", methods=["POST"])
@jwt_required()
def api_create_custom_room():
    """Create a custom room (Postgres-backed)."""
    actor = get_jwt_identity() or ""
    guard = _too_large_json_guard() or _chat_rate_limit_guard("custom_room_create", "rate_limit_custom_room_create", default_limit=5, default_window=300, actor=actor)
    if guard is not None:
        return guard
    data = request.get_json(silent=True) or {}
    name = normalize_room_name(data.get("name") or "")
    category = (data.get("category") or "").strip()
    subcategory = (data.get("subcategory") or "").strip()
    is_private = bool(data.get("is_private", False))
    is_18_plus = bool(data.get("is_18_plus", False))
    is_nsfw = bool(data.get("is_nsfw", False))
    if is_nsfw:
        is_18_plus = True

    ok, err, blocked_term = validate_custom_room_creation_name(name, settings=_runtime_settings())
    if not ok:
        if blocked_term and actor:
            try:
                log_audit_event(actor, "custom_room_name_blocked", name, f"matched={blocked_term}")
            except Exception:
                pass
        return jsonify({"error": err or "Invalid name"}), 400

    if not actor:
        return jsonify({"error": "Not authenticated"}), 401
    denied, status = _room_action_denial(actor, "create")
    if denied is not None:
        return jsonify(denied), status

    cfg = _runtime_settings()
    if not bool(cfg.get("allow_user_create_rooms", True)):
        try:
            can_override_create = bool(check_user_permission(actor, "admin:basic") or check_user_permission(actor, "room:create"))
        except Exception:
            can_override_create = False
        if not can_override_create:
            return jsonify({"error": "User-created rooms are disabled by the server owner", "code": "custom_room_creation_disabled"}), 403

    if not is_user_verified(actor):
        return jsonify({"error": "Only verified users can create rooms"}), 403

    catalog = _read_room_catalog()
    if not _catalog_has_path(catalog, category, subcategory):
        return jsonify({"error": "Invalid category/subcategory"}), 400

    try:
        conn = get_db()
        with conn.cursor() as cur:
            # Prevent collisions with existing rooms.
            #
            # IMPORTANT: We want users to be able to re-create a custom room that was auto-deleted.
            # Sometimes a stale chat_rooms row can remain (or the room exists under a different category).
            cur.execute("SELECT name, COALESCE(room_kind, '') FROM chat_rooms WHERE LOWER(name)=LOWER(%s) LIMIT 1;", (name,))
            existing_chat_room = cur.fetchone()
            if existing_chat_room is not None:
                existing_chat_name = str(existing_chat_room[0] or name).strip() or name
                # If a custom_rooms record exists, provide a helpful conflict message (including its path).
                cur.execute(
                    "SELECT name, category, subcategory, created_by, is_private FROM custom_rooms WHERE LOWER(name)=LOWER(%s) LIMIT 1;",
                    (name,),
                )
                row = cur.fetchone()
                if row is not None:
                    ex_name, ex_cat, ex_sub, ex_owner, ex_private = row
                    invited = False
                    if bool(ex_private) and (str(ex_owner or '').strip().lower() != str(actor or '').strip().lower()):
                        cur.execute(
                            """
                            SELECT 1
                              FROM custom_room_invites
                             WHERE LOWER(room_name)=LOWER(%s) AND LOWER(invited_user)=LOWER(%s)
                            UNION
                            SELECT 1
                              FROM custom_room_members
                             WHERE LOWER(room_name)=LOWER(%s) AND LOWER(member_user)=LOWER(%s)
                               AND (LOWER(COALESCE(role, '')) IN ('owner', 'moderator') OR invited_by IS NOT NULL)
                             LIMIT 1;
                            """,
                            (name, actor, name, actor),
                        )
                        invited = cur.fetchone() is not None

                    visible = (not bool(ex_private)) or (str(ex_owner or '').strip().lower() == str(actor or '').strip().lower()) or invited
                    if visible:
                        return (
                            jsonify(
                                {
                                    "error": f"Room already exists in {ex_cat} › {ex_sub}",
                                    "existing": {
                                        "name": ex_name or existing_chat_name or name,
                                        "category": ex_cat,
                                        "subcategory": ex_sub,
                                        "created_by": ex_owner,
                                        "is_private": bool(ex_private),
                                    },
                                }
                            ),
                            409,
                        )
                    # Do not confirm the existence or path of someone else's
                    # invite-only room when a caller guesses the exact name.
                    return jsonify({"error": "Room name unavailable"}), 409

                # No custom_rooms record exists, but a chat_rooms row does.
                # Exact-case stale custom/manual orphans may be revived.  A different
                # casing would create two browser-identical rooms in PostgreSQL's
                # case-sensitive unique index, so block it.
                if existing_chat_name.lower() != name.lower() or _catalog_has_roomname(catalog, existing_chat_name or name):
                    return jsonify({"error": "Room name already in use"}), 409
                if existing_chat_name != name:
                    return jsonify({"error": "Room name already in use"}), 409
                # else: proceed to insert into custom_rooms (revive exact stale orphan)

            cur.execute(
                """
                INSERT INTO custom_rooms (name, category, subcategory, created_by, is_private, is_18_plus, is_nsfw)
                VALUES (%s, %s, %s, %s, %s, %s, %s);
                """,
                (name, category, subcategory, actor, is_private, is_18_plus, is_nsfw),
            )
            cur.execute(
                """
                INSERT INTO chat_rooms (name, member_count, created_by, room_kind, last_active_at)
                VALUES (%s, 0, %s, 'custom', NOW())
                ON CONFLICT (name) DO UPDATE
                   SET room_kind = 'custom',
                       last_active_at = NOW();
                """,
                (name, actor),
            )
            cur.execute(
                """
                INSERT INTO custom_room_members (room_name, member_user, invited_by, role, last_seen_at)
                VALUES (%s, %s, NULL, 'owner', NOW())
                ON CONFLICT (room_name, member_user)
                DO UPDATE SET role = 'owner',
                              last_seen_at = NOW();
                """,
                (name, actor),
            )
        conn.commit()
        return jsonify({
            "status": "ok",
            "room": name,
            "category": category,
            "subcategory": subcategory,
            "is_private": bool(is_private),
            "is_18_plus": bool(is_18_plus),
            "is_nsfw": bool(is_nsfw),
            "created_by": actor,
            "my_room_role": "owner",
            "can_room_moderate": True,
            "auto_join": True,
            "auto_join_event": "join",
            "auto_join_payload": {"room": name, "auto_join_created_custom_room": True},
        }), 201
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        msg = str(e or "")
        if "duplicate" in msg.lower() or "unique" in msg.lower():
            return jsonify({"error": "Room name already in use"}), 409
        logging.exception("chat API operation failed")
        return jsonify({"error": "Server error"}), 500



@chat_bp.route("/api/custom_rooms/invite", methods=["POST"])
@jwt_required()
def api_invite_to_custom_room():
    """Send or refresh a pending invite for a private custom room.

    F094 lifecycle rules:
      - room lookup is canonical/case-insensitive;
      - inviter must already have accepted entry access;
      - pending invite rows are list/accept/decline state only;
      - users who already have accepted entry access are not re-invited.
    """
    actor = get_jwt_identity() or ""
    guard = _too_large_json_guard() or _chat_rate_limit_guard("custom_room_invite", "rate_limit_custom_room_invite", default_limit=20, default_window=60, actor=actor)
    if guard is not None:
        return guard
    denied, status = _room_action_denial(actor, "invite")
    if denied is not None:
        return _chat_json(denied, status)
    data = request.get_json(silent=True) or {}
    room = (data.get("room") or "").strip()
    invitee = (data.get("invitee") or "").strip()
    if not room or not invitee:
        return _chat_json({"error": "room and invitee required"}, 400)
    if invitee.lower() == str(actor or "").strip().lower():
        return _chat_json({"error": "Cannot invite yourself"}, 400)

    conn = None
    try:
        conn = get_db()
        with conn.cursor() as cur:
            row = _fetch_custom_room_casefold(cur, room)
            if not row:
                return _chat_json({"error": "Not a custom room"}, 404)
            canonical_room, created_by, is_private = str(row[0]), str(row[1] or ""), bool(row[2])
            if not is_private:
                return _chat_json({"error": "Room is public (no invite needed)"}, 400)

            # The invite button can live in the room browser, so the inviter does
            # not have to be connected to the room right now.  They do need
            # accepted private-room entry access, not just a pending invite.
            if not can_user_moderate_custom_room(canonical_room, actor):
                return _chat_json({"error": "Only the room owner or a room moderator can invite users to this private room"}, 403)

            cur.execute("SELECT username FROM users WHERE LOWER(username)=LOWER(%s) LIMIT 1;", (invitee,))
            urow = cur.fetchone()
            if urow is None:
                return _chat_json({"error": "User not found"}, 404)
            invitee = str(urow[0])
            if invitee.lower() == str(actor or "").strip().lower():
                return _chat_json({"error": "Cannot invite yourself"}, 400)
            if _either_blocked(actor, invitee):
                return _chat_json({"error": "You cannot invite this user"}, 403)
            if _custom_room_join_access_exists_cur(cur, canonical_room, invitee, created_by=created_by):
                return _chat_json({"error": "User already has access to this private room", "kind": "custom_private"}, 409)

            cur.execute(
                """
                INSERT INTO custom_room_invites (room_name, invited_user, invited_by)
                VALUES (%s, %s, %s)
                ON CONFLICT (room_name, invited_user)
                DO UPDATE SET invited_by = EXCLUDED.invited_by,
                              created_at = NOW();
                """,
                (canonical_room, invitee, actor),
            )
        conn.commit()

        delivered = _emit_to_username(invitee, "custom_room_invite", {"room": canonical_room, "by": actor, "kind": "custom_private"})
        return _chat_json({"status": "ok", "room": canonical_room, "invitee": invitee, "kind": "custom_private", "delivered": bool(delivered)}, 200)
    except Exception:
        try:
            if conn:
                conn.rollback()
        except Exception:
            pass
        logging.exception("chat API operation failed")
        return _chat_json({"error": "Server error"}, 500)


@chat_bp.route("/api/custom_rooms/members", methods=["GET"])
@jwt_required()
def api_list_custom_room_members():
    """Owner-only private-room member manager list.

    F104 separates durable access management from the active-room kick shortcut:
    accepted members and pending invites can be reviewed even when the target is
    offline, but only the room owner may view/manage this private access list.
    """
    actor = get_jwt_identity() or ""
    guard = _chat_rate_limit_guard("custom_room_member_list", "rate_limit_custom_room_member_manage", default_limit=60, default_window=60, actor=actor)
    if guard is not None:
        return guard
    room = (request.args.get("room") or "").strip()
    if not room:
        return _chat_json({"error": "room required"}, 400)

    try:
        conn = get_db()
        with conn.cursor() as cur:
            row = _fetch_custom_room_casefold(cur, room)
            if not row:
                return _chat_json({"error": "Not a custom room"}, 404)
            canonical_room, created_by, is_private = str(row[0]), str(row[1] or ""), bool(row[2])
            if not is_private:
                return _chat_json({"error": "Member manager is only for private custom rooms"}, 400)
            if not _is_custom_room_owner_for_manager(canonical_room, actor, created_by=created_by):
                return _chat_json({"error": "Only the room owner can manage private-room members"}, 403)

            cur.execute(
                """
                SELECT member_user, COALESCE(role, 'member') AS role, invited_by, joined_at, last_seen_at
                  FROM custom_room_members
                 WHERE LOWER(room_name)=LOWER(%s)
                 ORDER BY CASE LOWER(COALESCE(role, 'member'))
                            WHEN 'owner' THEN 0
                            WHEN 'moderator' THEN 1
                            ELSE 2
                          END,
                          LOWER(member_user);
                """,
                (canonical_room,),
            )
            member_rows = cur.fetchall() or []
            seen = set()
            members = []
            for mr in member_rows:
                uname = str(mr[0] or "").strip()
                if not uname:
                    continue
                role = str(mr[1] or "member").strip().lower()
                is_owner = role == "owner" or uname.lower() == created_by.lower()
                seen.add(uname.lower())
                members.append({
                    "username": uname,
                    "role": "owner" if is_owner else ("moderator" if role == "moderator" else "member"),
                    "invited_by": mr[2],
                    "joined_at": _iso_datetime(mr[3]),
                    "last_seen_at": _iso_datetime(mr[4]),
                    "is_owner": bool(is_owner),
                    "can_revoke": bool(not is_owner and uname.lower() != actor.lower()),
                    "status": "member",
                })

            if created_by and created_by.lower() not in seen:
                members.insert(0, {
                    "username": created_by,
                    "role": "owner",
                    "invited_by": None,
                    "joined_at": None,
                    "last_seen_at": None,
                    "is_owner": True,
                    "can_revoke": False,
                    "status": "member",
                })

            cur.execute(
                """
                SELECT i.invited_user, i.invited_by, i.created_at
                  FROM custom_room_invites i
                 WHERE LOWER(i.room_name)=LOWER(%s)
                   AND NOT EXISTS (
                       SELECT 1
                         FROM custom_room_members m
                        WHERE LOWER(m.room_name)=LOWER(i.room_name)
                          AND LOWER(m.member_user)=LOWER(i.invited_user)
                   )
                 ORDER BY i.created_at DESC, LOWER(i.invited_user)
                 LIMIT 200;
                """,
                (canonical_room,),
            )
            pending_rows = cur.fetchall() or []
            pending_invites = [
                {
                    "username": str(pr[0] or "").strip(),
                    "role": "pending",
                    "invited_by": pr[1],
                    "created_at": _iso_datetime(pr[2]),
                    "is_owner": False,
                    "can_revoke": bool(str(pr[0] or "").strip().lower() not in {created_by.lower(), actor.lower()}),
                    "status": "pending",
                }
                for pr in pending_rows
                if str(pr[0] or "").strip()
            ]
        return _chat_json({
            "status": "ok",
            "room": canonical_room,
            "is_private": True,
            "owner": created_by,
            "my_room_role": "owner",
            "members": members,
            "pending_invites": pending_invites,
        }, 200)
    except Exception:
        logging.exception("custom room member list failed")
        return _chat_json({"error": "Server error"}, 500)


@chat_bp.route("/api/custom_rooms/members/revoke", methods=["POST"])
@jwt_required()
def api_revoke_custom_room_member():
    """Owner-only durable private-room access revocation.

    This removes pending invite rows and accepted member rows without requiring
    the target to be live in the room.  It is intentionally not exposed to room
    moderators; moderators keep the narrower live kick action.
    """
    actor = get_jwt_identity() or ""
    guard = _too_large_json_guard() or _chat_rate_limit_guard("custom_room_member_revoke", "rate_limit_custom_room_member_manage", default_limit=20, default_window=60, actor=actor)
    if guard is not None:
        return guard
    denied, status = _room_action_denial(actor, "member_manage")
    if denied is not None:
        return _chat_json(denied, status)
    data = request.get_json(silent=True) or {}
    room = (data.get("room") or "").strip()
    target = (data.get("username") or data.get("target") or "").strip()
    if not room or not target:
        return _chat_json({"error": "room and username required"}, 400)

    conn = None
    try:
        conn = get_db()
        with conn.cursor() as cur:
            row = _fetch_custom_room_casefold(cur, room)
            if not row:
                return _chat_json({"error": "Not a custom room"}, 404)
            canonical_room, created_by, is_private = str(row[0]), str(row[1] or ""), bool(row[2])
            if not is_private:
                return _chat_json({"error": "Member manager is only for private custom rooms"}, 400)
            if not _is_custom_room_owner_for_manager(canonical_room, actor, created_by=created_by):
                return _chat_json({"error": "Only the room owner can revoke private-room access"}, 403)
            if target.lower() == actor.lower():
                return _chat_json({"error": "You cannot revoke yourself"}, 400)
            if created_by and target.lower() == created_by.lower():
                return _chat_json({"error": "You cannot revoke the room owner"}, 400)

            cur.execute(
                """
                SELECT COALESCE(m.member_user, i.invited_user)
                  FROM custom_room_members m
                  FULL OUTER JOIN custom_room_invites i
                    ON LOWER(i.room_name)=LOWER(m.room_name)
                   AND LOWER(i.invited_user)=LOWER(m.member_user)
                 WHERE LOWER(COALESCE(m.room_name, i.room_name))=LOWER(%s)
                   AND LOWER(COALESCE(m.member_user, i.invited_user))=LOWER(%s)
                 LIMIT 1;
                """,
                (canonical_room, target),
            )
            target_row = cur.fetchone()
            canonical_target = str(target_row[0] if target_row and target_row[0] else target).strip()
        conn.rollback()

        revoked = int(revoke_custom_room_access(canonical_room, canonical_target) or 0)
        if revoked <= 0:
            return _chat_json({"error": "No private-room access or pending invite found for that user", "room": canonical_room, "username": canonical_target}, 404)
        affected = _force_leave_revoked_custom_room_member(canonical_room, canonical_target, actor)
        _emit_to_username(canonical_target, "room_access_revoked", {"room": canonical_room, "by": actor, "kind": "custom_private", "affected_sessions": affected})
        try:
            log_audit_event(actor, "custom_room_member_revoke", f"{canonical_target}@{canonical_room}", f"revoked={revoked} affected_sessions={affected}")
        except Exception:
            pass
        return _chat_json({"status": "ok", "room": canonical_room, "username": canonical_target, "revoked": revoked, "affected_sessions": affected}, 200)
    except Exception:
        try:
            if conn:
                conn.rollback()
        except Exception:
            pass
        logging.exception("custom room member revoke failed")
        return _chat_json({"error": "Server error"}, 500)


@chat_bp.route("/api/custom_rooms/invites", methods=["GET"])
@jwt_required()
def api_list_custom_room_invites():
    """Return pending private custom-room invites for the current user."""
    username = get_jwt_identity() or ""
    guard = _chat_rate_limit_guard("custom_room_invite_list", "rate_limit_room_invite_read", default_limit=120, default_window=60, actor=username)
    if guard is not None:
        return guard
    try:
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT r.name, i.invited_by, i.created_at, r.category, r.subcategory
                  FROM custom_room_invites i
                  JOIN custom_rooms r ON LOWER(r.name) = LOWER(i.room_name)
                 WHERE LOWER(i.invited_user) = LOWER(%s)
                   AND r.is_private = TRUE
                   AND NOT EXISTS (
                       SELECT 1
                         FROM blocks b
                        WHERE (LOWER(b.blocker)=LOWER(%s) AND LOWER(b.blocked)=LOWER(i.invited_by))
                           OR (LOWER(b.blocker)=LOWER(i.invited_by) AND LOWER(b.blocked)=LOWER(%s))
                   )
                   AND NOT EXISTS (
                       SELECT 1
                         FROM custom_room_members m
                        WHERE LOWER(m.room_name)=LOWER(r.name)
                          AND LOWER(m.member_user)=LOWER(%s)
                          AND (LOWER(COALESCE(m.role, '')) IN ('owner', 'moderator') OR m.invited_by IS NOT NULL)
                   )
                 ORDER BY i.created_at DESC
                 LIMIT 200;
                """,
                (username, username, username, username),
            )
            rows = cur.fetchall() or []
        invites = [
            {
                "room": r[0],
                "by": r[1],
                "kind": "custom_private",
                "created_at": (r[2].isoformat() if hasattr(r[2], "isoformat") else str(r[2])),
                "category": r[3],
                "subcategory": r[4],
            }
            for r in rows
        ]
        return _chat_json({"invites": invites}, 200)
    except Exception:
        logging.exception("chat API operation failed")
        return _chat_json({"error": "Server error"}, 500)


@chat_bp.route("/api/custom_rooms/invites/accept", methods=["POST"])
@jwt_required()
def api_accept_custom_room_invite():
    """Accept a private-room invite and persist membership before Socket.IO join.

    Pending invite rows are visibility-only until this endpoint accepts the
    invite and writes a custom_room_members access row.
    """
    actor = get_jwt_identity() or ""
    guard = _too_large_json_guard() or _chat_rate_limit_guard("custom_room_invite_accept", "rate_limit_room_invite_response", default_limit=30, default_window=60, actor=actor)
    if guard is not None:
        return guard
    denied, status = _room_action_denial(actor, "accept_invite")
    if denied is not None:
        return _chat_json(denied, status)
    data = request.get_json(silent=True) or {}
    room = (data.get("room") or "").strip()
    if not room:
        return _chat_json({"error": "room required"}, 400)

    conn = None
    try:
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute(
                """
                DELETE FROM custom_room_invites i
                 USING custom_rooms r
                 WHERE LOWER(r.name)=LOWER(i.room_name)
                   AND r.is_private = TRUE
                   AND LOWER(i.room_name)=LOWER(%s)
                   AND LOWER(i.invited_user)=LOWER(%s)
                RETURNING r.name, i.invited_by, r.category, r.subcategory;
                """,
                (room, actor),
            )
            row = cur.fetchone()
            if not row:
                conn.rollback()
                return _chat_json({"error": "No pending invite for this private room", "kind": "custom_private"}, 403)
            accepted_room = str(row[0] if row and row[0] else room).strip()
            invited_by = (str(row[1]) if row and row[1] else "")
            accepted_category = (str(row[2]) if row and len(row) > 2 and row[2] else "")
            accepted_subcategory = (str(row[3]) if row and len(row) > 3 and row[3] else "")

            if invited_by and _either_blocked(actor, invited_by):
                conn.commit()
                _emit_to_username(actor, "room_invite_cleared", {"room": accepted_room, "by": invited_by, "kind": "custom_private", "action": "blocked"})
                return _chat_json({"error": "You cannot accept this invite", "kind": "custom_private", "action": "blocked", "room": accepted_room}, 403)

            cur.execute(
                """
                INSERT INTO custom_room_members (room_name, member_user, invited_by, role, last_seen_at)
                VALUES (%s, %s, %s, 'member', NOW())
                ON CONFLICT (room_name, member_user)
                DO UPDATE SET invited_by = COALESCE(EXCLUDED.invited_by, custom_room_members.invited_by),
                              role = CASE
                                  WHEN LOWER(COALESCE(custom_room_members.role, '')) = 'owner' THEN 'owner'
                                  WHEN LOWER(COALESCE(custom_room_members.role, '')) = 'moderator' THEN 'moderator'
                                  ELSE 'member'
                              END,
                              last_seen_at = NOW();
                """,
                (accepted_room, actor, invited_by or None),
            )
        conn.commit()
        _emit_to_username(actor, "room_invite_cleared", {"room": accepted_room, "by": invited_by, "kind": "custom_private", "action": "accepted"})
        return _chat_json({"status": "ok", "deleted": 1, "room": accepted_room, "kind": "custom_private", "action": "accepted", "category": accepted_category, "subcategory": accepted_subcategory}, 200)
    except Exception:
        try:
            if conn:
                conn.rollback()
        except Exception:
            pass
        logging.exception("chat API operation failed")
        return _chat_json({"error": "Server error"}, 500)


@chat_bp.route("/api/custom_rooms/invites/decline", methods=["POST"])
@jwt_required()
def api_decline_custom_room_invite():
    """Decline a private custom-room invite and remove the pending grant row."""
    actor = get_jwt_identity() or ""
    guard = _too_large_json_guard() or _chat_rate_limit_guard("custom_room_invite_decline", "rate_limit_room_invite_response", default_limit=30, default_window=60, actor=actor)
    if guard is not None:
        return guard
    data = request.get_json(silent=True) or {}
    room = (data.get("room") or "").strip()
    if not room:
        return _chat_json({"error": "room required"}, 400)

    conn = None
    try:
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute(
                """
                DELETE FROM custom_room_invites i
                 USING custom_rooms r
                 WHERE LOWER(r.name)=LOWER(i.room_name)
                   AND r.is_private = TRUE
                   AND LOWER(i.room_name)=LOWER(%s)
                   AND LOWER(i.invited_user)=LOWER(%s)
                RETURNING r.name, i.invited_by;
                """,
                (room, actor),
            )
            row = cur.fetchone()
            deleted = 1 if row else 0
            declined_room = str(row[0] if row and row[0] else room).strip()
            invited_by = (str(row[1]) if row and row[1] else "")
        conn.commit()
        if deleted:
            _emit_to_username(actor, "room_invite_cleared", {"room": declined_room, "by": invited_by, "kind": "custom_private", "action": "declined"})
        return _chat_json({"status": "ok", "deleted": deleted, "room": declined_room, "kind": "custom_private", "action": "declined"}, 200)
    except Exception:
        try:
            if conn:
                conn.rollback()
        except Exception:
            pass
        logging.exception("chat API operation failed")
        return _chat_json({"error": "Server error"}, 500)

@chat_bp.route("/api/rooms/invite", methods=["POST"])
@jwt_required()
def api_invite_to_room_any():
    """Invite a user to the current room via the HTTP helper.

    This stays aligned with the Socket.IO /invite command.  Private custom-room
    invites use the F094 lifecycle: canonical room/user lookup, accepted-access
    inviter check, duplicate refresh, and no re-inviting accepted members.
    """
    actor = get_jwt_identity() or ""
    guard = _too_large_json_guard() or _chat_rate_limit_guard("room_invite", "rate_limit_room_invite", default_limit=20, default_window=60, actor=actor)
    if guard is not None:
        return guard
    denied, status = _room_action_denial(actor, "invite")
    if denied is not None:
        return _chat_json(denied, status)
    data = request.get_json(silent=True) or {}
    room = (data.get("room") or "").strip()
    invitee = (data.get("invitee") or "").strip()

    if not room or not invitee:
        return _chat_json({"error": "room and invitee required"}, 400)
    if invitee.lower() == str(actor or "").strip().lower():
        return _chat_json({"error": "Cannot invite yourself"}, 400)

    # Keep the HTTP helper as an in-room action; the room-browser invite modal
    # can invite from the list through /api/custom_rooms/invite instead.
    if not _is_user_in_room_live(actor, room):
        return _chat_json({"error": "You must be in this room to invite users"}, 403)

    conn = None
    try:
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute("SELECT username FROM users WHERE LOWER(username)=LOWER(%s) LIMIT 1;", (invitee,))
            _urow = cur.fetchone()
            if _urow is None:
                return _chat_json({"error": "User not found"}, 404)
            invitee = str(_urow[0])
            if invitee.lower() == str(actor or "").strip().lower():
                return _chat_json({"error": "Cannot invite yourself"}, 400)
            if _either_blocked(actor, invitee):
                return _chat_json({"error": "You cannot invite this user"}, 403)

            row = _fetch_custom_room_casefold(cur, room)
            canonical_room = str(row[0]) if row else room
            created_by = str(row[1] or "") if row else ""

            cur.execute("SELECT 1 FROM chat_rooms WHERE LOWER(name)=LOWER(%s) LIMIT 1;", (canonical_room,))
            has_chat_room = cur.fetchone() is not None
            if not has_chat_room:
                if row:
                    create_room_if_missing(canonical_room, room_kind="custom")
                else:
                    return _chat_json({"error": "Room not found"}, 404)

            if row and bool(row[2]):
                if not can_user_moderate_custom_room(canonical_room, actor):
                    return _chat_json({"error": "Only the room owner or a room moderator can invite users to this private room"}, 403)
                if _custom_room_join_access_exists_cur(cur, canonical_room, invitee, created_by=created_by):
                    return _chat_json({"error": "User already has access to this private room", "kind": "custom_private"}, 409)

                cur.execute(
                    """
                    INSERT INTO custom_room_invites (room_name, invited_user, invited_by)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (room_name, invited_user)
                    DO UPDATE SET invited_by = EXCLUDED.invited_by,
                                  created_at = NOW();
                    """,
                    (canonical_room, invitee, actor),
                )
                conn.commit()
                delivered = _emit_to_username(invitee, "custom_room_invite", {"room": canonical_room, "by": actor, "kind": "custom_private"})
                return _chat_json({"status": "ok", "room": canonical_room, "invitee": invitee, "kind": "custom_private", "delivered": bool(delivered)}, 200)

            cur.execute(
                """
                INSERT INTO room_invites (room_name, invited_user, invited_by)
                VALUES (%s, %s, %s)
                ON CONFLICT (room_name, invited_user)
                DO UPDATE SET invited_by = EXCLUDED.invited_by,
                              created_at = NOW();
                """,
                (canonical_room, invitee, actor),
            )
        conn.commit()
        delivered = _emit_to_username(invitee, "room_invite", {"room": canonical_room, "by": actor, "kind": "room"})
        return _chat_json({"status": "ok", "room": canonical_room, "invitee": invitee, "kind": "room", "delivered": bool(delivered)}, 200)
    except Exception:
        try:
            if conn:
                conn.rollback()
        except Exception:
            pass
        logging.exception("chat API operation failed")
        return _chat_json({"error": "Server error"}, 500)


@chat_bp.route("/api/rooms/invites", methods=["GET"])
@jwt_required()
def api_list_room_invites():
    """Return room invites for the current user (UX notifications)."""
    username = get_jwt_identity() or ""
    guard = _chat_rate_limit_guard("room_invite_list", "rate_limit_room_invite_read", default_limit=120, default_window=60, actor=username)
    if guard is not None:
        return guard
    try:
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT r.name, i.invited_by, i.created_at
                  FROM room_invites i
                  JOIN chat_rooms r ON LOWER(r.name)=LOWER(i.room_name)
                  LEFT JOIN custom_rooms cr ON LOWER(cr.name)=LOWER(r.name)
                 WHERE LOWER(i.invited_user) = LOWER(%s)
                   AND (cr.name IS NULL OR cr.is_private = FALSE)
                   AND NOT EXISTS (
                       SELECT 1
                         FROM blocks b
                        WHERE (LOWER(b.blocker)=LOWER(%s) AND LOWER(b.blocked)=LOWER(i.invited_by))
                           OR (LOWER(b.blocker)=LOWER(i.invited_by) AND LOWER(b.blocked)=LOWER(%s))
                   )
                 ORDER BY i.created_at DESC
                 LIMIT 200;
                """,
                (username, username, username),
            )
            rows = cur.fetchall() or []
        invites = [
            {
                "room": r[0],
                "by": r[1],
                "kind": "room",
                "created_at": (r[2].isoformat() if hasattr(r[2], "isoformat") else str(r[2])),
            }
            for r in rows
        ]
        return jsonify({"invites": invites}), 200
    except Exception:
        logging.exception("chat API operation failed")
        return jsonify({"error": "Server error"}), 500


@chat_bp.route("/api/rooms/invites/accept", methods=["POST"])
@jwt_required()
def api_accept_room_invite():
    """Consume a generic room invite after the client accepts it from the bubble."""
    actor = get_jwt_identity() or ""
    guard = _too_large_json_guard() or _chat_rate_limit_guard("room_invite_accept", "rate_limit_room_invite_response", default_limit=30, default_window=60, actor=actor)
    if guard is not None:
        return guard
    denied, status = _room_action_denial(actor, "accept_invite")
    if denied is not None:
        return _chat_json(denied, status)
    data = request.get_json(silent=True) or {}
    room = (data.get("room") or "").strip()
    if not room:
        return jsonify({"error": "room required"}), 400

    conn = None
    try:
        conn = get_db()
        with conn.cursor() as cur:
            row = _delete_generic_room_invite_casefold(cur, room, actor)
            deleted = 1 if row else 0
            accepted_room = str(row[0] if row and row[0] else room).strip()
            invited_by = (str(row[1]) if row and row[1] else "")
        conn.commit()
        _emit_to_username(actor, "room_invite_cleared", {"room": accepted_room, "by": invited_by, "kind": "room", "action": "accepted"})
        if deleted and invited_by and _either_blocked(actor, invited_by):
            return jsonify({"error": "You cannot accept this invite", "deleted": deleted, "kind": "room", "action": "blocked", "room": accepted_room}), 403
        return jsonify({"status": "ok", "deleted": deleted, "room": accepted_room, "kind": "room", "action": "accepted"}), 200
    except Exception as e:
        try:
            if conn:
                conn.rollback()
        except Exception:
            pass
        logging.exception("chat API operation failed")
        return jsonify({"error": "Server error"}), 500


@chat_bp.route("/api/rooms/invites/decline", methods=["POST"])
@jwt_required()
def api_decline_room_invite():
    """Decline a generic room invite and remove it from the notification bubble."""
    actor = get_jwt_identity() or ""
    guard = _too_large_json_guard() or _chat_rate_limit_guard("room_invite_decline", "rate_limit_room_invite_response", default_limit=30, default_window=60, actor=actor)
    if guard is not None:
        return guard
    data = request.get_json(silent=True) or {}
    room = (data.get("room") or "").strip()
    if not room:
        return jsonify({"error": "room required"}), 400

    conn = None
    try:
        conn = get_db()
        with conn.cursor() as cur:
            row = _delete_generic_room_invite_casefold(cur, room, actor)
            deleted = 1 if row else 0
            declined_room = str(row[0] if row and row[0] else room).strip()
            invited_by = (str(row[1]) if row and row[1] else "")
        conn.commit()
        _emit_to_username(actor, "room_invite_cleared", {"room": declined_room, "by": invited_by, "kind": "room", "action": "declined"})
        return jsonify({"status": "ok", "deleted": deleted, "room": declined_room, "kind": "room", "action": "declined"}), 200
    except Exception as e:
        try:
            if conn:
                conn.rollback()
        except Exception:
            pass
        logging.exception("chat API operation failed")
        return jsonify({"error": "Server error"}), 500
