// ─────────────────────────────────────────────────────────────────────────────
// Room browser (left selection screen)
// ─────────────────────────────────────────────────────────────────────────────

const ROOM_BROWSER = {
  catalog: null,
  selectedCategory: null,
  selectedSubcategory: null,
  counts: new Map(),
  customRooms: [],
  inviteRoom: null,
  catQuery: "",
  roomQuery: "",
  customQuery: "",
  roomsSort: "active",
  customSort: "active",
  customFilter: "all",
  roomStatusFilter: "all", // all | open | active | empty | locked | readonly | slowmode | full
  roomScope: "all", // all | official | custom | current | recent | favorites | unread
  hideEmpty: false,
  roomStatusMeta: new Map(),
  collapsedCats: new Set(),
  started: false,
  selectedRoom: null,
  selectedRoomIsCustom: false,
  selectedRoomMeta: null,
  selectedRoomCategory: null,
  selectedRoomSubcategory: null,
  recentRooms: [],
  favoriteRooms: [],
  unreadCounts: new Map(),
  lastRenderedRows: [],
  roomOccupants: new Map(),
  roomOccupantsMeta: new Map(),
  popoutOpen: false,
  popoutHomeParentId: 'sitePlaceholderSlot',
  _pollTimer: null,
};

function rbNorm(s) {
  return String(s || "").toLowerCase();
}

function rbRoomNameKey(name) {
  // Room names are server-canonical, but browser-side metadata can arrive from
  // API rows, Socket.IO counts, recent/favorite storage, and user clicks. Use a
  // normalized lookup key so category/search/favorite/current state does not
  // split when casing or surrounding whitespace drifts.
  return rbNorm(String(name || '').trim());
}

function rbMapGetRoomValue(mapLike, roomName, fallback = undefined) {
  if (!(mapLike instanceof Map)) return fallback;
  const raw = String(roomName || '').trim();
  if (mapLike.has(raw)) return mapLike.get(raw);
  const key = rbRoomNameKey(raw);
  if (!key) return fallback;
  for (const [candidate, value] of mapLike.entries()) {
    if (rbRoomNameKey(candidate) === key) return value;
  }
  return fallback;
}

function rbSameRoomName(a, b) {
  return rbRoomNameKey(a) === rbRoomNameKey(b);
}

function rbSameCatalogPath(aCategory, aSubcategory, bCategory, bSubcategory) {
  return rbRoomNameKey(aCategory) === rbRoomNameKey(bCategory)
    && rbRoomNameKey(aSubcategory) === rbRoomNameKey(bSubcategory);
}

function rbUnreadKey(roomName) {
  return rbRoomNameKey(roomName);
}

function rbGetUnreadCount(roomName) {
  return Number(rbMapGetRoomValue(ROOM_BROWSER.unreadCounts, rbUnreadKey(roomName), 0) || 0) || 0;
}

function rbSetUnreadCount(roomName, count) {
  const key = rbUnreadKey(roomName);
  if (!key) return;
  const n = Math.max(0, Number(count || 0) || 0);
  for (const candidate of Array.from(ROOM_BROWSER.unreadCounts.keys())) {
    if (rbRoomNameKey(candidate) === key) ROOM_BROWSER.unreadCounts.delete(candidate);
  }
  if (n > 0) ROOM_BROWSER.unreadCounts.set(key, n);
}

function rbIsCurrentUserRoomCreator(createdBy) {
  // Creator-only private-room affordances must survive harmless username casing drift.
  return rbNorm(String(createdBy || "").trim()) === rbNorm(String(currentUser || "").trim());
}

function rbHasUI() {
  return !!($('rbCategoryTree') && $('rbRoomsList') && $('rbCustomRoomsList'));
}

function rbRoomKey(name, isCustom = false) {
  return `${isCustom ? 'custom' : 'official'}:${rbRoomNameKey(name)}`;
}

function rbReadStoredRoomList(key, fallback = []) {
  try {
    const raw = Settings.get(key, fallback);
    return Array.isArray(raw) ? raw : fallback;
  } catch {
    return fallback;
  }
}

function rbWriteStoredRoomList(key, rows) {
  try { Settings.set(key, Array.isArray(rows) ? rows : []); } catch {}
}

function rbLoadPersistedRoomBrowserState() {
  ROOM_BROWSER.recentRooms = rbReadStoredRoomList('roomBrowserRecent', []).map(rbNormalizeStoredRoom).filter(Boolean).slice(0, 12);
  ROOM_BROWSER.favoriteRooms = rbReadStoredRoomList('roomBrowserFavorites', []).map(rbNormalizeStoredRoom).filter(Boolean).slice(0, 24);
}

