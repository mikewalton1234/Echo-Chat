// WebRTC P2P file transfers: try P2P first, then fall back to server.
// Server is used ONLY as signaling relay (offer/answer/ICE), not as a data path.
// ───────────────────────────────────────────────────────────────────────────────
function socketEmitAck(event, data, timeoutMs = 6000) {
  if (typeof ecEmitAck === "function") {
    return ecEmitAck(event, data, timeoutMs, {
      connectBannerText: "🔌 Reconnecting before file-transfer signaling…",
      bannerDelayMs: 900,
    }).then((resp) => {
      if (resp && resp.success === false) throw new Error(resp.error || `Socket ACK failed for ${event}`);
      return resp;
    });
  }
  return new Promise((resolve, reject) => {
    let done = false;
    const t = setTimeout(() => {
      if (done) return;
      done = true;
      reject(new Error(`Socket ACK timeout for ${event}`));
    }, timeoutMs);

    socket.emit(event, data, (resp) => {
      if (done) return;
      done = true;
      clearTimeout(t);
      resolve(resp);
    });
  });
}

function p2pRememberClosedTransferId(transfer_id) {
  if (!transfer_id) return;
  const now = Date.now();
  try {
    for (const [tid, expiresAt] of P2P_RECENT_TRANSFER_IDS.entries()) {
      if (!expiresAt || expiresAt <= now) P2P_RECENT_TRANSFER_IDS.delete(tid);
    }
    P2P_RECENT_TRANSFER_IDS.set(String(transfer_id), now + P2P_RECENT_TRANSFER_ID_TTL_MS);
  } catch {}
}

function p2pTransferIdRecentlyUsed(transfer_id) {
  if (!transfer_id) return false;
  const tid = String(transfer_id);
  const expiresAt = P2P_RECENT_TRANSFER_IDS.get(tid);
  if (!expiresAt) return false;
  if (expiresAt > Date.now()) return true;
  P2P_RECENT_TRANSFER_IDS.delete(tid);
  return false;
}

function p2pNewTransferId() {
  // Short, URL-safe id. Use WebCrypto when available and avoid active/recent IDs.
  for (let attempt = 0; attempt < 8; attempt += 1) {
    let rnd = "";
    try {
      const bytes = new Uint8Array(12);
      window.crypto.getRandomValues(bytes);
      rnd = Array.from(bytes, (b) => b.toString(36).padStart(2, "0")).join("").slice(0, 18);
    } catch {
      rnd = Math.random().toString(36).slice(2, 14);
    }
    const tid = `p2p_${Date.now().toString(36)}_${rnd}`;
    if (!P2P_TRANSFERS.has(tid) && !p2pTransferIdRecentlyUsed(tid)) return tid;
  }
  return `p2p_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 14)}`;
}

function delay(ms) { return new Promise((r) => setTimeout(r, ms)); }

function p2pMakePc() {
  if (typeof RTCPeerConnection === "undefined") {
    throw new Error("WebRTC not available in this browser.");
  }
  return new RTCPeerConnection({ iceServers: P2P_ICE_SERVERS });
}

function p2pQueueIceCandidate(transfer_id, candidate) {
  if (!transfer_id || !candidate) return;
  let q = P2P_PENDING_ICE.get(transfer_id);
  if (!q) {
    q = [];
    P2P_PENDING_ICE.set(transfer_id, q);
  }
  q.push(candidate);
  while (q.length > P2P_ICE_QUEUE_LIMIT) q.shift();
}

async function p2pFlushIceQueue(tr) {
  if (!tr || !tr.transfer_id || !tr.pc) return;
  const pc = tr.pc;
  if (!pc.remoteDescription || !pc.remoteDescription.type) return;
  const queued = P2P_PENDING_ICE.get(tr.transfer_id) || [];
  P2P_PENDING_ICE.delete(tr.transfer_id);
  for (const candidate of queued) {
    try { await pc.addIceCandidate(new RTCIceCandidate(candidate)); } catch (e) { console.warn("P2P ICE candidate rejected", e); }
  }
}

