function voiceLeaveRoom(reason = "Left", notifyServer = true, opts = {}) {
  const room = VOICE_STATE.room.name;
  const keepDesired = !!(opts && opts.keepDesired);
  const silent = !!(opts && opts.silent);
  if (!room || !VOICE_STATE.room.joined) {
    if (!keepDesired) VOICE_STATE.room.wantRoomVoice = false;
    VOICE_STATE.room.viewerOnly = false;
    voiceRoomUi({ show: false });
    return;
  }
  // Close peer PCs
  for (const [peer, obj] of VOICE_STATE.room.peers.entries()) {
    try { obj.pc?.close(); } catch {}
    try {
      if (obj.remoteEl) {
        obj.remoteEl.srcObject = null;
        obj.remoteEl.remove();
      }
    } catch {}
  }
  VOICE_STATE.room.peers.clear();
  try { VOICE_STATE.room.iceQueues.clear(); } catch {}
  VOICE_STATE.room.joined = false;
  VOICE_STATE.room.name = null;
  VOICE_STATE.room.wantRoomVoice = keepDesired ? true : false;
  VOICE_STATE.room.viewerOnly = false;
  voiceSetMute(false);
  voiceStopAllAutoQualityMonitors();
  // Persisted state (reconnect restore)
  try {
    sessionStorage.removeItem("echochat_voice_room");
    sessionStorage.removeItem("echochat_voice_room_joined");
    if (!keepDesired) sessionStorage.removeItem("echochat_voice_desired");
    else sessionStorage.setItem("echochat_voice_desired", "1");
  } catch (e) {}
  if (notifyServer) socket.emit("voice_room_leave", { room }, () => {});
  voiceRoomUi({ show: false });
  voiceUpdateRoomVoiceButton();
  if (reason && !silent) toast(`🎤 ${reason}`, "info");
  voiceMaybeStopMic();
}

function voiceToggleMuteRoom() {
  const muted = !VOICE_STATE.micMuted;
  voiceSetMute(muted);
  voiceRoomUi({ muteLabel: muted ? "Unmute" : "Mute" });
  voiceUpdateRoomVoiceButton();
}

function voiceRoomIsInitiator(a, b) {
  return String(a) < String(b);
}

function voiceRoomEnsurePeer(room, peer) {
  if (!VOICE_STATE.room.joined || VOICE_STATE.room.name !== room) return;
  if (VOICE_STATE.room.peers.has(peer)) return;
  const pc = voiceMakePc();
  const stream = VOICE_STATE.micStream;
  if (stream) stream.getTracks().forEach(t => pc.addTrack(t, stream));
  voiceApplySenderQuality(pc);
  voiceStartAutoQualityMonitor(`room-${room}-${peer}`, pc);
  const obj = { pc, remoteEl: null, remoteVideoEl: null, echoVideoSender: null, echoVideoTransceiver: null };
  VOICE_STATE.room.peers.set(peer, obj);
  try {
    if (typeof echoCamAttachTrackToPeer === "function") echoCamAttachTrackToPeer(pc, obj, room, peer);
  } catch {}

  pc.ontrack = (ev) => {
    const st = ev.streams && ev.streams[0];
    if (!st) return;
    if (ev.track && ev.track.kind === "video" && typeof echoCamAttachRemoteVideo === "function") {
      obj.remoteVideoEl = echoCamAttachRemoteVideo(room, peer, st);
    } else {
      obj.remoteEl = voiceAttachRemoteAudio(`room-${room}-${peer}`, st);
    }
  };
  pc.onicecandidate = (ev) => {
    if (ev.candidate) socket.emit("voice_room_ice", { room, to: peer, candidate: ev.candidate });
  };
  pc._echoIceRestartOffer = async () => {
    if (pc.signalingState !== "stable" || pc._echoMakingOffer) return false;
    pc._echoMakingOffer = true;
    try {
      const offer = await pc.createOffer({ iceRestart: true });
      await pc.setLocalDescription(offer);
      socket.emit("voice_room_offer", { room, to: peer, offer: pc.localDescription, ice_restart: true });
      return true;
    } finally {
      pc._echoMakingOffer = false;
    }
  };

  // Perfect-negotiation-lite: normal room joins keep a deterministic first offer,
  // but later camera/audio track changes may need either side to renegotiate.
  pc._echoPolite = !voiceRoomIsInitiator(currentUser, peer);
  pc._echoMakingOffer = false;
  pc._echoIgnoreOffer = false;
  pc.onnegotiationneeded = async () => {
    try {
      pc._echoMakingOffer = true;
      const offer = await pc.createOffer();
      await pc.setLocalDescription(offer);
      socket.emit("voice_room_offer", { room, to: peer, offer: pc.localDescription });
    } catch (e) {
      console.warn("voice/video negotiation failed", e);
    } finally {
      pc._echoMakingOffer = false;
    }
  };
}

function voiceEndAll(reason = "Ended") {
  // DM calls
  for (const peer of Array.from(VOICE_STATE.dmCalls.keys())) {
    voiceHangupDm(peer, reason, true);
  }
  // Room
  voiceLeaveRoom(reason, true);
  voiceMaybeStopMic();
}
