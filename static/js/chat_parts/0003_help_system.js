const HELP_TOUR_STORAGE_KEY = 'helpTourSeen_v4';

function hasSeenHelpTourForCurrentAccount() {
  return Settings.get(HELP_TOUR_STORAGE_KEY, false, { allowLegacyFallback: false });
}

function markHelpTourSeenForCurrentAccount() {
  Settings.set(HELP_TOUR_STORAGE_KEY, true, { clearLegacy: true });
}

const HELP_TOUR_AUTO_DELAY_MS = 1200;
const HELP_TOUR_TARGET_RETRY_MAX = 4;

const EC_HELP = {
  layer: null,
  card: null,
  title: null,
  body: null,
  step: null,
  prevBtn: null,
  nextBtn: null,
  doneBtn: null,
  closeBtn: null,
  muteBtn: null,
  badge: null,
  advanceHint: null,
  progressTrack: null,
  progressFill: null,
  svg: null,
  arrow: null,
  arrowHead: null,
  currentTarget: null,
  visible: false,
  mode: '',
  hoverTimer: null,
  hoverTarget: null,
  closeTimer: null,
  pointerInsideCard: false,
  targetHover: false,
  targetFocus: false,
  hintNonce: 0,
  positionRaf: 0,
  tourIndex: 0,
  steps: [],
  currentStep: null,
  autoStarted: false,
  tourDemoState: {},
  initialized: false,
  observer: null
};

function isElementActuallyVisible(el) {
  if (!el || !el.isConnected) return false;
  if (el.classList?.contains('hidden')) return false;
  let cur = el;
  while (cur && cur !== document.body) {
    if (cur.classList?.contains('hidden')) return false;
    const cs = window.getComputedStyle(cur);
    if (!cs || cs.display === 'none' || cs.visibility === 'hidden' || Number(cs.opacity || 1) === 0) return false;
    cur = cur.parentElement;
  }
  const r = el.getBoundingClientRect();
  return r.width > 0 && r.height > 0;
}

function resolveHelpTarget(selectorOrEl) {
  if (!selectorOrEl) return null;
  if (typeof selectorOrEl === 'function') {
    try { return selectorOrEl() || null; } catch { return null; }
  }
  if (typeof selectorOrEl !== 'string') return selectorOrEl;
  return selectorOrEl;
}

function findVisibleHelpTarget(selectorOrEl) {
  const resolved = resolveHelpTarget(selectorOrEl);
  if (!resolved) return null;
  if (typeof resolved !== 'string') return isElementActuallyVisible(resolved) ? resolved : null;
  const nodes = [...document.querySelectorAll(resolved)];
  return nodes.find((el) => isElementActuallyVisible(el)) || null;
}

function waitForVisibleHelpTarget(selectorOrEl, opts = {}) {
  const timeoutMs = Math.max(0, Number(opts.timeoutMs || 1800));
  const intervalMs = Math.max(40, Number(opts.intervalMs || 90));
  const started = Date.now();
  return new Promise((resolve) => {
    const tick = () => {
      const target = findVisibleHelpTarget(selectorOrEl);
      if (target) {
        resolve(target);
        return;
      }
      if ((Date.now() - started) >= timeoutMs) {
        resolve(null);
        return;
      }
      setTimeout(tick, intervalMs);
    };
    tick();
  });
}

