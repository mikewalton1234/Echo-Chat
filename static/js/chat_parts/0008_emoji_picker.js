// ───────────────────────────────────────────────────────────────────────────────
// Emoticons / Emoji picker (rooms + DMs + groups)
//
// We use a self-hosted emoji picker library (no hardcoded emoji list) via:
//   https://github.com/nolanlawson/emoji-picker-element
//   It is loaded lazily with dynamic import() the first time the picker opens.
//
// Design goals:
// - Zero server changes (emoji are just Unicode text)
// - Works everywhere we have a message <input>
// - One shared popover instance
// ───────────────────────────────────────────────────────────────────────────────

function insertAtCursor(inputEl, text) {
  if (!inputEl) return;
  const v = String(inputEl.value || "");
  const start = (typeof inputEl.selectionStart === "number") ? inputEl.selectionStart : v.length;
  const end = (typeof inputEl.selectionEnd === "number") ? inputEl.selectionEnd : v.length;
  const next = v.slice(0, start) + text + v.slice(end);
  inputEl.value = next;
  const pos = start + text.length;
  try { inputEl.setSelectionRange(pos, pos); } catch { /* ignore */ }
  inputEl.focus();
  try { inputEl.dispatchEvent(new Event("input", { bubbles: true })); } catch { /* ignore */ }
}

const EMOJI_PICKER_MODULE_URLS = [
  // Preferred local vendored copy of the official module.
  "/static/vendor/emoji-picker-element/picker.js",
  // Backward-compatible fallback for older local bundles.
  "/static/vendor/emoji-picker-element/index.js"
];
const EMOJI_PICKER_DATA_URLS = [
  "/static/vendor/emoji-picker-element-data/en/emojibase/data.json"
];

function ecVersionedStaticUrl(url) {
  const raw = String(url || "").trim();
  if (!raw) return raw;
  const version = String(window.ECHOCHAT_APP_VERSION || "").trim();
  if (!version) return raw;
  try {
    const u = new URL(raw, window.location.origin);
    if (u.origin !== window.location.origin || !u.pathname.startsWith("/static/")) return raw;
    if (!u.searchParams.has("v")) u.searchParams.set("v", version);
    return u.pathname + u.search + u.hash;
  } catch (_) {
    return raw;
  }
}
// Official pinned CDN files used by tools/download_emoji_picker_vendor.sh:
//   https://cdn.jsdelivr.net/npm/emoji-picker-element@1.29.1/picker.js
//   https://cdn.jsdelivr.net/npm/emoji-picker-element@1.29.1/database.js
//   https://cdn.jsdelivr.net/npm/emoji-picker-element-data@1.8.0/en/emojibase/data.json

const EmojiUI = {
  pop: null,
  picker: null,
  activeInput: null,
  activeAnchor: null,
  visible: false,
  moduleReady: false,
  loadPromise: null,
  statusEl: null
};

async function ensureEmojiLibraryLoaded() {
  try {
    if (window.customElements?.get?.("emoji-picker")) {
      EmojiUI.moduleReady = true;
      return true;
    }
  } catch {}

  if (EmojiUI.loadPromise) return EmojiUI.loadPromise;

  EmojiUI.loadPromise = (async () => {
    for (const url of EMOJI_PICKER_MODULE_URLS) {
      try {
        await import(ecVersionedStaticUrl(url));
        if (window.customElements?.get?.("emoji-picker")) {
          EmojiUI.moduleReady = true;
          return true;
        }
      } catch (err) {
        console.warn("[emoji] failed to load picker module", url, err);
      }
    }
    EmojiUI.moduleReady = false;
    return false;
  })();

  return EmojiUI.loadPromise;
}

function setEmojiStatus(message) {
  if (!EmojiUI.statusEl) return;
  const msg = String(message || "").trim();
  EmojiUI.statusEl.textContent = msg;
  EmojiUI.statusEl.classList.toggle("hidden", !msg);
}

