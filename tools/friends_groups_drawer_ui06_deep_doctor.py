#!/usr/bin/env python3
"""Static checks for UI06 deep drawer invite action-state safety."""
from __future__ import annotations
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]

def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")

def require(text: str, token: str, rel: str) -> None:
    if token not in text:
        print(f"❌ {rel} missing {token!r}")
        sys.exit(1)

def main() -> None:
    groups = read("static/js/chat_parts/0042_group_invites.js")
    css = read("static/css/chat.css")
    notes = read("UI06_FRIENDS_GROUPS_DRAWER_DEEP_RECHECK_NOTES.md")
    for token in [
        "function groupInviteActionKey",
        "function groupInviteActionIsPending",
        "function setGroupInviteButtonsBusy",
        "function runGroupInviteButtonAction",
        "await runGroupInviteButtonAction(inv, [acceptBtn, declineBtn], acceptGroupInvite)",
        "await runGroupInviteButtonAction(inv, [acceptBtn, declineBtn], declineGroupInvite)",
        "setGroupInviteButtonsBusy([acceptBtn, declineBtn], groupInviteActionIsPending(inv))",
    ]:
        require(groups, token, "0042_group_invites.js")
    if groups.count("runGroupInviteButtonAction(inv, [acceptBtn, declineBtn]") < 4:
        print("❌ invite accept/decline handlers in both groups and alerts should use shared busy action runner")
        sys.exit(1)
    require(css, ".dock.ecShell button.isBusy", "static/css/chat.css")
    for token in ["0.11.0-beta.367", "Double taps", "aria-busy", "same pending action key"]:
        require(notes, token, "UI06_FRIENDS_GROUPS_DRAWER_DEEP_RECHECK_NOTES.md")
    print("✅ UI06 friends/groups drawer deep doctor passed")

if __name__ == "__main__":
    main()
