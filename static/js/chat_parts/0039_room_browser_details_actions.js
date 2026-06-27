// Room details panel is intentionally retired. The room browser now keeps
// all user-facing actions on each room row and the Custom Rooms column.
function rbRenderRoomDetails() {
  // Compatibility no-op for older call sites/extensions. Do not render a panel.
}

async function rbJumpToRoomLocation(rowLike) {
  const row = rowLike || rbSelectedRowSnapshot();
  if (!row?.category || !row?.subcategory) return;
  ROOM_BROWSER.selectedCategory = row.category;
  ROOM_BROWSER.selectedSubcategory = row.subcategory;
  ROOM_BROWSER.roomScope = row.isCustom ? 'custom' : 'all';
  rbRenderCategoryTree();
  await rbRefreshLists();
  rbSelectRoom(row, { render: true, syncCategory: true });
}

function rbCanStartRoomActivation(rowLike) {
  const row = rowLike || rbSelectedRowSnapshot();
  if (!row?.name) return false;
  const key = rbRoomKey(row.name, !!row.isCustom);
  const now = Date.now();
  const last = ROOM_BROWSER._lastRoomActivation || { key: '', at: 0 };
  if (last.key === key && (now - Number(last.at || 0)) < 1200) return false;
  ROOM_BROWSER._lastRoomActivation = { key, at: now };
  return true;
}

async function rbPrimaryActionForRow(rowLike) {
  const row = rowLike || rbSelectedRowSnapshot();
  if (!row?.name) return;
  if (!rbCanStartRoomActivation(row)) return;
  if (row.current) {
    // A tab restore or transient reconnect can leave the local browser thinking
    // it is still in the room while the server-side Socket.IO membership was
    // lost. Use the normal join path even for the current row so the roster is
    // re-asserted before opening the room pane.
    const res = await joinRoom(row.name, { silent: true, restore: true, rosterHeal: true, row });
    openRoomEmbedded(res?.room || row.name);
    rbClearUnread(res?.room || row.name);
    rbRenderRoomLists();
    rbClosePopoutAfterRoomChoice();
    return;
  }
  const res = await joinRoom(row.name, { row });
  if (res?.success) {
    rbRememberRecentRoom({ ...row, name: res?.room || row.name });
    rbClearUnread(res?.room || row.name);
    if (row.category && row.subcategory) {
      ROOM_BROWSER.selectedCategory = row.category;
      ROOM_BROWSER.selectedSubcategory = row.subcategory;
      rbRenderCategoryTree();
    }
    rbSetSelectedRow({ ...row, name: res?.room || row.name, current: true });
    rbRenderRoomLists();
    rbClosePopoutAfterRoomChoice();
  }
}

async function rbRefreshLists() {
  await rbLoadCounts();
  await rbLoadCustomRooms();
  rbRenderRoomLists();
}
