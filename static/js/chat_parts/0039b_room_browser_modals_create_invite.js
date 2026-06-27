function rbOpenModal(id) {
  clearSearchesForModalTransition();
  const el = $(id);
  if (el) el.classList.remove('hidden');
}
function rbCloseModal(id) {
  const el = $(id);
  if (el) el.classList.add('hidden');
  clearSearchesForModalTransition();
}

function crUpdateNameCount() {
  const input = $('crName');
  const count = $('crNameCount');
  if (!input || !count) return;
  const max = Number(input.getAttribute('maxlength') || 48) || 48;
  const used = String(input.value || '').length;
  count.textContent = `${used}/${max}`;
  count.classList.toggle('is-warning', used >= Math.max(1, max - 8));
}

function crUpdateVisibilityCards() {
  let selected = 'public';
  try {
    const checked = document.querySelector('input[name="crVis"]:checked');
    selected = String(checked?.value || 'public');
  } catch {}
  try {
    document.querySelectorAll('[data-cr-vis-card]').forEach((card) => {
      const active = String(card.getAttribute('data-cr-vis-card') || '') === selected;
      card.classList.toggle('is-active', active);
      card.setAttribute('aria-checked', active ? 'true' : 'false');
    });
  } catch {}
}

function crSetCreateBusy(isBusy) {
  const btn = $('btnCreateRoom');
  const cancel = $('btnCancelCreateRoom');
  const close = $('btnCloseCreateRoom');
  if (btn) {
    btn.disabled = !!isBusy;
    btn.textContent = isBusy ? 'Creating…' : 'Create and enter room';
  }
  if (cancel) cancel.disabled = !!isBusy;
  if (close) close.disabled = !!isBusy;
}

function rbPopulateCreateRoomSelects() {
  const catSel = $('crCategory');
  const subSel = $('crSubcategory');
  if (!catSel || !subSel) return;
  catSel.replaceChildren();
  subSel.replaceChildren();

  const cats = (ROOM_BROWSER.catalog && ROOM_BROWSER.catalog.categories) ? ROOM_BROWSER.catalog.categories : [];
  cats.forEach((c) => {
    const opt = document.createElement('option');
    opt.value = c.name;
    opt.textContent = c.name;
    catSel.appendChild(opt);
  });

  const setSubs = () => {
    subSel.replaceChildren();
    const catName = catSel.value;
    const c = cats.find((x) => x.name === catName);
    (c?.subcategories || []).forEach((s) => {
      const opt = document.createElement('option');
      opt.value = s.name;
      opt.textContent = s.name;
      subSel.appendChild(opt);
    });
  };

  catSel.onchange = setSubs;
  setSubs();

  try {
    if (ROOM_BROWSER.selectedCategory) catSel.value = ROOM_BROWSER.selectedCategory;
    setSubs();
    if (ROOM_BROWSER.selectedSubcategory) subSel.value = ROOM_BROWSER.selectedSubcategory;
  } catch {}
}

function rbResetCreateRoomForm() {
  const nameInput = $('crName');
  if (nameInput) nameInput.value = '';
  const cr18 = $('cr18');
  if (cr18) cr18.checked = false;
  const crNSFW = $('crNSFW');
  if (crNSFW) crNSFW.checked = false;
  try {
    const radios = document.querySelectorAll('input[name="crVis"]');
    radios.forEach((r) => { r.checked = (r.value === 'public'); });
  } catch {}
  crSetCreateBusy(false);
  crUpdateNameCount();
  crUpdateVisibilityCards();
}

function rbOpenCreateRoomModal() {
  rbPopulateCreateRoomSelects();
  rbResetCreateRoomForm();
  rbOpenModal('createRoomModal');
  try { setTimeout(() => $('crName')?.focus(), 30); } catch {}
}

