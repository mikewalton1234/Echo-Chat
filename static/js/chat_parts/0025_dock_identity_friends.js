
function ecNormalizeUsernameKey(value) {
  return String(value || '').replace(/\s+/g, ' ').trim().toLowerCase();
}

function ecCanonicalUsernameList(list, opts = {}) {
  const excludeSelf = !!opts.excludeSelf;
  const excludeBlocked = !!opts.excludeBlocked;
  const excludeFriends = !!opts.excludeFriends;
  const selfKey = ecNormalizeUsernameKey(currentUser || '');
  const seen = new Set();
  const out = [];
  (Array.isArray(list) ? list : []).forEach((value) => {
    const name = String(value || '').replace(/\s+/g, ' ').trim();
    const key = ecNormalizeUsernameKey(name);
    if (!name || !key || seen.has(key)) return;
    if (excludeSelf && selfKey && key === selfKey) return;
    if (excludeBlocked && ecUserSetHasName(UIState.blockedSet, name)) return;
    if (excludeFriends && ecUserSetHasName(UIState.friendSet, name)) return;
    seen.add(key);
    out.push(name);
  });
  return out;
}

function ecUserSetHasName(set, username) {
  const key = ecNormalizeUsernameKey(username);
  if (!key || !(set instanceof Set)) return false;
  if (set.has(username) || set.has(key)) return true;
  for (const item of set.values()) {
    if (ecNormalizeUsernameKey(item) === key) return true;
  }
  return false;
}

function ecSetPresenceForUsername(username, payload = {}) {
  const name = String(username || '').replace(/\s+/g, ' ').trim();
  const key = ecNormalizeUsernameKey(name);
  if (!name || !key) return;
  const data = {
    online: !!payload.online,
    presence: String(payload.presence || (payload.online ? 'online' : 'offline')),
    custom_status: String(payload.custom_status || payload.customStatus || ''),
    last_seen: payload.last_seen || payload.lastSeen || null,
    avatar_url: String(payload.avatar_url || payload.avatarUrl || ''),
  };
  UIState.presence.set(name, data);
  UIState.presence.set(key, data);
  try { window.ecRefreshMessageAvatarsForUsername?.(name); } catch {}
}

function ecGetPresenceForUsername(username) {
  const name = String(username || '').replace(/\s+/g, ' ').trim();
  const key = ecNormalizeUsernameKey(name);
  return UIState.presence.get(name) || UIState.presence.get(key) || null;
}

function setActiveDockQuickStat(targetId = null, tab = null) {
  const btns = [...document.querySelectorAll('#dockQuickStats .dockStat')];
  if (!btns.length) return;
  let active = null;
  if (targetId) active = btns.find((b) => String(b.dataset.jumpTarget || '') === String(targetId));
  if (!active && tab) active = btns.find((b) => String(b.dataset.jumpTab || '') === String(tab));
  if (!active) active = btns[0];
  btns.forEach((b) => b.classList.toggle('active', b === active));
}

function setActiveTab(tab) {
  const prevTab = String(UIState.activeTab || '');
  UIState.activeTab = tab;
  if (tab === 'groups') { try { refreshMyGroups(); refreshGroupInvites(); } catch (e) {} }

  ['friends', 'groups'].forEach(t => {
    $('tab' + t[0].toUpperCase() + t.slice(1))?.classList.toggle('active', t === tab);
    const panel = $('panel' + t[0].toUpperCase() + t.slice(1));
    panel?.classList.toggle('hidden', t !== tab);
    if (t === tab && panel && prevTab !== String(tab || '')) {
      try { window.ecAnimatePanel?.(panel); } catch {}
    }
  });

  if (prevTab !== String(tab || '')) {
    clearDockSearchesForPanelSwitch();
  }

  setActiveDockQuickStat(null, tab);
  applyDockSearchFilter($('dockSearch')?.value || '');
}

function dockInitials(name) {
  const s = String(name || '').trim();
  if (!s) return '•';
  const parts = s.split(/\s+/).filter(Boolean).slice(0, 2);
  return parts.map((p) => p[0]?.toUpperCase() || '').join('') || s[0].toUpperCase();
}

function humanPresenceText(online, presence) {
  if (!online) return 'Offline';
  switch (String(presence || 'online')) {
    case 'busy': return 'Busy';
    case 'away': return 'Away';
    case 'invisible': return 'Invisible';
    default: return 'Online';
  }
}

function normalizeDockAvatarUrl(raw) {
  const value = String(raw || '').trim();
  if (!value) return '';
  if (typeof ecNormalizeSafeUrl === 'function') {
    return ecNormalizeSafeUrl(value, { allowRelative: true, allowExternal: true }) || '';
  }
  return value;
}

