// ───────────────────────────────────────────────────────────────────────────────
// Window manager (floating desktop-style chat windows)
// ───────────────────────────────────────────────────────────────────────────────
function bringToFront(winEl) {
  UIState.highestZ += 1;
  winEl.style.zIndex = UIState.highestZ;
}

function registerWindowCleanup(win, cleanupFn) {
  if (!win || typeof cleanupFn !== "function") return cleanupFn;
  if (!Array.isArray(win._ecCleanupFns)) win._ecCleanupFns = [];
  win._ecCleanupFns.push(cleanupFn);
  return cleanupFn;
}

function runWindowCleanup(win) {
  if (!win || !Array.isArray(win._ecCleanupFns) || !win._ecCleanupFns.length) return;
  const cleanups = win._ecCleanupFns.splice(0, win._ecCleanupFns.length);
  cleanups.forEach((cleanupFn) => {
    try { cleanupFn(); } catch {}
  });
}

function createWindow({ id, title, kind }) {
  // If exists, just focus
  if (UIState.windows.has(id)) {
    const existing = UIState.windows.get(id);
    existing.classList.remove("hidden");
    bringToFront(existing);
    return existing;
  }

  const layer = $("windowsLayer");
  if (!layer) return null;

  const win = document.createElement("div");
  win.className = "ym-window";
  win.dataset.winId = id;
  win.dataset.kind = kind;
  if (kind === "dm" || kind === "group") {
    win.setAttribute("role", "dialog");
    win.setAttribute("aria-modal", "false");
    win.setAttribute("aria-label", title);
  }

  // Default placement
  const baseX = Math.max(20, window.innerWidth - 420 - 360 - 40);
  const x = baseX + Math.floor(Math.random() * 50);
  const y = 80 + Math.floor(Math.random() * 60);
  win.style.left = `${x}px`;
  win.style.top = `${y}px`;
  win.style.zIndex = String(++UIState.highestZ);

  const titlebar = document.createElement("div");
  titlebar.className = "ym-titlebar";

  const titleEl = document.createElement("div");
  titleEl.className = "ym-title";
  titleEl.textContent = title;
  titleEl.title = title;
  const titleId = `ym-title-${String(id || "window").replace(/[^a-zA-Z0-9_-]+/g, "-").slice(0, 80)}`;
  titleEl.id = titleId;
  win.setAttribute("aria-labelledby", titleId);
  win.dataset.windowTitle = title;

  const btns = document.createElement("div");
  btns.className = "ym-winBtns";

  const btnMin = document.createElement("button");
  btnMin.className = "winBtn";
  btnMin.title = "Minimize";
  btnMin.textContent = "–";

  const btnClose = document.createElement("button");
  btnClose.className = "winBtn danger";
  btnClose.title = "Close";
  btnClose.textContent = "×";

  btns.appendChild(btnMin);
  btns.appendChild(btnClose);

  titlebar.appendChild(titleEl);
  titlebar.appendChild(btns);

  const body = document.createElement("div");
  body.className = "ym-body";

  const log = document.createElement("div");
  log.className = "ym-log";
  ecClearNode(log);
  disableOutputContextMenu(log);

  const compose = document.createElement("div");
  compose.className = "ym-compose";

  // Shared optional controls for DM/group windows. These must be declared
  // before the group layout block below. beta.74 accidentally assigned the
  // group roster handles before their `let` declarations, which triggers a
  // temporal-dead-zone ReferenceError and prevents group chats from opening.
  let toolbar = null;
  let fileBtn = null;
  let fileInput = null;
  let toolHint = null;
  let gifBtn = null;
  let gifHint = null;
  let voiceBtn = null;
  let voiceHint = null;
  let voiceBar = null;
  let voiceStatus = null;
  let voiceBtnCall = null;
  let voiceBtnHang = null;
  let voiceBtnMute = null;
  let voiceBtnAccept = null;
  let voiceBtnDecline = null;
  let voiceBtnTalk = null;
  let voiceHandsFree = null;
  let groupInviteBtn = null;
  let groupSettingsBtn = null;
  let groupVoiceBtn = null;
  let groupVoiceHint = null;
  let groupTalkBtn = null;
  let groupHandsFree = null;
  let groupMembersPanel = null;
  let groupMembersList = null;
  let groupMembersCount = null;
  let groupMembersRefreshBtn = null;
  let groupMembersCloseBtn = null;

  const input = document.createElement("input");
  input.className = "ym-input";
  input.type = "text";
  input.placeholder = "Type a message…";
  input.setAttribute("autocomplete", kind === "dm" ? "off" : "off");

  // Emoticons (emoji) button
  const emojiBtn = document.createElement("button");
  emojiBtn.type = "button";
  emojiBtn.className = "ym-toolBtn ym-emojiBtn";
  emojiBtn.title = "Emoticons";
  emojiBtn.textContent = "😊";

  const send = document.createElement("button");
  send.className = "ym-send";
  send.textContent = "Send";

  compose.appendChild(input);
  compose.appendChild(emojiBtn);
  compose.appendChild(send);

  if (kind === "group") {
    const groupLayout = document.createElement("div");
    groupLayout.className = "ym-groupChatLayout";

    const groupMain = document.createElement("div");
    groupMain.className = "ym-groupChatMain";
    groupMain.appendChild(log);

    groupMembersPanel = document.createElement("aside");
    groupMembersPanel.className = "ym-groupMembersPanel";
    groupMembersPanel.setAttribute("aria-label", "Group members");

    const groupMembersHead = document.createElement("div");
    groupMembersHead.className = "ym-groupMembersHead";

    const groupMembersTitle = document.createElement("div");
    groupMembersTitle.className = "ym-groupMembersTitle";
    groupMembersTitle.textContent = "Users in group";

    groupMembersCount = document.createElement("span");
    groupMembersCount.className = "roomUsersCount ym-groupMembersCount";
    groupMembersCount.textContent = "0";

    groupMembersRefreshBtn = document.createElement("button");
    groupMembersRefreshBtn.type = "button";
    groupMembersRefreshBtn.className = "iconBtn ym-groupMembersRefresh";
    groupMembersRefreshBtn.title = "Refresh group users";
    groupMembersRefreshBtn.textContent = "↻";

    groupMembersCloseBtn = document.createElement("button");
    groupMembersCloseBtn.type = "button";
    groupMembersCloseBtn.className = "iconBtn ym-groupMembersClose";
    groupMembersCloseBtn.title = "Close group users drawer";
    groupMembersCloseBtn.setAttribute("aria-label", "Close group users drawer");
    groupMembersCloseBtn.textContent = "×";

    const groupMembersHeadRight = document.createElement("div");
    groupMembersHeadRight.className = "ym-groupMembersHeadRight";
    groupMembersHeadRight.appendChild(groupMembersCount);
    groupMembersHeadRight.appendChild(groupMembersRefreshBtn);
    groupMembersHeadRight.appendChild(groupMembersCloseBtn);

    groupMembersHead.appendChild(groupMembersTitle);
    groupMembersHead.appendChild(groupMembersHeadRight);

    groupMembersList = document.createElement("ul");
    groupMembersList.className = "list small roomUsersList ym-groupMembersList";
    groupMembersList.appendChild(ecRoomSidebarEmptyRow("Loading group users…", { muted: true }));

    groupMembersPanel.appendChild(groupMembersHead);
    groupMembersPanel.appendChild(groupMembersList);

    groupLayout.appendChild(groupMain);
    groupLayout.appendChild(groupMembersPanel);
    body.appendChild(groupLayout);
  } else {
    body.appendChild(log);
  }

  // DM toolbar sits between output (log) and input (compose)
  if (kind === "dm") {
    toolbar = document.createElement("div");
    toolbar.className = "ym-toolbar";

    fileBtn = document.createElement("button");
    fileBtn.type = "button";
    fileBtn.className = "ym-toolBtn";
    fileBtn.title = "Send a file";
    fileBtn.textContent = "📎";

    toolHint = document.createElement("span");
    toolHint.className = "ym-toolHint";
    toolHint.textContent = "File";

    fileInput = document.createElement("input");
    fileInput.type = "file";
    fileInput.className = "ym-fileInput";
    fileInput.style.display = "none";

    toolbar.appendChild(fileBtn);
    toolbar.appendChild(toolHint);

// GIF button (GIPHY)
gifBtn = document.createElement("button");
gifBtn.type = "button";
gifBtn.className = "ym-toolBtn";
gifBtn.title = "Search GIFs";
gifBtn.textContent = "GIF";

gifHint = document.createElement("span");
gifHint.className = "ym-toolHint";
gifHint.textContent = "GIF";

toolbar.appendChild(gifBtn);
toolbar.appendChild(gifHint);
    // Voice button
    voiceBtn = document.createElement("button");
    voiceBtn.type = "button";
    voiceBtn.className = "ym-toolBtn";
    voiceBtn.title = "Voice chat";
    voiceBtn.textContent = "🎤";

    voiceHint = document.createElement("span");
    voiceHint.className = "ym-toolHint";
    voiceHint.textContent = "Voice";

    toolbar.appendChild(voiceBtn);
    toolbar.appendChild(voiceHint);

    toolbar.appendChild(fileInput);
    body.appendChild(toolbar);

    // Voice bar: call status + quick actions
    voiceBar = document.createElement("div");
    voiceBar.className = "ym-voiceBar hidden";

    const left = document.createElement("div");
    left.className = "ym-voiceLeft";
    left.appendChild(ecCreateEl('span', { className: 'ym-voiceBadge', text: 'VOICE' }));

    voiceStatus = document.createElement("span");
    voiceStatus.className = "ym-voiceStatus";
    voiceStatus.textContent = "Not connected";
    left.appendChild(voiceStatus);

    const btns = document.createElement("div");
    btns.className = "ym-voiceBtns";

    voiceBtnCall = document.createElement("button");
    voiceBtnCall.className = "miniBtn";
    voiceBtnCall.textContent = "Call";

    voiceBtnHang = document.createElement("button");
    voiceBtnHang.className = "miniBtn danger";
    voiceBtnHang.textContent = "Hang up";

    voiceBtnMute = document.createElement("button");
    voiceBtnMute.className = "miniBtn";
    voiceBtnMute.textContent = "Mute";

    voiceBtnAccept = document.createElement("button");
    voiceBtnAccept.className = "miniBtn";
    voiceBtnAccept.textContent = "Accept";

    voiceBtnDecline = document.createElement("button");
    voiceBtnDecline.className = "miniBtn danger";
    voiceBtnDecline.textContent = "Decline";

    voiceBtnTalk = document.createElement("button");
    voiceBtnTalk.className = "miniBtn ym-talkBtn";
    voiceBtnTalk.textContent = "Hold Talk";
    voiceBtnTalk.title = "Hold to talk; release to mute again";

    const handsLabel = document.createElement("label");
    handsLabel.className = "ym-handsFreeLabel";
    voiceHandsFree = document.createElement("input");
    voiceHandsFree.type = "checkbox";
    handsLabel.appendChild(voiceHandsFree);
    handsLabel.appendChild(document.createTextNode(" Hands-free"));

    // Default: show outbound controls only
    voiceBtnAccept.style.display = "none";
    voiceBtnDecline.style.display = "none";
    voiceBtnTalk.style.display = "none";
    handsLabel.style.display = "none";

    btns.appendChild(voiceBtnCall);
    btns.appendChild(voiceBtnHang);
    btns.appendChild(voiceBtnMute);
    btns.appendChild(voiceBtnAccept);
    btns.appendChild(voiceBtnDecline);
    btns.appendChild(voiceBtnTalk);
    btns.appendChild(handsLabel);

    voiceBar.appendChild(left);
    voiceBar.appendChild(btns);
    body.appendChild(voiceBar);
  }
  if (kind === "group") {
    toolbar = document.createElement("div");
    toolbar.className = "ym-toolbar ym-groupActionToolbar";

    fileBtn = document.createElement("button");
    fileBtn.type = "button";
    fileBtn.className = "ym-toolBtn";
    fileBtn.title = "Send a file to the group (E2EE)";
    fileBtn.textContent = "📎";

    toolHint = document.createElement("span");
    toolHint.className = "ym-toolHint";
    toolHint.textContent = "File";

    fileInput = document.createElement("input");
    fileInput.type = "file";
    fileInput.className = "ym-fileInput";
    fileInput.style.display = "none";

    toolbar.appendChild(fileBtn);
    toolbar.appendChild(toolHint);

// GIF button (GIPHY)
gifBtn = document.createElement("button");
gifBtn.type = "button";
gifBtn.className = "ym-toolBtn";
gifBtn.title = "Search GIFs";
gifBtn.textContent = "GIF";

gifHint = document.createElement("span");
gifHint.className = "ym-toolHint";
gifHint.textContent = "GIF";

toolbar.appendChild(gifBtn);
toolbar.appendChild(gifHint);

    groupInviteBtn = document.createElement("button");
    groupInviteBtn.type = "button";
    groupInviteBtn.className = "ym-toolBtn ym-toolBtnWide ym-groupInviteBtn";
    groupInviteBtn.title = "Invite a user to this group";
    groupInviteBtn.textContent = "➕ Invite";

    groupSettingsBtn = document.createElement("button");
    groupSettingsBtn.type = "button";
    groupSettingsBtn.className = "ym-toolBtn ym-toolBtnWide ym-groupSettingsBtn";
    groupSettingsBtn.title = "Group settings and moderation";
    groupSettingsBtn.textContent = "⚙ Settings";

    groupVoiceBtn = document.createElement("button");
    groupVoiceBtn.type = "button";
    groupVoiceBtn.className = "ym-toolBtn ym-toolBtnWide ym-groupVoiceBtn";
    groupVoiceBtn.title = "Enable voice for this group";
    groupVoiceBtn.textContent = "🎤 Voice";

    groupVoiceHint = document.createElement("span");
    groupVoiceHint.className = "ym-toolHint ym-groupVoiceHint";
    groupVoiceHint.textContent = "Voice";

    toolbar.appendChild(groupInviteBtn);
    toolbar.appendChild(groupSettingsBtn);
    toolbar.appendChild(groupVoiceBtn);
    toolbar.appendChild(groupVoiceHint);

    groupTalkBtn = document.createElement("button");
    groupTalkBtn.type = "button";
    groupTalkBtn.className = "ym-toolBtn ym-talkBtn";
    groupTalkBtn.title = "Push-to-talk for any active voice session";
    groupTalkBtn.textContent = "Hold Talk";

    const groupHandsLabel = document.createElement("label");
    groupHandsLabel.className = "ym-handsFreeLabel ym-toolbarCheck";
    groupHandsFree = document.createElement("input");
    groupHandsFree.type = "checkbox";
    groupHandsLabel.appendChild(groupHandsFree);
    groupHandsLabel.appendChild(document.createTextNode(" Hands-free"));

    toolbar.appendChild(groupTalkBtn);
    toolbar.appendChild(groupHandsLabel);
    toolbar.appendChild(fileInput);
    body.appendChild(toolbar);
  }

  body.appendChild(compose);

  const resize = document.createElement("div");
  resize.className = "ym-resize";

  win.appendChild(titlebar);
  win.appendChild(body);
  win.appendChild(resize);

  layer.appendChild(win);
  try { window.ecAnimateOnce?.(win, 'ec-enter-scale'); } catch {}
  UIState.windows.set(id, win);

  // Focus behavior
  win.addEventListener("mousedown", () => bringToFront(win));
  titlebar.addEventListener("mousedown", () => bringToFront(win));

  // Drag behavior
  (function attachDrag() {
    let dragging = false;
    let startX = 0, startY = 0, origX = 0, origY = 0;

    const onTitlebarMouseDown = (e) => {
      dragging = true;
      startX = e.clientX; startY = e.clientY;
      origX = parseInt(win.style.left || "0", 10);
      origY = parseInt(win.style.top || "0", 10);
      e.preventDefault();
    };
    const onWindowMouseMove = (e) => {
      if (!dragging) return;
      const dx = e.clientX - startX;
      const dy = e.clientY - startY;
      win.style.left = `${origX + dx}px`;
      win.style.top = `${origY + dy}px`;
    };
    const onWindowMouseUp = () => { dragging = false; };

    titlebar.addEventListener("mousedown", onTitlebarMouseDown);
    window.addEventListener("mousemove", onWindowMouseMove);
    window.addEventListener("mouseup", onWindowMouseUp);
    registerWindowCleanup(win, () => {
      dragging = false;
      titlebar.removeEventListener("mousedown", onTitlebarMouseDown);
      window.removeEventListener("mousemove", onWindowMouseMove);
      window.removeEventListener("mouseup", onWindowMouseUp);
    });
  })();

  // Resize behavior
  (function attachResize() {
    let resizing = false;
    let startX = 0, startY = 0, startW = 0, startH = 0;

    const onResizeMouseDown = (e) => {
      resizing = true;
      startX = e.clientX; startY = e.clientY;
      startW = win.offsetWidth; startH = win.offsetHeight;
      e.preventDefault();
      bringToFront(win);
    };
    const onResizeMouseMove = (e) => {
      if (!resizing) return;
      const dx = e.clientX - startX;
      const dy = e.clientY - startY;
      win.style.width = `${Math.max(340, startW + dx)}px`;
      win.style.height = `${Math.max(280, startH + dy)}px`;
    };
    const onResizeMouseUp = () => { resizing = false; };

    resize.addEventListener("mousedown", onResizeMouseDown);
    window.addEventListener("mousemove", onResizeMouseMove);
    window.addEventListener("mouseup", onResizeMouseUp);
    registerWindowCleanup(win, () => {
      resizing = false;
      resize.removeEventListener("mousedown", onResizeMouseDown);
      window.removeEventListener("mousemove", onResizeMouseMove);
      window.removeEventListener("mouseup", onResizeMouseUp);
    });
  })();

  // Minimize/Close
  btnMin.onclick = () => minimizeWindow(id, win.dataset.windowTitle || title);
  btnClose.onclick = () => closeWindow(id);

  // Expose handles for message plumbing
  win._ym = { titleEl, log, input, send, emojiBtn, toolbar, fileBtn, fileInput, toolHint, gifBtn, gifHint, voiceBtn, voiceHint, voiceBar, voiceStatus, voiceBtnCall, voiceBtnHang, voiceBtnMute, voiceBtnAccept, voiceBtnDecline, voiceBtnTalk, voiceHandsFree, groupInviteBtn, groupSettingsBtn, groupVoiceBtn, groupVoiceHint, groupTalkBtn, groupHandsFree, groupMembersPanel, groupMembersList, groupMembersCount, groupMembersRefreshBtn, groupMembersCloseBtn };
  try { appendLine(win, "System:", "Window opened.", { ts: Date.now() }); } catch {}

  // Bind emoticons picker
  bindEmojiButton(emojiBtn, input);

  // Let the mobile shell convert newly-created PM/group windows into phone sheets immediately.
  try {
    if (kind === "dm" || kind === "group") {
      window.ecSyncMobileWindows?.();
    }
  } catch {}

  // Enter-to-send
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") send.click();
  });

  return win;
}

