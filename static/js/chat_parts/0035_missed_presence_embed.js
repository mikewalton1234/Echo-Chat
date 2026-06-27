// Missed (offline) PM notifications
// - Only counts messages received while you were offline.
// - Clicking an item opens the DM window and pulls all currently missed PMs
//   from that sender (ciphertext-only from the server).
// ───────────────────────────────────────────────────────────────────────────────
let MISSED_SUMMARY_TOAST_ARMED = false;

/**
 * Apply a local delta to the missed PM summary list and re-render immediately.
 * This keeps the UI responsive while we wait for the server to push the updated summary.
 */
function consumeMissedPmLocal(sender, consumedCount) {
  if (!sender) return;
  const n = Number(consumedCount || 0) || 0;
  if (n <= 0) return;

  const list = Array.isArray(UIState.missedPmSummary) ? UIState.missedPmSummary.slice() : [];
  let changed = false;

  const next = [];
  for (const it of list) {
    if (!it || it.sender !== sender) {
      next.push(it);
      continue;
    }
    const cur = Number(it.count ?? 0) || 0;
    const remaining = Math.max(0, cur - n);
    changed = true;
    if (remaining > 0) next.push({ ...it, count: remaining });
    // if remaining == 0, drop the entry
  }

  if (changed) {
    UIState.missedPmSummary = next;
    renderMissedPmList(next);
  }
}

function dropMissedEntryLocal(sender) {
  if (!sender) return;
  const list = Array.isArray(UIState.missedPmSummary) ? UIState.missedPmSummary : [];
  const next = list.filter((it) => it && it.sender !== sender);
  if (next.length !== list.length) {
    UIState.missedPmSummary = next;
    renderMissedPmList(next);
  }
}

function removePendingRequestLocal(fromUser) {
  if (!fromUser) return;
  const list = Array.isArray(UIState.pendingRequests) ? UIState.pendingRequests : [];
  const next = list.filter((it) => String(it || '') !== String(fromUser || ''));
  if (next.length !== list.length) {
    UIState.pendingRequests = next;
    renderPendingFriendRequestsInto($("pendingRequestsList"), next);
    renderPendingFriendRequestsInto($("railPendingRequestsList"), next);
    updateDockSummaryCounts();
    try { if (rbHasUI()) rbRenderRoomLists(); } catch {}
  }
}

function closeDockRailPanelIfEmpty(panel = '') {
  const wanted = String(panel || '').trim();
  if (!wanted) return;
  const flyout = $('dockAlertFlyout');
  if (!flyout || flyout.classList.contains('hidden')) return;
  const active = String(document.querySelector('.dockAlertBubble.isActive')?.dataset?.railPanel || '');
  if (active !== wanted) return;
  const totals = getDockAlertActivityTotals();
  const remaining = wanted === 'missed'
    ? totals.missedTotal
    : (wanted === 'pending' ? totals.pendingTotal : totals.alertsTotal);
  if (Number(remaining || 0) <= 0) closeDockRailPanel();
}

function getMissedCountFor(sender) {
  const list = Array.isArray(UIState.missedPmSummary) ? UIState.missedPmSummary : [];
  for (const it of list) {
    if (it && it.sender === sender) return Number(it.count ?? 0) || 0;
  }
  return 0;
}

function queuePendingOfflineDm(peer, msg) {
  if (!peer || !msg) return false;
  const id = Number(msg.id || 0) || 0;
  if (id > 0) {
    if (UIState.pendingOfflineDmSeen.has(id)) return true;
    UIState.pendingOfflineDmSeen.add(id);
  }
  const cur = UIState.pendingOfflineDm.get(peer) || [];
  cur.push({
    id: id || null,
    cipher: msg.cipher,
    ts: (typeof msg.ts === "number") ? msg.ts : null,
    needsAck: !!msg.needsAck
  });
  // Keep it bounded per peer to avoid runaway memory.
  UIState.pendingOfflineDm.set(peer, cur.slice(-200));
  return true;
}

async function ackOfflinePmIds(ids, { quiet = true } = {}) {
  const clean = Array.from(new Set((Array.isArray(ids) ? ids : [])
    .map((x) => Number(x) || 0)
    .filter((x) => x > 0)))
    .slice(0, 1000);
  if (!clean.length || !socket) return { success: true, updated: 0, requested: 0 };

  const res = await new Promise((resolve) => {
    try {
      socket.emit("ack_offline_pms", { ids: clean }, (r) => resolve((r && typeof r === 'object') ? r : null));
    } catch (e) {
      resolve({ success: false, error: String(e?.message || e || 'ack_failed') });
    }
  });

  if (!res || !res.success) {
    if (!quiet) toast(`⚠️ Could not acknowledge missed PMs: ${res?.error || 'server did not respond'}`, "warn", 3600);
    try { socket.emit("get_missed_pm_summary"); } catch {}
    return res || { success: false, error: 'no_response' };
  }

  try { socket.emit("get_missed_pm_summary"); } catch {}
  return { ...res, requested: Number(res.requested ?? clean.length) || clean.length };
}

