// ───────────────────────────────────────────────────────────────────────────────
// Local PM history (client-side only)
//
// - Stored in browser localStorage (per-device)
// - Only saved if the user enables it in Settings
// - Intended for *client* convenience; server remains ciphertext-only for DMs
// ───────────────────────────────────────────────────────────────────────────────
const PM_HISTORY_KEY = "pmHistoryV1";
const PM_HISTORY_MAX_PER_CONV = 500;


function ecPmPeerName(username) {
  return String(username || "").trim().replace(/\s+/g, " ");
}

function ecPmPeerKey(username) {
  return ecPmPeerName(username).toLowerCase();
}

function ecPmWindowId(username) {
  const key = ecPmPeerKey(username);
  return key ? `dm:${key}` : "dm:";
}

function ecGetPmWindow(username) {
  const id = ecPmWindowId(username);
  return (UIState && UIState.windows && UIState.windows.get(id)) || null;
}

function ecSamePmPeer(a, b) {
  return ecPmPeerKey(a) === ecPmPeerKey(b);
}

function loadPmHistory() {
  const d = Settings.get(PM_HISTORY_KEY, { v: 1, convs: {} });
  if (!d || typeof d !== "object") return { v: 1, convs: {} };
  if (!d.convs || typeof d.convs !== "object") d.convs = {};
  return d;
}

function savePmHistory(d) {
  Settings.set(PM_HISTORY_KEY, d);
}

function ecPmHistoryKey(peer) {
  return ecPmPeerKey(peer);
}

function ecNormalizePmHistoryStore(d) {
  if (!d || typeof d !== "object") return { v: 1, convs: {} };
  if (!d.convs || typeof d.convs !== "object") d.convs = {};
  const normalized = {};
  for (const [rawPeer, rawItems] of Object.entries(d.convs)) {
    const key = ecPmHistoryKey(rawPeer);
    if (!key || !Array.isArray(rawItems)) continue;
    const existing = Array.isArray(normalized[key]) ? normalized[key] : [];
    normalized[key] = existing.concat(rawItems).slice(-PM_HISTORY_MAX_PER_CONV);
  }
  d.convs = normalized;
  return d;
}

function getPmHistory(peer) {
  const key = ecPmHistoryKey(peer);
  if (!key) return [];
  const d = ecNormalizePmHistoryStore(loadPmHistory());
  const arr = d.convs[key];
  return Array.isArray(arr) ? arr : [];
}

function addPmHistory(peer, dir, text, tsSec = null) {
  if (!UIState.prefs.savePmLocal) return;
  if (!peer || !text) return;

  const key = ecPmHistoryKey(peer);
  if (!key) return;
  const d = ecNormalizePmHistoryStore(loadPmHistory());
  const arr = Array.isArray(d.convs[key]) ? d.convs[key] : [];
  const ts = (typeof tsSec === "number" && !Number.isNaN(tsSec)) ? tsSec : (Date.now() / 1000);

  arr.push({ dir, ts, text: String(text) });
  if (arr.length > PM_HISTORY_MAX_PER_CONV) {
    d.convs[key] = arr.slice(arr.length - PM_HISTORY_MAX_PER_CONV);
  } else {
    d.convs[key] = arr;
  }
  savePmHistory(d);
}

function clearPmHistory() {
  savePmHistory({ v: 1, convs: {} });
  toast("🧹 Local PM history cleared", "ok");
}

function clearVisibleRoomChatData() {
  const pane = getRoomEmbedEl();
  const room = UIState.roomEmbedRoom || UIState.currentRoom || null;
  if (pane?._ym?.log) {
    resetChatLogState(pane._ym.log);
  }
  if (room) toast(`🧹 Cleared visible room chat for ${room} on this device`, "ok");
  else toast("🧹 Cleared visible room chat on this device", "ok");
}

function clearVisibleGroupChatData() {
  let count = 0;
  for (const [id, win] of UIState.windows.entries()) {
    if (!String(id || "").startsWith('group:')) continue;
    if (win?._ym?.log) {
      resetChatLogState(win._ym.log);
      const st = groupHistState(win);
      st.loading = false;
      st.done = false;
      updateGroupOlderUI(win);
      count += 1;
    }
  }
  toast(count ? `🧹 Cleared visible group chat in ${count} window(s)` : "🧹 No open group chat windows to clear", count ? "ok" : "info");
}

function clearVisiblePrivateChatData() {
  let count = 0;
  for (const [id, win] of UIState.windows.entries()) {
    if (!String(id || "").startsWith('dm:')) continue;
    if (win?._ym?.log) {
      resetChatLogState(win._ym.log);
      win.dataset.pmHistoryRendered = "0";
      count += 1;
    }
  }
  clearPmHistory();
  toast(count ? `🧹 Cleared visible private chat in ${count} window(s)` : "🧹 Cleared private chat history on this device", count ? "ok" : "info");
}

function downloadTextFile(filename, content, mime = "application/json") {
  try {
    const blob = new Blob([content], { type: mime });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 2500);
  } catch (e) {
    console.error(e);
    toast("❌ Download failed", "error");
  }
}

function downloadBlob(filename, blob) {
  try {
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 2500);
  } catch (e) {
    console.error(e);
    toast("❌ Download failed", "error");
  }
}

function humanBytes(n) {
  const num = Number(n);
  if (!Number.isFinite(num) || num <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let u = 0;
  let v = num;
  while (v >= 1024 && u < units.length - 1) {
    v = v / 1024;
    u++;
  }
  const fixed = (u === 0) ? String(Math.round(v)) : v.toFixed(v >= 10 ? 1 : 2);
  return `${fixed} ${units[u]}`;
}
