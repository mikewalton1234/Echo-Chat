#!/usr/bin/env python3
"""Static checks for beta.440 private-message typing hardening."""
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
MIN_BETA = 440


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def fail(message: str) -> None:
    print(f"FAIL: {message}")
    sys.exit(1)


def require(text: str, token: str, rel: str) -> None:
    if token not in text:
        fail(f"{rel} missing {token!r}")


def beta_number(version: str) -> int:
    match = re.search(r"beta\.(\d+)", version)
    if not match:
        fail(f"VERSION.txt has unexpected beta version: {version!r}")
    return int(match.group(1))


version = read("VERSION.txt").strip()
if beta_number(version) < MIN_BETA:
    fail(f"VERSION.txt is {version!r}, expected beta.{MIN_BETA} or newer")

convo_js = read("static/js/chat_parts/0043_group_history_dm_windows.js")
dm_py = read("realtime/dm.py")
pm_js = read("static/js/chat_parts/0045_transfers_crypto.js")
doc = read("docs/PM_TYPING_HARDENING_beta440.md")
manifest = read("release_manifest_beta440_pm_typing_hardening.json")

for token in [
    "function ecTypingEmit(eventName, payload, onAck = null)",
    "return false;",
    "function ecConversationTypingStart(input)",
    "function ecConversationTypingArmStopTimer(input)",
    "function ecStopAllConversationTyping(opts = {})",
    "function ecClearAllConversationTypingIndicators()",
    "window.__ecConvoTypingLifecycleBound",
    "document.addEventListener('visibilitychange'",
    "window.addEventListener('pagehide'",
    "socket.on('disconnect'",
    "socket.on('connect'",
    "setTimeout(() => ecRenderConversationTyping(surface, conv), 0)",
    "input.addEventListener('focus'",
    "input.addEventListener('compositionend'",
    "input._ecTypingLastSent = 0;",
    "window.ecPmTypingDebugState",
]:
    require(convo_js, token, "static/js/chat_parts/0043_group_history_dm_windows.js")

for token in [
    "def _emit_direct_stop_typing(sender: str, to: str) -> bool:",
    "_emit_to_user(clean_to, \"direct_stop_typing\"",
    "Stop-typing should clear stale receiver UI",
    "_emit_direct_stop_typing(sender, to)",
    "delivered = _emit_to_user(to, \"private_message\", live_payload)",
]:
    require(dm_py, token, "realtime/dm.py")

if dm_py.count("_emit_direct_stop_typing(sender, to)") < 2:
    fail("realtime/dm.py should use _emit_direct_stop_typing for explicit stops and accepted PM cleanup")

require(pm_js, "ecSetConversationTyping('pm', senderName, senderName, false, 0)", "static/js/chat_parts/0045_transfers_crypto.js")

for token in [
    "PM typing now re-renders immediately",
    "Server-side `send_direct_message` now emits",
    "direct_stop_typing",
    "python tools/pm_typing_hardening_doctor.py",
]:
    require(doc, token, "docs/PM_TYPING_HARDENING_beta440.md")

for token in [
    "v0.11.0-beta.440-pm-typing-hardening",
    "Private-message typing hardening",
    "python tools/pm_typing_hardening_doctor.py",
]:
    require(manifest, token, "release_manifest_beta440_pm_typing_hardening.json")

print("PASS: beta.440 PM typing hardening static checks passed")
