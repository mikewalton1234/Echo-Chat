// Embedded room-scoped moderation tools
// Custom-room owners/moderators get controls inside the active room Users pane.
// This keeps room-owner powers visually scoped to the room instead of creating
// a detached admin-style moderation window.
(function () {
  function byId(id) {
    try { return document.getElementById(id); } catch { return null; }
  }

  function clean(value) {
    return String(value || '').trim();
  }

  function sameUser(a, b) {
    return clean(a).toLowerCase() === clean(b).toLowerCase();
  }

  function currentRoomForPanel(roomOverride) {
    try {
      return clean(roomOverride || (UIState && (UIState.currentRoom || UIState.roomEmbedRoom)) || '');
    } catch {
      return clean(roomOverride || '');
    }
  }

  function currentUsername() {
    try { return clean(currentUser); } catch {}
    try { return clean(window.CURRENT_USER || window.USERNAME); } catch {}
    return '';
  }

  function roomUsersFor(room) {
    try {
      const list = UIState && UIState.roomUsers && UIState.roomUsers.get(clean(room));
      return Array.isArray(list) ? list.map(clean).filter(Boolean) : [];
    } catch {
      return [];
    }
  }

  function selectedRoomUser(room) {
    try {
      const source = clean(UIState && UIState.selectedBuddySource);
      const selected = clean(UIState && UIState.selectedBuddy);
      if (source !== 'room' || !selected) return '';
      const users = roomUsersFor(room);
      if (users.length && !users.some((u) => sameUser(u, selected))) return '';
      return selected;
    } catch {
      return '';
    }
  }

  function roleLabel(policy) {
    const raw = clean(policy && policy.my_room_role).toLowerCase();
    if (raw === 'owner') return 'Owner tools for this room only';
    if (raw === 'moderator') return 'Moderator tools for this room only';
    return 'Room-scoped moderation';
  }

  function canManageMembers(policy) {
    return !!(policy && policy.is_custom_room && policy.is_private_room && clean(policy.my_room_role).toLowerCase() === 'owner');
  }

  function canKickTarget(policy, target) {
    const me = currentUsername();
    const owner = clean(policy && policy.room_owner);
    if (!target || !policy || !policy.can_room_moderate) return false;
    if (sameUser(target, me)) return false;
    if (owner && sameUser(target, owner)) return false;
    return true;
  }

  function setHidden(el, hidden) {
    if (!el) return;
    el.classList.toggle('hidden', !!hidden);
  }

  async function ecRoomManagerJson(url, opts = {}) {
    const resp = await fetchWithAuth(url, {
      credentials: 'include',
      headers: { 'Content-Type': 'application/json', ...(opts.headers || {}) },
      ...opts,
    }, { retryOn401: true });
    const data = (typeof ecReadApiJson === 'function') ? await ecReadApiJson(resp, {}) : await resp.json().catch(() => ({}));
    if (!resp || !resp.ok) {
      const msg = (typeof ecApiErrorMessage === 'function') ? ecApiErrorMessage(resp, data, 'Request failed') : (data?.error || data?.msg || 'Request failed');
      throw new Error(msg);
    }
    return data;
  }

  function managerEls() {
    return {
      box: byId('roomEmbedMemberManager'),
      list: byId('roomEmbedMemberManagerList'),
      status: byId('roomEmbedMemberManagerStatus'),
      manageBtn: byId('btnRoomModManage'),
      refreshBtn: byId('btnRoomModMembersRefresh'),
    };
  }

  function setManagerStatus(message, kind) {
    const { status } = managerEls();
    if (!status) return;
    status.textContent = message || '';
    status.dataset.kind = kind || '';
  }

  function renderManagerRows(room, data) {
    const { list } = managerEls();
    if (!list) return;
    list.replaceChildren();
    const rows = [];
    (data?.members || []).forEach((row) => rows.push({ ...row, status: 'member' }));
    (data?.pending_invites || []).forEach((row) => rows.push({ ...row, status: 'pending' }));
    if (!rows.length) {
      const li = document.createElement('li');
      li.className = 'roomEmbedMemberManagerEmpty muted';
      li.textContent = 'No members or pending invites found.';
      list.appendChild(li);
      return;
    }
    rows.forEach((row) => {
      const username = clean(row.username);
      if (!username) return;
      const li = document.createElement('li');
      li.className = 'roomEmbedMemberManagerRow';
      li.dataset.username = username;
      li.dataset.status = clean(row.status || 'member');

      const meta = document.createElement('div');
      meta.className = 'roomEmbedMemberManagerMeta';
      const name = document.createElement('strong');
      name.textContent = username;
      const detail = document.createElement('span');
      const role = clean(row.role || row.status || 'member').toLowerCase();
      const label = row.status === 'pending' ? 'pending invite' : role;
      detail.textContent = row.invited_by ? `${label} · invited by ${row.invited_by}` : label;
      meta.appendChild(name);
      meta.appendChild(detail);
      li.appendChild(meta);

      const btn = document.createElement('button');
      btn.className = 'miniBtn danger roomEmbedMemberRevokeBtn';
      btn.type = 'button';
      btn.textContent = row.status === 'pending' ? 'Cancel' : 'Revoke';
      btn.disabled = !row.can_revoke;
      btn.title = row.can_revoke ? `Revoke ${username}'s private-room access` : 'The room owner cannot be revoked here';
      btn.addEventListener('click', () => ecRoomMemberManagerRevoke(room, username));
      li.appendChild(btn);
      list.appendChild(li);
    });
  }

  async function ecRoomMemberManagerRefresh(roomOverride) {
    const room = currentRoomForPanel(roomOverride);
    const policy = room && typeof getRoomPolicy === 'function' ? getRoomPolicy(room) : null;
    const { box, refreshBtn } = managerEls();
    if (!room || !canManageMembers(policy)) {
      setHidden(box, true);
      return;
    }
    if (refreshBtn) refreshBtn.disabled = true;
    setManagerStatus('Loading private-room members…', 'busy');
    try {
      const qs = new URLSearchParams({ room });
      const data = await ecRoomManagerJson(`/api/custom_rooms/members?${qs.toString()}`, { method: 'GET' });
      renderManagerRows(data.room || room, data);
      const total = Number((data.members || []).length || 0) + Number((data.pending_invites || []).length || 0);
      setManagerStatus(`${total} access row${total === 1 ? '' : 's'} shown. Owner-only durable access controls.`, 'ok');
    } catch (e) {
      setManagerStatus(`Could not load members: ${e?.message || e}`, 'error');
    } finally {
      if (refreshBtn) refreshBtn.disabled = false;
    }
  }

  async function ecRoomMemberManagerRevoke(roomOverride, username) {
    const room = currentRoomForPanel(roomOverride);
    const target = clean(username);
    if (!room || !target) return;
    const yes = window.confirm ? window.confirm(`Revoke ${target}'s access to ${room}?`) : true;
    if (!yes) return;
    setManagerStatus(`Revoking ${target}…`, 'busy');
    try {
      const data = await ecRoomManagerJson('/api/custom_rooms/members/revoke', {
        method: 'POST',
        body: JSON.stringify({ room, username: target }),
      });
      if (typeof toast === 'function') toast(`✅ Revoked ${data.username || target} from ${data.room || room}`, 'ok', 4200);
      await ecRoomMemberManagerRefresh(data.room || room);
      try { if (typeof window.getUsersInRoom === 'function') getUsersInRoom(data.room || room); } catch {}
    } catch (e) {
      if (typeof toast === 'function') toast(`❌ Revoke failed: ${e?.message || e}`, 'error', 7000);
      setManagerStatus(`Revoke failed: ${e?.message || e}`, 'error');
    }
  }

  function ecRoomMemberManagerToggle(roomOverride) {
    const room = currentRoomForPanel(roomOverride);
    const policy = room && typeof getRoomPolicy === 'function' ? getRoomPolicy(room) : null;
    const { box } = managerEls();
    if (!box || !canManageMembers(policy)) return;
    const opening = box.classList.contains('hidden');
    setHidden(box, !opening);
    if (opening) ecRoomMemberManagerRefresh(room);
  }

  function ecRoomModeratorPanelSync(roomOverride) {
    const room = currentRoomForPanel(roomOverride);
    const panel = byId('roomEmbedModPanel');
    if (!panel) return;

    const roleEl = byId('roomEmbedModRole');
    const hintEl = byId('roomEmbedModHint');
    const targetWrap = byId('roomEmbedModTarget');
    const targetName = byId('roomEmbedModTargetName');
    const kickBtn = byId('btnRoomModKick');
    const inviteBtn = byId('btnRoomModInvite');
    const { manageBtn, box } = managerEls();

    const policy = room && typeof getRoomPolicy === 'function' ? getRoomPolicy(room) : null;
    const canModerate = !!(policy && policy.can_room_moderate && policy.is_custom_room);
    const canManage = canManageMembers(policy);

    panel.dataset.room = room || '';
    setHidden(panel, !room || !canModerate);
    if (!room || !canModerate) {
      if (kickBtn) kickBtn.disabled = true;
      if (targetName) targetName.textContent = '—';
      if (manageBtn) manageBtn.classList.add('hidden');
      setHidden(box, true);
      setHidden(targetWrap, true);
      return;
    }

    if (roleEl) roleEl.textContent = roleLabel(policy);
    const target = selectedRoomUser(room);
    const canKick = canKickTarget(policy, target);

    if (targetName) targetName.textContent = target || '—';
    setHidden(targetWrap, !target);
    if (kickBtn) {
      kickBtn.disabled = !canKick;
      kickBtn.title = target
        ? (canKick ? `Kick ${target} from ${room}` : 'You cannot kick this user')
        : 'Select a user in the Users list first';
    }
    if (manageBtn) {
      manageBtn.classList.toggle('hidden', !canManage);
      manageBtn.disabled = !canManage;
      manageBtn.title = canManage ? 'Manage private-room members and pending invites' : 'Only the private-room owner can manage members';
    }
    if (!canManage) setHidden(box, true);
    if (hintEl) {
      if (!target) hintEl.textContent = canManage ? 'Select a user to kick, or open Manage for offline member access.' : 'Select a user in this room to moderate them here.';
      else if (!canKick) hintEl.textContent = 'This user cannot be kicked by room-scoped tools.';
      else hintEl.textContent = 'These tools only affect this room. They do not grant global admin access.';
    }
    if (inviteBtn) inviteBtn.title = `Invite a user to ${room}`;
  }

  function ecRoomModeratorKickSelected() {
    const room = currentRoomForPanel();
    const policy = room && typeof getRoomPolicy === 'function' ? getRoomPolicy(room) : null;
    const target = selectedRoomUser(room);
    if (!canKickTarget(policy, target)) {
      if (typeof toast === 'function') toast('Select a kickable user in this room first.', 'warn');
      ecRoomModeratorPanelSync(room);
      return;
    }
    if (typeof kickUserFromCurrentRoom === 'function') {
      kickUserFromCurrentRoom(target, room);
      return;
    }
    try {
      socket.emit('room_kick_user', { room, username: target }, (res) => {
        if (res && res.success) {
          if (typeof toast === 'function') toast(`👢 Kicked ${target} from ${room}`, 'ok', 4200);
          try { if (typeof window.getUsersInRoom === 'function') getUsersInRoom(room); } catch {}
        } else if (typeof toast === 'function') {
          toast(`❌ Kick failed: ${res?.error || 'room kick failed'}`, 'error', 7000);
        }
      });
    } catch (e) {
      if (typeof toast === 'function') toast(`❌ Kick failed: ${e?.message || e}`, 'error', 7000);
    }
  }

  function bindRoomModeratorPanel() {
    const panel = byId('roomEmbedModPanel');
    if (!panel || panel.dataset.boundRoomModeratorPanel === '1') return;
    panel.dataset.boundRoomModeratorPanel = '1';

    const kickBtn = byId('btnRoomModKick');
    if (kickBtn) kickBtn.addEventListener('click', ecRoomModeratorKickSelected);

    const manageBtn = byId('btnRoomModManage');
    if (manageBtn) manageBtn.addEventListener('click', () => ecRoomMemberManagerToggle(currentRoomForPanel()));

    const refreshBtn = byId('btnRoomModMembersRefresh');
    if (refreshBtn) refreshBtn.addEventListener('click', () => ecRoomMemberManagerRefresh(currentRoomForPanel()));

    const inviteBtn = byId('btnRoomModInvite');
    if (inviteBtn) {
      inviteBtn.addEventListener('click', () => {
        if (typeof ecInviteUserToCurrentRoom === 'function') ecInviteUserToCurrentRoom('');
      });
    }

    const users = byId('userList');
    if (users) {
      ['click', 'contextmenu'].forEach((eventName) => {
        users.addEventListener(eventName, (ev) => {
          const li = ev.target && ev.target.closest ? ev.target.closest('#userList li[data-name]') : null;
          if (!li) return;
          setTimeout(() => ecRoomModeratorPanelSync(currentRoomForPanel()), 0);
        });
      });
    }
  }

  function installSocketHooks() {
    try {
      if (!window.socket || socket.__ecRoomModPanelHooks === '1') return;
      socket.__ecRoomModPanelHooks = '1';
      socket.on('room_policy_state', (payload) => {
        const room = clean(payload && payload.room);
        setTimeout(() => ecRoomModeratorPanelSync(room), 0);
      });
      socket.on('room_users', (payload) => {
        const room = typeof payload === 'object' && payload ? clean(payload.room) : currentRoomForPanel();
        setTimeout(() => ecRoomModeratorPanelSync(room), 0);
      });
      socket.on('room_forced_leave', (payload) => {
        const room = clean(payload && payload.room);
        setTimeout(() => ecRoomModeratorPanelSync(room), 0);
      });
      socket.on('room_access_revoked', (payload) => {
        const room = clean(payload && payload.room);
        setTimeout(() => ecRoomModeratorPanelSync(room), 0);
      });
    } catch {}
  }

  function start() {
    bindRoomModeratorPanel();
    installSocketHooks();
    ecRoomModeratorPanelSync(currentRoomForPanel());
  }

  window.ecRoomModeratorPanelSync = ecRoomModeratorPanelSync;
  window.ecRoomModeratorKickSelected = ecRoomModeratorKickSelected;
  window.ecRoomMemberManagerRefresh = ecRoomMemberManagerRefresh;
  window.ecRoomMemberManagerRevoke = ecRoomMemberManagerRevoke;

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start, { once: true });
  } else {
    start();
  }
})();