function normalizeMissedPmSummaryItems(items) {
  const merged = new Map();
  for (const raw of Array.isArray(items) ? items : []) {
    const sender = String(raw?.sender || '').trim();
    const key = sender.toLowerCase();
    const count = Math.max(0, Number(raw?.count ?? 0) || 0);
    if (!sender || !key || count <= 0) continue;
    const lastTs = (typeof raw?.last_ts === 'number' && Number.isFinite(raw.last_ts)) ? raw.last_ts : null;
    const prev = merged.get(key);
    if (!prev) {
      merged.set(key, { sender, count, last_ts: lastTs });
    } else {
      prev.count += count;
      if (lastTs !== null && (prev.last_ts === null || lastTs > prev.last_ts)) prev.last_ts = lastTs;
    }
  }
  return Array.from(merged.values()).sort((a, b) => {
    const bt = (typeof b.last_ts === 'number') ? b.last_ts : 0;
    const at = (typeof a.last_ts === 'number') ? a.last_ts : 0;
    if (bt !== at) return bt - at;
    return String(a.sender).localeCompare(String(b.sender));
  });
}

async function flushPendingOfflineDm(peer = null) {
  // Only attempt if we have a key.
  if (!window.myPrivateCryptoKey) return;
  const peers = peer ? [peer] : Array.from(UIState.pendingOfflineDm.keys());
  for (const p of peers) {
    const pending = UIState.pendingOfflineDm.get(p) || [];
    if (!pending.length) continue;

    const win = ecGetPmWindow(p);
    let processed = 0;
    const keep = [];
    const ackIds = [];
    for (const m of pending) {
      try {
        const cipher = m?.cipher;
        if (!cipher) continue;

        let plaintext;
        if (typeof cipher === "string" && cipher.startsWith(PM_PLAINTEXT_PREFIX) && DM_PLAINTEXT_COMPAT_ALLOWED) {
          plaintext = unwrapPlainDm(cipher);
        } else if (typeof cipher === "string" && cipher.startsWith(PM_ENVELOPE_PREFIX)) {
          plaintext = await decryptHybridEnvelope(window.myPrivateCryptoKey, cipher);
        } else {
          plaintext = await decryptLegacyRSA(window.myPrivateCryptoKey, cipher);
        }

        const payload = parseDmPayload(plaintext);
        if (win) appendDmPayload(win, `${p}:`, payload, { peer: p, direction: "in", ts: m?.ts });

        const histText = (payload.kind === "file")
          ? `📎 ${payload.name} (${humanBytes(payload.size)})`
          : (payload.kind === "torrent")
            ? `🧲 ${payload?.t?.name || payload?.t?.infohash || "Torrent"}`
            : payload.text;

        addPmHistory(p, "in", histText, m?.ts);
        processed += 1;
        const mid = Number(m?.id || 0) || 0;
        if (mid > 0) ackIds.push(mid);
      } catch (e) {
        keep.push(m);
      }
    }

    if (keep.length) UIState.pendingOfflineDm.set(p, keep);
    else UIState.pendingOfflineDm.delete(p);

    // Persist backlog changes so refresh won't lose ciphertext that is still locked.
    try { persistOfflineDmBacklog(); } catch {}

    if (ackIds.length) {
      const ack = await ackOfflinePmIds(ackIds, { quiet: true });
      if (ack?.success) {
        consumeMissedPmLocal(p, Number(ack.requested ?? ackIds.length) || ackIds.length);
        closeDockRailPanelIfEmpty('missed');
      }
    }

    if (processed) toast(`🔓 Decrypted ${processed} pending PM(s) from ${p}`, "ok", 2200);
  }
}