function renderDockAvatar(avatar, name, avatarUrl = '') {
  if (!avatar) return;
  const fallback = dockInitials(name);
  avatar.classList.remove('hasImage');
  avatar.replaceChildren(document.createTextNode(fallback));

  const safeAvatarUrl = normalizeDockAvatarUrl(avatarUrl);
  if (!safeAvatarUrl) return;

  const img = document.createElement('img');
  img.src = safeAvatarUrl;
  img.alt = `${String(name || 'User')} avatar`;
  img.loading = 'lazy';
  img.referrerPolicy = 'no-referrer';
  img.addEventListener('error', () => {
    avatar.classList.remove('hasImage');
    avatar.replaceChildren(document.createTextNode(fallback));
  }, { once: true });
  avatar.classList.add('hasImage');
  avatar.replaceChildren(img);
}

function createDockIdentity(left, { name = '', presenceClass = 'offline', meta = '', chip = '', avatarUrl = '' } = {}) {
  const dot = document.createElement('span');
  dot.className = 'presDot ' + presenceClass;

  const avatar = document.createElement('span');
  avatar.className = 'liAvatar';
  renderDockAvatar(avatar, name, avatarUrl);

  const textWrap = document.createElement('div');
  textWrap.className = 'liText';

  const primary = document.createElement('div');
  primary.className = 'liPrimaryRow';

  const nameEl = document.createElement('span');
  nameEl.className = 'liName';
  nameEl.textContent = name;
  primary.appendChild(nameEl);

  if (chip) {
    const chipEl = document.createElement('span');
    chipEl.className = 'liChip';
    chipEl.textContent = chip;
    primary.appendChild(chipEl);
  }

  textWrap.appendChild(primary);

  if (meta) {
    const metaEl = document.createElement('div');
    metaEl.className = 'liMeta';
    metaEl.textContent = meta;
    textWrap.appendChild(metaEl);
  }

  left.appendChild(dot);
  left.appendChild(avatar);
  left.appendChild(textWrap);

  return { dot, avatar, textWrap, nameEl };
}

function selectBuddyRow(username, source = '', rowEl = null) {
  const u = String(username || '').trim();
  UIState.selectedBuddy = u;
  UIState.selectedBuddySource = String(source || '');
  document.querySelectorAll('.friendItem.selected, .roomUsersList li.selected, #blockedUsersList li.selected, #pendingRequestsList li.selected, #missedPmList li.selected, #railPendingRequestsList li.selected, #railMissedPmList li.selected, #railAlertsList li.selected').forEach((el) => {
    el.classList.remove('selected');
  });
  if (rowEl) rowEl.classList.add('selected');
  try {
    if (source === 'room' && typeof ecRoomModeratorPanelSync === 'function') {
      ecRoomModeratorPanelSync(UIState.currentRoom || UIState.roomEmbedRoom || '');
    }
  } catch {}
}

function setStatusFromHub(nextStatus) {
  const normalized = String(nextStatus || '').trim();
  if (!['online', 'away', 'busy', 'invisible'].includes(normalized)) return;
  const sel = $('meStatus');
  if (!sel) return;
  sel.value = normalized;
  try { sel.dispatchEvent(new Event('change', { bubbles: true })); } catch {}
}

function sendFriendRequestTo(targetUsername, opts = {}) {
  const friend = String(targetUsername || '').trim();
  const friendKey = ecNormalizeUsernameKey(friend);
  const currentKey = ecNormalizeUsernameKey(currentUser || '');
  if (!friend) return toast('⚠️ Enter a username', 'warn');
  if (friendKey && currentKey && friendKey === currentKey) return toast('⚠️ You cannot add yourself', 'warn');

  if (ecUserSetHasName(UIState.friendSet, friend)) return toast(`ℹ️ ${friend} is already on your friends list`, 'info');
  if (ecUserSetHasName(UIState.blockedSet, friend)) return toast(`⚠️ ${friend} is blocked. Unblock them first.`, 'warn');

  const send = (typeof ecEmitAck === 'function')
    ? ecEmitAck('send_friend_request', { to_username: friend }, 8000, { connectBannerText: '🔌 Reconnecting before sending friend request…' })
    : new Promise((resolve) => socket.emit('send_friend_request', { to_username: friend }, (res) => resolve(res || { success: false })));

  send.then((res) => {
    const canonicalFriend = String(res?.to_username || friend).trim() || friend;
    if (res && res.success) {
      toast(`✅ Friend request sent to ${canonicalFriend}`, 'ok');
      getPendingFriendRequests();
      getFriends();
    } else {
      if (res?.incoming_pending) getPendingFriendRequests();
      toast(`❌ ${res?.error || 'Failed to send request'}`, 'error');
    }
  }).catch((e) => toast(`❌ ${e?.message || 'Failed to send request'}`, 'error'));
}

