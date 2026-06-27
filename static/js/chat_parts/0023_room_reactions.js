// ───────────────────────────────────────────────────────────────────────────────
// Message reactions (rooms)
// ───────────────────────────────────────────────────────────────────────────────
const DEFAULT_REACTION_EMOJIS = ["👍", "👎", "😂", "❤️", "😮"]; // fast common set

function _ensureMsgIndex(viewEl) {
  if (!viewEl) return;
  if (!viewEl._ym) viewEl._ym = {};
  if (!viewEl._ym.msgIndex) viewEl._ym.msgIndex = new Map();
  if (!viewEl._ym.myReactions) viewEl._ym.myReactions = new Map(); // message_id -> emoji (current user)
}

function _findMsgEl(viewEl, messageId) {
  _ensureMsgIndex(viewEl);
  return viewEl._ym.msgIndex.get(messageId) || null;
}


function _removeRoomMessage(viewEl, messageId, reason) {
  if (!viewEl || !messageId) return false;
  _ensureMsgIndex(viewEl);
  const msgEl = _findMsgEl(viewEl, messageId);
  if (!msgEl) {
    try { viewEl._ym?.msgIndex?.delete(messageId); } catch {}
    try { viewEl._ym?.myReactions?.delete(messageId); } catch {}
    return false;
  }
  try { clearTimeout(Number(msgEl._ecExpiryTimer || 0)); } catch {}
  try { viewEl._ym?.msgIndex?.delete(messageId); } catch {}
  try { viewEl._ym?.myReactions?.delete(messageId); } catch {}
  if (viewEl?._ym?.pinnedMessageId === messageId) {
    viewEl._ym.pinnedMessageId = null;
  }
  msgEl.classList.add("ec-msgItem--expired");
  msgEl.setAttribute("data-expired-reason", String(reason || "expired"));
  msgEl.remove();
  return true;
}

function _parseRoomMessageExpiresAt(payload) {
  const raw = payload?.expires_at || payload?.expiresAt || null;
  if (raw === null || raw === undefined || raw === "") return 0;
  if (typeof raw === "number" && Number.isFinite(raw)) {
    return raw > 100000000000 ? raw : raw * 1000;
  }
  const n = Number(raw);
  if (Number.isFinite(n) && n > 0) return n > 100000000000 ? n : n * 1000;
  const parsed = Date.parse(String(raw));
  return Number.isFinite(parsed) ? parsed : 0;
}

function _scheduleRoomMessageExpiry(viewEl, messageId, payload) {
  const msgEl = _findMsgEl(viewEl, messageId);
  if (!msgEl) return;
  const expMs = _parseRoomMessageExpiresAt(payload);
  if (!expMs) return;
  msgEl.dataset.expiresAt = String(expMs);
  const delay = expMs - Date.now();
  if (delay <= 0) {
    _removeRoomMessage(viewEl, messageId, "expired");
    return;
  }
  try { clearTimeout(Number(msgEl._ecExpiryTimer || 0)); } catch {}
  msgEl._ecExpiryTimer = setTimeout(() => {
    _removeRoomMessage(viewEl, messageId, "expired");
  }, Math.min(delay, 2147483647));
}

function _getMyReaction(viewEl, messageId) {
  _ensureMsgIndex(viewEl);
  return viewEl?._ym?.myReactions?.get(messageId) || null;
}

function _setMyReaction(viewEl, messageId, emojiOrNull) {
  _ensureMsgIndex(viewEl);
  if (!viewEl?._ym?.myReactions) return;

  if (emojiOrNull) viewEl._ym.myReactions.set(messageId, emojiOrNull);
  else viewEl._ym.myReactions.delete(messageId);

  const msgEl = _findMsgEl(viewEl, messageId);
  if (!msgEl) return;
  msgEl.querySelectorAll(".reactBtn").forEach((b) => {
    b.classList.toggle("active", (b.dataset?.emoji || b.textContent) === emojiOrNull);
  });
}

function _lockReactions(viewEl, messageId) {
  const msgEl = _findMsgEl(viewEl, messageId);
  if (!msgEl) return;
  msgEl.classList.add("rxLocked");
  msgEl.querySelectorAll(".reactBtn").forEach((b) => {
    b.disabled = true;
    b.classList.add("disabled");
  });
}

