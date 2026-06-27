// ───────────────────────────────────────────────────────────────────────────────
// Settings modal
// ───────────────────────────────────────────────────────────────────────────────
function getGifResultsLimit() {
  const n = clampInt(UIState?.prefs?.gifResultsPerLoad, 12, 48, 12);
  return [12, 24, 36, 48].includes(n) ? n : 12;
}

function applyGifPickerPrefs() {
  const size = clampInt(UIState?.prefs?.gifTileSize, 96, 220, 140);
  const showTitles = UIState?.prefs?.gifShowTitles !== false;
  const labelDisplay = showTitles ? 'block' : 'none';
  const targets = [document.documentElement, document.body, GifUI?.modal, GifUI?.card, GifUI?.grid].filter(Boolean);
  try {
    targets.forEach((el) => {
      el.style.setProperty('--ec-gif-tile-size', `${size}px`);
      el.style.setProperty('--ec-gif-label-display', labelDisplay);
    });
  } catch {}

  try {
    if (GifUI?.grid) {
      GifUI.grid.style.gridTemplateColumns = `repeat(auto-fill, minmax(${size}px, 1fr))`;
    }
    document.querySelectorAll('.ym-gifItemImg').forEach((img) => {
      img.style.height = `${size}px`;
    });
    document.querySelectorAll('.ym-gifItemLabel').forEach((label) => {
      label.style.display = labelDisplay;
    });
  } catch {}

  const out = $("setGifTileSizeVal");
  if (out) out.textContent = `${size}px`;
}

const SETTINGS_PREF_DEFAULTS = Object.freeze({
  darkMode: false,
  highContrast: false,
  accentTheme: 'default',
  popupNotif: false,
  soundNotif: ECHOCHAT_CFG.sound_notifications_default === undefined ? true : !!ECHOCHAT_CFG.sound_notifications_default,
  soundTheme: String(ECHOCHAT_CFG.sound_theme_default || ECHOCHAT_CFG.default_sound_theme || 'soft_chime'),
  roomFontSize: 12,
  gifTileSize: 140,
  gifResultsPerLoad: 12,
  gifOpenMode: 'recents',
  gifShowTitles: true,
  gifKeepOpen: false,
  missedToast: true,
  savePmLocal: false,
  friendStatusInline: true,
  friendStatusTooltip: true,
  helpHints: true
});

const SETTINGS_SECTION_KEYS = Object.freeze({
  chat: ['roomFontSize', 'gifTileSize', 'gifResultsPerLoad', 'gifOpenMode', 'gifShowTitles', 'gifKeepOpen'],
  theme: ['darkMode', 'highContrast', 'accentTheme'],
  alerts: ['popupNotif', 'soundNotif', 'soundTheme', 'missedToast'],
  friends: ['friendStatusInline', 'friendStatusTooltip', 'helpHints']
});

function getSettingsDefaultValue(key) {
  return Object.prototype.hasOwnProperty.call(SETTINGS_PREF_DEFAULTS, key)
    ? SETTINGS_PREF_DEFAULTS[key]
    : null;
}

function getSettingsDraftValue(draft, key, fallback) {
  if (draft && Object.prototype.hasOwnProperty.call(draft, key)) return draft[key];
  if (UIState?.prefs && Object.prototype.hasOwnProperty.call(UIState.prefs, key)) return UIState.prefs[key];
  return fallback;
}

