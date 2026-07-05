#!/usr/bin/env python3
"""Static UI02 checks for room message rendering consistency.

This doctor verifies that room messages use one shared rendering path for text,
styled text, GIFs, emoticons, torrents, media cards, reactions, and pins instead
of duplicating per-message-type parsing in the room append function.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def require(haystack: str, needle: str, label: str) -> None:
    if needle not in haystack:
        raise SystemExit(f"❌ UI02 message rendering doctor failed: missing {label}: {needle!r}")


def forbid(haystack: str, needle: str, label: str) -> None:
    if needle in haystack:
        raise SystemExit(f"❌ UI02 message rendering doctor failed: forbidden stale {label}: {needle!r}")


def main() -> int:
    rendering_js = read("static/js/chat_parts/0020_chat_log_rendering.js")
    torrent_js = read("static/js/chat_parts/0021_dm_file_torrent_rendering.js")
    room_js = read("static/js/chat_parts/0023_room_reactions.js")
    runtime_js = read("static/js/chat_parts/0041_rooms_runtime.js")
    css = read("static/css/chat.css")

    for token in [
        "function ecTryParseChatWireObject",
        "function ecTryGetStyledTextObject",
        "function ecBuildGifMessageBody",
        "function ecTryParseRoomRadioWireObject",
        "function ecTryBuildWireSpecialMessageBody",
        "function ecClassifyChatMessageKind",
        "function ecBuildRoomMessageBody",
        "nestedSpecial",
    ]:
        require(rendering_js, token, "shared rendering helper")

    for token in [
        "function ecTryNormalizeTorrentMessage",
        "styled_text",
        "const nested = ecTryNormalizeTorrentMessage(obj.text)",
        "buildTorrentCard(torrent)",
    ]:
        require(torrent_js, token, "torrent backward-compatible special renderer")

    for token in [
        "const renderedKind =",
        "ecClassifyChatMessageKind(message)",
        "item.classList.add(`ec-msgItem--${renderedKind}`)",
        "contentWrap.dataset.messageKind = renderedKind",
        "ecBuildRoomMessageBody(message",
        "initialCounts = payload?.reaction_counts",
        "viewEl._ym.pinnedPayload",
        "_setRoomPinnedMessage(viewEl, messageId, viewEl._ym.pinnedPayload",
    ]:
        require(room_js, token, "room append unified rendering/reaction/pin flow")

    for stale in [
        "const specialBody =",
        "contentWrap.appendChild(specialBody)",
        "message.trimStart().startsWith(\"{\")",
    ]:
        forbid(room_js, stale, "duplicated room JSON renderer")

    for token in [
        "socket.on(\"message_reactions\"",
        "socket.on(\"room_message_pinned\"",
        "socket.on(\"room_message_unpinned\"",
    ]:
        require(runtime_js, token, "live reaction/pin socket handlers")

    for token in [
        ".msgReactions",
        "flex-wrap: wrap",
        ".ec-msgItem--room .ec-msgContent--rich",
        ".ec-msgItem--room.ec-msgItem--torrent .ym-torrentCard",
        ".ec-msgItem--room.ec-msgItem--gif .ym-gifWrap",
        ".ec-msgItem--pinned .ec-msgContent",
    ]:
        require(css, token, "room rich-message/reaction CSS")

    print("✅ UI02 message rendering doctor passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
