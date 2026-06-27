// ───────────────────────────────────────────────────────────────────────────────
// Rooms (optional ciphertext-only envelopes)
// ───────────────────────────────────────────────────────────────────────────────
function bytesToB64(bytes) {
  if (bytes instanceof Uint8Array) return b64FromBytes(bytes);
  if (bytes instanceof ArrayBuffer) return b64FromBytes(new Uint8Array(bytes));
  return b64FromBytes(new Uint8Array(bytes || []));
}

async function encryptRoomEnvelopeForUsers(recipients, plaintext) {
  // Hybrid encrypt (per message): AES-GCM payload, RSA-OAEP wraps AES key *per recipient*.
  const encoder = new TextEncoder();
  const msgBytes = encoder.encode(String(plaintext ?? ""));

  const aesKey = await window.crypto.subtle.generateKey(
    { name: "AES-GCM", length: 256 },
    true,
    ["encrypt", "decrypt"]
  );
  const iv = window.crypto.getRandomValues(new Uint8Array(12));
  const ctBuffer = await window.crypto.subtle.encrypt({ name: "AES-GCM", iv }, aesKey, msgBytes);

  const rawAesKey = await window.crypto.subtle.exportKey("raw", aesKey);

  const keys = {};
  for (const u of recipients) {
    const rsaPubKey = await getUserRsaPublicKey(u);
    const wrappedKey = await window.crypto.subtle.encrypt({ name: "RSA-OAEP" }, rsaPubKey, rawAesKey);
    keys[u] = b64FromBytes(new Uint8Array(wrappedKey));
  }

  const envelope = {
    v: 1,
    alg: "RSA-OAEP+AES-GCM",
    iv: b64FromBytes(iv),
    ct: b64FromBytes(new Uint8Array(ctBuffer)),
    keys
  };

  return ROOM_ENVELOPE_PREFIX + btoa(JSON.stringify(envelope));
}

// Encrypt a group message to all group members (AES-GCM payload + RSA-OAEP wrapped AES key per member).
async function encryptGroupEnvelopeForUsers(recipients, plaintext) {
  const encoder = new TextEncoder();
  const msgBytes = encoder.encode(String(plaintext ?? ""));

  const aesKey = await window.crypto.subtle.generateKey(
    { name: "AES-GCM", length: 256 },
    true,
    ["encrypt", "decrypt"]
  );
  const iv = window.crypto.getRandomValues(new Uint8Array(12));
  const ctBuffer = await window.crypto.subtle.encrypt({ name: "AES-GCM", iv }, aesKey, msgBytes);

  const rawAesKey = await window.crypto.subtle.exportKey("raw", aesKey);

  const keys = {};
  for (const u of recipients) {
    const rsaPubKey = await getUserRsaPublicKey(u);
    const wrappedKey = await window.crypto.subtle.encrypt({ name: "RSA-OAEP" }, rsaPubKey, rawAesKey);
    keys[u] = b64FromBytes(new Uint8Array(wrappedKey));
  }

  const envelope = {
    v: 1,
    alg: "RSA-OAEP+AES-GCM",
    iv: b64FromBytes(iv),
    ct: b64FromBytes(new Uint8Array(ctBuffer)),
    keys
  };

  return GROUP_ENVELOPE_PREFIX + btoa(JSON.stringify(envelope));
}

async function decryptGroupEnvelope(privKey, cipherStr) {
  const envJson = atob(cipherStr.slice(GROUP_ENVELOPE_PREFIX.length));
  let env;
  try { env = JSON.parse(envJson); } catch { throw new Error("Bad group envelope JSON"); }

  if (!env || env.v !== 1 || env.alg !== "RSA-OAEP+AES-GCM" || !env.keys) {
    throw new Error("Unknown group envelope format");
  }
  const myEk = env.keys[currentUser];
  if (!myEk) throw new Error("No recipient key for me");

  const wrappedKeyBuf = bytesFromB64(String(myEk)).buffer;
  const rawAesKey = await window.crypto.subtle.decrypt({ name: "RSA-OAEP" }, privKey, wrappedKeyBuf);

  const aesKey = await window.crypto.subtle.importKey("raw", rawAesKey, { name: "AES-GCM" }, false, ["decrypt"]);
  const iv = bytesFromB64(env.iv);
  const ctBuf = bytesFromB64(env.ct).buffer;

  const decryptedBuffer = await window.crypto.subtle.decrypt({ name: "AES-GCM", iv }, aesKey, ctBuf);
  return new TextDecoder().decode(decryptedBuffer);
}