function applySettingsDraftToControls(draft = {}) {
  const boolVal = (key, fallback = false) => !!getSettingsDraftValue(draft, key, fallback);
  const strVal = (key, fallback = '') => {
    const value = getSettingsDraftValue(draft, key, fallback);
    return value == null ? String(fallback || '') : String(value);
  };
  const numVal = (key, min, max, fallback) => clampInt(getSettingsDraftValue(draft, key, fallback), min, max, fallback);

  const dark = $("setDarkMode");
  if (dark) dark.checked = boolVal('darkMode', false);
  const contrast = $("setHighContrast");
  if (contrast) contrast.checked = boolVal('highContrast', false);
  const accent = $("setAccentTheme");
  if (accent) accent.value = strVal('accentTheme', 'default');
  const popup = $("setPopupNotif");
  if (popup) popup.checked = boolVal('popupNotif', false);
  const sound = $("setSoundNotif");
  if (sound) sound.checked = boolVal('soundNotif', SETTINGS_PREF_DEFAULTS.soundNotif);
  const soundTheme = $("setSoundTheme");
  if (soundTheme) {
    try { ecPopulateSoundSelect(soundTheme, strVal('soundTheme', SETTINGS_PREF_DEFAULTS.soundTheme), { showFiles: true }); } catch {}
    soundTheme.value = ecNormalizeSoundTheme(strVal('soundTheme', SETTINGS_PREF_DEFAULTS.soundTheme));
  }
  const missed = $("setMissedToast");
  if (missed) missed.checked = boolVal('missedToast', true);
  const savePm = $("setSavePmLocal");
  if (savePm) savePm.checked = boolVal('savePmLocal', false);
  const friendInline = $("setFriendStatusInline");
  if (friendInline) friendInline.checked = boolVal('friendStatusInline', true);
  const friendTip = $("setFriendStatusTooltip");
  if (friendTip) friendTip.checked = boolVal('friendStatusTooltip', true);
  const helpHints = $("setHelpHints");
  if (helpHints) helpHints.checked = boolVal('helpHints', true);

  const roomSlider = $("setRoomFontSize");
  const roomSize = numVal('roomFontSize', 10, 22, 12);
  if (roomSlider) roomSlider.value = String(roomSize);
  applyRoomFontSize(roomSize);

  const gifSize = $("setGifTileSize");
  const gifTile = numVal('gifTileSize', 96, 220, 140);
  if (gifSize) gifSize.value = String(gifTile);
  UIState.prefs.gifTileSize = gifTile;

  const gifCount = $("setGifResultsPerLoad");
  const gifResultsRaw = Number(getSettingsDraftValue(draft, 'gifResultsPerLoad', 12));
  const gifResults = [12, 24, 36, 48].includes(gifResultsRaw) ? gifResultsRaw : 12;
  if (gifCount) gifCount.value = String(gifResults);

  const gifMode = $("setGifOpenMode");
  const openMode = ['recents', 'trending', 'last_search'].includes(strVal('gifOpenMode', 'recents')) ? strVal('gifOpenMode', 'recents') : 'recents';
  if (gifMode) gifMode.value = openMode;

  const gifTitles = $("setGifShowTitles");
  const showTitles = boolVal('gifShowTitles', true);
  if (gifTitles) gifTitles.checked = showTitles;
  UIState.prefs.gifShowTitles = showTitles;

  const gifKeep = $("setGifKeepOpen");
  if (gifKeep) gifKeep.checked = boolVal('gifKeepOpen', false);

  applyGifPickerPrefs();
  updateSettingsResetButtons();
}

function updateSettingsResetButtons() {
  const btn = $("btnResetSettingsSection");
  if (!btn) return;
  const tab = String(UIState?.prefs?.settingsTab || 'chat');
  const keys = SETTINGS_SECTION_KEYS[tab] || [];
  const enabled = keys.length > 0;
  btn.disabled = !enabled;
  btn.title = enabled ? 'Reset the current settings tab to its defaults' : 'This section does not have resettable saved settings';
}

function resetCurrentSettingsSectionDraft() {
  const tab = String(UIState?.prefs?.settingsTab || 'chat');
  const keys = SETTINGS_SECTION_KEYS[tab] || [];
  if (!keys.length) {
    toast('ℹ️ This section has no resettable saved settings', 'info');
    updateSettingsResetButtons();
    return;
  }
  const draft = {};
  keys.forEach((key) => {
    draft[key] = getSettingsDefaultValue(key);
  });
  applySettingsDraftToControls(draft);
  toast('↺ Current settings section reset. Click Save to keep it.', 'info');
}

async function resetAllSettingsDraft() {
  const ok = await ecConfirm(`Reset all ${SERVER_NAME} settings in this browser back to defaults? Click Save after reviewing to keep the reset.`, {
    title: 'Reset all settings',
    confirmLabel: 'Reset all',
    danger: true,
    focusCancel: true,
  });
  if (!ok) return;
  applySettingsDraftToControls(SETTINGS_PREF_DEFAULTS);
  toast('↺ All settings reset to defaults. Click Save to keep them.', 'info');
}

function setSettingsTab(tabName, opts = {}) {
  const requested = String(tabName || 'chat');
  const tabs = Array.from(document.querySelectorAll('.settingsTabBtn[data-settings-tab]'));
  const panels = Array.from(document.querySelectorAll('.settingsPanel[data-settings-panel]'));
  const hasRequested = tabs.some((btn) => btn.dataset.settingsTab === requested)
    && panels.some((panel) => panel.dataset.settingsPanel === requested);
  const name = hasRequested ? requested : 'chat';

  let activeTabButton = null;
  tabs.forEach((btn) => {
    const active = btn.dataset.settingsTab === name;
    btn.classList.toggle('is-active', active);
    btn.setAttribute('aria-selected', active ? 'true' : 'false');
    if (active) activeTabButton = btn;
  });
  panels.forEach((panel) => {
    const active = panel.dataset.settingsPanel === name;
    panel.classList.toggle('is-active', active);
    panel.hidden = !active;
  });

  UIState.prefs.settingsTab = name;
  if (opts.persist !== false) Settings.set('settingsTab', name);
  updateSettingsResetButtons();
  if (activeTabButton && opts.scrollIntoView !== false) {
    try { activeTabButton.scrollIntoView({ inline: 'center', block: 'nearest', behavior: 'smooth' }); } catch (_) {}
  }
}

