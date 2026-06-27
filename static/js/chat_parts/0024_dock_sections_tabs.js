// Dock tabs + search
// ───────────────────────────────────────────────────────────────────────────────
function getDockPanelByKey(panelKey) {
  return $(panelKey === 'groups' ? 'panelGroups' : 'panelFriends');
}

function getDockSectionStorageKey(panelKey) {
  return `dockSectionOrder_${String(panelKey || 'friends')}`;
}

function getDockSections(panel) {
  if (!panel) return [];
  return [...panel.querySelectorAll(':scope > .dockSection[id]')];
}

function saveDockSectionOrder(panelKey) {
  const panel = getDockPanelByKey(panelKey);
  if (!panel) return;
  const order = getDockSections(panel).map((section) => section.id).filter(Boolean);
  Settings.set(getDockSectionStorageKey(panelKey), order);
}

function applyDockSectionOrder(panelKey) {
  const panel = getDockPanelByKey(panelKey);
  if (!panel) return;

  const defaults = Array.isArray(DOCK_SECTION_DEFAULT_ORDER[panelKey]) ? DOCK_SECTION_DEFAULT_ORDER[panelKey].slice() : [];
  const saved = Settings.get(getDockSectionStorageKey(panelKey), defaults);
  const sections = getDockSections(panel);
  const map = new Map(sections.map((section) => [section.id, section]));
  const mergedOrder = [];

  [...saved, ...defaults, ...sections.map((section) => section.id)].forEach((id) => {
    const key = String(id || '');
    if (!key || !map.has(key) || mergedOrder.includes(key)) return;
    mergedOrder.push(key);
  });

  const tail = panel.querySelector(':scope > .dockSearchEmpty');
  mergedOrder.forEach((id) => {
    const section = map.get(id);
    if (!section) return;
    if (tail) panel.insertBefore(section, tail);
    else panel.appendChild(section);
  });
}

function getDockDragRects(panel) {
  if (!panel) return [];
  const cached = panel._ecDockDragRects;
  if (Array.isArray(cached)) return cached;
  const rects = getDockSections(panel)
    .filter((section) => !section.classList.contains('dragging'))
    .map((section) => {
      const rect = section.getBoundingClientRect();
      return { section, top: rect.top, height: rect.height };
    });
  panel._ecDockDragRects = rects;
  return rects;
}

function clearDockDragRects(panel) {
  if (!panel) return;
  try { delete panel._ecDockDragRects; } catch { panel._ecDockDragRects = null; }
}

function getDockDragAfterElement(panel, y) {
  const rects = getDockDragRects(panel);
  let closest = { offset: Number.NEGATIVE_INFINITY, element: null };
  rects.forEach(({ section, top, height }) => {
    const offset = y - top - height / 2;
    if (offset < 0 && offset > closest.offset) closest = { offset, element: section };
  });
  return closest.element;
}

function clearDockDragOverMarkers() {
  document.querySelectorAll('.dockSection.dragOver').forEach((el) => el.classList.remove('dragOver'));
}

