function rbBumpUnread(roomName) {
  const key = String(roomName || '').trim();
  if (!key) return;
  const cur = Number(ROOM_BROWSER.unreadCounts.get(key) || 0) || 0;
  ROOM_BROWSER.unreadCounts.set(key, cur + 1);
}

function rbToastApiLoadError(resp, data, fallback) {
  const msg = (typeof ecApiErrorMessage === 'function') ? ecApiErrorMessage(resp, data, fallback) : fallback;
  try { toast(`⚠️ ${msg}`, 'warn', 3200); } catch {}
}

async function rbLoadCatalog() {
  const resp = await fetchWithAuth('/api/room_catalog', { method: 'GET' }, { retryOn401: true });
  const j = (typeof ecReadApiJson === 'function') ? await ecReadApiJson(resp, {}) : await resp.json().catch(() => ({}));
  if (!resp || !resp.ok) {
    rbToastApiLoadError(resp, j, 'Could not load room catalog');
    return { version: 2, categories: [] };
  }
  if (j && Array.isArray(j.categories)) return j;
  rbToastApiLoadError(resp, j, 'Room catalog response was invalid');
  return { version: 2, categories: [] };
}

async function rbLoadCounts() {
  const resp = await fetchWithAuth('/api/rooms', { method: 'GET' }, { retryOn401: true });
  const j = (typeof ecReadApiJson === 'function') ? await ecReadApiJson(resp, null) : await resp.json().catch(() => null);
  if (!resp || !resp.ok) {
    rbToastApiLoadError(resp, j, 'Could not load room counts');
    return;
  }
  const rows = Array.isArray(j) ? j : (Array.isArray(j?.rooms) ? j.rooms : []);
  if (!Array.isArray(rows)) {
    rbToastApiLoadError(resp, j, 'Room count response was invalid');
    return;
  }
  const m = new Map();
  const meta = new Map();
  (rows || []).forEach((r) => {
    const name = String(r?.name || r?.room || '').trim();
    const count = (r?.count ?? r?.cnt ?? r?.member_count ?? r?.members ?? 0);
    if (!name) return;
    const n = Number(count || 0) || 0;
    m.set(String(name), n);
    const capacity = Number(r?.capacity || r?.max_users || 0) || 0;
    meta.set(String(name), {
      member_count: n,
      locked: !!r?.locked,
      readonly: !!r?.readonly,
      slowmode_seconds: Number(r?.slowmode_seconds || r?.slowmode || 0) || 0,
      capacity,
      full: !!r?.full || (capacity > 0 && n >= capacity),
      is_custom: !!r?.is_custom,
      is_private: !!r?.is_private,
      room_kind: String(r?.room_kind || '').trim(),
    });
  });
  ROOM_BROWSER.counts = m;
  ROOM_BROWSER.roomStatusMeta = meta;
}

async function rbLoadCustomRooms() {
  const c = ROOM_BROWSER.selectedCategory;
  const s = ROOM_BROWSER.selectedSubcategory;
  if (!c || !s) { ROOM_BROWSER.customRooms = []; return; }
  const qs = new URLSearchParams({ category: c, subcategory: s });
  const resp = await fetchWithAuth(`/api/custom_rooms?${qs.toString()}`, { method: 'GET' }, { retryOn401: true });
  const j = (typeof ecReadApiJson === 'function') ? await ecReadApiJson(resp, {}) : await resp.json().catch(() => ({}));
  if (!resp || !resp.ok) {
    rbToastApiLoadError(resp, j, 'Could not load custom rooms');
    return;
  }
  const responseCategory = String(j?.category || c || '').trim();
  const responseSubcategory = String(j?.subcategory || s || '').trim();
  const loadedAt = Date.now();
  ROOM_BROWSER.customRooms = (Array.isArray(j.rooms) ? j.rooms : []).map((room) => ({
    ...(room || {}),
    category: String(room?.category || responseCategory || c || '').trim(),
    subcategory: String(room?.subcategory || responseSubcategory || s || '').trim(),
    idle_ttl_minutes: Number(room?.idle_ttl_minutes || 0) || 0,
    idle_ttl_seconds: Number(room?.idle_ttl_seconds || 0) || 0,
    last_active_at: room?.last_active_at ? String(room.last_active_at) : null,
    last_active_age_seconds: Number(room?.last_active_age_seconds || 0) || 0,
    expires_in_seconds: (room?.expires_in_seconds === null || room?.expires_in_seconds === undefined) ? null : (Number(room.expires_in_seconds) || 0),
    expires_at: room?.expires_at ? String(room.expires_at) : null,
    timer_paused: !!room?.timer_paused,
    deletion_state: room?.deletion_state ? String(room.deletion_state) : '',
    cleanup_occupancy_count: Number(room?.cleanup_occupancy_count || 0) || 0,
    _customExpiryLoadedAt: loadedAt,
  })).filter((room) => {
    return String(room?.category || '') === String(c) && String(room?.subcategory || '') === String(s);
  });
}