async function consumeOfflinePmsForPeer(peer, { promptUnlock = false, quiet = false } = {}) {
  if (!peer) return;
  if (!socket) return;

  const existing = UIState.consumingOfflinePeerPromises.get(peer);
  if (existing) {
    try {
      await existing;
      if (promptUnlock && !window.myPrivateCryptoKey) {
        try { await ensurePrivateKeyUnlocked(); } catch {}
      }
      if (window.myPrivateCryptoKey) {
        try { await flushPendingOfflineDm(peer); } catch {}
      }
    } finally {
      try { socket.emit("get_missed_pm_summary"); } catch {}
    }
    return;
  }

  UIState.consumingOfflinePeers.add(peer);

  const job = (async () => {
    // Fetch with peek=true, then explicitly ACK only after each ciphertext is
    // either rendered or safely copied into the local encrypted backlog.
    const res = await new Promise((resolve) => {
      try {
        socket.emit("fetch_offline_pms", { from_user: peer, peek: true }, (r) => resolve(r));
      } catch (e) {
        resolve(null);
      }
    });

    if (!res || !res.success) {
      if (!quiet) toast(`❌ ${res?.error || "Failed to fetch offline PMs"}`, "error");
      try { socket.emit("get_missed_pm_summary"); } catch {}
      return;
    }

    const msgs = Array.isArray(res.messages) ? res.messages : [];
    if (!msgs.length) {
      // Server may already have cleared the summary; still re-sync.
      try { socket.emit("get_missed_pm_summary"); } catch {}
      return;
    }

    // Ensure DM window exists, but do not trigger a second background consume.
    const win = ecGetPmWindow(peer) || openPrivateChat(peer, { consumeOffline: false });
    if (win) ensureDmHistoryRendered(win, peer);

    let privKey = window.myPrivateCryptoKey;
    if (!privKey && promptUnlock) {
      try { privKey = await ensurePrivateKeyUnlocked(); } catch { privKey = null; }
    }

    let processed = 0;
    let queued = 0;
    const ackIds = [];
    const queuedAckIds = [];

    for (const m of msgs) {
      const cipher = m?.cipher;
      const msgId = m?.id;
      const ts = (typeof m?.ts === "number") ? m.ts : null;
      if (!cipher || !msgId) continue;

      // Prevent duplicate processing if the server delivers the same IDs again.
      const mid = Number(msgId) || 0;
      if (mid > 0 && UIState.pendingOfflineDmSeen.has(mid)) {
        ackIds.push(mid);
        continue;
      }

      try {
        let plaintext;

        if (typeof cipher === "string" && cipher.startsWith(PM_PLAINTEXT_PREFIX) && DM_PLAINTEXT_COMPAT_ALLOWED) {
          plaintext = unwrapPlainDm(cipher);
        } else {
          if (!privKey) throw new Error("dm_locked");
          if (typeof cipher === "string" && cipher.startsWith(PM_ENVELOPE_PREFIX)) {
            plaintext = await decryptHybridEnvelope(privKey, cipher);
          } else {
            plaintext = await decryptLegacyRSA(privKey, cipher);
          }
        }

        const payload = parseDmPayload(plaintext);
        if (win) appendDmPayload(win, `${peer}:`, payload, { peer, direction: "in", ts });

        const histText = (payload.kind === "file")
          ? `📎 ${payload.name} (${humanBytes(payload.size)})`
          : (payload.kind === "torrent")
            ? `🧲 ${payload?.t?.name || payload?.t?.infohash || "Torrent"}`
            : payload.text;

        addPmHistory(peer, "in", histText, ts);
        processed += 1;
        if (mid > 0) {
          UIState.pendingOfflineDmSeen.add(mid);
          ackIds.push(mid);
        }
      } catch (e) {
        queued += 1;
        queuePendingOfflineDm(peer, { id: msgId, cipher, ts, needsAck: true });
        if (mid > 0) queuedAckIds.push(mid);
        if (win) {
          appendLine(win, "System:", "Missed message saved. Sign out and sign back in if private messages are not showing.", "system");
        }
      }
    }

    // Persist ciphertext backlog so refresh won't lose queued items.
    const backlogPersisted = persistOfflineDmBacklog();

    if (backlogPersisted && queuedAckIds.length) {
      ackIds.push(...queuedAckIds);
    }

    if (ackIds.length) {
      const ack = await ackOfflinePmIds(ackIds, { quiet });
      if (ack?.success) {
        consumeMissedPmLocal(peer, Number(ack.requested ?? ackIds.length) || ackIds.length);
        closeDockRailPanelIfEmpty('missed');
      }
    }

    // If we have a key now, decrypt anything that was queued.
    if (window.myPrivateCryptoKey) {
      try { await flushPendingOfflineDm(peer); } catch {}
    }

    if (!quiet) {
      if (processed) toast(`📥 Loaded ${processed} missed PM(s) from ${peer}`, "ok");
      if (queued) {
        const note = backlogPersisted
          ? `${queued} missed PM(s) saved locally until private messages unlock.`
          : `${queued} missed PM(s) kept on the server because local browser storage was unavailable.`;
        toast(note, backlogPersisted ? "info" : "warn", 4200);
      }
    }
  })();

  UIState.consumingOfflinePeerPromises.set(peer, job);

  try {
    await job;
  } finally {
    UIState.consumingOfflinePeers.delete(peer);
    UIState.consumingOfflinePeerPromises.delete(peer);
    // Always re-sync; server is source of truth.
    try { socket.emit("get_missed_pm_summary"); } catch {}
  }
}