async function decryptRoomEnvelope(privKey, cipherStr) {
  const envJson = atob(cipherStr.slice(ROOM_ENVELOPE_PREFIX.length));
  let env;
  try { env = JSON.parse(envJson); } catch { throw new Error("Bad room envelope JSON"); }

  if (!env || env.v !== 1 || env.alg !== "RSA-OAEP+AES-GCM" || !env.keys) {
    throw new Error("Unknown room envelope format");
  }
  const myEk = env.keys[currentUser];
  if (!myEk) throw new Error("No recipient key for me");

  const wrappedKeyBuf = bytesFromB64(String(myEk)).buffer;
  const rawAesKey = await window.crypto.subtle.decrypt({ name: "RSA-OAEP" }, privKey, wrappedKeyBuf);

  const aesKey = await window.crypto.subtle.importKey("raw", rawAesKey, { name: "AES-GCM" }, false, ["decrypt"]);
  const iv = bytesFromB64(env.iv);
  const ctBuf = bytesFromB64(env.ct).buffer;

  const decryptedBuffer = await window.crypto.subtle.decrypt({ name: "AES-GCM", iv }, aesKey, ctBuf);
  return new TextDecoder().decode(decryptedBuffer);
}

// Encrypt a room message to all *current* room members that have public keys.
// If any member lacks a key, we abort (ciphertext-only guarantee).
async function buildRoomCipher(room, plaintext) {
  if (!HAS_WEBCRYPTO) throw new Error("Room encryption requires HTTPS or http://localhost.");

  // Get the freshest roster we can.
  const users = await requestRoomUsers(room, 1500).catch(() => (UIState.roomUsers.get(room) || []));
  const uniq = Array.from(new Set((users || []).map(String).filter(Boolean)));
  if (!uniq.includes(currentUser)) uniq.push(currentUser);

  // Prefetch keys (so we can provide a clear error list)
  const missing = [];
  for (const u of uniq) {
    try {
      await getUserRsaPublicKey(u);
    } catch {
      missing.push(u);
    }
  }
  if (missing.length) {
    throw new Error(`Users missing public keys: ${missing.slice(0, 6).join(", ")}${missing.length > 6 ? "…" : ""}`);
  }

  return await encryptRoomEnvelopeForUsers(uniq, plaintext);
}

function inferRoomMessageKindFromPlaintext(plaintext) {
  const raw = String(plaintext ?? "").trim();
  if (!raw) return "text";
  if (raw.toLowerCase().startsWith("gif:")) return "gif";
  try {
    const obj = JSON.parse(raw);
    const ec = String(obj?._ec || obj?.kind || obj?.type || "").trim().toLowerCase();
    if (ec === "gif") return "gif";
    if (ec === "torrent" || ec === "magnet") return "torrent";
    if (ec === "file" || ec === "upload") return "file";
    if (obj && (obj.magnet || obj.infohash || obj.infohash_hex)) return "torrent";
  } catch {}
  return "text";
}


function ecApplyRoomSendPolicyFromAck(room, out) {
  try {
    if (!out?.success && out?.error) {
      const e = String(out.error).toLowerCase();
      if (e.includes("read-only") || e.includes("read only")) upsertRoomPolicy(room, { readonly: true, can_send: false, block_reason: "read_only" });
      if (e.includes("locked")) upsertRoomPolicy(room, { locked: true, can_send: false, block_reason: "locked" });
    }
  } catch {}
  return out;
}

async function ecSendRoomMessageAck(payload) {
  const out = (typeof ecEmitAck === "function")
    ? await ecEmitAck("send_message", payload, 8500, { connectBannerText: "🔌 Reconnecting before sending room message…" })
    : await new Promise((resolve) => socket.emit("send_message", payload, (res) => resolve(res || { success: false })));
  return ecApplyRoomSendPolicyFromAck(payload?.room, out || { success: false });
}

