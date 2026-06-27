// Audio is blocked until a user gesture (browser autoplay policy).
// Arm sound after the first pointer interaction to avoid console spam.
let AUDIO_ARMED = false;
function armEchoAudio() { AUDIO_ARMED = true; }
document.addEventListener("pointerdown", armEchoAudio, { once: true });
document.addEventListener("keydown", armEchoAudio, { once: true });

// ───────────────────────────────────────────────────────────────────────────────
// DOM helpers
// ───────────────────────────────────────────────────────────────────────────────
function $(id) { return document.getElementById(id); }

const EC_THEME_ACCENTS = Object.freeze(["default", "blue", "purple", "emerald", "sunset", "slate", "rosewood", "paper"]);

function ecNormalizeThemeAccent(value) {
  const raw = String(value || "default").trim().toLowerCase().replace(/[\s-]+/g, "_");
  return EC_THEME_ACCENTS.includes(raw) ? raw : "default";
}

function setThemeFromPrefs() {
  const root = $("appRoot");
  const prefs = UIState?.prefs || {};
  const dark = !!prefs.darkMode;
  const highContrast = !!prefs.highContrast;

  const accent = ecNormalizeThemeAccent(prefs.accentTheme);
  const accentClasses = EC_THEME_ACCENTS.map((name) => `accent-${name}`);

  document.body.classList.toggle("theme-dark", dark);
  document.body.classList.toggle("theme-light", !dark);
  document.body.classList.toggle("contrast-high", highContrast);
  document.body.classList.remove(...accentClasses);
  document.body.classList.add(`accent-${accent}`);

  if (root) {
    root.classList.toggle("theme-dark", dark);
    root.classList.toggle("theme-light", !dark);
    root.classList.toggle("contrast-high", highContrast);
    root.classList.remove(...accentClasses);
    root.classList.add(`accent-${accent}`);
  }
}


function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (m) => ({
    "&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"
  }[m]));
}

function ecNormalizeSafeUrl(raw, opts = {}) {
  const allowRelative = opts.allowRelative !== false;
  const allowExternal = opts.allowExternal !== false;
  const value = String(raw || '').trim();
  if (!value) return '';
  try {
    const parsed = new URL(value, window.location.origin);
    const protocol = String(parsed.protocol || '').toLowerCase();
    if (protocol !== 'http:' && protocol !== 'https:') return '';
    const sameOrigin = parsed.origin === window.location.origin;
    if (!allowExternal && !sameOrigin) return '';
    const wasRelative = !/^[a-z][a-z0-9+.-]*:/i.test(value) && !value.startsWith('//');
    if (wasRelative && !allowRelative) return '';
    if (wasRelative && sameOrigin) {
      return `${parsed.pathname}${parsed.search}${parsed.hash}`;
    }
    return parsed.href;
  } catch {
    return '';
  }
}

function ecSafeUrlAttr(raw, opts = {}) {
  const safe = ecNormalizeSafeUrl(raw, opts);
  return safe ? escapeHtml(safe) : '';
}

function ecCssUrl(raw, opts = {}) {
  const safe = ecNormalizeSafeUrl(raw, opts);
  if (!safe) return '';
  const cssString = safe.replace(/[\\"\n\r\f]/g, (ch) => ({
    '\\': '\\\\',
    '"': '\\"',
    '\n': '\\a ',
    '\r': '\\d ',
    '\f': '\\c ',
  }[ch] || ''));
  return `url("${cssString}")`;
}

function ecClearNode(node) {
  if (!node) return;
  try {
    node.replaceChildren();
    return;
  } catch {}
  try {
    while (node.firstChild) node.removeChild(node.firstChild);
  } catch {}
}



function ecNextAnimationFrame(fn) {
  const cb = (typeof fn === 'function') ? fn : function () {};
  try {
    return window.requestAnimationFrame(cb);
  } catch {
    return window.setTimeout(cb, 16);
  }
}

function ecCancelAnimationFrame(handle) {
  if (handle === undefined || handle === null) return;
  try { window.cancelAnimationFrame(handle); } catch { try { window.clearTimeout(handle); } catch {} }
}

function ecRafThrottle(fn) {
  let frame = null;
  let lastArgs = null;
  let lastThis = null;
  const run = () => {
    frame = null;
    const args = lastArgs || [];
    const ctx = lastThis;
    lastArgs = null;
    lastThis = null;
    try { fn.apply(ctx, args); } catch (err) { console.error(err); }
  };
  const throttled = function (...args) {
    lastArgs = args;
    lastThis = this;
    if (frame !== null) return;
    frame = ecNextAnimationFrame(run);
  };
  throttled.cancel = () => {
    if (frame !== null) ecCancelAnimationFrame(frame);
    frame = null;
    lastArgs = null;
    lastThis = null;
  };
  throttled.flush = () => {
    if (frame === null) return;
    ecCancelAnimationFrame(frame);
    run();
  };
  return throttled;
}

