function showRoomInviteToast(room, by, opts = {}) {
  const r = String(room || "").trim();
  if (!r) return;
  const who = String(by || "").trim();
  const kind = String(opts?.kind || 'room');
  const key = _inviteKey(r, who, kind);
  if (UIState.inviteSeen?.has?.(key)) return;
  rememberInviteSeen(key);

  const label = who ? `📨 Room invite: ${r} (from ${who})` : `📨 Room invite: ${r}`;
  toastChoice(label, {
    kind: "info",
    event: "room_invite",
    timeout: 14000,
    acceptLabel: "✅",
    declineLabel: "❌",
    onAccept: async () => {
      try {
        await acceptRoomInvite({ room: r, by: who, kind });
      } catch (e) {
        toast(`❌ ${e.message || `Could not join ${r}`}`, 'error');
      }
    },
    onDecline: async () => {
      try {
        await declineRoomInvite({ room: r, by: who, kind });
      } catch (e) {
        toast(`❌ ${e.message || 'Could not decline invite'}`, 'error');
      }
    },
  });

  maybeBrowserNotify("Room invite", who ? `${who} invited you to ${r}` : `Invite to ${r}`);
}

socket.on("room_invite_cleared", ({ room, by, kind }) => {
  try {
    removeRoomInviteFromState(room, by, kind || 'room');
    renderAlertsInviteListInto($('railAlertsList'), UIState.groupInvites, UIState.roomInvites, { openRail: true });
    updateDockSummaryCounts();
    try { forgetInviteSeen(_inviteKey(room, by, kind || 'room')); } catch {}
  } catch {}
});

// Realtime custom-room invite event
socket.on("custom_room_invite", ({ room, by }) => {
  try { mergeRoomInvites('custom_private', [{ room, by, kind: 'custom_private', created_at: new Date().toISOString() }]); } catch {}
  try { renderAlertsInviteListInto($('railAlertsList'), UIState.groupInvites, UIState.roomInvites, { openRail: true }); } catch {}
  try { updateDockSummaryCounts(); } catch {}
  showRoomInviteToast(room, by, { kind: 'custom_private' });
});

// Realtime invite for official/public rooms
socket.on("room_invite", ({ room, by }) => {
  try { mergeRoomInvites('room', [{ room, by, kind: 'room', created_at: new Date().toISOString() }]); } catch {}
  try { renderAlertsInviteListInto($('railAlertsList'), UIState.groupInvites, UIState.roomInvites, { openRail: true }); } catch {}
  try { updateDockSummaryCounts(); } catch {}
  showRoomInviteToast(room, by, { kind: 'room' });
});

socket.on("group_invite", (payload = {}) => {
  try {
    mergeGroupInvites([{ ...payload, created_at: payload?.created_at || new Date().toISOString() }]);
  } catch {}
  try { renderGroupInviteListInto($('groupInviteList'), UIState.groupInvites); } catch {}
  try { renderAlertsInviteListInto($('railAlertsList'), UIState.groupInvites, UIState.roomInvites, { openRail: true }); } catch {}
  try { updateDockSummaryCounts(); } catch {}
  try { showGroupInviteToast(payload); } catch {}
});

socket.on("group_invite_cleared", ({ group_id, from_user }) => {
  try { removeGroupInviteFromState(group_id, from_user || ''); } catch {}
  try { renderGroupInviteListInto($('groupInviteList'), UIState.groupInvites); } catch {}
  try { renderAlertsInviteListInto($('railAlertsList'), UIState.groupInvites, UIState.roomInvites, { openRail: true }); } catch {}
  try { updateDockSummaryCounts(); } catch {}
});

socket.on("groups_refresh", (payload = {}) => {
  try { refreshMyGroups(); } catch {}
  try { refreshGroupInvites(); } catch {}
  try {
    const groupId = Number(payload?.group_id || 0);
    if (groupId) {
      if (String(payload?.reason || '') === 'metadata_updated' && typeof applyGroupMetadataUpdateFromEvent === 'function') {
        applyGroupMetadataUpdateFromEvent(groupId, payload);
      }
      const win = UIState.windows.get("group:" + String(groupId));
      if (win) refreshGroupMemberRoster(groupId, win).catch(() => {});
    }
  } catch {}
});

// ───────────────────────────────────────────────────────────────────────────────
// Media UI wiring (voice controls)
// ───────────────────────────────────────────────────────────────────────────────
(function webcamWireUiOnce(){
  try{
    const bMute = $("btnRoomEmbedVoiceMute");
    if (bMute) {
      bMute.addEventListener("click", (ev) => {
        try{
          if (ecMediaModeReady()) { ecMediaToggleMic(); return; }
        } catch {}
      });
    }
    // Voice bar controls stay voice-only; webcam has its own panel/button.

    // The top-level Voice/Webcam buttons are rebound by openRoomEmbedded()
    // for the active room. Do not add global listeners here or one click can
    // toggle media twice after the room view attaches its own handlers.
    const bCamTop = $("btnRoomEmbedCam");
    if (bCamTop) bCamTop.classList.toggle("hidden", !ecMediaModeReady());
    try { ecMediaRefreshModeFromServer().then(() => { try { voiceUpdateRoomCamButton(); } catch {}; }); } catch {}
    const bHide = $("btnRoomEmbedAvHide");
    if (bHide) {
      bHide.addEventListener("click", (ev) => {
        try{
          const p = $("roomEmbedAvPanel");
          if (!p) return;
          p.classList.add("hidden");
        } catch {}
      });
    }
  }catch{}
})();