function decorateDockSection(section) {
  if (!section || section.dataset.dragDecorated === '1') return;
  section.dataset.dragDecorated = '1';
  section.draggable = true;

  const row = section.querySelector('.panelSubRow');
  if (row) {
    row.classList.add('dockSectionHeaderRow');
    let main = row.querySelector('.dockSectionHeaderMain');
    if (!main) {
      main = document.createElement('div');
      main.className = 'dockSectionHeaderMain';
      const first = row.querySelector('.panelSub');
      if (first) row.insertBefore(main, first);
      while (row.firstChild && row.firstChild !== main) main.appendChild(row.firstChild);
      const sub = row.querySelector('.panelSub');
      if (sub && sub.parentElement !== main) main.appendChild(sub);
    }

    if (!row.querySelector('.dockDragHandle')) {
      const handle = document.createElement('button');
      handle.type = 'button';
      handle.className = 'dockDragHandle';
      handle.title = 'Drag to move section';
      handle.setAttribute('aria-label', 'Drag to move section');
      handle.textContent = '⋮⋮';
      handle.draggable = false;
      handle.addEventListener('mousedown', () => { section.dataset.dragArmed = '1'; });
      handle.addEventListener('touchstart', () => { section.dataset.dragArmed = '1'; }, { passive: true });
      main.insertBefore(handle, main.firstChild || null);
    }
  }

  section.addEventListener('dragstart', (ev) => {
    if (section.dataset.dragArmed !== '1') {
      ev.preventDefault();
      return;
    }
    const panel = section.closest('.dockPanel');
    if (!panel) {
      ev.preventDefault();
      return;
    }
    section.classList.add('dragging');
    clearDockDragRects(panel);
    getDockDragRects(panel);
    if (ev.dataTransfer) {
      ev.dataTransfer.effectAllowed = 'move';
      try { ev.dataTransfer.setData('text/plain', section.id || 'dock-section'); } catch {}
    }
  });

  section.addEventListener('dragend', () => {
    delete section.dataset.dragArmed;
    section.classList.remove('dragging');
    clearDockDragOverMarkers();
    const panel = section.closest('.dockPanel');
    clearDockDragRects(panel);
    const panelKey = panel?.dataset?.panelKey || '';
    if (panelKey) saveDockSectionOrder(panelKey);
  });
}

function initDockSectionReorder() {
  document.querySelectorAll('.dockPanel').forEach((panel) => {
    const panelKey = String(panel.dataset.panelKey || '');
    if (!panelKey) return;
    applyDockSectionOrder(panelKey);
    getDockSections(panel).forEach((section) => decorateDockSection(section));

    let pendingDragY = 0;
    const runDragOver = (typeof ecRafThrottle === 'function') ? ecRafThrottle(() => {
      const dragging = panel.querySelector('.dockSection.dragging');
      if (!dragging) return;
      const after = getDockDragAfterElement(panel, pendingDragY);
      const currentAfter = dragging.nextElementSibling === after || (!after && dragging.nextElementSibling && dragging.nextElementSibling.classList?.contains('dockSearchEmpty'));
      if (currentAfter) return;
      if (after) panel.insertBefore(dragging, after);
      else {
        const tail = panel.querySelector(':scope > .dockSearchEmpty');
        if (tail) panel.insertBefore(dragging, tail);
        else panel.appendChild(dragging);
      }
      clearDockDragRects(panel);
      clearDockDragOverMarkers();
      if (after) after.classList.add('dragOver');
    }) : null;

    panel.addEventListener('dragover', (ev) => {
      const dragging = panel.querySelector('.dockSection.dragging');
      if (!dragging) return;
      ev.preventDefault();
      pendingDragY = ev.clientY;
      if (runDragOver) runDragOver();
      else {
        const after = getDockDragAfterElement(panel, pendingDragY);
        if (after) panel.insertBefore(dragging, after);
        else panel.appendChild(dragging);
        clearDockDragRects(panel);
      }
    });

    panel.addEventListener('drop', (ev) => {
      const dragging = panel.querySelector('.dockSection.dragging');
      if (!dragging) return;
      ev.preventDefault();
      clearDockDragOverMarkers();
      saveDockSectionOrder(panelKey);
    });

    panel.addEventListener('dragleave', (ev) => {
      const rel = ev.relatedTarget;
      if (rel && panel.contains(rel)) return;
      clearDockDragOverMarkers();
    });
  });

  document.addEventListener('mouseup', () => {
    document.querySelectorAll('.dockSection[data-drag-armed="1"]').forEach((el) => delete el.dataset.dragArmed);
    clearFriendDragArmedFlags();
  });
  document.addEventListener('touchend', () => {
    document.querySelectorAll('.dockSection[data-drag-armed="1"]').forEach((el) => delete el.dataset.dragArmed);
    clearFriendDragArmedFlags();
  }, { passive: true });
}
