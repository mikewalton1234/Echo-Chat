function setDockAlertBubbleState(id, count, title = '') {
  const btn = $(id);
  if (!btn) return;
  const safe = Number.isFinite(Number(count)) ? Number(count) : 0;
  btn.classList.toggle('hasUnread', safe > 0);
  if (title) btn.title = title;
}

function closeDockRailPanel() {
  $('dockAlertFlyout')?.classList.add('hidden');
  document.querySelectorAll('.dockAlertBubble.isActive').forEach((btn) => btn.classList.remove('isActive'));
  updateDockAlertRailPresentation();
}

function openDockRailPanel(panel = 'missed') {
  const wanted = String(panel || 'missed');
  const flyout = $('dockAlertFlyout');
  if (!flyout) return;

  document.querySelectorAll('.dockAlertPanel[data-alert-panel]').forEach((section) => {
    section.classList.toggle('hidden', String(section.dataset.alertPanel || '') !== wanted);
  });
  document.querySelectorAll('.dockAlertBubble[data-rail-panel]').forEach((btn) => {
    btn.classList.toggle('isActive', String(btn.dataset.railPanel || '') === wanted);
  });

  syncDockAlertFlyoutMeta(wanted);
  flyout.classList.remove('hidden');
  updateDockAlertRailPresentation();

  if (wanted === 'alerts') {
    try { refreshCustomRoomInvites(); } catch {}
    try { refreshRoomInvites(); } catch {}
    try { refreshGroupInvites(); } catch {}
  }
}

function toggleDockRailPanel(panel = 'missed') {
  const wanted = String(panel || 'missed');
  const flyout = $('dockAlertFlyout');
  const active = document.querySelector('.dockAlertBubble.isActive')?.dataset?.railPanel || '';
  if (flyout && !flyout.classList.contains('hidden') && active === wanted) {
    closeDockRailPanel();
    return;
  }
  openDockRailPanel(wanted);
}

function bindDockAlertRail() {
  document.querySelectorAll('.dockAlertBubble[data-rail-panel]').forEach((btn) => {
    if (btn.dataset.alertBound === '1') return;
    btn.dataset.alertBound = '1';
    btn.addEventListener('click', (ev) => {
      try {
        ev.preventDefault();
        ev.stopPropagation();
      } catch {}
      toggleDockRailPanel(btn.dataset.railPanel || 'missed');
    });
    // Keep rail bubbles completely pinned on hover. No pointer-tracking drift.
    btn.style.setProperty('--bubble-float-x', '0px');
    btn.style.setProperty('--bubble-float-y', '0px');
    btn.addEventListener('mouseenter', () => {
      btn.style.setProperty('--bubble-float-x', '0px');
      btn.style.setProperty('--bubble-float-y', '0px');
    });
    btn.addEventListener('mousemove', () => {
      btn.style.setProperty('--bubble-float-x', '0px');
      btn.style.setProperty('--bubble-float-y', '0px');
    });
    btn.addEventListener('mouseleave', () => {
      btn.style.setProperty('--bubble-float-x', '0px');
      btn.style.setProperty('--bubble-float-y', '0px');
    });
  });

  const closeBtn = $('btnCloseDockAlertFlyout');
  if (closeBtn && closeBtn.dataset.alertBound !== '1') {
    closeBtn.dataset.alertBound = '1';
    closeBtn.addEventListener('click', () => closeDockRailPanel());
  }

  if (window.__dockAlertRailBound) return;
  window.__dockAlertRailBound = true;

  document.addEventListener('click', (ev) => {
    const rail = $('dockAlertRail');
    if (!rail) return;
    if (rail.contains(ev.target)) return;
    closeDockRailPanel();
  });

  updateDockAlertRailPresentation();

  document.addEventListener('keydown', (ev) => {
    if (ev.key === 'Escape') closeDockRailPanel();
  });
}

