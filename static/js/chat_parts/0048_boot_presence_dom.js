// ───────────────────────────────────────────────────────────────────────────────
// Boot
// ───────────────────────────────────────────────────────────────────────────────
function setMyPresence(opts = {}) {
  const presence = opts.presence ?? $("meStatus")?.value ?? "online";
  // If custom_status key is present, we send it; otherwise we leave it unchanged.
  const payload = { presence };
  if (Object.prototype.hasOwnProperty.call(opts, "custom_status")) {
    payload.custom_status = opts.custom_status;
  }
  socket.emit("set_my_presence", payload, (res) => {
    if (res && res.success) {
      toast("✅ Status updated", "ok");
    } else {
      toast(`❌ ${res?.error || "Status update failed"}`, "error");
    }
  });
}

document.addEventListener("DOMContentLoaded", async () => {
  renderMyHubIdentity({ username: currentUser });
  bindHubProfileControls();

  // Theme
  setThemeFromPrefs();

  initHelpSystem();
  bindSettingsTabs();
  bindDockMenus();
  bindDockAddFriendPopup();
  bindDockNewPmComposer();
  try { bindBlockedUsersModal(); } catch (_) {}

  // Re-render friends list to apply display preferences immediately.
  try { getFriends(); } catch (_) {}
  bindFriendsSectionContextMenu();

  // Apply room text size preference
  applyRoomFontSize(UIState.prefs.roomFontSize);
  applyGifPickerPrefs();

  // Dock section ordering / drag-to-move
  initDockSectionReorder();
  bindDockAlertRail();

  // Tabs
  $("tabFriends")?.addEventListener("click", () => setActiveTab("friends"));
  $("tabGroups")?.addEventListener("click", () => setActiveTab("groups"));
  // Search
  const dockSearchEl = wireTransientSearchInputWhenAvailable("dockSearch", { clearOnLoad: true, clearOnPageShow: true, clearOnRefocusAfterBlur: true });
  const applyDockSearchFilterRaf = (typeof ecRafThrottle === 'function') ? ecRafThrottle((value) => applyDockSearchFilter(value)) : applyDockSearchFilter;
  dockSearchEl?.addEventListener("input", (e) => applyDockSearchFilterRaf(e.target.value));

  document.querySelectorAll("input.rbSearch").forEach((el) => wireTransientSearchInput(el, { clearOnLoad: true, clearOnPageShow: true, clearOnRefocusAfterBlur: false }));
  // Presence controls
  // Track the last real presence so our "Set custom status…" option doesn't send an invalid presence.
  if (!window.__ym_lastPresence) window.__ym_lastPresence = $("meStatus")?.value || "online";
  if (!window.__ec_manualPresence) window.__ec_manualPresence = window.__ym_lastPresence || "online";
  if (!window.__ec_autoAwayActive) window.__ec_autoAwayActive = false;
  if (!window.__ec_autoOfflineActive) window.__ec_autoOfflineActive = false;
  if (!window.__ym_lastCustomStatus) window.__ym_lastCustomStatus = "";

  $("meStatus")?.addEventListener("change", async () => {
    const sel = $("meStatus");
    if (!sel) return;
    const v = sel.value || "online";

    if (v === "__custom__") {
      // Revert select immediately; this is not a real presence value.
      sel.value = window.__ym_lastPresence || "online";
      const current = (window.__ym_lastCustomStatus || "").toString();
      const msg = await ecPrompt("Enter a custom status (max 128 characters):", current, {
        title: "Set custom status",
        inputLabel: "Custom status",
        confirmLabel: "Save status",
        maxLength: 128,
        placeholder: "What are you up to?",
      });
      if (msg === null) return; // cancelled
      const cleaned = (msg || "").toString().trim();
      window.__ym_lastCustomStatus = cleaned;
      setMyPresence({ presence: (window.__ym_lastPresence || "online"), custom_status: cleaned });
      const disp = $("meCustomDisplay");
      if (disp) {
        disp.textContent = cleaned ? `“${cleaned}”` : "";
        disp.style.display = cleaned ? "block" : "none";
      }
      return;
    }

    if (v === "__clear_custom__") {
      // Revert select immediately; clearing is orthogonal to presence.
      sel.value = window.__ym_lastPresence || "online";
      window.__ym_lastCustomStatus = "";
      setMyPresence({ presence: (window.__ym_lastPresence || "online"), custom_status: "" });
      const disp = $("meCustomDisplay");
      if (disp) {
        disp.textContent = "";
        disp.style.display = "none";
      }
      return;
    }

    // Real presence update
    window.__ym_lastPresence = v;
    window.__ec_manualPresence = v;
    window.__ec_autoAwayActive = false;
    window.__ec_autoOfflineActive = false;
    setMyPresence({ presence: v });
  });

  // Buttons
  $("btnCreateGroup")?.addEventListener("click", createGroup);
  $("btnJoinGroup")?.addEventListener("click", joinGroupById);
  $("btnRefreshGroupInvites")?.addEventListener("click", refreshGroupInvites);

  $("btnSettings")?.addEventListener("click", openSettings);
  $("btnHelpTour")?.addEventListener("click", () => startHelpTour({ auto: false }));

  $("btnLogout")?.addEventListener("click", async () => {
    const ok = await ecConfirm(`Log out of ${SERVER_NAME}?`, {
      title: 'Log out',
      confirmLabel: 'Log out',
      focusCancel: true,
    });
    if (!ok) return;
    try {
      await fetch("/logout", { method: "POST", credentials: "include", headers: (() => { const csrf = getCookie('csrf_access_token') || getCookie('csrf_refresh_token'); return csrf ? { 'X-CSRF-TOKEN': csrf } : {}; })() });
    } catch (_) {}
    window.location.href = "/login?reason=logged_out";
  });
  $("btnSaveSettings")?.addEventListener("click", saveSettings);
  $("btnCloseSettings")?.addEventListener("click", closeSettings);
  $("btnResetSettingsSection")?.addEventListener("click", resetCurrentSettingsSectionDraft);
  $("btnResetSettingsAll")?.addEventListener("click", resetAllSettingsDraft);

  $("btnTestSoundTheme")?.addEventListener("click", testUiSoundTheme);

  $("btnClearRoomChatData")?.addEventListener("click", clearVisibleRoomChatData);
  $("btnClearGroupChatData")?.addEventListener("click", clearVisibleGroupChatData);
  $("btnClearPmHistory")?.addEventListener("click", clearVisiblePrivateChatData);


  // Live preview inside Settings
  $("setRoomFontSize")?.addEventListener("input", (e) => applyRoomFontSize(e.target.value));
  $("setGifTileSize")?.addEventListener("input", (e) => {
    UIState.prefs.gifTileSize = clampInt(e.target.value, 96, 220, 140);
    applyGifPickerPrefs();
  });
  $("setGifShowTitles")?.addEventListener("change", (e) => {
    UIState.prefs.gifShowTitles = !!e.target.checked;
    applyGifPickerPrefs();
  });

  // Render rooms immediately if server gave them
  if (Array.isArray(window.INIT_ROOMS)) renderRooms(window.INIT_ROOMS);
  maybeAutoStartHelpTour();

  // Auto-unlock private messages using the main login password stored in sessionStorage (per-tab).
  // This removes the "second login" prompt for DMs.
  try {
    await tryAutoUnlockPrivateMessages("");
  } catch (_e) {
    // Non-fatal: user can still use rooms; DMs will show as locked.
  }

  // Ensure a valid access token after long idle / hard refresh.
  // We use the refresh token cookie (HttpOnly) + csrf_refresh_token cookie.
  try {
    await refreshAccessToken();
  } catch (e) {
    const msg = (e && (e.message || e.toString())) || "";
    // IMPORTANT:
    // Do NOT abort the entire chat bootstrap here.
    // If refresh fails right after page load (missing/rotated refresh cookie, race with
    // another tab, temporary CSRF mismatch, dev restart, etc.), returning here leaves the
    // room browser half-rendered and makes the page feel like "JavaScript is broken".
    // Instead we continue bootstrapping and let the normal socket/API auth recovery paths
    // decide whether the session can be recovered.
    if (/network error/i.test(msg)) {
      setConnBannerSoon("connecting", "⚠️ Server unreachable — reconnecting…", { showRetry: true });
    } else {
      setConnBannerSoon("refresh_pending", "🔑 Session refresh failed — trying your current session…", { spinner: true, showRetry: true }, 4500);
    }
  }

  AUTH_BOOTSTRAP_PENDING = false;

  let socketConnectRetried = false;

  async function recoverSocketAuth(trigger) {
    // Re-auth without redirecting; if it can't be recovered, pause traffic and ask user.
    if (AUTH_RECOVERY_IN_PROGRESS) return;
    await attemptAuthRecoveryFlow(trigger || 'auth_required');
  }

  // Server can emit this when a JWT expires inside an event handler.
  socket.on('auth_error', async (_payload) => {
    await recoverSocketAuth('auth_required');
  });
  socket.on("connect_error", async (err) => {
    const msg = (err && (err.message || err.toString())) || "";
	    EC_RECONNECT_IN_PROGRESS = false;

    // Auth-related connect errors: try a single refresh, then force login.
    if (/expired|unauthoriz|401/i.test(msg)) {
      if (!socketConnectRetried) {
        socketConnectRetried = true;
        await attemptAuthRecoveryFlow('auth_required');
        return;
      }
      enterAuthExpiredState('auth_required');
      return;
    }

    // Non-auth connect errors (server down / blocked / CORS): stay in-app.
	    setConnBannerSoon("connect_error", "⚠️ Can't reach server — retrying…", { showRetry: true });
  });

  socket.connect();

  // Room browser on the left.
  initRoomBrowser().catch(() => {});

  // Keep the access token fresh while the app is open.
  // Keep-alive: refresh ~every 22 minutes (below the 30-minute access TTL).
  // Keep-alive: refresh ~every 22 minutes (below the 30-minute access TTL).
  // Store timer so we can pause it during auth-expired mode.
  if (!EC_TOKEN_KEEPALIVE_TIMER) {
    EC_TOKEN_KEEPALIVE_TIMER = setInterval(() => {
      if (typeof AUTH_EXPIRED !== 'undefined' && AUTH_EXPIRED) return;
      refreshAccessToken().catch(() => {});
    }, 22 * 60 * 1000);
  }

  // If the tab was suspended (sleep/background), refresh on focus/visibility.
  // Do not disconnect the live socket just because a proactive refresh failed:
  // WebSocket connections keep the cookies from their original handshake, and
  // another tab may have already rotated the refresh token. True auth failures
  // are handled by HTTP 401 responses, auth_error, and connect_error.
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) {
      refreshAccessToken().catch((e) => {
        const msg = (e && (e.message || e.toString())) || "";
        if (/network error/i.test(msg) || (navigator && navigator.onLine === false)) {
          setConnBannerSoon("connecting", "⚠️ Server unreachable — reconnecting…");
          tryReconnectNow("focus_refresh_network_error");
        } else {
          console.warn("proactive token refresh failed; keeping current realtime session alive", msg);
        }
      });
    }
  });

  window.addEventListener("offline", () => {
    // Browser detected network loss.
    setConnBannerNow("offline", "📡 Offline — waiting for network…", { spinner: false, showRetry: false });
  });

  window.addEventListener("online", () => {
    // Network is back; attempt an immediate reconnect. Keep it silent unless
    // the offline banner was already visible.
    if (EC_CONN_STATE === "offline") {
      setConnBannerNow("reconnecting", "🔁 Network back — reconnecting…");
    }
    tryReconnectNow("online");
  });

  // Initial data (after socket connect)
});

// Connection hooks
if (socket && socket.io) {
  // Socket.IO Manager-level reconnection events (v4)
  socket.io.on("reconnect_attempt", (attempt) => {
    const n = Number(attempt || 0) || 0;
    EC_CONN_ATTEMPT = n;
    setConnBannerSoon("reconnecting", `🔁 Reconnecting… (attempt ${n})`);
  });
  socket.io.on("reconnect_error", (_err) => {
    setConnBannerSoon("reconnecting", "⚠️ Reconnect failed — retrying…");
  });
  socket.io.on("reconnect_failed", () => {
    setConnBannerNow("reconnect_failed", "❌ Could not reconnect. Click Retry.", { spinner: false, showRetry: true });
  });
}

let EC_RESTORE_IN_PROGRESS = false;

// On reconnect, re-join the last room and (optionally) re-join room voice.
// This fixes: server restart / Wi‑Fi blip → user stays on /chat but loses room membership.