function ensureHelpLayer() {
  if (EC_HELP.layer) return EC_HELP.layer;
  const layer = ecCreateEl('div', { id: 'ecHelpLayer', className: 'ecHelpLayer hidden' });
  layer.appendChild(ecCreateEl('div', { className: 'ecHelpBackdrop' }));
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('class', 'ecHelpSvg');
  svg.setAttribute('aria-hidden', 'true');
  const arrow = document.createElementNS('http://www.w3.org/2000/svg', 'path');
  arrow.setAttribute('class', 'ecHelpArrow');
  const arrowHead = document.createElementNS('http://www.w3.org/2000/svg', 'path');
  arrowHead.setAttribute('class', 'ecHelpArrowHead');
  svg.appendChild(arrow);
  svg.appendChild(arrowHead);
  layer.appendChild(svg);

  const card = ecCreateEl('div', { className: 'ecHelpCard', role: 'dialog', ariaLive: 'polite', ariaAtomic: 'true' });
  card.appendChild(ecCreateEl('button', { type: 'button', className: 'ecHelpClose', ariaLabel: 'Close help', text: '×' }));
  card.appendChild(ecCreateEl('div', { className: 'ecHelpBadge', text: `${SERVER_NAME} guide` }));
  card.appendChild(ecCreateEl('div', { className: 'ecHelpTitle' }));
  card.appendChild(ecCreateEl('div', { className: 'ecHelpBody' }));
  card.appendChild(ecCreateEl('div', { className: 'ecHelpProgressTrack', ariaHidden: 'true' }, [
    ecCreateEl('span', { className: 'ecHelpProgressFill' })
  ]));
  const footer = ecCreateEl('div', { className: 'ecHelpFooter' });
  footer.appendChild(ecCreateEl('div', { className: 'ecHelpMeta' }, [
    ecCreateEl('div', { className: 'ecHelpStep' }),
    ecCreateEl('div', { className: 'ecHelpAdvance', text: 'Click this card to continue' })
  ]));
  footer.appendChild(ecCreateEl('div', { className: 'ecHelpActions' }, [
    ecCreateEl('button', { type: 'button', className: 'miniBtn secondary ecHelpMute', text: 'Turn off tips' }),
    ecCreateEl('button', { type: 'button', className: 'miniBtn secondary ecHelpPrev', text: 'Back' }),
    ecCreateEl('button', { type: 'button', className: 'miniBtn ecHelpNext', text: 'Next' }),
    ecCreateEl('button', { type: 'button', className: 'miniBtn ecHelpDone', text: 'Done' })
  ]));
  card.appendChild(footer);
  layer.appendChild(card);
  document.body.appendChild(layer);

  EC_HELP.layer = layer;
  EC_HELP.card = layer.querySelector('.ecHelpCard');
  EC_HELP.title = layer.querySelector('.ecHelpTitle');
  EC_HELP.body = layer.querySelector('.ecHelpBody');
  EC_HELP.step = layer.querySelector('.ecHelpStep');
  EC_HELP.prevBtn = layer.querySelector('.ecHelpPrev');
  EC_HELP.nextBtn = layer.querySelector('.ecHelpNext');
  EC_HELP.doneBtn = layer.querySelector('.ecHelpDone');
  EC_HELP.closeBtn = layer.querySelector('.ecHelpClose');
  EC_HELP.muteBtn = layer.querySelector('.ecHelpMute');
  EC_HELP.badge = layer.querySelector('.ecHelpBadge');
  EC_HELP.advanceHint = layer.querySelector('.ecHelpAdvance');
  EC_HELP.progressTrack = layer.querySelector('.ecHelpProgressTrack');
  EC_HELP.progressFill = layer.querySelector('.ecHelpProgressFill');
  EC_HELP.svg = layer.querySelector('.ecHelpSvg');
  EC_HELP.arrow = layer.querySelector('.ecHelpArrow');
  EC_HELP.arrowHead = layer.querySelector('.ecHelpArrowHead');

  EC_HELP.prevBtn?.addEventListener('click', () => stepHelpTour(-1));
  EC_HELP.nextBtn?.addEventListener('click', () => stepHelpTour(1));
  EC_HELP.doneBtn?.addEventListener('click', () => closeHelpOverlay({ markSeen: true }));
  EC_HELP.closeBtn?.addEventListener('click', () => closeHelpOverlay({ markSeen: true }));
  EC_HELP.muteBtn?.addEventListener('click', () => {
    setHelpHintsEnabled(false, { persist: true, syncUi: true });
    closeHelpOverlay({ markSeen: false });
    toast('🛈 Quick tips disabled. You can turn them back on in Settings.', 'ok');
  });
  EC_HELP.card?.addEventListener('mouseenter', () => {
    EC_HELP.pointerInsideCard = true;
    cancelHelpCloseTimer();
  });
  EC_HELP.card?.addEventListener('mouseleave', () => {
    EC_HELP.pointerInsideCard = false;
    requestHintClose(140);
  });
  EC_HELP.card?.addEventListener('focusin', () => {
    EC_HELP.pointerInsideCard = true;
    cancelHelpCloseTimer();
  });
  EC_HELP.card?.addEventListener('focusout', () => {
    setTimeout(() => {
      EC_HELP.pointerInsideCard = !!(EC_HELP.card && EC_HELP.card.contains(document.activeElement));
      requestHintClose(140);
    }, 0);
  });
  EC_HELP.card?.addEventListener('click', (e) => {
    if (EC_HELP.mode !== 'tour') return;
    const t = e.target;
    if (t && typeof t.closest === 'function' && t.closest('button, a, input, select, textarea, label, summary, [role="button"]')) return;
    e.preventDefault();
    stepHelpTour(1);
  });
  layer.querySelector('.ecHelpBackdrop')?.addEventListener('click', () => {
    if (EC_HELP.mode === 'tour') stepHelpTour(1);
    else closeHelpOverlay({ markSeen: false });
  });

  return layer;
}

function setHelpMetadata(el, meta = {}) {
  if (!el || !meta) return;
  if (meta.title) el.dataset.helpTitle = String(meta.title);
  if (meta.text) el.dataset.helpText = String(meta.text);
  if (meta.placement) el.dataset.helpPlacement = String(meta.placement);
  wireInlineHelpTarget(el);
}

function applyHelpMetadata(selector, meta = {}) {
  document.querySelectorAll(selector).forEach((el) => setHelpMetadata(el, meta));
}

function helpHintsEnabled() {
  return UIState?.prefs?.helpHints !== false;
}

function syncHelpHintsSettingUi() {
  const cb = $("setHelpHints");
  if (cb) cb.checked = helpHintsEnabled();
}

function cancelHelpCloseTimer() {
  clearTimeout(EC_HELP.closeTimer);
  EC_HELP.closeTimer = null;
}

function shouldKeepHelpHintOpen(target = EC_HELP.currentTarget) {
  if (EC_HELP.mode === 'tour') return true;
  if (!target || !isElementActuallyVisible(target)) return false;
  const active = document.activeElement;
  return !!(
    EC_HELP.pointerInsideCard ||
    EC_HELP.targetHover ||
    EC_HELP.targetFocus ||
    active === target ||
    (active && target.contains?.(active)) ||
    (EC_HELP.card && active && EC_HELP.card.contains(active))
  );
}

function requestHintClose(delay = 140) {
  if (EC_HELP.mode === 'tour') return;
  cancelHelpCloseTimer();
  EC_HELP.closeTimer = setTimeout(() => {
    EC_HELP.closeTimer = null;
    if (!shouldKeepHelpHintOpen()) closeHelpOverlay({ markSeen: false });
  }, delay);
}

function scheduleHelpPositionRefresh() {
  if (EC_HELP.positionRaf) cancelAnimationFrame(EC_HELP.positionRaf);
  EC_HELP.positionRaf = requestAnimationFrame(() => {
    EC_HELP.positionRaf = 0;
    refreshActiveHelpPosition();
  });
}

