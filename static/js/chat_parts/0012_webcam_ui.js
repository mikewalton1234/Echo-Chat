// Echo webcam/media engine — built-in WebRTC, no external media server SDK.
// This file intentionally keeps its current manifest filename so upgrades do not
// break stale deployments, but the runtime engine is EchoMedia/WebRTC.
(function () {
  const CAM_PROFILES = (ECHOCHAT_CFG.webcam_quality_profiles && typeof ECHOCHAT_CFG.webcam_quality_profiles === "object")
    ? ECHOCHAT_CFG.webcam_quality_profiles
    : {
        low: { label: "Low data / compatible", width: 320, height: 180, frameRate: 12, max_bitrate: 160000, preferred_codecs: ["H264", "VP8", "VP9"], content_hint: "detail", degradation_preference: "maintain-framerate" },
        balanced: { label: "Balanced / compatible", width: 640, height: 360, frameRate: 18, max_bitrate: 550000, preferred_codecs: ["H264", "VP8", "VP9"], content_hint: "motion", degradation_preference: "balanced" },
        high: { label: "High quality", width: 1280, height: 720, frameRate: 24, max_bitrate: 1500000, preferred_codecs: ["H264", "VP8", "VP9", "AV1"], content_hint: "motion", degradation_preference: "balanced" },
      };

  const ECHO_MEDIA = {
    echoRoom: "",
    voiceDesired: false,
    camDesired: false,
    comboDesired: false,
    camEnabled: false,
    micEnabled: false,
    camStream: null,
    panel: null,
    grid: null,
    status: null,
    quality: "balanced",
    codec: "auto",
    remoteTiles: new Map(),
    // viewer side: room::owner webcams this browser explicitly requested/was allowed to view.
    requestedViewers: new Set(),
    // owner side: room::viewer clients approved to receive this user's camera track.
    approvedViewers: new Set(),
    activeViewers: new Map(),
    localTile: null,
    lastCameraError: "",
    lastCameraQuality: "",
  };

  function safeToast(message, level = "info", ms) {
    try { if (typeof toast === "function") toast(message, level, ms); } catch {}
  }

  function readSavedQuality() {
    try {
      const v = Settings && Settings.get ? Settings.get("echoWebcamQuality", null) : null;
      if (v && CAM_PROFILES[String(v).toLowerCase()]) return String(v).toLowerCase();
    } catch {}
    const cfg = String((ECHOCHAT_CFG && ECHOCHAT_CFG.webcam_quality) || (ECHOCHAT_CFG && ECHOCHAT_CFG.echo_webcam_quality) || "balanced").toLowerCase();
    return CAM_PROFILES[cfg] ? cfg : "balanced";
  }

  function saveQuality(name) {
    const q = CAM_PROFILES[String(name || "").toLowerCase()] ? String(name).toLowerCase() : "balanced";
    ECHO_MEDIA.quality = q;
    try { Settings && Settings.set && Settings.set("echoWebcamQuality", q); } catch {}
    return q;
  }

  function profile(name = ECHO_MEDIA.quality) {
    const key = String(name || "balanced").toLowerCase();
    return CAM_PROFILES[key] || CAM_PROFILES.balanced || CAM_PROFILES.low;
  }

  ECHO_MEDIA.quality = readSavedQuality();

  function isLocalhostLikeOrigin() {
    try {
      const h = String(location && location.hostname || "").toLowerCase();
      return h === "localhost" || h === "127.0.0.1" || h === "::1" || h.endsWith(".localhost");
    } catch {
      return false;
    }
  }

  function webcamConfigStatus() {
    const cfg = (ECHOCHAT_CFG && typeof ECHOCHAT_CFG === "object") ? ECHOCHAT_CFG : {};
    const features = (cfg.features && typeof cfg.features === "object") ? cfg.features : {};
    const policy = echoCamPolicy();
    if (policy.webcam_approval_mode === "disabled") {
      return { ok: false, reason: "Webcam is disabled by the server webcam policy." };
    }
    if (cfg.webcam_enabled === false || cfg.echo_webcam_enabled === false) {
      const mode = String(cfg.av_mode || cfg.av_requested_mode || "").toLowerCase();
      const suffix = mode === "standard" ? " Admin → Echo Media is set to Standard voice only." : "";
      return { ok: false, reason: `Webcam is disabled by server settings.${suffix}` };
    }
    if (features.webcam === false) {
      return { ok: false, reason: "Webcam is not enabled for the current server media mode." };
    }
    return { ok: true, reason: "" };
  }

  function browserWebcamStatus() {
    if (!VOICE_ENABLED) return { ok: false, reason: "Voice/media is disabled on this server." };
    if (typeof RTCPeerConnection === "undefined") return { ok: false, reason: "This browser does not support WebRTC peer connections." };
    if (!window.isSecureContext && !isLocalhostLikeOrigin()) {
      return { ok: false, reason: "Webcam requires HTTPS, localhost, or 127.0.0.1." };
    }
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      return { ok: false, reason: "This browser/context does not expose camera access. Use HTTPS or localhost, and make sure camera permission is not blocked." };
    }
    return { ok: true, reason: "" };
  }

  function ready() {
    const browser = browserWebcamStatus();
    // Keep the media engine ready for room voice even when webcam is disabled
    // by policy.  Webcam-specific controls call webcamAvailable() below.
    return !!(VOICE_ENABLED && typeof RTCPeerConnection !== "undefined" && navigator.mediaDevices && navigator.mediaDevices.getUserMedia);
  }

  function webcamUnavailableReason() {
    const cfg = webcamConfigStatus();
    if (!cfg.ok) return cfg.reason;
    const browser = browserWebcamStatus();
    if (!browser.ok) return browser.reason;
    return "Webcam is not available.";
  }

  function webcamAvailable() {
    return !!(webcamConfigStatus().ok && browserWebcamStatus().ok);
  }

  function localRoomName() {
    return String(ECHO_MEDIA.echoRoom || (VOICE_STATE && VOICE_STATE.room && VOICE_STATE.room.name) || UIState.currentRoom || UIState.roomEmbedRoom || "").trim();
  }

  function updateStatus(text) {
    if (ECHO_MEDIA.status) ECHO_MEDIA.status.textContent = text || "";
  }


  function echoCamPolicy() {
    const cfg = (ECHOCHAT_CFG && typeof ECHOCHAT_CFG === "object") ? ECHOCHAT_CFG : {};
    const policy = (cfg.webcam_policy && typeof cfg.webcam_policy === "object") ? cfg.webcam_policy : {};
    const raw = String(cfg.webcam_approval_mode || policy.webcam_approval_mode || "owner_approval").trim().toLowerCase().replace(/-/g, "_");
    const mode = (raw === "open" || raw === "public" || raw === "everyone") ? "open"
      : (raw === "disabled" || raw === "blocked" || raw === "off") ? "disabled"
      : "owner_approval";
    return {
      webcam_approval_mode: mode,
      webcam_max_viewers: Number(cfg.webcam_max_viewers || policy.webcam_max_viewers || 0) || 0,
      default_media_policy: String(cfg.default_media_policy || policy.default_media_policy || "user_choice"),
    };
  }

  function echoCamKey(room, username) {
    return `${String(room || "").trim()}::${String(username || "").trim()}`;
  }

  function echoCamViewerRequested(room, owner) {
    return ECHO_MEDIA.requestedViewers.has(echoCamKey(room, owner));
  }

  function echoCamViewerApproved(room, viewer) {
    return ECHO_MEDIA.approvedViewers.has(echoCamKey(room, viewer));
  }

  function echoCamSetViewerApproved(room, viewer, approved) {
    const key = echoCamKey(room, viewer);
    if (!String(viewer || "").trim() || !String(room || "").trim()) return false;
    if (approved) ECHO_MEDIA.approvedViewers.add(key);
    else ECHO_MEDIA.approvedViewers.delete(key);
    return true;
  }

  function echoCamRequestKey(room, viewer) {
    return echoCamKey(room, viewer).toLowerCase();
  }

  function echoCamViewerRoomKey(room) {
    return String(room || localRoomName()).trim();
  }

  function echoCamViewerSetForRoom(room) {
    const key = echoCamViewerRoomKey(room);
    if (!key) return new Set();
    if (!ECHO_MEDIA.activeViewers.has(key)) ECHO_MEDIA.activeViewers.set(key, new Set());
    return ECHO_MEDIA.activeViewers.get(key);
  }

  function echoCamViewerSummary(room) {
    const key = echoCamViewerRoomKey(room);
    const viewers = key ? Array.from(ECHO_MEDIA.activeViewers.get(key) || []).filter(Boolean).sort() : [];
    return { viewers, viewerCount: viewers.length };
  }

  function echoCamUpdateLocalViewerInfo(room) {
    if (!ECHO_MEDIA.localTile || !ECHO_MEDIA.localTile._echoInfo) return;
    const summary = echoCamViewerSummary(room);
    if (!ECHO_MEDIA.camDesired && !ECHO_MEDIA.camEnabled) {
      ECHO_MEDIA.localTile._echoInfo.textContent = "Local camera preview";
      return;
    }
    ECHO_MEDIA.localTile._echoInfo.textContent = summary.viewerCount
      ? `Viewing: ${summary.viewers.join(", ")}`
      : "No active webcam viewers";
    try { ECHO_MEDIA.localTile.dataset.viewerCount = String(summary.viewerCount); } catch {}
  }

  function echoCamSetActiveViewing(room, viewer, viewing) {
    room = echoCamViewerRoomKey(room);
    viewer = String(viewer || "").trim();
    if (!room || !viewer || viewer === String(currentUser || "").trim()) return echoCamViewerSummary(room);
    const set = echoCamViewerSetForRoom(room);
    if (viewing) set.add(viewer);
    else set.delete(viewer);
    echoCamUpdateLocalViewerInfo(room);
    return echoCamViewerSummary(room);
  }

  function echoCamReplaceActiveViewers(room, viewers) {
    room = echoCamViewerRoomKey(room);
    if (!room) return echoCamViewerSummary(room);
    const set = new Set((Array.isArray(viewers) ? viewers : []).map(v => String(v || "").trim()).filter(v => v && v !== String(currentUser || "").trim()));
    ECHO_MEDIA.activeViewers.set(room, set);
    echoCamUpdateLocalViewerInfo(room);
    return echoCamViewerSummary(room);
  }

  function echoCamRenderAlertRequests(opts = {}) {
    try {
      if (typeof renderAlertsInviteListInto === "function") {
        renderAlertsInviteListInto($("railAlertsList"), UIState.groupInvites, UIState.roomInvites, { openRail: true });
      }
    } catch {}
    try { if (typeof updateDockSummaryCounts === "function") updateDockSummaryCounts(); } catch {}
    try {
      if (opts && opts.open && typeof openDockRailPanel === "function") openDockRailPanel("alerts");
    } catch {}
  }

  function echoCamUpsertIncomingRequest(room, viewer, policy = null) {
    room = String(room || localRoomName()).trim();
    viewer = String(viewer || "").trim();
    if (!room || !viewer || viewer === String(currentUser || "").trim()) return null;
    if (!Array.isArray(UIState.webcamRequests)) UIState.webcamRequests = [];
    const key = echoCamRequestKey(room, viewer);
    const existing = UIState.webcamRequests.find((req) => echoCamRequestKey(req && req.room, req && req.viewer) === key);
    const req = existing || { room, viewer, requested_at: new Date().toISOString() };
    req.room = room;
    req.viewer = viewer;
    req.policy = policy || req.policy || null;
    req.requested_at = req.requested_at || new Date().toISOString();
    req.updated_at = new Date().toISOString();
    if (!existing) UIState.webcamRequests.unshift(req);
    echoCamRenderAlertRequests({ open: true });
    return req;
  }

  function echoCamRemoveIncomingRequest(room, viewer) {
    room = String(room || localRoomName()).trim();
    viewer = String(viewer || "").trim();
    if (!Array.isArray(UIState.webcamRequests) || !room || !viewer) return false;
    const key = echoCamRequestKey(room, viewer);
    const before = UIState.webcamRequests.length;
    UIState.webcamRequests = UIState.webcamRequests.filter((req) => echoCamRequestKey(req && req.room, req && req.viewer) !== key);
    if (UIState.webcamRequests.length !== before) {
      echoCamRenderAlertRequests({ open: false });
      return true;
    }
    return false;
  }

  function echoCamClearIncomingRequestsForRoom(room) {
    room = String(room || localRoomName()).trim();
    if (!Array.isArray(UIState.webcamRequests) || !room) return false;
    const before = UIState.webcamRequests.length;
    UIState.webcamRequests = UIState.webcamRequests.filter((req) => String(req && req.room || "") !== room);
    if (UIState.webcamRequests.length !== before) echoCamRenderAlertRequests({ open: false });
    return UIState.webcamRequests.length !== before;
  }

  function echoCamCanSendToPeer(room, peer) {
    if (!ECHO_MEDIA.camDesired || !ECHO_MEDIA.camEnabled) return false;
    if (!peer || peer === String(currentUser || "")) return false;
    const policy = echoCamPolicy();
    if (policy.webcam_approval_mode === "disabled") return false;
    // Important privacy rule: even "open" mode means anyone may request/join
    // without owner approval; it does NOT mean every room user is auto-subscribed.
    return echoCamViewerApproved(room, peer);
  }

  function echoCamCanReceiveFromPeer(room, owner) {
    if (!owner || owner === String(currentUser || "")) return false;
    const policy = echoCamPolicy();
    if (policy.webcam_approval_mode === "disabled") return false;
    return echoCamViewerRequested(room, owner);
  }

  function ensurePanel() {
    if (ECHO_MEDIA.panel && document.body.contains(ECHO_MEDIA.panel)) return ECHO_MEDIA.panel;

    const panel = document.createElement("div");
    panel.className = "ym-avPanel";
    panel.id = "echoWebcamPanel";

    const top = document.createElement("div");
    top.className = "ym-avTop";

    const meta = document.createElement("div");
    meta.className = "ym-avMeta";
    const title = document.createElement("div");
    title.className = "ym-avTitle";
    title.textContent = "Webcam";
    const status = document.createElement("div");
    status.className = "ym-avStatus";
    status.textContent = "Built-in WebRTC";
    meta.append(title, status);

    const close = document.createElement("button");
    close.type = "button";
    close.className = "miniBtn";
    close.textContent = "✕";
    close.title = "Close webcam panel";
    close.addEventListener("click", () => panel.classList.add("hidden"));
    top.append(meta, close);

    const deviceRow = document.createElement("div");
    deviceRow.className = "ym-avDeviceRow";
    const qualityField = document.createElement("label");
    qualityField.className = "ym-avDeviceField";
    const qText = document.createElement("span");
    qText.textContent = "Quality";
    const select = document.createElement("select");
    select.className = "ym-avSelect";
    for (const [key, val] of Object.entries(CAM_PROFILES)) {
      const opt = document.createElement("option");
      opt.value = key;
      opt.textContent = val && val.label ? String(val.label) : key;
      select.appendChild(opt);
    }
    select.value = ECHO_MEDIA.quality;
    select.addEventListener("change", async () => {
      const q = saveQuality(select.value);
      try { await echoCamApplyQualityToLocalTrack(); } catch {}
      try { echoCamApplyQualityToAllSenders(); } catch {}
      safeToast(`📷 Webcam quality set to ${profile(q).label || q}`, "info", 2200);
    });
    qualityField.append(qText, select);
    deviceRow.appendChild(qualityField);

    const grid = document.createElement("div");
    grid.className = "ym-avGrid";

    panel.append(top, deviceRow, grid);
    document.body.appendChild(panel);
    ECHO_MEDIA.panel = panel;
    ECHO_MEDIA.grid = grid;
    ECHO_MEDIA.status = status;
    return panel;
  }

  function showPanel() {
    const panel = ensurePanel();
    panel.classList.remove("hidden");
    return panel;
  }

  function makeTile(username, label, local = false) {
    showPanel();
    const tile = document.createElement("div");
    tile.className = "ym-avTile";
    tile.dataset.user = String(username || "");

    const head = document.createElement("div");
    head.className = "ym-avTileHead";
    const name = document.createElement("div");
    name.className = "ym-avTileName";
    name.textContent = label || username || "Webcam";
    const badge = document.createElement("div");
    badge.className = "ym-avTileBadge";
    badge.textContent = local ? "You" : "Peer";
    head.append(name, badge);

    const media = document.createElement("div");
    media.className = "ym-avMedia";
    const video = document.createElement("video");
    video.autoplay = true;
    video.playsInline = true;
    video.muted = !!local;
    media.appendChild(video);

    const controls = document.createElement("div");
    controls.className = "ym-avTileControls";
    const info = document.createElement("div");
    info.className = "ym-avViewers";
    info.textContent = local ? "Local camera preview" : "Room webcam stream";
    controls.appendChild(info);

    tile.append(head, media, controls);
    tile._echoVideo = video;
    tile._echoInfo = info;
    ECHO_MEDIA.grid.appendChild(tile);
    return tile;
  }

  function attachLocalPreview(stream) {
    if (!stream) return;
    const tile = ECHO_MEDIA.localTile || makeTile(currentUser || "me", `${currentUser || "Me"} camera`, true);
    ECHO_MEDIA.localTile = tile;
    try { tile._echoVideo.srcObject = stream; } catch {}
    echoCamUpdateLocalViewerInfo(localRoomName());
    return tile;
  }

  function echoCamAttachRemoteVideo(room, peer, stream) {
    if (!room || localRoomName() && String(room) !== localRoomName()) return null;
    const key = String(peer || "").trim();
    if (!key) return null;
    if (!echoCamCanReceiveFromPeer(room, key)) {
      try { if (stream && stream.getVideoTracks) stream.getVideoTracks().forEach(t => { t.enabled = false; }); } catch {}
      return null;
    }
    let tile = ECHO_MEDIA.remoteTiles.get(key);
    if (!tile || !document.body.contains(tile)) {
      tile = makeTile(key, `${key} camera`, false);
      ECHO_MEDIA.remoteTiles.set(key, tile);
    }
    try { tile._echoVideo.srcObject = stream; } catch {}
    updateStatus(`Receiving webcam from ${key}`);
    showPanel();
    return tile;
  }

  function echoCamRemoveRemoteVideo(peer) {
    const key = String(peer || "").trim();
    if (!key) return;
    const tile = ECHO_MEDIA.remoteTiles.get(key);
    if (tile) {
      try { tile._echoVideo.srcObject = null; } catch {}
      try { tile.remove(); } catch {}
    }
    ECHO_MEDIA.remoteTiles.delete(key);
  }

  function clearRemoteVideos() {
    for (const key of Array.from(ECHO_MEDIA.remoteTiles.keys())) echoCamRemoveRemoteVideo(key);
  }

  function videoConstraints(profileName = ECHO_MEDIA.quality) {
    const p = profile(profileName);
    const width = Number(p.width || 640);
    const height = Number(p.height || 360);
    const frameRate = Number(p.frameRate || p.framerate || 18);
    const out = {
      width: width > 0 ? { ideal: width } : undefined,
      height: height > 0 ? { ideal: height } : undefined,
      frameRate: frameRate > 0 ? { ideal: frameRate, max: Math.max(10, frameRate) } : undefined,
      facingMode: { ideal: "user" },
    };
    if (width > 0 && height > 0) out.aspectRatio = { ideal: width / height };
    return out;
  }

  function isFatalCameraError(err) {
    const name = String(err && err.name || "").toLowerCase();
    return name.includes("notallowed") || name.includes("permission") || name.includes("security") || name.includes("notfound") || name.includes("notreadable");
  }

  function cameraOpenAttempts() {
    const preferred = String(ECHO_MEDIA.quality || "balanced").toLowerCase();
    const order = [];
    [preferred, "balanced", "low"].forEach((q) => {
      if (CAM_PROFILES[q] && !order.includes(q)) order.push(q);
    });
    const attempts = order.map((q) => ({ quality: q, constraints: videoConstraints(q) }));
    attempts.push({ quality: "browser-default", constraints: true });
    return attempts;
  }

  function describeCameraError(err) {
    const name = String(err && err.name || "CameraError");
    const detail = String(err && err.message || "Camera blocked or unavailable");
    if (name === "NotAllowedError" || name === "PermissionDeniedError") return "Camera permission was denied. Allow camera access in the browser address-bar permissions menu.";
    if (name === "NotFoundError" || name === "DevicesNotFoundError") return "No webcam was found by the browser.";
    if (name === "NotReadableError" || name === "TrackStartError") return "The webcam is busy or blocked by another app.";
    if (name === "OverconstrainedError" || name === "ConstraintNotSatisfiedError") return "The webcam does not support the requested quality; try Low data.";
    return `${name}: ${detail}`;
  }

  async function ensureCamera() {
    if (ECHO_MEDIA.camStream) return ECHO_MEDIA.camStream;
    if (!webcamAvailable()) throw new Error(webcamUnavailableReason());
    let lastErr = null;
    let chosenQuality = ECHO_MEDIA.quality;
    for (const attempt of cameraOpenAttempts()) {
      try {
        updateStatus(attempt.quality === "browser-default" ? "Opening webcam with browser defaults…" : `Opening webcam · ${profile(attempt.quality).label || attempt.quality}…`);
        const stream = await navigator.mediaDevices.getUserMedia({ audio: false, video: attempt.constraints });
        if (attempt.quality !== "browser-default" && attempt.quality !== ECHO_MEDIA.quality) chosenQuality = saveQuality(attempt.quality);
        else chosenQuality = ECHO_MEDIA.quality;
        const track = stream.getVideoTracks()[0];
        if (track) {
          try { track.contentHint = String(profile(chosenQuality).content_hint || "motion"); } catch {}
          track.addEventListener("ended", () => {
            try { echoCamDisable("Camera stopped", { keepRoom: true }); } catch {}
          });
        }
        ECHO_MEDIA.lastCameraError = "";
        ECHO_MEDIA.lastCameraQuality = attempt.quality === "browser-default" ? "browser-default" : String(chosenQuality || attempt.quality);
        if (attempt.quality !== preferred && attempt.quality !== "browser-default") {
          safeToast(`📷 Requested quality was not supported; using ${profile(attempt.quality).label || attempt.quality}.`, "warn", 3600);
        } else if (attempt.quality === "browser-default") {
          safeToast("📷 Requested webcam constraints failed; using browser default camera settings.", "warn", 3600);
        }
        ECHO_MEDIA.camStream = stream;
        ECHO_MEDIA.camEnabled = true;
        attachLocalPreview(stream);
        return stream;
      } catch (err) {
        lastErr = err;
        if (isFatalCameraError(err)) break;
      }
    }
    ECHO_MEDIA.lastCameraError = describeCameraError(lastErr);
    throw new Error(ECHO_MEDIA.lastCameraError || "Camera blocked");
  }

  async function echoCamApplyQualityToLocalTrack() {
    const track = ECHO_MEDIA.camStream && ECHO_MEDIA.camStream.getVideoTracks && ECHO_MEDIA.camStream.getVideoTracks()[0];
    if (!track) return;
    try { track.contentHint = String(profile().content_hint || "motion"); } catch {}
    if (track.applyConstraints) {
      try { await track.applyConstraints(videoConstraints()); }
      catch (err) {
        safeToast(`📷 Could not apply that camera quality: ${describeCameraError(err)}`, "warn", 4200);
      }
    }
  }

  function codecStrategy() {
    const raw = String((ECHOCHAT_CFG && ECHOCHAT_CFG.webcam_codec_strategy) || "prefer-compatible").toLowerCase().replace(/_/g, "-");
    if (raw === "prefer-efficient" || raw === "efficient") return "prefer-efficient";
    if (raw === "prefer-quality" || raw === "quality") return "prefer-quality";
    return "prefer-compatible";
  }

  function codecPreferenceList() {
    const p = profile();
    if (Array.isArray(p.preferred_codecs) && p.preferred_codecs.length) return p.preferred_codecs.map(x => String(x).toUpperCase());
    const strategy = codecStrategy();
    if (strategy === "prefer-efficient") return ["VP9", "AV1", "H264", "VP8"];
    if (strategy === "prefer-quality") return ["H264", "VP9", "AV1", "VP8"];
    return ["H264", "VP8", "VP9", "AV1"];
  }

  function sortedVideoCodecs() {
    let codecs = [];
    try {
      const caps = (RTCRtpReceiver.getCapabilities && RTCRtpReceiver.getCapabilities("video")) || null;
      codecs = Array.isArray(caps && caps.codecs) ? caps.codecs.slice() : [];
    } catch {}
    if (!codecs.length) return [];
    const wanted = codecPreferenceList();
    const score = (c) => {
      const mt = String(c.mimeType || "").toUpperCase();
      const idx = wanted.findIndex(w => mt.includes(w));
      return idx < 0 ? 999 : idx;
    };
    return codecs.sort((a, b) => score(a) - score(b));
  }

  function applyCodecPreference(transceiver) {
    if (!transceiver || !transceiver.setCodecPreferences) return;
    const list = sortedVideoCodecs();
    if (!list.length) return;
    try { transceiver.setCodecPreferences(list); } catch {}
  }

  function applySenderParams(sender) {
    if (!sender || !sender.getParameters) return;
    const p = profile();
    const bitrate = Number(p.max_bitrate || p.maxBitrate || 550000);
    const scale = Number(p.scaleResolutionDownBy || p.scale_resolution_down_by || 1);
    try {
      const params = sender.getParameters() || {};
      if (!params.encodings || !params.encodings.length) params.encodings = [{}];
      if (Number.isFinite(bitrate) && bitrate > 0) params.encodings[0].maxBitrate = bitrate;
      if (Number.isFinite(scale) && scale > 1) params.encodings[0].scaleResolutionDownBy = scale;
      params.degradationPreference = String(p.degradationPreference || p.degradation_preference || "balanced");
      if (sender.setParameters) sender.setParameters(params).catch(() => {});
    } catch {}
  }

  function echoCamApplyQualityToAllSenders() {
    try {
      if (!VOICE_STATE || !VOICE_STATE.room || !VOICE_STATE.room.peers) return;
      VOICE_STATE.room.peers.forEach((obj) => {
        if (!obj || !obj.pc) return;
        if (obj.echoVideoTransceiver) applyCodecPreference(obj.echoVideoTransceiver);
        if (obj.echoVideoSender) applySenderParams(obj.echoVideoSender);
      });
    } catch {}
  }

  function attachCameraToPeer(pc, obj, room, peer) {
    const stream = ECHO_MEDIA.camStream;
    const track = stream && stream.getVideoTracks && stream.getVideoTracks()[0];
    if (!pc || !obj || !track) return null;
    if (!echoCamCanSendToPeer(room, peer)) return null;
    if (obj.echoVideoSender && obj.echoVideoSender.track === track) {
      applySenderParams(obj.echoVideoSender);
      return obj.echoVideoSender;
    }
    let transceiver = null;
    try {
      if (obj.echoVideoTransceiver && obj.echoVideoTransceiver.sender) {
        transceiver = obj.echoVideoTransceiver;
        obj.echoVideoSender = transceiver.sender;
        if (obj.echoVideoSender.replaceTrack) obj.echoVideoSender.replaceTrack(track).catch(() => {});
        try { transceiver.direction = "sendrecv"; } catch {}
        applyCodecPreference(transceiver);
      } else if (pc.addTransceiver) {
        transceiver = pc.addTransceiver(track, { direction: "sendrecv", streams: [stream] });
        applyCodecPreference(transceiver);
        obj.echoVideoTransceiver = transceiver;
        obj.echoVideoSender = transceiver.sender;
      } else {
        obj.echoVideoSender = pc.addTrack(track, stream);
      }
      applySenderParams(obj.echoVideoSender);
    } catch (e) {
      console.warn("camera attach failed", e);
    }
    return obj.echoVideoSender;
  }

  function attachCameraToApprovedPeers() {
    if (!ECHO_MEDIA.camStream || !VOICE_STATE || !VOICE_STATE.room || !VOICE_STATE.room.peers) return;
    const room = localRoomName();
    VOICE_STATE.room.peers.forEach((obj, peer) => {
      if (echoCamCanSendToPeer(room, peer)) attachCameraToPeer(obj && obj.pc, obj, room, peer);
    });
  }

  function removeCameraFromPeer(obj) {
    if (!obj || !obj.pc) return;
    try {
      if (obj.echoVideoTransceiver) {
        if (obj.echoVideoSender && obj.echoVideoSender.replaceTrack) obj.echoVideoSender.replaceTrack(null).catch(() => {});
        try { obj.echoVideoTransceiver.direction = "inactive"; } catch {}
        return;
      }
      if (obj.echoVideoSender) obj.pc.removeTrack(obj.echoVideoSender);
    } catch {}
    obj.echoVideoSender = null;
    obj.echoVideoTransceiver = null;
  }

  function removeCameraFromAllPeers() {
    try {
      if (!VOICE_STATE || !VOICE_STATE.room || !VOICE_STATE.room.peers) return;
      VOICE_STATE.room.peers.forEach((obj) => {
        if (!obj || !obj.pc) return;
        removeCameraFromPeer(obj);
      });
    } catch {}
  }

  function setMicTracksEnabled(on) {
    try {
      const s = VOICE_STATE && VOICE_STATE.micStream;
      if (s) s.getAudioTracks().forEach(t => { t.enabled = !!on; });
    } catch {}
  }

  function echoCamDisable(reason = "Webcam disabled", opts = {}) {
    const room = localRoomName();
    ECHO_MEDIA.camDesired = false;
    ECHO_MEDIA.comboDesired = false;
    ECHO_MEDIA.camEnabled = false;
    ECHO_MEDIA.approvedViewers.clear();
    if (room) ECHO_MEDIA.activeViewers.delete(room);
    echoCamClearIncomingRequestsForRoom(room);
    removeCameraFromAllPeers();
    if (ECHO_MEDIA.camStream) {
      try { ECHO_MEDIA.camStream.getTracks().forEach(t => t.stop()); } catch {}
    }
    ECHO_MEDIA.camStream = null;
    if (ECHO_MEDIA.localTile) {
      try { ECHO_MEDIA.localTile._echoVideo.srcObject = null; } catch {}
      try { ECHO_MEDIA.localTile.remove(); } catch {}
    }
    ECHO_MEDIA.localTile = null;
    try { echoCamUpdateLocalViewerInfo(room); } catch {}
    try { voiceUpdateLocalMediaStatus(localRoomName(), { webcam_on: false, voice_on: !!ECHO_MEDIA.voiceDesired }); } catch {}
    try { if (room) socket.emit("webcam_status", { room, camera_on: false }, () => {}); } catch {}
    try { voiceUpdateRoomCamButton(); } catch {}
    updateStatus(reason);
    if (!opts.keepRoom && !ECHO_MEDIA.voiceDesired) {
      try { voiceLeaveRoom(reason, true); } catch {}
    }
  }

  async function ensureMediaRoom(room, opts = {}) {
    room = String(room || localRoomName()).trim();
    if (!room) throw new Error("Join a room first");
    ECHO_MEDIA.echoRoom = room;
    const needAudio = opts.audio !== false;
    if (!VOICE_STATE.room.joined || VOICE_STATE.room.name !== room) {
      const res = await voiceJoinRoom(room, { silent: true, audio: needAudio, viewerOnly: opts.viewerOnly === true || !needAudio });
      if (!res || !res.success) throw new Error(res && res.error ? res.error : "Media room join failed");
    } else if (needAudio && !VOICE_STATE.micStream) {
      await voiceEnsureMic();
      try {
        VOICE_STATE.room.peers.forEach((obj) => {
          if (!obj || !obj.pc || !VOICE_STATE.micStream) return;
          const hasAudio = obj.pc.getSenders && obj.pc.getSenders().some(s => s && s.track && s.track.kind === "audio");
          if (!hasAudio) VOICE_STATE.micStream.getTracks().forEach(t => obj.pc.addTrack(t, VOICE_STATE.micStream));
          voiceApplySenderQuality(obj.pc);
        });
      } catch {}
    }
    return room;
  }

  async function toggleVoiceForRoom(room) {
    room = String(room || localRoomName()).trim();
    if (!room) throw new Error("Join a room first");
    if (ECHO_MEDIA.voiceDesired && ECHO_MEDIA.echoRoom === room) {
      ECHO_MEDIA.voiceDesired = false;
      ECHO_MEDIA.micEnabled = false;
      try { VOICE_STATE.room.wantRoomVoice = false; } catch {}
      try { sessionStorage.removeItem("echochat_voice_desired"); } catch {}
      try { voiceRemoveRoomAudioSenders(); } catch {}
      setMicTracksEnabled(false);
      try { voiceStopMicOnly(); } catch { try { voiceSetMute(true); } catch {} }
      try { voiceUpdateLocalMediaStatus(room, { voice_on: false, webcam_on: !!ECHO_MEDIA.camDesired }); } catch {}
      if (!ECHO_MEDIA.camDesired) {
        try { voiceLeaveRoom("Voice disabled", true); } catch {}
      } else {
        safeToast("🔇 Voice disabled; webcam still on", "info", 2200);
      }
      try { voiceUpdateRoomVoiceButton(); } catch {}
      return { success: true, voice: false, webcam: !!ECHO_MEDIA.camDesired };
    }
    await ensureMediaRoom(room, { audio: true });
    ECHO_MEDIA.voiceDesired = true;
    ECHO_MEDIA.micEnabled = true;
    ECHO_MEDIA.echoRoom = room;
    setMicTracksEnabled(true);
    try { voiceSetMute(false); voiceApplyTalkMode({ silent: true }); } catch {}
    try { voiceUpdateLocalMediaStatus(room, { voice_on: true, webcam_on: !!ECHO_MEDIA.camDesired }); } catch {}
    try { voiceUpdateRoomVoiceButton(); } catch {}
    safeToast("🎤 Voice connected", "info", 1600);
    return { success: true, voice: true, webcam: !!ECHO_MEDIA.camDesired };
  }

  async function toggleCamForRoom(room) {
    room = String(room || localRoomName()).trim();
    if (!room) throw new Error("Join a room first");
    if (ECHO_MEDIA.camDesired && ECHO_MEDIA.echoRoom === room) {
      echoCamDisable("Webcam disabled", { keepRoom: !!ECHO_MEDIA.voiceDesired });
      safeToast("📷 Webcam disabled", "info", 1600);
      return { success: true, webcam: false, voice: !!ECHO_MEDIA.voiceDesired };
    }
    await ensureMediaRoom(room, { audio: !!ECHO_MEDIA.voiceDesired });
    // A webcam-only click must not turn on voice, store voice reconnect flags,
    // or request a microphone. Voice is enabled only by the Voice button.
    if (!ECHO_MEDIA.voiceDesired) {
      try { VOICE_STATE.room.wantRoomVoice = false; } catch {}
      try { sessionStorage.removeItem("echochat_voice_desired"); } catch {}
      try { voiceUpdateLocalMediaStatus(room, { voice_on: false, webcam_on: !!ECHO_MEDIA.camDesired }); } catch {}
    }
    await ensureCamera();
    ECHO_MEDIA.camDesired = true;
    ECHO_MEDIA.camEnabled = true;
    ECHO_MEDIA.echoRoom = room;
    attachCameraToApprovedPeers();
    try { socket.emit("webcam_status", { room, camera_on: true }, () => {}); } catch {}
    try { voiceUpdateLocalMediaStatus(room, { webcam_on: true, voice_on: !!ECHO_MEDIA.voiceDesired }); } catch {}
    try { voiceUpdateRoomCamButton(); } catch {}
    updateStatus(`Webcam on · ${profile().label || ECHO_MEDIA.quality}`);
    safeToast("📷 Webcam enabled", "info", 1600);
    return { success: true, webcam: true, voice: !!ECHO_MEDIA.voiceDesired };
  }

  async function toggleBothForRoom(room) {
    room = String(room || localRoomName()).trim();
    if (ECHO_MEDIA.voiceDesired && ECHO_MEDIA.camDesired && ECHO_MEDIA.echoRoom === room) {
      await leave("Voice/webcam disabled");
      return { success: true, voice: false, webcam: false };
    }
    await ensureMediaRoom(room, { audio: true });
    ECHO_MEDIA.voiceDesired = true;
    ECHO_MEDIA.micEnabled = true;
    setMicTracksEnabled(true);
    await ensureCamera();
    ECHO_MEDIA.camDesired = true;
    ECHO_MEDIA.camEnabled = true;
    ECHO_MEDIA.comboDesired = true;
    attachCameraToApprovedPeers();
    try { socket.emit("webcam_status", { room, camera_on: true }, () => {}); } catch {}
    try { voiceUpdateLocalMediaStatus(room, { voice_on: true, webcam_on: true }); } catch {}
    try { voiceUpdateRoomVoiceButton(); voiceUpdateRoomCamButton(); } catch {}
    updateStatus(`Voice + webcam · ${profile().label || ECHO_MEDIA.quality}`);
    return { success: true, voice: true, webcam: true };
  }

  async function toggleMic() {
    if (!ECHO_MEDIA.voiceDesired && !(VOICE_STATE && VOICE_STATE.micStream)) return null;
    const muted = !VOICE_STATE.micMuted;
    try { voiceSetMute(muted); } catch {}
    ECHO_MEDIA.micEnabled = !muted;
    safeToast(muted ? "🔇 Mic muted" : "🎤 Mic unmuted", "info", 1600);
    return { success: true, muted };
  }

  async function toggleCam() {
    const room = localRoomName();
    return toggleCamForRoom(room);
  }

  async function switchRoomIfMediaDesired(room) {
    room = String(room || "").trim();
    if (!room) return null;
    const wantVoice = !!ECHO_MEDIA.voiceDesired;
    const wantCam = !!ECHO_MEDIA.camDesired;
    if (!wantVoice && !wantCam) return null;
    const previousRoom = String(ECHO_MEDIA.echoRoom || (VOICE_STATE && VOICE_STATE.room && VOICE_STATE.room.name) || "").trim();
    const switchingRooms = !!(previousRoom && previousRoom !== room);
    const oldCam = ECHO_MEDIA.camStream;
    if (switchingRooms) {
      // Clear old-room webcam permissions/status before moving the active camera
      // to the new room.  Without this, old-room users can keep seeing stale
      // webcam-on badges and previously approved viewers can be reused.
      try { if (wantCam) socket.emit("webcam_status", { room: previousRoom, camera_on: false }, () => {}); } catch {}
      try { voiceUpdateLocalMediaStatus(previousRoom, { voice_on: false, webcam_on: false }); } catch {}
      try { echoCamClearIncomingRequestsForRoom(previousRoom); } catch {}
      ECHO_MEDIA.approvedViewers.clear();
      ECHO_MEDIA.requestedViewers.clear();
      clearRemoteVideos();
    }
    await ensureMediaRoom(room, { audio: wantVoice });
    ECHO_MEDIA.echoRoom = room;
    if (wantCam && oldCam) {
      attachCameraToApprovedPeers();
      try { socket.emit("webcam_status", { room, camera_on: true }, () => {}); } catch {}
    }
    try { voiceUpdateLocalMediaStatus(room, { voice_on: wantVoice, webcam_on: wantCam }); } catch {}
    return { success: true, room, voice: wantVoice, webcam: wantCam };
  }

  async function leave(reason = "Media disabled", opts = {}) {
    ECHO_MEDIA.voiceDesired = !!(opts && opts.preserveDesired && ECHO_MEDIA.voiceDesired);
    ECHO_MEDIA.micEnabled = false;
    const hadCam = !!ECHO_MEDIA.camDesired;
    echoCamDisable(reason, { keepRoom: false });
    if (!opts || !opts.preserveDesired) ECHO_MEDIA.voiceDesired = false;
    try { voiceLeaveRoom(reason, true, { silent: !!(opts && opts.silent) }); } catch {}
    clearRemoteVideos();
    if (ECHO_MEDIA.panel && !hadCam) updateStatus(reason);
    return { success: true };
  }


  function echoSocketAck(event, payload) {
    return new Promise((resolve) => {
      try {
        if (!socket || !socket.emit) return resolve({ success: false, error: "Socket is not connected" });
        socket.emit(event, payload || {}, (ack) => resolve(ack || {}));
      } catch (err) {
        resolve({ success: false, error: err && err.message ? err.message : String(err || "socket_error") });
      }
    });
  }

  function echoCamOwnerHasWebcamOn(owner, room) {
    owner = String(owner || "").trim();
    room = String(room || localRoomName()).trim();
    if (!owner || owner === String(currentUser || "").trim() || !room) return false;
    try {
      if (typeof voiceStatusForUser !== "function") return true;
      const st = voiceStatusForUser(owner, room);
      return !!(st && st.webcam_on);
    } catch {
      return false;
    }
  }

  async function echoJoinMediaRoomForViewing(owner, room) {
    owner = String(owner || "").trim();
    room = String(room || localRoomName()).trim();
    if (!owner || !room) return { success: false, error: "Missing webcam owner or room" };
    const alreadyInRoom = !!(VOICE_STATE.room.joined && VOICE_STATE.room.name === room);
    const preserveVoice = alreadyInRoom && !!(ECHO_MEDIA.voiceDesired || VOICE_STATE.room.wantRoomVoice);
    if (!alreadyInRoom) {
      const res = await voiceJoinRoom(room, { silent: true, audio: false, viewerOnly: true });
      if (!res || !res.success) return res || { success: false, error: "Media room join failed" };
    }
    ECHO_MEDIA.echoRoom = room;
    ECHO_MEDIA.requestedViewers.add(echoCamKey(room, owner));
    if (!preserveVoice) {
      try { VOICE_STATE.room.wantRoomVoice = false; } catch {}
      try { sessionStorage.removeItem("echochat_voice_desired"); } catch {}
      try { voiceUpdateLocalMediaStatus(room, { voice_on: false, webcam_on: !!ECHO_MEDIA.camDesired }); } catch {}
    }
    try {
      if (!VOICE_STATE.room.peers.has(owner) && typeof voiceRoomEnsurePeer === "function") voiceRoomEnsurePeer(room, owner);
    } catch {}
    showPanel();
    updateStatus(`Opening ${owner}'s webcam…`);
    try { socket.emit("webcam_viewing", { room, owner, viewing: true }, () => {}); } catch {}
    return { success: true, owner, room };
  }

  async function echoRequestRemoteCamFromRoomUser(owner, roomName) {
    owner = String(owner || "").trim();
    const room = String(roomName || localRoomName()).trim();
    if (!owner || !room) {
      safeToast("📷 Join a room before viewing webcams.", "warn");
      return { success: false, error: "missing_room_or_owner" };
    }
    if (owner === String(currentUser || "").trim()) {
      safeToast("📷 Use the webcam button to preview your own camera.", "info");
      return { success: false, error: "self_webcam" };
    }
    if (!echoCamOwnerHasWebcamOn(owner, room)) {
      safeToast(`${owner} does not have webcam on right now.`, "warn", 2600);
      return { success: false, error: "webcam_off" };
    }

    safeToast(`📷 Requesting ${owner}'s webcam…`, "info", 1800);
    const ack = await echoSocketAck("webcam_view_request", { room, owner });
    if (!ack || !ack.success) {
      safeToast(`❌ Webcam request failed: ${ack && ack.error ? ack.error : "not delivered"}`, "error", 5000);
      return ack || { success: false, error: "webcam_request_failed" };
    }
    if (ack.allowed || ack.auto_allowed || (ack.policy && ack.policy.webcam_approval_mode === "open")) {
      const opened = await echoJoinMediaRoomForViewing(owner, room);
      if (opened && opened.success) safeToast(`📷 Viewing ${owner}'s webcam`, "ok", 2200);
      return { ...ack, opened: !!(opened && opened.success) };
    }
    safeToast(`📷 Requested ${owner}'s webcam. Waiting for approval.`, "info", 3600);
    return ack;
  }

  async function echoRespondToCamViewRequest(room, viewer, allowed) {
    room = String(room || localRoomName()).trim();
    viewer = String(viewer || "").trim();
    if (!room || !viewer || viewer === String(currentUser || "").trim()) return;
    const ack = await echoSocketAck("webcam_view_response", { room, viewer, allowed: !!allowed });
    if (!ack || !ack.success) {
      safeToast(`❌ Webcam response failed: ${ack && ack.error ? ack.error : "not delivered"}`, "error", 4500);
      return ack;
    }
    echoCamRemoveIncomingRequest(room, viewer);
    echoCamSetViewerApproved(room, viewer, !!allowed);
    if (Array.isArray(ack.viewers)) echoCamReplaceActiveViewers(room, ack.viewers);
    if (allowed) {
      try {
        const obj = VOICE_STATE && VOICE_STATE.room && VOICE_STATE.room.peers && VOICE_STATE.room.peers.get(viewer);
        if (obj) attachCameraToPeer(obj.pc, obj, room, viewer);
      } catch {}
    } else {
      try {
        const obj = VOICE_STATE && VOICE_STATE.room && VOICE_STATE.room.peers && VOICE_STATE.room.peers.get(viewer);
        if (obj) removeCameraFromPeer(obj);
      } catch {}
    }
    safeToast(allowed ? `📷 Allowed ${viewer} to view your webcam` : `📷 Denied ${viewer}'s webcam request`, allowed ? "ok" : "info", 2600);
    return ack;
  }

  function wireEchoWebcamViewEvents() {
    if (!socket || socket._echoWebcamViewEventsBound) return;
    socket._echoWebcamViewEventsBound = true;

    socket.on("webcam_view_request", (payload = {}) => {
      const room = String(payload.room || localRoomName()).trim();
      const viewer = String(payload.viewer || "").trim();
      if (!room || !viewer || viewer === String(currentUser || "").trim()) return;
      const localCamOn = !!(ECHO_MEDIA.camDesired || ECHO_MEDIA.camEnabled);
      if (!localCamOn) {
        echoRespondToCamViewRequest(room, viewer, false);
        return;
      }
      echoCamUpsertIncomingRequest(room, viewer, payload.policy || null);
      safeToast(`📷 Webcam request from ${viewer} is waiting in Alerts.`, "info", 5000);
      try { if (typeof maybeBrowserNotify === "function") maybeBrowserNotify("Webcam request", `${viewer} wants to view your webcam in ${room}`); } catch {}
    });

    socket.on("webcam_view_response", async (payload = {}) => {
      const room = String(payload.room || localRoomName()).trim();
      const owner = String(payload.owner || "").trim();
      if (!room || !owner || owner === String(currentUser || "").trim()) return;
      if (Array.isArray(payload.viewers) && owner === String(currentUser || "").trim()) echoCamReplaceActiveViewers(room, payload.viewers);
      if (payload.allowed) {
        const opened = await echoJoinMediaRoomForViewing(owner, room);
        if (opened && opened.success) safeToast(`📷 Viewing ${owner}'s webcam`, "ok", 2200);
      } else {
        safeToast(`📷 ${owner} denied the webcam request.`, "warn", 3200);
      }
    });

    socket.on("webcam_view_kick", (payload = {}) => {
      const owner = String(payload.owner || "").trim();
      if (Array.isArray(payload.viewers) && owner === String(currentUser || "").trim()) echoCamReplaceActiveViewers(String(payload.room || localRoomName()).trim(), payload.viewers);
      if (owner) echoCamRemoveRemoteVideo(owner);
      safeToast(owner ? `📷 ${owner} stopped your webcam view.` : "📷 Webcam view stopped.", "info", 3200);
    });


    socket.on("webcam_viewing", (payload = {}) => {
      const room = String(payload.room || localRoomName()).trim();
      const viewer = String(payload.viewer || "").trim();
      const viewing = payload.viewing !== false && String(payload.viewing).toLowerCase() !== "false";
      if (!room || !viewer || viewer === String(currentUser || "").trim()) return;
      if (Array.isArray(payload.viewers)) echoCamReplaceActiveViewers(room, payload.viewers);
      else echoCamSetActiveViewing(room, viewer, viewing);
      if (viewing) echoCamRemoveIncomingRequest(room, viewer);
      echoCamSetViewerApproved(room, viewer, viewing);
      try {
        const obj = VOICE_STATE && VOICE_STATE.room && VOICE_STATE.room.peers && VOICE_STATE.room.peers.get(viewer);
        if (viewing) {
          if (!obj && VOICE_STATE && VOICE_STATE.room && VOICE_STATE.room.joined && VOICE_STATE.room.name === room && typeof voiceRoomEnsurePeer === "function") voiceRoomEnsurePeer(room, viewer);
          const nextObj = VOICE_STATE && VOICE_STATE.room && VOICE_STATE.room.peers && VOICE_STATE.room.peers.get(viewer);
          if (nextObj) attachCameraToPeer(nextObj.pc, nextObj, room, viewer);
        } else if (obj) {
          removeCameraFromPeer(obj);
        }
      } catch {}
    });

    socket.on("webcam_status", (payload = {}) => {
      const owner = String(payload.owner || "").trim();
      const room = String(payload.room || localRoomName()).trim();
      if (Array.isArray(payload.viewers) && owner === String(currentUser || "").trim()) echoCamReplaceActiveViewers(room, payload.viewers);
      if (owner && payload.camera_on === false) {
        ECHO_MEDIA.requestedViewers.delete(echoCamKey(room, owner));
        echoCamRemoveRemoteVideo(owner);
      }
    });
  }

  function snapshot() {
    return {
      engine: "echo",
      connected: !!(VOICE_STATE && VOICE_STATE.room && VOICE_STATE.room.joined),
      echoRoom: localRoomName(),
      voiceDesired: !!ECHO_MEDIA.voiceDesired,
      camDesired: !!ECHO_MEDIA.camDesired,
      comboDesired: !!ECHO_MEDIA.comboDesired,
      micEnabled: !!(ECHO_MEDIA.voiceDesired && !VOICE_STATE.micMuted),
      camEnabled: !!ECHO_MEDIA.camEnabled,
      quality: ECHO_MEDIA.quality,
      lastCameraQuality: ECHO_MEDIA.lastCameraQuality || "",
      viewers: echoCamViewerSummary(localRoomName()).viewers,
      viewerCount: echoCamViewerSummary(localRoomName()).viewerCount,
      lastCameraError: ECHO_MEDIA.lastCameraError || "",
    };
  }

  async function refreshModeFromServer() {
    let resp = null;
    let j = {};
    try {
      resp = await (typeof fetchWithAuth === "function" ? fetchWithAuth("/api/av/mode") : fetch("/api/av/mode"));
      j = typeof ecReadApiJson === "function" ? await ecReadApiJson(resp) : await resp.json().catch(() => ({}));
      if (resp && !resp.ok && typeof ecApiErrorMessage === "function") {
        throw new Error(ecApiErrorMessage(resp, j, 'Media mode request failed'));
      }
      if (j && j.client_config && j.client_config.webcam_quality) saveQuality(j.client_config.webcam_quality);
      else if (j && j.webcam_quality) saveQuality(j.webcam_quality);
      return j;
    } catch (err) {
      if (typeof ecApiErrorMessage === "function" && resp) {
        console.warn(ecApiErrorMessage(resp, j, 'Media mode request failed'));
      }
      return { ok: true, av_mode: "echo", reason: "offline_client_default", error: err && err.message ? err.message : String(err || "") };
    }
  }

  wireEchoWebcamViewEvents();

  window.echoCamAttachRemoteVideo = echoCamAttachRemoteVideo;
  window.echoCamRemoveRemoteVideo = echoCamRemoveRemoteVideo;
  window.echoCamAttachTrackToPeer = attachCameraToPeer;
  window.echoCamCanReceiveFromPeer = echoCamCanReceiveFromPeer;
  window.echoCamCanSendToPeer = echoCamCanSendToPeer;
  window.echoCamSetViewerApproved = echoCamSetViewerApproved;
  window.echoCamSetActiveViewing = echoCamSetActiveViewing;
  window.echoCamReplaceActiveViewers = echoCamReplaceActiveViewers;
  window.echoCamViewerSummary = echoCamViewerSummary;
  window.echoCamUpsertIncomingRequest = echoCamUpsertIncomingRequest;
  window.echoCamRemoveIncomingRequest = echoCamRemoveIncomingRequest;
  window.echoRespondToCamViewRequest = echoRespondToCamViewRequest;
  window.echoCamApplyQualityToAllSenders = echoCamApplyQualityToAllSenders;
  window.echoCamApplyQualityToLocalTrack = echoCamApplyQualityToLocalTrack;
  window.echoCamDisable = echoCamDisable;
  window.echoRequestRemoteCamFromRoomUser = echoRequestRemoteCamFromRoomUser;

  try {
    if (typeof ecRegisterMediaEngine === "function") {
      ecRegisterMediaEngine({
        id: "echo",
        label: "Echo built-in media",
        ready,
        webcamAvailable,
        webcamUnavailableReason,
        refreshModeFromServer,
        snapshot,
        toggleVoiceForRoom,
        toggleCamForRoom,
        toggleBothForRoom,
        toggleMic,
        toggleCam,
        switchRoomIfMediaDesired,
        leave,
        isConnectedToRoom: (room) => String(localRoomName()) === String(room || "") && !!(VOICE_STATE && VOICE_STATE.room && VOICE_STATE.room.joined),
      }, { active: true });
      if (typeof ecMediaSetActive === "function") ecMediaSetActive("echo");
    }
  } catch (e) {
    console.warn("Echo media engine registration failed", e);
  }
})();
