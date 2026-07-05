function rbApplyRoomCounts(countsObj) {
  if (!countsObj || typeof countsObj !== 'object') return;
  const m = new Map();
  try {
    Object.entries(countsObj).forEach(([k, v]) => {
      const n = Number(v || 0) || 0;
      if (k) m.set(String(k), n);
    });
  } catch {}
  ROOM_BROWSER.counts = m;
  rbUpdateCountsInDom();
}

function rbRoomListElements() {
  return [$('rbRoomsList'), $('rbCustomRoomsList')].filter(Boolean);
}

function rbUpdateCountsInDom() {
  const lists = rbRoomListElements();
  if (!lists.length) return;
  try {
    lists.forEach((list) => {
      list.querySelectorAll('li[data-room]').forEach((li) => {
        const room = li.dataset.room;
        const cnt = rbMapGetRoomValue(ROOM_BROWSER.counts, room, 0) || 0;
        li.classList.toggle('has-online', cnt > 0);
        const roomCountBadge = li.querySelector('.rbCountBadge');
        if (roomCountBadge) {
          const countText = roomCountBadge.querySelector('.rbCountText');
          if (countText) countText.textContent = String(cnt);
          else roomCountBadge.textContent = String(cnt);
          roomCountBadge.classList.toggle('zero', cnt <= 0);
        }
        const mt = li.querySelector('.rbItemMeta');
        if (mt) {
          const roomKey = rbRoomKey(room, li.dataset.custom === '1');
          const currentRow = ROOM_BROWSER.lastRenderedRows.find((r) => r.key === roomKey || (r.isCustom === (li.dataset.custom === '1') && rbSameRoomName(r.name, room)));
          if (currentRow && typeof rbRoomMetaText === 'function') {
            currentRow.cnt = Number(cnt || 0) || 0;
            const capacity = Number(currentRow.capacity || currentRow.meta?.capacity || 0) || 0;
            currentRow.full = capacity > 0 ? currentRow.cnt >= capacity : !!currentRow.meta?.full;
            mt.textContent = rbRoomMetaText(currentRow, cnt);
          }
        }
      });
    });
  } catch {}
}

