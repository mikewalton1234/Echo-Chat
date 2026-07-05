function rbFormatCustomRoomCountdown(totalSeconds) {
  const sec = Math.max(0, Math.floor(Number(totalSeconds || 0) || 0));
  const d = Math.floor(sec / 86400);
  const h = Math.floor((sec % 86400) / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const s = sec % 60;
  if (d > 0) return `${d}d ${h}h`;
  if (h > 0) return `${h}h ${m}m`;
  if (m > 0) return `${m}m ${s}s`;
  return `${s}s`;
}

function rbCustomRoomExpiryText(row) {
  if (!row?.isCustom) return '';
  const meta = row.meta || {};
  const ttlMinutes = Number(meta.idle_ttl_minutes || 0) || 0;
  if (!ttlMinutes) return '';
  const occupancy = Number(row.cnt || meta.cleanup_occupancy_count || 0) || 0;
  if (occupancy > 0 || meta.timer_paused) {
    return `cleanup paused while occupied • idle window ${ttlMinutes}m`;
  }
  const initialRemaining = (meta.expires_in_seconds === null || meta.expires_in_seconds === undefined) ? null : Number(meta.expires_in_seconds);
  if (initialRemaining === null || Number.isNaN(initialRemaining)) return `cleanup idle window ${ttlMinutes}m`;
  const loadedAt = Number(meta._customExpiryLoadedAt || Date.now()) || Date.now();
  const elapsed = Math.max(0, Math.floor((Date.now() - loadedAt) / 1000));
  const remaining = Math.max(0, Math.floor(initialRemaining - elapsed));
  if (remaining <= 0 || meta.deletion_state === 'eligible_now') {
    return `cleanup eligible now • idle window ${ttlMinutes}m`;
  }
  return `cleanup: expires in ${rbFormatCustomRoomCountdown(remaining)} • idle window ${ttlMinutes}m`;
}

function rbUpdateCustomRoomCountdowns() {
  try {
    document.querySelectorAll('[data-custom-room-expiry="1"]').forEach((node) => {
      const row = node._rbRoomRef;
      if (!row) return;
      node.textContent = rbRoomMetaText(row);
    });
  } catch {}
}

function rbRoomKindLabel(row) {
  if (!row?.isCustom) return row?.meta?.autosplit_base ? 'Overflow' : 'Official';
  return row.meta?.is_private ? 'Private' : 'Custom';
}

function rbCustomRoomAccessLabel(row) {
  if (!row?.isCustom) return '';
  const role = String(row?.meta?.my_room_role || '').trim().toLowerCase();
  if (rbIsCurrentUserRoomCreator(row?.meta?.created_by) || role === 'owner') return 'Owner';
  if (role === 'moderator') return 'Moderator';
  if (row?.meta?.is_private) return 'Invited';
  return '';
}

function rbCanInviteToCustomRoom(row) {
  if (!row?.isCustom || !row?.meta?.is_private) return false;
  if (rbIsCurrentUserRoomCreator(row?.meta?.created_by)) return true;
  if (!!row?.meta?.can_room_moderate) return true;
  const role = String(row?.meta?.my_room_role || '').trim().toLowerCase();
  return role === 'owner' || role === 'moderator';
}

function rbRoomMetaText(row, countOverride = null) {
  if (!row) return '';
  const cnt = Number(countOverride ?? row.cnt ?? 0) || 0;
  const parts = [`${cnt} online`];
  if (row.full) parts.push('full');
  if (row.locked) parts.push('locked');
  if (row.readonly) parts.push('read-only');
  if (Number(row.slowmode_seconds || 0) > 0) parts.push(`slow ${Number(row.slowmode_seconds || 0)}s`);
  if (row.category && row.subcategory) parts.push(`${row.category} › ${row.subcategory}`);
  if (row.isCustom && row.meta?.created_by) {
    parts.push(rbIsCurrentUserRoomCreator(row.meta.created_by) ? 'by you' : `by ${row.meta.created_by}`);
  }
  const access = (typeof rbCustomRoomAccessLabel === 'function') ? rbCustomRoomAccessLabel(row) : '';
  if (access && access !== 'Owner') parts.push(access.toLowerCase());
  const friendCount = rbSelectedFriendCount(row);
  if (friendCount > 0) parts.push(`${friendCount} friend${friendCount === 1 ? '' : 's'} inside`);
  if (row.unread > 0) parts.push(`${row.unread} unread`);
  const expiryText = rbCustomRoomExpiryText(row);
  if (expiryText) parts.push(expiryText);
  const topic = String(rbRoomTopic(row) || '').trim();
  if (topic && topic !== 'Standard room') parts.push(topic);
  return parts.join(' · ');
}

function rbMakeRoomLi(row) {
  const li = document.createElement('li');
  li.dataset.room = row.name;
  li.dataset.roomKey = row.key;
  li.dataset.custom = row.isCustom ? '1' : '0';
  li.classList.add('rbRoomRow');
  li.classList.add(row.isCustom ? 'is-custom' : 'is-official');
  if (row.isCustom) li.classList.add(row.meta?.is_private ? 'is-private' : 'is-public');
  if (row.cnt > 0) li.classList.add('has-online');
  if (row.locked) li.classList.add('is-locked');
  if (row.readonly) li.classList.add('is-readonly');
  if (Number(row.slowmode_seconds || 0) > 0) li.classList.add('is-slowmode');
  if (row.full) li.classList.add('is-full');
  li.dataset.roomStatus = (typeof rbRoomStatusLabel === 'function') ? rbRoomStatusLabel(row) : '';
  if (row.current) li.classList.add('is-current');
  if (row.favorite) li.classList.add('is-favorite');
  if (rbRoomKey(ROOM_BROWSER.selectedRoom, !!ROOM_BROWSER.selectedRoomIsCustom) === row.key) li.classList.add('active');

  const flags = [];
  if (row.isCustom && row.meta?.is_private) flags.push('Invite-only');
  if (row.meta?.is_18_plus) flags.push('18+');
  if (row.meta?.is_nsfw) flags.push('NSFW');

  const left = document.createElement('div');
  left.className = 'rbItemLeft';

  const icon = document.createElement('div');
  icon.className = 'rbIcon';
  if (row.current) icon.textContent = '💬';
  else if (!row.isCustom) icon.textContent = '#';
  else icon.textContent = row.meta?.is_private ? '🔒' : '🌐';

  const text = document.createElement('div');
  text.className = 'rbItemText';

  const nameRow = document.createElement('div');
  nameRow.className = 'rbItemNameRow';
  const nm = document.createElement('div');
  nm.className = 'rbItemName';
  nm.textContent = row.name;
  nm.title = row.name;
  nameRow.appendChild(nm);

  const tags = document.createElement('div');
  tags.className = 'rbRowTags';
  const tagDefs = [rbRoomKindLabel(row)];
  const accessLabel = (typeof rbCustomRoomAccessLabel === 'function') ? rbCustomRoomAccessLabel(row) : '';
  if (accessLabel) tagDefs.push(accessLabel);
  if (row.full) tagDefs.push('Full');
  if (row.locked) tagDefs.push('Locked');
  if (row.readonly) tagDefs.push('Read-only');
  if (Number(row.slowmode_seconds || 0) > 0) tagDefs.push(`Slow ${Number(row.slowmode_seconds || 0)}s`);
  const featureTags = Array.isArray(row.meta?.tags) ? row.meta.tags.slice(0, 2) : [];
  featureTags.forEach((txt) => tagDefs.push(txt));
  if (Array.isArray(row.meta?.features)) {
    if (row.meta.features.includes('room_radio')) tagDefs.push('Radio');
    if (row.meta.features.includes('watch_party')) tagDefs.push('Watch');
    if (row.meta.features.includes('file_share')) tagDefs.push('Files');
  }
  if (row.current) tagDefs.push('Current');
  if (row.favorite) tagDefs.push('★ Favorite');
  const friendCount = rbSelectedFriendCount(row);
  if (friendCount > 0) tagDefs.push(`${friendCount} friend${friendCount === 1 ? '' : 's'}`);
  if (row.unread > 0) tagDefs.push(`${row.unread} unread`);
  flags.forEach((txt) => tagDefs.push(txt));
  tagDefs.forEach((txt) => {
    const tag = document.createElement('span');
    tag.className = 'rbRowTag';
    if (txt === 'Private' || txt === 'Invite-only' || txt === 'Invited') tag.classList.add('is-private-tag');
    if (txt === 'Custom') tag.classList.add('is-custom-tag');
    if (txt === 'Official') tag.classList.add('is-official-tag');
    if (txt === 'Owner' || txt === 'Moderator') tag.classList.add('is-role-tag');
    if (txt === 'Full' || txt === 'Locked') tag.classList.add('is-blocked-tag');
    if (txt === 'Read-only' || String(txt).startsWith('Slow ')) tag.classList.add('is-policy-tag');
    tag.textContent = txt;
    tags.appendChild(tag);
  });
  if (tags.childNodes.length) nameRow.appendChild(tags);

  const mt = document.createElement('div');
  mt.className = 'rbItemMeta';
  mt.textContent = rbRoomMetaText(row);
  if (row.isCustom && Number(row.meta?.idle_ttl_minutes || 0) > 0) {
    mt.setAttribute('data-custom-room-expiry', '1');
    mt._rbRoomRef = row;
  }

  text.appendChild(nameRow);
  text.appendChild(mt);
  left.appendChild(icon);
  left.appendChild(text);

  const right = document.createElement('div');
  right.className = 'rbBtns';

  if (row.unread > 0) {
    const unread = document.createElement('span');
    unread.className = 'rbBadge rbBadgeUnread';
    unread.textContent = String(row.unread);
    right.appendChild(unread);
  }

  const badge = document.createElement('span');
  badge.className = 'rbBadge rbCountBadge' + (row.cnt <= 0 ? ' zero' : '');
  const dot = document.createElement('span');
  dot.className = 'rbStatusDot';
  dot.setAttribute('aria-hidden', 'true');
  badge.appendChild(dot);
  const countText = document.createElement('span');
  countText.className = 'rbCountText';
  countText.textContent = String(row.cnt);
  badge.appendChild(countText);
  right.appendChild(badge);

  const favBtn = document.createElement('button');
  favBtn.className = 'rbFavBtn';
  favBtn.type = 'button';
  favBtn.title = row.favorite ? 'Remove from favorites' : 'Add to favorites';
  favBtn.setAttribute('aria-label', favBtn.title);
  favBtn.textContent = row.favorite ? '★' : '☆';
  favBtn.addEventListener('click', (e) => {
    e.stopPropagation();
    rbToggleFavoriteRoom(row);
  });
  right.appendChild(favBtn);

  if ((typeof rbCanInviteToCustomRoom === 'function') ? rbCanInviteToCustomRoom(row) : (row.isCustom && row.meta?.is_private && rbIsCurrentUserRoomCreator(row.meta?.created_by))) {
    const inviteBtn = document.createElement('button');
    inviteBtn.className = 'rbInviteBtn';
    inviteBtn.type = 'button';
    inviteBtn.textContent = 'Invite';
    inviteBtn.title = 'Invite someone to this private room';
    inviteBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      rbOpenInviteModal(row.name);
    });
    right.appendChild(inviteBtn);
  }

  const actBtn = document.createElement('button');
  actBtn.className = 'rbJoinBtn';
  actBtn.type = 'button';
  actBtn.textContent = rbActionLabel(row);
  actBtn.addEventListener('click', (e) => {
    e.stopPropagation();
    rbSelectRoom(row, { render: true });
    rbPrimaryActionForRow(row);
  });
  right.appendChild(actBtn);

  li.appendChild(left);
  li.appendChild(right);
  li.addEventListener('click', () => {
    rbSelectRoom(row, { render: false });
    if (typeof rbRoomBrowserOverlayIsOpen === 'function' && rbRoomBrowserOverlayIsOpen()) {
      rbPrimaryActionForRow(row);
    }
  });
  li.addEventListener('dblclick', () => {
    rbSelectRoom(row, { render: false });
    rbPrimaryActionForRow(row);
  });
  return li;
}
