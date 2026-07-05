from __future__ import annotations

VERSION = "0022_social_block_compatibility"
NAME = "Backfill legacy blocked_users rows into blocks"
KIND = "python"


def _table_exists(cur, table_name: str) -> bool:
    cur.execute("SELECT to_regclass(%s);", (f"public.{table_name}",))
    row = cur.fetchone()
    return bool(row and row[0])


def upgrade(conn) -> None:
    with conn.cursor() as cur:
        if not (_table_exists(cur, "blocked_users") and _table_exists(cur, "blocks") and _table_exists(cur, "users")):
            return
        cur.execute(
            """
            INSERT INTO blocks (blocker, blocked)
            SELECT blocker_user.username, blocked_user.username
              FROM blocked_users legacy
              JOIN users blocker_user ON blocker_user.id = legacy.user_id
              JOIN users blocked_user ON blocked_user.id = legacy.blocked_id
             WHERE blocker_user.username IS NOT NULL
               AND blocked_user.username IS NOT NULL
               AND LOWER(blocker_user.username) <> LOWER(blocked_user.username)
               AND NOT EXISTS (
                    SELECT 1 FROM blocks b
                     WHERE LOWER(b.blocker) = LOWER(blocker_user.username)
                       AND LOWER(b.blocked) = LOWER(blocked_user.username)
               );
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_blocks_lower_pair_compat
                ON blocks (LOWER(BTRIM(blocker)), LOWER(BTRIM(blocked)));
            """
        )