function setHelpHintsEnabled(enabled, opts = {}) {
  UIState.prefs.helpHints = !!enabled;
  if (opts.persist !== false) Settings.set("helpHints", UIState.prefs.helpHints);
  if (opts.syncUi) syncHelpHintsSettingUi();
  clearTimeout(EC_HELP.hoverTimer);
  EC_HELP.hoverTarget = null;
  if (!UIState.prefs.helpHints && EC_HELP.visible && EC_HELP.mode !== 'tour') {
    closeHelpOverlay({ markSeen: false });
  }
}

function tourRememberSurfaceState(key, wasOpen) {
  if (!key) return;
  EC_HELP.tourDemoState[key] = { wasOpen: !!wasOpen };
}

function tourShouldCloseSurface(key) {
  if (!key) return false;
  return !EC_HELP.tourDemoState?.[key]?.wasOpen;
}

function tourForgetSurfaceState(key) {
  if (!key || !EC_HELP.tourDemoState) return;
  delete EC_HELP.tourDemoState[key];
}

function isModalCurrentlyOpen(id) {
  const modal = $(id);
  return !!(modal && !modal.classList.contains('hidden'));
}

function isWindowCurrentlyOpen(id) {
  try {
    const win = UIState?.windows?.get?.(id);
    return !!(win && !win.classList.contains('hidden'));
  } catch {
    return false;
  }
}

function rememberAndOpenTourModal(key, id, openFn) {
  tourRememberSurfaceState(key, isModalCurrentlyOpen(id));
  if (!tourShouldCloseSurface(key)) return;
  try { openFn?.(); } catch {}
}

function closeTourModalIfOpenedByTour(key, id, closeFn) {
  const shouldClose = tourShouldCloseSurface(key);
  tourForgetSurfaceState(key);
  if (!shouldClose) return;
  try { closeFn?.(); } catch {}
}

function rememberAndOpenTourWindow(key, id, openFn) {
  tourRememberSurfaceState(key, isWindowCurrentlyOpen(id));
  if (!tourShouldCloseSurface(key)) return;
  try { openFn?.(); } catch {}
}

function closeTourWindowIfOpenedByTour(key, id) {
  const shouldClose = tourShouldCloseSurface(key);
  tourForgetSurfaceState(key);
  if (!shouldClose) return;
  try { closeWindow(id); } catch {}
}

function wireInlineHelpTarget(el) {
  if (!el || el.dataset.helpWired === '1') return;
  el.dataset.helpWired = '1';

  const openHint = () => {
    if (EC_HELP.mode === 'tour' || !helpHintsEnabled()) return;
    if (!isElementActuallyVisible(el)) return;
    cancelHelpCloseTimer();
    showHelpForElement(el, {
      mode: 'hint',
      title: el.dataset.helpTitle || SERVER_NAME,
      text: el.dataset.helpText || '',
      placement: el.dataset.helpPlacement || 'right'
    });
  };

  const scheduleOpen = () => {
    if (EC_HELP.mode === 'tour' || !helpHintsEnabled()) return;
    cancelHelpCloseTimer();
    clearTimeout(EC_HELP.hoverTimer);
    EC_HELP.hoverTarget = el;
    const nonce = ++EC_HELP.hintNonce;
    EC_HELP.hoverTimer = setTimeout(() => {
      if (EC_HELP.hoverTarget !== el || nonce !== EC_HELP.hintNonce) return;
      openHint();
    }, 320);
  };

  const scheduleHide = () => {
    if (EC_HELP.mode === 'tour') return;
    clearTimeout(EC_HELP.hoverTimer);
    if (EC_HELP.hoverTarget === el) EC_HELP.hoverTarget = null;
    requestHintClose(140);
  };

  el.addEventListener('mouseenter', () => {
    EC_HELP.targetHover = true;
    scheduleOpen();
  });
  el.addEventListener('mouseleave', () => {
    EC_HELP.targetHover = false;
    scheduleHide();
  });
  el.addEventListener('focus', () => {
    EC_HELP.targetFocus = true;
    openHint();
  });
  el.addEventListener('blur', () => {
    EC_HELP.targetFocus = false;
    scheduleHide();
  });
}