function rbCatalogCategories() {
  const cats = (ROOM_BROWSER.catalog && Array.isArray(ROOM_BROWSER.catalog.categories))
    ? ROOM_BROWSER.catalog.categories
    : [];
  return cats.filter((cat) => cat && typeof cat === 'object' && String(cat.name || '').trim());
}

function rbCatalogSubcategories(category) {
  const subs = Array.isArray(category?.subcategories) ? category.subcategories : [];
  return subs.filter((sub) => sub && typeof sub === 'object' && String(sub.name || '').trim());
}

function rbCatalogRoomsForSubcategory(subcategory) {
  return Array.isArray(subcategory?.rooms) ? subcategory.rooms : [];
}

function rbCatalogEntrySearchText(entry) {
  if (typeof entry === 'string') return String(entry || '');
  if (!entry || typeof entry !== 'object') return '';
  const parts = [
    entry.name,
    entry.topic,
    entry.description,
    ...(Array.isArray(entry.tags) ? entry.tags : []),
    ...(Array.isArray(entry.features) ? entry.features : []),
  ];
  return parts.map((part) => String(part || '')).join(' ');
}

function rbSubcategoryOfficialRoomCount(subcategory) {
  return rbCatalogRoomsForSubcategory(subcategory).filter((room) => rbCatalogRoomName(room)).length;
}

function rbSubcategoryOnlineCount(subcategory) {
  let total = 0;
  rbCatalogRoomsForSubcategory(subcategory).forEach((room) => {
    const name = rbCatalogRoomName(room);
    if (!name) return;
    total += Number(ROOM_BROWSER.counts?.get(name) || 0) || 0;
    try {
      ROOM_BROWSER.counts.forEach((count, candidateName) => {
        if (rbNorm(rbAutosplitShardBaseName(candidateName)) === rbNorm(name)) {
          total += Number(count || 0) || 0;
        }
      });
    } catch {}
  });
  return total;
}

function rbCategoryOfficialRoomCount(category) {
  return rbCatalogSubcategories(category).reduce((sum, sub) => sum + rbSubcategoryOfficialRoomCount(sub), 0);
}

function rbCategoryOnlineCount(category) {
  return rbCatalogSubcategories(category).reduce((sum, sub) => sum + rbSubcategoryOnlineCount(sub), 0);
}

function rbSubcategoryMatchesCatalogQuery(categoryName, subcategory, query) {
  const q = rbNorm(query);
  if (!q) return true;
  const subName = String(subcategory?.name || '').trim();
  if (rbNorm(categoryName).includes(q) || rbNorm(subName).includes(q)) return true;
  return rbCatalogRoomsForSubcategory(subcategory).some((room) => rbNorm(rbCatalogEntrySearchText(room)).includes(q));
}

function rbCategoryMatchesCatalogQuery(category, query) {
  const q = rbNorm(query);
  if (!q) return true;
  const categoryName = String(category?.name || '').trim();
  if (rbNorm(categoryName).includes(q)) return true;
  return rbCatalogSubcategories(category).some((sub) => rbSubcategoryMatchesCatalogQuery(categoryName, sub, q));
}

function rbFirstCatalogPath(catalog = ROOM_BROWSER.catalog) {
  const cats = catalog && Array.isArray(catalog.categories) ? catalog.categories : [];
  for (const category of cats) {
    const categoryName = String(category?.name || '').trim();
    if (!categoryName) continue;
    for (const subcategory of (Array.isArray(category?.subcategories) ? category.subcategories : [])) {
      const subcategoryName = String(subcategory?.name || '').trim();
      if (!subcategoryName) continue;
      return { category: categoryName, subcategory: subcategoryName };
    }
  }
  return null;
}

function rbScopeLabel() {
  return ({
    all: 'All rooms',
    official: 'Official rooms',
    current: 'Current room',
    recent: 'Recent rooms',
    favorites: 'Favorite rooms',
    unread: 'Unread rooms',
    custom: 'Custom rooms',
  })[ROOM_BROWSER.roomScope] || 'All rooms';
}

