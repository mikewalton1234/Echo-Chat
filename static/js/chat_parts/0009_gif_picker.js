// ───────────────────────────────────────────────────────────────────────────────
// GIF picker (GIPHY)
// ───────────────────────────────────────────────────────────────────────────────
const GIF_RECENTS_KEY = 'gif_recents_v1';

function getGifRecentsStorageKey() {
  try {
    return (typeof buildScopedStorageKey === 'function') ? buildScopedStorageKey(GIF_RECENTS_KEY) : `ec_${GIF_RECENTS_KEY}`;
  } catch {
    return `ec_${GIF_RECENTS_KEY}`;
  }
}
const GIF_RECENTS_LIMIT = 24;

const GifUI = {
  modal: null,
  card: null,
  closeBtn: null,
  search: null,
  searchBtn: null,
  recentBtn: null,
  trendingBtn: null,
  randomBtn: null,
  status: null,
  grid: null,
  onPick: null,
  visible: false,
  mode: 'recents',
  lastResults: [],
};

function gifReadRecents() {
  try {
    const raw = localStorage.getItem(getGifRecentsStorageKey()) || '[]';
    const arr = JSON.parse(raw);
    if (!Array.isArray(arr)) return [];
    return arr
      .map((g) => ({
        id: String(g?.id || '').trim(),
        title: String(g?.title || '').trim(),
        url: String(g?.url || '').trim(),
        preview: String(g?.preview || g?.url || '').trim(),
      }))
      .filter((g) => g.url)
      .slice(0, GIF_RECENTS_LIMIT);
  } catch {
    return [];
  }
}

function gifWriteRecents(items) {
  try {
    localStorage.setItem(getGifRecentsStorageKey(), JSON.stringify((items || []).slice(0, GIF_RECENTS_LIMIT)));
    try { localStorage.removeItem(`ec_${GIF_RECENTS_KEY}`); } catch {}
  } catch {}
}

function gifPushRecent(item) {
  if (!item?.url) return;
  const next = [
    {
      id: String(item.id || '').trim(),
      title: String(item.title || '').trim(),
      url: String(item.url || '').trim(),
      preview: String(item.preview || item.url || '').trim(),
    },
    ...gifReadRecents().filter((g) => String(g?.url || '').trim() !== String(item.url || '').trim()),
  ].slice(0, GIF_RECENTS_LIMIT);
  gifWriteRecents(next);
}

function gifSetMode(mode) {
  GifUI.mode = mode || 'recents';
  const active = String(GifUI.mode);
  GifUI.recentBtn?.classList.toggle('is-active', active === 'recents');
  GifUI.trendingBtn?.classList.toggle('is-active', active === 'trending');
  GifUI.randomBtn?.classList.toggle('is-active', active === 'random');
}

