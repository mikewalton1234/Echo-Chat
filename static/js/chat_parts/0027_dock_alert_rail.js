function setDockBadge(id, count, title = '') {
  const el = $(id);
  if (!el) return;
  const n = Number(count || 0);
  const safe = Number.isFinite(n) ? n : 0;
  el.textContent = String(safe);
  if (title) el.title = title;
}

function getDockAlertPanelSummary(panel = 'missed') {
  const missedTotals = (typeof ecGetMissedPmTotals === 'function')
    ? ecGetMissedPmTotals()
    : {
        threads: Array.isArray(UIState.missedPmSummary) ? UIState.missedPmSummary.length : 0,
        total: Array.isArray(UIState.missedPmSummary) ? UIState.missedPmSummary.reduce((sum, it) => sum + (Number(it?.count || 0) || 0), 0) : 0,
      };
  const missedThreads = Number(missedTotals.threads || 0) || 0;
  const missedTotal = Number(missedTotals.total || 0) || 0;
  const pendingCount = Array.isArray(UIState.pendingRequests) ? UIState.pendingRequests.length : 0;
  const groupAlertCount = Array.isArray(UIState.groupInvites) ? UIState.groupInvites.length : 0;
  const roomAlertCount = Array.isArray(UIState.roomInvites) ? UIState.roomInvites.length : 0;
  const webcamRequestCount = Array.isArray(UIState.webcamRequests) ? UIState.webcamRequests.length : 0;
  const profilePostNotificationCount = Array.isArray(UIState.profilePostNotifications) ? UIState.profilePostNotifications.length : 0;
  const alertCount = groupAlertCount + roomAlertCount + webcamRequestCount + profilePostNotificationCount;

  switch (String(panel || 'missed')) {
    case 'pending':
      return {
        title: 'Pending friends',
        meta: pendingCount > 0
          ? `${pendingCount} incoming friend request${pendingCount === 1 ? '' : 's'}`
          : 'No incoming friend requests'
      };
    case 'alerts':
      return {
        title: 'Important notifications',
        meta: alertCount > 0
          ? `${alertCount} important notification${alertCount === 1 ? '' : 's'} waiting`
          : 'No important notifications right now'
      };
    case 'missed':
    default:
      return {
        title: 'Missed messages',
        meta: missedTotal > 0
          ? `${missedTotal} unread message${missedTotal === 1 ? '' : 's'} across ${missedThreads} conversation${missedThreads === 1 ? '' : 's'}`
          : 'No missed private messages'
      };
  }
}

function syncDockAlertFlyoutMeta(panel = null) {
  const activePanel = String(panel || document.querySelector('.dockAlertBubble.isActive')?.dataset.railPanel || 'missed');
  const meta = getDockAlertPanelSummary(activePanel);
  const titleEl = $('dockAlertFlyoutTitle');
  const metaEl = $('dockAlertFlyoutMeta');
  if (titleEl) titleEl.textContent = meta.title;
  if (metaEl) metaEl.textContent = meta.meta;
}

function getDockAlertActivityTotals() {
  const stateMissedTotal = (typeof ecGetMissedPmTotals === 'function')
    ? (Number(ecGetMissedPmTotals().total || 0) || 0)
    : (Array.isArray(UIState.missedPmSummary) ? UIState.missedPmSummary.reduce((sum, it) => sum + (Number(it?.count || 0) || 0), 0) : 0);
  const badgeMissedTotal = Number($('railMissedCount')?.textContent || 0) || 0;
  const missedTotal = Math.max(0, stateMissedTotal, badgeMissedTotal);
  const pendingTotal = Array.isArray(UIState.pendingRequests) ? UIState.pendingRequests.length : 0;
  const alertsTotal = (Array.isArray(UIState.groupInvites) ? UIState.groupInvites.length : 0) + (Array.isArray(UIState.roomInvites) ? UIState.roomInvites.length : 0) + (Array.isArray(UIState.webcamRequests) ? UIState.webcamRequests.length : 0) + (Array.isArray(UIState.profilePostNotifications) ? UIState.profilePostNotifications.length : 0);
  return {
    missedTotal,
    pendingTotal,
    alertsTotal,
    hasActivity: (missedTotal + pendingTotal + alertsTotal) > 0,
  };
}

function updateDockAlertRailPresentation() {
  const rail = $('dockAlertRail');
  if (!rail) return;
  const flyout = $('dockAlertFlyout');
  let flyoutOpen = !!(flyout && !flyout.classList.contains('hidden'));
  let activePanel = String(document.querySelector('.dockAlertBubble.isActive')?.dataset?.railPanel || '');
  const totals = getDockAlertActivityTotals();
  const byPanel = {
    missed: totals.missedTotal,
    pending: totals.pendingTotal,
    alerts: totals.alertsTotal,
  };
  try { if (typeof ecMissedDebug === 'function') ecMissedDebug('rail.presentation.start', { totals, flyoutOpen, activePanel, byPanel }); } catch {}

  if (flyoutOpen && activePanel && Number(byPanel[activePanel] || 0) <= 0) {
    try { flyout.classList.add('hidden'); } catch {}
    document.querySelectorAll('.dockAlertBubble.isActive').forEach((btn) => btn.classList.remove('isActive'));
    flyoutOpen = false;
    activePanel = '';
  }

  let anyPeeked = false;
  document.querySelectorAll('.dockAlertBubble[data-rail-panel]').forEach((btn) => {
    const panel = String(btn.dataset.railPanel || '');
    const count = Number(byPanel[panel] || 0);
    const isCurrent = (flyoutOpen && activePanel === panel) || btn.classList.contains('isActive');
    const shouldPeek = count > 0 || isCurrent;
    const shouldAlert = count > 0;
    btn.classList.toggle('isPeeked', shouldPeek);
    btn.classList.toggle('isAlerting', shouldAlert || isCurrent);
    btn.classList.toggle('isCollapsed', !shouldPeek);
    btn.setAttribute('aria-hidden', shouldPeek ? 'false' : 'true');
    anyPeeked = anyPeeked || shouldPeek;
  });

  rail.classList.toggle('hasPeekedBubble', anyPeeked);
  rail.classList.toggle('isCollapsed', !anyPeeked && !flyoutOpen);

  const dock = rail.closest('.dock');
  if (dock) {
    // beta.403: no wide edge mask. The physical CSS lip handles the overlap
    // without covering the hub search/profile text.
    dock.classList.remove('hasDockAlertMask');
  }
  try {
    if (typeof ecMissedDebug === 'function') ecMissedDebug('rail.presentation.done', { anyPeeked, flyoutOpen, activePanel, totals });
    if (totals.missedTotal > 0 && typeof ecRepairMissedBubblePaintPath === 'function') {
      setTimeout(() => { try { ecRepairMissedBubblePaintPath('rail_presentation'); } catch {} }, 80);
    }
  } catch {}
}
