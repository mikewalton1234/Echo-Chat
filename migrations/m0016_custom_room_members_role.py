from __future__ import annotations

VERSION = "0016_custom_room_members_role"
NAME = "Ensure custom-room member room-scoped role column"
KIND = "python"


def upgrade(conn) -> None:
    """Add the room-scoped role column for existing custom_room_members tables.

    Beta 164 introduced room-scoped owner/moderator roles. Fresh databases get
    the column from the bootstrap schema, but long-lived beta databases may have
    migration 0001 already applied from an older build and therefore never rerun
    the updated bootstrap helper. This migration repairs those databases without
    relying on a restart-time best-effort helper.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS custom_room_members (
                id           SERIAL PRIMARY KEY,
                room_name    TEXT NOT NULL,
                member_user  TEXT NOT NULL,
                invited_by   TEXT,
                role         TEXT NOT NULL DEFAULT 'member',
                joined_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                UNIQUE(room_name, member_user)
            );
            """
        )
        cur.execute(
            """
            ALTER TABLE custom_room_members
            ADD COLUMN IF NOT EXISTS role TEXT NOT NULL DEFAULT 'member';
            """
        )
        cur.execute(
            """
            UPDATE custom_room_members
               SET role = 'member'
             WHERE role IS NULL OR BTRIM(role) = '';
            """
        )
        cur.execute(
            """
            DO $$
            BEGIN
                IF to_regclass('public.custom_rooms') IS NOT NULL THEN
                    UPDATE custom_room_members m
                       SET role = 'owner'
                      FROM custom_rooms cr
                     WHERE LOWER(BTRIM(cr.name)) = LOWER(BTRIM(m.room_name))
                       AND LOWER(BTRIM(cr.created_by)) = LOWER(BTRIM(m.member_user))
                       AND LOWER(COALESCE(m.role, '')) <> 'owner';
                END IF;
            END $$;
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_custom_room_members_user
                ON custom_room_members(member_user);
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_custom_room_members_room
                ON custom_room_members(room_name);
            """
        )
