#!/usr/bin/env python3
"""Static checks for UI06 friends/groups drawer canonical state and touch safety."""
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
    identity = read("static/js/chat_parts/0025_dock_identity_friends.js")
    friends = read("static/js/chat_parts/0029_friends_requests_blocks.js")
    pending = read("static/js/chat_parts/0035_missed_presence_embed.js")
    ctx = read("static/js/chat_parts/0031_user_context_menu.js")
    groups = read("static/js/chat_parts/0042_group_invites.js")
    group_win = read("static/js/chat_parts/0043_group_history_dm_windows.js")
    realtime = read("static/js/chat_parts/0048b_reconnect_restore_runtime.js")
    css = read("static/css/chat.css")
    notes = read("UI06_FRIENDS_GROUPS_DRAWER_PATCH_NOTES.md")

    for token in [
        "function ecNormalizeUsernameKey",
        "function ecCanonicalUsernameList",
        "function ecUserSetHasName",
        "function ecSetPresenceForUsername",
        "function ecGetPresenceForUsername",
    ]:
        require(identity, token, "0025_dock_identity_friends.js")

    for token in [
        "const EC_PENDING_FRIEND_ACTIONS = new Set()",
        "function scheduleFriendsListRenderRefresh",
        "function getFriendAssignmentKey",
        "ecCanonicalUsernameList(Array.isArray(friends) ? friends : [], { excludeSelf: true, excludeBlocked: true })",
        "const p = ecGetPresenceForUsername(friend)",
        "state.assignments[getFriendAssignmentKey(friend)]",
        "knownFriendKeys",
    ]:
        require(friends, token, "0029_friends_requests_blocks.js")

    for token in [
        "ecCanonicalUsernameList(Array.isArray(requests) ? requests : [], { excludeSelf: true, excludeBlocked: true, excludeFriends: true })",
        "EC_PENDING_FRIEND_ACTIONS.has(`accept:${actionKey}`)",
        "EC_PENDING_FRIEND_ACTIONS.has(`reject:${actionKey}`)",
        "ecNormalizeUsernameKey(it) !== wantedKey",
        "scheduleFriendsListRenderRefresh('friends_presence')",
        "scheduleFriendsListRenderRefresh('friend_presence_update')",
        "ecSetPresenceForUsername(p.username, p)",
    ]:
        require(pending, token, "0035_missed_presence_embed.js")

    for token in [
        "return ecNormalizeUsernameKey(a) === ecNormalizeUsernameKey(b)",
        "return ecUserSetHasName(setLike, username)",
    ]:
        require(ctx, token, "0031_user_context_menu.js")

    for token in [
        "function selectGroupDockRow",
        "function dockGroupUnreadSet",
        "function groupRoleChip",
        "dockGroupUnreadSet(gid, unreadCount)",
        "li.dataset.search = `${gname} ${gid} group ${role} ${memberCount} member ${unreadCount} unread`",
        "selectGroupDockRow(gid, li); openGroupWindow(gid, gname)",
        "setMiniActionBusy(inviteBtn, true, '➕')",
        "setMiniActionBusy(revokeInviteBtn, true, '↩')",
        "normalizeGroupNameInput(inv?.group_name || groupId)",
    ]:
        require(groups, token, "0042_group_invites.js")

    if groups.count("actions.appendChild(revokeInviteBtn);") != 1:
        fail("0042_group_invites.js should append revokeInviteBtn exactly once")

    for token in [
        "UIState.groupUnreadCounts?.get?.(String(gid))",
        "UIState.groupUnreadCounts.set(String(gid), count)",
    ]:
        require(group_win, token, "0043_group_history_dm_windows.js")

    for token in [
        "renderPendingFriendRequestsInto($('pendingRequestsList'), UIState.pendingRequests)",
        "getPendingFriendRequests();\n  getFriends();",
        "getPendingFriendRequests();\n});",
    ]:
        require(realtime, token, "0048b_reconnect_restore_runtime.js")

    for token in [
        "UI06 friends/groups drawer hardening",
        "@media (hover: none), (pointer: coarse)",
        ".dock.ecShell #groupList .groupDockItem.hasUnread",
    ]:
        require(css, token, "static/css/chat.css")

    for token in ["0.11.0-beta.366", "presence-refresh throttling", "duplicate friend requests", "touch-friendly"]:
        require(notes, token, "UI06_FRIENDS_GROUPS_DRAWER_PATCH_NOTES.md")

    print("✅ UI06 friends/groups drawer doctor passed")


if __name__ == "__main__":
    main()
