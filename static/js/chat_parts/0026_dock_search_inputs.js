function clearRoomBrowserSearchesForPanelSwitch() {
  // Keep the category search intact so users can continue navigating categories,
  // but clear the content-panel searches because the visible room/custom-room
  // results are changing underneath them.
  clearSearchInputs(['rbRoomSearch', 'rbCustomSearch']);
}

function resetRoomBrowserSearchBarsAfterClose() {
  // The room browser can be opened as an in-room overlay. Search text should be
  // temporary there: closing the overlay should not leave stale filters that hide
  // rooms the next time a user opens Rooms.
  clearSearchInputs(['rbCatSearch', 'rbRoomSearch', 'rbCustomSearch']);
  try { ROOM_BROWSER.catQuery = ''; } catch {}
  try { ROOM_BROWSER.roomQuery = ''; } catch {}
  try { ROOM_BROWSER.customQuery = ''; } catch {}
  try { rbRenderCategoryTree(); } catch {}
  try { rbRenderRoomLists(); } catch {}
  try { rbUpdateCountsInDom(); } catch {}
}

function clearSearchesForModalTransition(opts = {}) {
  const includeGifSearch = !!opts.includeGifSearch;
  clearSearchInputs(['dockSearch', 'rbRoomSearch', 'rbCustomSearch']);
  if (includeGifSearch) {
    try { clearSearchLikeInput(GifUI?.search); } catch {}
  }
}

function isSearchLikeInput(el) {
  if (!el || String(el.tagName || '').toUpperCase() !== 'INPUT') return false;
  const id = String(el.id || '');
  if (['dockSearch', 'rbCatSearch', 'rbRoomSearch', 'rbCustomSearch'].includes(id)) return true;
  if (el.classList?.contains('dockSearch') || el.classList?.contains('rbSearch') || el.classList?.contains('ym-gifSearch')) return true;
  const ph = String(el.getAttribute('placeholder') || '');
  return /search/i.test(ph);
}

function ensureSearchClearButton(idOrEl) {
  const el = (typeof idOrEl === 'string') ? $(idOrEl) : idOrEl;
  if (!isSearchLikeInput(el)) return el;

  try { el.dataset.searchClearable = '1'; } catch {}

  let wrap = el.parentElement;
  if (!wrap || !wrap.classList?.contains('searchInputWrap')) {
    wrap = document.createElement('div');
    wrap.className = 'searchInputWrap';
    try {
      el.parentNode?.insertBefore(wrap, el);
      wrap.appendChild(el);
    } catch {
      return el;
    }
  }

  let btn = wrap.querySelector(':scope > .searchClearBtn');
  if (!btn) {
    btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'searchClearBtn';
    btn.setAttribute('aria-label', 'Clear search');
    btn.setAttribute('title', 'Clear search');
    btn.textContent = '×';
    wrap.appendChild(btn);
  }

  if (el.dataset?.searchClearButtonWired === '1') {
    const hasValue = String(el.value || '').length > 0;
    wrap.classList.toggle('hasValue', hasValue);
    return el;
  }

  const sync = () => {
    const hasValue = String(el.value || '').length > 0;
    wrap.classList.toggle('hasValue', hasValue);
    btn.disabled = !hasValue;
    btn.setAttribute('aria-hidden', hasValue ? 'false' : 'true');
    return hasValue;
  };

  const clearAndSync = () => {
    clearSearchLikeInput(el);
    try { el.dispatchEvent(new Event('input', { bubbles: true })); } catch {}
    try { el.dispatchEvent(new Event('change', { bubbles: true })); } catch {}
    sync();
  };

  try { el.dataset.searchClearButtonWired = '1'; } catch {}

  btn.addEventListener('click', (e) => {
    e.preventDefault();
    e.stopPropagation();
    clearAndSync();
    try { el.focus(); } catch {}
  });

  el.addEventListener('input', sync);
  el.addEventListener('change', sync);
  el.addEventListener('blur', sync);
  el.addEventListener('focus', sync);
  el.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && String(el.value || '').length > 0) {
      e.preventDefault();
      e.stopPropagation();
      clearAndSync();
    }
  });

  sync();
  return el;
}