function gifItemMeta(g) {
  const rawUrl = String(g?.url || '').trim();
  const rawPreview = String(g?.preview || rawUrl).trim();
  const url = (typeof ecNormalizeSafeUrl === 'function')
    ? ecNormalizeSafeUrl(rawUrl, { allowRelative: false, allowExternal: true })
    : (/^https?:\/\//i.test(rawUrl) ? rawUrl : '');
  const preview = (typeof ecNormalizeSafeUrl === 'function')
    ? (ecNormalizeSafeUrl(rawPreview, { allowRelative: false, allowExternal: true }) || url)
    : (/^https?:\/\//i.test(rawPreview) ? rawPreview : url);
  const title = String(g?.title || 'GIF').trim();
  const id = String(g?.id || '').trim();
  return { id, title, url, preview };
}

function gifRenderItems(items, statusText = '') {
  if (!GifUI.status || !GifUI.grid) return;
  const arr = Array.isArray(items) ? items.map(gifItemMeta).filter((g) => g.url) : [];
  GifUI.lastResults = arr;
  if (typeof ecClearNode === 'function') ecClearNode(GifUI.grid);
  else GifUI.grid.replaceChildren();

  if (!arr.length) {
    GifUI.status.textContent = statusText || 'No GIFs to show yet.';
    return;
  }

  GifUI.status.textContent = statusText || `${arr.length} result(s)`;

  arr.forEach((g) => {
    const url = g.url;
    const pv = g.preview || url;

    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'ym-gifItem';
    btn.title = g.title.slice(0, 120) || 'GIF';

    const img = document.createElement('img');
    img.className = 'ym-gifItemImg';
    img.loading = 'lazy';
    img.decoding = 'async';
    img.referrerPolicy = 'no-referrer';
    img.src = pv || url;
    img.alt = g.title || 'GIF';
    img.onerror = () => {
      const fb = _gifFallbackUrl(url) || _gifFallbackUrl(pv);
      if (fb && img.src !== fb) img.src = _gifCacheBust(fb);
    };

    const label = document.createElement('div');
    label.className = 'ym-gifItemLabel';
    label.textContent = g.title || 'GIF';

    btn.appendChild(img);
    btn.appendChild(label);
    btn.onclick = () => {
      try {
        gifPushRecent(g);
        if (GifUI.onPick) GifUI.onPick(url);
      } finally {
        closeGifPicker();
      }
    };

    GifUI.grid.appendChild(btn);
  });

  applyGifPickerPrefs();
}

function gifShowRecents() {
  gifSetMode('recents');
  const items = gifReadRecents();
  if (!items.length) {
    if (GifUI.grid) ecClearNode(GifUI.grid);
    GifUI.status && (GifUI.status.textContent = 'No recent GIFs yet. Search or open Top GIFs.');
    return;
  }
  gifRenderItems(items, `Recent GIFs (${items.length})`);
}

function ensureGifPicker() {
  if (GifUI.modal) return GifUI.modal;

  const overlay = ecCreateEl('div', { id: 'ecGifPicker', className: 'ym-gifPicker hidden' });
  const card = ecCreateEl('div', { className: 'ym-gifCard', role: 'dialog', ariaModal: 'true', ariaLabel: 'GIF picker' });
  card.appendChild(ecCreateEl('div', { className: 'ym-gifHead' }, [
    ecCreateEl('div', { className: 'ym-gifTitle', text: 'GIFs' }),
    ecCreateEl('button', { type: 'button', className: 'winBtn danger ym-gifClose', title: 'Close', text: '×' })
  ]));
  card.appendChild(ecCreateEl('div', { className: 'ym-gifSearchRow' }, [
    ecCreateEl('input', { className: 'ym-gifSearch', type: 'text', placeholder: 'Search GIPHY…', autocomplete: 'off' }),
    ecCreateEl('button', { type: 'button', className: 'ym-send ym-gifSearchBtn', text: 'Search' })
  ]));
  card.appendChild(ecCreateEl('div', { className: 'ym-gifQuickRow' }, [
    ecCreateEl('button', { type: 'button', className: 'ym-gifQuickBtn ym-gifRecentBtn', text: 'Recents' }),
    ecCreateEl('button', { type: 'button', className: 'ym-gifQuickBtn ym-gifTrendingBtn', text: 'Top GIFs' }),
    ecCreateEl('button', { type: 'button', className: 'ym-gifQuickBtn ym-gifRandomBtn', text: 'Random' })
  ]));
  card.appendChild(ecCreateEl('div', { className: 'ym-gifStatus' }));
  card.appendChild(ecCreateEl('div', { className: 'ym-gifGrid', ariaLabel: 'GIF results' }));
  overlay.appendChild(card);

  document.body.appendChild(overlay);

  GifUI.modal = overlay;
  GifUI.card = overlay.querySelector('.ym-gifCard');
  GifUI.closeBtn = overlay.querySelector('.ym-gifClose');
  GifUI.search = overlay.querySelector('.ym-gifSearch');
  try { wireTransientSearchInput(GifUI.search, { clearOnLoad: false, clearOnPageShow: false, clearOnRefocusAfterBlur: false }); } catch {}
  GifUI.searchBtn = overlay.querySelector('.ym-gifSearchBtn');
  GifUI.recentBtn = overlay.querySelector('.ym-gifRecentBtn');
  GifUI.trendingBtn = overlay.querySelector('.ym-gifTrendingBtn');
  GifUI.randomBtn = overlay.querySelector('.ym-gifRandomBtn');
  GifUI.status = overlay.querySelector('.ym-gifStatus');
  GifUI.grid = overlay.querySelector('.ym-gifGrid');
  applyGifPickerPrefs();

  const close = () => closeGifPicker();

  GifUI.closeBtn?.addEventListener('click', (e) => { e.preventDefault(); close(); });
  overlay.addEventListener('mousedown', (e) => {
    const tgt = e.target;
    if (!tgt) return;
    if (tgt === overlay) close();
  });

  const doSearch = () => {
    const q = GifUI.search?.value?.trim() || '';
    gifSearch(q);
  };

  GifUI.searchBtn?.addEventListener('click', (e) => { e.preventDefault(); doSearch(); });
  GifUI.search?.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') doSearch();
    if (e.key === 'Escape') close();
  });

  GifUI.recentBtn?.addEventListener('click', (e) => {
    e.preventDefault();
    gifShowRecents();
  });
  GifUI.trendingBtn?.addEventListener('click', (e) => {
    e.preventDefault();
    gifTrending();
  });
  GifUI.randomBtn?.addEventListener('click', (e) => {
    e.preventDefault();
    gifRandom();
  });

  if (!document.body.dataset.ecGifEscapeBound) {
    document.body.dataset.ecGifEscapeBound = '1';
    document.addEventListener('keydown', (e) => {
      if (GifUI.visible && e.key === 'Escape') closeGifPicker();
    });
  }

  return overlay;
}