function renderMissedPmListInto(ul, items) {
  if (!ul) return;
  ecClearNode(ul);

  const list = Array.isArray(items) ? items : [];
  if (!list.length) {
    ul.appendChild(ecListStatusItem({ name: 'empty', dot: 'offline', avatar: '✉', text: 'No missed messages' }));
    return;
  }

  for (const it of list) {
    const sender = it?.sender;
    const count = Number(it?.count ?? 0) || 0;
    if (!sender || count <= 0) continue;

    const p = UIState.presence.get(sender);
    const online = (p && typeof p === 'object') ? !!p.online : !!p;
    const presence = (p && typeof p === 'object') ? (p.presence || (online ? 'online' : 'offline')) : (online ? 'online' : 'offline');

    const li = document.createElement('li');
    li.dataset.name = sender;
    li.dataset.search = `${sender} missed ${count} ${presence}`;
    li.classList.add('isInteractive');

    const left = document.createElement('div');
    left.className = 'liLeft';
    const dotState = online ? ((presence === 'busy') ? 'busy' : ((presence === 'away') ? 'away' : 'online')) : 'offline';
    createDockIdentity(left, {
      name: sender,
      presenceClass: dotState,
      meta: `${count} unread message${count === 1 ? '' : 's'}`
    });

    const badge = document.createElement('span');
    badge.className = 'liBadge';
    badge.textContent = String(count);

    const actions = document.createElement('div');
    actions.className = 'liActions';
    const openBtn = document.createElement('button');
    openBtn.className = 'iconBtn';
    openBtn.title = 'Open messages';
    openBtn.textContent = '💬';
    openBtn.onclick = (ev) => { ev.stopPropagation(); openMissedPmFrom(sender); };
    actions.appendChild(openBtn);

    li.appendChild(left);
    li.appendChild(badge);
    li.appendChild(actions);

    li.onclick = () => {
      selectBuddyRow(sender, 'missed', li);
      openMissedPmFrom(sender);
    };
    li.ondblclick = () => openMissedPmFrom(sender);
    li.oncontextmenu = (ev) => {
      selectBuddyRow(sender, 'missed', li);
      showUserContextMenu(ev, sender, { source: 'missed' });
    };

    ul.appendChild(li);
  }
}

function renderMissedPmList(items) {
  renderMissedPmListInto($('missedPmList'), items);
  renderMissedPmListInto($('railMissedPmList'), items);
  updateDockSummaryCounts();
  try { if (rbHasUI()) rbRenderRoomLists(); } catch {}
}

function ecNormalizeSocialName(name) {
  return String(name || '').trim().toLowerCase();
}

function ecBlockedAlertCleanupMatcher(peer = '') {
  const explicitPeer = ecNormalizeSocialName(peer);
  const blockedKeys = new Set();
  try {
    if (UIState.blockedSet instanceof Set) {
      UIState.blockedSet.forEach((name) => {
        const key = ecNormalizeSocialName(name);
        if (key) blockedKeys.add(key);
      });
    }
  } catch (_) {}
  return (candidate) => {
    const key = ecNormalizeSocialName(candidate);
    if (!key) return false;
    return (!!explicitPeer && key === explicitPeer) || blockedKeys.has(key);
  };
}

function cleanupBlockedPairAlerts(peer = '', opts = {}) {
  const isBlockedPeer = ecBlockedAlertCleanupMatcher(peer);
  let changedMissed = false;
  let changedPending = false;
  let changedGroups = false;
  let changedRooms = false;

  const missed = Array.isArray(UIState.missedPmSummary) ? UIState.missedPmSummary : [];
  const nextMissed = missed.filter((it) => !isBlockedPeer(it?.sender));
  changedMissed = nextMissed.length !== missed.length;
  if (changedMissed) {
    UIState.missedPmSummary = nextMissed;
    renderMissedPmList(nextMissed);
    closeDockRailPanelIfEmpty('missed');
  }

  try {
    const peers = Array.from(UIState.pendingOfflineDm?.keys?.() || []);
    peers.forEach((name) => {
      if (isBlockedPeer(name)) clearOfflineDmBacklog(name);
    });
  } catch (_) {}

  const pending = Array.isArray(UIState.pendingRequests) ? UIState.pendingRequests : [];
  const nextPending = pending.filter((name) => !isBlockedPeer(name));
  changedPending = nextPending.length !== pending.length;
  if (changedPending) {
    UIState.pendingRequests = nextPending;
    renderPendingFriendRequestsInto($('pendingRequestsList'), nextPending);
    renderPendingFriendRequestsInto($('railPendingRequestsList'), nextPending);
    closeDockRailPanelIfEmpty('pending');
  }

  const groupInvites = Array.isArray(UIState.groupInvites) ? UIState.groupInvites : [];
  const nextGroupInvites = groupInvites.filter((inv) => !isBlockedPeer(inv?.from_user || inv?.fromUser || inv?.by));
  changedGroups = nextGroupInvites.length !== groupInvites.length;
  if (changedGroups) UIState.groupInvites = nextGroupInvites;

  const roomInvites = Array.isArray(UIState.roomInvites) ? UIState.roomInvites : [];
  const nextRoomInvites = roomInvites.filter((inv) => !isBlockedPeer(inv?.by || inv?.from_user || inv?.invited_by));
  changedRooms = nextRoomInvites.length !== roomInvites.length;
  if (changedRooms) UIState.roomInvites = nextRoomInvites;

  if (changedGroups || changedRooms) {
    try { renderGroupInviteListInto($('groupInviteList'), UIState.groupInvites); } catch (_) {}
    try { renderAlertsInviteListInto($('railAlertsList'), UIState.groupInvites, UIState.roomInvites, { openRail: true }); } catch (_) {}
    closeDockRailPanelIfEmpty('alerts');
  }

  if (changedMissed || changedPending || changedGroups || changedRooms) {
    updateDockSummaryCounts();
    try { if (rbHasUI()) rbRenderRoomLists(); } catch (_) {}
  }

  if (opts.refresh !== false) {
    try { socket.emit('get_missed_pm_summary'); } catch (_) {}
    try { refreshGroupInvites(); } catch (_) {}
    try { refreshRoomInvites(); } catch (_) {}
    try { refreshCustomRoomInvites(); } catch (_) {}
  }
}