async function ecSendGroupMessageAck(payload) {
  return (typeof ecEmitAck === "function")
    ? await ecEmitAck("group_message", payload, 8500, { connectBannerText: "🔌 Reconnecting before sending group message…" })
    : await new Promise((resolve) => socket.emit("group_message", payload, (res) => resolve(res || { success: false })));
}

async function buildDuplicateMessageHints(plaintext, messageKind = "text") {
  const raw = String(plaintext ?? "");
  const normalized = raw.trim().toLowerCase().replace(/\s+/g, " ");
  const enc = new TextEncoder();
  const mkDigest = async (value) => {
    const buf = await window.crypto.subtle.digest("SHA-256", enc.encode(String(messageKind || "text") + "\n" + value));
    return Array.from(new Uint8Array(buf)).map((b) => b.toString(16).padStart(2, "0")).join("");
  };
  return {
    dup_sig_raw: await mkDigest(raw),
    dup_sig_norm: await mkDigest(normalized),
    dup_plain_len: raw.length,
  };
}

async function sendRoomTo(room, plaintext) {
  // Slash command: /invite <username>
  // This must never be broadcast into chat history; it triggers an invite notification only.
  try {
    const raw = (typeof plaintext === 'string') ? plaintext : String(plaintext ?? '');
    const t = raw.trim();
    if (/^\/invite(\s|$)/i.test(t)) {
      const rest = t.replace(/^\/invite\s*/i, '').trim();
      const u = ((rest.split(/\s+/)[0] || '').trim()).replace(/^@/, '');
      if (!u) return { success: false, error: 'Usage: /invite <username>' };
      try {
        await apiJson('/api/rooms/invite', { method: 'POST', body: JSON.stringify({ room, invitee: u }) });
        toast(`✅ Invited ${u} to ${room}`, 'ok');
        return { success: true, command: 'invite' };
      } catch (e) {
        return { success: false, error: (e?.message || String(e)) };
      }
    }
    if (/^\/skip(\s|$)/i.test(t)) {
      return await ecSendRoomMessageAck({ room, message: '/skip', message_kind: 'command', dup_sig_raw: null, dup_sig_norm: null, dup_plain_len: 5 });
    }
  } catch (e) { /* ignore */ }

  const serverRequiresRoomE2EE = !!(ECHOCHAT_CFG.require_room_e2ee || ECHOCHAT_CFG.require_private_room_e2ee);
  const useE2EE = serverRequiresRoomE2EE ? true : Settings.get("roomE2EE", true);

  const messageKind = inferRoomMessageKindFromPlaintext(plaintext);

  if (useE2EE && HAS_WEBCRYPTO) {
    const dupHints = await buildDuplicateMessageHints(plaintext, messageKind);
    const cipher = await buildRoomCipher(room, plaintext);
    return await ecSendRoomMessageAck({ room, cipher, message_kind: messageKind, ...dupHints });
  }

  return await ecSendRoomMessageAck({ room, message: String(plaintext ?? ""), message_kind: messageKind, dup_sig_raw: null, dup_sig_norm: null, dup_plain_len: String(plaintext ?? "").length });
}

async function requestGroupMembers(groupId, timeoutMs = 1500) {
  const gid = Number(groupId);
  if (!gid) return [];
  const res = (typeof ecEmitAck === "function")
    ? await ecEmitAck("get_group_members", { group_id: gid }, Math.max(1200, Number(timeoutMs || 1500) + 700), { connectBannerText: "🔌 Reconnecting before refreshing group members…", bannerDelayMs: 1200 })
    : await new Promise((resolve) => socket.emit("get_group_members", { group_id: gid }, (r) => resolve(r || { success: false })));
  if (res?.success) return Array.isArray(res.members) ? res.members : [];
  throw new Error(res?.error || "group_members failed");
}