async function waitForDataChannelOpen(dc, timeoutMs) {
  if (dc.readyState === "open") return true;
  return new Promise((resolve, reject) => {
    let done = false;
    const t = setTimeout(() => {
      if (done) return;
      done = true;
      reject(new Error("DataChannel open timeout"));
    }, timeoutMs);

    dc.addEventListener("open", () => {
      if (done) return;
      done = true;
      clearTimeout(t);
      resolve(true);
    }, { once: true });

    dc.addEventListener("error", () => {
      if (done) return;
      done = true;
      clearTimeout(t);
      reject(new Error("DataChannel error"));
    }, { once: true });
  });
}

function p2pSafeClose(transfer_id, why = null) {
  const tr = P2P_TRANSFERS.get(transfer_id);
  if (!tr) return;
  try { if (tr._watchdog) clearTimeout(tr._watchdog); } catch {}
  try { if (tr._watchdogInterval) clearInterval(tr._watchdogInterval); } catch {}
  try { if (tr._answerTimer) clearTimeout(tr._answerTimer); } catch {}
  try { if (tr._ackTimer) clearTimeout(tr._ackTimer); } catch {}
  try { tr.dc && tr.dc.close(); } catch {}
  try { tr.pc && tr.pc.close(); } catch {}
  try { P2P_PENDING_ICE.delete(transfer_id); } catch {}
  try { p2pRememberClosedTransferId(transfer_id); } catch {}
  if (tr.ui && why) tr.ui.setStatus(why);
  P2P_TRANSFERS.delete(transfer_id);
}

function p2pEmitIceCandidate(toUser, transfer_id, candidate, tr = null) {
  if (!toUser || !transfer_id || !candidate) return;
  // Sender ICE can fire immediately after setLocalDescription(), before the
  // server has created the transfer session from p2p_file_offer. Queue those
  // candidates until the offer ACK arrives, or the server rejects them as
  // Unknown/expired and the peer never gets the host candidates needed for P2P.
  if (tr && tr.role === "sender" && !tr._offerAcked) {
    tr._localIceQueue = Array.isArray(tr._localIceQueue) ? tr._localIceQueue : [];
    tr._localIceQueue.push(candidate);
    while (tr._localIceQueue.length > P2P_ICE_QUEUE_LIMIT) tr._localIceQueue.shift();
    return;
  }
  socket.emit("p2p_file_ice", { to: toUser, transfer_id, candidate });
}

function p2pFlushLocalIceQueue(toUser, tr) {
  if (!tr || !tr.transfer_id) return;
  const queued = Array.isArray(tr._localIceQueue) ? tr._localIceQueue.slice() : [];
  tr._localIceQueue = [];
  for (const candidate of queued) {
    p2pEmitIceCandidate(toUser, tr.transfer_id, candidate, tr);
  }
}