function rbNormalizeStoredRoom(entry) {
  if (!entry) return null;
  const name = String(entry.name || entry.room || '').trim();
  if (!name) return null;
  return {
    name,
    isCustom: !!entry.isCustom,
    category: entry.category ? String(entry.category) : null,
    subcategory: entry.subcategory ? String(entry.subcategory) : null,
    created_by: entry.created_by ? String(entry.created_by) : null,
    my_room_role: entry.my_room_role ? String(entry.my_room_role) : '',
    can_room_moderate: !!entry.can_room_moderate,
    is_private: !!entry.is_private,
    is_18_plus: !!entry.is_18_plus,
    is_nsfw: !!entry.is_nsfw,
    topic: entry.topic ? String(entry.topic) : '',
    description: entry.description ? String(entry.description) : '',
    tags: Array.isArray(entry.tags) ? entry.tags.map((t) => String(t || '').trim()).filter(Boolean) : [],
    features: Array.isArray(entry.features) ? entry.features.map((f) => String(f || '').trim()).filter(Boolean) : [],
    stations: Array.isArray(entry.stations) ? entry.stations.slice(0, 16) : [],
    member_count: Number(entry.member_count || 0) || 0,
    locked: !!entry.locked,
    readonly: !!entry.readonly,
    slowmode_seconds: Number(entry.slowmode_seconds || 0) || 0,
    capacity: Number(entry.capacity || entry.max_users || 0) || 0,
    full: !!entry.full,
    idle_ttl_minutes: Number(entry.idle_ttl_minutes || 0) || 0,
    idle_ttl_seconds: Number(entry.idle_ttl_seconds || 0) || 0,
    last_active_at: entry.last_active_at ? String(entry.last_active_at) : null,
    last_active_age_seconds: Number(entry.last_active_age_seconds || 0) || 0,
    expires_in_seconds: (entry.expires_in_seconds === null || entry.expires_in_seconds === undefined) ? null : (Number(entry.expires_in_seconds) || 0),
    expires_at: entry.expires_at ? String(entry.expires_at) : null,
    timer_paused: !!entry.timer_paused,
    deletion_state: entry.deletion_state ? String(entry.deletion_state) : '',
    cleanup_occupancy_count: Number(entry.cleanup_occupancy_count || 0) || 0,
    _customExpiryLoadedAt: Number(entry._customExpiryLoadedAt || Date.now()) || Date.now(),
    lastAt: Number(entry.lastAt || entry.ts || Date.now()) || Date.now(),
  };
}

function rbNormalizeOfficialRoomMeta(raw) {
  if (!raw || typeof raw !== 'object') return null;
  const name = String(raw.name || '').trim();
  if (!name) return null;
  return {
    name,
    description: raw.description ? String(raw.description).trim() : '',
    topic: raw.topic ? String(raw.topic).trim() : '',
    tags: Array.isArray(raw.tags) ? raw.tags.map((t) => String(t || '').trim()).filter(Boolean) : [],
    features: Array.isArray(raw.features) ? raw.features.map((f) => String(f || '').trim()).filter(Boolean) : [],
    stations: Array.isArray(raw.stations) ? raw.stations.map((station) => {
      if (!station || typeof station !== 'object') return null;
      const label = String(station.label || station.name || '').trim();
      const page_url = String(station.page_url || station.url || '').trim();
      const embed_url = String(station.embed_url || '').trim();
      const provider = String(station.provider || '').trim();
      if (!label && !page_url && !embed_url) return null;
      return { label, page_url, embed_url, provider };
    }).filter(Boolean).slice(0, 16) : [],
    autosplit_base: raw.autosplit_base ? String(raw.autosplit_base).trim() : '',
    locked: !!raw.locked,
    readonly: !!raw.readonly,
    slowmode_seconds: Number(raw.slowmode_seconds || raw.slowmode || 0) || 0,
    capacity: Number(raw.capacity || raw.max_users || 0) || 0,
    full: !!raw.full,
  };
}

function rbFindCatalogRoom(roomName) {
  const name = String(roomName || '').trim();
  if (!name || !ROOM_BROWSER.catalog) return null;
  for (const cat of (ROOM_BROWSER.catalog.categories || [])) {
    const category = String(cat?.name || '').trim();
    for (const sub of (cat?.subcategories || [])) {
      const subcategory = String(sub?.name || '').trim();
      const rooms = Array.isArray(sub?.rooms) ? sub.rooms : [];
      for (const room of rooms) {
        const roomNameResolved = (typeof room === 'string') ? String(room || '').trim() : String(room?.name || '').trim();
        if (!rbSameRoomName(roomNameResolved, name)) continue;
        const canonicalName = roomNameResolved || name;
        return { name: canonicalName, isCustom: false, category, subcategory, meta: rbNormalizeOfficialRoomMeta(typeof room === 'object' ? { ...room, name: canonicalName } : { name: canonicalName }) };
      }
    }
  }
  return null;
}