function _setRoomPinnedMessage(viewEl, messageId, pinPayload) {
  _ensureMsgIndex(viewEl);
  if (!viewEl?._ym) return;
  const currentPinned = viewEl._ym.pinnedMessageId || null;
  if (currentPinned && currentPinned !== messageId) {
    const oldEl = _findMsgEl(viewEl, currentPinned);
    if (oldEl) {
      oldEl.classList.remove("ec-msgItem--pinned");
      oldEl.querySelector(".ecRoomPinBadge")?.remove();
      oldEl.querySelectorAll(".pinRoomBtn").forEach((b) => { b.textContent = "📌 Pin"; });
    }
  }
  viewEl._ym.pinnedMessageId = messageId || null;
  const msgEl = _findMsgEl(viewEl, messageId);
  if (!msgEl) return;
  msgEl.classList.add("ec-msgItem--pinned");
  let badge = msgEl.querySelector(".ecRoomPinBadge");
  if (!badge) {
    badge = document.createElement("span");
    badge.className = "ecRoomPinBadge";
    badge.setAttribute("aria-label", "Pinned room message");
    const content = msgEl.querySelector(".ec-msgContent") || msgEl;
    content.prepend(badge);
  }
  const by = String(pinPayload?.pinned_by || "").trim();
  badge.textContent = by ? `📌 Pinned by ${by}` : "📌 Pinned";
  msgEl.querySelectorAll(".pinRoomBtn").forEach((b) => { b.textContent = "📌 Pinned"; });
}

function _clearRoomPinnedMessage(viewEl, messageId) {
  _ensureMsgIndex(viewEl);
  if (!viewEl?._ym) return;
  if (messageId && viewEl._ym.pinnedMessageId && viewEl._ym.pinnedMessageId !== messageId) return;
  const oldId = messageId || viewEl._ym.pinnedMessageId;
  viewEl._ym.pinnedMessageId = null;
  const msgEl = _findMsgEl(viewEl, oldId);
  if (!msgEl) return;
  msgEl.classList.remove("ec-msgItem--pinned");
  msgEl.querySelector(".ecRoomPinBadge")?.remove();
  msgEl.querySelectorAll(".pinRoomBtn").forEach((b) => { b.textContent = "📌 Pin"; });
}

function _sendRoomPin(viewEl, room, messageId) {
  if (!room || !messageId) return;
  socket.emit("pin_message", { room, message_id: messageId }, (res) => {
    if (!res?.success) return toast(`❌ ${res?.error || "Pin failed"}`, "error");
    _setRoomPinnedMessage(viewEl, messageId, res?.pin || res);
    toast("📌 Message pinned", "ok");
  });
}

function _sendRoomUnpin(viewEl, room, messageId) {
  if (!room || !messageId) return;
  socket.emit("unpin_message", { room, message_id: messageId }, (res) => {
    if (!res?.success) return toast(`❌ ${res?.error || "Unpin failed"}`, "error");
    _clearRoomPinnedMessage(viewEl, messageId);
    toast("📌 Message unpinned", "ok");
  });
}

function _renderReactionPills(container, counts) {
  if (!container) return;
  container.replaceChildren();
  if (!counts) return;

  // Stable ordering: show default emojis first, then any others the server sends.
  const keys = Object.keys(counts);
  const ordered = [
    ...DEFAULT_REACTION_EMOJIS.filter(e => keys.includes(e)),
    ...keys.filter(e => !DEFAULT_REACTION_EMOJIS.includes(e)).sort()
  ];

  ordered.forEach((emoji) => {
    const n = counts[emoji];
    if (!n) return;
    const pill = document.createElement("span");
    pill.className = "reactPill";
    pill.textContent = `${emoji} ${n}`;
    container.appendChild(pill);
  });
}

function _sendReaction(viewEl, room, messageId, emoji) {
  if (!room || !messageId || !emoji) return;

  // Enforce "final reaction" client-side: once you react, it is locked.
  const current = _getMyReaction(viewEl, messageId);
  if (current) {
    toast("🔒 Reaction is final. You can’t change or undo it.", "warn");
    return;
  }

  socket.emit("react_to_message", { room, message_id: messageId, emoji }, (res) => {
    if (!res?.success) {
      if (res?.counts) {
        const msgEl = _findMsgEl(viewEl, messageId);
        const rx = msgEl?.querySelector(".msgReactions");
        if (rx) _renderReactionPills(rx, res.counts);
      }
      if (res?.current) {
        _setMyReaction(viewEl, messageId, res.current);
        _lockReactions(viewEl, messageId);
      }
      toast(`❌ ${res?.error || "Reaction failed"}`, "error");
      return;
    }

    // Track my selected emoji for UI highlighting.
    _setMyReaction(viewEl, messageId, res?.current || emoji);
    _lockReactions(viewEl, messageId);

    // Fast-path update (server also broadcasts message_reactions).
    const msgEl = _findMsgEl(viewEl, messageId);
    if (msgEl) {
      const rx = msgEl.querySelector(".msgReactions");
      if (rx && res?.counts) _renderReactionPills(rx, res.counts);
    }
  });
}

