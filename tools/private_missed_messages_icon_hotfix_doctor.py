#!/usr/bin/env python3
"""Static guard for beta.386 private missed-message icon hotfix."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
checks: list[str] = []

def require(path: str, needles: list[str]) -> None:
    text = (ROOT / path).read_text(encoding='utf-8')
    for needle in needles:
        if needle not in text:
            raise SystemExit(f"FAIL {path}: missing {needle}")
        checks.append(f"PASS {path}: {needle}")

require('socket_handlers.py', [
    'def _store_offline_pm(sender: str, receiver: str, cipher: str) -> int | None:',
    'RETURNING id;',
    'return int(row[0]) if row and row[0] is not None else None',
])
require('realtime/dm.py', [
    'unread_id = _store_offline_pm(sender, to, cipher)',
    'live_payload["id"] = int(unread_id)',
    'server_unread = bool(unread_id)',
    '_emit_missed_pm_summary_to_user(to)',
])
require('static/js/chat_parts/0045_transfers_crypto.js', [
    'openPrivateChat(senderName, { clearLiveUnread: suppressActivePmAlert, consumeOffline: false })',
    'UIState.pendingOfflineDmSeen.add(msgId)',
    'serverBacked: msgId > 0',
    'ackOfflinePmIds([msgId], { quiet: true })',
])
require('static/js/chat_parts/0048b_reconnect_restore_runtime.js', [
    'const activelyReading = win && (typeof ecIsConversationWindowActive === \'function\') && ecIsConversationWindowActive(win);',
    'if (activelyReading) {',
])
require('static/js/chat_parts/0035_missed_presence_embed.js', [
    'const serverKeys = new Set();',
    'serverBacked && serverKeys.has(key)',
    'server_backed: !!(opts.serverBacked || existing?.item?.server_backed)',
])
require('static/js/chat_parts/0043_group_history_dm_windows.js', [
    "typeof ecGetCombinedMissedPmItems === 'function'",
])
print('\n'.join(checks))
print('private missed-message icon hotfix doctor passed')