async function openMissedPmFrom(sender) {
  if (!sender) return;

  // User explicitly clicked a missed entry: open the DM and then load/ACK missed PMs.
  // We do NOT optimistically clear the UI until the consume/ACK actually happens.
  closeDockRailPanel();

  openPrivateChat(sender, { consumeOffline: false });
  await consumeOfflinePmsForPeer(sender, { promptUnlock: true, quiet: false });
}

// Server can push updated friends list at any time (e.g., friend accepted).
socket.on("friends_list", (friends) => {
  try {
    if (Array.isArray(friends)) updateFriendsListUI(friends);
  } catch (e) {}
});

function renderPendingFriendRequestsInto(ul, requests) {
  if (!ul) return;
  ecClearNode(ul);

  if (!requests || requests.length === 0) {
    ul.appendChild(ecListStatusItem({ name: 'none', dot: 'offline', avatar: '?', text: 'None' }));
    return;
  }

  requests.forEach(from_user => {
    const li = document.createElement("li");
    li.dataset.name = from_user;
    li.dataset.search = `${from_user} request friend invite`;
    li.title = `Friend request from ${from_user}`;
    li.setAttribute('aria-label', `Friend request from ${from_user}`);
    li.classList.add('isInteractive', 'pendingRequestItem');

    const left = document.createElement("div");
    left.className = "liLeft";
    createDockIdentity(left, {
      name: from_user,
      presenceClass: 'offline',
      meta: `Friend request from ${from_user}`,
      chip: 'New'
    });

    const actions = document.createElement("div");
    actions.className = "liActions";

    const yes = document.createElement("button");
    yes.className = "iconBtn";
    yes.textContent = "✅";
    yes.title = "Accept";
    yes.onclick = (ev) => {
      ev.stopPropagation();
      removePendingRequestLocal(from_user);
      closeDockRailPanelIfEmpty('pending');
      socket.emit("accept_friend_request", { from_user }, (res) => {
        if (res?.success) {
          toast("✅ Friend request accepted", "ok");
          closeDockRailPanelIfEmpty('pending');
        } else {
          toast(`❌ ${res?.error || 'Could not accept request'}`, "error");
        }
        getPendingFriendRequests();
        getFriends();
      });
    };

    const no = document.createElement("button");
    no.className = "iconBtn";
    no.textContent = "✖";
    no.title = "Reject";
    no.onclick = (ev) => {
      ev.stopPropagation();
      removePendingRequestLocal(from_user);
      closeDockRailPanelIfEmpty('pending');
      socket.emit("reject_friend_request", { from_user }, (res) => {
        if (res?.success) {
          toast("Rejected", "warn");
          closeDockRailPanelIfEmpty('pending');
        } else {
          toast(`❌ ${res?.error || 'Could not reject request'}`, "error");
        }
        getPendingFriendRequests();
      });
    };

    actions.appendChild(yes);
    actions.appendChild(no);

    li.appendChild(left);
    li.appendChild(actions);
    li.onclick = () => {
      selectBuddyRow(from_user, 'pending', li);
      openProfileWindow(from_user);
    };
    li.oncontextmenu = (ev) => {
      selectBuddyRow(from_user, 'pending', li);
      showUserContextMenu(ev, from_user, { source: 'pending' });
    };
    ul.appendChild(li);
  });
}

