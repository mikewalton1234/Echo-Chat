from __future__ import annotations

VERSION = "0019_auth_changed_at"
NAME = "Auth lifecycle changed timestamp"
KIND = "python"


def _table_exists(cur, table_name: str) -> bool:
    cur.execute("SELECT to_regclass(%s);", (f"public.{table_name}",))
    row = cur.fetchone()
    return bool(row and row[0])


def upgrade(conn) -> None:
    with conn.cursor() as cur:
        if _table_exists(cur, "users"):
            cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS auth_changed_at TIMESTAMPTZ NULL;")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_users_auth_changed_at ON users(auth_changed_at DESC);")