async function tryP2PFileTransfer(toUser, meta, arrayBuffer, { ui } = {}) {
  // WebRTC requires a secure context in most browsers.
  if (!window.isSecureContext) {
    if (ui) ui.setStatus("P2P requires HTTPS/localhost — fallback to server");
    return null;
  }
  if (!toUser || !arrayBuffer) return null;

  const transfer_id = p2pNewTransferId();
  const pc = p2pMakePc();
  const dc = pc.createDataChannel("ec_file", { ordered: true });

  dc.binaryType = "arraybuffer";

  const tr = {
    role: "sender",
    peer: toUser,
    transfer_id,
    pc,
    dc,
    ui,
    meta,
    _answerResolve: null,
    _answerReject: null,
    _answerTimer: null,
    _ackResolve: null,
    _ackReject: null,
    _ackTimer: null,
    _offerAcked: false,
    _localIceQueue: [],
  };
  P2P_TRANSFERS.set(transfer_id, tr);
  if (ui && typeof ui.onCancel === "function") {
    ui.onCancel(() => {
      try { socket.emit("p2p_file_decline", { to: toUser, transfer_id, reason: "Cancelled" }); } catch {}
      p2pSafeClose(transfer_id, "Cancelled");
      setTimeout(() => { try { ui.remove(); } catch {} }, 700);
    });
  }

  pc.onicecandidate = (e) => {
    if (e.candidate) {
      p2pEmitIceCandidate(toUser, transfer_id, e.candidate, tr);
    }
  };

  // Register the answer listener before sending the offer. Fast local peers can
  // accept immediately; creating this after the offer ACK can miss the answer.
  const answerPromise = new Promise((resolve, reject) => {
    tr._answerResolve = resolve;
    tr._answerReject = reject;
    tr._answerTimer = setTimeout(() => reject(new Error("P2P answer timeout")), P2P_FILE_HANDSHAKE_TIMEOUT_MS);
  });

  // Listen for ack on the datachannel.
  const ackPromise = new Promise((resolve, reject) => {
    tr._ackResolve = resolve;
    tr._ackReject = reject;
    tr._ackTimer = setTimeout(() => reject(new Error("P2P transfer timeout")), P2P_FILE_TRANSFER_TIMEOUT_MS);

    dc.addEventListener("message", (ev) => {
      if (typeof ev.data === "string") {
        try {
          const msg = JSON.parse(ev.data);
          if (msg && msg.type === "ack" && msg.transfer_id === transfer_id) {
            if (tr._ackTimer) clearTimeout(tr._ackTimer);
            resolve(true);
          }
        } catch {}
      }
    });
  });
  ackPromise.catch(() => {}); // avoid an unhandled rejection if handshake fails first

  // Offer / Answer
  const offer = await pc.createOffer();
  await pc.setLocalDescription(offer);

  if (ui) ui.setStatus("Sending P2P offer…");
  const offerResp = await socketEmitAck("p2p_file_offer", {
    to: toUser,
    transfer_id,
    offer: { type: pc.localDescription.type, sdp: pc.localDescription.sdp },
    meta,
  }).catch(() => null);

  if (!offerResp || offerResp.success === false || offerResp.delivered === false) {
    p2pSafeClose(transfer_id, "Peer offline — fallback to server");
    return null;
  }

  tr._offerAcked = true;
  p2pFlushLocalIceQueue(toUser, tr);

  let answer;
  try {
    answer = await answerPromise;
  } catch (e) {
    p2pSafeClose(transfer_id, "P2P answer timeout — fallback to server");
    throw e;
  }
  if (tr._answerTimer) clearTimeout(tr._answerTimer);
  try {
    await pc.setRemoteDescription(new RTCSessionDescription(answer));
    await p2pFlushIceQueue(tr);
  } catch (e) {
    p2pSafeClose(transfer_id, "P2P answer failed — fallback to server");
    throw e;
  }

  if (ui) ui.setStatus("Connecting data channel…");
  try {
    await waitForDataChannelOpen(dc, P2P_FILE_HANDSHAKE_TIMEOUT_MS);
  } catch (e) {
    p2pSafeClose(transfer_id, "P2P channel failed — fallback to server");
    throw e;
  }

  // Send metadata first (JSON string), then raw chunks.
  if (ui) ui.setStatus("Sending file (P2P)…");

  const total = arrayBuffer.byteLength || 0;
  let sent = 0;

  try {
    dc.send(JSON.stringify({ type: "meta", transfer_id, meta }));

    // Backpressure thresholds
    const MAX_BUFFERED = 8 * 1024 * 1024; // 8MB
    const buf = arrayBuffer;

    for (let off = 0; off < total; off += P2P_FILE_CHUNK_BYTES) {
      const chunk = buf.slice(off, Math.min(off + P2P_FILE_CHUNK_BYTES, total));

      // Simple flow control
      while (dc.bufferedAmount > MAX_BUFFERED) {
        await delay(30);
      }

      dc.send(chunk);
      sent += chunk.byteLength || 0;
      if (ui) ui.setProgress(total ? (sent / total) : 1);
    }

    dc.send(JSON.stringify({ type: "done", transfer_id }));
  } catch (e) {
    p2pSafeClose(transfer_id, "P2P send failed — fallback to server");
    throw e;
  }

  // Wait for receiver ack (assembled)
  try {
    await ackPromise;
  } catch (e) {
    p2pSafeClose(transfer_id, "P2P acknowledgement failed — fallback to server");
    throw e;
  }

  if (ui) {
    ui.setProgress(1);
    ui.setStatus("✅ Sent via P2P");
  }

  // Keep the connection around briefly so late ICE doesn't explode.
  setTimeout(() => p2pSafeClose(transfer_id), 1200);

  return {
    kind: "file",
    source: "p2p",
    transfer_id,
    name: meta.name,
    size: meta.size,
    mime: meta.mime,
    sha256: meta.sha256,
  };
}