function rbRenderCategoryTree() {
  const ul = $('rbCategoryTree');
  if (!ul) return;
  ul.replaceChildren();

  const q = rbNorm(ROOM_BROWSER.catQuery);
  const cats = (typeof rbCatalogCategories === 'function') ? rbCatalogCategories() : ((ROOM_BROWSER.catalog && ROOM_BROWSER.catalog.categories) ? ROOM_BROWSER.catalog.categories : []);
  let renderedAny = false;

  if (!cats.length) {
    rbRenderEmptyRooms(ul, 'No official room categories', 'The official room catalog did not load any categories or subcategories.');
    return;
  }

  cats.forEach((c) => {
    const cName = String(c.name || '').trim();
    if (!cName) return;
    const subs = (typeof rbCatalogSubcategories === 'function') ? rbCatalogSubcategories(c) : (Array.isArray(c.subcategories) ? c.subcategories : []);
    const catMatches = (typeof rbCategoryMatchesCatalogQuery === 'function') ? rbCategoryMatchesCatalogQuery(c, q) : (q ? rbNorm(cName).includes(q) : true);
    if (q && !catMatches) return;

    let matchingSubs = subs;
    if (q && typeof rbSubcategoryMatchesCatalogQuery === 'function') {
      matchingSubs = subs.filter((s) => rbSubcategoryMatchesCatalogQuery(cName, s, q));
    } else if (q) {
      matchingSubs = subs.filter((s) => rbNorm(s?.name || '').includes(q) || rbNorm(cName).includes(q));
    }
    if (q && !matchingSubs.length) return;

    const collapsed = (!q) && ROOM_BROWSER.collapsedCats.has(cName);
    const officialCount = (typeof rbCategoryOfficialRoomCount === 'function') ? rbCategoryOfficialRoomCount(c) : 0;
    const onlineCount = (typeof rbCategoryOnlineCount === 'function') ? rbCategoryOnlineCount(c) : 0;

    const header = document.createElement('li');
    header.className = 'rbCatHeader';
    header.dataset.category = cName;
    header.setAttribute('role', 'button');
    header.setAttribute('tabindex', '0');
    header.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
    header.setAttribute('title', collapsed ? `Show ${cName} subcategories` : `Hide ${cName} subcategories`);

    const row = document.createElement('div');
    row.className = 'rbCatHeadRow';
    const title = document.createElement('span');
    title.className = 'rbCatName';
    title.textContent = cName;
    const counts = document.createElement('span');
    counts.className = 'rbCatCounts';
    counts.textContent = `${officialCount} rooms${onlineCount > 0 ? ` • ${onlineCount} online` : ''}`;
    const chev = document.createElement('span');
    chev.className = 'rbCatChevron';
    chev.textContent = collapsed ? '▸' : '▾';
    row.appendChild(title);
    row.appendChild(counts);
    row.appendChild(chev);
    header.appendChild(row);

    const toggle = () => {
      if (q) return;
      if (ROOM_BROWSER.collapsedCats.has(cName)) ROOM_BROWSER.collapsedCats.delete(cName);
      else ROOM_BROWSER.collapsedCats.add(cName);
      rbRenderCategoryTree();
    };
    header.addEventListener('click', toggle);
    header.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        toggle();
      }
    });
    ul.appendChild(header);
    renderedAny = true;

    if (collapsed) return;

    matchingSubs.forEach((s) => {
      const sName = String(s?.name || '').trim();
      if (!sName) return;
      const subRoomCount = (typeof rbSubcategoryOfficialRoomCount === 'function') ? rbSubcategoryOfficialRoomCount(s) : 0;
      const subOnlineCount = (typeof rbSubcategoryOnlineCount === 'function') ? rbSubcategoryOnlineCount(s) : 0;
      const li = document.createElement('li');
      li.className = 'rbCatSub';
      li.dataset.category = cName;
      li.dataset.subcategory = sName;
      li.setAttribute('role', 'option');
      li.setAttribute('tabindex', '0');
      const active = (ROOM_BROWSER.selectedCategory === cName && ROOM_BROWSER.selectedSubcategory === sName);
      li.setAttribute('aria-selected', active ? 'true' : 'false');
      if (active) li.classList.add('active');

      const nameSpan = document.createElement('span');
      nameSpan.className = 'rbCatSubName';
      nameSpan.textContent = sName;
      const metaSpan = document.createElement('span');
      metaSpan.className = 'rbCatSubMeta';
      metaSpan.textContent = `${subRoomCount} rooms${subOnlineCount > 0 ? ` • ${subOnlineCount} online` : ''}`;
      li.appendChild(nameSpan);
      li.appendChild(metaSpan);

      const choose = async () => {
        const prevCategory = String(ROOM_BROWSER.selectedCategory || '');
        const prevSubcategory = String(ROOM_BROWSER.selectedSubcategory || '');
        ROOM_BROWSER.selectedCategory = cName;
        ROOM_BROWSER.selectedSubcategory = sName;
        if (['recent', 'favorites', 'current', 'unread'].includes(ROOM_BROWSER.roomScope)) {
          ROOM_BROWSER.roomScope = 'all';
        }
        if (prevCategory !== cName || prevSubcategory !== sName) {
          clearRoomBrowserSearchesForPanelSwitch();
        }
        rbRenderCategoryTree();
        await rbRefreshLists();
        try { if (typeof window.ecSetMobileRoomBrowserStep === 'function') window.ecSetMobileRoomBrowserStep('official'); } catch {}
      };
      li.addEventListener('click', choose);
      li.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          choose();
        }
      });
      ul.appendChild(li);
      renderedAny = true;
    });
  });

  if (!renderedAny) {
    rbRenderEmptyRooms(ul, 'No category matches', 'Search category names, subcategories, room names, topics, tags, or features.');
  }
}

function rbUpdateScopeButtons() {
  try {
    document.querySelectorAll('#rbScopeBar .rbScopeChip').forEach((btn) => {
      const scope = String(btn.dataset.rbScope || 'all');
      const active = scope === String(ROOM_BROWSER.roomScope || 'all');
      btn.classList.toggle('is-active', active);
      btn.setAttribute('aria-selected', active ? 'true' : 'false');
      if (scope === 'unread') {
        const total = Array.from(ROOM_BROWSER.unreadCounts.values()).reduce((a, b) => a + (Number(b || 0) || 0), 0);
        btn.textContent = total > 0 ? `Unread (${total})` : 'Unread';
      }
    });
  } catch {}
}

