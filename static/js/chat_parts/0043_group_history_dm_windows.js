// buildDuplicateMessageHints compatibility hook
// ───────────────────────────────────────────────────────────────────────────────
// Group history pagination (Load older)
// ───────────────────────────────────────────────────────────────────────────────
const GROUP_HISTORY_PAGE_SIZE = 200;

function groupMsgId(m) {
  const v = (m && (m.message_id ?? m.messageId ?? m.id)) ?? null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

function groupHistState(win) {
  if (!win) return { oldestId: null, loading: false, done: true };
  if (!win._groupHist) win._groupHist = { oldestId: null, loading: false, done: false };
  return win._groupHist;
}

function groupSeenIds(win) {
  if (!win) return new Set();
  if (!win._groupSeenMessageIds) win._groupSeenMessageIds = new Set();
  return win._groupSeenMessageIds;
}

function rememberGroupMessageId(win, messageId) {
  const id = groupMsgId({ message_id: messageId });
  if (id === null) return false;
  groupSeenIds(win).add(id);
  return true;
}

function hasSeenGroupMessageId(win, messageId) {
  const id = groupMsgId({ message_id: messageId });
  if (id === null) return false;
  return groupSeenIds(win).has(id);
}


function groupWindowIsVisible(win) {
  try {
    return !!win && !win.classList.contains('hidden') && !!document.body?.contains(win);
  } catch {
    return false;
  }
}

function shouldNotifyGroupMessage(win, groupId, sender) {
  const from = String(sender || '').trim();
  const me = String(currentUser || '').trim().toLowerCase();
  if (!from || (me && from.toLowerCase() === me)) return false;
  // If the group window is already visible and Echo Chat is focused, the message
  // line itself is the notification. Avoid noisy duplicate toasts/popups.
  if (groupWindowIsVisible(win) && typeof ecIsWindowActivelyFocused === 'function' && ecIsWindowActivelyFocused()) return false;
  return true;
}

function updateGroupUnreadCache(groupId, unreadCount) {
  const gid = Number(groupId || 0);
  const count = Math.max(0, Number(unreadCount || 0) || 0);
  if (!gid) return;
  try {
    if (!UIState.groupUnreadCounts) UIState.groupUnreadCounts = new Map();
    UIState.groupUnreadCounts.set(gid, count);
    if (Array.isArray(UIState.myGroups)) {
      const idx = UIState.myGroups.findIndex((g) => Number(g?.id || g?.group_id || 0) === gid);
      if (idx >= 0) UIState.myGroups[idx] = { ...UIState.myGroups[idx], unread_count: count, unread: count };
    }
  } catch {}
}

function markGroupMessagesRead(groupId, messageIds) {
  const gid = Number(groupId || 0);
  if (!gid) return;
  const ids = [];
  const seen = new Set();
  (Array.isArray(messageIds) ? messageIds : [messageIds]).forEach((raw) => {
    const mid = groupMsgId({ message_id: raw });
    if (mid === null || seen.has(mid)) return;
    seen.add(mid);
    ids.push(mid);
  });
  if (!ids.length) return;
  try {
    // Legacy single-message equivalent: socket.emit('mark_group_read', { group_id: gid, message_id: mid }
    socket.emit('mark_group_read', { group_id: gid, message_ids: ids }, (res) => {
      if (res?.success && typeof res.unread_count !== 'undefined') updateGroupUnreadCache(gid, res.unread_count);
    });
  } catch {}
}

function markVisibleGroupMessageRead(groupId, messageId) {
  markGroupMessagesRead(groupId, [messageId]);
}

async function ecJoinGroupChatAck(groupId) {
  const gid = Number(groupId || 0);
  if (!gid) return { success: false, error: 'bad_group_id' };
  return (typeof ecEmitAck === 'function')
    ? await ecEmitAck('join_group_chat', { group_id: gid }, 8500, { connectBannerText: '🔌 Reconnecting before opening group chat…' })
    : await new Promise((resolve) => socket.emit('join_group_chat', { group_id: gid }, (res) => resolve(res || { success: false })));
}

async function ecLeaveGroupChatAck(groupId) {
  const gid = Number(groupId || 0);
  if (!gid) return { success: false, error: 'bad_group_id' };
  return (typeof ecEmitAck === 'function')
    ? await ecEmitAck('leave_group_chat', { group_id: gid }, 3500, { connectBannerText: '🔌 Reconnecting before leaving group chat…', bannerDelayMs: 1200 })
    : await new Promise((resolve) => socket.emit('leave_group_chat', { group_id: gid }, (res) => resolve(res || { success: false })));
}

function updateGroupOlderUI(win) {
  const st = groupHistState(win);
  const btn = win?._ym?.groupOlderBtn;
  const hint = win?._ym?.groupOlderHint;
  if (!btn) return;
  btn.disabled = !!st.loading || !!st.done || !st.oldestId;
  if (hint) hint.textContent = st.loading ? "Loading…" : (st.done ? "No more" : "Older");
}

function ensureGroupHistoryToolbar(win, groupId) {
  if (!win || !win._ym?.log) return;
  if (win._ym.groupOlderBtn) return;

  const body = win.querySelector('.ym-body');
  if (!body) return;

  const bar = document.createElement('div');
  bar.className = 'ym-toolbar ym-groupToolbar';

  const btn = document.createElement('button');
  btn.type = 'button';
  btn.className = 'ym-toolBtn';
  btn.title = 'Load older messages';
  btn.textContent = '⬆';

  const hint = document.createElement('span');
  hint.className = 'ym-toolHint';
  hint.textContent = 'Older';

  bar.appendChild(btn);
  bar.appendChild(hint);

  const parent = win._ym.log?.parentElement || body;
  parent.insertBefore(bar, win._ym.log);

  win._ym.groupOlderBtn = btn;
  win._ym.groupOlderHint = hint;
  btn.onclick = () => loadOlderGroupHistory(win, groupId);

  updateGroupOlderUI(win);
}

async function groupHistoryItemToText(m) {
  const isEnc = !!m?.is_encrypted || m?.is_encrypted === 1 || m?.is_encrypted === true;
  const cipher = (m && typeof m.cipher === 'string') ? m.cipher : null;
  let msgForUi = String(m?.message ?? '');

  const candidate = cipher || msgForUi;
  if (candidate && typeof candidate === 'string' && candidate.startsWith(GROUP_ENVELOPE_PREFIX)) {
    if (HAS_WEBCRYPTO && window.myPrivateCryptoKey) {
      try {
        msgForUi = await decryptGroupEnvelope(window.myPrivateCryptoKey, candidate);
      } catch (e) {
        console.error(e);
        msgForUi = '🔒 Encrypted message';
      }
    } else {
      msgForUi = '🔒 Encrypted message (unlock to read)';
    }
  } else if (isEnc && !cipher) {
    msgForUi = '🔒 Encrypted message';
  }
  return msgForUi;
}

async function appendGroupHistory(win, hist) {
  const log = win?._ym?.log;
  if (!log) return;
  const id = String(win?._ym?.id || "");
  const gid = id.startsWith("group:") ? Number(id.split(":")[1]) : null;
  const renderedIds = [];

  for (const m of (hist || [])) {
    const messageId = groupMsgId(m);
    if (messageId !== null && hasSeenGroupMessageId(win, messageId)) continue;
    if (messageId !== null) {
      rememberGroupMessageId(win, messageId);
      renderedIds.push(messageId);
    }
    const sender = String(m?.sender || "?");
    const ts = m?.timestamp || m?.ts || null;
    const msgForUi = await groupHistoryItemToText(m);

    let parsed = null;
    if (typeof msgForUi === "string") {
      const s = msgForUi.trim();
      if (s.startsWith("{") && s.endsWith("}")) {
        try { parsed = JSON.parse(s); } catch { parsed = null; }
      }
    }

    if (parsed && typeof parsed === "object" && parsed.kind === "file" && parsed.file_id) {
      if (!parsed.group_id && gid) parsed.group_id = gid;
      appendFileLine(win, `${sender}:`, parsed, { peer: gid ? `group:${gid}` : null, direction: "in", ts });
    } else if (parsed && typeof parsed === "object" && parsed.kind === "torrent") {
      appendTorrentLine(win, `${sender}:`, parsed.t || parsed, { peer: gid ? `group:${gid}` : null, direction: "in", ts });
    } else {
      appendLine(win, `${sender}:`, msgForUi, { ts });
    }
  }
  if (gid && renderedIds.length) markGroupMessagesRead(gid, renderedIds);
  scheduleScrollLogToBottom(log);
}

async function insertGroupHistoryAtTop(win, hist) {
  const log = win?._ym?.log;
  if (!log) return;

  const id = String(win?._ym?.id || "");
  const gid = id.startsWith("group:") ? Number(id.split(":")[1]) : null;
  const renderedIds = [];

  const beforeH = log.scrollHeight;
  const beforeTop = log.scrollTop;

  const temp = document.createElement("div");
  for (const m of (hist || [])) {
    const messageId = groupMsgId(m);
    if (messageId !== null && hasSeenGroupMessageId(win, messageId)) continue;
    if (messageId !== null) {
      rememberGroupMessageId(win, messageId);
      renderedIds.push(messageId);
    }
    const sender = String(m?.sender || "?");
    const ts = m?.timestamp || m?.ts || null;
    const msgForUi = await groupHistoryItemToText(m);

    let parsed = null;
    if (typeof msgForUi === "string") {
      const s = msgForUi.trim();
      if (s.startsWith("{") && s.endsWith("}")) {
        try { parsed = JSON.parse(s); } catch { parsed = null; }
      }
    }

    if (parsed && typeof parsed === "object" && parsed.kind === "file" && parsed.file_id) {
      if (!parsed.group_id && gid) parsed.group_id = gid;
      appendGenericMessageItem(temp, `${sender}:`, buildFileCardElement(parsed, { peer: gid ? `group:${gid}` : null, direction: "in" }), { ts, kind: "file", context: "group" });
    } else if (parsed && typeof parsed === "object" && parsed.kind === "torrent") {
      appendGenericMessageItem(temp, `${sender}:`, buildTorrentCard(parsed.t || parsed), { ts, kind: "torrent", context: "group" });
    } else {
      appendGenericMessageItem(temp, `${sender}:`, buildTextMessageBody(msgForUi), { ts, kind: parseGifMarker(msgForUi) ? "gif" : "text", context: "group" });
    }
  }

  const first = log.firstElementChild;
  const incomingLastDate = temp._ecChatUi?.lastDateKey || null;
  if (incomingLastDate && first?.classList?.contains("ec-dateSep") && first.dataset?.dateKey === incomingLastDate) {
    try { first.remove(); } catch {}
  }

  while (temp.firstChild) {
    log.insertBefore(temp.firstChild, log.firstChild);
  }

  if (gid && renderedIds.length) markGroupMessagesRead(gid, renderedIds);
  const afterH = log.scrollHeight;
  log.scrollTop = beforeTop + (afterH - beforeH);
}

function updateOldestId(win, hist) {
  const st = groupHistState(win);
  const ids = (hist || []).map(groupMsgId).filter((x) => x !== null);
  if (ids.length) {
    const minId = Math.min(...ids);
    st.oldestId = (st.oldestId === null || st.oldestId === undefined) ? minId : Math.min(st.oldestId, minId);
  }
}

function loadOlderGroupHistory(win, groupId) {
  const st = groupHistState(win);
  if (st.loading || st.done) return;
  if (!st.oldestId) {
    st.done = true;
    updateGroupOlderUI(win);
    return;
  }

  st.loading = true;
  updateGroupOlderUI(win);

  const historyRequest = (typeof ecEmitAck === 'function')
    ? ecEmitAck('get_group_history', { group_id: Number(groupId), before_id: st.oldestId, limit: GROUP_HISTORY_PAGE_SIZE }, 8500, { connectBannerText: '🔌 Reconnecting before loading group history…', bannerDelayMs: 1200 })
    : new Promise((resolve) => socket.emit('get_group_history', { group_id: Number(groupId), before_id: st.oldestId, limit: GROUP_HISTORY_PAGE_SIZE }, (res) => resolve(res || { success: false })));

  historyRequest.then(async (res) => {
    st.loading = false;
    if (!res?.success) {
      updateGroupOlderUI(win);
      toast('❌ Could not load older messages', 'error');
      return;
    }

    const hist = Array.isArray(res.history) ? res.history : [];
    if (!hist.length) {
      st.done = true;
      updateGroupOlderUI(win);
      return;
    }

    await insertGroupHistoryAtTop(win, hist);
    updateOldestId(win, hist);
    if (hist.length < GROUP_HISTORY_PAGE_SIZE) st.done = true;
    updateGroupOlderUI(win);
  }).catch(() => {
    st.loading = false;
    updateGroupOlderUI(win);
    toast('❌ Could not load older messages', 'error');
  });
}


function normalizeGroupMemberDetails(rawMembers, fallbackMembers = []) {
  const rows = [];
  const seen = new Set();
  const validRole = (role) => {
    const r = String(role || 'member').trim().toLowerCase();
    return ['owner', 'admin', 'moderator', 'member'].includes(r) ? r : 'member';
  };
  const pushRow = (username, role = 'member', extra = {}) => {
    const name = String(username || '').trim();
    if (!name) return;
    const key = name.toLowerCase();
    if (seen.has(key)) return;
    seen.add(key);
    const normalizedRole = validRole(role);
    rows.push({
      username: name,
      role: normalizedRole,
      role_label: extra.role_label || groupMemberRoleLabel(normalizedRole),
      role_rank: Number.isFinite(Number(extra.role_rank)) ? Number(extra.role_rank) : groupRoleRank(normalizedRole),
      capabilities: extra.capabilities || null,
      is_self: Boolean(extra.is_self),
      joined_at: extra.joined_at || '',
    });
  };

  (Array.isArray(rawMembers) ? rawMembers : []).forEach((row) => {
    if (typeof row === 'string') pushRow(row, 'member');
    else if (row && typeof row === 'object') pushRow(row.username || row.name || row.user, row.role || 'member', row);
  });
  (Array.isArray(fallbackMembers) ? fallbackMembers : []).forEach((row) => {
    if (typeof row === 'string') pushRow(row, 'member');
    else if (row && typeof row === 'object') pushRow(row.username || row.name || row.user, row.role || 'member', row);
  });

  const rank = { owner: 0, admin: 1, moderator: 2, member: 3 };
  rows.sort((a, b) => {
    const ar = rank[a.role] ?? 9;
    const br = rank[b.role] ?? 9;
    if (ar !== br) return ar - br;
    return a.username.localeCompare(b.username, undefined, { sensitivity: 'base' });
  });
  return rows;
}

function rememberGroupMembersFromResponse(groupId, res = {}) {
  const gid = Number(groupId || 0);
  if (!gid) return [];
  const details = normalizeGroupMemberDetails(res?.member_details, res?.members);
  const names = details.map((m) => m.username);
  UIState.groupMembers.set(gid, names);
  UIState.groupMemberDetails.set(gid, details);
  if (typeof res?.unread_count !== 'undefined') updateGroupUnreadCache(gid, res.unread_count);
  try {
    if (Array.isArray(UIState.myGroups)) {
      const idx = UIState.myGroups.findIndex((g) => Number(g?.id || g?.group_id || 0) === gid);
      if (idx >= 0) {
        UIState.myGroups[idx] = {
          ...UIState.myGroups[idx],
          role: res?.role || res?.current_role || UIState.myGroups[idx].role,
          role_label: res?.role_label || UIState.myGroups[idx].role_label,
          role_rank: Number.isFinite(Number(res?.role_rank)) ? Number(res.role_rank) : UIState.myGroups[idx].role_rank,
          capabilities: res?.capabilities || res?.current_capabilities || UIState.myGroups[idx].capabilities,
          member_count: Number(res?.total || details.length || UIState.myGroups[idx].member_count || 0) || 0,
        };
      }
    }
  } catch {}
  return details;
}

function groupMemberPresence(username) {
  const exact = UIState.presence?.get?.(username);
  let p = exact;
  if (!p && UIState.presence && typeof UIState.presence.forEach === 'function') {
    const wanted = String(username || '').toLowerCase();
    UIState.presence.forEach((value, key) => {
      if (!p && String(key || '').toLowerCase() === wanted) p = value;
    });
  }
  const presence = String(p?.presence || (p?.online ? 'online' : 'offline')).toLowerCase();
  if (!p?.online || presence === 'offline' || presence === 'invisible') return { className: 'offline', label: 'Offline' };
  if (presence === 'busy') return { className: 'busy', label: 'Busy' };
  if (presence === 'away') return { className: 'away', label: 'Away' };
  return { className: 'online', label: 'Online' };
}

function groupMemberRoleLabel(role) {
  switch (String(role || 'member').toLowerCase()) {
    case 'owner': return 'Owner';
    case 'admin': return 'Admin';
    case 'moderator': return 'Moderator';
    default: return 'Member';
  }
}


const EC_GROUP_ROLE_RANK = { member: 0, moderator: 1, admin: 2, owner: 3 };

function groupRoleRank(role) {
  return EC_GROUP_ROLE_RANK[String(role || 'member').toLowerCase()] ?? 0;
}

function groupMemberDetailFor(groupId, username) {
  const gid = Number(groupId || 0);
  const wanted = String(username || '').trim().toLowerCase();
  if (!gid || !wanted) return null;
  const details = normalizeGroupMemberDetails(UIState.groupMemberDetails?.get?.(gid), UIState.groupMembers?.get?.(gid));
  return details.find((m) => String(m.username || '').toLowerCase() === wanted) || null;
}

function groupMetaFromCache(groupId, title = '') {
  const gid = Number(groupId || 0);
  const cached = (Array.isArray(UIState.myGroups) ? UIState.myGroups : []).find((g) => Number(g?.id || 0) === gid) || null;
  const titleName = String(title || '').replace(/\s*\(#\d+\)\s*$/, '').replace(/^Group\s+—\s+/, '').trim();
  const groupName = String(cached?.group_name || titleName || (gid ? `Group #${gid}` : 'Group')).trim();
  const groupDescription = String(cached?.group_description || '').trim();
  const cachedRole = String(cached?.role || '').trim().toLowerCase();
  return {
    group_id: gid,
    group_name: groupName,
    group_description: groupDescription,
    role: cachedRole || '',
  };
}

function currentGroupRole(groupId) {
  const gid = Number(groupId || 0);
  const cached = groupMetaFromCache(gid)?.role;
  return cached || groupMemberDetailFor(gid, currentUser)?.role || 'member';
}

function currentGroupCanModerate(groupId, targetUsername, minRole = 'moderator') {
  const me = currentGroupRole(groupId);
  const mine = groupRoleRank(me);
  const min = groupRoleRank(minRole);
  if (mine < min) return false;
  const target = groupMemberDetailFor(groupId, targetUsername);
  if (!target) return false;
  return mine > groupRoleRank(target.role);
}

function groupVoiceUserIsActive(groupId, username) {
  const gid = Number(groupId || 0);
  const name = String(username || '').trim();
  if (!gid || !name || typeof voiceMediaMapForRoom !== 'function') return false;
  try {
    const st = voiceMediaMapForRoom(groupVoiceRoomName(gid))?.get?.(name);
    return !!(st && st.voice_on);
  } catch {
    return false;
  }
}

function refreshGroupVoiceIndicatorsForRoom(room) {
  const gid = groupVoiceRoomIdFromName(room);
  if (!gid) return;
  const win = UIState.windows.get('group:' + String(gid));
  if (win) renderGroupMemberRoster(win, gid);
}

function groupDisplayError(e, fallback = 'Group action failed') {
  return String(e?.message || e?.error || e || fallback || 'Group action failed');
}

async function groupApiPost(groupId, path, body = {}) {
  const gid = Number(groupId || 0);
  if (!gid) throw new Error('Missing group id');
  return apiJson(`/api/groups/${encodeURIComponent(gid)}${path}`, {
    method: 'POST',
    body: JSON.stringify(body || {}),
  });
}

function groupMutedSetFor(groupId) {
  const gid = Number(groupId || 0);
  return UIState.groupMutedMembers?.get?.(gid) || new Set();
}

function groupMemberIsMuted(groupId, username) {
  const name = String(username || '').trim().toLowerCase();
  if (!name) return false;
  try { return groupMutedSetFor(groupId).has(name); } catch { return false; }
}

async function groupRefreshMutes(groupId, opts = {}) {
  const gid = Number(groupId || 0);
  if (!gid) return { success: false, mutes: [] };
  try {
    const res = await apiJson(`/api/groups/${encodeURIComponent(gid)}/mutes`, { method: 'GET' });
    const rows = Array.isArray(res?.mutes) ? res.mutes : [];
    const names = new Set(rows.map((m) => String(m?.username || '').trim().toLowerCase()).filter(Boolean));
    UIState.groupMutedMembers?.set?.(gid, names);
    if (!opts.silent && rows.length) toast(`🔇 ${rows.length} muted member${rows.length === 1 ? '' : 's'} in this group`, 'info');
    return { success: true, mutes: rows };
  } catch (e) {
    if (!opts.silent) toast(`❌ Could not load group mute list: ${groupDisplayError(e)}`, 'error');
    return { success: false, error: groupDisplayError(e), mutes: [] };
  }
}

async function groupRefreshAfterAction(groupId) {
  const gid = Number(groupId || 0);
  if (!gid) return;
  try {
    const win = UIState.windows.get('group:' + String(gid));
    await refreshGroupMemberRoster(gid, win || null);
  } catch {}
  try { await groupRefreshMutes(gid, { silent: true }); } catch {}
  try { renderGroupSettingsMembers(gid); renderGroupSettingsMutes(gid); } catch {}
  try { refreshMyGroups(); } catch {}
}

async function groupMuteMember(groupId, username) {
  const u = String(username || '').trim();
  if (!u) return;
  try {
    await groupApiPost(groupId, '/mute', { username: u });
    toast(`🔇 Muted ${u} in this group`, 'ok');
    await groupRefreshAfterAction(groupId);
  } catch (e) {
    toast(`❌ Mute failed: ${groupDisplayError(e)}`, 'error');
  }
}

async function groupUnmuteMember(groupId, username) {
  const u = String(username || '').trim();
  if (!u) return;
  try {
    await groupApiPost(groupId, '/unmute', { username: u });
    toast(`🎤 Unmuted ${u} in this group`, 'ok');
    await groupRefreshAfterAction(groupId);
  } catch (e) {
    toast(`❌ Unmute failed: ${groupDisplayError(e)}`, 'error');
  }
}

async function groupKickMember(groupId, username) {
  const u = String(username || '').trim();
  if (!u) return;
  const ok = await ecConfirm(`Remove ${u} from this group?`, {
    title: `Kick ${u}?`,
    confirmLabel: 'Remove from group',
    danger: true,
    focusCancel: true,
  });
  if (!ok) return;
  try {
    await groupApiPost(groupId, '/kick', { username: u });
    toast(`👢 Removed ${u} from the group`, 'ok');
    await groupRefreshAfterAction(groupId);
  } catch (e) {
    toast(`❌ Kick failed: ${groupDisplayError(e)}`, 'error');
  }
}

async function groupSetMemberRole(groupId, username, role) {
  const u = String(username || '').trim();
  const r = String(role || '').trim().toLowerCase();
  if (!u || !r) return;
  const label = groupMemberRoleLabel(r);
  const ok = await ecConfirm(`Change ${u}'s group role to ${label}?`, {
    title: `Set ${u} as ${label}?`,
    confirmLabel: 'Change role',
    focusCancel: true,
  });
  if (!ok) return;
  try {
    await groupApiPost(groupId, '/set_role', { username: u, role: r });
    toast(`✅ ${u} is now ${label}`, 'ok');
    await groupRefreshAfterAction(groupId);
  } catch (e) {
    toast(`❌ Role change failed: ${groupDisplayError(e)}`, 'error');
  }
}

async function groupTransferOwnership(groupId, username) {
  const u = String(username || '').trim();
  if (!u) return;
  const ok = await ecConfirm(`Transfer ownership of this group to ${u}? You will become an admin.`, {
    title: 'Transfer group ownership?',
    confirmLabel: 'Transfer ownership',
    danger: true,
    focusCancel: true,
  });
  if (!ok) return;
  try {
    await groupApiPost(groupId, '/transfer_ownership', { username: u });
    toast(`👑 ${u} is now the group owner`, 'ok');
    await groupRefreshAfterAction(groupId);
  } catch (e) {
    toast(`❌ Ownership transfer failed: ${groupDisplayError(e)}`, 'error');
  }
}

async function groupKickMemberFromVoice(groupId, username) {
  const u = String(username || '').trim();
  if (!u) return;
  try {
    await groupApiPost(groupId, '/voice/kick', { username: u });
    toast(`🎤 Disconnected ${u} from group voice`, 'ok');
    refreshGroupVoiceIndicatorsForRoom(groupVoiceRoomName(groupId));
  } catch (e) {
    toast(`❌ Voice disconnect failed: ${groupDisplayError(e)}`, 'error');
  }
}

async function inviteSelectedUserToCurrentRoom(username) {
  const u = String(username || '').trim();
  const room = String(UIState.roomEmbedRoom || UIState.currentRoom || '').trim();
  if (!u) return;
  if (!room) return toast('Join a room first, then invite someone.', 'warn');
  try {
    await apiJson('/api/rooms/invite', { method: 'POST', body: JSON.stringify({ room, invitee: u }) });
    toast(`✅ Invited ${u} to ${room}`, 'ok');
  } catch (e) {
    toast(`❌ Room invite failed: ${groupDisplayError(e)}`, 'error');
  }
}

function ecSetGroupWindowTitle(win, groupId, groupName) {
  const gid = Number(groupId || 0);
  const cleanName = String(groupName || '').trim() || `#${gid}`;
  const nextTitle = `Group — ${cleanName} (#${gid})`;
  if (!win || !gid) return nextTitle;
  if (win._ym?.titleEl) {
    win._ym.titleEl.textContent = nextTitle;
    win._ym.titleEl.title = nextTitle;
  }
  win.setAttribute('aria-label', nextTitle);
  win.dataset.windowTitle = nextTitle;
  win.dataset.windowFullTitle = nextTitle;
  try {
    const taskBtn = UIState.minimized?.get?.('group:' + String(gid));
    if (taskBtn) taskBtn.textContent = nextTitle;
  } catch {}
  return nextTitle;
}

async function groupUpdateMetadata(groupId, name, description = '', opts = {}) {
  const gid = Number(groupId || 0);
  const cleanName = String(name || '').trim();
  const cleanDescription = String(description || '').trim();
  if (!gid) return { success: false, error: 'Missing group id' };
  if (!cleanName) return { success: false, error: 'Group name required' };
  if (cleanName.length > 64) return { success: false, error: 'Group name too long (max 64)' };
  if (cleanDescription.length > 512) return { success: false, error: 'Description too long (max 512)' };

  await apiJson(`/api/groups/${encodeURIComponent(gid)}`, {
    method: 'PATCH',
    body: JSON.stringify({ name: cleanName, description: cleanDescription }),
  });

  const win = UIState.windows.get('group:' + String(gid));
  if (win) ecSetGroupWindowTitle(win, gid, cleanName);
  try {
    const idx = Array.isArray(UIState.myGroups) ? UIState.myGroups.findIndex((g) => Number(g?.id || 0) === gid) : -1;
    if (idx >= 0) {
      UIState.myGroups[idx] = { ...UIState.myGroups[idx], group_name: cleanName, group_description: cleanDescription };
    }
  } catch {}
  if (!opts.silent) toast('✅ Group settings saved', 'ok');
  try { refreshMyGroups(); } catch {}
  return { success: true };
}

async function groupRenameDescription(groupId, title = '') {
  const gid = Number(groupId || 0);
  if (!gid) return;
  const meta = groupMetaFromCache(gid, title);
  const role = currentGroupRole(gid);
  if (groupRoleRank(role) < groupRoleRank('admin')) {
    toast('Only group admins and the owner can rename or edit the description.', 'warn');
    return;
  }
  const name = await ecPrompt('New group name:', meta.group_name, {
    title: 'Rename group',
    inputLabel: 'Group name',
    confirmLabel: 'Save',
    maxLength: 64,
  });
  if (name === null) return;
  const desc = await ecPrompt('Group description:', meta.group_description || '', {
    title: 'Group description',
    inputLabel: 'Description',
    confirmLabel: 'Save',
    maxLength: 512,
  });
  if (desc === null) return;
  try {
    const res = await groupUpdateMetadata(gid, name, desc);
    if (!res?.success) toast(`❌ Save failed: ${res?.error || 'Invalid group settings'}`, 'error');
  } catch (e) {
    toast(`❌ Save failed: ${groupDisplayError(e)}`, 'error');
  }
}

async function groupLeaveFromSettings(groupId, title = '') {
  const gid = Number(groupId || 0);
  if (!gid) return;
  const ok = await ecConfirm(`Leave ${title || 'this group'}?`, {
    title: 'Leave group?',
    confirmLabel: 'Leave group',
    danger: true,
    focusCancel: true,
  });
  if (!ok) return;
  try {
    const res = await groupApiPost(gid, '/leave', {});
    forceLeaveGroupUI(gid, res?.status === 'deleted' ? 'deleted' : 'left');
  } catch (e) {
    toast(`❌ Leave failed: ${groupDisplayError(e)}`, 'error');
  }
}

async function groupDeleteFromSettings(groupId, title = '') {
  const gid = Number(groupId || 0);
  if (!gid) return;
  const ok = await ecConfirm(`Delete ${title || 'this group'} for everyone? This cannot be undone.`, {
    title: 'Delete group?',
    confirmLabel: 'Delete group',
    danger: true,
    focusCancel: true,
  });
  if (!ok) return;
  try {
    await apiJson(`/api/groups/${encodeURIComponent(gid)}`, { method: 'DELETE' });
    forceLeaveGroupUI(gid, 'deleted');
  } catch (e) {
    toast(`❌ Delete failed: ${groupDisplayError(e)}`, 'error');
  }
}

let EC_GROUP_SETTINGS_MODAL = null;
let EC_GROUP_SETTINGS_ACTIVE = null;

function groupSettingsDetailSnapshot(modal = EC_GROUP_SETTINGS_MODAL) {
  if (!modal) return { name: '', description: '' };
  return {
    name: String(modal.querySelector('#ecGroupSettingsName')?.value || '').trim(),
    description: String(modal.querySelector('#ecGroupSettingsDescription')?.value || '').trim(),
  };
}

function updateGroupSettingsSaveState() {
  const modal = EC_GROUP_SETTINGS_MODAL;
  const active = EC_GROUP_SETTINGS_ACTIVE;
  if (!modal || !active) return;
  const saveBtn = modal.querySelector('#ecGroupSettingsSave');
  const dirtyEl = modal.querySelector('#ecGroupSettingsDirty');
  const nameCount = modal.querySelector('#ecGroupSettingsNameCount');
  const descCount = modal.querySelector('#ecGroupSettingsDescriptionCount');
  const snap = groupSettingsDetailSnapshot(modal);
  if (nameCount) nameCount.textContent = `${snap.name.length} / 64`;
  if (descCount) descCount.textContent = `${snap.description.length} / 512`;
  const changed = snap.name !== String(active.originalName || '') || snap.description !== String(active.originalDescription || '');
  const valid = !!snap.name && snap.name.length <= 64 && snap.description.length <= 512;
  if (dirtyEl) {
    dirtyEl.textContent = changed ? 'Unsaved changes' : 'Saved';
    dirtyEl.classList.toggle('dirty', changed);
  }
  if (saveBtn) {
    saveBtn.disabled = !active.canEditMeta || !changed || !valid;
    saveBtn.textContent = changed ? 'Save changes' : 'No changes';
  }
}

function groupSettingsStats(groupId) {
  const gid = Number(groupId || 0);
  const details = normalizeGroupMemberDetails(UIState.groupMemberDetails?.get?.(gid), UIState.groupMembers?.get?.(gid));
  let online = 0;
  let voice = 0;
  details.forEach((member) => {
    const username = String(member.username || '').trim();
    const presence = groupMemberPresence(username);
    if (presence.className !== 'offline') online += 1;
    if (groupVoiceUserIsActive(gid, username)) voice += 1;
  });
  return { total: details.length, online, voice, details };
}

function updateGroupSettingsStats(groupId) {
  const modal = EC_GROUP_SETTINGS_MODAL;
  if (!modal) return;
  const stats = groupSettingsStats(groupId);
  const memberEl = modal.querySelector('#ecGroupSettingsMemberCount');
  const onlineEl = modal.querySelector('#ecGroupSettingsOnlineCount');
  const voiceEl = modal.querySelector('#ecGroupSettingsVoiceCount');
  if (memberEl) memberEl.textContent = `${stats.total} member${stats.total === 1 ? '' : 's'}`;
  if (onlineEl) onlineEl.textContent = `${stats.online} online`;
  if (voiceEl) voiceEl.textContent = `${stats.voice} in voice`;
  return stats;
}

function renderGroupSettingsMembers(groupId) {
  const modal = EC_GROUP_SETTINGS_MODAL;
  if (!modal) return;
  const gid = Number(groupId || 0);
  const list = modal.querySelector('#ecGroupSettingsMembersList');
  const summary = modal.querySelector('#ecGroupSettingsMembersSummary');
  if (!list) return;
  ecClearNode(list);
  const stats = updateGroupSettingsStats(gid) || groupSettingsStats(gid);
  const q = String(modal.querySelector('#ecGroupSettingsMemberSearch')?.value || '').trim().toLowerCase();
  const matches = q ? stats.details.filter((m) => `${m.username} ${m.role}`.toLowerCase().includes(q)) : stats.details;
  if (summary) {
    summary.textContent = q
      ? `${matches.length} matching member${matches.length === 1 ? '' : 's'} of ${stats.total}`
      : `${stats.total} group member${stats.total === 1 ? '' : 's'} shown by role`;
  }
  if (!matches.length) {
    list.appendChild(ecCreateEl('li', { className: 'ecGroupSettingsMemberEmpty', text: q ? 'No matching members.' : 'No group members loaded yet.' }));
    return;
  }
  matches.slice(0, 80).forEach((member) => {
    const username = String(member.username || '').trim();
    if (!username) return;
    const roleLabel = groupMemberRoleLabel(member.role);
    const presence = groupMemberPresence(username);
    const voiceActive = groupVoiceUserIsActive(gid, username);
    const mutedInGroup = groupMemberIsMuted(gid, username);
    const isSelf = String(username).toLowerCase() === String(currentUser || '').toLowerCase();
    const li = ecCreateEl('li', { className: `ecGroupSettingsMember ${presence.className}` });
    const left = ecCreateEl('button', { className: 'ecGroupSettingsMemberMain', type: 'button', attrs: { title: isSelf ? 'This is you' : `Open private chat with ${username}` } }, [
      ecCreateEl('span', { className: `presenceDot ${presence.className}` }),
      ecCreateEl('span', { className: 'ecGroupSettingsMemberName', text: username }),
      ecCreateEl('span', { className: 'ecGroupSettingsMemberMeta', text: `${roleLabel} · ${presence.label}${voiceActive ? ' · Voice' : ''}${mutedInGroup ? ' · Muted' : ''}` }),
    ]);
    left.disabled = isSelf;
    left.addEventListener('click', () => { if (!isSelf) openPrivateChat(username); });
    const role = ecCreateEl('span', { className: `ecGroupSettingsRoleBadge role-${String(member.role || 'member').toLowerCase()}`, text: isSelf ? 'You' : roleLabel });
    li.appendChild(left);
    li.appendChild(role);
    list.appendChild(li);
  });
  if (matches.length > 80) {
    list.appendChild(ecCreateEl('li', { className: 'ecGroupSettingsMemberEmpty', text: `Showing first 80 of ${matches.length}. Use search to narrow the list.` }));
  }
}

function renderGroupSettingsMutes(groupId) {
  const modal = EC_GROUP_SETTINGS_MODAL;
  if (!modal) return;
  const gid = Number(groupId || 0);
  const panel = modal.querySelector('#ecGroupSettingsMutedPanel');
  const list = modal.querySelector('#ecGroupSettingsMutedList');
  const summary = modal.querySelector('#ecGroupSettingsMutedSummary');
  if (!panel || !list) return;
  const canModerate = groupRoleRank(currentGroupRole(gid)) >= groupRoleRank('moderator');
  panel.classList.toggle('hidden', !canModerate);
  ecClearNode(list);
  if (!canModerate) return;
  const muted = Array.from(groupMutedSetFor(gid));
  if (summary) summary.textContent = muted.length ? `${muted.length} muted member${muted.length === 1 ? '' : 's'}` : 'No muted members.';
  if (!muted.length) {
    list.appendChild(ecCreateEl('li', { className: 'ecGroupSettingsMemberEmpty', text: 'Nobody is muted in this group.' }));
    return;
  }
  muted.slice(0, 80).forEach((lowerName) => {
    const detail = groupMemberDetailFor(gid, lowerName);
    const username = String(detail?.username || lowerName || '').trim();
    const li = ecCreateEl('li', { className: 'ecGroupSettingsMember muted' });
    li.appendChild(ecCreateEl('span', { className: 'ecGroupSettingsMemberName', text: username }));
    const btn = ecCreateEl('button', { className: 'ghostBtn smallBtn', type: 'button', text: 'Unmute' });
    btn.addEventListener('click', () => groupUnmuteMember(gid, username));
    li.appendChild(btn);
    list.appendChild(li);
  });
}

function runGroupSettingsCommandChip(command) {
  const active = EC_GROUP_SETTINGS_ACTIVE;
  const modal = EC_GROUP_SETTINGS_MODAL;
  if (!active?.groupId || !modal) return;
  const cmd = String(command || '').trim().toLowerCase();
  if (cmd === 'invite') {
    modal.querySelector('#ecGroupSettingsInviteInput')?.focus?.();
    return;
  }
  if (cmd === 'rename') {
    modal.querySelector('#ecGroupSettingsName')?.focus?.();
    return;
  }
  if (cmd === 'desc') {
    modal.querySelector('#ecGroupSettingsDescription')?.focus?.();
    return;
  }
  if (cmd === 'voice') {
    modal.querySelector('#ecGroupSettingsVoice')?.click?.();
    return;
  }
  if (cmd === 'users') {
    modal.querySelector('#ecGroupSettingsRefresh')?.click?.();
  }
}

function closeGroupSettingsModal() {
  if (!EC_GROUP_SETTINGS_MODAL) return;
  const active = EC_GROUP_SETTINGS_ACTIVE;
  EC_GROUP_SETTINGS_ACTIVE = null;
  EC_GROUP_SETTINGS_MODAL.classList.add('hidden');
  try { active?.restoreFocus?.focus?.(); } catch {}
}

function ensureGroupSettingsModal() {
  if (EC_GROUP_SETTINGS_MODAL) return EC_GROUP_SETTINGS_MODAL;

  const modal = ecCreateEl('div', {
    id: 'ecGroupSettingsModal',
    className: 'modal hidden ecGroupSettingsModal',
    role: 'dialog',
    ariaModal: 'true',
    attrs: { 'aria-labelledby': 'ecGroupSettingsTitle' },
  });
  const card = ecCreateEl('div', { className: 'modalCard ecGroupSettingsCard' });

  const closeBtn = ecCreateEl('button', { id: 'ecGroupSettingsClose', className: 'iconBtn', type: 'button', text: '×', attrs: { 'aria-label': 'Close group settings' } });
  card.appendChild(ecCreateEl('div', { className: 'modalHead ecGroupSettingsHead' }, [
    ecCreateEl('div', {}, [
      ecCreateEl('div', { id: 'ecGroupSettingsTitle', className: 'modalTitle', text: 'Group settings' }),
      ecCreateEl('div', { id: 'ecGroupSettingsSubTitle', className: 'ecGroupSettingsSubTitle', text: 'Manage this group without typing actions.' }),
    ]),
    closeBtn,
  ]));

  const nameInput = ecCreateEl('input', { id: 'ecGroupSettingsName', className: 'modalInput ecGroupSettingsInput', type: 'text', autocomplete: 'off', attrs: { maxlength: '64' } });
  const descInput = ecCreateEl('textarea', { id: 'ecGroupSettingsDescription', className: 'modalInput ecGroupSettingsTextarea', attrs: { maxlength: '512', rows: '4' } });
  const inviteInput = ecCreateEl('input', { id: 'ecGroupSettingsInviteInput', className: 'modalInput ecGroupSettingsInviteInput', type: 'text', autocomplete: 'off', attrs: { maxlength: '80', placeholder: 'username' } });
  const memberSearch = ecCreateEl('input', { id: 'ecGroupSettingsMemberSearch', className: 'modalInput ecGroupSettingsMemberSearch', type: 'search', autocomplete: 'off', attrs: { maxlength: '80', placeholder: 'Filter members…' } });
  const rolePill = ecCreateEl('span', { id: 'ecGroupSettingsRole', className: 'ecGroupSettingsRole', text: 'Member' });
  const permissionHint = ecCreateEl('div', { id: 'ecGroupSettingsPermissionHint', className: 'ecGroupSettingsHint', text: '' });

  const body = ecCreateEl('div', { className: 'modalBody ecGroupSettingsBody' }, [
    ecCreateEl('div', { className: 'ecGroupSettingsHero' }, [
      ecCreateEl('div', {}, [
        ecCreateEl('div', { className: 'ecGroupSettingsLabel', text: 'Current role' }),
        rolePill,
      ]),
      ecCreateEl('div', { id: 'ecGroupSettingsGroupId', className: 'ecGroupSettingsId', text: '#0' }),
    ]),
    ecCreateEl('div', { id: 'ecGroupSettingsStats', className: 'ecGroupSettingsStats', attrs: { 'aria-label': 'Group status summary' } }, [
      ecCreateEl('span', { id: 'ecGroupSettingsMemberCount', className: 'ecGroupSettingsStatPill', text: '0 members' }),
      ecCreateEl('span', { id: 'ecGroupSettingsOnlineCount', className: 'ecGroupSettingsStatPill', text: '0 online' }),
      ecCreateEl('span', { id: 'ecGroupSettingsVoiceCount', className: 'ecGroupSettingsStatPill', text: '0 in voice' }),
    ]),
    ecCreateEl('div', { className: 'ecGroupSettingsPanel' }, [
      ecCreateEl('div', { className: 'ecGroupSettingsPanelHead' }, [
        ecCreateEl('div', { className: 'ecGroupSettingsPanelTitle', text: 'Details' }),
        ecCreateEl('div', { id: 'ecGroupSettingsDirty', className: 'ecGroupSettingsDirty', text: 'Saved' }),
      ]),
      ecCreateEl('div', { className: 'ecGroupSettingsGrid' }, [
        ecCreateEl('div', { className: 'ecGroupSettingsLabelRow' }, [
          ecCreateEl('label', { className: 'fieldLabel', attrs: { for: 'ecGroupSettingsName' }, text: 'Group name' }),
          ecCreateEl('span', { id: 'ecGroupSettingsNameCount', className: 'ecGroupSettingsCounter', text: '0 / 64' }),
        ]),
        nameInput,
        ecCreateEl('div', { className: 'ecGroupSettingsLabelRow' }, [
          ecCreateEl('label', { className: 'fieldLabel', attrs: { for: 'ecGroupSettingsDescription' }, text: 'Description' }),
          ecCreateEl('span', { id: 'ecGroupSettingsDescriptionCount', className: 'ecGroupSettingsCounter', text: '0 / 512' }),
        ]),
        descInput,
        permissionHint,
      ]),
    ]),
    ecCreateEl('div', { className: 'ecGroupSettingsPanel' }, [
      ecCreateEl('div', { className: 'ecGroupSettingsPanelHead' }, [
        ecCreateEl('div', { className: 'ecGroupSettingsPanelTitle', text: 'Invite' }),
        ecCreateEl('div', { className: 'ecGroupSettingsHint', text: 'Same as /invite username' }),
      ]),
      ecCreateEl('div', { className: 'ecGroupSettingsInviteRow' }, [
        inviteInput,
        ecCreateEl('button', { id: 'ecGroupSettingsInviteSend', className: 'primaryBtn', type: 'button', text: 'Send invite' }),
      ]),
    ]),
    ecCreateEl('div', { className: 'ecGroupSettingsPanel' }, [
      ecCreateEl('div', { className: 'ecGroupSettingsPanelHead' }, [
        ecCreateEl('div', { className: 'ecGroupSettingsPanelTitle', text: 'Members' }),
        ecCreateEl('button', { id: 'ecGroupSettingsRefresh', className: 'ghostBtn smallBtn', type: 'button', text: '↻ Refresh' }),
      ]),
      memberSearch,
      ecCreateEl('div', { id: 'ecGroupSettingsMembersSummary', className: 'ecGroupSettingsHint', text: 'Loading members…' }),
      ecCreateEl('ul', { id: 'ecGroupSettingsMembersList', className: 'ecGroupSettingsMembersList', attrs: { 'aria-label': 'Group members' } }),
    ]),
    ecCreateEl('div', { id: 'ecGroupSettingsMutedPanel', className: 'ecGroupSettingsPanel hidden' }, [
      ecCreateEl('div', { className: 'ecGroupSettingsPanelHead' }, [
        ecCreateEl('div', { className: 'ecGroupSettingsPanelTitle', text: 'Muted members' }),
        ecCreateEl('button', { id: 'ecGroupSettingsMutedRefresh', className: 'ghostBtn smallBtn', type: 'button', text: '↻ Refresh' }),
      ]),
      ecCreateEl('div', { id: 'ecGroupSettingsMutedSummary', className: 'ecGroupSettingsHint', text: 'Loading mute list…' }),
      ecCreateEl('ul', { id: 'ecGroupSettingsMutedList', className: 'ecGroupSettingsMembersList', attrs: { 'aria-label': 'Muted group members' } }),
    ]),
    ecCreateEl('div', { className: 'ecGroupSettingsActions', attrs: { 'aria-label': 'Group quick actions' } }, [
      ecCreateEl('button', { id: 'ecGroupSettingsInvite', className: 'ghostBtn', type: 'button', text: '➕ Invite user' }),
      ecCreateEl('button', { id: 'ecGroupSettingsVoice', className: 'ghostBtn', type: 'button', text: '🎤 Toggle voice' }),
      ecCreateEl('button', { id: 'ecGroupSettingsLeave', className: 'ghostBtn dangerText', type: 'button', text: 'Leave group' }),
      ecCreateEl('button', { id: 'ecGroupSettingsDelete', className: 'ghostBtn dangerText', type: 'button', text: 'Delete group' }),
    ]),
    ecCreateEl('div', { className: 'ecGroupSettingsCommandHint' }, [
      ecCreateEl('span', { text: 'Text commands still work: ' }),
      ecCreateEl('button', { className: 'ecGroupCommandChip', type: 'button', text: '/invite', attrs: { 'data-command': 'invite' } }),
      ecCreateEl('button', { className: 'ecGroupCommandChip', type: 'button', text: '/voice', attrs: { 'data-command': 'voice' } }),
      ecCreateEl('button', { className: 'ecGroupCommandChip', type: 'button', text: '/users', attrs: { 'data-command': 'users' } }),
      ecCreateEl('button', { className: 'ecGroupCommandChip', type: 'button', text: '/rename', attrs: { 'data-command': 'rename' } }),
      ecCreateEl('button', { className: 'ecGroupCommandChip', type: 'button', text: '/desc', attrs: { 'data-command': 'desc' } }),
    ]),
  ]);
  card.appendChild(body);
  card.appendChild(ecCreateEl('div', { className: 'modalFoot confirmModalFoot ecGroupSettingsFoot' }, [
    ecCreateEl('button', { id: 'ecGroupSettingsCancel', className: 'ghostBtn', type: 'button', text: 'Cancel' }),
    ecCreateEl('button', { id: 'ecGroupSettingsSave', className: 'primaryBtn', type: 'button', text: 'Save changes' }),
  ]));

  modal.appendChild(card);
  modal.addEventListener('mousedown', (ev) => {
    if (ev.target === modal) closeGroupSettingsModal();
  });
  closeBtn.addEventListener('click', closeGroupSettingsModal);
  card.querySelector('#ecGroupSettingsCancel')?.addEventListener('click', closeGroupSettingsModal);
  card.querySelector('#ecGroupSettingsSave')?.addEventListener('click', async () => {
    const active = EC_GROUP_SETTINGS_ACTIVE;
    if (!active?.groupId) return;
    const saveBtn = card.querySelector('#ecGroupSettingsSave');
    try {
      if (saveBtn) saveBtn.disabled = true;
      const res = await groupUpdateMetadata(active.groupId, nameInput.value, descInput.value);
      if (res?.success) {
        active.originalName = String(nameInput.value || '').trim();
        active.originalDescription = String(descInput.value || '').trim();
        updateGroupSettingsSaveState();
        closeGroupSettingsModal();
      }
      else toast(`❌ Save failed: ${res?.error || 'Invalid group settings'}`, 'error');
    } catch (e) {
      toast(`❌ Save failed: ${groupDisplayError(e)}`, 'error');
    } finally {
      if (saveBtn) saveBtn.disabled = false;
    }
  });
  card.querySelector('#ecGroupSettingsInvite')?.addEventListener('click', async () => {
    const active = EC_GROUP_SETTINGS_ACTIVE;
    if (!active?.groupId) return;
    const input = card.querySelector('#ecGroupSettingsInviteInput');
    if (input) {
      input.focus();
      return;
    }
    await inviteToGroupFromWindow(active.groupId, active.title || '');
  });
  const sendInlineInvite = async () => {
    const active = EC_GROUP_SETTINGS_ACTIVE;
    const input = card.querySelector('#ecGroupSettingsInviteInput');
    if (!active?.groupId || !input) return;
    const target = String(input.value || '').trim();
    if (!target) {
      input.focus();
      toast('Type a username to invite.', 'warn');
      return;
    }
    const btn = card.querySelector('#ecGroupSettingsInviteSend');
    try {
      if (btn) btn.disabled = true;
      const res = await groupInviteUsername(active.groupId, target);
      if (res?.success) input.value = '';
    } finally {
      if (btn) btn.disabled = false;
    }
  };
  card.querySelector('#ecGroupSettingsInviteSend')?.addEventListener('click', sendInlineInvite);
  card.querySelector('#ecGroupSettingsInviteInput')?.addEventListener('keydown', (ev) => {
    if (ev.key !== 'Enter') return;
    ev.preventDefault();
    sendInlineInvite();
  });
  nameInput.addEventListener('input', updateGroupSettingsSaveState);
  descInput.addEventListener('input', updateGroupSettingsSaveState);
  memberSearch.addEventListener('input', () => renderGroupSettingsMembers(EC_GROUP_SETTINGS_ACTIVE?.groupId));
  card.querySelectorAll('.ecGroupCommandChip').forEach((btn) => {
    btn.addEventListener('click', () => runGroupSettingsCommandChip(btn.dataset.command));
  });
  card.querySelector('#ecGroupSettingsVoice')?.addEventListener('click', async () => {
    const active = EC_GROUP_SETTINGS_ACTIVE;
    if (!active?.groupId) return;
    const win = UIState.windows.get('group:' + String(active.groupId));
    await toggleGroupVoice(active.groupId, win);
    updateGroupSettingsVoiceButton(active.groupId);
  });
  card.querySelector('#ecGroupSettingsRefresh')?.addEventListener('click', async () => {
    const active = EC_GROUP_SETTINGS_ACTIVE;
    if (!active?.groupId) return;
    const win = UIState.windows.get('group:' + String(active.groupId));
    await refreshGroupMemberRoster(active.groupId, win, { toast: true });
    await groupRefreshMutes(active.groupId, { silent: true });
    renderGroupSettingsMembers(active.groupId);
    renderGroupSettingsMutes(active.groupId);
  });
  card.querySelector('#ecGroupSettingsMutedRefresh')?.addEventListener('click', async () => {
    const active = EC_GROUP_SETTINGS_ACTIVE;
    if (!active?.groupId) return;
    await groupRefreshMutes(active.groupId, { silent: false });
    renderGroupSettingsMembers(active.groupId);
    renderGroupSettingsMutes(active.groupId);
  });
  card.querySelector('#ecGroupSettingsLeave')?.addEventListener('click', async () => {
    const active = EC_GROUP_SETTINGS_ACTIVE;
    if (!active?.groupId) return;
    closeGroupSettingsModal();
    await groupLeaveFromSettings(active.groupId, active.title || '');
  });
  card.querySelector('#ecGroupSettingsDelete')?.addEventListener('click', async () => {
    const active = EC_GROUP_SETTINGS_ACTIVE;
    if (!active?.groupId) return;
    closeGroupSettingsModal();
    await groupDeleteFromSettings(active.groupId, active.title || '');
  });

  document.addEventListener('keydown', (ev) => {
    if (!EC_GROUP_SETTINGS_ACTIVE || !EC_GROUP_SETTINGS_MODAL || EC_GROUP_SETTINGS_MODAL.classList.contains('hidden')) return;
    if (ev.key === 'Escape') {
      ev.preventDefault();
      closeGroupSettingsModal();
    }
  });

  (document.body || document.documentElement).appendChild(modal);
  EC_GROUP_SETTINGS_MODAL = modal;
  return modal;
}

function updateGroupSettingsVoiceButton(groupId) {
  const modal = EC_GROUP_SETTINGS_MODAL;
  if (!modal || modal.classList.contains('hidden')) return;
  const btn = modal.querySelector('#ecGroupSettingsVoice');
  if (!btn) return;
  const active = groupVoiceIsActive(groupId);
  btn.textContent = active ? '📞 Leave voice' : '🎤 Start voice';
  btn.classList.toggle('active', active);
  btn.disabled = !VOICE_ENABLED;
  if (!VOICE_ENABLED) btn.textContent = '🎤 Voice disabled';
}

async function openGroupSettings(groupId, title = '') {
  const gid = Number(groupId || 0);
  if (!gid) return;
  const modal = ensureGroupSettingsModal();
  const meta = groupMetaFromCache(gid, title);
  const role = currentGroupRole(gid);
  const roleLabel = groupMemberRoleLabel(role);
  const canEditMeta = groupRoleRank(role) >= groupRoleRank('admin');
  const isOwner = role === 'owner';

  const titleEl = modal.querySelector('#ecGroupSettingsTitle');
  const subTitleEl = modal.querySelector('#ecGroupSettingsSubTitle');
  const idEl = modal.querySelector('#ecGroupSettingsGroupId');
  const roleEl = modal.querySelector('#ecGroupSettingsRole');
  const nameInput = modal.querySelector('#ecGroupSettingsName');
  const descInput = modal.querySelector('#ecGroupSettingsDescription');
  const hint = modal.querySelector('#ecGroupSettingsPermissionHint');
  const saveBtn = modal.querySelector('#ecGroupSettingsSave');
  const inviteBtn = modal.querySelector('#ecGroupSettingsInvite');
  const inviteSendBtn = modal.querySelector('#ecGroupSettingsInviteSend');
  const inviteInput = modal.querySelector('#ecGroupSettingsInviteInput');
  const memberSearch = modal.querySelector('#ecGroupSettingsMemberSearch');
  const deleteBtn = modal.querySelector('#ecGroupSettingsDelete');

  if (titleEl) titleEl.textContent = 'Group settings';
  if (subTitleEl) subTitleEl.textContent = `${meta.group_name} · ${roleLabel}`;
  if (idEl) idEl.textContent = `#${gid}`;
  if (roleEl) roleEl.textContent = roleLabel;
  if (nameInput) {
    nameInput.value = meta.group_name;
    nameInput.disabled = !canEditMeta;
  }
  if (descInput) {
    descInput.value = meta.group_description;
    descInput.disabled = !canEditMeta;
  }
  if (hint) {
    hint.textContent = canEditMeta
      ? 'Admins and the owner can update the group name and description.'
      : 'Only group admins and the owner can update the group name and description. You can still use invite, voice, refresh, or leave if allowed.';
  }
  const canInvite = groupRoleRank(role) >= groupRoleRank('moderator');
  if (inviteBtn) inviteBtn.disabled = !canInvite;
  if (inviteSendBtn) inviteSendBtn.disabled = !canInvite;
  if (inviteInput) {
    inviteInput.value = '';
    inviteInput.disabled = !canInvite;
    inviteInput.placeholder = canInvite ? 'username' : 'Moderators, admins, and owners can invite';
  }
  if (memberSearch) memberSearch.value = '';
  if (deleteBtn) deleteBtn.classList.toggle('hidden', !isOwner);
  updateGroupSettingsVoiceButton(gid);

  EC_GROUP_SETTINGS_ACTIVE = {
    groupId: gid,
    title: title || meta.group_name,
    originalName: meta.group_name,
    originalDescription: meta.group_description,
    canEditMeta,
    canInvite,
    restoreFocus: document.activeElement instanceof HTMLElement ? document.activeElement : null,
  };
  updateGroupSettingsSaveState();
  renderGroupSettingsMembers(gid);
  renderGroupSettingsMutes(gid);
  if (groupRoleRank(role) >= groupRoleRank('moderator')) {
    groupRefreshMutes(gid, { silent: true }).then(() => {
      renderGroupSettingsMembers(gid);
      renderGroupSettingsMutes(gid);
    }).catch(() => {});
  }
  modal.classList.remove('hidden');
  window.setTimeout(() => {
    try {
      if (canEditMeta) nameInput?.focus?.();
      else modal.querySelector('#ecGroupSettingsInvite:not(:disabled), #ecGroupSettingsVoice:not(:disabled), #ecGroupSettingsCancel')?.focus?.();
    } catch {}
  }, 0);
}

async function groupInviteUsername(groupId, username) {
  const gid = Number(groupId || 0);
  const targetUser = String(username || '').trim().replace(/^@/, '');
  if (!gid || !targetUser) return { success: false, error: 'Usage: /invite <username>' };
  try {
    const res = await apiJson(`/api/groups/${encodeURIComponent(gid)}/invite`, {
      method: 'POST',
      body: JSON.stringify({ to_user: targetUser }),
    });
    if (res?.status === 'already_member') {
      toast(`ℹ️ ${targetUser} is already in this group`, 'info');
    } else {
      toast(`✅ Invite sent to ${targetUser}`, 'ok');
    }
    return { success: true, command: 'invite' };
  } catch (e) {
    const msg = groupDisplayError(e);
    toast(`❌ Invite failed: ${msg}`, 'error');
    return { success: false, command: 'invite', error: msg };
  }
}

async function runGroupTextCommand(groupId, plaintext, ctx = {}) {
  const gid = Number(groupId || 0);
  const raw = (typeof plaintext === 'string') ? plaintext : String(plaintext ?? '');
  const t = raw.trim();
  if (!gid || !t.startsWith('/')) return { handled: false };
  const lower = t.toLowerCase();
  const win = ctx?.win || UIState.windows.get('group:' + String(gid));
  const title = ctx?.title || win?.dataset?.windowTitle || '';
  const meta = groupMetaFromCache(gid, title);

  if (/^\/invite(\s|$)/i.test(t)) {
    const rest = t.replace(/^\/invite\s*/i, '').trim();
    const u = ((rest.split(/\s+/)[0] || '').trim()).replace(/^@/, '');
    if (!u) return { handled: true, success: false, command: 'invite', error: 'Usage: /invite <username>' };
    const res = await groupInviteUsername(gid, u);
    return { handled: true, ...res };
  }
  if (lower === '/settings' || lower === '/group settings') {
    await openGroupSettings(gid, title);
    return { handled: true, success: true, command: 'settings' };
  }
  if (lower === '/voice') {
    await toggleGroupVoice(gid, win);
    return { handled: true, success: true, command: 'voice' };
  }
  if (lower === '/users' || lower === '/members') {
    await refreshGroupMemberRoster(gid, win, { toast: true });
    return { handled: true, success: true, command: 'members' };
  }
  if (lower === '/leave') {
    await groupLeaveFromSettings(gid, meta.group_name);
    return { handled: true, success: true, command: 'leave' };
  }
  if (/^\/rename\s+/i.test(t)) {
    if (groupRoleRank(currentGroupRole(gid)) < groupRoleRank('admin')) {
      return { handled: true, success: false, command: 'rename', error: 'Only group admins and the owner can rename this group.' };
    }
    const name = t.replace(/^\/rename\s+/i, '').trim();
    const res = await groupUpdateMetadata(gid, name, meta.group_description);
    return { handled: true, command: 'rename', success: !!res?.success, error: res?.error };
  }
  if (/^\/(desc|description)\s+/i.test(t)) {
    if (groupRoleRank(currentGroupRole(gid)) < groupRoleRank('admin')) {
      return { handled: true, success: false, command: 'description', error: 'Only group admins and the owner can edit the description.' };
    }
    const desc = t.replace(/^\/(desc|description)\s+/i, '').trim();
    const res = await groupUpdateMetadata(gid, meta.group_name, desc);
    return { handled: true, command: 'description', success: !!res?.success, error: res?.error };
  }
  if (lower === '/grouphelp' || lower === '/help group') {
    toast('Group commands: /invite username, /settings, /voice, /users, /leave, /rename name, /desc description', 'info', 6500);
    return { handled: true, success: true, command: 'help' };
  }
  return { handled: false };
}

function renderGroupMemberRoster(win, groupId, opts = {}) {
  if (!win?._ym?.groupMembersList) return;
  const gid = Number(groupId || 0);
  const ul = win._ym.groupMembersList;
  const countEl = win._ym.groupMembersCount;
  ecClearNode(ul);

  const details = normalizeGroupMemberDetails(UIState.groupMemberDetails?.get?.(gid), UIState.groupMembers?.get?.(gid));
  if (countEl) countEl.textContent = String(details.length || 0);
  win.dataset.groupMemberCount = String(details.length || 0);
  try {
    const usersBtn = win.querySelector('.ym-mobileWindowUsersBtn');
    if (usersBtn) {
      usersBtn.textContent = details.length ? `Users (${details.length})` : 'Users';
      usersBtn.setAttribute('aria-label', details.length ? `Show ${details.length} group users` : 'Show group users');
    }
  } catch {}

  if (!details.length) {
    const text = opts.loading ? 'Loading group users…' : 'No group users found';
    ul.appendChild(ecRoomSidebarEmptyRow(text, { muted: true }));
    return;
  }

  details.forEach((member) => {
    const username = String(member.username || '').trim();
    if (!username) return;
    const roleLabel = groupMemberRoleLabel(member.role);
    const presence = groupMemberPresence(username);
    const voiceActive = groupVoiceUserIsActive(gid, username);
    const mutedInGroup = groupMemberIsMuted(gid, username);
    const isSelf = String(username).toLowerCase() === String(currentUser || '').toLowerCase();

    const li = document.createElement('li');
    li.className = 'ym-groupMemberItem';
    li.dataset.name = username;
    li.dataset.search = `${username} ${roleLabel} ${presence.label} group member`;

    const left = document.createElement('div');
    left.className = 'liLeft';
    try {
      createDockIdentity(left, {
        name: username,
        presenceClass: presence.className,
        meta: `${roleLabel} · ${presence.label}${voiceActive ? ' · Voice' : ''}`,
        chip: isSelf ? 'You' : (voiceActive ? 'Voice' : (roleLabel !== 'Member' ? roleLabel : '')),
        avatarUrl: UIState.presence?.get?.(username)?.avatar_url || '',
      });
    } catch {
      left.appendChild(ecRoomSidebarLeft(presence.className, username, { descText: ` · ${roleLabel}${voiceActive ? ' · Voice' : ''}` }));
    }

    const actions = document.createElement('div');
    actions.className = 'liActions';
    const pmBtn = document.createElement('button');
    pmBtn.className = 'iconBtn';
    pmBtn.textContent = '💬';
    pmBtn.title = isSelf ? 'This is you' : `Private message ${username}`;
    pmBtn.disabled = isSelf;
    pmBtn.onclick = (ev) => {
      ev.stopPropagation();
      if (!isSelf) openPrivateChat(username);
    };
    actions.appendChild(pmBtn);

    li.appendChild(left);
    li.appendChild(actions);
    li.onclick = () => selectBuddyRow(username, 'group', li);
    li.ondblclick = () => { if (!isSelf) openPrivateChat(username); };
    li.oncontextmenu = (ev) => {
      selectBuddyRow(username, 'group', li);
      showUserContextMenu(ev, username, { source: 'group', group_id: gid });
    };

    ul.appendChild(li);
  });
}

function refreshGroupMemberRoster(groupId, win = null, opts = {}) {
  const gid = Number(groupId || 0);
  const targetWin = win || UIState.windows.get('group:' + String(gid));
  if (!gid) return Promise.resolve([]);
  if (targetWin) renderGroupMemberRoster(targetWin, gid, { loading: true });
  return new Promise((resolve) => {
    socket.emit('get_group_members', { group_id: gid }, (res) => {
      if (res?.success) {
        const details = rememberGroupMembersFromResponse(gid, res);
        if (targetWin) renderGroupMemberRoster(targetWin, gid);
        if (EC_GROUP_SETTINGS_ACTIVE?.groupId === gid) renderGroupSettingsMembers(gid);
        if (opts.toast) toast(`👥 Refreshed ${details.length} group user${details.length === 1 ? '' : 's'}`, 'ok');
        resolve(details);
        return;
      }
      if (targetWin) renderGroupMemberRoster(targetWin, gid);
      if (opts.toast) toast(`❌ Could not refresh group users`, 'error');
      resolve([]);
    });
  });
}

function wireGroupMemberRoster(win, groupId) {
  if (!win?._ym) return;
  const gid = Number(groupId || 0);
  win.dataset.groupId = String(gid || '');
  if (win._ym.groupMembersRefreshBtn) {
    win._ym.groupMembersRefreshBtn.onclick = (ev) => {
      ev.preventDefault();
      refreshGroupMemberRoster(gid, win, { toast: true });
    };
  }
  if (win._ym.groupMembersCloseBtn) {
    win._ym.groupMembersCloseBtn.onclick = (ev) => {
      ev.preventDefault();
      win.classList.remove('is-mobile-group-members-open');
      const usersBtn = win.querySelector('.ym-mobileWindowUsersBtn');
      if (usersBtn) usersBtn.setAttribute('aria-expanded', 'false');
      const usersPanel = win.querySelector('.ym-groupMembersPanel');
      if (usersPanel) usersPanel.setAttribute('aria-hidden', 'true');
    };
  }
  renderGroupMemberRoster(win, gid, { loading: true });
  registerWindowCleanup(win, () => {
    if (win._groupMemberRefreshTimer) {
      clearInterval(win._groupMemberRefreshTimer);
      win._groupMemberRefreshTimer = null;
    }
  });
  if (!win._groupMemberRefreshTimer) {
    win._groupMemberRefreshTimer = setInterval(() => {
      if (!document.body?.contains(win) || win.classList.contains('hidden')) return;
      refreshGroupMemberRoster(gid, win).catch(() => {});
    }, 60000);
  }
}


function groupVoiceRoomName(groupId) {
  const gid = Number(groupId || 0);
  return gid ? `group_${gid}` : '';
}

function groupVoiceRoomIdFromName(room) {
  const m = String(room || '').match(/^group_(\d+)$/);
  return m ? Number(m[1] || 0) : 0;
}

function groupVoiceIsActive(groupId) {
  const room = groupVoiceRoomName(groupId);
  return !!(room && VOICE_STATE?.room?.joined && VOICE_STATE?.room?.name === room);
}

function updateGroupVoiceButton(groupId, win = null) {
  const gid = Number(groupId || 0);
  const targetWin = win || UIState.windows.get('group:' + String(gid));
  if (!targetWin?._ym?.groupVoiceBtn) return;
  const btn = targetWin._ym.groupVoiceBtn;
  const hint = targetWin._ym.groupVoiceHint;
  const active = groupVoiceIsActive(gid);
  btn.disabled = !VOICE_ENABLED;
  btn.classList.toggle('active', active);
  if (!VOICE_ENABLED) {
    btn.textContent = '🎤 Voice';
    btn.title = 'Voice is disabled on this server';
    if (hint) hint.textContent = 'Voice off';
    return;
  }
  if (!active) {
    btn.textContent = '🎤 Voice';
    btn.title = 'Enable voice for this group';
    if (hint) hint.textContent = 'Voice';
    return;
  }
  if (VOICE_STATE?.micMuted) {
    btn.textContent = '🔇 Muted';
    btn.title = 'Group voice is on but muted — click to leave, right-click to unmute';
    if (hint) hint.textContent = 'Muted';
  } else {
    btn.textContent = '📞 Voice on';
    btn.title = 'Group voice is on — click to leave, right-click to mute';
    if (hint) hint.textContent = 'Voice on';
  }
}

function updateAllGroupVoiceButtons() {
  try {
    UIState.windows.forEach((win) => {
      if (!win || win.dataset.kind !== 'group') return;
      const gid = Number(win.dataset.groupId || String(win.dataset.winId || '').replace(/^group:/, '') || 0);
      if (gid) updateGroupVoiceButton(gid, win);
    });
  } catch {}
}

async function inviteToGroupFromWindow(groupId, groupTitle = '') {
  const gid = Number(groupId || 0);
  if (!gid) return;
  const u = await ecPrompt('Invite which username?', '', {
    title: 'Invite user to group',
    inputLabel: 'Username',
    confirmLabel: 'Send invite',
    maxLength: 80,
    placeholder: 'username',
  });
  const targetUser = String(u || '').trim();
  if (!targetUser) return;
  await groupInviteUsername(gid, targetUser);
}

async function toggleGroupVoice(groupId, win = null) {
  const gid = Number(groupId || 0);
  const room = groupVoiceRoomName(gid);
  if (!gid || !room) return;
  try {
    if (!VOICE_ENABLED) return toast('🎤 Voice is disabled on this server', 'warn');
    if (groupVoiceIsActive(gid)) {
      VOICE_STATE.room.wantRoomVoice = false;
      voiceLeaveRoom('Group voice disabled', true);
      updateAllGroupVoiceButtons();
      return;
    }
    // Group voice is intentionally voice-only.  Do not route this through the
    // room webcam/media toggle, because that can carry an active room camera
    // into the group.  The underlying WebRTC voice mesh is the same one the
    // room voice button uses.
    VOICE_STATE.room.wantRoomVoice = true;
    voiceSetMute(false);
    const res = await voiceJoinRoom(room, { silent: true, audio: true });
    if (!res?.success) {
      if (res?.error_code === 'voice_room_full') voiceShowRoomFull(room, res);
      else toast(`❌ ${res?.error || 'Group voice join failed'}`, 'error');
    } else {
      toast('🎤 Group voice connected', 'ok', 1800);
    }
    updateGroupVoiceButton(gid, win);
  } catch (e) {
    console.error(e);
    toast(`❌ Group voice error: ${e?.message || e}`, 'error');
  } finally {
    updateAllGroupVoiceButtons();
  }
}

function wireGroupWindowActions(win, groupId, title = '') {
  const gid = Number(groupId || 0);
  if (!win?._ym || !gid) return;
  if (win._ym.groupInviteBtn) {
    win._ym.groupInviteBtn.onclick = (ev) => {
      ev.preventDefault();
      inviteToGroupFromWindow(gid, title);
    };
  }
  if (win._ym.groupSettingsBtn) {
    win._ym.groupSettingsBtn.onclick = async (ev) => {
      ev.preventDefault();
      await openGroupSettings(gid, title || win?.dataset?.windowTitle || '');
    };
  }
  if (win._ym.groupVoiceBtn) {
    win._ym.groupVoiceBtn.onclick = async (ev) => {
      ev.preventDefault();
      await toggleGroupVoice(gid, win);
    };
    win._ym.groupVoiceBtn.oncontextmenu = (ev) => {
      ev.preventDefault();
      if (!groupVoiceIsActive(gid)) return false;
      const muted = !VOICE_STATE.micMuted;
      voiceSetMute(muted);
      updateAllGroupVoiceButtons();
      toast(muted ? '🔇 Mic muted' : '🎤 Mic unmuted', 'info');
      return false;
    };
  }
  updateGroupVoiceButton(gid, win);
}

function openGroupWindow(groupId, title) {
  const id = "group:" + groupId;
  const existing = UIState.windows.get(id);
  if (existing) {
    existing.classList.remove("hidden");
    if (String(title || '').trim()) ecSetGroupWindowTitle(existing, groupId, title);
    bringToFront(existing);
    refreshGroupMemberRoster(groupId, existing).catch(() => {});
    wireGroupWindowActions(existing, groupId, title);
    return existing;
  }
  const win = createWindow({ id, title: `Group — ${title} (#${groupId})`, kind: "group" });
  if (!win) return;
  ecSetGroupWindowTitle(win, groupId, title);
  wireGroupMemberRoster(win, groupId);
  wireGroupWindowActions(win, groupId, title);

  // Group: add history toolbar + paging state
  ensureGroupHistoryToolbar(win, groupId);
  const _gst = groupHistState(win);
  _gst.loading = false;
  _gst.done = false;
  updateGroupOlderUI(win);

  try { voiceWireWindowTalkControls(win); } catch (e) {}

  // Join Socket.IO room for group chat, with reconnect-aware ACK handling.
  ecJoinGroupChatAck(groupId).then((res) => {
    if (res?.success) {
      win._groupChatJoined = true;
      if (res?.group_name) ecSetGroupWindowTitle(win, groupId, res.group_name);
      rememberGroupMembersFromResponse(groupId, res);
      renderGroupMemberRoster(win, groupId);

      // Render history (ciphertext-only safe). If history exists, replace the
      // default "Window opened" line to avoid clutter.
      const hist = Array.isArray(res.history) ? res.history : [];
      if (win._ym?.log && hist.length) {
        resetChatLogState(win._ym.log);
        (async () => {
          await appendGroupHistory(win, hist);
          const st = groupHistState(win);
          st.done = false;
          updateOldestId(win, hist);
          if (hist.length < GROUP_HISTORY_PAGE_SIZE) st.done = true;
          updateGroupOlderUI(win);
          appendLine(win, "System:", "Joined group chat.", { ts: res?.joined_at || Date.now() });
        })();
      } else {
        const st = groupHistState(win);
        st.oldestId = null;
        st.done = true;
        updateGroupOlderUI(win);
        appendLine(win, "System:", "Joined group chat.", { ts: res?.joined_at || Date.now() });
      }
      return;
    }
    const reason = res?.error || 'Could not join group chat';
    appendLine(win, 'System:', `Could not join group chat: ${reason}`, { ts: Date.now() });
    toast(`❌ ${reason}`, 'error');
  }).catch((e) => {
    const reason = e?.message || 'Could not join group chat';
    appendLine(win, 'System:', `Could not join group chat: ${reason}`, { ts: Date.now() });
    toast(`❌ ${reason}`, 'error');
  });

  win._ym.send.onclick = () => {
    const msg = win._ym.input.value.trim();
    if (!msg) return;

    sendGroupTo(groupId, msg, { win, title: title || win?.dataset?.windowTitle || '' }).then((res) => {
      if (res?.success) {
        win._ym.input.value = "";
      } else {
        toast(`❌ ${res?.error || "Group send failed"}`, "error");
      }
    }).catch((e) => {
      console.error(e);
      toast(`❌ Group send failed: ${e?.message || e}`, "error");
    });
  };

  // Group GIF button (send without polluting the input field)
  if (win._ym?.gifBtn) {
    win._ym.gifBtn.onclick = () => {
      openGifPicker((url) => {
        const clean = _gifFallbackUrl(url) || url;
          const msg = `gif:${clean}`;
        sendGroupTo(groupId, msg).then((res) => {
          if (res?.success) {
          } else {
            toast(`❌ ${res?.error || "Group GIF send failed"}`, "error");
          }
        }).catch((e) => {
          console.error(e);
          toast(`❌ Group GIF send failed: ${e?.message || e}`, "error");
        });
      });
    };
  }

  // Group file button (E2EE + server ciphertext storage)
  if (win._ym?.fileBtn && win._ym?.fileInput) {
    win._ym.fileBtn.onclick = () => win._ym.fileInput.click();
    win._ym.fileInput.onchange = async () => {
      try {
        const f = win._ym.fileInput.files?.[0];
        win._ym.fileInput.value = "";
        if (!f) return;

        const payload = await sendGroupFileTo(groupId, f, { win });
        if (payload) {
          appendDmPayload(win, "You:", payload, { peer: `group:${groupId}`, direction: "out" });
        }
      } catch (e) {
        console.error(e);
        toast(`❌ Group file send failed: ${e?.message || e}`, "error");
      }
    };
  }

  bringToFront(win);
  return win;
}

function forceLeaveGroupUI(groupId, why = "removed") {
  const gid = String(groupId || "").trim();
  if (!gid) return;
  try { UIState.groupMembers.delete(Number(gid)); } catch {}
  try { UIState.groupMemberDetails.delete(Number(gid)); } catch {}
  try {
    const id = "group:" + gid;
    if (UIState.windows.has(id)) closeWindow(id);
  } catch {}
  try { refreshMyGroups(); } catch {}
  const reason = String(why || "removed").toLowerCase();
  if (reason === "kicked") toast(`👢 Removed from group #${gid}`, "warn", 4200);
  else if (reason === "deleted") toast(`🗑️ Group #${gid} was deleted`, "warn", 4200);
  else if (reason === "left") toast(`👋 Left group #${gid}`, "info", 3200);
}

socket.on("group_forced_leave", (payload = {}) => {
  try {
    const groupId = payload?.group_id;
    if (!groupId) return;
    forceLeaveGroupUI(groupId, payload?.reason || "removed");
  } catch (e) {
    console.warn("group_forced_leave handler failed", e);
  }
});

function applyGroupMetadataUpdateFromEvent(groupId, payload = {}) {
  const gid = Number(groupId || 0);
  if (!gid) return;
  const nextName = String(payload?.name || '').trim();
  if (!nextName) return;
  try {
    const idx = Array.isArray(UIState.myGroups) ? UIState.myGroups.findIndex((g) => Number(g?.id || 0) === gid) : -1;
    if (idx >= 0) UIState.myGroups[idx] = { ...UIState.myGroups[idx], group_name: nextName };
  } catch {}
  const win = UIState.windows.get('group:' + String(gid));
  if (win) ecSetGroupWindowTitle(win, gid, nextName);
  if (EC_GROUP_SETTINGS_ACTIVE?.groupId === gid) {
    try {
      const modal = EC_GROUP_SETTINGS_MODAL;
      const subtitle = modal?.querySelector?.('#ecGroupSettingsSubTitle');
      if (subtitle) subtitle.textContent = `${nextName} · ${groupMemberRoleLabel(currentGroupRole(gid))}`;
      EC_GROUP_SETTINGS_ACTIVE.title = nextName;
      EC_GROUP_SETTINGS_ACTIVE.originalName = nextName;
    } catch {}
  }
}

socket.on("group_members_changed", (payload = {}) => {
  try {
    const groupId = Number(payload?.group_id || 0);
    if (!groupId) return;
    if (String(payload?.reason || '') === 'metadata_updated') {
      applyGroupMetadataUpdateFromEvent(groupId, payload);
    }
    const win = UIState.windows.get("group:" + String(groupId));
    if (win) refreshGroupMemberRoster(groupId, win).catch(() => {});
    try { refreshMyGroups(); } catch {}
  } catch (e) {
    console.warn("group_members_changed handler failed", e);
  }
});

socket.on("group_message", async (payload) => {
  if (!payload) return;
  const group_id = payload.group_id;
  const sender = payload.sender;
  const win = UIState.windows.get("group:" + String(group_id));
  if (!win) return;
  if (hasSeenGroupMessageId(win, payload?.message_id)) return;
  rememberGroupMessageId(win, payload?.message_id);
  markVisibleGroupMessageRead(group_id, payload?.message_id);

  let msgForUi = payload.message;

  const cipher = payload.cipher || payload.message;
  if (cipher && typeof cipher === "string" && cipher.startsWith(GROUP_ENVELOPE_PREFIX)) {
    if (HAS_WEBCRYPTO && window.myPrivateCryptoKey) {
      try {
        msgForUi = await decryptGroupEnvelope(window.myPrivateCryptoKey, cipher);
      } catch (e) {
        console.error(e);
        msgForUi = "🔒 Encrypted message";
      }
    } else {
      msgForUi = "🔒 Encrypted message (unlock to read)";
    }
  }

  let parsed = null;
  if (typeof msgForUi === "string") {
    const s = msgForUi.trim();
    if (s.startsWith("{") && s.endsWith("}")) {
      try { parsed = JSON.parse(s); } catch { parsed = null; }
    }
  }

  const ts = payload?.timestamp || payload?.ts || Date.now();
  if (parsed && typeof parsed === "object" && parsed.kind === "file" && parsed.file_id) {
    if (!parsed.group_id) parsed.group_id = Number(group_id);
    appendDmPayload(win, `${sender}:`, parsed, { peer: `group:${group_id}`, direction: "in", ts });
  } else if (parsed && typeof parsed === "object" && parsed.kind === "torrent") {
    appendDmPayload(win, `${sender}:`, parsed, { peer: `group:${group_id}`, direction: "in", ts });
  } else {
    appendLine(win, `${sender}:`, msgForUi, { ts });
  }

  if (shouldNotifyGroupMessage(win, group_id, sender)) {
    const notifText = (parsed && parsed.kind === "file")
      ? `📎 ${parsed?.name || "file"}`
      : (parsed && parsed.kind === "torrent")
        ? "🧲 Torrent"
        : `${msgForUi}`;
    const dedupeKey = `groupmsg:${String(group_id)}:${String(sender || '').toLowerCase()}:${String(payload?.message_id || ecNormalizeNotificationText(notifText))}`;
    toast(`👥 ${sender} in group #${group_id}`, "info", 3500, { event: "group_message", dedupeKey });
    maybeBrowserNotify("Group message", `${sender}: ${notifText}`, { dedupeKey });
  }
});

// ───────────────────────────────────────────────────────────────────────────────
// DMs (E2EE) — floating windows
// ───────────────────────────────────────────────────────────────────────────────
const EC_PM_FULL_TITLE_USERNAME_MAX = 14;

function ecPrivateMessageWindowTitle(username) {
  const name = String(username || "").trim().replace(/\s+/g, " ") || "user";
  const prefix = name.length <= EC_PM_FULL_TITLE_USERNAME_MAX ? "Private message" : "PM";
  return `${prefix} — ${name}`;
}

function ecPrivateMessageWindowFullTitle(username) {
  const name = String(username || "").trim().replace(/\s+/g, " ") || "user";
  return `Private message — ${name}`;
}

function ecUpdatePrivateMessageWindowTitle(win, username) {
  if (!win || !win._ym || !win._ym.titleEl) return;
  const title = ecPrivateMessageWindowTitle(username);
  const fullTitle = ecPrivateMessageWindowFullTitle(username);
  win._ym.titleEl.textContent = title;
  win._ym.titleEl.title = fullTitle;
  win.setAttribute("aria-label", fullTitle);
  win.dataset.windowTitle = title;
  win.dataset.windowFullTitle = fullTitle;
}

function openPrivateChat(username, opts = {}) {
  const peer = ecPmPeerName(username);
  if (!peer) return null;

  const currentUserName = ecPmPeerName(window.CURRENT_USER || window.USERNAME || '');
  if (peer && currentUserName && ecSamePmPeer(peer, currentUserName) && !opts?.allowSelf) {
    toast("ℹ️ You cannot open a private message window to yourself.", "info");
    return null;
  }

  const consumeOffline = opts?.consumeOffline !== false;
  const consumePromptUnlock = !!opts?.promptUnlock;
  const consumeQuiet = opts?.quiet !== false;

  const id = ecPmWindowId(peer);
  const existed = UIState.windows.has(id);
  const win = createWindow({ id, title: ecPrivateMessageWindowTitle(peer), kind: "dm" });
  if (!win) return null;
  win.dataset.pmPeer = peer;
  win.dataset.pmPeerKey = ecPmPeerKey(peer);
  win.dataset.mobileSheet = "pm";
  ecUpdatePrivateMessageWindowTitle(win, peer);

  // Load local history (if enabled) once per window.
  ensureDmHistoryRendered(win, peer);

  if (!existed) {
    win._ym.send.onclick = async () => {
      const msg = win._ym.input.value.trim();
      if (!msg) return;

      try {
        // Magnet paste → render as torrent card in chat
        if (isMagnetText(msg)) {
          const meta = await sendTorrentMagnetShare(peer, msg, { win });
          if (meta) {
            addPmHistory(peer, "out", `🧲 Magnet: ${meta.name || meta.infohash}`);
            win._ym.input.value = "";
          }
          return;
        }

        const ok = await sendPrivateTo(peer, msg);
        if (ok) {
          appendLine(win, "You:", msg);
          addPmHistory(peer, "out", msg);
          win._ym.input.value = "";
        }
      } catch (e) {
        console.error(e);
        toast("❌ Message send failed", "error");
      }
    };

    // DM GIF button (send without touching the composer input)
    if (win._ym?.gifBtn) {
      win._ym.gifBtn.onclick = () => {
        openGifPicker(async (url) => {
          const clean = _gifFallbackUrl(url) || url;
          const msg = `gif:${clean}`;
          try {
            const ok = await sendPrivateTo(peer, msg);
            if (ok) {
              appendLine(win, "You:", msg);
              addPmHistory(peer, "out", msg);
            } else {
              toast("❌ GIF send failed", "error");
            }
          } catch (e) {
            console.error(e);
            toast(`❌ GIF send failed: ${e?.message || e}`, "error");
          }
        });
      };
    }

    // File share (encrypted upload) button between log + compose
    if (win._ym.fileBtn && win._ym.fileInput) {
      win._ym.fileBtn.onclick = () => win._ym.fileInput.click();
      win._ym.fileInput.onchange = async () => {
        const f = win._ym.fileInput.files && win._ym.fileInput.files[0];
        // Reset selection immediately so reselecting the same file triggers change
        win._ym.fileInput.value = "";
        if (!f) return;

        try {
          if (isTorrentName(f.name)) {
            toast(`🧲 Sharing torrent ${f.name}…`, "info", 1600);
            await sendTorrentShare(peer, f, { win });
            addPmHistory(peer, "out", `🧲 Torrent: ${f.name}`);
            toast(`✅ Torrent shared with ${peer}`, "ok");
            return;
          }

          toast(`⬆️ Uploading ${f.name}…`, "info", 1600);
          const payload = await sendDmFileTo(peer, f, { win });
          if (payload) {
            appendDmPayload(win, "You:", payload, { peer, direction: "out" });
            addPmHistory(peer, "out", `📎 ${payload.name} (${humanBytes(payload.size)})`);
            toast(`✅ Sent file to ${peer}`, "ok");
          }
        } catch (e) {
          console.error(e);
          toast(`❌ File send failed: ${e?.message || e}`, "error");
        }
      };
    }

    // Voice controls
    if (win._ym.voiceBtn) {
      // Start hidden by default
      voiceDmUi(peer, { statusText: "Not connected", mode: "idle", hideBar: true });

      win._ym.voiceBtn.onclick = () => voiceToggleDmMain(peer);
      win._ym.voiceBtn.oncontextmenu = (ev) => {
        try {
          ev.preventDefault();
          if (!VOICE_STATE.micStream) return false;
          const muted = !VOICE_STATE.micMuted;
          voiceSetMute(muted);
          voiceDmUi(peer, { muteLabel: muted ? "Unmute" : "Mute" });
          voiceUpdateDmVoiceButton(peer);
          toast(muted ? "🔇 Mic muted" : "🎤 Mic unmuted", "info");
        } catch (e) {}
        return false;
      };

      win._ym.voiceBtnCall && (win._ym.voiceBtnCall.onclick = () => voiceStartDmCall(peer));
      win._ym.voiceBtnHang && (win._ym.voiceBtnHang.onclick = () => voiceHangupDm(peer, "Ended", true));
      win._ym.voiceBtnMute && (win._ym.voiceBtnMute.onclick = () => voiceToggleMuteDm(peer));
      win._ym.voiceBtnAccept && (win._ym.voiceBtnAccept.onclick = () => voiceAcceptDmCall(peer));
      win._ym.voiceBtnDecline && (win._ym.voiceBtnDecline.onclick = () => voiceDeclineDmCall(peer, "Declined"));
      try { voiceWireWindowTalkControls(win); } catch (e) {}
    }
  }

  bringToFront(win);

  // If this DM window is open, the missed-messages sidebar should not keep showing this peer.
  // Consume any offline queue for this peer ONLY when it makes sense:
  // - Only if we actually have missed messages for this peer
  // - Only if we can decrypt now (key already unlocked) OR the caller explicitly wants to prompt
  // This avoids a common failure mode where the app "peeks" while locked, hides the missed entry,
  // and then the bubble reappears after refresh because nothing was actually ACKed.
  if (consumeOffline) {
    try {
      // Always check once per DM window open, even if the missed summary arrives later.
      // This prevents a race where the user opens the DM before we received missed_pm_summary,
      // which would otherwise skip consumption and keep the bubble stuck.
      if (!win._ym.__offlineChecked) {
        win._ym.__offlineChecked = true;

        // Consume server-side; ciphertext is queued locally if private messages are not ready.
        consumeOfflinePmsForPeer(peer, { promptUnlock: consumePromptUnlock, quiet: consumeQuiet });

        // Optional hint (once) when locked and we did not prompt.
        if (!window.myPrivateCryptoKey && !consumePromptUnlock) {
          try {
            if (!win._ym.__missedHintShown) {
              win._ym.__missedHintShown = true;
              appendLine(win, "System:", `📨 Missed messages from ${peer} will appear after private messages are ready. Sign out and sign back in if they do not appear.`, "system");
            }
          } catch {}
        }
      }
    } catch {}
  }

  return win;
}
// ───────────────────────────────────────────────────────────────────────────────
async function sendPrivateTo(to, plaintext) {
  const allowPlain = DM_PLAINTEXT_COMPAT_ALLOWED;
  const targetUser = ecPmPeerName(to);
  const currentUser = ecPmPeerName(window.CURRENT_USER || window.USERNAME || '');

  if (!targetUser) {
    toast("❌ Missing PM recipient", "error");
    return false;
  }

  if (targetUser && currentUser && ecSamePmPeer(targetUser, currentUser)) {
    toast("ℹ️ You cannot send a private message to yourself.", "info");
    return false;
  }

  if (typeof ecIsBlockedPrivateMessageSender === "function" && ecIsBlockedPrivateMessageSender(targetUser)) {
    toast(`⛔ PM blocked between you and ${targetUser}`, "error");
    try { socket.emit("get_missed_pm_summary"); } catch {}
    return false;
  }

  const emitDmAck = (payload, timeoutMs = 8000) => {
    if (typeof ecEmitAck === "function") {
      return ecEmitAck("send_direct_message", payload, timeoutMs, {
        connectBannerText: "🔌 Reconnecting before sending PM…",
      }).then((res) => (res && typeof res === "object") ? res : { success: false, error: "No response from server" });
    }
    return new Promise((resolve) => {
      let done = false;
      const timer = setTimeout(() => {
        if (done) return;
        done = true;
        resolve({ success: false, error: "Socket ACK timeout" });
      }, timeoutMs);

      try {
        socket.emit("send_direct_message", payload, (res) => {
          if (done) return;
          done = true;
          clearTimeout(timer);
          resolve((res && typeof res === "object") ? res : { success: false, error: "No response from server" });
        });
      } catch (e) {
        if (done) return;
        done = true;
        clearTimeout(timer);
        resolve({ success: false, error: String(e?.message || e || "Socket emit failed") });
      }
    });
  };

  const describeDmError = (res, fallbackUser) => {
    const raw = String(res?.error || res?.message || "PM failed");
    const low = raw.toLowerCase();
    if (low.includes("cannot dm yourself") || low.includes("self_dm_disabled")) {
      return "ℹ️ You cannot send a private message to yourself.";
    }
    if (low.includes("blocked")) {
      return `⛔ PM blocked between you and ${fallbackUser}`;
    }
    if (low.includes("user_not_found") || low.includes("invalid_username") || low.includes("username_required")) {
      return `❌ PM user not found: ${fallbackUser}`;
    }
    if (low.includes("target_not_active")) {
      return `⛔ ${fallbackUser} cannot receive private messages right now.`;
    }
    if (low.includes("rate limit")) {
      return `⏳ ${raw}`;
    }
    if (low.includes("quota exceeded")) {
      return `⏳ ${raw}`;
    }
    if (low.includes("socket ack timeout") || low.includes("no response from server")) {
      return "⚠️ PM server did not respond in time.";
    }
    if (low.includes("dm_requires_e2ee")) {
      return "🔒 This server requires encrypted private messages.";
    }
    if (low.includes("plaintext_dm_disabled")) {
      return "🔒 Plaintext DM fallback is disabled on this server.";
    }
    if (low.includes("missing recipient or message")) {
      return "❌ Missing PM recipient or message.";
    }
    return `❌ PM to ${fallbackUser} failed: ${raw}`;
  };

  // If WebCrypto isn't available (non-HTTPS/non-localhost), optionally fall back to plaintext wrapper.
  if (!HAS_WEBCRYPTO) {
    if (allowPlain) {
      try {
        const cipher = wrapPlainDm(plaintext);
        const ok = await new Promise((resolve) => {
          emitDmAck({ to: targetUser, cipher }).then((res) => resolve(res));
        });
        if (ok?.success) {
          toast("⚠️ Sent without E2EE (compat mode)", "warn", 2600);
          return true;
        }
        toast(describeDmError(ok, targetUser), "error");
      } catch (e) {
        console.error(e);
      }
    }
    toast("🔒 Private messages require HTTPS or http://localhost.", "warn");
    return false;
  }

  // Normal E2EE path (hybrid RSA-OAEP + AES-GCM envelope)
  try {
    // IMPORTANT: do not rely on a long-lived cached pubkey for DMs.
    // Keys can rotate (e.g., after password reset), and stale caches cause 1-way "could not decrypt".
    const rsaPubKey = await getUserRsaPublicKey(targetUser, { forceRefresh: true });

    const encoder = new TextEncoder();
    const msgBytes = encoder.encode(String(plaintext ?? ""));

    const aesKey = await window.crypto.subtle.generateKey(
      { name: "AES-GCM", length: 256 },
      true,
      ["encrypt", "decrypt"]
    );
    const iv = window.crypto.getRandomValues(new Uint8Array(12));
    const ctBuffer = await window.crypto.subtle.encrypt({ name: "AES-GCM", iv }, aesKey, msgBytes);
    const rawAesKey = await window.crypto.subtle.exportKey("raw", aesKey);
    const wrappedKey = await window.crypto.subtle.encrypt({ name: "RSA-OAEP" }, rsaPubKey, rawAesKey);

    const envelope = {
      v: 1,
      alg: "RSA-OAEP+AES-GCM",
      ek: b64FromBytes(new Uint8Array(wrappedKey)),
      iv: b64FromBytes(iv),
      ct: b64FromBytes(new Uint8Array(ctBuffer))
    };

    const cipher = PM_ENVELOPE_PREFIX + btoa(JSON.stringify(envelope));

    const ok = await new Promise((resolve) => {
      emitDmAck({ to: targetUser, cipher }).then((res) => resolve(res));
    });

    if (!ok?.success) {
      toast(describeDmError(ok, targetUser), ok?.error && String(ok.error).toLowerCase().includes("cannot dm yourself") ? "info" : "error");
      return false;
    }
    if (ok?.queued_offline || ok?.delivered === false) {
      toast(`📬 ${targetUser} is offline. PM saved for later delivery.`, "info", 2600, { event: "dm", dedupeKey: `pm-queued:${targetUser}` });
    }
    return true;
  } catch (e) {
    console.error(e);
    const encErr = String(e?.message || e || "").toLowerCase();
    if (encErr.includes("blocked")) {
      toast(describeDmError({ error: "blocked" }, targetUser), "error");
      return false;
    }
    if (encErr.includes("user_not_found") || encErr.includes("target_not_active") || encErr.includes("invalid_username") || encErr.includes("username_required")) {
      toast(describeDmError({ error: e?.message || e }, targetUser), "error");
      return false;
    }

    // Compatibility: peer may lack keys (or server refused /get_public_key). Optionally fall back.
    if (allowPlain) {
      try {
        const cipher = wrapPlainDm(plaintext);
        const ok = await new Promise((resolve) => {
          emitDmAck({ to: targetUser, cipher }).then((res) => resolve(res));
        });
        if (ok?.success) {
          toast("⚠️ Sent without E2EE (peer missing keys)", "warn", 2600);
          return true;
        }
        toast(describeDmError(ok, targetUser), "error");
      } catch (e2) {
        console.error(e2);
      }
    }

    toast("❌ Failed to encrypt or send PM", "error");
    return false;
  }
}
