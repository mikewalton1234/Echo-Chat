#!/usr/bin/env python3
"""Static checks for UI05 room browser search/filter/private-room affordances."""
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
    template = read("templates/chat.html")
    state = read("static/js/chat_parts/0036_room_browser_state.js")
    data = read("static/js/chat_parts/0037_room_browser_data_scope.js")
    rows = read("static/js/chat_parts/0037c_room_browser_row_rendering.js")
    selection = read("static/js/chat_parts/0038_room_browser_selection.js")
    init = read("static/js/chat_parts/0039c_room_browser_init.js")
    css = read("static/css/chat.css")

    for token in ["rbCustomSearch", "rbScopeCustom", "value=\"invited\""]:
        require(template, token, "templates/chat.html")

    for token in ["rbRoomNameKey", "rbMapGetRoomValue", "rbRoomKey(name"]:
        require(state, token, "0036_room_browser_state.js")

    for token in ["customQuery", "filter === 'invited'", "my_room_role", "can_room_moderate"]:
        require(data, token, "0037_room_browser_data_scope.js")

    for token in ["rbCustomRoomAccessLabel", "rbCanInviteToCustomRoom", "is-role-tag", "Invite someone to this private room"]:
        require(rows, token, "0037c_room_browser_row_rendering.js")

    for token in ["suppressedByScope", "Custom scope active", "rbMapGetRoomValue(ROOM_BROWSER.counts"]:
        require(selection, token, "0038_room_browser_selection.js")

    for token in ["const customSearch", "ROOM_BROWSER.customQuery = customSearch.value"]:
        require(init, token, "0039c_room_browser_init.js")

    for token in [".rbToolsCustom .rbCustomSearch", ".rbRowTag.is-role-tag"]:
        require(css, token, "static/css/chat.css")

    print("✅ UI05 room browser doctor passed")


if __name__ == "__main__":
    main()
