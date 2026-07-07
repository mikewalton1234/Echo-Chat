// ───────────────────────────────────────────────────────────────────────────────
// Message reactions (rooms)
// ───────────────────────────────────────────────────────────────────────────────
const DEFAULT_REACTION_EMOJIS = ["👍", "👎", "😂", "❤️", "😮"]; // fast common set
const EC_MAX_REACTION_PILLS = 20;

function _roomMsgIdKey(messageId) {
  const key = String(messageId ?? "").trim();
  return key || "";
}

function _normalizeRoomReactionCounts(counts) {
  if (!counts || typeof counts !== "object" || Array.isArray(counts)) return {};
  const out = {};
  const keys = Object.keys(counts);
  const ordered = [
    ...DEFAULT_REACTION_EMOJIS.filter((emoji) => keys.includes(emoji)),
    ...keys.filter((emoji) => !DEFAULT_REACTION_EMOJIS.includes(emoji)).sort(),
  ];
  for (const rawEmoji of ordered) {
    if (Object.keys(out).length >= EC_MAX_REACTION_PILLS) break;
    const emoji = String(rawEmoji || "").trim();
    if (!emoji || emoji.length > 16) continue;
    const n = Math.max(0, Math.min(999, Math.floor(Number(counts[rawEmoji] || 0) || 0)));
    if (n > 0) out[emoji] = n;
  }
  return out;
}

function _storeRoomReactionCounts(viewEl, messageId, counts) {
  _ensureMsgIndex(viewEl);
  const key = _roomMsgIdKey(messageId);
  if (!key || !viewEl?._ym?.reactionCounts) return;
  const normalized = _normalizeRoomReactionCounts(counts);
  viewEl._ym.reactionCounts.set(key, normalized);
}

function _getRoomReactionCounts(viewEl, messageId) {
  _ensureMsgIndex(viewEl);
  const key = _roomMsgIdKey(messageId);
  if (!key) return {};
  return viewEl?._ym?.reactionCounts?.get(key) || {};
}

function _ensureMsgIndex(viewEl) {
  if (!viewEl) return;
  if (!viewEl._ym) viewEl._ym = {};
  if (!viewEl._ym.msgIndex) viewEl._ym.msgIndex = new Map();
  if (!viewEl._ym.myReactions) viewEl._ym.myReactions = new Map(); // message_id -> emoji (current user)
  if (!viewEl._ym.reactionCounts) viewEl._ym.reactionCounts = new Map(); // message_id -> latest counts, including early socket events
}

function _findMsgEl(viewEl, messageId) {
  _ensureMsgIndex(viewEl);
  const key = _roomMsgIdKey(messageId);
  return key ? (viewEl._ym.msgIndex.get(key) || null) : null;
}


function _removeRoomMessage(viewEl, messageId, reason) {
  const key = _roomMsgIdKey(messageId);
  if (!viewEl || !key) return false;
  _ensureMsgIndex(viewEl);
  const msgEl = _findMsgEl(viewEl, key);
  if (!msgEl) {
    try { viewEl._ym?.msgIndex?.delete(key); } catch {}
    try { viewEl._ym?.myReactions?.delete(key); } catch {}
    try { viewEl._ym?.reactionCounts?.delete(key); } catch {}
    return false;
  }
  try { clearTimeout(Number(msgEl._ecExpiryTimer || 0)); } catch {}
  try { viewEl._ym?.msgIndex?.delete(key); } catch {}
  try { viewEl._ym?.myReactions?.delete(key); } catch {}
  try { viewEl._ym?.reactionCounts?.delete(key); } catch {}
  if (_roomMsgIdKey(viewEl?._ym?.pinnedMessageId) === key) {
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
  const key = _roomMsgIdKey(messageId);
  return key ? (viewEl?._ym?.myReactions?.get(key) || null) : null;
}

function _setMyReaction(viewEl, messageId, emojiOrNull) {
  _ensureMsgIndex(viewEl);
  if (!viewEl?._ym?.myReactions) return;

  const key = _roomMsgIdKey(messageId);
  if (!key) return;
  if (emojiOrNull) viewEl._ym.myReactions.set(key, emojiOrNull);
  else viewEl._ym.myReactions.delete(key);

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
  const messageKey = _roomMsgIdKey(messageId);
  if (!messageKey) return;
  const currentPinned = _roomMsgIdKey(viewEl._ym.pinnedMessageId || null);
  if (currentPinned && currentPinned !== messageKey) {
    const oldEl = _findMsgEl(viewEl, currentPinned);
    if (oldEl) {
      oldEl.classList.remove("ec-msgItem--pinned");
      oldEl.querySelector(".ecRoomPinBadge")?.remove();
      oldEl.querySelectorAll(".pinRoomBtn").forEach((b) => { b.textContent = "📌 Pin"; });
    }
  }
  viewEl._ym.pinnedMessageId = messageKey || null;
  viewEl._ym.pinnedPayload = pinPayload ? { ...pinPayload } : null;
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
  const messageKey = _roomMsgIdKey(messageId);
  const pinnedKey = _roomMsgIdKey(viewEl._ym.pinnedMessageId);
  if (messageKey && pinnedKey && pinnedKey !== messageKey) return;
  const oldId = messageKey || pinnedKey;
  viewEl._ym.pinnedMessageId = null;
  viewEl._ym.pinnedPayload = null;
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
  const normalized = _normalizeRoomReactionCounts(counts);

  // Stable ordering: show default emojis first, then any other sanitized server emojis.
  const keys = Object.keys(normalized);
  const ordered = [
    ...DEFAULT_REACTION_EMOJIS.filter(e => keys.includes(e)),
    ...keys.filter(e => !DEFAULT_REACTION_EMOJIS.includes(e)).sort()
  ];

  ordered.forEach((emoji) => {
    const n = normalized[emoji];
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
        _storeRoomReactionCounts(viewEl, messageId, res.counts);
        const msgEl = _findMsgEl(viewEl, messageId);
        const rx = msgEl?.querySelector(".msgReactions");
        if (rx) _renderReactionPills(rx, _getRoomReactionCounts(viewEl, messageId));
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
      if (rx && res?.counts) {
        _storeRoomReactionCounts(viewEl, messageId, res.counts);
        _renderReactionPills(rx, _getRoomReactionCounts(viewEl, messageId));
      }
    }
  });
}

