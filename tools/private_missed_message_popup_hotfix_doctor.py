#!/usr/bin/env python3
"""Static guard for beta.391 private missed-message summary/debug fix."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
checks: list[str] = []


def require(path: str, needles: list[str]) -> None:
    text = (ROOT / path).read_text(encoding="utf-8")
    for needle in needles:
        if needle not in text:
            raise SystemExit(f"FAIL {path}: missing {needle}")
        checks.append(f"PASS {path}: {needle}")

require("static/js/chat_parts/0035_missed_presence_embed.js", [
    "function ecMaybePopupMissedPmSummary",
    "toastAction(message, {",
    "openDockRailPanel('missed')",
    "maybeBrowserNotify('Missed private messages'",
    "forceActiveConversationPopup: !!(opts.forceActiveConversationPopup || opts.forcePopupEvenIfActive || opts.incomingPrivateMessage)",
    "opts.reason === 'incoming_private_message'",
    "let EC_LAST_MISSED_PM_POPUP_TOTAL = 0;",
    "function ecForceMissedBubbleVisible",
    "function ecResolveMissedPmTotals",
    "ecResolveMissedPmTotals(items, opts.total)",
    "ecResolveMissedPmTotals(null, total)",
    "alreadyCountedById",
])

require("static/js/chat_parts/0027_dock_alert_rail.js", [
    "const badgeMissedTotal = Number($('railMissedCount')?.textContent || 0) || 0;",
    "const missedTotal = Math.max(0, stateMissedTotal, badgeMissedTotal);",
])

require("static/js/chat_parts/0045_transfers_crypto.js", [
    "incoming_private_message_preopen",
    "Prime the missed bubble BEFORE openPrivateChat()",
])

require("static/js/chat_parts/0048b_reconnect_restore_runtime.js", [
    "const listTotal = list.reduce",
    "const summaryTotal = Math.max(0, Number.isFinite(serverTotal) ? serverTotal : 0, listTotal);",
    "ecMaybePopupMissedPmSummary(list, { total: summaryTotal, reason: 'server_summary' });",
    "MISSED_SUMMARY_TOAST_ARMED = false;",
])

require("static/css/chat.css", [
    ".dockAlertBubble.ecForceVisible",
    ".dockAlertBubble.ecMissedPmAttention",
    "@keyframes ec-missed-pm-pulse",
    "beta.390: missed bubble regression guard",
    ".dockAlertRail {",
])


# beta.391 old-vs-new regression guard: the missed badge summary must count
# every undelivered offline/private-message row like beta.322 did. Delivery
# filtering belongs to fetch_offline_pms, not the badge summary.
summary_text = (ROOT / "socket_handlers.py").read_text(encoding="utf-8")
summary_start = summary_text.find("def _emit_missed_pm_summary")
summary_end = summary_text.find("def _emit_missed_pm_summary_to_user", summary_start)
summary_body = summary_text[summary_start:summary_end]
if "message LIKE 'EC1:%'" in summary_body or 'e2ee_summary_filter' in summary_body:
    raise SystemExit("FAIL socket_handlers.py: missed summary still filters by EC1 prefix")
checks.append("PASS socket_handlers.py: missed summary restored beta.322 all-undelivered-row count")

require("static/js/chat_parts/0035_missed_presence_embed.js", [
    "function ecEnableMissedPmDebug",
    "function ecSimulateMissedPmBubble",
    "function ecDumpMissedPmDebugState",
    "function ecRepairMissedBubblePaintPath",
])

print("\n".join(checks))
print("private missed-message beta.391 doctor passed")