function openGifPicker(onPick, { prefill = '' } = {}) {
  clearSearchesForModalTransition();
  const modal = ensureGifPicker();
  GifUI.onPick = (typeof onPick === 'function') ? onPick : null;

  if (GifUI.search) {
    const remembered = String(Settings.get('gifLastSearch', '') || '');
    const first = String(prefill || '').trim();
    GifUI.search.value = first || (UIState?.prefs?.gifOpenMode === 'last_search' ? remembered : '');
    try { GifUI.search.dispatchEvent(new Event('input', { bubbles: true })); } catch {}
    try { GifUI.search.focus(); GifUI.search.select(); } catch {}
  }

  modal.classList.remove('hidden');
  GifUI.visible = true;
  applyGifPickerPrefs();
  requestAnimationFrame(() => applyGifPickerPrefs());

  const q = (GifUI.search?.value || '').trim();
  if (q) {
    gifSearch(q);
    return;
  }
  const mode = String(UIState?.prefs?.gifOpenMode || 'recents');
  if (mode === 'trending') {
    gifTrending();
  } else if (mode === 'last_search') {
    if (gifReadRecents().length) gifShowRecents();
    else gifTrending();
  } else if (gifReadRecents().length) {
    gifShowRecents();
  } else {
    gifTrending();
  }
}

function closeGifPicker() {
  if (!GifUI.modal) return;
  GifUI.modal.classList.add('hidden');
  GifUI.visible = false;
  GifUI.onPick = null;
  clearSearchesForModalTransition({ includeGifSearch: true });
}

async function gifSearch(query) {
  const q = (query || '').trim();
  if (!GifUI.status || !GifUI.grid) return;

  if (!q) {
    gifShowRecents();
    return;
  }

  gifSetMode('search');
  try { Settings.set('gifLastSearch', q); } catch {}
  GifUI.status.textContent = 'Searching…';
  if (typeof ecClearNode === 'function') ecClearNode(GifUI.grid);
  else GifUI.grid.replaceChildren();

  try {
    const resp = await fetchWithAuth(`/api/gifs/search?q=${encodeURIComponent(q)}&limit=${encodeURIComponent(getGifResultsLimit())}`, { method: 'GET' });
    const data = (typeof ecReadApiJson === 'function') ? await ecReadApiJson(resp, null) : await resp.json().catch(() => null);
    if (!resp.ok || !data?.success) {
      let msg = (typeof ecApiErrorMessage === 'function') ? ecApiErrorMessage(resp, data, 'GIF request failed') : (data?.error || `HTTP ${resp?.status || '?'}`);
      if (String(msg).includes('GIPHY_API_KEY') || String(msg).toLowerCase().includes('giphy')) {
        msg = `${msg} — Admin: open Admin panel → Settings → GIFs and set the key.`;
      }
      GifUI.status.textContent = `❌ ${msg}`;
      return;
    }

    const arr = Array.isArray(data?.data) ? data.data : [];
    if (!arr.length) {
      GifUI.status.textContent = 'No results.';
      return;
    }

    gifRenderItems(arr, `${arr.length} result(s) for “${q}”`);
  } catch (e) {
    console.error(e);
    GifUI.status.textContent = '❌ GIF search failed.';
  }
}

