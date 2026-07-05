#!/usr/bin/env python3
"""Deep static checks for UI02 room message rendering edge cases.

This verifies the second-pass safeguards for duplicate room messages, race-safe
reaction updates, canonical message ids, bounded reaction pills, and rich-card
layout containment.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def require(haystack: str, needle: str, label: str) -> None:
    if needle not in haystack:
        raise SystemExit(f"❌ UI02 deep doctor failed: missing {label}: {needle!r}")


def forbid(haystack: str, needle: str, label: str) -> None:
    if needle in haystack:
        raise SystemExit(f"❌ UI02 deep doctor failed: forbidden {label}: {needle!r}")


def main() -> int:
    rendering_js = read("static/js/chat_parts/0020_chat_log_rendering.js")
    reactions_js = read("static/js/chat_parts/0023_room_reactions.js")
    runtime_js = read("static/js/chat_parts/0041_rooms_runtime.js")
    css = read("static/css/chat.css")

    for token in [
        "function ecStyledTextInnerValue",
        "depth > 4",
        "ecClassifyChatMessageKind(ecStyledTextInnerValue(styledObj), depth + 1)",
        "const nestedSpecial = ecTryBuildWireSpecialMessageBody(ecStyledTextInnerValue(obj)",
    ]:
        require(rendering_js, token, "bounded styled-text unwrapping")

    for token in [
        "function _roomMsgIdKey",
        "function _normalizeRoomReactionCounts",
        "const EC_MAX_REACTION_PILLS = 20",
        "function _storeRoomReactionCounts",
        "function _getRoomReactionCounts",
        "if (!viewEl._ym.reactionCounts) viewEl._ym.reactionCounts = new Map()",
        "const existing = _findMsgEl(viewEl, messageId)",
        "Do not duplicate the visible row",
        "_storeRoomReactionCounts(viewEl, messageId, incomingCounts)",
        "_renderReactionPills(rx, _getRoomReactionCounts(viewEl, messageId))",
        "reactionCounts?.delete(key)",
    ]:
        require(reactions_js, token, "reaction/message-id race and dedupe guard")

    for token in [
        "const messageId = payload?.message_id || payload?.messageId || payload?.id",
        "_storeRoomReactionCounts(view, messageId, counts)",
        "_renderReactionPills(rx, (typeof _getRoomReactionCounts === \"function\") ? _getRoomReactionCounts(view, messageId) : counts)",
    ]:
        require(runtime_js, token, "early socket reaction cache")

    for token in [
        "/* UI02 deep recheck: keep rich room cards bounded under long payload metadata. */",
        ".ym-torrentCard,",
        "overflow-wrap: anywhere;",
        ".ec-msgItem--room .ec-msgContent--rich .reactPill",
    ]:
        require(css, token, "bounded rich-card CSS")

    for stale in [
        "const msgEl = _findMsgEl(viewEl, messageKey)",
        "Object.keys(counts);\n  const ordered = [\n    ...DEFAULT_REACTION_EMOJIS.filter(e => keys.includes(e))",
    "String(viewEl._ym.pinnedMessageId) === messageId",
    "const messageId = payload?.message_id;",
    "ecClassifyChatMessageKind(styledObj.text)",
    "String(obj?.text ?? \"\")",
    "_renderReactionPills(rx, counts);",
    "viewEl._ym.msgIndex.set(messageId, item);\n  if (viewEl._ym.pinnedMessageId && String(viewEl._ym.pinnedMessageId) === messageId)",
    ]:
        forbid(reactions_js + runtime_js + rendering_js, stale, "stale UI02 pattern")

    print("✅ UI02 message rendering deep doctor passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