function getDockPmSuggestions() {
  const seen = new Set();
  const names = [];
  const pushName = (value) => {
    const name = String(value || '').trim();
    if (!name) return;
    if (currentUser && ecNormalizeUsernameKey(name) === ecNormalizeUsernameKey(currentUser)) return;
    const key = ecNormalizeUsernameKey(name);
    if (seen.has(key)) return;
    seen.add(key);
    names.push(name);
  };

  (Array.isArray(UIState.friendsListCache) ? UIState.friendsListCache : []).forEach(pushName);

  return names.sort((a, b) => a.localeCompare(b, undefined, { sensitivity: 'base' }));
}

function refreshDockPmSuggestions() {
  const list = $('dockPmSuggestions');
  if (!list) return;
  list.replaceChildren();
  getDockPmSuggestions().forEach((name) => {
    const opt = document.createElement('option');
    opt.value = name;
    list.appendChild(opt);
  });
}

function ensureDockNewPmPopupViewportModal() {
  const popup = $('dockNewPmPopup');
  const backdrop = $('dockNewPmBackdrop');
  const body = document.body;
  if (!popup || !backdrop || !body) return { popup, backdrop };
  if (backdrop.parentElement !== body) body.appendChild(backdrop);
  if (popup.parentElement !== body) body.appendChild(popup);
  return { popup, backdrop };
}

function openDockNewPmPopup(prefill = '') {
  const { popup, backdrop } = ensureDockNewPmPopupViewportModal();
  const input = $('dockNewPmInput');
  if (!popup || !input) return;
  refreshDockPmSuggestions();
  backdrop?.classList.remove('hidden');
  popup.classList.remove('hidden');
  const nextValue = String(prefill || '').trim();
  input.value = nextValue;
  requestAnimationFrame(() => {
    try { input.focus(); } catch {}
    try { input.select(); } catch {}
  });
}

function focusDockNewPmInput(prefill = '') {
  openDockNewPmPopup(prefill);
}

function closeDockNewPmPopup() {
  $('dockNewPmBackdrop')?.classList.add('hidden');
  $('dockNewPmPopup')?.classList.add('hidden');
}

function submitDockNewPm() {
  const input = $('dockNewPmInput');
  const popup = $('dockNewPmPopup');
  if (!input || !popup || popup.classList.contains('hidden')) return;
  const target = String(input.value || '').trim();
  if (!target) return toast('⚠️ Enter a username', 'warn');
  const win = openPrivateChat(target, { consumeOffline: true, promptUnlock: false, quiet: true });
  if (!win) return;
  input.value = '';
  closeDockNewPmPopup();
  try { bringToFront(win); } catch {}
}

function bindDockNewPmComposer() {
  const { popup, backdrop } = ensureDockNewPmPopupViewportModal();
  const input = $('dockNewPmInput');
  const openBtn = $('btnDockNewPmOpen');
  const closeBtn = $('btnDockNewPmClose');
  const cancelBtn = $('btnDockNewPmCancel');
  if (!popup || !input || popup.dataset.bound === '1') return;
  popup.dataset.bound = '1';

  refreshDockPmSuggestions();
  openBtn?.addEventListener('click', () => submitDockNewPm());
  closeBtn?.addEventListener('click', () => closeDockNewPmPopup());
  cancelBtn?.addEventListener('click', () => closeDockNewPmPopup());
  backdrop?.addEventListener('click', () => closeDockNewPmPopup());
  input.addEventListener('focus', () => refreshDockPmSuggestions());
  input.addEventListener('keydown', (ev) => {
    if (ev.key === 'Enter') {
      try { ev.preventDefault(); } catch {}
      submitDockNewPm();
      return;
    }
    if (ev.key === 'Escape') {
      try { ev.preventDefault(); } catch {}
      input.value = '';
      closeDockNewPmPopup();
    }
  });
  document.addEventListener('keydown', (ev) => {
    if (ev.key !== 'Escape') return;
    if (popup.classList.contains('hidden')) return;
    closeDockNewPmPopup();
  });
}

function ensureDockAddFriendPopupViewportModal() {
  const popup = $('dockAddFriendPopup');
  const backdrop = $('dockAddFriendBackdrop');
  const body = document.body;
  if (!popup || !backdrop || !body) return { popup, backdrop };
  if (backdrop.parentElement !== body) body.appendChild(backdrop);
  if (popup.parentElement !== body) body.appendChild(popup);
  return { popup, backdrop };
}