// Encrypt a group message to all group members that have public keys.
// If any member lacks a key, we abort (ciphertext-only guarantee).
async function buildGroupCipher(groupId, plaintext) {
  if (!HAS_WEBCRYPTO) throw new Error("Group encryption requires HTTPS or http://localhost.");

  const gid = Number(groupId);
  // Prefer cached members, but refresh from server when possible.
  const cached = UIState.groupMembers.get(gid) || [];
  const members = await requestGroupMembers(gid, 1500).catch(() => cached);
  const uniq = Array.from(new Set((members || []).map(String).filter(Boolean)));
  if (!uniq.includes(currentUser)) uniq.push(currentUser);

  const missing = [];
  for (const u of uniq) {
    try { await getUserRsaPublicKey(u); } catch { missing.push(u); }
  }
  if (missing.length) {
    throw new Error(`Users missing public keys: ${missing.slice(0, 6).join(", ")}${missing.length > 6 ? "…" : ""}`);
  }

  return await encryptGroupEnvelopeForUsers(uniq, plaintext);
}

function inferGroupMessageKindFromPlaintext(plaintext) {
  const raw = String(plaintext ?? '').trim();
  if (!raw) return 'text';
  if (raw.toLowerCase().startsWith('gif:')) return 'gif';
  try {
    const obj = JSON.parse(raw);
    const ec = String(obj?._ec || obj?.kind || obj?.type || '').trim().toLowerCase();
    if (ec === 'gif') return 'gif';
    if (ec === 'torrent' || ec === 'magnet') return 'torrent';
    if (ec === 'file' || ec === 'upload') return 'file';
    if (obj && (obj.magnet || obj.infohash || obj.infohash_hex)) return 'torrent';
  } catch {}
  return 'text';
}

async function sendGroupTo(groupId, plaintext, ctx = {}) {
  const gid = Number(groupId);

  try {
    if (typeof runGroupTextCommand === "function") {
      const commandResult = await runGroupTextCommand(gid, plaintext, ctx);
      if (commandResult?.handled) {
        return {
          success: !!commandResult.success,
          command: commandResult.command || 'group_command',
          error: commandResult.error || '',
        };
      }
    }
  } catch (e) {
    return { success: false, command: 'group_command', error: e?.message || String(e) };
  }

  const serverRequiresGroupE2EE = (ECHOCHAT_CFG.require_group_e2ee === undefined) ? true : !!ECHOCHAT_CFG.require_group_e2ee;
  const useE2EE = serverRequiresGroupE2EE ? true : Settings.get("groupE2EE", true);

  const messageKind = inferGroupMessageKindFromPlaintext(plaintext);

  if (useE2EE && HAS_WEBCRYPTO) {
    const cipher = await buildGroupCipher(gid, plaintext);
    const dupHints = await buildDuplicateMessageHints(plaintext, messageKind);
    return await ecSendGroupMessageAck({ group_id: gid, cipher, message_kind: messageKind, ...dupHints });
  }

  return await ecSendGroupMessageAck({ group_id: gid, message: String(plaintext ?? ""), message_kind: messageKind, dup_sig_raw: null, dup_sig_norm: null, dup_plain_len: String(plaintext ?? "").length });
}

async function sendGroupCipher(groupId, plaintext) {
  const gid = Number(groupId);
  const messageKind = inferGroupMessageKindFromPlaintext(plaintext);
  const cipher = await buildGroupCipher(gid, plaintext);
  const dupHints = await buildDuplicateMessageHints(plaintext, messageKind);
  return await ecSendGroupMessageAck({ group_id: gid, cipher, message_kind: messageKind, ...dupHints });
}