function bindSettingsTabs() {
  if (document.body?.dataset?.ecSettingsTabsBound === '1') return;
  if (document.body) document.body.dataset.ecSettingsTabsBound = '1';
  document.querySelectorAll('.settingsTabBtn[data-settings-tab]').forEach((btn) => {
    btn.addEventListener('click', () => setSettingsTab(btn.dataset.settingsTab || 'chat'));
  });
}

function previewThemeSettingsFromControls() {
  const dark = $("setDarkMode");
  const contrast = $("setHighContrast");
  const accent = $("setAccentTheme");
  UIState.prefs.darkMode = dark ? !!dark.checked : false;
  UIState.prefs.highContrast = contrast ? !!contrast.checked : false;
  UIState.prefs.accentTheme = (typeof ecNormalizeThemeAccent === 'function')
    ? ecNormalizeThemeAccent(accent ? accent.value : 'default')
    : String(accent?.value || 'default');
  setThemeFromPrefs();
}

function bindSettingsLivePreview() {
  if (document.body?.dataset?.ecSettingsPreviewBound === '1') return;
  if (document.body) document.body.dataset.ecSettingsPreviewBound = '1';
  ['setDarkMode', 'setHighContrast', 'setAccentTheme'].forEach((id) => {
    const el = $(id);
    if (!el) return;
    el.addEventListener('input', previewThemeSettingsFromControls);
    el.addEventListener('change', previewThemeSettingsFromControls);
  });
}

function openSettings() {
  clearSearchesForModalTransition();
  const modal = $("settingsModal");
  if (!modal) return;

  applySettingsDraftToControls(UIState.prefs);
  syncHelpHintsSettingUi();
  bindSettingsLivePreview();

  modal.dataset.prevRoomFontSize = String(UIState.prefs.roomFontSize ?? 12);
  modal.dataset.prevGifTileSize = String(clampInt(UIState.prefs.gifTileSize, 96, 220, 140));
  modal.dataset.prevGifShowTitles = UIState.prefs.gifShowTitles === false ? '0' : '1';
  modal.dataset.prevDarkMode = UIState.prefs.darkMode ? '1' : '0';
  modal.dataset.prevHighContrast = UIState.prefs.highContrast ? '1' : '0';
  modal.dataset.prevAccentTheme = String(UIState.prefs.accentTheme || 'default');
  modal.dataset.settingsPreviewActive = '1';
  setSettingsTab(UIState.prefs.settingsTab || 'chat', { persist: false });

  modal.classList.remove("hidden");
}

function closeSettings(opts = {}) {
  const shouldRevertPreview = opts.revertPreview !== false;
  // If user closes without saving, revert any live preview.
  const modal = $("settingsModal");
  if (shouldRevertPreview && modal?.dataset?.settingsPreviewActive === '1') {
    const prev = modal.dataset.prevRoomFontSize;
    if (prev) applyRoomFontSize(prev);
    if (modal.dataset.prevGifTileSize !== undefined) {
      UIState.prefs.gifTileSize = clampInt(modal.dataset.prevGifTileSize, 96, 220, UIState.prefs.gifTileSize || 140);
    }
    if (modal.dataset.prevGifShowTitles !== undefined) UIState.prefs.gifShowTitles = modal.dataset.prevGifShowTitles !== '0';
    if (modal.dataset.prevDarkMode !== undefined) UIState.prefs.darkMode = modal.dataset.prevDarkMode === '1';
    if (modal.dataset.prevHighContrast !== undefined) UIState.prefs.highContrast = modal.dataset.prevHighContrast === '1';
    if (modal.dataset.prevAccentTheme !== undefined) UIState.prefs.accentTheme = String(modal.dataset.prevAccentTheme || 'default');
    applyGifPickerPrefs();
    setThemeFromPrefs();
  }
  if (modal) modal.dataset.settingsPreviewActive = '0';
  $("settingsModal")?.classList.add("hidden");
  clearSearchesForModalTransition();
}

async function requestNotifPermissionIfNeeded() {
  if (!("Notification" in window)) return;
  if (Notification.permission === "default") {
    try { await Notification.requestPermission(); } catch {}
  }
}