socket.on("pending_friend_requests", (requests) => {
  UIState.pendingRequests = Array.isArray(requests) ? requests.slice() : [];
  renderPendingFriendRequestsInto($("pendingRequestsList"), UIState.pendingRequests);
  renderPendingFriendRequestsInto($("railPendingRequestsList"), UIState.pendingRequests);
  updateDockSummaryCounts();
  try { if (rbHasUI()) rbRenderRoomLists(); } catch {}
});

socket.on("blocked_users_list", (users) => {
  const canonicalBlockedUsers = [];
  const seenBlocked = new Set();
  (Array.isArray(users) ? users : []).forEach((name) => {
    const clean = String(name || '').trim();
    if (!clean) return;
    const key = clean.toLowerCase();
    if (seenBlocked.has(key)) return;
    seenBlocked.add(key);
    canonicalBlockedUsers.push(clean);
  });
  UIState.blockedUsersCache = canonicalBlockedUsers.slice();
  try { UIState.blockedSet = new Set(canonicalBlockedUsers); } catch { UIState.blockedSet = new Set(); }
  cleanupBlockedPairAlerts('', { refresh: false });
  const blockedCountEl = $("blockedUsersCount");
  if (blockedCountEl) blockedCountEl.textContent = String(canonicalBlockedUsers.length);
  const ul = $("blockedUsersList");
  if (!ul) return;
  ecClearNode(ul);

  if (!canonicalBlockedUsers.length) {
    UIState.blockedSet = new Set();
    ul.appendChild(ecListStatusItem({ name: 'none', dot: 'offline', avatar: '-', text: 'None' }));
    updateDockSummaryCounts();
    try { if (rbHasUI()) rbRenderRoomLists(); } catch {}
    return;
  }

  canonicalBlockedUsers.forEach(u => {
    const li = document.createElement("li");
    li.dataset.name = u;
    li.dataset.search = `${u} blocked`;

    const left = document.createElement("div");
    left.className = "liLeft";
    createDockIdentity(left, {
      name: u,
      presenceClass: 'busy',
      meta: 'Blocked contact',
      chip: 'Blocked'
    });

    const actions = document.createElement("div");
    actions.className = "liActions";

    const unblock = document.createElement("button");
    unblock.className = "iconBtn";
    unblock.textContent = "↩";
    unblock.title = "Unblock";
    unblock.onclick = (ev) => {
      ev.stopPropagation();
      socket.emit("unblock_user", { blocked: u }, (res) => {
        const canonicalBlocked = String(res?.blocked || u).trim() || u;
        toast(res?.success ? `Unblocked ${canonicalBlocked}` : `❌ ${res?.error || 'Unblock failed'}`, res?.success ? "ok" : "error");
        getFriends();
        getPendingFriendRequests();
        getBlockedUsers();
      });
    };

    actions.appendChild(unblock);

    li.appendChild(left);
    li.appendChild(actions);
    li.onclick = () => selectBuddyRow(u, 'blocked', li);
    li.oncontextmenu = (ev) => {
      selectBuddyRow(u, 'blocked', li);
      showUserContextMenu(ev, u, { source: 'blocked' });
    };
    ul.appendChild(li);
  });

  updateDockSummaryCounts();
});

socket.on("social_alert_cleanup", (payload = {}) => {
  const peer = String(payload?.peer || payload?.username || '').trim();
  cleanupBlockedPairAlerts(peer, { refresh: true });
});

// Presence updates (server addition; falls back gracefully if not present)
socket.on("friends_presence", (payload) => {
  if (!payload || !Array.isArray(payload)) return;
  UIState.presence.clear();
  payload.forEach((row) => {
    if (!row) return;
    if (typeof row === "string") {
      UIState.presence.set(row, { online: false, presence: "offline", custom_status: "", last_seen: null });
      return;
    }
    if (!row.username) return;
    const online = !!row.online;
    const presence = row.presence || (online ? "online" : "offline");
    const custom_status = row.custom_status || "";
    const last_seen = row.last_seen || null;
    const avatar_url = row.avatar_url || row.avatarUrl || "";
    UIState.presence.set(row.username, { online, presence, custom_status, last_seen, avatar_url });
  });
  // Refresh UI using the current list if available
  getFriends();
});

socket.on("friend_presence_update", (p) => {
  if (!p || !p.username) return;
  const online = !!p.online;
  const presence = p.presence || (online ? "online" : "offline");
  const custom_status = p.custom_status || "";
  const last_seen = p.last_seen || null;
  const avatar_url = p.avatar_url || p.avatarUrl || "";
  UIState.presence.set(p.username, { online, presence, custom_status, last_seen, avatar_url });
  getFriends();
});

socket.on('my_profile', (p) => {
  if (!p || typeof p !== 'object') return;
  UIState.myProfile = p;
  renderMyHubIdentity(p);
});