async function sendGroupFileTo(groupId, file, ctx = {}) {
  if (!file) return null;
  if (!HAS_WEBCRYPTO) {
    toast("🔒 Group file transfers require HTTPS (or http://localhost).", "warn", 5200);
    return null;
  }
  if (file.size > MAX_GROUP_FILE_BYTES) {
    toast(`❌ File too large (max ${humanBytes(MAX_GROUP_FILE_BYTES)})`, "error");
    return null;
  }

  const gid = Number(groupId);
  const win = ctx?.win || null;
  const meta = {
    name: file.name || "file",
    size: file.size || 0,
    mime: file.type || "application/octet-stream",
  };

  let ui = null;
  try {
    if (win) {
      ui = appendP2pTransferUI(win, "You:", meta, { mode: "outgoing" });
      if (ui?.setBadge) ui.setBadge("SRV");
      ui.setStatus("Encrypting…");
    }

    const arrayBuffer = await file.arrayBuffer();
    const sha256 = await sha256HexFromArrayBuffer(arrayBuffer);
    meta.sha256 = sha256;

    // Get group member list (includes current user).
    const cached = UIState.groupMembers.get(gid) || [];
    const members = await requestGroupMembers(gid, 1500).catch(() => cached);
    const uniq = Array.from(new Set((members || []).map(String).filter(Boolean)));
    if (!uniq.includes(currentUser)) uniq.push(currentUser);

    // Ensure all pubkeys exist
    const missing = [];
    for (const u of uniq) {
      try { await getUserRsaPublicKey(u); } catch { missing.push(u); }
    }
    if (missing.length) {
      throw new Error(`Users missing public keys: ${missing.slice(0, 6).join(", ")}${missing.length > 6 ? "…" : ""}`);
    }

    // Encrypt file bytes under random AES key, wrap AES key for each member.
    const aesKey = await window.crypto.subtle.generateKey(
      { name: "AES-GCM", length: 256 },
      true,
      ["encrypt", "decrypt"]
    );
    const iv = window.crypto.getRandomValues(new Uint8Array(12));
    const ctBuf = await window.crypto.subtle.encrypt({ name: "AES-GCM", iv }, aesKey, arrayBuffer);
    const rawAesKey = await window.crypto.subtle.exportKey("raw", aesKey);

    const ek_map = {};
    for (const u of uniq) {
      const pub = await getUserRsaPublicKey(u);
      const ek = await window.crypto.subtle.encrypt({ name: "RSA-OAEP" }, pub, rawAesKey);
      ek_map[u] = bytesToB64(new Uint8Array(ek));
    }

    const ctBlob = new Blob([ctBuf], { type: "application/octet-stream" });

    if (ui) ui.setStatus("Uploading…");

    const uploaded = await uploadEncryptedGroupFile(gid, {
      ctBlob,
      originalName: meta.name,
      mimeType: meta.mime,
      ivBytes: iv,
      ek_map,
      sha256: meta.sha256,
    }, {
      onProgress: (pct) => {
        if (ui) ui.setStatus(`Uploading… ${Math.max(0, Math.min(100, Math.floor(pct)))}%`);
      }
    });

    // Send metadata as a group-encrypted payload (never plaintext).
    const wire = {
      kind: "file",
      scope: "group",
      source: "server",
      group_id: gid,
      file_id: uploaded.file_id,
      name: uploaded.name || meta.name,
      size: uploaded.size || meta.size,
      mime: uploaded.mime || meta.mime,
      sha256: uploaded.sha256 || meta.sha256,
    };

    if (ui) ui.setStatus("Sending…");
    const res = await sendGroupCipher(gid, JSON.stringify(wire));
    if (!res?.success) throw new Error(res?.error || "Could not notify group");

    if (ui) ui.remove();
    return wire;
  } catch (e) {
    if (ui) {
      const msg = String(e?.message || e || "Failed");
      ui.setStatus(`❌ Failed: ${msg}`);
      setTimeout(() => ui.remove(), 6500);
    }
    throw e;
  }
}