function rbResolveCustomMeta(roomName, fallbackMeta = null) {
  const name = String(roomName || '').trim();
  const key = rbRoomNameKey(name);
  const fromLive = (ROOM_BROWSER.customRooms || []).find((r) => rbRoomNameKey(r?.name) === key);
  const src = fromLive || fallbackMeta || null;
  if (!src) return null;
  const canonicalName = String(src.name || src.room || name).trim() || name;
  return {
    name: canonicalName,
    created_by: src.created_by ? String(src.created_by) : null,
    my_room_role: src.my_room_role ? String(src.my_room_role) : '',
    can_room_moderate: !!src.can_room_moderate,
    is_private: !!src.is_private,
    is_18_plus: !!src.is_18_plus,
    is_nsfw: !!src.is_nsfw,
    category: src.category ? String(src.category) : null,
    subcategory: src.subcategory ? String(src.subcategory) : null,
    topic: src.topic ? String(src.topic) : '',
    member_count: Number(src.member_count || 0) || 0,
    locked: !!src.locked,
    readonly: !!src.readonly,
    slowmode_seconds: Number(src.slowmode_seconds || 0) || 0,
    capacity: Number(src.capacity || src.max_users || 0) || 0,
    full: !!src.full,
    idle_ttl_minutes: Number(src.idle_ttl_minutes || 0) || 0,
    idle_ttl_seconds: Number(src.idle_ttl_seconds || 0) || 0,
    last_active_at: src.last_active_at ? String(src.last_active_at) : null,
    last_active_age_seconds: Number(src.last_active_age_seconds || 0) || 0,
    expires_in_seconds: (src.expires_in_seconds === null || src.expires_in_seconds === undefined) ? null : (Number(src.expires_in_seconds) || 0),
    expires_at: src.expires_at ? String(src.expires_at) : null,
    timer_paused: !!src.timer_paused,
    deletion_state: src.deletion_state ? String(src.deletion_state) : '',
    cleanup_occupancy_count: Number(src.cleanup_occupancy_count || 0) || 0,
    _customExpiryLoadedAt: Number(src._customExpiryLoadedAt || Date.now()) || Date.now(),
  };
}

function rbBuildRow(roomName, { isCustom = false, meta = null, category = null, subcategory = null, recentAt = null } = {}) {
  const rawName = String(roomName || '').trim();
  if (!rawName) return null;
  const officialHit = !isCustom ? (rbFindCatalogRoom(rawName) || null) : null;
  const resolvedMeta = isCustom ? rbResolveCustomMeta(rawName, meta) : (rbNormalizeOfficialRoomMeta(meta) || officialHit?.meta || null);
  const name = String((isCustom ? resolvedMeta?.name : (resolvedMeta?.name || officialHit?.name)) || rawName).trim() || rawName;
  const statusMeta = rbMapGetRoomValue(ROOM_BROWSER.roomStatusMeta, name, {}) || rbMapGetRoomValue(ROOM_BROWSER.roomStatusMeta, rawName, {}) || {};
  const mergedMeta = { ...(resolvedMeta || {}), ...(statusMeta || {}) };
  const fallbackCount = Number(mergedMeta?.member_count ?? 0) || 0;
  const countValue = rbMapGetRoomValue(ROOM_BROWSER.counts, name, rbMapGetRoomValue(ROOM_BROWSER.counts, rawName, null));
  const liveCount = countValue !== null && countValue !== undefined
    ? (Number(countValue || 0) || 0)
    : fallbackCount;
  const capacity = Number(mergedMeta?.capacity || mergedMeta?.max_users || 0) || 0;
  const full = !!mergedMeta?.full || (capacity > 0 && liveCount >= capacity);
  const row = {
    name,
    isCustom: !!isCustom,
    meta: mergedMeta,
    category: category || resolvedMeta?.category || officialHit?.category || ROOM_BROWSER.selectedCategory || null,
    subcategory: subcategory || resolvedMeta?.subcategory || officialHit?.subcategory || ROOM_BROWSER.selectedSubcategory || null,
    cnt: liveCount,
    locked: !!mergedMeta?.locked,
    readonly: !!mergedMeta?.readonly,
    slowmode_seconds: Number(mergedMeta?.slowmode_seconds || 0) || 0,
    capacity,
    full,
    current: rbSameRoomName(UIState.currentRoom || '', name),
    unread: rbGetUnreadCount(name),
    favorite: rbIsFavoriteRoom(name, !!isCustom),
    recentAt: Number(recentAt || 0) || 0,
  };
  row.key = rbRoomKey(row.name, row.isCustom);
  return row;
}