function rbUpdateToolVisibility() {
  const customTools = $('rbCustomTools');
  if (customTools) customTools.classList.remove('hidden');
}

function rbSetSelectedRow(row, opts = {}) {
  if (!row) {
    ROOM_BROWSER.selectedRoom = null;
    ROOM_BROWSER.selectedRoomIsCustom = false;
    ROOM_BROWSER.selectedRoomMeta = null;
    ROOM_BROWSER.selectedRoomCategory = null;
    ROOM_BROWSER.selectedRoomSubcategory = null;
    return;
  }
  ROOM_BROWSER.selectedRoom = row.name;
  ROOM_BROWSER.selectedRoomIsCustom = !!row.isCustom;
  ROOM_BROWSER.selectedRoomMeta = row.meta || null;
  ROOM_BROWSER.selectedRoomCategory = row.category || null;
  ROOM_BROWSER.selectedRoomSubcategory = row.subcategory || null;
  if (opts.syncCategory && row.category && row.subcategory) {
    ROOM_BROWSER.selectedCategory = row.category;
    ROOM_BROWSER.selectedSubcategory = row.subcategory;
  }
  rbEnsureOccupantsForRoom(row);
}

function rbSyncSelectionInDom() {
  const selectedKey = rbRoomKey(ROOM_BROWSER.selectedRoom, !!ROOM_BROWSER.selectedRoomIsCustom);
  try {
    rbRoomListElements().forEach((list) => {
      list.querySelectorAll('li.rbRoomRow[data-room-key]').forEach((li) => {
        li.classList.toggle('active', String(li.dataset.roomKey || '') === String(selectedKey || ''));
      });
    });
  } catch {}
}

function rbSelectRoom(row, opts = {}) {
  rbSetSelectedRow(row, { syncCategory: !!opts.syncCategory });
  if (opts.render !== false) {
    rbRenderRoomLists();
  } else {
    rbSyncSelectionInDom();
  }
}

function rbRenderEmptyRooms(list, message, subMessage = '') {
  const li = document.createElement('li');
  li.className = 'rbEmptyState';
  li.style.cursor = 'default';

  const left = document.createElement('div');
  left.className = 'rbItemLeft';
  const text = document.createElement('div');
  text.className = 'rbItemText';
  const name = document.createElement('div');
  name.className = 'rbItemName muted';
  name.textContent = String(message || '');
  text.appendChild(name);

  if (subMessage) {
    const meta = document.createElement('div');
    meta.className = 'rbItemMeta muted';
    meta.textContent = String(subMessage || '');
    text.appendChild(meta);
  }

  left.appendChild(text);
  li.appendChild(left);
  list.appendChild(li);
}

function rbUniqueRows(rows) {
  const out = [];
  const seen = new Set();
  (rows || []).forEach((row) => {
    if (!row?.key || seen.has(row.key)) return;
    seen.add(row.key);
    out.push(row);
  });
  return out;
}

function rbRenderCustomRoomsPanel(list, rows, opts = {}) {
  if (!list) return;
  list.replaceChildren();
  if (opts.suppressedByScope) {
    rbRenderEmptyRooms(list, 'Custom scope active', 'Custom rooms are shown in the main room list while the Custom scope is selected.');
    return;
  }
  if (!rows.length) {
    const noMatch = !!(ROOM_BROWSER.customQuery || ROOM_BROWSER.customFilter !== 'all' || ROOM_BROWSER.hideEmpty);
    rbRenderEmptyRooms(
      list,
      noMatch ? 'No custom room matches' : 'No custom rooms here yet',
      noMatch ? 'Adjust custom filters, status filters, or turn off Hide empty.' : 'Use Create Room to make one. Created rooms open automatically.'
    );
    return;
  }
  const hdr = document.createElement('li');
  hdr.className = 'rbGroupHeader';
  hdr.textContent = 'Custom rooms';
  list.appendChild(hdr);
  rows.forEach((row) => list.appendChild(rbMakeRoomLi(row)));
}

