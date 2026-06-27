// ───────────────────────────────────────────────────────────────────────────────
// Hub menu bar
// ───────────────────────────────────────────────────────────────────────────────
let EC_DOCK_MENU = null;
let EC_DOCK_MENU_HOVER_TIMER = 0;
let EC_DOCK_MENU_ACTIVE_BUTTON = null;

const HUB_MENU_DEFS = {
  account: {
    title: 'Account',
    items: [
      { id: 'editMyProfile', icon: '👤', label: 'Edit my profile' },
      { sep: true },
      { id: 'statusOnline', icon: '🟢', label: 'Set status: Online' },
      { id: 'statusAway', icon: '🟡', label: 'Set status: Away' },
      { id: 'statusBusy', icon: '🔴', label: 'Set status: Busy' },
      { id: 'statusInvisible', icon: '👻', label: 'Set status: Invisible' },
      { sep: true },
      { id: 'openSettings', icon: '⚙', label: 'Settings' },
      { id: 'logout', icon: '↪', label: 'Log out' }
    ]
  },
  people: {
    title: 'People',
    items: [
      { id: 'openNewPm', icon: '💬', label: 'Open private message…' },
      { id: 'openAddFriend', icon: '➕', label: 'Add friend by username' },
      { id: 'viewPending', icon: '🕓', label: 'Open pending friends' },
      { id: 'viewBlockedUsers', icon: '🚫', label: 'View blocked users' },
      { id: 'refreshFriends', icon: '↻', label: 'Refresh friends list' }
    ]
  },
  view: {
    title: 'View',
    items: [
      { id: 'showFriendsTab', icon: '🧑', label: 'Show friends panel' },
      { id: 'openMissedPm', icon: '💬', label: 'Open missed private message' },
      { id: 'showGroupsTab', icon: '👥', label: 'Show groups panel' },
      { id: 'openGroupsCreate', icon: '✨', label: 'Create group from hub' },
      { id: 'refreshHub', icon: '🔄', label: 'Refresh hub now' }
    ]
  },
  help: {
    title: 'Help',
    items: [
      { id: 'startTour', icon: '❓', label: 'Replay hub tour' },
      { id: 'showTips', icon: '⌨', label: 'Show quick tips' },
      { sep: true },
      { id: 'aboutHub', icon: 'ℹ', label: `About ${SERVER_NAME} hub` }
    ]
  }
};

function ensureDockMenu() {
  if (EC_DOCK_MENU) return EC_DOCK_MENU;
  const menu = document.createElement('div');
  menu.id = 'ecDockMenu';
  menu.className = 'ecDockMenu hidden';
  menu.addEventListener('contextmenu', (e) => { try { e.preventDefault(); } catch {} });
  menu.addEventListener('click', (e) => {
    const item = e.target?.closest?.('.ecDockMenuItem');
    if (!item) return;
    const cmd = String(item.dataset.cmd || '');
    hideDockMenu();
    if (cmd) handleDockMenuAction(cmd);
  });
  document.addEventListener('mousedown', (e) => {
    if (!EC_DOCK_MENU || EC_DOCK_MENU.classList.contains('hidden')) return;
    if (EC_DOCK_MENU.contains(e.target)) return;
    if (e.target?.closest?.('.dockMenuBtn')) return;
    hideDockMenu();
  });
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') hideDockMenu(); });
  window.addEventListener('resize', () => hideDockMenu());
  window.addEventListener('blur', () => hideDockMenu());
  (document.body || document.documentElement).appendChild(menu);
  EC_DOCK_MENU = menu;
  return menu;
}

function hideDockMenu() {
  if (EC_DOCK_MENU_HOVER_TIMER) {
    clearTimeout(EC_DOCK_MENU_HOVER_TIMER);
    EC_DOCK_MENU_HOVER_TIMER = 0;
  }
  if (!EC_DOCK_MENU) return;
  EC_DOCK_MENU.classList.add('hidden');
  EC_DOCK_MENU.dataset.menu = '';
  if (EC_DOCK_MENU_ACTIVE_BUTTON) {
    try { EC_DOCK_MENU_ACTIVE_BUTTON.classList.remove('is-menu-hot'); } catch {}
    EC_DOCK_MENU_ACTIVE_BUTTON = null;
  }
  document.querySelectorAll('.dockMenuBtn[aria-expanded="true"]').forEach((btn) => {
    btn.setAttribute('aria-expanded', 'false');
    btn.classList.remove('is-menu-hot');
  });
}

function buildDockMenuNode(menuKey) {
  const def = HUB_MENU_DEFS[String(menuKey || '')];
  if (!def) return document.createDocumentFragment();
  const frag = document.createDocumentFragment();
  frag.appendChild(ecCreateEl('div', { className: 'ecDockMenuHeader', text: def.title || '' }));
  for (const item of (def.items || [])) {
    if (item.sep) {
      frag.appendChild(ecCreateEl('div', { className: 'ecDockMenuSep' }));
      continue;
    }
    frag.appendChild(ecCreateEl('button', { type: 'button', className: 'ecDockMenuItem', dataset: { cmd: item.id || '' } }, [
      ecCreateEl('span', { className: 'ecDockMenuItemIcon', ariaHidden: 'true', text: item.icon || '' }),
      ecCreateEl('span', { text: item.label || '' })
    ]));
  }
  return frag;
}

function isDockMenuOpen() {
  return !!(EC_DOCK_MENU && !EC_DOCK_MENU.classList.contains('hidden') && EC_DOCK_MENU.dataset.menu);
}