function minimizeWindow(id, title) {
  const win = UIState.windows.get(id);
  if (!win) return;

  win.classList.add("hidden");

  if (UIState.minimized.has(id)) return;

  const bar = $("dockTaskbar");
  if (!bar) return;

  const btn = document.createElement("button");
  btn.className = "taskBtn";
  btn.textContent = title;
  btn.onclick = () => {
    win.classList.remove("hidden");
    bringToFront(win);
    btn.remove();
    UIState.minimized.delete(id);
  };

  bar.appendChild(btn);
  UIState.minimized.set(id, btn);
}

function closeWindow(id) {
  const win = UIState.windows.get(id);
  if (!win) return;

  // If closing a DM while in a voice call, hang up.
  if (typeof id === "string" && id.startsWith("dm:")) {
    const peer = String(win.dataset.pmPeer || id.slice(3) || '').trim();
    if (peer && VOICE_STATE.dmCalls.has(peer)) {
      voiceHangupDm(peer, "Closed", true);
    }
  }

  // If it's a room window, keep state consistent
  if (win.dataset.kind === "room") {
    // no-op: leaving room is user-controlled via Leave button
  }

  if (win.dataset.kind === "group" && win._groupChatJoined) {
    const rawGroupId = String(id || '').startsWith('group:') ? String(id).slice(6) : '';
    const groupId = Number(rawGroupId || 0);
    if (groupId) {
      const groupVoiceRoom = `group_${groupId}`;
      if (typeof voiceLeaveRoom === 'function' && VOICE_STATE?.room?.joined && VOICE_STATE?.room?.name === groupVoiceRoom) {
        try { voiceLeaveRoom('Left group voice', true, { silent: true }); } catch {}
      }
      try {
        if (typeof ecLeaveGroupChatAck === 'function') ecLeaveGroupChatAck(groupId).catch(() => {});
        else socket.emit('leave_group_chat', { group_id: groupId });
      } catch {}
      try { UIState.groupMembers.delete(Number(groupId)); } catch {}
    }
    win._groupChatJoined = false;
  }

  runWindowCleanup(win);
  win.remove();
  UIState.windows.delete(id);

  const taskBtn = UIState.minimized.get(id);
  if (taskBtn) taskBtn.remove();
  UIState.minimized.delete(id);
}
