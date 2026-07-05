#!/usr/bin/env python3
"""Static doctor for the block/unblock room privacy and test-checklist pass.

This does not replace the manual two-browser checklist. It verifies that the
critical server/client guardrails added for block/unblock privacy are present in
this source tree.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

CHECKS: list[tuple[str, str, str]] = [
    ("socket_handlers.py", "def _socketio_room_targets", "Socket.IO transport-room participant resolver exists"),
    ("socket_handlers.py", "manager.get_participants", "Socket.IO manager participants are consulted"),
    ("socket_handlers.py", "upsert_connected_session", "stale shared session state can be repaired from transport-room membership"),
    ("socket_handlers.py", "def _emit_room_users_snapshot", "room user snapshots are centralized"),
    ("socket_handlers.py", "current_user", "room users payload is personalized per viewer"),
    ("socket_handlers.py", "Blocking is not room", "room roster keeps blocked users visible as room members"),
    ("socket_handlers.py", "blocked_by_me", "room users payload exposes block metadata instead of filtering roster"),
    ("realtime/rooms.py", "def _emit_room_chat_message_filtered", "room chat delivery is block-aware"),
    ("realtime/rooms.py", "_is_blocked(target_name, clean_sender)", "room fanout skips only viewers who blocked the sender"),
    ("realtime/rooms.py", "_emit_once(request.sid)", "sender echo is direct so sends do not appear to disappear"),
    ("realtime/rooms.py", "def _room_live_allowed_recipient_names", "live allowed E2EE recipient list exists"),
    ("realtime/rooms.py", "def _room_e2ee_recipient_mismatch", "room E2EE recipient mismatch detector exists"),
    ("realtime/rooms.py", "room_roster_stale", "stale self-only room E2EE envelopes are rejected for client retry"),
    ("realtime/rooms.py", "def _emit_room_signal_filtered", "room typing/stop-typing signals are block-aware"),
    ("realtime/rooms.py", "\"room_typing\", _room_typing_payload", "room typing uses filtered delivery helper"),
    ("realtime/presence_social.py", "def _emit_pair_room_visibility_refresh", "block/unblock roster refresh helper exists"),
    ("realtime/presence_social.py", "live_rooms = _pair_live_rooms", "delayed refresh re-reads live rooms"),
    ("realtime/presence_social.py", "for delay in (0.35, 1.10, 2.25)", "delayed refresh passes cover unblock ordering races"),
    ("realtime/presence_social.py", "def _emit_unblock_realtime_refresh", "unblock pushes realtime cleanup/refresh"),
    ("static/js/chat_parts/0031_user_context_menu.js", "unblock_user", "front-end unblock action exists"),
    ("static/js/chat_parts/0035_missed_presence_embed.js", "blocked_users_list", "front-end blocked-list refresh listener exists"),
    ("static/js/chat_parts/0041_rooms_runtime.js", "ecRoomShouldHideBlockedSender", "room renderer hides blocked senders client-side"),
        ("static/js/chat_parts/0044_room_group_e2ee.js", "room_roster_stale", "room E2EE sender handles server stale-roster response"),
    ("static/js/chat_parts/0044_room_group_e2ee.js", "ecRefreshRoomRosterBeforeRetry", "room E2EE sender refreshes roster before retry"),
    ("static/js/chat_parts/0044_room_group_e2ee.js", "excludeBlocked: false", "room E2EE keeps users I blocked in outbound recipient set unless they blocked me"),
    ("routes_auth.py", "room_key_scope", "public-key lookup has room-scope viewer-side block behavior"),
    ("BLOCK_UNBLOCK_FULL_TEST_CHECKLIST_beta426.md", "Quick release-smoke sequence", "manual block/unblock release-smoke checklist is included"),
    ("BLOCK_ROOM_MODEL_FIX_NOTES_beta427.md", "Blocking is not room membership", "beta.427 corrected block model notes are included"),
]


def read(path: str) -> str:
    p = ROOT / path
    if not p.exists():
        raise AssertionError(f"missing file: {path}")
    return p.read_text(encoding="utf-8", errors="replace")


def main() -> int:
    failures: list[str] = []
    for path, needle, label in CHECKS:
        try:
            text = read(path)
            if needle not in text:
                failures.append(f"FAIL {path}: missing {needle!r} — {label}")
            else:
                print(f"PASS {path}: {label}")
        except Exception as exc:
            failures.append(f"FAIL {path}: {exc}")

    if failures:
        print("\n".join(failures))
        return 1
    print("\nPASS block/unblock deep checklist doctor")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