function saveSettings() {
  const dm = $("setDarkMode");
  UIState.prefs.darkMode = dm ? !!dm.checked : false;
  const hc = $("setHighContrast");
  UIState.prefs.highContrast = hc ? !!hc.checked : false;
  const at = $("setAccentTheme");
  UIState.prefs.accentTheme = (typeof ecNormalizeThemeAccent === 'function')
    ? ecNormalizeThemeAccent(at ? at.value : UIState.prefs.accentTheme)
    : String(at?.value || UIState.prefs.accentTheme || "default");
  const popup = $("setPopupNotif");
  UIState.prefs.popupNotif = popup ? !!popup.checked : false;
  const soundNotif = $("setSoundNotif");
  UIState.prefs.soundNotif = soundNotif ? !!soundNotif.checked : SETTINGS_PREF_DEFAULTS.soundNotif;
  const soundTheme = $("setSoundTheme");
  UIState.prefs.soundTheme = ecNormalizeSoundTheme(soundTheme ? soundTheme.value : UIState.prefs.soundTheme);

  const mt = $("setMissedToast");
  UIState.prefs.missedToast = mt ? !!mt.checked : true;
  UIState.prefs.savePmLocal = false;

  const fsi = $("setFriendStatusInline");
  UIState.prefs.friendStatusInline = fsi ? !!fsi.checked : true;
  const fst = $("setFriendStatusTooltip");
  UIState.prefs.friendStatusTooltip = fst ? !!fst.checked : true;
  const hhc = $("setHelpHints");
  UIState.prefs.helpHints = hhc ? !!hhc.checked : true;

  const slider = $("setRoomFontSize");
  if (slider) {
    UIState.prefs.roomFontSize = clampInt(slider.value, 10, 22, 12);
    Settings.set("roomFontSize", UIState.prefs.roomFontSize);
    applyRoomFontSize(UIState.prefs.roomFontSize);
    const modal = $("settingsModal");
    if (modal) modal.dataset.prevRoomFontSize = String(UIState.prefs.roomFontSize);
  }

  const gifSize = $("setGifTileSize");
  UIState.prefs.gifTileSize = gifSize ? clampInt(gifSize.value, 96, 220, 140) : 140;
  const gifCount = $("setGifResultsPerLoad");
  UIState.prefs.gifResultsPerLoad = gifCount ? clampInt(gifCount.value, 12, 48, 12) : 12;
  if (![12,24,36,48].includes(UIState.prefs.gifResultsPerLoad)) UIState.prefs.gifResultsPerLoad = 12;
  const gifMode = $("setGifOpenMode");
  UIState.prefs.gifOpenMode = gifMode ? String(gifMode.value || 'recents') : 'recents';
  if (!["recents","trending","last_search"].includes(UIState.prefs.gifOpenMode)) UIState.prefs.gifOpenMode = 'recents';
  const gifTitles = $("setGifShowTitles");
  const gifKeepOpen = $("setGifKeepOpen");
  UIState.prefs.gifShowTitles = gifTitles ? !!gifTitles.checked : true;
  UIState.prefs.gifKeepOpen = gifKeepOpen ? !!gifKeepOpen.checked : false;
  const modal = $("settingsModal");
  if (modal) {
    modal.dataset.prevGifTileSize = String(UIState.prefs.gifTileSize);
    modal.dataset.prevGifShowTitles = UIState.prefs.gifShowTitles ? '1' : '0';
  }
  applyGifPickerPrefs();

  Settings.set("darkMode", UIState.prefs.darkMode);
  Settings.set("highContrast", UIState.prefs.highContrast);
  Settings.set("accentTheme", UIState.prefs.accentTheme);
  Settings.set("popupNotif", UIState.prefs.popupNotif);
  Settings.set("soundNotif", UIState.prefs.soundNotif);
  Settings.set("soundTheme", UIState.prefs.soundTheme);
  Settings.set("missedToast", UIState.prefs.missedToast);
  Settings.set("savePmLocal", false);
  Settings.set("gifTileSize", UIState.prefs.gifTileSize);
  Settings.set("gifResultsPerLoad", UIState.prefs.gifResultsPerLoad);
  Settings.set("gifOpenMode", UIState.prefs.gifOpenMode);
  Settings.set("gifShowTitles", UIState.prefs.gifShowTitles);
  Settings.set("gifKeepOpen", UIState.prefs.gifKeepOpen);
  Settings.set("settingsTab", UIState.prefs.settingsTab || 'chat');
  Settings.set("friendStatusInline", UIState.prefs.friendStatusInline);
  Settings.set("friendStatusTooltip", UIState.prefs.friendStatusTooltip);
  setHelpHintsEnabled(UIState.prefs.helpHints, { persist: true, syncUi: false });

  setThemeFromPrefs();

  // Re-render friends list to apply display preferences immediately.
  try { getFriends(); } catch (_) {}

  if (UIState.prefs.popupNotif) requestNotifPermissionIfNeeded();

  toast("✅ Settings saved", "ok");
  closeSettings({ revertPreview: false });
}