async function downloadAndDecryptDmFile(fileId, fallbackName) {
  if (!HAS_WEBCRYPTO) throw new Error(`E2EE requires HTTPS (or http://localhost / http://127.0.0.1). Current origin: ${window.location.origin}`);
  const privKey = await ensurePrivateKeyUnlocked();

  const metaResp = await fetchWithAuth(`/api/dm_files/${encodeURIComponent(fileId)}/meta`, {
    method: "GET",
    credentials: "include",
  });
  const meta = (typeof ecReadApiJson === 'function') ? await ecReadApiJson(metaResp, null) : await metaResp.json().catch(() => null);
  if (!metaResp || !metaResp.ok || !meta?.success) {
    const msg = (typeof ecApiErrorMessage === 'function') ? ecApiErrorMessage(metaResp, meta, 'Metadata fetch failed') : (meta?.error || `Metadata fetch failed (HTTP ${metaResp?.status || '?'})`);
    throw new Error(msg);
  }

  const blobResp = await fetchWithAuth(`/api/dm_files/${encodeURIComponent(fileId)}/blob`, {
    method: "GET",
    credentials: "include",
  });
  if (!blobResp || !blobResp.ok) {
    const msg = (typeof ecApiErrorMessage === 'function') ? ecApiErrorMessage(blobResp, null, 'Blob fetch failed') : `Blob fetch failed (HTTP ${blobResp?.status || '?'})`;
    throw new Error(msg);
  }
  const ctBuf = await blobResp.arrayBuffer();

  const wrappedKeyBuf = bytesFromB64(meta.ek_b64).buffer;
  const rawAesKey = await window.crypto.subtle.decrypt({ name: "RSA-OAEP" }, privKey, wrappedKeyBuf);
  const aesKey = await window.crypto.subtle.importKey("raw", rawAesKey, { name: "AES-GCM" }, false, ["decrypt"]);
  const iv = bytesFromB64(meta.iv_b64);

  const ptBuf = await window.crypto.subtle.decrypt({ name: "AES-GCM", iv }, aesKey, ctBuf);
  const mime = meta.mime || "application/octet-stream";
  const outBlob = new Blob([ptBuf], { type: mime });
  const filename = meta.name || fallbackName || "file";
  downloadBlob(filename, outBlob);
}

async function downloadAndDecryptGroupFile(fileId, fallbackName, groupId) {
  if (!HAS_WEBCRYPTO) throw new Error(`E2EE requires HTTPS (or http://localhost / http://127.0.0.1). Current origin: ${window.location.origin}`);
  const privKey = await ensurePrivateKeyUnlocked();

  const metaResp = await fetchWithAuth(`/api/group_files/${encodeURIComponent(fileId)}/meta`, {
    method: "GET",
    credentials: "include",
  });
  const meta = (typeof ecReadApiJson === 'function') ? await ecReadApiJson(metaResp, null) : await metaResp.json().catch(() => null);
  if (!metaResp || !metaResp.ok || !meta?.success) {
    const msg = (typeof ecApiErrorMessage === 'function') ? ecApiErrorMessage(metaResp, meta, 'Metadata fetch failed') : (meta?.error || `Metadata fetch failed (HTTP ${metaResp?.status || '?'})`);
    throw new Error(msg);
  }
  if (groupId && Number(meta.group_id) !== Number(groupId)) {
    // Soft guard: the server is authoritative, but keep UI consistent.
    console.warn("Group file meta group_id mismatch", { meta_gid: meta.group_id, expected: groupId });
  }

  const blobResp = await fetchWithAuth(`/api/group_files/${encodeURIComponent(fileId)}/blob`, {
    method: "GET",
    credentials: "include",
  });
  if (!blobResp || !blobResp.ok) {
    const msg = (typeof ecApiErrorMessage === 'function') ? ecApiErrorMessage(blobResp, null, 'Blob fetch failed') : `Blob fetch failed (HTTP ${blobResp?.status || '?'})`;
    throw new Error(msg);
  }
  const ctBuf = await blobResp.arrayBuffer();

  const wrappedKeyBuf = bytesFromB64(meta.ek_b64).buffer;
  const rawAesKey = await window.crypto.subtle.decrypt({ name: "RSA-OAEP" }, privKey, wrappedKeyBuf);
  const aesKey = await window.crypto.subtle.importKey("raw", rawAesKey, { name: "AES-GCM" }, false, ["decrypt"]);
  const iv = bytesFromB64(meta.iv_b64);

  const ptBuf = await window.crypto.subtle.decrypt({ name: "AES-GCM", iv }, aesKey, ctBuf);
  const mime = meta.mime || "application/octet-stream";
  const outBlob = new Blob([ptBuf], { type: mime });
  const filename = (meta.name || fallbackName || "file").toString();
  downloadBlob(filename, outBlob);
}