async function getUserRsaPublicKey(username, opts = {}) {
  // Fetch user’s public key PEM (cookies carry JWT). If the access token expired,
  // refresh and retry automatically.
  const uname = String(username || "").trim();
  if (!uname) throw new Error("username required");
  const cacheKey = uname.toLowerCase();
  const forceRefresh = !!opts.forceRefresh;
  const now = Date.now();
  const cached = RSA_PUBKEY_CACHE.get(cacheKey);
  if (cached && cached.key && !forceRefresh) {
    const age = now - (Number(cached.fetchedAt) || 0);
    if (age >= 0 && age < RSA_PUBKEY_CACHE_TTL_MS) return cached.key;
  }

  const resp = await fetchWithAuth(`/get_public_key?username=${encodeURIComponent(uname)}`, {
    method: "GET",
    credentials: "same-origin"
  });
  const data = (typeof ecReadApiJson === 'function') ? await ecReadApiJson(resp, {}) : await resp.json().catch(() => ({}));
  if (!resp || !resp.ok) {
    const keyLookupError = String(data?.error || data?.code || data?.msg || '').trim();
    if (["blocked", "no_public_key", "user_not_found", "invalid_username", "username_required", "target_not_active"].includes(keyLookupError)) {
      throw new Error(keyLookupError);
    }
    const msg = (typeof ecApiErrorMessage === 'function') ? ecApiErrorMessage(resp, data, `Could not fetch public key for ${uname}`) : (keyLookupError || `Could not fetch public key for ${uname} (HTTP ${resp?.status || '?'})`);
    throw new Error(msg);
  }
  const { public_key } = data || {};
  const canonicalUsername = String(data?.username || uname).trim();
  const publicPemText = String(public_key || "").trim();
  if (!publicPemText.startsWith("-----BEGIN PUBLIC KEY-----") || !publicPemText.endsWith("-----END PUBLIC KEY-----")) {
    throw new Error("no_public_key");
  }
  let key;
  try {
    const pubPem = publicPemText
      .replace("-----BEGIN PUBLIC KEY-----", "")
      .replace("-----END PUBLIC KEY-----", "")
      .replace(/\s+/g, "");
    const pubDer = Uint8Array.from(atob(pubPem), c => c.charCodeAt(0));
    key = await window.crypto.subtle.importKey(
      "spki",
      pubDer.buffer,
      { name: "RSA-OAEP", hash: "SHA-256" },
      false,
      ["encrypt"]
    );
  } catch (e) {
    throw new Error("no_public_key");
  }
  RSA_PUBKEY_CACHE.set(cacheKey, { key, fetchedAt: now, username: canonicalUsername });
  if (canonicalUsername) RSA_PUBKEY_CACHE.set(canonicalUsername.toLowerCase(), { key, fetchedAt: now, username: canonicalUsername });
  return key;
}

async function sha256HexFromArrayBuffer(ab) {
  if (!HAS_WEBCRYPTO) {
    throw new Error("File transfers require HTTPS (or http://localhost).");
  }
  const hash = await window.crypto.subtle.digest("SHA-256", ab);
  const bytes = new Uint8Array(hash);
  let out = "";
  for (const b of bytes) out += b.toString(16).padStart(2, "0");
  return out;
}

async function uploadEncryptedDmFile(toUser, payload, { onProgress } = {}) {
  if (DM_FILE_DISABLED) throw new Error("File sharing is disabled");
  if (!HAS_WEBCRYPTO) throw new Error(`E2EE requires HTTPS (or http://localhost / http://127.0.0.1). Current origin: ${window.location.origin}`);

  // Back-compat accepted shapes:
  //  - { ctBlob, originalName, mimeType, iv_b64, ek_to_b64, ek_from_b64, sha256 }
  //  - { ctBytes, original_name, mime_type, ivBytes, ekToBytes, ekFromBytes, sha256 }
  const originalName = payload.originalName || payload.original_name || payload.name || "file.bin";
  const mimeType = payload.mimeType || payload.mime_type || payload.mime || "application/octet-stream";

  const ctBlob = payload.ctBlob
    ? payload.ctBlob
    : new Blob([payload.ctBytes || new Uint8Array()], { type: "application/octet-stream" });

  const iv_b64 = payload.iv_b64 || (payload.ivBytes ? bytesToB64(payload.ivBytes) : "");
  const ek_to_b64 = payload.ek_to_b64 || (payload.ekToBytes ? bytesToB64(payload.ekToBytes) : "");
  const ek_from_b64 = payload.ek_from_b64 || (payload.ekFromBytes ? bytesToB64(payload.ekFromBytes) : "");

  if (!iv_b64 || !ek_to_b64 || !ek_from_b64) throw new Error("Missing encryption envelope fields");

  const fd = new FormData();
  fd.append("to", toUser);
  fd.append("file", ctBlob, "cipher.bin");
  fd.append("iv_b64", iv_b64);
  fd.append("ek_to_b64", ek_to_b64);
  fd.append("ek_from_b64", ek_from_b64);
  if (payload.sha256) fd.append("sha256", payload.sha256);
  fd.append("original_name", originalName);
  fd.append("mime_type", mimeType);

  // Prefer XHR so we can show progress, but fall back to fetch() if the
  // browser/network stack wedges (seen in some environments).
  let res = null;
  try {
    res = await xhrPostFormWithAuth("/api/dm_files/upload", fd, { onProgress });
  } catch (e) {
    console.warn("XHR upload failed; retrying with fetch()", e);
    res = await fetchPostFormWithAuth("/api/dm_files/upload", fd);
  }

  const data = res?.json || null;

  if (!res?.ok || !data?.success) {
    const fallback = (res?.text || "").trim();
    const snippet = fallback ? ` — ${fallback.slice(0, 180)}` : "";
    const msg = data?.error || `Upload failed (HTTP ${res?.status ?? "?"})${snippet}`;
    throw new Error(msg);
  }
  return data; // {success, file_id, name, mime, size}
}