function queueDockMenuHoverSwitch(btn, menuKey) {
  const key = String(menuKey || '').trim();
  if (!btn || !key || !HUB_MENU_DEFS[key]) return;
  if (!isDockMenuOpen()) return;
  if (EC_DOCK_MENU?.dataset?.menu === key) return;
  if (EC_DOCK_MENU_HOVER_TIMER) clearTimeout(EC_DOCK_MENU_HOVER_TIMER);
  EC_DOCK_MENU_HOVER_TIMER = setTimeout(() => {
    EC_DOCK_MENU_HOVER_TIMER = 0;
    if (!isDockMenuOpen()) return;
    showDockMenu(btn, key, { viaHover: true });
  }, 70);
}

function cancelDockMenuHoverSwitch() {
  if (!EC_DOCK_MENU_HOVER_TIMER) return;
  clearTimeout(EC_DOCK_MENU_HOVER_TIMER);
  EC_DOCK_MENU_HOVER_TIMER = 0;
}

function showDockMenu(btn, menuKey, opts = {}) {
  const key = String(menuKey || '').trim();
  if (!btn || !HUB_MENU_DEFS[key]) return;
  const menu = ensureDockMenu();
  const sameMenuOpen = !menu.classList.contains('hidden') && menu.dataset.menu === key;
  if (sameMenuOpen && !opts.viaHover) {
    hideDockMenu();
    return;
  }
  cancelDockMenuHoverSwitch();
  document.querySelectorAll('.dockMenuBtn[aria-expanded="true"]').forEach((node) => {
    node.setAttribute('aria-expanded', 'false');
    node.classList.remove('is-menu-hot');
  });
  if (EC_DOCK_MENU_ACTIVE_BUTTON && EC_DOCK_MENU_ACTIVE_BUTTON !== btn) {
    try { EC_DOCK_MENU_ACTIVE_BUTTON.classList.remove('is-menu-hot'); } catch {}
  }

  ecClearNode(menu);
  menu.appendChild(buildDockMenuNode(key));
  menu.dataset.menu = key;
  menu.classList.remove('hidden');
  btn.setAttribute('aria-expanded', 'true');
  btn.classList.add('is-menu-hot');
  EC_DOCK_MENU_ACTIVE_BUTTON = btn;

  const pad = 8;
  const btnRect = btn.getBoundingClientRect();
  const rect = menu.getBoundingClientRect();
  let left = btnRect.left;
  let top = btnRect.bottom + 6;
  if (left + rect.width + pad > window.innerWidth) left = window.innerWidth - rect.width - pad;
  if (top + rect.height + pad > window.innerHeight) top = Math.max(pad, btnRect.top - rect.height - 6);
  menu.style.left = `${Math.max(pad, left)}px`;
  menu.style.top = `${Math.max(pad, top)}px`;
}

function handleDockMenuAction(cmd) {
  switch (String(cmd || '')) {
    case 'statusOnline': setStatusFromHub('online'); return;
    case 'statusAway': setStatusFromHub('away'); return;
    case 'statusBusy': setStatusFromHub('busy'); return;
    case 'statusInvisible': setStatusFromHub('invisible'); return;
    case 'openSettings': openSettings(); return;
    case 'logout': $('btnLogout')?.click(); return;
    case 'editMyProfile':
      openMyProfileEditor();
      return;
    case 'openNewPm':
      openDockNewPmPopup(UIState.selectedBuddy || '');
      return;
    case 'openAddFriend':
      openDockAddFriendPopup();
      return;
    case 'refreshFriends':
      getFriends();
      getPendingFriendRequests();
      getBlockedUsers();
      toast('↻ Buddy list refreshed', 'info', 2500);
      return;
    case 'viewPending':
      setActiveTab('friends');
      openDockRailPanel('pending');
      return;
    case 'viewBlockedUsers':
      viewBlockedUsersFromMenu();
      return;
    case 'showFriendsTab':
      setActiveTab('friends');
      return;
    case 'showGroupsTab':
      setActiveTab('groups');
      try { $('groupsSectionList')?.scrollIntoView({ behavior: 'smooth', block: 'start' }); } catch {}
      return;
    case 'openGroupsCreate':
      setActiveTab('groups');
      try { $('groupCreateName')?.focus(); } catch {}
      return;
    case 'openMissedPm': {
      const first = Array.isArray(UIState.missedPmSummary) ? UIState.missedPmSummary[0] : null;
      if (!first?.sender) {
        openDockRailPanel('missed');
        return toast('ℹ️ No missed private messages right now', 'info');
      }
      openDockRailPanel('missed');
      openMissedPmFrom(first.sender);
      return;
    }
    case 'refreshHub':
      getFriends();
      getPendingFriendRequests();
      getBlockedUsers();
      try { refreshMyGroups(); refreshGroupInvites(); } catch {}
      try { if (rbHasUI()) rbRenderRoomLists(); } catch {}
      toast('🔄 Hub refreshed', 'info', 2500);
      return;
    case 'startTour':
      startHelpTour({ auto: false });
      return;
    case 'showTips':
      toast('Tip: right-click a user for profile, PM, block, or add-friend actions. Use the alert bubbles for missed messages, pending friends, and important hub items.', 'info', 7000);
      return;
    case 'aboutHub':
      toast(`${SERVER_NAME} hub includes a desktop-style menu bar, buddy list controls, and a vertical alert bubble rail for missed and pending items.`, 'info', 6000);
      return;
  }
}
