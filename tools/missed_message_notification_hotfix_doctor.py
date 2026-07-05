#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
checks = []

def require(path, needles):
    text = (ROOT / path).read_text(encoding='utf-8')
    for needle in needles:
        if needle not in text:
            raise SystemExit(f"FAIL {path}: missing {needle}")
        checks.append(f"PASS {path}: {needle}")

require('static/js/chat_parts/0002_state_storage.js', [
    'livePmUnreadCounts: new Map()',
])
require('static/js/chat_parts/0035_missed_presence_embed.js', [
    'function ecGetCombinedMissedPmItems',
    'function ecBumpLivePmUnread',
    'function ecClearLivePmUnread',
    'renderMissedPmListInto($(\'railMissedPmList\'), combined)',
    'ecClearLivePmUnread(targetPeer)',
])
require('static/js/chat_parts/0027_dock_alert_rail.js', [
    'ecGetMissedPmTotals',
])
require('static/js/chat_parts/0028_dock_counts.js', [
    'ecGetMissedPmTotals',
])
require('static/js/chat_parts/0045_transfers_crypto.js', [
    'shouldCountAsMissedPm',
    'ecBumpLivePmUnread(senderName, 1',
    'openPrivateChat(senderName, { clearLiveUnread: suppressActivePmAlert, consumeOffline: false })',
])
require('static/js/chat_parts/0043_group_history_dm_windows.js', [
    'function ecIsGroupConversationActive',
    'function bumpGroupUnreadCache',
    'render.readSafe && messageId !== null && groupIsActive',
])
require('static/js/chat_parts/0041_rooms_runtime.js', [
    'rbBumpUnread(room); rbRenderRoomLists();',
    'quietActiveRoomMessage && room === UIState.currentRoom',
])
require('static/js/chat_parts/0018_windows_manager.js', [
    'function ecMarkConversationWindowSeen',
    'ecClearLivePmUnread(peer)',
    'markGroupMessagesRead(gid, ids)',
])
print('\n'.join(checks))
print('missed message notification hotfix doctor passed')