async function uploadEncryptedGroupFile(groupId, payload, { onProgress } = {}) {
  if (GROUP_FILE_DISABLED) throw new Error("File sharing is disabled");
  if (!HAS_WEBCRYPTO) throw new Error(`E2EE requires HTTPS (or http://localhost / http://127.0.0.1). Current origin: ${window.location.origin}`);

  const originalName = payload.originalName || payload.original_name || payload.name || "file.bin";
  const mimeType = payload.mimeType || payload.mime_type || payload.mime || "application/octet-stream";

  const ctBlob = payload.ctBlob
    ? payload.ctBlob
    : new Blob([payload.ctBytes || new Uint8Array()], { type: "application/octet-stream" });

  const iv_b64 = payload.iv_b64 || (payload.ivBytes ? bytesToB64(payload.ivBytes) : "");
  const ek_map = payload.ek_map || payload.ekMap || null;
  const ek_map_json = payload.ek_map_json || (ek_map ? JSON.stringify(ek_map) : "");

  if (!iv_b64 || !ek_map_json) throw new Error("Missing encryption envelope fields");

  const fd = new FormData();
  fd.append("group_id", String(groupId));
  fd.append("file", ctBlob, "cipher.bin");
  fd.append("iv_b64", iv_b64);
  fd.append("ek_map_json", ek_map_json);
  if (payload.sha256) fd.append("sha256", payload.sha256);
  fd.append("original_name", originalName);
  fd.append("mime_type", mimeType);

  let res = null;
  try {
    res = await xhrPostFormWithAuth("/api/group_files/upload", fd, { onProgress });
  } catch (e) {
    console.warn("XHR upload failed; retrying with fetch()", e);
    res = await fetchPostFormWithAuth("/api/group_files/upload", fd);
  }

  const data = res?.json || null;
  if (!res?.ok || !data?.success) {
    const fallback = (res?.text || "").trim();
    const snippet = fallback ? ` — ${fallback.slice(0, 180)}` : "";
    const msg = data?.error || `Upload failed (HTTP ${res?.status ?? "?"})${snippet}`;
    throw new Error(msg);
  }
  return data; // {success, group_id, file_id, name, mime, size, sha256}
}