function wireTransientSearchInput(idOrEl, opts = {}) {
  const el = (typeof idOrEl === 'string') ? $(idOrEl) : idOrEl;
  if (!el) return null;
  ensureSearchClearButton(el);
  if (el.dataset?.transientSearchWired === '1') return el;

  const clearOnLoad = !!opts.clearOnLoad;
  const clearOnPageShow = !!opts.clearOnPageShow;
  const clearOnRefocusAfterBlur = opts.clearOnRefocusAfterBlur !== false;

  let userTouched = false;
  const markTouched = () => { userTouched = true; };
  const unlockReadonly = () => {
    try {
      if (el.readOnly) el.readOnly = false;
    } catch {}
  };
  const clearIfUntouched = () => {
    if (!userTouched) clearSearchLikeInput(el);
  };

  try { el.dataset.transientSearchWired = '1'; } catch {}
  try { el.setAttribute('autocomplete', 'new-password'); } catch {}
  try { el.setAttribute('autocapitalize', 'off'); } catch {}
  try { el.setAttribute('autocorrect', 'off'); } catch {}
  try { el.setAttribute('spellcheck', 'false'); } catch {}
  try { el.setAttribute('data-lpignore', 'true'); } catch {}
  try { el.setAttribute('data-1p-ignore', 'true'); } catch {}
  try { el.setAttribute('aria-autocomplete', 'none'); } catch {}
  try {
    if (!el.dataset?.autofillSafeNameApplied) {
      const base = String(el.id || el.name || 'search').replace(/[^a-z0-9_-]/gi, '').toLowerCase() || 'search';
      el.name = `ym_${base}_${Math.random().toString(36).slice(2, 8)}`;
      el.dataset.autofillSafeNameApplied = '1';
    }
  } catch {}
  try {
    el.readOnly = true;
    requestAnimationFrame(() => setTimeout(unlockReadonly, 0));
  } catch {}
  try { el.spellcheck = false; } catch {}

  if (clearOnLoad) {
    clearSearchLikeInput(el);
    [0, 60, 250, 800].forEach((ms) => setTimeout(clearIfUntouched, ms));
  }

  let clearOnNextFocus = false;

  const maybeClear = () => {
    unlockReadonly();
    if (!clearOnRefocusAfterBlur || !clearOnNextFocus) return;
    if (String(el.value || '').length > 0) clearSearchLikeInput(el);
    clearOnNextFocus = false;
  };

  el.addEventListener('input', markTouched);
  el.addEventListener('keydown', markTouched);
  el.addEventListener('paste', markTouched);
  el.addEventListener('change', markTouched);
  el.addEventListener('pointerdown', unlockReadonly, { capture: true });
  el.addEventListener('mousedown', unlockReadonly, { capture: true });
  el.addEventListener('touchstart', unlockReadonly, { capture: true, passive: true });

  el.addEventListener('blur', () => {
    if (clearOnRefocusAfterBlur) clearOnNextFocus = true;
  });

  el.addEventListener('pointerdown', maybeClear);
  el.addEventListener('focus', maybeClear);

  if (clearOnPageShow) {
    window.addEventListener('pageshow', () => {
      userTouched = false;
      clearSearchLikeInput(el);
      [0, 60, 250, 800].forEach((ms) => setTimeout(clearIfUntouched, ms));
      clearOnNextFocus = false;
      try {
        el.readOnly = true;
        requestAnimationFrame(() => setTimeout(unlockReadonly, 0));
      } catch {}
    });
  }

  return el;
}

function wireTransientSearchInputWhenAvailable(id, opts = {}) {
  const wired = wireTransientSearchInput(id, opts);
  if (wired) return wired;

  const root = document.body || document.documentElement;
  if (!root || typeof MutationObserver === 'undefined') return null;

  const obs = new MutationObserver(() => {
    const found = wireTransientSearchInput(id, opts);
    if (found) obs.disconnect();
  });
  obs.observe(root, { childList: true, subtree: true });
  return null;
}