function ecRestartAnimationClass(el, cls, timeoutMs = 520, onStarted = null) {
  if (!el || !cls) return;
  try { el.classList.remove(cls); } catch {}
  // Avoid `void el.offsetWidth` forced-layout restarts. Queue the re-add for the
  // browser's next paint cycle so style invalidation and animation start stay
  // batched with other writes.
  ecNextAnimationFrame(() => {
    ecNextAnimationFrame(() => {
      try {
        if (!el.isConnected) return;
        el.classList.add(cls);
        if (typeof onStarted === 'function') onStarted();
      } catch {}
    });
  });
}

function ecCreateEl(tag, opts = {}, children = []) {
  const el = document.createElement(tag);
  if (opts.id) el.id = String(opts.id);
  if (opts.className) el.className = String(opts.className);
  if (opts.text !== undefined) el.textContent = String(opts.text);
  if (opts.type) el.setAttribute('type', String(opts.type));
  if (opts.title) el.title = String(opts.title);
  if (opts.value !== undefined) el.value = String(opts.value);
  if (opts.placeholder !== undefined) el.setAttribute('placeholder', String(opts.placeholder));
  if (opts.autocomplete !== undefined) el.setAttribute('autocomplete', String(opts.autocomplete));
  if (opts.role) el.setAttribute('role', String(opts.role));
  if (opts.ariaLabel) el.setAttribute('aria-label', String(opts.ariaLabel));
  if (opts.ariaModal !== undefined) el.setAttribute('aria-modal', String(opts.ariaModal));
  if (opts.ariaLive) el.setAttribute('aria-live', String(opts.ariaLive));
  if (opts.ariaAtomic !== undefined) el.setAttribute('aria-atomic', String(opts.ariaAtomic));
  if (opts.ariaHidden !== undefined) el.setAttribute('aria-hidden', String(opts.ariaHidden));
  if (opts.htmlFor) el.setAttribute('for', String(opts.htmlFor));
  if (opts.attrs && typeof opts.attrs === 'object') {
    Object.entries(opts.attrs).forEach(([k, v]) => {
      if (v === undefined || v === null || v === false) return;
      el.setAttribute(String(k), v === true ? '' : String(v));
    });
  }
  if (opts.dataset && typeof opts.dataset === 'object') {
    Object.entries(opts.dataset).forEach(([k, v]) => {
      if (v === undefined || v === null) return;
      el.dataset[String(k)] = String(v);
    });
  }
  const kids = Array.isArray(children) ? children : [children];
  kids.forEach((child) => {
    if (child === undefined || child === null || child === false) return;
    if (child instanceof Node) el.appendChild(child);
    else el.appendChild(document.createTextNode(String(child)));
  });
  return el;
}

function ecListStatusItem(opts = {}) {
  const li = document.createElement('li');
  li.dataset.name = String(opts.name || 'none');
  if (opts.search !== undefined) li.dataset.search = String(opts.search || '');
  if (opts.className) li.className = String(opts.className);
  const left = ecCreateEl('div', { className: 'liLeft' });
  if (opts.dot !== false) left.appendChild(ecCreateEl('span', { className: `presDot ${String(opts.dot || 'offline')}` }));
  if (opts.avatar !== false) left.appendChild(ecCreateEl('span', { className: 'liAvatar', text: opts.avatar !== undefined ? opts.avatar : '-' }));
  left.appendChild(ecCreateEl('span', { className: opts.muted === false ? 'liName' : 'liName muted', text: opts.text !== undefined ? opts.text : 'None' }));
  li.appendChild(left);
  return li;
}

function ecCtxHeader(label, id) {
  const span = ecCreateEl('span', { id, className: 'ecCtxUser', text: label || '' });
  return ecCreateEl('div', { className: 'ecCtxHeader' }, [span]);
}

function ecCtxItem(action, icon, label, extraClass = '') {
  return ecCreateEl('div', {
    className: `ecCtxItem${extraClass ? ` ${extraClass}` : ''}`,
    dataset: { action }
  }, [String(icon || ''), ' ', ecCreateEl('span', { text: label || '' })]);
}

function ecCtxSep() {
  return ecCreateEl('div', { className: 'ecCtxSep' });
}

function ecSetSafeUrlAttr(el, attr, raw, opts = {}) {
  if (!el || !attr) return '';
  const safe = ecNormalizeSafeUrl(raw, opts);
  if (!safe) {
    try { el.removeAttribute(attr); } catch {}
    return '';
  }
  try { el.setAttribute(attr, safe); } catch {}
  return safe;
}

function ecOpenSafeUrl(raw, opts = {}) {
  const safe = ecNormalizeSafeUrl(raw, { allowRelative: false, allowExternal: true, ...opts });
  if (!safe) return false;
  const target = opts.target || '_blank';
  const features = opts.features || 'noopener,noreferrer';
  try {
    window.open(safe, target, features);
    return true;
  } catch {
    try { window.open(safe, target, 'noopener,noreferrer'); return true; } catch {}
  }
  return false;
}