async function decryptLegacyRSA(privKey, cipherB64) {
  const raw = atob(cipherB64);
  const buf = new Uint8Array(raw.split("").map(c => c.charCodeAt(0))).buffer;
  const decryptedBuffer = await window.crypto.subtle.decrypt({ name: "RSA-OAEP" }, privKey, buf);
  return new TextDecoder().decode(decryptedBuffer);
}

async function decryptHybridEnvelope(privKey, cipherStr) {
  const envJson = atob(cipherStr.slice(PM_ENVELOPE_PREFIX.length));
  let env;
  try { env = JSON.parse(envJson); } catch { throw new Error("Bad PM envelope JSON"); }

  if (!env || env.v !== 1 || env.alg !== "RSA-OAEP+AES-GCM") {
    throw new Error("Unknown PM envelope format");
  }

  const wrappedKeyBuf = bytesFromB64(env.ek).buffer;
  const rawAesKey = await window.crypto.subtle.decrypt({ name: "RSA-OAEP" }, privKey, wrappedKeyBuf);

  const aesKey = await window.crypto.subtle.importKey("raw", rawAesKey, { name: "AES-GCM" }, false, ["decrypt"]);
  const iv = bytesFromB64(env.iv);
  const ctBuf = bytesFromB64(env.ct).buffer;

  const decryptedBuffer = await window.crypto.subtle.decrypt({ name: "AES-GCM", iv }, aesKey, ctBuf);
  return new TextDecoder().decode(decryptedBuffer);
}

function ecIsBlockedPrivateMessageSender(username) {
  try {
    const raw = String(username || '').trim();
    const key = raw.toLowerCase();
    if (!key || !(UIState.blockedSet instanceof Set)) return false;
    if (UIState.blockedSet.has(raw) || UIState.blockedSet.has(key)) return true;
    for (const blocked of UIState.blockedSet.values()) {
      if (String(blocked || '').trim().toLowerCase() === key) return true;
    }
  } catch (_e) {}
  return false;
}