function initHelpMetadata() {
  const defs = [
    ['#sitePlaceholder .rbTitle', { title: 'Room browser', text: 'This is the main lobby picker. Choose a category on the left, browse official rooms in the middle, and use the Custom Rooms panel on the right for user-created rooms.', placement: 'right' }],
    ['#rbCatSearch', { title: 'Category search', text: 'Filter the category tree without changing your active room. This is handy when the room list gets long.', placement: 'right' }],
    ['#rbRoomSearch', { title: 'Official room search', text: 'Search the built-in rooms in the selected category. Use sorting and Hide empty to narrow the official list faster.', placement: 'right' }],
    ['#rbRoomSort', { title: 'Official room sort', text: 'Switch between most active rooms first or alphabetical order.', placement: 'bottom' }],
    ['#rbHideEmpty', { title: 'Hide empty rooms', text: 'Turn this on if you only want rooms that currently have people inside them.', placement: 'bottom' }],
    ['#rbRoomStatusFilter', { title: 'Room status filter', text: 'Filter rooms by open, active, empty, locked, read-only, slowmode, or full status without opening a details panel.', placement: 'bottom' }],
    ['#rbScopeBar', { title: 'Room scopes', text: 'Switch between all official rooms, your current room, recent picks, favorites, or unread rooms.', placement: 'bottom' }],
    ['#rbRoomsList', { title: 'Official room list', text: 'Single-click an official room to select it. Double-click it, or use Join / Open, to enter fast. Use ☆ to pin favorites.', placement: 'right' }],
    ['#rbCustomRoomsList', { title: 'Custom rooms', text: 'User-created rooms now live in this right-side panel. Use Join / Open, ☆ favorites, and Invite for private rooms you own.', placement: 'left' }],
    ['#rbCustomFilter', { title: 'Custom room filter', text: 'Filter all custom rooms, public rooms, private rooms, or just the ones you own.', placement: 'bottom' }],
    ['#rbCustomSort', { title: 'Custom room sort', text: 'Sort custom rooms by activity or alphabetically.', placement: 'bottom' }],
    ['#btnOpenCreateRoom', { title: 'Create room', text: 'Open the custom-room creator. Pick a category, visibility, and optional age / NSFW flags. After a room is created, you are moved into it automatically.', placement: 'left' }],
    ['#roomEmbedTitle', { title: 'Active room', text: 'When you join a room, the live chat opens here on the left side.', placement: 'right' }],
    ['#roomEmbedInput', { title: 'Room message box', text: 'Type a room message here. Use the emoji, torrent, and GIF buttons beside it for extras.', placement: 'top' }],
    ['#roomEmbedEmojiBtn', { title: 'Emoji picker', text: 'Open the emoji picker for the current room message.', placement: 'top' }],
    ['#roomEmbedGifBtn', { title: 'GIF picker', text: 'Search and send a GIF into the current room.', placement: 'top' }],
    ['#roomEmbedTorrentBtn', { title: 'Torrent share', text: 'Attach a .torrent file or magnet-style share into the current room.', placement: 'top' }],
    ['#btnRoomEmbedVoice', { title: 'Room voice', text: 'Join or manage voice chat for the current room from here.', placement: 'left' }],
    ['#meStatus', { title: 'Presence status', text: 'Set yourself Online, Away, Busy, Invisible, or add a custom status message.', placement: 'left' }],
    ['#dockSearch', { title: 'Dock search', text: 'Search inside the active Friends or Groups panel. It filters names, statuses, invites, and request lists.', placement: 'left' }],
    ['#tabFriends', { title: 'Friends tab', text: 'Shows your buddy list. Missed messages and pending friend requests now live in the side alert bubbles.', placement: 'left' }],
    ['#tabGroups', { title: 'Groups tab', text: 'Shows group tools, invites, and the groups you already belong to.', placement: 'left' }],
    ['#friendsSectionList', { title: 'Friends list', text: 'Single-click or double-click a friend to open a private chat. Use the icons on each row for quick actions.', placement: 'left' }],
    ['#dockAlertRail', { title: 'Alert bubbles', text: 'Important hub items now live here. Use these vertical bubbles for missed private messages, pending friends, and key alerts.', placement: 'left' }],
    ['#railPendingBtn', { title: 'Pending friends bubble', text: 'Open this bubble to accept or reject incoming friend requests without cluttering the main buddy list.', placement: 'left' }],
    ['#groupsSectionCreate', { title: 'Create group', text: 'Make a private group-style chat space for invited members.', placement: 'left' }],
    ['#groupCreateName', { title: 'New group name', text: 'Type the name of the group you want to create, then click Create.', placement: 'left' }],
    ['#groupsSectionJoin', { title: 'Join by invite', text: 'Paste a group ID here when someone invites you to an existing group.', placement: 'left' }],
    ['#groupJoinId', { title: 'Group ID field', text: 'Paste an invite-based group ID here to join that group.', placement: 'left' }],
    ['#railAlertsBtn', { title: 'Important alerts bubble', text: 'Use this bubble for important notifications like group invites. Refresh inside the drawer if needed.', placement: 'left' }],
    ['#groupsSectionList', { title: 'My groups', text: 'This list contains the groups you already belong to.', placement: 'left' }],
    ['#btnLogout', { title: 'Log out', text: `Safely sign out of ${SERVER_NAME} from here.`, placement: 'bottom' }],
    ['#btnSettings', { title: 'Settings', text: 'Open preferences for room text size, notifications, PM storage, themes, and layout.', placement: 'bottom' }],
    ['#btnHelpTour', { title: 'Help / tour', text: `Click here any time to replay the guided ${SERVER_NAME} tour.`, placement: 'bottom' }],
    ['#createRoomModal .modalCard', { title: 'Create custom room', text: `Name the room, choose its category, pick the Public or Private card, and press Create and enter room. ${SERVER_NAME} moves the creator into the new room automatically.`, placement: 'left' }],
    ['#crName', { title: 'Room name', text: 'Give the room a clear name so people know what it is for.', placement: 'bottom' }],
    ['#settingsModal .modalCard', { title: 'Settings panel', text: 'This is where you tune notifications, themes, room text size, and layout.', placement: 'left' }]
  ];
  defs.forEach(([selector, meta]) => applyHelpMetadata(selector, meta));
  applyHelpMetadata('#meAvatar', { title: 'Your profile', text: 'Click your avatar or username to edit your profile card, avatar image, and bio.', placement: 'left' });
  applyHelpMetadata('#meName', { title: 'Your username', text: 'Your username is pinned here in the hub so you can always see which account is signed in.', placement: 'left' });
  applyHelpMetadata('#dockTitleUser', { title: 'Signed-in account', text: 'The hub title now shows the account currently signed in.', placement: 'bottom' });
}

