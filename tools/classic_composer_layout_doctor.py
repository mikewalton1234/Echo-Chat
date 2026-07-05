#!/usr/bin/env python3
"""Static doctor for the beta.345 classic room composer layout."""
from __future__ import annotations

from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def fail(msg: str) -> None:
    print(f"❌ {msg}")
    raise SystemExit(1)


def main() -> int:
    html = read("templates/chat.html")
    css = read("static/css/chat.css")
    nav_js = read("static/js/chat_parts/0004_navigation_invites_font.js")
    send_js = read("static/js/chat_parts/0044_room_group_e2ee.js")
    render_js = read("static/js/chat_parts/0020_chat_log_rendering.js")

    block_match = re.search(r'<div class="ym-compose roomEmbedCompose ecClassicCompose"[\s\S]*?</div>\s*</div>\s*<!-- Right:', html)
    if not block_match:
        fail("classic room composer block not found")
    block = block_match.group(0)

    expected_order = [
        "roomEmbedFontFamily",
        "roomEmbedFontSize",
        "roomEmbedBoldBtn",
        "roomEmbedItalicBtn",
        "roomEmbedUnderlineBtn",
        "roomEmbedTextColor",
        "roomEmbedEmojiBtn",
        "roomEmbedTorrentBtn",
        "roomEmbedGifBtn",
        "btnRoomEmbedVoice",
        "btnRoomEmbedCam",
        "roomEmbedInput",
        "roomEmbedSend",
    ]
    last = -1
    for token in expected_order:
        idx = block.find(token)
        if idx < 0:
            fail(f"{token} missing from classic composer")
        if idx <= last:
            fail(f"{token} is out of order")
        last = idx

    lowered = block.lower()
    if "highlight" in lowered or "highlighter" in lowered:
        fail("highlighter control should not be present")

    required_css = [
        ".roomEmbedCompose.ecClassicCompose",
        ".ecClassicComposeToolbar",
        "--room-font-family",
        "--room-composer-color",
        ".ec-msgText--styled",
    ]
    for token in required_css:
        if token not in css:
            fail(f"CSS token missing: {token}")

    required_js = [
        "ecBindClassicRoomComposerToolbar",
        "ecBuildStyledRoomMessagePayload",
        "roomComposerBold",
        "roomComposerItalic",
        "roomComposerUnderline",
        "roomComposerColor",
    ]
    for token in required_js:
        if token not in nav_js:
            fail(f"composer JS token missing: {token}")

    if "ecBuildStyledRoomMessagePayload(plaintext)" not in send_js and "ecBuildStyledRoomMessagePayload(filteredPlaintext)" not in send_js:
        fail("room send path does not apply classic styled payloads")
    if "ecBuildStyledTextMessageBody" not in render_js or "ecTryGetStyledTextObject" not in render_js or "styled_text" not in render_js:
        fail("room render path does not support styled text payloads")

    print("✅ Classic composer layout doctor passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