function updateDockSummaryCounts() {
  const missedTotals = (typeof ecGetMissedPmTotals === 'function')
    ? ecGetMissedPmTotals()
    : {
        threads: Array.isArray(UIState.missedPmSummary) ? UIState.missedPmSummary.length : 0,
        total: Array.isArray(UIState.missedPmSummary) ? UIState.missedPmSummary.reduce((sum, it) => sum + (Number(it?.count || 0) || 0), 0) : 0,
      };
  const missedThreads = Number(missedTotals.threads || 0) || 0;
  const missedTotal = Number(missedTotals.total || 0) || 0;
  const friendCount = UIState.friendSet instanceof Set ? UIState.friendSet.size : 0;
  const pendingCount = Array.isArray(UIState.pendingRequests) ? UIState.pendingRequests.length : 0;
  const blockedCount = UIState.blockedSet instanceof Set ? UIState.blockedSet.size : 0;
  const groupCount = Array.isArray(UIState.myGroups) ? UIState.myGroups.length : 0;
  const groupInviteCount = Array.isArray(UIState.groupInvites) ? UIState.groupInvites.length : 0;
  const roomInviteCount = Array.isArray(UIState.roomInvites) ? UIState.roomInvites.length : 0;
  const webcamRequestCount = Array.isArray(UIState.webcamRequests) ? UIState.webcamRequests.length : 0;
  const profilePostNotificationCount = Array.isArray(UIState.profilePostNotifications) ? UIState.profilePostNotifications.length : 0;
  const alertInviteCount = groupInviteCount + roomInviteCount + webcamRequestCount + profilePostNotificationCount;

  setDockBadge('dockMissedCount', missedTotal, `${missedThreads} conversations`);
  setDockBadge('railMissedCount', missedTotal, `${missedThreads} conversations`);
  setDockBadge('missedPmCount', missedThreads, `${missedTotal} total unread private messages`);
  setDockBadge('friendsCount', friendCount, 'Friends in your dock');
  setDockBadge('dockPendingCount', pendingCount, 'Pending inbound friend requests');
  setDockBadge('railPendingCount', pendingCount, 'Pending inbound friend requests');
  setDockBadge('pendingRequestsCount', pendingCount, 'Pending inbound friend requests');
  setDockBadge('groupListCount', groupCount, 'Groups in your dock');
  setDockBadge('railAlertsCount', alertInviteCount, 'Pending invites and profile notifications');
  setDockBadge('groupInvitesCount', alertInviteCount, 'Pending important notifications');

  setDockAlertBubbleState('railMissedBtn', missedTotal, missedTotal > 0 ? `${missedTotal} unread private message${missedTotal === 1 ? '' : 's'}` : 'Missed messages');
  try { if (typeof ecMissedDebug === 'function') ecMissedDebug('dock_counts.update', { missedThreads, missedTotal, pendingCount, alertInviteCount }); } catch {}
  setDockAlertBubbleState('railPendingBtn', pendingCount, pendingCount > 0 ? `${pendingCount} incoming friend request${pendingCount === 1 ? '' : 's'}` : 'Pending friend requests');
  setDockAlertBubbleState('railAlertsBtn', alertInviteCount, alertInviteCount > 0 ? `${alertInviteCount} important notification${alertInviteCount === 1 ? '' : 's'}` : 'Important notifications');
  updateDockAlertRailPresentation();
  try {
    if (typeof ecForceMissedBubbleVisible === 'function') {
      ecForceMissedBubbleVisible(missedTotal, { pulse: false, reason: 'dock_count_sync' });
    }
  } catch {}
  syncDockAlertFlyoutMeta();

  applyDockSearchFilter($('dockSearch')?.value || '');
}

function applyDockSearchFilter(query) {
  const q = String(query || '').trim().toLowerCase();
  const activePanelId = UIState.activeTab === 'groups' ? 'panelGroups' : 'panelFriends';
  const panel = $(activePanelId);
  if (!panel) return;

  let anyVisible = false;
  panel.querySelectorAll('.dockSection[data-filter-list]').forEach((section) => {
    const listId = section.dataset.filterList;
    const ul = $(listId);
    if (!ul) return;

    let visible = 0;
    if (listId === 'friendsList' && ul.dataset.friendGroups === '1') {
      visible = applyFriendGroupListFilter(ul, q);
    } else {
      [...ul.children].forEach((li) => {
        const placeholder = isDockPlaceholderItem(li);
        const hay = `${li.dataset?.name || ''} ${li.dataset?.search || ''} ${li.textContent || ''}`.toLowerCase();
        let show = true;
        if (q) show = !placeholder && hay.includes(q);
        li.style.display = show ? '' : 'none';
        if (show && !placeholder) visible += 1;
      });
    }

    section.classList.toggle('sectionFilteredEmpty', !!q && visible === 0);
    if ((!q && ul.children.length > 0) || visible > 0) anyVisible = true;
  });

  const empty = UIState.activeTab === 'groups' ? $('groupsSearchEmpty') : $('friendsSearchEmpty');
  if (empty) empty.classList.toggle('hidden', !q || anyVisible);
}

function setRoomUsersCount(n) {
  const el = $("roomUsersCount");
  if (!el) return;
  const v = Number(n || 0);
  el.textContent = String(isFinite(v) ? v : 0);
}