function rbIsFavoriteRoom(roomName, isCustom = false) {
  const key = rbRoomKey(roomName, isCustom);
  return (ROOM_BROWSER.favoriteRooms || []).some((r) => rbRoomKey(r?.name, !!r?.isCustom) === key);
}

function rbToggleFavoriteRoom(rowLike) {
  const row = rbNormalizeStoredRoom({
    ...rowLike,
    isCustom: !!rowLike?.isCustom,
    category: rowLike?.category || rowLike?.meta?.category || null,
    subcategory: rowLike?.subcategory || rowLike?.meta?.subcategory || null,
    created_by: rowLike?.created_by || rowLike?.meta?.created_by || null,
    my_room_role: rowLike?.my_room_role || rowLike?.meta?.my_room_role || '',
    can_room_moderate: !!(rowLike?.can_room_moderate ?? rowLike?.meta?.can_room_moderate),
    is_private: !!(rowLike?.is_private ?? rowLike?.meta?.is_private),
    is_18_plus: !!(rowLike?.is_18_plus ?? rowLike?.meta?.is_18_plus),
    is_nsfw: !!(rowLike?.is_nsfw ?? rowLike?.meta?.is_nsfw),
    topic: rowLike?.topic || rowLike?.meta?.topic || '',
    member_count: Number(rowLike?.member_count || rowLike?.meta?.member_count || rowLike?.cnt || 0) || 0,
    locked: !!(rowLike?.locked ?? rowLike?.meta?.locked),
    readonly: !!(rowLike?.readonly ?? rowLike?.meta?.readonly),
    slowmode_seconds: Number(rowLike?.slowmode_seconds || rowLike?.meta?.slowmode_seconds || 0) || 0,
    capacity: Number(rowLike?.capacity || rowLike?.meta?.capacity || 0) || 0,
    full: !!(rowLike?.full ?? rowLike?.meta?.full),
  });
  if (!row) return;
  const key = rbRoomKey(row.name, row.isCustom);
  const items = Array.isArray(ROOM_BROWSER.favoriteRooms) ? ROOM_BROWSER.favoriteRooms.slice() : [];
  const idx = items.findIndex((r) => rbRoomKey(r?.name, !!r?.isCustom) === key);
  if (idx >= 0) {
    items.splice(idx, 1);
    toast(`⭐ Removed favorite: ${row.name}`, 'warn', 2200);
  } else {
    items.unshift({
      name: row.name,
      isCustom: row.isCustom,
      category: row.category || null,
      subcategory: row.subcategory || null,
      created_by: row.created_by || row.meta?.created_by || null,
      my_room_role: row.my_room_role || row.meta?.my_room_role || '',
      can_room_moderate: !!(row.can_room_moderate ?? row.meta?.can_room_moderate),
      is_private: !!(row.is_private ?? row.meta?.is_private),
      is_18_plus: !!(row.is_18_plus ?? row.meta?.is_18_plus),
      is_nsfw: !!(row.is_nsfw ?? row.meta?.is_nsfw),
      topic: row.topic || row.meta?.topic || '',
      member_count: Number(row.member_count || row.meta?.member_count || row.cnt || 0) || 0,
      locked: !!(row.locked ?? row.meta?.locked),
      readonly: !!(row.readonly ?? row.meta?.readonly),
      slowmode_seconds: Number(row.slowmode_seconds || row.meta?.slowmode_seconds || 0) || 0,
      capacity: Number(row.capacity || row.meta?.capacity || 0) || 0,
      full: !!(row.full ?? row.meta?.full),
      idle_ttl_minutes: Number(row.idle_ttl_minutes || row.meta?.idle_ttl_minutes || 0) || 0,
      idle_ttl_seconds: Number(row.idle_ttl_seconds || row.meta?.idle_ttl_seconds || 0) || 0,
      last_active_at: row.last_active_at || row.meta?.last_active_at || null,
      last_active_age_seconds: Number(row.last_active_age_seconds || row.meta?.last_active_age_seconds || 0) || 0,
      expires_in_seconds: (row.expires_in_seconds ?? row.meta?.expires_in_seconds ?? null),
      expires_at: row.expires_at || row.meta?.expires_at || null,
      timer_paused: !!(row.timer_paused ?? row.meta?.timer_paused),
      deletion_state: row.deletion_state || row.meta?.deletion_state || '',
      cleanup_occupancy_count: Number(row.cleanup_occupancy_count || row.meta?.cleanup_occupancy_count || 0) || 0,
      _customExpiryLoadedAt: Date.now(),
      lastAt: Date.now(),
    });
    toast(`⭐ Favorited room: ${row.name}`, 'ok', 2200);
  }
  ROOM_BROWSER.favoriteRooms = items.slice(0, 24);
  rbWriteStoredRoomList('roomBrowserFavorites', ROOM_BROWSER.favoriteRooms);
  rbRenderRoomLists();
}