function buildHelpTourSteps() {
  return [
    {
      selector: '#sitePlaceholder .rbTitle',
      section: 'Start',
      title: `Welcome to ${SERVER_NAME}`,
      text: 'This quick end-user tour focuses on the daily chat flow: finding rooms, joining conversations, checking alerts, and adjusting your own account settings.',
      placement: 'right',
      skipIfMissing: true,
      waitMs: 250,
      before: () => { try { rbCloseModal('createRoomModal'); } catch {} try { closeSettings(); } catch {} try { hideDockMenu(); } catch {} try { setActiveTab('friends'); } catch {} }
    },
    {
      selector: '#rbCatSearch',
      section: 'Rooms',
      title: 'Find a category',
      text: 'Use category search when the room tree gets long. It filters the list without changing the room you are currently using.',
      placement: 'right',
      skipIfMissing: true,
      waitMs: 220
    },
    {
      selector: '#rbScopeBar',
      section: 'Rooms',
      title: 'Filter the room list',
      text: 'These chips help you switch between official rooms, favorites, recent rooms, unread rooms, and your current room.',
      placement: 'bottom',
      skipIfMissing: true,
      waitMs: 220
    },
    {
      selector: '#rbRoomsList',
      section: 'Rooms',
      title: 'Join an official room',
      text: 'Official rooms are in the middle list. Double-click a room or use Join / Open. Use ☆ to save a favorite.',
      placement: 'right',
      skipIfMissing: true,
      waitMs: 220
    },
    {
      selector: '#rbCustomRoomsList',
      section: 'Rooms',
      title: 'Use custom rooms',
      text: 'Custom rooms now live on the right side instead of a details card. Public custom rooms can be joined from here; private rooms show invite controls when you own them.',
      placement: 'left',
      skipIfMissing: true,
      waitMs: 220
    },
    {
      selector: '#btnOpenCreateRoom',
      section: 'Rooms',
      title: 'Create your own room',
      text: 'Create Room opens the cleaner custom-room form. Public rooms appear in the custom list; private rooms are invite-only; every created room automatically moves you into it so the creator can start chatting right away.',
      placement: 'left',
      skipIfMissing: true,
      waitMs: 220
    },
    {
      selector: '#roomEmbedTitle',
      section: 'Chat',
      title: 'Your active room',
      text: 'After you join a room, the live conversation opens here. This step is skipped unless a room is already active.',
      placement: 'right',
      skipIfMissing: true,
      waitMs: 180
    },
    {
      selector: '#roomEmbedInput',
      section: 'Chat',
      title: 'Send a room message',
      text: 'Type your message here. The nearby buttons add emoji, GIFs, torrent/file shares, and room voice tools when available.',
      placement: 'top',
      skipIfMissing: true,
      waitMs: 180
    },
    {
      selector: '#meStatus',
      section: 'Account',
      title: 'Set your presence',
      text: 'Set yourself Online, Away, Busy, or Invisible so other users understand whether you are available.',
      placement: 'left'
    },
    {
      selector: '#meAvatar',
      section: 'Account',
      title: 'Open your profile',
      text: 'Your avatar and username open your profile controls. Use them for your avatar, banner, intro, favorites, and posts.',
      placement: 'left',
      before: () => { try { setActiveTab('friends'); } catch {} }
    },
    {
      selector: '.dockMenuBtn[data-dock-menu="account"]',
      section: 'Hub',
      title: 'Use the hub menu bar',
      text: 'The Account, People, View, and Help menus collect account actions, friend tools, display options, and tour controls.',
      placement: 'left',
      before: () => { try { showDockMenu(document.querySelector('.dockMenuBtn[data-dock-menu="account"]'), 'account'); } catch {} },
      after: () => { try { hideDockMenu(); } catch {} },
      waitMs: 900
    },
    {
      selector: '#dockSearch',
      section: 'Hub',
      title: 'Search the hub',
      text: 'This box filters whichever hub tab is open, so you can quickly find friends, groups, invites, and requests.',
      placement: 'left'
    },
    {
      selector: '#friendsSectionList',
      section: 'Friends',
      title: 'Friends and private messages',
      text: 'Your friends list stays here. Open private chats from friend rows and use the row controls for quick actions.',
      placement: 'left',
      before: () => { try { setActiveTab('friends'); } catch {} }
    },
    {
      selector: '#dockAlertRail',
      section: 'Alerts',
      title: 'Alert bubbles',
      text: 'Important activity uses these side bubbles, including missed private messages, friend requests, group invites, and room invites.',
      placement: 'left',
      before: () => { try { setActiveTab('friends'); closeDockRailPanel(); } catch {} }
    },
    {
      selector: '#btnSettings',
      section: 'Settings',
      title: 'Open settings when needed',
      text: 'Settings control appearance, room text size, notifications, local DM behavior, and other personal preferences.',
      placement: 'bottom',
      before: () => { try { hideDockMenu(); } catch {} try { setActiveTab('friends'); } catch {} }
    },
    {
      selector: '#btnHelpTour',
      section: 'Finish',
      title: 'Replay this guide anytime',
      text: `Use the Help button whenever you want to replay this shorter ${SERVER_NAME} tour.`,
      placement: 'bottom',
      before: () => { try { closeSettings(); } catch {} try { hideDockMenu(); } catch {} try { setActiveTab('friends'); } catch {} }
    }
  ];
}

function clearHelpTargetHighlight() {
  try {
    document.querySelectorAll('.ecHelpTarget').forEach((el) => el.classList.remove('ecHelpTarget'));
  } catch {}
}

