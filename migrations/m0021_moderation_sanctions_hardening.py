from __future__ import annotations

VERSION = "0021_moderation_sanctions_hardening"
NAME = "Moderation sanctions casefold and active lookup hardening"
KIND = "python"


def _table_exists(cur, table_name: str) -> bool:
    cur.execute("SELECT to_regclass(%s);", (f"public.{table_name}",))
    row = cur.fetchone()
    return bool(row and row[0])


def upgrade(conn) -> None:
    with conn.cursor() as cur:
        if not _table_exists(cur, "user_sanctions"):
            return

        # Keep arbitrary room_ban:<room> sanction types supported, but normalize
        # the command portion so runtime checks are deterministic.
        cur.execute(
            """
            UPDATE user_sanctions
               SET sanction_type = LOWER(BTRIM(sanction_type))
             WHERE sanction_type IS DISTINCT FROM LOWER(BTRIM(sanction_type));
            """
        )

        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_user_sanctions_user_type_active
                ON user_sanctions (LOWER(username), sanction_type, expires_at, created_at DESC);
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_user_sanctions_type_active
                ON user_sanctions (sanction_type, expires_at, created_at DESC);
            """
        )