function appendRoomMessage(viewEl, payload) {
  const log = viewEl?._ym?.log;
  if (!log) return;

  const username = payload?.username || "";
  try {
    if (username && (payload?.avatar_url || payload?.avatarUrl)) {
      ecCacheUserAvatar(username, payload.avatar_url || payload.avatarUrl, { online: true, presence: 'online' });
    }
  } catch {}
  if (typeof ecRoomShouldHideBlockedSender === "function" && ecRoomShouldHideBlockedSender(username)) return null;
  const message = payload?.message ?? "";
  const room = payload?.room || UIState.currentRoom || null;
  const tsMs = normalizeChatTs(payload?.timestamp || payload?.ts || payload?.created_at || payload?.createdAt);

  const messageId = _roomMsgIdKey(payload?.message_id || payload?.messageId || payload?.id || `local-${Date.now()}-${Math.random().toString(16).slice(2)}`);
  _ensureMsgIndex(viewEl);

  // Reconnect/history can replay a room message that was already appended live.
  // Do not duplicate the visible row; refresh dynamic state instead.
  const existing = _findMsgEl(viewEl, messageId);
  if (existing) {
    const incomingCounts = payload?.reaction_counts || payload?.reactions || payload?.counts || null;
    if (incomingCounts) {
      _storeRoomReactionCounts(viewEl, messageId, incomingCounts);
      const rx = existing.querySelector(".msgReactions");
      if (rx) _renderReactionPills(rx, _getRoomReactionCounts(viewEl, messageId));
    }
    const myReactionExisting = payload?.my_reaction || payload?.current_reaction || null;
    if (myReactionExisting) {
      _setMyReaction(viewEl, messageId, myReactionExisting);
      _lockReactions(viewEl, messageId);
    }
    if (viewEl._ym.pinnedMessageId && _roomMsgIdKey(viewEl._ym.pinnedMessageId) === messageId) {
      _setRoomPinnedMessage(viewEl, messageId, viewEl._ym.pinnedPayload || {});
    }
    _scheduleRoomMessageExpiry(viewEl, messageId, payload);
    return existing;
  }

  try { if (typeof ecRoomRemoveLiveOnlyState === "function") ecRoomRemoveLiveOnlyState(viewEl); } catch {}
  const group = getOrCreateChatGroup(log, username ? String(username) : "?", tsMs, { variant: "room", context: "room" });
  if (!group?.itemsEl) return;

  const item = document.createElement("div");
  item.className = "ec-msgItem ec-msgItem--room";
  item.dataset.msgid = messageId;

  // Content
  const renderedKind = (typeof ecClassifyChatMessageKind === "function") ? ecClassifyChatMessageKind(message) : "text";
  item.classList.add(`ec-msgItem--${renderedKind}`);

  const contentWrap = document.createElement("div");
  contentWrap.className = "ec-msgContent";
  contentWrap.dataset.messageKind = renderedKind;
  if (["torrent", "gif", "media", "room-radio"].includes(renderedKind)) {
    contentWrap.classList.add("ec-msgContent--rich");
  }

  const body = (typeof ecBuildRoomMessageBody === "function")
    ? ecBuildRoomMessageBody(message, { autoScrollLog: log, username })
    : buildTextMessageBody(message, { autoScrollLog: log, username });
  contentWrap.appendChild(body);

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

  const initialCounts = payload?.reaction_counts || payload?.reactions || payload?.counts || null;
  if (initialCounts) _storeRoomReactionCounts(viewEl, messageId, initialCounts);
  const effectiveCounts = _getRoomReactionCounts(viewEl, messageId);
  if (effectiveCounts && Object.keys(effectiveCounts).length) _renderReactionPills(rx, effectiveCounts);
  const myReaction = payload?.my_reaction || payload?.current_reaction || null;
  if (myReaction) _setMyReaction(viewEl, messageId, myReaction);

  reactionWrap.appendChild(rx);
  reactionWrap.appendChild(actions);
  contentWrap.appendChild(reactionWrap);

  line.appendChild(contentWrap);
  item.appendChild(line);

  group.itemsEl.appendChild(item);
  try { window.ecAnimateMessageOnce?.(item, 'room'); } catch {}
  viewEl._ym.msgIndex.set(messageId, item);
  if (viewEl._ym.pinnedMessageId && _roomMsgIdKey(viewEl._ym.pinnedMessageId) === messageId) {
    _setRoomPinnedMessage(viewEl, messageId, viewEl._ym.pinnedPayload || {});
  }
  if (myReaction) {
    _setMyReaction(viewEl, messageId, myReaction);
    _lockReactions(viewEl, messageId);
  }
  _scheduleRoomMessageExpiry(viewEl, messageId, payload);

  const media = item.querySelector('img[data-ec-gif="1"]');
  if (media) media._ecScrollLog = log;
  scheduleScrollLogToBottom(log);
}

// ───────────────────────────────────────────────────────────────────────────────