function closeHelpOverlay(opts = {}) {
  const markSeen = !!opts.markSeen;
  const layer = ensureHelpLayer();
  clearTimeout(EC_HELP.hoverTimer);
  EC_HELP.hoverTarget = null;
  cancelHelpCloseTimer();
  if (EC_HELP.positionRaf) {
    cancelAnimationFrame(EC_HELP.positionRaf);
    EC_HELP.positionRaf = 0;
  }
  EC_HELP.pointerInsideCard = false;
  EC_HELP.targetHover = false;
  EC_HELP.targetFocus = false;
  clearHelpTargetHighlight();
  clearHelpSpotlight();
  if (EC_HELP.currentStep?.after) {
    try { EC_HELP.currentStep.after(); } catch {}
  }
  EC_HELP.currentStep = null;
  EC_HELP.currentTarget = null;
  EC_HELP.visible = false;
  EC_HELP.mode = '';
  layer.classList.add('hidden');
  layer.classList.remove('isTour', 'isHint');
  if (markSeen) markHelpTourSeenForCurrentAccount();
}

function clearHelpSpotlight() {
  const layer = EC_HELP.layer || document.getElementById('ecHelpLayer');
  if (!layer) return;
  layer.style.removeProperty('--ec-help-spot-x');
  layer.style.removeProperty('--ec-help-spot-y');
  layer.style.removeProperty('--ec-help-spot-r');
  layer.style.removeProperty('--ec-help-spot-radius');
}

function updateHelpSpotlightFromRect(rect) {
  const layer = ensureHelpLayer();
  if (!layer || !rect) return;
  const cx = rect.left + (rect.width / 2);
  const cy = rect.top + (rect.height / 2);
  const radius = Math.max(72, Math.min(190, Math.max(rect.width, rect.height) * 0.76));
  const corner = Math.max(12, Math.min(28, Math.round(Math.min(rect.width, rect.height) * 0.28)));
  layer.style.setProperty('--ec-help-spot-x', `${Math.round(cx)}px`);
  layer.style.setProperty('--ec-help-spot-y', `${Math.round(cy)}px`);
  layer.style.setProperty('--ec-help-spot-r', `${Math.round(radius)}px`);
  layer.style.setProperty('--ec-help-spot-radius', `${corner}px`);
}

function getHelpCardPreferredPlacement(targetRect, cardWidth, cardHeight, preferred = 'right') {
  const vw = window.innerWidth || document.documentElement.clientWidth || 1280;
  const vh = window.innerHeight || document.documentElement.clientHeight || 720;
  const gap = 22;
  const margin = 16;
  const plans = [];
  const pushPlan = (placement, left, top) => plans.push({ placement, left, top });

  pushPlan('right', targetRect.right + gap, targetRect.top + Math.max(-6, (targetRect.height - cardHeight) / 2));
  pushPlan('left', targetRect.left - cardWidth - gap, targetRect.top + Math.max(-6, (targetRect.height - cardHeight) / 2));
  pushPlan('bottom', targetRect.left + (targetRect.width - cardWidth) / 2, targetRect.bottom + gap);
  pushPlan('top', targetRect.left + (targetRect.width - cardWidth) / 2, targetRect.top - cardHeight - gap);

  const ordered = [preferred, 'right', 'left', 'bottom', 'top'].filter((v, i, arr) => arr.indexOf(v) === i);
  const candidates = ordered.map((placement) => plans.find((p) => p.placement === placement)).filter(Boolean);

  for (const plan of candidates) {
    const left = Math.min(Math.max(plan.left, margin), vw - cardWidth - margin);
    const top = Math.min(Math.max(plan.top, margin), vh - cardHeight - margin);
    const fits = left >= margin && top >= margin && left + cardWidth <= vw - margin && top + cardHeight <= vh - margin;
    if (fits) return { placement: plan.placement, left, top };
  }

  const fallback = candidates[0] || { placement: 'right', left: margin, top: margin };
  return {
    placement: fallback.placement,
    left: Math.min(Math.max(fallback.left, margin), vw - cardWidth - margin),
    top: Math.min(Math.max(fallback.top, margin), vh - cardHeight - margin)
  };
}

function drawHelpArrow(cardRect, targetRect, placement) {
  const svg = EC_HELP.svg;
  const path = EC_HELP.arrow;
  const head = EC_HELP.arrowHead;
  if (!svg || !path || !head) return;

  const vw = window.innerWidth || document.documentElement.clientWidth || 1280;
  const vh = window.innerHeight || document.documentElement.clientHeight || 720;
  svg.setAttribute('viewBox', `0 0 ${vw} ${vh}`);
  svg.setAttribute('width', String(vw));
  svg.setAttribute('height', String(vh));

  const targetX = targetRect.left + targetRect.width / 2;
  const targetY = targetRect.top + targetRect.height / 2;
  let startX = cardRect.left + cardRect.width / 2;
  let startY = cardRect.top + cardRect.height / 2;

  if (placement === 'right') {
    startX = cardRect.left;
    startY = cardRect.top + Math.min(cardRect.height - 26, Math.max(28, cardRect.height * 0.45));
  } else if (placement === 'left') {
    startX = cardRect.right;
    startY = cardRect.top + Math.min(cardRect.height - 26, Math.max(28, cardRect.height * 0.45));
  } else if (placement === 'top') {
    startX = cardRect.left + Math.min(cardRect.width - 28, Math.max(28, cardRect.width * 0.50));
    startY = cardRect.bottom;
  } else {
    startX = cardRect.left + Math.min(cardRect.width - 28, Math.max(28, cardRect.width * 0.50));
    startY = cardRect.top;
  }

  const dx = targetX - startX;
  const dy = targetY - startY;
  const curveLift = placement === 'left' ? -70 : placement === 'right' ? 70 : (dy > 0 ? 70 : -70);
  const controlX = startX + dx * 0.48 + (placement === 'top' || placement === 'bottom' ? curveLift : 0);
  const controlY = startY + dy * 0.48 - (placement === 'left' || placement === 'right' ? 80 : 0);
  path.setAttribute('d', `M ${startX} ${startY} Q ${controlX} ${controlY} ${targetX} ${targetY}`);

  const angle = Math.atan2(targetY - controlY, targetX - controlX);
  const headLen = 12;
  const a1 = angle - Math.PI / 7;
  const a2 = angle + Math.PI / 7;
  const x1 = targetX - Math.cos(a1) * headLen;
  const y1 = targetY - Math.sin(a1) * headLen;
  const x2 = targetX - Math.cos(a2) * headLen;
  const y2 = targetY - Math.sin(a2) * headLen;
  head.setAttribute('d', `M ${x1} ${y1} L ${targetX} ${targetY} L ${x2} ${y2}`);
}