function rbRememberRecentRoom(rowLike) {
  const row = rbNormalizeStoredRoom({
    ...rowLike,
    isCustom: !!rowLike?.isCustom,
    category: rowLike?.category || rowLike?.meta?.category || null,
    subcategory: rowLike?.subcategory || rowLike?.meta?.subcategory || null,
    created_by: rowLike?.created_by || rowLike?.meta?.created_by || null,
    my_room_role: rowLike?.my_room_role || rowLike?.meta?.my_room_role || '',
    can_room_moderate: !!(rowLike?.can_room_moderate ?? rowLike?.meta?.can_room_moderate),
    is_private: !!(rowLike?.is_private ?? rowLike?.meta?.is_private),
    is_18_plus: !!(rowLike?.is_18_plus ?? rowLike?.meta?.is_18_plus),
    is_nsfw: !!(rowLike?.is_nsfw ?? rowLike?.meta?.is_nsfw),
    topic: rowLike?.topic || rowLike?.meta?.topic || '',
    member_count: Number(rowLike?.member_count || rowLike?.meta?.member_count || rowLike?.cnt || 0) || 0,
    locked: !!(rowLike?.locked ?? rowLike?.meta?.locked),
    readonly: !!(rowLike?.readonly ?? rowLike?.meta?.readonly),
    slowmode_seconds: Number(rowLike?.slowmode_seconds || rowLike?.meta?.slowmode_seconds || 0) || 0,
    capacity: Number(rowLike?.capacity || rowLike?.meta?.capacity || 0) || 0,
    full: !!(rowLike?.full ?? rowLike?.meta?.full),
    idle_ttl_minutes: Number(rowLike?.idle_ttl_minutes || rowLike?.meta?.idle_ttl_minutes || 0) || 0,
    idle_ttl_seconds: Number(rowLike?.idle_ttl_seconds || rowLike?.meta?.idle_ttl_seconds || 0) || 0,
    last_active_at: rowLike?.last_active_at || rowLike?.meta?.last_active_at || null,
    last_active_age_seconds: Number(rowLike?.last_active_age_seconds || rowLike?.meta?.last_active_age_seconds || 0) || 0,
    expires_in_seconds: (rowLike?.expires_in_seconds ?? rowLike?.meta?.expires_in_seconds ?? null),
    expires_at: rowLike?.expires_at || rowLike?.meta?.expires_at || null,
    timer_paused: !!(rowLike?.timer_paused ?? rowLike?.meta?.timer_paused),
    deletion_state: rowLike?.deletion_state || rowLike?.meta?.deletion_state || '',
    cleanup_occupancy_count: Number(rowLike?.cleanup_occupancy_count || rowLike?.meta?.cleanup_occupancy_count || 0) || 0,
    _customExpiryLoadedAt: Date.now(),
    lastAt: Date.now(),
  });
  if (!row) return;
  const key = rbRoomKey(row.name, row.isCustom);
  const items = Array.isArray(ROOM_BROWSER.recentRooms) ? ROOM_BROWSER.recentRooms.slice() : [];
  const filtered = items.filter((r) => rbRoomKey(r?.name, !!r?.isCustom) !== key);
  filtered.unshift(row);
  ROOM_BROWSER.recentRooms = filtered.slice(0, 12);
  rbWriteStoredRoomList('roomBrowserRecent', ROOM_BROWSER.recentRooms);
}

function rbClearUnread(roomName) {
  const key = rbUnreadKey(roomName);
  if (!key) return;
  for (const candidate of Array.from(ROOM_BROWSER.unreadCounts.keys())) {
    if (rbRoomNameKey(candidate) === key) ROOM_BROWSER.unreadCounts.delete(candidate);
  }
}