function openDockAddFriendPopup(prefill = '') {
  const { popup, backdrop } = ensureDockAddFriendPopupViewportModal();
  const input = $('dockAddFriendInput');
  if (!popup || !input) return;
  backdrop?.classList.remove('hidden');
  popup.classList.remove('hidden');
  const value = String(prefill || '').trim();
  input.value = value;
  requestAnimationFrame(() => {
    try { input.focus(); } catch {}
    try { input.select(); } catch {}
  });
}

function closeDockAddFriendPopup() {
  $('dockAddFriendBackdrop')?.classList.add('hidden');
  $('dockAddFriendPopup')?.classList.add('hidden');
}

function submitDockAddFriendPopup() {
  const input = $('dockAddFriendInput');
  const popup = $('dockAddFriendPopup');
  if (!input || !popup || popup.classList.contains('hidden')) return;
  const friend = String(input.value || '').trim();
  if (!friend) return toast('⚠️ Enter a username', 'warn');
  sendFriendRequestTo(friend);
  input.value = '';
  closeDockAddFriendPopup();
}

function bindDockAddFriendPopup() {
  const { popup, backdrop } = ensureDockAddFriendPopupViewportModal();
  const input = $('dockAddFriendInput');
  const sendBtn = $('btnDockAddFriendSend');
  const cancelBtn = $('btnDockAddFriendCancel');
  const closeBtn = $('btnDockAddFriendClose');
  if (!popup || popup.dataset.bound === '1') return;
  popup.dataset.bound = '1';

  backdrop?.addEventListener('click', () => closeDockAddFriendPopup());
  sendBtn?.addEventListener('click', () => submitDockAddFriendPopup());
  cancelBtn?.addEventListener('click', () => closeDockAddFriendPopup());
  closeBtn?.addEventListener('click', () => closeDockAddFriendPopup());
  input?.addEventListener('keydown', (ev) => {
    if (ev.key === 'Enter') {
      try { ev.preventDefault(); } catch {}
      submitDockAddFriendPopup();
    } else if (ev.key === 'Escape') {
      try { ev.preventDefault(); } catch {}
      closeDockAddFriendPopup();
    }
  });

  document.addEventListener('mousedown', (ev) => {
    if (popup.classList.contains('hidden')) return;
    if (popup.contains(ev.target)) return;
    if (ev.target?.closest?.('.dockMenuBtn')) return;
    closeDockAddFriendPopup();
  });
}

function isDockPlaceholderItem(li) {
  if (!li) return true;
  const n = String(li.dataset?.name || '').toLowerCase();
  return n === 'empty' || n === 'none' || n === 'error';
}

function clearSearchLikeInput(el) {
  if (!el) return;
  try { el.value = ''; } catch {}
  const syncWrap = () => {
    try {
      const wrap = el.parentElement;
      if (!wrap || !wrap.classList?.contains('searchInputWrap')) return;
      const hasValue = String(el.value || '').length > 0;
      wrap.classList.toggle('hasValue', hasValue);
      const btn = wrap.querySelector(':scope > .searchClearBtn');
      if (btn) {
        btn.disabled = !hasValue;
        btn.setAttribute('aria-hidden', hasValue ? 'false' : 'true');
      }
    } catch {}
  };
  switch (String(el.id || '')) {
    case 'dockSearch':
      try { applyDockSearchFilter(''); } catch {}
      break;
    case 'rbCatSearch':
      try { ROOM_BROWSER.catQuery = ''; } catch {}
      try { rbRenderCategoryTree(); } catch {}
      break;
    case 'rbRoomSearch':
      try { ROOM_BROWSER.roomQuery = ''; } catch {}
      try { rbRenderRoomLists(); } catch {}
      try { rbUpdateCountsInDom(); } catch {}
      break;
    case 'rbCustomSearch':
      try { ROOM_BROWSER.customQuery = ''; } catch {}
      try { rbRenderRoomLists(); } catch {}
      try { rbUpdateCountsInDom(); } catch {}
      break;
    default:
      if (el.classList?.contains('ym-gifSearch')) {
        try {
          if (GifUI?.visible) gifShowRecents();
        } catch {}
      }
      break;
  }
  syncWrap();
}

function clearSearchInputs(ids = []) {
  (Array.isArray(ids) ? ids : []).forEach((id) => {
    try { clearSearchLikeInput(typeof id === 'string' ? $(id) : id); } catch {}
  });
}

function clearDockSearchesForPanelSwitch() {
  clearSearchInputs(['dockSearch']);
}