function rbSetSelectionLabel() {
  const el = $('rbSelectionLabel');
  const customEl = $('rbCustomSelectionLabel');
  const base = (ROOM_BROWSER.selectedCategory && ROOM_BROWSER.selectedSubcategory)
    ? `${ROOM_BROWSER.selectedCategory} › ${ROOM_BROWSER.selectedSubcategory}`
    : 'Select a category/subcategory…';
  if (el) {
    if (['recent', 'favorites', 'current', 'unread'].includes(ROOM_BROWSER.roomScope)) {
      el.textContent = `${rbScopeLabel()} across ${SERVER_NAME}`;
    } else {
      el.textContent = `${base} • ${rbScopeLabel()}`;
    }
  }
  if (customEl) {
    customEl.textContent = (ROOM_BROWSER.selectedCategory && ROOM_BROWSER.selectedSubcategory)
      ? `${base} • Custom rooms`
      : 'Pick a category to show custom rooms…';
  }
}

function rbRoomsForSelection() {
  const cat = ROOM_BROWSER.selectedCategory;
  const sub = ROOM_BROWSER.selectedSubcategory;
  if (!ROOM_BROWSER.catalog || !cat || !sub) return [];
  const c = (ROOM_BROWSER.catalog.categories || []).find((x) => (x.name || '') === cat);
  if (!c) return [];
  const sObj = (c.subcategories || []).find((x) => (x.name || '') === sub);
  if (!sObj) return [];
  return Array.isArray(sObj.rooms) ? sObj.rooms : [];
}

function rbCatalogRoomName(entry) {
  if (typeof entry === 'string') return String(entry || '').trim();
  return String(entry?.name || '').trim();
}

function rbAutosplitShardBaseName(roomName) {
  const name = String(roomName || '').trim();
  const match = name.match(/^(.*?)\s*\(\s*([2-9]\d*)\s*\)\s*$/);
  if (!match) return '';
  return String(match[1] || '').trim();
}

function rbAutosplitShardNumber(roomName) {
  const name = String(roomName || '').trim();
  const match = name.match(/\(\s*([2-9]\d*)\s*\)\s*$/);
  return match ? (Number(match[1] || 0) || 0) : 0;
}

function rbAutosplitShardRowsForBase(baseRow, entry) {
  const baseName = String(baseRow?.name || '').trim();
  if (!baseName || !(ROOM_BROWSER.counts instanceof Map)) return [];
  const baseMeta = rbNormalizeOfficialRoomMeta((entry && typeof entry === 'object') ? entry : { name: baseName }) || baseRow?.meta || { name: baseName };
  const rows = [];
  const seen = new Set();
  ROOM_BROWSER.counts.forEach((_count, candidateName) => {
    const name = String(candidateName || '').trim();
    if (!name || seen.has(name)) return;
    if (rbNorm(rbAutosplitShardBaseName(name)) !== rbNorm(baseName)) return;
    seen.add(name);
    rows.push(rbBuildRow(name, {
      isCustom: false,
      meta: {
        ...(baseMeta || {}),
        name,
        autosplit_base: baseName,
        topic: `Overflow room for ${baseName}`,
        description: `Autosplit overflow room for ${baseName}. Users land here when the main room is full.`,
      },
      category: baseRow.category || ROOM_BROWSER.selectedCategory,
      subcategory: baseRow.subcategory || ROOM_BROWSER.selectedSubcategory,
    }));
  });
  return rows.filter(Boolean).sort((a, b) => (rbAutosplitShardNumber(a.name) - rbAutosplitShardNumber(b.name)) || a.name.localeCompare(b.name));
}

function rbOfficialRowsForSelection() {
  const qRoom = rbNorm(ROOM_BROWSER.roomQuery);
  const hideEmpty = !!ROOM_BROWSER.hideEmpty;
  const rows = [];
  (rbRoomsForSelection() || []).forEach((entry) => {
    const baseRow = rbBuildRow(rbCatalogRoomName(entry), {
      isCustom: false,
      meta: entry,
      category: ROOM_BROWSER.selectedCategory,
      subcategory: ROOM_BROWSER.selectedSubcategory,
    });
    if (!baseRow) return;
    rows.push(baseRow);
    rbAutosplitShardRowsForBase(baseRow, entry).forEach((shardRow) => rows.push(shardRow));
  });
  const filtered = rows.filter((row) => {
    if (!rbMatchesRoomSearch(row, qRoom)) return false;
    if (!rbMatchesRoomStatusFilter(row)) return false;
    if (hideEmpty && row.cnt <= 0) return false;
    return true;
  });
  if (ROOM_BROWSER.roomsSort === 'az') filtered.sort((a, b) => a.name.localeCompare(b.name));
  else filtered.sort((a, b) => (b.cnt - a.cnt) || a.name.localeCompare(b.name));
  return filtered;
}

