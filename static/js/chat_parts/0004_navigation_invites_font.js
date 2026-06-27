// Ensure we don't leave "ghost" room occupants behind when the user navigates away
// (Back button, tab close, BFCache pagehide). This helps keep room counts accurate.
window.addEventListener("pagehide", () => {
  try {
    if (socket && socket.connected) {
      if (UIState.currentRoom) {
        // Best-effort; server disconnect handler is the real cleanup.
        socket.emit("leave", { room: UIState.currentRoom });
      }
      socket.disconnect();
    }
  } catch (e) {}
});

// Track which invite notifications we've already shown this tab/session.
// This prevents repeated toasts on reconnect/reload while still allowing
// invites to be re-surfaced after a full sign-out.
const INV_SEEN_SS_KEY = "echochat_invite_seen_v1";
try {
  const raw = sessionStorage.getItem(INV_SEEN_SS_KEY);
  const arr = raw ? JSON.parse(raw) : [];
  if (Array.isArray(arr)) UIState.inviteSeen = new Set(arr.map(String));
} catch (e) {}

function rememberInviteSeen(key) {
  try {
    UIState.inviteSeen.add(String(key));
    sessionStorage.setItem(INV_SEEN_SS_KEY, JSON.stringify([...UIState.inviteSeen].slice(-200)));
  } catch (e) {}
}

function forgetInviteSeen(key) {
  try {
    UIState.inviteSeen.delete(String(key));
    sessionStorage.setItem(INV_SEEN_SS_KEY, JSON.stringify([...UIState.inviteSeen].slice(-200)));
  } catch (e) {}
}

function clampInt(v, min, max, fallback) {
  const n = parseInt(v, 10);
  if (Number.isNaN(n)) return fallback;
  return Math.max(min, Math.min(max, n));
}

function applyRoomFontSize(px) {
  const val = clampInt(px, 10, 22, 12);
  document.documentElement.style.setProperty("--room-font-size", `${val}px`);
  const out = $("setRoomFontSizeVal");
  if (out) out.textContent = `${val}px`;
}