function appendRoomMessage(viewEl, payload) {
  const log = viewEl?._ym?.log;
  if (!log) return;

  const username = payload?.username || "";
  const message = payload?.message ?? "";
  const room = payload?.room || UIState.currentRoom || null;
  const tsMs = normalizeChatTs(payload?.timestamp || payload?.ts || payload?.created_at || payload?.createdAt);

  const messageId = payload?.message_id || payload?.messageId || payload?.id || `local-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  _ensureMsgIndex(viewEl);

  const group = getOrCreateChatGroup(log, username ? String(username) : "?", tsMs, { variant: "room", context: "room" });
  if (!group?.itemsEl) return;

  const item = document.createElement("div");
  item.className = "ec-msgItem ec-msgItem--room";
  item.dataset.msgid = messageId;

  // Content
  const contentWrap = document.createElement("div");
  contentWrap.className = "ec-msgContent";

  let _ecObj = null;
  if (typeof message === "string" && message.startsWith("{")) {
    try { _ecObj = JSON.parse(message); } catch { _ecObj = null; }
  }

  if (_ecObj && _ecObj._ec === "torrent") {
    const t = {
      name: String(_ecObj.name || _ecObj.file_name || "Torrent"),
      infohash: String(_ecObj.infohash || _ecObj.infohash_hex || ""),
      magnet: String(_ecObj.magnet || ""),
      total_size: Number(_ecObj.total_size || 0) || 0,
      seeds: (_ecObj.seeds === null || _ecObj.seeds === undefined) ? null : Number(_ecObj.seeds),
      leechers: (_ecObj.leechers === null || _ecObj.leechers === undefined) ? null : Number(_ecObj.leechers),
      completed: (_ecObj.completed === null || _ecObj.completed === undefined) ? null : Number(_ecObj.completed),
      trackers: Array.isArray(_ecObj.trackers) ? _ecObj.trackers.map(String) : [],
      tracker_count: Number(_ecObj.tracker_count || (Array.isArray(_ecObj.trackers) ? _ecObj.trackers.length : 0) || 0),
      declared_tracker_count: Number(_ecObj.declared_tracker_count || 0),
      tracker_source: _ecObj.tracker_source ? String(_ecObj.tracker_source) : "torrent",
      using_public_fallback_trackers: !!_ecObj.using_public_fallback_trackers,
      web_seeds: Array.isArray(_ecObj.web_seeds) ? _ecObj.web_seeds.map(String) : [],
      web_seed_count: Number(_ecObj.web_seed_count || (Array.isArray(_ecObj.web_seeds) ? _ecObj.web_seeds.length : 0) || 0),
      scrape_status: _ecObj.scrape_status ? String(_ecObj.scrape_status) : "",
      scrape_error: _ecObj.scrape_error ? String(_ecObj.scrape_error) : "",
      swarm_deferred: !!_ecObj.swarm_deferred,
      trackers_tried: Number(_ecObj.trackers_tried || 0),
      dht_queries: Number(_ecObj.dht_queries || 0),
      dht_peers_seen: Number(_ecObj.dht_peers_seen || 0),
      comment: _ecObj.comment ? String(_ecObj.comment) : "",
      created_by: _ecObj.created_by ? String(_ecObj.created_by) : "",
      creation_date: _ecObj.creation_date ? String(_ecObj.creation_date) : "",
      torrent_id: _ecObj.torrent_id ? String(_ecObj.torrent_id) : "",
      file_name: _ecObj.file_name ? String(_ecObj.file_name) : "",
      download_url: _ecObj.download_url ? String(_ecObj.download_url) : ""
    };
    contentWrap.appendChild(buildTorrentCard(t));
  } else if (_ecObj && _ecObj._ec === "room_radio") {
    const station = roomMediaHandleWire(_ecObj);
    const card = document.createElement('div');
    card.className = 'ecRoomRadioWireCard';
    const title = document.createElement('div');
    title.className = 'ecRoomRadioWireTitle';
    title.textContent = '🎵 Shared radio updated';
    const meta = document.createElement('div');
    meta.className = 'ecRoomRadioWireMeta';
    meta.textContent = `${String(_ecObj.actor || username || 'Someone')} switched this room to ${String(station?.label || 'a new station')}.`;
    card.appendChild(title);
    card.appendChild(meta);
    contentWrap.appendChild(card);
  } else if (typeof message === "string" && isMagnetText(message)) {
    const pm = parseMagnet(message);
    if (pm) {
      const t = {
        name: pm.name || "Magnet",
        infohash: pm.infohash,
        magnet: pm.magnet,
        total_size: 0,
        seeds: null,
        leechers: null,
        completed: null,
        trackers: pm.trackers || [],
        declared_tracker_count: Number(pm.declared_tracker_count || 0),
        tracker_count: Number(pm.tracker_count || (pm.trackers || []).length || 0),
        tracker_source: pm.tracker_source || (pm.using_public_fallback_trackers ? "public_fallback" : "magnet"),
        using_public_fallback_trackers: !!pm.using_public_fallback_trackers,
        swarm_deferred: true,
        web_seeds: Array.isArray(pm.web_seeds) ? pm.web_seeds : [],
        web_seed_count: Number(pm.web_seed_count || 0),
        scrape_status: "pending",
        scrape_error: "",
        trackers_tried: 0,
        comment: "",
        created_by: "",
        creation_date: "",
        download_url: ""
      };
      contentWrap.appendChild(buildTorrentCard(t));
    } else {
      contentWrap.appendChild(buildTextMessageBody(message, { autoScrollLog: log }));
    }
  } else {
    contentWrap.appendChild(buildTextMessageBody(message, { autoScrollLog: log }));
  }

  const line = document.createElement("div");
  line.className = "msgLine";

  // Reactions (rooms only)
  // Keep reactions attached to the rendered message content, not to the
  // outside message row. This makes short messages readable and prevents the
  // hover picker from stretching / bouncing the whole message block.
  const reactionWrap = document.createElement("div");
  reactionWrap.className = "msgReactionDock";

  const rx = document.createElement("div");
  rx.className = "msgReactions";
  rx.setAttribute("aria-label", "Message reactions");

  const actions = document.createElement("div");
  actions.className = "msgActions";
  actions.setAttribute("aria-label", "Add a reaction");
  DEFAULT_REACTION_EMOJIS.forEach((emoji) => {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "reactBtn";
    b.textContent = emoji;
    b.dataset.emoji = emoji;
    b.title = `React ${emoji}`;
    b.onclick = () => _sendReaction(viewEl, room, messageId, emoji);
    actions.appendChild(b);
  });

  if (window.IS_ADMIN) {
    const pinBtn = document.createElement("button");
    pinBtn.type = "button";
    pinBtn.className = "pinRoomBtn";
    pinBtn.textContent = "📌 Pin";
    pinBtn.title = "Pin this room message";
    pinBtn.onclick = () => _sendRoomPin(viewEl, room, messageId);
    actions.appendChild(pinBtn);

    const unpinBtn = document.createElement("button");
    unpinBtn.type = "button";
    unpinBtn.className = "unpinRoomBtn";
    unpinBtn.textContent = "Unpin";
    unpinBtn.title = "Unpin this room message";
    unpinBtn.onclick = () => _sendRoomUnpin(viewEl, room, messageId);
    actions.appendChild(unpinBtn);
  }

  reactionWrap.appendChild(rx);
  reactionWrap.appendChild(actions);
  contentWrap.appendChild(reactionWrap);

  line.appendChild(contentWrap);
  item.appendChild(line);

  group.itemsEl.appendChild(item);
  try { window.ecAnimateMessageOnce?.(item, 'room'); } catch {}
  viewEl._ym.msgIndex.set(messageId, item);
  _scheduleRoomMessageExpiry(viewEl, messageId, payload);

  const media = item.querySelector('img[data-ec-gif="1"]');
  if (media) media._ecScrollLog = log;
  scheduleScrollLogToBottom(log);
}

// ───────────────────────────────────────────────────────────────────────────────
