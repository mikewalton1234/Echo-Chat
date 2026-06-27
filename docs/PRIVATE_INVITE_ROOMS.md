# Private / Invite-only custom rooms

Echo-Chat treats custom rooms created as private as invite-only rooms.

## Visibility

Invite-only rooms are hidden from global room lists unless the caller is one of these:

- the room creator
- an invited user
- a persisted private-room member from a prior successful invited join

This applies to both `/api/rooms` and the Socket.IO `get_rooms` list. The category-specific custom-room browser uses the same visibility model.

## Joining

Direct room joins still check server-side access. Typing or modifying a client to request the room name does not bypass the invite gate.

Custom rooms are not autoscaled. That prevents a private room from being rerouted to an automatically-created shard that would not carry the original room privacy metadata.

## Legacy cleanup

The old public `/upload` compatibility route remains registered only to return a clear `410` response. Legacy/global torrent download escape hatches are no longer emitted by new setup/admin UI and are hard-disabled at runtime.

## Room-scoped owner moderation

When a user creates a custom room, Echo-Chat records that creator as the room `owner` in `custom_room_members`. This is a room-scoped role only. It does **not** grant server admin permissions, access to the Admin Panel, or moderation power in any other room.

The owner can right-click a user in that room's Users panel and choose **Kick from this room**. For private rooms, that kick also removes the kicked user's pending invite and persisted private-room membership so they cannot immediately rejoin unless invited again. Public custom-room kicks remove the active room session only.

Room owner tools are hidden for users who are not the room owner or a room moderator, and server-side Socket.IO enforcement still checks the room role before kicking anyone.
## Embedded room owner/moderator tools

Room-scoped moderation should stay visually attached to the room. Echo-Chat embeds the creator/moderator controls in the active room's Users pane as **Room tools** instead of opening a detached admin-style window. The panel only appears for the custom-room owner or room moderator in that specific room. Selecting a user enables **Kick from this room** when the target can be kicked; the right-click action remains as a shortcut.

These controls do not grant Admin Panel access or global moderation powers.

## Beta 166 hardening

- Private-room access is now owner/invite-grant based. Old member rows that do not have a room role or `invited_by` value are ignored so a user cannot re-enter only because an older build accidentally stored a stale membership row.
- Generated shards of private custom rooms, for example `Room (2)`, are hidden and rejected. Invite-only rooms do not autoscale or expose generated sub-room entry points.
- Accepted invites persist the invite source as the member grant, so legitimately invited users can still rejoin after accepting.


## 0.11.0-beta.167 hardening

Private-room access is checked on every important room action, not only on the initial join. If a stale tab/socket is visually inside a private room but the user no longer has owner, moderator, or accepted-member access, Echo-Chat removes that socket from the room and returns `invite_required`. Fake invite acceptance without a pending invite returns 403.

## 0.11.0-beta.254 fake accept guard

F095 confirms that a private-room invitation cannot be forged by posting only a guessed room name to the accept endpoint. The server grants durable access only after it deletes a matching pending invite for the current user joined to a live private custom-room row. Public-room stale rows, deleted-room stale rows, accepted-member replay attempts, and block-state failures do not create `custom_room_members` access.

## 0.11.0-beta.253 invite lifecycle

Private-room invites have a strict pending → accepted/declined lifecycle:

- **Send**: the inviter must already have accepted entry access to the private room. Sending a duplicate pending invite refreshes the pending invite instead of creating a second row.
- **List**: the invite bubble shows only pending private-room invites for existing private custom rooms. Users who already accepted access are filtered out of the pending invite list.
- **Accept**: accepting a pending invite removes the pending row and writes `custom_room_members` before the browser attempts to join the room.
- **Decline**: declining removes the pending row and does not create membership.

Pending invite rows make the private room visible enough for the invite UI, but they do not grant direct room-entry access until accepted.

## Persisted membership after accept

F096 confirms that accepted private-room membership survives refresh, reconnect, and fresh Socket.IO sessions. After accept succeeds, the pending invite row is removed and the durable `custom_room_members` row becomes the source of truth for private-room visibility and entry. REST global room lists, category-scoped custom-room lists, and Socket.IO join checks all use that persisted member grant.

F097 confirms that kicking a private-room member removes both durable access sources: any pending `custom_room_invites` row and any accepted `custom_room_members` row. Revocation is case-insensitive for room names and usernames, the active socket target is matched case-insensitively, and later room actions must pass the same private-room access gate before history, message, typing, reaction, poll, wave, link, media, or rejoin behavior continues.

## 0.11.0-beta.259 right-click room kick hardening

F101 confirms that the right-click **Kick from this room** shortcut is only a scoped custom-room moderation shortcut. The browser shows it only from the active room user list when live policy says the signed-in user can moderate that custom room, the target is present in the room roster, and the target is not self, blocked, or the room owner. The action still calls the server-side `room_kick_user` handler, so private-room revocation and role hierarchy remain enforced server-side.

## 0.11.0-beta.258 moderator role and embedded tools hardening

F099 confirms that a persisted `custom_room_members.role='moderator'` grants room-scoped moderation only for that custom room. Moderator role lookup is normalized and case-insensitive, room-role rank is enforced as `owner > moderator > member`, and room moderators cannot kick the room owner or another same/higher-ranked room role. This does not grant Admin Panel access or global moderation.

F100 confirms that owner/moderator controls are embedded in the active room Users pane instead of opening a detached admin-style window. The panel only appears when live room policy says the user can moderate that custom room, and the panel/right-click kick affordances use case-insensitive self and owner checks.

## 0.11.0-beta.257 creator owner-role hardening

F098 confirms that the custom-room creator is assigned the room-scoped `owner` role when the room is created. That role is scoped only to the created custom room; it does not grant Admin Panel access or global moderation. Owner-role lookup and repair now use case-insensitive room/user matching, and membership writes canonicalize against the stored `custom_rooms` row so refresh, reconnect, auto-join, or harmless casing drift does not split or lose the creator's owner status.



### F102/F103 server-side room kick enforcement

F102 confirms that `room_kick_user` is a server-enforced active-room moderation endpoint. The actor must be live in the room, pass room-scoped or global kick authority, target a user who is currently connected to that same room, and pass the room-control rate limit before any force-leave or private-room access revocation occurs. This keeps a forged socket payload from revoking an offline member's durable private-room access; member revocation remains a separate planned manager flow.

F103 confirms that room owners cannot kick themselves. The self-kick denial is case-insensitive and runs before the global moderation permission override, so an owner/admin cannot accidentally remove their own room owner access through the room kick path.

## 0.11.0-beta.261 member manager/revoke access

F104 adds a real private-room member manager instead of relying on live kicks as the only removal path. The custom-room owner can open **Room tools → Manage** inside the active room Users pane to review accepted members and pending invites. Revoking a user removes both their pending `custom_room_invites` row and accepted `custom_room_members` row, then forces any live socket for that user out of the room.

This durable revoke path is owner-only. Room moderators can still use room-scoped live kick where allowed by role hierarchy, but they cannot remove offline/private-room membership grants.