async function sendDmFileTo(toUser, file, ctx = {}) {
  if (!file) return null;
  if (DM_FILE_DISABLED) {
    toast("File sharing is disabled by the server administrator.", "warn", 5200);
    return null;
  }
  if (!HAS_WEBCRYPTO) {
    toast("🔒 File transfers require HTTPS (or http://localhost).", "warn", 5200);
    return null;
  }
  if (file.size > MAX_DM_FILE_BYTES) {
    toast(`❌ File too large (max ${humanBytes(MAX_DM_FILE_BYTES)})`, "error");
    return null;
  }

  // Small UX: show a transfer line while we attempt P2P / upload.
  const win = ctx?.win || null;
  const meta = {
    name: file.name || "file",
    size: file.size || 0,
    mime: file.type || "application/octet-stream",
  };

  let ui = null;
  try {
    if (win) {
      ui = appendP2pTransferUI(win, "You:", meta, { mode: "outgoing" });
      if (ui?.setBadge) ui.setBadge("P2P");
      ui.setStatus("Negotiating P2P…");
    }

    // Preload bytes once; reused for hashing + P2P send + server fallback.
    const arrayBuffer = await file.arrayBuffer();
    const sha256 = await sha256HexFromArrayBuffer(arrayBuffer);
    meta.sha256 = sha256;

    // 1) P2P first (WebRTC DataChannel), 2) fallback to encrypted server upload.
    if (P2P_FILE_ENABLED) {
      let p2pPayload = null;
      try {
        p2pPayload = await tryP2PFileTransfer(toUser, meta, arrayBuffer, { ui });
      } catch (e) {
        const msg = String(e?.message || e || "");
        if (msg.toLowerCase().includes("declin")) {
          if (ui) {
            ui.setStatus("❌ Declined");
            setTimeout(() => ui.remove(), 900);
          }
          return null; // do NOT fallback if the peer explicitly declined.
        }
        console.warn("P2P file transfer failed, falling back to server:", e);
        p2pPayload = null;
      }
      if (p2pPayload) {
        if (ui) ui.remove();
        return p2pPayload;
      }
    }

    if (ui?.setBadge) ui.setBadge("SRV");
    if (ui) ui.setStatus("P2P unavailable — uploading to server…");
    const serverPayload = await sendDmFileViaServer(toUser, meta, arrayBuffer, { ui });
    if (ui) ui.remove();
    return serverPayload;
  } catch (e) {
    if (ui) {
      const msg = String(e?.message || e || "Failed");
      ui.setStatus(`❌ Failed: ${msg}`);
      setTimeout(() => ui.remove(), 6500);
    }
    throw e;
  }
}

async function sendDmFileViaServer(toUser, meta, arrayBuffer, { ui } = {}) {
  if (!HAS_WEBCRYPTO) {
    toast("🔒 File sharing requires HTTPS or http://localhost.", "warn");
    return null;
  }
  if (!toUser || !arrayBuffer) return null;

  // Two wrapped keys: recipient + sender. Server cannot decrypt.
  // Recipient key can rotate (password reset). Fetch fresh to avoid encrypting to a stale key.
  const pubTo = await getUserRsaPublicKey(toUser, { forceRefresh: true });
  const pubMe = await getUserRsaPublicKey(currentUser);

  const aesKey = await window.crypto.subtle.generateKey(
    { name: "AES-GCM", length: 256 },
    true,
    ["encrypt", "decrypt"]
  );
  const iv = window.crypto.getRandomValues(new Uint8Array(12));
  const ctBuf = await window.crypto.subtle.encrypt({ name: "AES-GCM", iv }, aesKey, arrayBuffer);
  const rawAesKey = await window.crypto.subtle.exportKey("raw", aesKey);
  const ekTo = await window.crypto.subtle.encrypt({ name: "RSA-OAEP" }, pubTo, rawAesKey);
  const ekFrom = await window.crypto.subtle.encrypt({ name: "RSA-OAEP" }, pubMe, rawAesKey);

  if (ui?.setBadge) ui.setBadge("SRV");
  if (ui) ui.setStatus("Uploading to server (encrypted)…");

  // Upload ciphertext
  const uploadRes = await uploadEncryptedDmFile(toUser, {
    original_name: meta.name,
    mime_type: meta.mime,
    sha256: meta.sha256,
    ctBytes: new Uint8Array(ctBuf),
    ivBytes: iv,
    ekToBytes: new Uint8Array(ekTo),
    ekFromBytes: new Uint8Array(ekFrom),
  }, { onProgress: (p) => { try { ui && ui.setProgress(p); } catch {} } });

  if (!uploadRes?.file_id) {
    throw new Error(uploadRes?.error || "Upload did not return a file id");
  }

  // Notify peer via normal encrypted PM (wire payload)
  const wire = {
    _ec: "file",
    v: 1,
    file_id: uploadRes.file_id,
    name: meta.name,
    size: meta.size,
    mime: meta.mime,
    sha256: meta.sha256,
  };

  if (ui) ui.setStatus("Notifying peer…");

  const ok = await sendPrivateTo(toUser, JSON.stringify(wire));
  if (!ok) throw new Error("Could not notify peer");

  // Return a UI-friendly payload shape (used by appendDmPayload)
  return {
    kind: "file",
    source: "server",
    file_id: wire.file_id,
    name: wire.name,
    size: wire.size,
    mime: wire.mime,
    sha256: wire.sha256,
  };
}

// ───────────────────────────────────────────────────────────────────────────────