function rbMatchesCustomFilter(row) {
  const filter = ROOM_BROWSER.customFilter || 'all';
  if (!row?.isCustom) return true;
  if (filter === 'public' && row.meta?.is_private) return false;
  if (filter === 'private' && !row.meta?.is_private) return false;
  if (filter === 'mine' && !rbIsCurrentUserRoomCreator(row.meta?.created_by)) return false;
  return true;
}

function rbRoomSearchText(row) {
  if (!row) return '';
  const meta = row.meta || {};
  const parts = [
    row.name,
    meta.autosplit_base,
    meta.topic,
    meta.description,
    row.category,
    row.subcategory,
    row.isCustom ? 'custom user created' : 'official built in',
    row.isCustom && meta.is_private ? 'private invite locked' : '',
    row.locked ? 'locked closed' : 'open unlocked',
    row.readonly ? 'readonly read only' : '',
    Number(row.slowmode_seconds || 0) > 0 ? 'slowmode slow' : '',
    row.full ? 'full capacity' : '',
    ...(Array.isArray(meta.tags) ? meta.tags : []),
    ...(Array.isArray(meta.features) ? meta.features : []),
  ];
  return parts.map((part) => String(part || '')).join(' ');
}

function rbMatchesRoomSearch(row, query) {
  const q = rbNorm(query);
  if (!q) return true;
  return rbNorm(rbRoomSearchText(row)).includes(q);
}

function rbRoomStatusLabel(row) {
  if (!row) return 'unknown';
  if (row.full) return 'full';
  if (row.locked) return 'locked';
  if (row.readonly) return 'readonly';
  if (Number(row.slowmode_seconds || 0) > 0) return 'slowmode';
  if (Number(row.cnt || 0) > 0) return 'active';
  return 'empty';
}

function rbMatchesRoomStatusFilter(row) {
  const filter = String(ROOM_BROWSER.roomStatusFilter || 'all');
  if (filter === 'all') return true;
  if (filter === 'open') return !!row && !row.locked && !row.readonly && !row.full;
  if (filter === 'active') return !!row && Number(row.cnt || 0) > 0;
  if (filter === 'empty') return !!row && Number(row.cnt || 0) <= 0;
  if (filter === 'locked') return !!row && !!row.locked;
  if (filter === 'readonly') return !!row && !!row.readonly;
  if (filter === 'slowmode') return !!row && Number(row.slowmode_seconds || 0) > 0;
  if (filter === 'full') return !!row && !!row.full;
  return true;
}

function rbCustomRowsForSelection() {
  const qCustom = rbNorm(ROOM_BROWSER.customQuery);
  const rows = (ROOM_BROWSER.customRooms || []).map((meta) => rbBuildRow(meta?.name, {
    isCustom: true,
    meta,
    category: meta?.category || ROOM_BROWSER.selectedCategory,
    subcategory: meta?.subcategory || ROOM_BROWSER.selectedSubcategory,
  })).filter(Boolean).filter((row) => {
    if (!rbMatchesCustomFilter(row)) return false;
    if (!rbMatchesRoomStatusFilter(row)) return false;
    if (qCustom && !rbMatchesRoomSearch(row, qCustom)) return false;
    if (ROOM_BROWSER.hideEmpty && row.cnt <= 0) return false;
    return true;
  });
  if (ROOM_BROWSER.customSort === 'az') rows.sort((a, b) => a.name.localeCompare(b.name));
  else rows.sort((a, b) => (b.cnt - a.cnt) || a.name.localeCompare(b.name));
  return rows;
}

function rbResolveStoredRows(entries) {
  const out = [];
  (entries || []).forEach((entry) => {
    const item = rbNormalizeStoredRoom(entry);
    if (!item) return;
    const row = rbBuildRow(item.name, {
      isCustom: !!item.isCustom,
      meta: item.isCustom ? item : null,
      category: item.category,
      subcategory: item.subcategory,
      recentAt: item.lastAt,
    });
    if (row) out.push(row);
  });
  return out;
}

function rbApplyQueriesToMixedRows(rows) {
  const roomQuery = rbNorm(ROOM_BROWSER.roomQuery);
  return (rows || []).filter((row) => {
    if (ROOM_BROWSER.hideEmpty && row.cnt <= 0) return false;
    if (!rbMatchesRoomStatusFilter(row)) return false;
    if (row.isCustom) {
      const customQuery = rbNorm(ROOM_BROWSER.customQuery);
      if (!rbMatchesCustomFilter(row)) return false;
      if (customQuery && !rbMatchesRoomSearch(row, customQuery)) return false;
    } else if (roomQuery && !rbMatchesRoomSearch(row, roomQuery)) {
      return false;
    }
    return true;
  });
}