async function rbCreateRoom() {
  const name = ($('crName')?.value || '').trim();
  const category = ($('crCategory')?.value || '').trim();
  const subcategory = ($('crSubcategory')?.value || '').trim();
  const roomScopeBeforeCreate = String(ROOM_BROWSER.roomScope || 'all');
  const is_nsfw = !!$('crNSFW')?.checked;
  const is_18_plus = !!$('cr18')?.checked || is_nsfw;
  let is_private = false;
  try {
    const sel = document.querySelector('input[name="crVis"]:checked');
    is_private = (sel && sel.value === 'private');
  } catch {}

  if (!name) { toast('⚠️ Room name required', 'warn'); $('crName')?.focus(); return; }
  if (!category || !subcategory) { toast('⚠️ Choose a category and subcategory', 'warn'); return; }

  const payload = { name, category, subcategory, is_private, is_18_plus, is_nsfw };
  crSetCreateBusy(true);
  let resp = null;
  let data = {};
  try {
    resp = await fetchWithAuth('/api/custom_rooms', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    }, { retryOn401: true });

    data = (typeof ecReadApiJson === 'function') ? await ecReadApiJson(resp, {}) : await resp.json().catch(() => ({}));
  } catch (e) {
    crSetCreateBusy(false);
    toast(`❌ Create failed: ${e?.message || 'network_error'}`, 'error');
    return;
  }
  crSetCreateBusy(false);

  if (!resp || !resp.ok) {
    const msg = (typeof ecApiErrorMessage === 'function') ? ecApiErrorMessage(resp, data, 'Create failed') : (data?.error || 'Create failed');
    const existing = data?.existing || null;
    toast(`❌ ${msg}`, 'error');

    try {
      if (existing && existing.category && existing.subcategory) {
        ROOM_BROWSER.selectedCategory = String(existing.category);
        ROOM_BROWSER.selectedSubcategory = String(existing.subcategory);
        ROOM_BROWSER.roomScope = roomScopeBeforeCreate || 'all';
        rbRenderCategoryTree();
        await rbRefreshLists();
      }
    } catch {}

    return;
  }
  const createdRoomName = String(data?.room || name).trim() || name;
  const createdMeta = {
    ...payload,
    ...data,
    name: createdRoomName,
    room: createdRoomName,
    created_by: data?.created_by || currentUser || payload.created_by || '',
    auto_join: true,
  };

  toast(`✅ Room created: ${createdRoomName}. Opening…`, 'ok');
  rbCloseModal('createRoomModal');
  ROOM_BROWSER.selectedCategory = category;
  ROOM_BROWSER.selectedSubcategory = subcategory;
  ROOM_BROWSER.roomScope = roomScopeBeforeCreate || 'all';
  rbRenderCategoryTree();
  await rbRefreshLists();

  rbSelectRoom(rbBuildRow(createdRoomName, { isCustom: true, meta: createdMeta, category, subcategory }), { render: true });

  if (typeof joinRoom === 'function') {
    try {
      const autoJoinPayload = (data && data.auto_join_payload && typeof data.auto_join_payload === 'object') ? data.auto_join_payload : null;
      const joined = await joinRoom(createdRoomName, {
        silent: true,
        autoJoinCreatedCustomRoom: !!(autoJoinPayload && autoJoinPayload.auto_join_created_custom_room)
      });
      if (joined?.success) {
        const joinedRoom = String(joined?.room || createdRoomName);
        toast(`🚪 Created and joined: ${joinedRoom}`, 'ok');
      } else {
        toast(`⚠️ Room created, but auto-join failed: ${joined?.error || 'join_failed'}`, 'warn');
      }
    } catch (e) {
      toast(`⚠️ Room created, but auto-join failed: ${e?.message || 'join_failed'}`, 'warn');
    }
  }
}

function rbOpenInviteModal(roomName) {
  ROOM_BROWSER.inviteRoom = roomName;
  const lab = $('irRoomLabel');
  if (lab) lab.textContent = `Room: ${roomName}`;
  const inp = $('irUser');
  if (inp) inp.value = '';
  rbOpenModal('inviteRoomModal');
}

async function rbSendInvite() {
  const room = ROOM_BROWSER.inviteRoom;
  const invitee = ($('irUser')?.value || '').trim();
  if (!room || !invitee) { toast('⚠️ Room + username required', 'warn'); return; }

  const resp = await fetchWithAuth('/api/custom_rooms/invite', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ room, invitee })
  }, { retryOn401: true });

  const data = (typeof ecReadApiJson === 'function') ? await ecReadApiJson(resp, {}) : await resp.json().catch(() => ({}));
  if (!resp || !resp.ok) {
    const msg = (typeof ecApiErrorMessage === 'function') ? ecApiErrorMessage(resp, data, 'Invite failed') : (data?.error || 'Invite failed');
    toast(`❌ ${msg}`, 'error');
    return;
  }
  toast(`✅ Invited ${invitee}`, 'ok');
  rbCloseModal('inviteRoomModal');
}