function ensureEmojiPopover() {
  if (EmojiUI.pop) return EmojiUI.pop;

  const pop = document.createElement("div");
  pop.id = "ecEmojiPopover";
  pop.className = "ec-emojiPopover hidden";
  pop.setAttribute("role", "dialog");
  pop.setAttribute("aria-label", "Emoticons");

  const status = document.createElement("div");
  status.className = "ec-emojiStatus hidden";
  status.setAttribute("aria-live", "polite");
  pop.appendChild(status);

  // The custom element is defined by emoji-picker-element (loaded as a module script).
  const picker = document.createElement("emoji-picker");
  picker.id = "ecEmojiPicker";

  // Self-hosted picker/data path served directly by EchoChat.
  picker.setAttribute("data-source", ecVersionedStaticUrl(EMOJI_PICKER_DATA_URLS[0]));

  pop.appendChild(picker);
  document.body.appendChild(pop);

  const position = () => {
    if (!EmojiUI.activeAnchor) return;
    const r = EmojiUI.activeAnchor.getBoundingClientRect();

    // Match the fixed CSS sizes without forcing a popover layout read.
    const compact = (() => {
      try { return window.matchMedia('(max-width: 520px)').matches; } catch { return false; }
    })();
    const w = compact ? 320 : 360;
    const h = compact ? 380 : 420;

    let left = Math.max(8, Math.min(window.innerWidth - w - 8, r.right - w));
    let top = r.top - h - 8;
    if (top < 8) top = Math.min(window.innerHeight - h - 8, r.bottom + 8);

    pop.style.left = `${left}px`;
    pop.style.top = `${top}px`;
  };

  // Insert emoji into the active input
  picker.addEventListener("emoji-click", (event) => {
    const d = event?.detail || {};
    const unicode = d.unicode || d.emoji?.unicode || d.emoji?.native || d.emoji?.emoji || "";
    if (unicode && EmojiUI.activeInput) {
      insertAtCursor(EmojiUI.activeInput, unicode);
    }
    closeEmojiPicker();
  });

  // One global outside-click handler
  if (!document.body.dataset.ecEmojiOutsideBound) {
    document.body.dataset.ecEmojiOutsideBound = "1";
    document.addEventListener("mousedown", (e) => {
      if (!EmojiUI.visible || !EmojiUI.pop) return;
      const t = e.target;
      if (!(t instanceof Node)) return;
      if (EmojiUI.pop.contains(t)) return;
      if (EmojiUI.activeAnchor && EmojiUI.activeAnchor.contains(t)) return;
      closeEmojiPicker();
    });
    window.addEventListener("resize", () => { if (EmojiUI.visible) closeEmojiPicker(); });
    window.addEventListener("scroll", () => { if (EmojiUI.visible) closeEmojiPicker(); }, true);
    document.addEventListener("keydown", (e) => { if (EmojiUI.visible && e.key === "Escape") closeEmojiPicker(); });
  }

  // Expose helpers
  EmojiUI.pop = pop;
  EmojiUI.picker = picker;
  EmojiUI.statusEl = status;
  pop._ecPosition = position;
  return pop;
}

async function openEmojiPicker(anchorEl, inputEl) {
  const ok = await ensureEmojiLibraryLoaded();
  const pop = ensureEmojiPopover();

  // Toggle if clicking the same button while open
  if (EmojiUI.visible && EmojiUI.activeAnchor === anchorEl) {
    closeEmojiPicker();
    return;
  }

  EmojiUI.activeInput = inputEl || null;
  EmojiUI.activeAnchor = anchorEl || null;

  if (!ok) {
    setEmojiStatus("Emoticons could not load from this server. Please refresh and check the browser console for details.");
  } else {
    setEmojiStatus("");
    if (EmojiUI.picker && !window.customElements?.get?.("emoji-picker")) {
      // Last-chance fallback: re-apply the local dataset path after the module loads.
      try { EmojiUI.picker.setAttribute("data-source", ecVersionedStaticUrl(EMOJI_PICKER_DATA_URLS[0])); } catch {}
    }
  }

  pop.classList.remove("hidden");
  EmojiUI.visible = true;
  if (typeof ecNextAnimationFrame === 'function') ecNextAnimationFrame(() => pop._ecPosition && pop._ecPosition());
  else pop._ecPosition && pop._ecPosition();
}

function closeEmojiPicker() {
  if (!EmojiUI.pop) return;
  EmojiUI.pop.classList.add("hidden");
  EmojiUI.visible = false;
  EmojiUI.activeInput = null;
  EmojiUI.activeAnchor = null;
}

function bindEmojiButton(btnEl, inputEl) {
  if (!btnEl || !inputEl) return;
  if (btnEl.dataset.ecEmojiBound === "1") return;
  btnEl.dataset.ecEmojiBound = "1";
  btnEl.addEventListener("click", (e) => {
    e.preventDefault();
    e.stopPropagation();
    void openEmojiPicker(btnEl, inputEl);
  });
}