socket.on("my_presence", (p) => {
  if (!p) return;
  const sel = $("meStatus");
  if (sel && p.presence) {
    sel.value = p.presence;
    try {
      const autoAwayEcho = !!window.__ec_autoAwayActive && p.presence === "away";
      const autoOfflineEcho = !!window.__ec_autoOfflineActive && p.presence === "invisible";
      if (!autoAwayEcho && !autoOfflineEcho) {
        window.__ym_lastPresence = p.presence;
        window.__ec_manualPresence = p.presence;
      }
      if (p.presence !== "away") {
        window.__ec_autoAwayActive = false;
      }
      if (p.presence !== "invisible") {
        window.__ec_autoOfflineActive = false;
      }
    } catch (_) {}
  }
  try {
    window.__ym_lastCustomStatus = (p.custom_status || "");
    const disp = $("meCustomDisplay");
    if (disp) {
      const t = (p.custom_status || "").trim();
      disp.textContent = t ? `“${t}”` : "";
      disp.style.display = t ? "block" : "none";
    }
  } catch (_) {}
});

// ───────────────────────────────────────────────────────────────────────────────

// ───────────────────────────────────────────────────────────────────────────────
// Embedded room pane (left side)
// ───────────────────────────────────────────────────────────────────────────────
function getRoomEmbedEl() {
  const el = $("roomEmbed");
  if (!el) return null;
  if (!el._ym) {
    el._ym = {
      titleEl: $("roomEmbedTitle"),
      log: $("roomEmbedLog"),
      input: $("roomEmbedInput"),
      emojiBtn: $("roomEmbedEmojiBtn"),
      send: $("roomEmbedSend"),
      torrentBtn: $("roomEmbedTorrentBtn"),
      gifBtn: $("roomEmbedGifBtn"),
      torrentInput: $("roomEmbedTorrentInput"),
      mediaRail: $("roomEmbedMediaRail"),
      mediaTitle: $("roomEmbedMediaTitle"),
      mediaMeta: $("roomEmbedMediaMeta"),
      mediaStations: $("roomEmbedMediaStations"),
      mediaFrame: $("roomEmbedMediaFrame"),
      mediaPlayerBtn: $("btnRoomEmbedMediaPlayer"),
      mediaOpenBtn: $("btnRoomEmbedMediaOpen"),
      mediaHideBtn: $("btnRoomEmbedMediaHide"),
      mediaSkipBtn: $("btnRoomEmbedMediaSkip"),
      mediaVoteStatus: $("roomEmbedMediaVoteStatus"),
      mediaMuteBtn: $("btnRoomEmbedMediaMute"),
      mediaDuckChk: $("chkRoomEmbedMediaDuck"),
      mediaVolume: $("roomEmbedMediaVolume"),
      mediaVolumeLabel: $("roomEmbedMediaVolumeLabel"),
      mediaVolumeHint: $("roomEmbedMediaVolumeHint")
    };
    disableOutputContextMenu(el._ym.log);
  }
  return el;
}

function rbPopoutElements() {
  return {
    root: $('roomBrowserPopout'),
    body: $('roomBrowserPopoutBody'),
    closeBtn: $('btnRoomBrowserPopoutClose'),
    toggleBtn: $('btnRoomBrowserPopout'),
    placeholder: $('sitePlaceholder'),
    slot: $('sitePlaceholderSlot'),
    siteArea: $('siteArea'),
    roomEmbed: $('roomEmbed'),
  };
}

function rbSyncHomeSlotState() {
  const { slot } = rbPopoutElements();
  if (!slot) return;
  const shouldHideSlot = !!UIState.roomEmbedRoom;
  slot.classList.toggle('hidden', shouldHideSlot);
}

function rbSyncOverlayState() {
  const { root, placeholder, siteArea, roomEmbed } = rbPopoutElements();
  const overlayOpen = !!ROOM_BROWSER.popoutOpen && !!UIState.roomEmbedRoom;
  if (siteArea) siteArea.classList.toggle('room-browser-overlay-open', overlayOpen);
  if (roomEmbed) roomEmbed.classList.toggle('is-underlay', overlayOpen);
  if (root) root.classList.toggle('is-room-overlay', overlayOpen);
  if (placeholder) placeholder.classList.toggle('is-room-overlay', overlayOpen);
  rbSyncHomeSlotState();
}

function rbRestorePlaceholderHome() {
  const { placeholder, slot } = rbPopoutElements();
  if (!placeholder || !slot) return;
  if (placeholder.parentElement !== slot) slot.appendChild(placeholder);
  placeholder.classList.remove('is-popout');
  placeholder.classList.remove('is-room-overlay');
  rbSyncHomeSlotState();
}