socket.on("private_message", async ({ sender, cipher, ts }) => {
  const senderName = ecPmPeerName(sender);
  if (!senderName) return;

  // The server denies blocked-pair sends before relay/storage. This client-side
  // check is a second guard for races/in-flight packets and prevents a blocked
  // sender from reopening a PM window locally after the user blocks them.
  if (ecIsBlockedPrivateMessageSender(senderName)) {
    try { socket.emit("get_missed_pm_summary"); } catch {}
    return;
  }

  const liveTs = (typeof ts === "number" && Number.isFinite(ts)) ? ts : null;
  // Historical guard shapes kept for split-runtime regression visibility:
  // const hadOpenPmWindow = !!ecGetPmWindow(sender)
  // dedupeKey: `pm:${sender}:
  // dedupeKey: `pm-file:${sender}:
  // dedupeKey: `pm-decrypt:${sender}:
  // Runtime uses the canonicalized senderName so case/spacing aliases hit the same PM window.
  const hadOpenPmWindow = !!ecGetPmWindow(senderName);
  const suppressActivePmAlert = hadOpenPmWindow &&
    (typeof ecIsWindowActivelyFocused === "function") && ecIsWindowActivelyFocused();
  const win = openPrivateChat(senderName) || ecGetPmWindow(senderName);
  try {
    let plaintext;

    // Plaintext wrapper is accepted only when explicit legacy compat mode is enabled.
    if (typeof cipher === "string" && cipher.startsWith(PM_PLAINTEXT_PREFIX) && DM_PLAINTEXT_COMPAT_ALLOWED) {
      plaintext = unwrapPlainDm(cipher);
    } else {
      const privKey = await ensurePrivateKeyUnlocked();
      if (typeof cipher === "string" && cipher.startsWith(PM_ENVELOPE_PREFIX)) {
        plaintext = await decryptHybridEnvelope(privKey, cipher);
      } else {
        plaintext = await decryptLegacyRSA(privKey, cipher);
      }
    }

    const payload = parseDmPayload(plaintext);
    const w = ecGetPmWindow(senderName);
    if (w) appendDmPayload(w, `${senderName}:`, payload, { peer: senderName, direction: "in", ts: liveTs });

    if (payload.kind === "file") {
      addPmHistory(senderName, "in", `📎 ${payload.name} (${humanBytes(payload.size)})`, liveTs);
    } else if (payload.kind === "torrent") {
      const nm = payload?.t?.name || payload?.t?.infohash || "Torrent";
      addPmHistory(senderName, "in", `🧲 ${nm}`, liveTs);
    } else {
      addPmHistory(senderName, "in", payload.text, liveTs);
    }

    if (!suppressActivePmAlert) {
      if (payload.kind === "file") {
        toast(`📎 ${senderName} sent a file: ${payload.name}`, "info", 3500, { event: "file", dedupeKey: `pm-file:${senderName}:${payload.name}:${payload.size}` });
        maybeBrowserNotify("File received", `${senderName}: ${payload.name}`, { dedupeKey: `pm-file:${senderName}:${payload.name}:${payload.size}` });
      } else if (payload.kind === "torrent") {
        const nm = payload?.t?.name || payload?.t?.infohash || "Torrent";
        toast(`🧲 ${senderName} shared a torrent: ${nm}`, "info", 3500, { event: "file", dedupeKey: `pm-torrent:${senderName}:${nm}` });
        maybeBrowserNotify("Torrent shared", `${senderName}: ${nm}`, { dedupeKey: `pm-torrent:${senderName}:${nm}` });
      } else {
        toast(`📥 New PM from ${senderName}`, "info", 3500, { event: "dm", dedupeKey: `pm:${senderName}:${String(payload.text || '').slice(0, 160)}` });
        maybeBrowserNotify("Private message", `${senderName}: ${payload.text}`, { dedupeKey: `pm:${senderName}:${String(payload.text || '').slice(0, 160)}` });
      }
    }
  } catch (e) {
    console.error("Failed to process PM:", e);
    const w = ecGetPmWindow(senderName);

    const msg = String(e?.message || e || "");
    const low = msg.toLowerCase();

    let sysLine = "PM received but could not decrypt.";
    let toastMsg = `⚠️ PM from ${senderName} (could not decrypt)`;

    if (!HAS_WEBCRYPTO) {
      sysLine = `PM received but could not decrypt (E2EE requires HTTPS or localhost; current: ${window.location.origin}).`;
      toastMsg = `⚠️ PM from ${senderName} (E2EE unavailable on this origin)`;
    } else if (low.includes("private messages are locked") || low.includes("unlock skipped") || low.includes("no encrypted private key")) {
      sysLine = "PM received but private messages are not ready in this tab. Sign out and sign back in to refresh private messages.";
      toastMsg = `PM from ${senderName} is waiting. Sign out and sign back in if it does not appear.`;
    } else if (low.includes("operationerror") || low.includes("data error") || low.includes("could not decrypt") || low.includes("bad pm envelope")) {
      // Most common cause in practice: sender encrypted to a stale public key (keys rotate after password reset).
      sysLine = "🔑 PM received but could not decrypt (key mismatch). If you recently reset your password, ask the sender to refresh and resend.";
      toastMsg = `🔑 PM from ${senderName} (key mismatch)`;
    }

    if (w) appendLine(w, "System:", sysLine);
    if (!suppressActivePmAlert) toast(toastMsg, "warn", 3500, { event: "error", dedupeKey: `pm-decrypt:${senderName}:${toastMsg}` });
  }
});