function positionHelpCard(target, placement = 'right') {
  const layer = ensureHelpLayer();
  const card = EC_HELP.card;
  if (!target || !card || !layer) return;
  card.style.left = '-9999px';
  card.style.top = '-9999px';
  card.style.visibility = 'hidden';
  layer.classList.remove('hidden');

  const targetRect = target.getBoundingClientRect();
  updateHelpSpotlightFromRect(targetRect);
  const cardRectSeed = card.getBoundingClientRect();
  const width = Math.max(280, Math.min(360, cardRectSeed.width || 320));
  card.style.width = `${width}px`;
  const measured = card.getBoundingClientRect();
  const pos = getHelpCardPreferredPlacement(targetRect, measured.width || width, measured.height || 180, placement);
  card.style.left = `${pos.left}px`;
  card.style.top = `${pos.top}px`;
  card.style.visibility = 'visible';
  const cardRect = card.getBoundingClientRect();
  drawHelpArrow(cardRect, targetRect, pos.placement);
}

function showHelpForElement(target, opts = {}) {
  const layer = ensureHelpLayer();
  if (!target || !isElementActuallyVisible(target)) return;
  cancelHelpCloseTimer();
  clearHelpTargetHighlight();
  EC_HELP.currentTarget = target;
  target.classList.add('ecHelpTarget');
  EC_HELP.mode = opts.mode || 'hint';
  EC_HELP.visible = true;
  layer.classList.remove('hidden');
  layer.classList.toggle('isTour', EC_HELP.mode === 'tour');
  layer.classList.toggle('isHint', EC_HELP.mode !== 'tour');

  const sectionLabel = String(opts.section || '').trim();
  if (EC_HELP.badge) EC_HELP.badge.textContent = EC_HELP.mode === 'tour'
    ? `${SERVER_NAME} tour${sectionLabel ? ` · ${sectionLabel}` : ''}`
    : 'Tip';
  if (EC_HELP.title) EC_HELP.title.textContent = String(opts.title || target.dataset.helpTitle || SERVER_NAME);
  if (EC_HELP.body) EC_HELP.body.textContent = String(opts.text || target.dataset.helpText || '');

  const total = Number(opts.total || 0);
  const stepNum = Number(opts.step || 0);
  const progressPct = (EC_HELP.mode === 'tour' && total > 0) ? Math.max(0, Math.min(100, (stepNum / total) * 100)) : 0;
  if (EC_HELP.step) EC_HELP.step.textContent = (EC_HELP.mode === 'tour' && total > 0) ? `Step ${stepNum} of ${total}` : 'Hover or focus controls for quick tips.';
  if (EC_HELP.advanceHint) {
    EC_HELP.advanceHint.style.display = EC_HELP.mode === 'tour' ? '' : 'none';
    const demoAdvance = opts.demoAdvanceText || '';
    EC_HELP.advanceHint.textContent = (EC_HELP.mode === 'tour' && stepNum >= total)
      ? 'Click Done to finish the tour'
      : (demoAdvance || 'Click this guide card to continue');
  }
  if (EC_HELP.progressTrack) EC_HELP.progressTrack.style.display = EC_HELP.mode === 'tour' ? '' : 'none';
  if (EC_HELP.progressFill) EC_HELP.progressFill.style.width = `${progressPct}%`;
  if (EC_HELP.prevBtn) EC_HELP.prevBtn.style.display = EC_HELP.mode === 'tour' ? '' : 'none';
  if (EC_HELP.nextBtn) EC_HELP.nextBtn.style.display = EC_HELP.mode === 'tour' ? '' : 'none';
  if (EC_HELP.doneBtn) EC_HELP.doneBtn.style.display = EC_HELP.mode === 'tour' ? '' : 'none';
  if (EC_HELP.muteBtn) EC_HELP.muteBtn.style.display = EC_HELP.mode === 'tour' ? 'none' : '';
  if (EC_HELP.closeBtn) EC_HELP.closeBtn.style.display = '';
  if (EC_HELP.prevBtn) EC_HELP.prevBtn.disabled = !(EC_HELP.mode === 'tour' && stepNum > 1);
  if (EC_HELP.nextBtn) EC_HELP.nextBtn.style.display = (EC_HELP.mode === 'tour' && stepNum < total) ? '' : 'none';
  if (EC_HELP.doneBtn) EC_HELP.doneBtn.style.display = (EC_HELP.mode === 'tour' && stepNum >= total) ? '' : (EC_HELP.mode === 'tour' ? 'none' : 'none');

  positionHelpCard(target, opts.placement || target.dataset.helpPlacement || 'right');
}

function showHelpTourStep(index, direction = 1) {
  const steps = EC_HELP.steps || [];
  if (!steps.length) {
    closeHelpOverlay({ markSeen: true });
    return;
  }
  let idx = Number(index || 0);
  if (idx < 0) idx = 0;
  if (idx >= steps.length) {
    closeHelpOverlay({ markSeen: true });
    return;
  }

  const step = steps[idx];
  EC_HELP.tourIndex = idx;
  EC_HELP.currentStep = step;
  try { step.before?.(); } catch {}
  showHelpTourStepWhenReady(step, idx, direction);
}

