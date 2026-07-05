#!/usr/bin/env python3
"""Deep static checks for UI05 room browser canonical state and invite refresh safety."""
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
    state = read("static/js/chat_parts/0036_room_browser_state.js")
    data = read("static/js/chat_parts/0037_room_browser_data_scope.js")
    presence = read("static/js/chat_parts/0037b_room_browser_meta_presence.js")
    selection = read("static/js/chat_parts/0038_room_browser_selection.js")
    invites_ui = read("static/js/chat_parts/0042_group_invites.js")
    invite_socket = read("static/js/chat_parts/0048c_room_invites_webcam_ui.js")
    routes = read("routes_chat.py")
    notes = read("UI05_ROOM_BROWSER_DEEP_RECHECK_NOTES.md")

    for token in [
        "function rbSameRoomName",
        "function rbSameCatalogPath",
        "function rbUnreadKey",
        "function rbGetUnreadCount",
        "function rbSetUnreadCount",
        "rbSameRoomName(roomNameResolved, name)",
        "rbGetUnreadCount(name)",
        "function rbClearUnread(roomName)",
    ]:
        require(state, token, "0036_room_browser_state.js")

    for token in [
        "rbSetUnreadCount(key, cur + 1)",
        "ROOM_BROWSER.customRooms = [];",
        "seenCustomRoomKeys",
        "rbSameCatalogPath(room?.category || '', room?.subcategory || '', c, s)",
        "rbRoomNameKey(x?.name || '') === rbRoomNameKey(cat)",
        "const customQuery = rbNorm(ROOM_BROWSER.customQuery) || roomQuery",
    ]:
        require(data, token, "0037_room_browser_data_scope.js")

    for token in [
        "rbSameRoomName(ROOM_BROWSER.selectedRoom, roomName)",
        "function rbFindRoomMapEntry",
        "rbFindRoomMapEntry(ROOM_BROWSER.roomOccupants, key)",
        "rbSameRoomName(room, UIState.currentRoom || '')",
    ]:
        require(presence, token, "0037b_room_browser_meta_presence.js")

    for token in [
        "r.key === roomKey || (r.isCustom === (li.dataset.custom === '1') && rbSameRoomName(r.name, room))",
        "currentRow.cnt = Number(cnt || 0) || 0",
        "currentRow.full = capacity > 0 ? currentRow.cnt >= capacity",
    ]:
        require(selection, token, "0038_room_browser_selection.js")

    for token in [
        "ROOM_BROWSER.roomScope = 'custom'",
        "rbScheduleInviteBrowserRefresh('accepted_room_invite')",
        "rbScheduleInviteBrowserRefresh('declined_room_invite')",
        "rbScheduleInviteBrowserRefresh('custom_invites_poll')",
    ]:
        require(invites_ui, token, "0042_group_invites.js")

    for token in [
        "function rbScheduleInviteBrowserRefresh",
        "rbScheduleInviteBrowserRefresh('invite_cleared')",
        "rbScheduleInviteBrowserRefresh('custom_room_invite')",
        "rbScheduleInviteBrowserRefresh('room_invite')",
    ]:
        require(invite_socket, token, "0048c_room_invites_webcam_ui.js")

    for token in [
        "SELECT r.name, i.invited_by, i.created_at, r.category, r.subcategory",
        '"category": r[3]',
        '"subcategory": r[4]',
        "RETURNING r.name, i.invited_by, r.category, r.subcategory",
        '"category": accepted_category',
        '"subcategory": accepted_subcategory',
    ]:
        require(routes, token, "routes_chat.py")

    for token in ["0.11.0-beta.366", "stale custom-room rows", "normalized room key"]:
        require(notes, token, "UI05_ROOM_BROWSER_DEEP_RECHECK_NOTES.md")

    print("✅ UI05 deep room browser doctor passed")


if __name__ == "__main__":
    main()