function rbRoomBrowserOverlayIsOpen() {
  try {
    return !!(ROOM_BROWSER && ROOM_BROWSER.popoutOpen && UIState && UIState.roomEmbedRoom);
  } catch (e) {
    return false;
  }
}

function rbClosePopoutAfterRoomChoice() {
  if (!rbRoomBrowserOverlayIsOpen()) return;
  try { rbClosePopout({ keepHidden: true }); } catch (e) {}
}

function rbClosePopout(opts = {}) {
  const keepHidden = !!opts.keepHidden;
  if (opts.resetSearches !== false) {
    try { resetRoomBrowserSearchBarsAfterClose(); } catch (e) {}
  }
  const { root, placeholder, toggleBtn } = rbPopoutElements();
  ROOM_BROWSER.popoutOpen = false;
  if (root) root.classList.add('hidden');
  rbRestorePlaceholderHome();
  if (placeholder) {
    if (keepHidden && UIState.roomEmbedRoom) placeholder.classList.add('hidden');
    else placeholder.classList.remove('hidden');
  }
  if (toggleBtn) {
    toggleBtn.classList.remove('active');
    toggleBtn.setAttribute('aria-expanded', 'false');
    toggleBtn.textContent = 'Rooms';
  }
  rbSyncOverlayState();
}

function rbOpenPopout() {
  const { root, body, placeholder, toggleBtn } = rbPopoutElements();
  if (!root || !body || !placeholder || !UIState.roomEmbedRoom) return;
  ROOM_BROWSER.popoutOpen = true;
  if (placeholder.parentElement !== body) body.appendChild(placeholder);
  placeholder.classList.remove('hidden');
  placeholder.classList.add('is-popout');
  root.classList.remove('hidden');
  if (toggleBtn) {
    toggleBtn.classList.add('active');
    toggleBtn.setAttribute('aria-expanded', 'true');
    toggleBtn.textContent = 'Hide rooms';
  }
  rbSyncOverlayState();
}

function rbTogglePopout(force) {
  if (!UIState.roomEmbedRoom) return;
  const wantsOpen = typeof force === 'boolean' ? force : !ROOM_BROWSER.popoutOpen;
  if (wantsOpen) rbOpenPopout();
  else rbClosePopout({ keepHidden: true });
}

function bindRoomBrowserPopoutUi() {
  const { root, closeBtn, toggleBtn } = rbPopoutElements();
  if (toggleBtn && !toggleBtn.dataset.boundRoomBrowserPopout) {
    toggleBtn.dataset.boundRoomBrowserPopout = '1';
    toggleBtn.setAttribute('aria-haspopup', 'dialog');
    toggleBtn.setAttribute('aria-expanded', 'false');
    toggleBtn.addEventListener('click', () => rbTogglePopout());
  }
  if (closeBtn && !closeBtn.dataset.boundRoomBrowserPopout) {
    closeBtn.dataset.boundRoomBrowserPopout = '1';
    closeBtn.addEventListener('click', () => rbClosePopout({ keepHidden: true }));
  }
  if (root && !root.dataset.boundRoomBrowserPopout) {
    root.dataset.boundRoomBrowserPopout = '1';
    root.addEventListener('mousedown', (ev) => {
      if (ev.target === root) rbClosePopout({ keepHidden: true });
    });
  }
  if (!window.__rbPopoutEscBound) {
    window.__rbPopoutEscBound = true;
    window.addEventListener('keydown', (ev) => {
      if (ev.key === 'Escape' && ROOM_BROWSER.popoutOpen) rbClosePopout({ keepHidden: true });
    });
  }
}

function showRoomEmbed(room) {
  const pane = getRoomEmbedEl();
  const ph = $("sitePlaceholder");
  const slot = $("sitePlaceholderSlot");
  if (!pane) return null;

  bindRoomBrowserPopoutUi();
  const previousRoom = String(UIState.roomEmbedRoom || '').trim();
  const nextRoom = String(room || '').trim();
  if (previousRoom && previousRoom !== nextRoom && typeof roomMediaStopLocalPlayback === 'function') {
    try { roomMediaStopLocalPlayback(previousRoom, { hideRail: true, heartbeat: true }); } catch {}
  }
  UIState.roomEmbedRoom = room || null;

  if (room) {
    if (!ROOM_BROWSER.popoutOpen) ph?.classList.add("hidden");
    else ph?.classList.remove('hidden');
    slot?.classList.add('hidden');
    pane.classList.remove("hidden");
    if (pane._ym?.titleEl) pane._ym.titleEl.textContent = `Room — ${room}`;
  } else {
    rbClosePopout({ keepHidden: false });
    pane.classList.add("hidden");
    ph?.classList.remove("hidden");
    slot?.classList.remove('hidden');
    if (pane._ym?.titleEl) pane._ym.titleEl.textContent = "Room —";
  }

  rbSyncOverlayState();
  return pane;
}
