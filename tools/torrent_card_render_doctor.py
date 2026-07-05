#!/usr/bin/env python3
"""Static doctor for torrent room-card rendering safety."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def fail(msg: str) -> None:
    print(f"❌ {msg}")
    raise SystemExit(1)


def require(text: str, token: str, label: str) -> None:
    if token not in text:
        fail(f"{label} missing token: {token}")


def main() -> int:
    composer_js = read("static/js/chat_parts/0004_navigation_invites_font.js")
    rendering_js = read("static/js/chat_parts/0020_chat_log_rendering.js")
    torrent_js = read("static/js/chat_parts/0021_dm_file_torrent_rendering.js")
    room_js = read("static/js/chat_parts/0023_room_reactions.js")
    send_js = read("static/js/chat_parts/0044_room_group_e2ee.js")

    for token in [
        "ecClassicRoomComposerShouldBypassStyle",
        "torrent_id",
        "download_url",
        "infohash",
        "return text;",
    ]:
        require(composer_js, token, "classic composer wire bypass")

    for token in [
        "ecTryBuildWireSpecialMessageBody(text",
        "ecBuildSpecialMessageBody(message)",
        "ecTryGetStyledTextObject",
        "ecClassifyChatMessageKind",
    ]:
        require(rendering_js, token, "generic message special renderer")

    for token in [
        "function ecTryParseWireJsonObject",
        "function ecNormalizeTorrentWireObject",
        "function ecTryNormalizeTorrentMessage",
        "function ecBuildSpecialMessageBody",
        "styled_text",
        "buildTorrentCard(torrent)",
        "download_url",
        "file_name",
    ]:
        require(torrent_js, token, "torrent wire normalization")

    for token in [
        "ecClassifyChatMessageKind(message)",
        "ecBuildRoomMessageBody(message",
        "ec-msgContent--rich",
        "contentWrap.appendChild(body)",
    ]:
        require(room_js, token, "room message torrent rendering")

    require(send_js, "inferRoomMessageKindFromPlaintext(outgoingPlaintext)", "room send kind inference")
    require(send_js, "message_kind: messageKind", "room send message_kind")

    print("✅ Torrent card render doctor passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