async function gifTrending() {
  if (!GifUI.status || !GifUI.grid) return;
  gifSetMode('trending');
  GifUI.status.textContent = 'Loading top GIFs…';
  if (typeof ecClearNode === 'function') ecClearNode(GifUI.grid);
  else GifUI.grid.replaceChildren();

  try {
    const resp = await fetchWithAuth(`/api/gifs/trending?limit=${encodeURIComponent(getGifResultsLimit())}`, { method: 'GET' });
    const data = (typeof ecReadApiJson === 'function') ? await ecReadApiJson(resp, null) : await resp.json().catch(() => null);
    if (!resp.ok || !data?.success) {
      let msg = (typeof ecApiErrorMessage === 'function') ? ecApiErrorMessage(resp, data, 'GIF request failed') : (data?.error || `HTTP ${resp?.status || '?'}`);
      if (String(msg).includes('GIPHY_API_KEY') || String(msg).toLowerCase().includes('giphy')) {
        msg = `${msg} — Admin: open Admin panel → Settings → GIFs and set the key.`;
      }
      GifUI.status.textContent = `❌ ${msg}`;
      return;
    }

    const arr = Array.isArray(data?.data) ? data.data : [];
    if (!arr.length) {
      GifUI.status.textContent = 'No top GIFs right now.';
      return;
    }

    gifRenderItems(arr, `Top GIFs (${arr.length})`);
  } catch (e) {
    console.error(e);
    GifUI.status.textContent = '❌ Could not load top GIFs.';
  }
}

async function gifRandom() {
  if (!GifUI.status || !GifUI.grid) return;
  gifSetMode('random');
  GifUI.status.textContent = 'Loading a random GIF…';
  if (typeof ecClearNode === 'function') ecClearNode(GifUI.grid);
  else GifUI.grid.replaceChildren();

  try {
    let arr = Array.isArray(GifUI.lastResults) ? GifUI.lastResults.slice() : [];
    if (!arr.length) {
      const resp = await fetchWithAuth(`/api/gifs/trending?limit=${encodeURIComponent(getGifResultsLimit())}`, { method: 'GET' });
      const data = (typeof ecReadApiJson === 'function') ? await ecReadApiJson(resp, null) : await resp.json().catch(() => null);
      if (!resp.ok || !data?.success) {
        let msg = data?.error || `HTTP ${resp.status}`;
        if (String(msg).includes('GIPHY_API_KEY') || String(msg).toLowerCase().includes('giphy')) {
          msg = `${msg} — Admin: open Admin panel → Settings → GIFs and set the key.`;
        }
        GifUI.status.textContent = `❌ ${msg}`;
        return;
      }
      arr = Array.isArray(data?.data) ? data.data : [];
    }

    if (!arr.length) {
      GifUI.status.textContent = 'No GIFs available for random pick.';
      return;
    }

    const chosen = arr[Math.floor(Math.random() * arr.length)];
    gifRenderItems([chosen], 'Random GIF');
  } catch (e) {
    console.error(e);
    GifUI.status.textContent = '❌ Could not load a random GIF.';
  }
}

function getCookie(name) {
  const value = `; ${document.cookie}`;
  const parts = value.split(`; ${name}=`);
  if (parts.length === 2) return parts.pop().split(";").shift();
  return null;
}
