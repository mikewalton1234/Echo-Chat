#!/usr/bin/env python3
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
checks = [
    ("realtime/presence_social.py", "UPDATE users\n                       SET online = TRUE"),
    ("realtime/presence_social.py", "heal after refreshes, stale DB flags"),
    ("realtime/presence_social.py", 'emit("friends_presence", [_public_presence_for_user(f)'),
    ("socket_handlers.py", "or bool(online)) if username else bool(online)"),
    ("socket_handlers.py", "or bool(db_online)) if username else bool(db_online)"),
    ("static/js/chat_parts/0029_friends_requests_blocks.js", 'socket.emit("get_friend_presence")'),
    ("static/js/chat_parts/0029_friends_requests_blocks.js", "function ecDumpFriendsPresenceState"),
    ("static/js/chat_parts/0035_missed_presence_embed.js", 'socket.emit("get_friend_presence")'),
]
failed = 0
for rel, needle in checks:
    p = ROOT / rel
    text = p.read_text(errors="replace") if p.exists() else ""
    if needle in text:
        print(f"PASS {rel}: {needle}")
    else:
        print(f"FAIL {rel}: missing {needle}")
        failed += 1
sys.exit(1 if failed else 0)
