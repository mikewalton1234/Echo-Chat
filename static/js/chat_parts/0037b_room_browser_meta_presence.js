function rbRowsForScope() {
  const scope = ROOM_BROWSER.roomScope || 'all';
  const official = rbOfficialRowsForSelection();
  const custom = rbCustomRowsForSelection();
  if (scope === 'official') return { rows: official, sections: [{ key: 'official', label: 'Official rooms', rows: official }] };
  if (scope === 'custom') return { rows: custom, sections: [{ key: 'custom', label: 'Custom rooms', rows: custom }] };
  if (scope === 'current') {
    const roomName = String(UIState.currentRoom || '').trim();
    const roomNameKey = rbRoomNameKey(roomName);
    const storedCurrent = (ROOM_BROWSER.recentRooms || []).find((r) => rbRoomNameKey(r?.name) === roomNameKey)
      || (ROOM_BROWSER.favoriteRooms || []).find((r) => rbRoomNameKey(r?.name) === roomNameKey)
      || (ROOM_BROWSER.customRooms || []).find((r) => rbRoomNameKey(r?.name) === roomNameKey)
      || null;
    const row = roomName ? (rbBuildRow(roomName, {
      isCustom: !!(storedCurrent?.isCustom || storedCurrent?.is_private || (ROOM_BROWSER.selectedRoomIsCustom && rbSameRoomName(ROOM_BROWSER.selectedRoom, roomName))),
      meta: rbSameRoomName(ROOM_BROWSER.selectedRoom, roomName) ? ROOM_BROWSER.selectedRoomMeta : storedCurrent,
      category: storedCurrent?.category || null,
      subcategory: storedCurrent?.subcategory || null,
    }) || rbBuildRow(roomName, { isCustom: false })) : null;
    const rows = row && rbMatchesRoomStatusFilter(row) && rbMatchesRoomSearch(row, ROOM_BROWSER.roomQuery) ? [row] : [];
    return { rows, sections: [{ key: 'current', label: 'Current room', rows }] };
  }
  if (scope === 'recent') {
    let rows = rbResolveStoredRows(ROOM_BROWSER.recentRooms);
    rows = rbApplyQueriesToMixedRows(rows);
    rows.sort((a, b) => (b.recentAt - a.recentAt) || a.name.localeCompare(b.name));
    return { rows, sections: [{ key: 'recent', label: 'Recent rooms', rows }] };
  }
  if (scope === 'favorites') {
    let rows = rbResolveStoredRows(ROOM_BROWSER.favoriteRooms);
    rows = rbApplyQueriesToMixedRows(rows);
    rows.sort((a, b) => a.name.localeCompare(b.name));
    return { rows, sections: [{ key: 'favorites', label: 'Favorite rooms', rows }] };
  }
  if (scope === 'unread') {
    const unreadEntries = Array.from(ROOM_BROWSER.unreadCounts.entries()).filter(([, count]) => Number(count || 0) > 0).map(([name]) => ({ name }));
    let rows = unreadEntries.map((entry) => {
      const entryKey = rbRoomNameKey(entry.name);
      const fav = ROOM_BROWSER.favoriteRooms.find((f) => rbRoomNameKey(f?.name) === entryKey) || null;
      const recent = ROOM_BROWSER.recentRooms.find((f) => rbRoomNameKey(f?.name) === entryKey) || null;
      const custom = ROOM_BROWSER.customRooms.find((f) => rbRoomNameKey(f?.name) === entryKey) || null;
      const stored = fav || recent || custom || null;
      return rbBuildRow(entry.name, {
        isCustom: !!(stored?.isCustom || stored?.is_private),
        meta: stored,
        category: stored?.category || null,
        subcategory: stored?.subcategory || null,
      });
    }).filter(Boolean);
    rows = rbApplyQueriesToMixedRows(rows);
    rows.sort((a, b) => (b.unread - a.unread) || a.name.localeCompare(b.name));
    return { rows, sections: [{ key: 'unread', label: 'Unread rooms', rows }] };
  }
  return {
    rows: official,
    sections: [
      { key: 'official', label: 'Official rooms', rows: official },
    ]
  };
}

function rbRoomTopic(row) {
  if (row?.meta?.autosplit_base) {
    return `Autosplit overflow room for ${row.meta.autosplit_base}; users land here when the main room is full.`;
  }
  const explicit = String(row?.meta?.topic || '').trim();
  if (explicit) return explicit;
  const described = String(row?.meta?.description || '').trim();
  if (described) return described;
  const name = String(row?.name || '').trim();
  const lower = name.toLowerCase();
  const presets = {
    lobby: 'Main public lobby for arrivals, casual chat, and general server traffic.',
    random: 'Off-topic hangout for side conversations, memes, and anything that does not fit elsewhere.',
    support: `Help desk room for troubleshooting ${SERVER_NAME} issues, questions, and setup help.`,
    introductions: 'Meet new users, share a little about yourself, and break the ice.',
  };
  if (presets[lower]) return presets[lower];
  if (row?.isCustom) {
    const owner = row?.meta?.created_by ? `Created by ${row.meta.created_by}. ` : '';
    const privacy = row?.meta?.is_private ? 'Private custom room for invited users. ' : 'Public custom room for user-created discussions. ';
    const age = row?.meta?.is_18_plus ? '18+ access is enabled. ' : '';
    const nsfw = row?.meta?.is_nsfw ? 'Marked NSFW. ' : '';
    const path = (row?.category && row?.subcategory) ? `Filed under ${row.category} › ${row.subcategory}.` : '';
    return `${privacy}${owner}${age}${nsfw}${path}`.trim() || 'User-created custom room.';
  }
  if (row?.category && row?.subcategory) {
    return `Official ${row.subcategory.toLowerCase()} room in ${row.category}.`;
  }
  return `${serverRoomLabel()}.`;
}

