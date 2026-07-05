#!/usr/bin/env python3
"""Static checks for the per-message image emoticon flood guard."""
from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def fail(message: str) -> None:
    print(f"❌ {message}")
    sys.exit(1)


def require(text: str, token: str, rel: str) -> None:
    if token not in text:
        fail(f"{rel} missing {token!r}")


def main() -> None:
    emoji = read("static/js/chat_parts/0008_emoji_picker.js")
    render = read("static/js/chat_parts/0020_chat_log_rendering.js")
    dm_group = read("static/js/chat_parts/0043_group_history_dm_windows.js")
    room_group_send = read("static/js/chat_parts/0044_room_group_e2ee.js")
    rooms_py = read("realtime/rooms.py")
    groups_py = read("realtime/groups.py")
    socket_handlers = read("socket_handlers.py")
    catalog = read("emoticon_catalog.py")
    routes_auth = read("routes_auth.py")
    config = read("server_config.example.json")

    for token in [
        "ecMessageEmoticonLimit",
        "max_emoticons_per_message",
        "ecLimitCodeEmoticonsInText",
        "ecLimitOutgoingChatEmoticons",
        "ecMakeEmoticonRenderState",
        "ecLimitRichComposerText",
        "limited.trimmed",
        "state: renderState",
        "renderState.count",
        "renderState.removed",
        "Removed ${removed} extra",
    ]:
        require(emoji, token, "0008_emoji_picker.js")

    require(render, "ecMakeEmoticonRenderState", "0020_chat_log_rendering.js")
    require(render, "ecAppendChatTextSegment(container, text, emoticonState", "0020_chat_log_rendering.js")
    require(dm_group, "ecLimitOutgoingChatEmoticons(sendText, { surface: \"pm\"", "0043_group_history_dm_windows.js")
    require(room_group_send, "ecLimitOutgoingChatEmoticons(filteredPlaintext, { surface: \"room\"", "0044_room_group_e2ee.js")
    require(room_group_send, "ecLimitOutgoingChatEmoticons(filteredPlaintext, { surface: \"group\"", "0044_room_group_e2ee.js")
    require(catalog, "filter_excess_emoticon_shortcuts", "emoticon_catalog.py")
    require(socket_handlers, "_filter_excess_emoticons", "socket_handlers.py")
    require(rooms_py, "_filter_excess_emoticons(message)", "realtime/rooms.py")
    require(groups_py, "_filter_excess_emoticons(message)", "realtime/groups.py")
    require(routes_auth, '"max_emoticons_per_message"', "routes_auth.py")
    require(config, '"max_emoticons_per_message": 15', "server_config.example.json")

    sys.path.insert(0, str(ROOT))
    from emoticon_catalog import filter_excess_emoticon_shortcuts  # noqa: WPS433

    sample = ":)" * 20
    filtered, kept, removed = filter_excess_emoticon_shortcuts(sample, max_count=15)
    if kept != 15 or removed != 5 or filtered != ":)" * 15:
        fail(f"functional emoticon flood filtering failed: kept={kept} removed={removed} text={filtered!r}")

    print("✅ Emoticon flood guard doctor passed")


if __name__ == "__main__":
    main()