function rbRenderRoomLists() {
  const list = $('rbRoomsList');
  const customList = $('rbCustomRoomsList');
  if (!list) return;
  list.replaceChildren();
  if (customList) customList.replaceChildren();
  rbSetSelectionLabel();
  rbUpdateScopeButtons();
  rbUpdateToolVisibility();

  const { rows, sections } = rbRowsForScope();
  const mainRows = Array.isArray(rows) ? rows.slice() : [];
  const allCustomPanelRows = rbCustomRowsForSelection();
  const suppressCustomPanel = ROOM_BROWSER.roomScope === 'custom';
  const customPanelRows = suppressCustomPanel ? [] : allCustomPanelRows;
  ROOM_BROWSER.lastRenderedRows = rbUniqueRows([...mainRows, ...customPanelRows]);

  const selectedKey = rbRoomKey(ROOM_BROWSER.selectedRoom, !!ROOM_BROWSER.selectedRoomIsCustom);
  const hasSelected = ROOM_BROWSER.lastRenderedRows.some((row) => row.key === selectedKey);
  if (!hasSelected) {
    if (mainRows.length) rbSetSelectedRow(mainRows[0]);
    else if (customPanelRows.length) rbSetSelectedRow(customPanelRows[0]);
    else rbSetSelectedRow(null);
  }

  const appendSection = (label, rowsForSection) => {
    if (!rowsForSection || !rowsForSection.length) return;
    const hdr = document.createElement('li');
    hdr.className = 'rbGroupHeader';
    hdr.textContent = label;
    list.appendChild(hdr);
    rowsForSection.forEach((row) => list.appendChild(rbMakeRoomLi(row)));
  };

  if (!mainRows.length) {
    const scope = ROOM_BROWSER.roomScope;
    if (scope === 'current') rbRenderEmptyRooms(list, 'No current room', 'Join a room and it will show up here.');
    else if (scope === 'recent') rbRenderEmptyRooms(list, 'No recent rooms yet', 'Rooms you open will appear here.');
    else if (scope === 'favorites') rbRenderEmptyRooms(list, 'No favorites yet', 'Use the ☆ button on a room row to pin favorites.');
    else if (scope === 'unread') rbRenderEmptyRooms(list, 'No unread rooms', 'Unread room counters will appear here when this client tracks them.');
    else if (scope === 'custom') rbRenderEmptyRooms(list, ROOM_BROWSER.customFilter !== 'all' ? 'No custom room matches this filter' : 'No custom rooms', 'Use the Custom Rooms panel to create or join custom rooms.');
    else if (scope === 'official') rbRenderEmptyRooms(list, (ROOM_BROWSER.roomQuery || ROOM_BROWSER.hideEmpty || ROOM_BROWSER.roomStatusFilter !== 'all') ? 'No official room matches' : 'No official rooms', 'Adjust search, status filters, Hide empty, or pick another category.');
    else rbRenderEmptyRooms(list, 'No rooms match', 'Adjust search/status filters or try a different scope.');
  } else if (ROOM_BROWSER.roomScope === 'all') {
    sections.forEach((section) => appendSection(section.label, section.rows));
  } else {
    const only = sections[0];
    if (ROOM_BROWSER.roomScope === 'current') {
      mainRows.forEach((row) => list.appendChild(rbMakeRoomLi(row)));
    } else if (only) {
      appendSection(only.label, only.rows);
    }
  }

  rbRenderCustomRoomsPanel(customList, customPanelRows, { suppressedByScope: suppressCustomPanel });
  rbSyncSelectionInDom();
}

function rbSelectedRowSnapshot() {
  const key = rbRoomKey(ROOM_BROWSER.selectedRoom, !!ROOM_BROWSER.selectedRoomIsCustom);
  return ROOM_BROWSER.lastRenderedRows.find((row) => row.key === key) || (ROOM_BROWSER.selectedRoom ? rbBuildRow(ROOM_BROWSER.selectedRoom, {
    isCustom: !!ROOM_BROWSER.selectedRoomIsCustom,
    meta: ROOM_BROWSER.selectedRoomMeta,
    category: ROOM_BROWSER.selectedRoomCategory,
    subcategory: ROOM_BROWSER.selectedRoomSubcategory,
  }) : null);
}

function rbActionButton(label, extraClass = '') {
  const btn = document.createElement('button');
  btn.type = 'button';
  btn.className = `rbDetailBtn ${extraClass}`.trim();
  btn.textContent = label;
  return btn;
}