function rbRoomActivityLabel(count) {
  const n = Number(count || 0) || 0;
  if (n >= 25) return 'Very active';
  if (n >= 10) return 'Active';
  if (n >= 3) return 'Steady';
  if (n >= 1) return 'Quiet';
  return 'Empty right now';
}

function rbFindRoomMapEntry(mapLike, roomName) {
  if (!(mapLike instanceof Map)) return null;
  const wanted = rbRoomNameKey(roomName);
  if (!wanted) return null;
  if (mapLike.has(roomName)) return { key: roomName, value: mapLike.get(roomName) };
  for (const [candidate, value] of mapLike.entries()) {
    if (rbRoomNameKey(candidate) === wanted) return { key: candidate, value };
  }
  return null;
}

function rbHasOccupantSnapshot(roomName) {
  const key = String(roomName || '').trim();
  if (!key) return false;
  if (rbFindRoomMapEntry(ROOM_BROWSER.roomOccupants, key)) return true;
  if (rbSameRoomName(key, UIState.currentRoom || '')) {
    return !!rbFindRoomMapEntry(UIState.roomUsers, key);
  }
  return false;
}

function rbOccupantsForRoom(roomName) {
  const key = String(roomName || '').trim();
  if (!key) return [];
  const cached = rbFindRoomMapEntry(ROOM_BROWSER.roomOccupants, key);
  if (Array.isArray(cached?.value)) return cached.value;
  if (rbSameRoomName(key, UIState.currentRoom || '')) {
    const live = rbFindRoomMapEntry(UIState.roomUsers, key);
    if (Array.isArray(live?.value)) return live.value;
  }
  return [];
}

function rbFriendOccupantsForRoom(roomName) {
  const friends = (UIState.friendSet instanceof Set) ? UIState.friendSet : new Set();
  return rbOccupantsForRoom(roomName).filter((u) => friends.has(String(u)) && String(u) !== String(currentUser || ''));
}

function rbEnsureOccupantsForRoom(roomLike) {
  const row = roomLike && typeof roomLike === 'object' ? roomLike : rbSelectedRowSnapshot();
  const room = String(row?.name || '').trim();
  if (!room) return;
  if (rbSameRoomName(room, UIState.currentRoom || '')) {
    const liveEntry = rbFindRoomMapEntry(UIState.roomUsers, room);
    if (Array.isArray(liveEntry?.value)) {
      ROOM_BROWSER.roomOccupants.set(room, liveEntry.value);
      ROOM_BROWSER.roomOccupantsMeta.set(rbRoomNameKey(room), Date.now());
      return;
    }
  }
  const lastAt = Number(rbMapGetRoomValue(ROOM_BROWSER.roomOccupantsMeta, rbRoomNameKey(room), 0) || 0) || 0;
  if (rbFindRoomMapEntry(ROOM_BROWSER.roomOccupants, room) && (Date.now() - lastAt) < 20000) return;
  try { socket.emit('get_users_in_room', { room }, () => {}); } catch {}
}

function rbRenderFriendChips(users) {
  const items = Array.isArray(users) ? users : [];
  if (!items.length) return '<div class="rbFriendNone">No friends detected in this room right now.</div>';
  const chips = items.slice(0, 8).map((u) => `<span class="rbFriendChip">👤 ${escapeHtml(String(u || ''))}</span>`).join('');
  const more = items.length > 8 ? `<span class="rbFriendMore">+${items.length - 8} more</span>` : '';
  return `<div class="rbFriendChips">${chips}${more}</div>`;
}

function rbAppendFriendChips(parent, users) {
  const items = Array.isArray(users) ? users : [];
  if (!parent) return;
  if (!items.length) {
    const empty = document.createElement('div');
    empty.className = 'rbFriendNone';
    empty.textContent = 'No friends detected in this room right now.';
    parent.appendChild(empty);
    return;
  }

  const wrap = document.createElement('div');
  wrap.className = 'rbFriendChips';
  items.slice(0, 8).forEach((u) => {
    const chip = document.createElement('span');
    chip.className = 'rbFriendChip';
    chip.textContent = `👤 ${String(u || '')}`;
    wrap.appendChild(chip);
  });
  if (items.length > 8) {
    const more = document.createElement('span');
    more.className = 'rbFriendMore';
    more.textContent = `+${items.length - 8} more`;
    wrap.appendChild(more);
  }
  parent.appendChild(wrap);
}

function rbSelectedFriendCount(row) {
  return rbFriendOccupantsForRoom(row?.name).length;
}

function rbActionLabel(row) {
  return row?.current ? 'Open' : 'Join';
}