function showHelpTourStepWhenReady(step, idx, direction, attempt = 0) {
  requestAnimationFrame(() => {
    requestAnimationFrame(async () => {
      if (EC_HELP.mode !== 'tour' || EC_HELP.tourIndex !== idx || EC_HELP.currentStep !== step) return;
      const isOptionalStep = !!step.skipIfMissing;
      const timeoutMs = isOptionalStep ? Math.max(80, Math.min(Number(step.waitMs || 220), 450)) : (step.waitMs || 1800);
      const target = await waitForVisibleHelpTarget(step.selector, { timeoutMs, intervalMs: step.waitIntervalMs || 90 });
      if (EC_HELP.mode !== 'tour' || EC_HELP.tourIndex !== idx || EC_HELP.currentStep !== step) return;
      if (!target) {
        if (isOptionalStep) {
          stepHelpTour(direction || 1, true);
          return;
        }
        if (attempt < HELP_TOUR_TARGET_RETRY_MAX) {
          setTimeout(() => showHelpTourStepWhenReady(step, idx, direction, attempt + 1), 90);
          return;
        }
        stepHelpTour(direction || 1, true);
        return;
      }
      try {
        target.scrollIntoView({ block: 'nearest', inline: 'nearest', behavior: 'smooth' });
      } catch {}
      if (EC_HELP.mode !== 'tour' || EC_HELP.tourIndex !== idx || EC_HELP.currentStep !== step) return;
      showHelpForElement(target, {
        mode: 'tour',
        title: step.title,
        text: step.text,
        placement: step.placement,
        step: idx + 1,
        total: (EC_HELP.steps || []).length,
        section: step.section || '',
        demoAdvanceText: step.demoAdvanceText || ''
      });
    });
  });
}

function stepHelpTour(delta = 1, fromSkip = false) {
  const steps = EC_HELP.steps || [];
  if (!steps.length) {
    closeHelpOverlay({ markSeen: true });
    return;
  }
  if (EC_HELP.currentStep?.after) {
    try { EC_HELP.currentStep.after(); } catch {}
  }
  const next = Number(EC_HELP.tourIndex || 0) + Number(delta || 1);
  if (next < 0) {
    showHelpTourStep(0, delta);
    return;
  }
  if (next >= steps.length) {
    closeHelpOverlay({ markSeen: true });
    return;
  }
  if (fromSkip && next === EC_HELP.tourIndex) {
    closeHelpOverlay({ markSeen: true });
    return;
  }
  showHelpTourStep(next, delta);
}

function startHelpTour(opts = {}) {
  ensureHelpLayer();
  EC_HELP.steps = buildHelpTourSteps();
  if (!EC_HELP.steps.length) return;
  EC_HELP.mode = 'tour';
  EC_HELP.visible = true;
  EC_HELP.autoStarted = !!opts.auto;
  showHelpTourStep(0);
}

function maybeAutoStartHelpTour() {
  if (!helpHintsEnabled()) return;
  if (hasSeenHelpTourForCurrentAccount()) return;
  setTimeout(() => {
    if (EC_HELP.visible || EC_HELP.mode === 'tour') return;
    startHelpTour({ auto: true });
  }, HELP_TOUR_AUTO_DELAY_MS);
}

function refreshActiveHelpPosition() {
  if (!EC_HELP.visible || !EC_HELP.currentTarget) return;
  if (!isElementActuallyVisible(EC_HELP.currentTarget)) {
    if (EC_HELP.mode === 'tour') stepHelpTour(1, true);
    else closeHelpOverlay({ markSeen: false });
    return;
  }
  const placement = (EC_HELP.mode === 'tour' ? EC_HELP.currentStep?.placement : EC_HELP.currentTarget.dataset.helpPlacement) || 'right';
  positionHelpCard(EC_HELP.currentTarget, placement);
}

function initHelpSystem() {
  if (EC_HELP.initialized) return;
  if (document.body?.dataset?.ecHelpSystemBound === '1') { EC_HELP.initialized = true; return; }
  EC_HELP.initialized = true;
  if (document.body) document.body.dataset.ecHelpSystemBound = '1';
  ensureHelpLayer();
  initHelpMetadata();
  window.addEventListener('resize', scheduleHelpPositionRefresh);
  window.addEventListener('scroll', scheduleHelpPositionRefresh, true);
  document.addEventListener('pointerdown', (e) => {
    if (EC_HELP.mode === 'tour' || !EC_HELP.visible) return;
    const t = e.target;
    const insideCard = !!(EC_HELP.card && t && EC_HELP.card.contains(t));
    const insideTarget = !!(EC_HELP.currentTarget && t && EC_HELP.currentTarget.contains(t));
    if (!insideCard && !insideTarget) closeHelpOverlay({ markSeen: false });
  }, true);
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && EC_HELP.visible) {
      e.preventDefault();
      closeHelpOverlay({ markSeen: EC_HELP.mode === 'tour' });
      return;
    }
    if (EC_HELP.mode !== 'tour') return;
    if (e.key === 'ArrowRight' || e.key === 'Enter') {
      e.preventDefault();
      stepHelpTour(1);
    } else if (e.key === 'ArrowLeft') {
      e.preventDefault();
      stepHelpTour(-1);
    }
  });

  EC_HELP.observer = new MutationObserver(() => initHelpMetadata());
  EC_HELP.observer.observe(document.body || document.documentElement, { childList: true, subtree: true });
}
