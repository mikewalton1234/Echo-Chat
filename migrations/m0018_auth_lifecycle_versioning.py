from __future__ import annotations

VERSION = "0018_auth_lifecycle_versioning"
NAME = "Auth lifecycle versioning and session token safety"
KIND = "python"


def _table_exists(cur, table_name: str) -> bool:
    cur.execute("SELECT to_regclass(%s);", (f"public.{table_name}",))
    row = cur.fetchone()
    return bool(row and row[0])


def upgrade(conn) -> None:
    with conn.cursor() as cur:
        if _table_exists(cur, "users"):
            cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS auth_version INTEGER NOT NULL DEFAULT 0;")
            cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS password_changed_at TIMESTAMPTZ NULL;")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_users_auth_version ON users(auth_version);")
        if _table_exists(cur, "auth_sessions"):
            cur.execute("ALTER TABLE auth_sessions ADD COLUMN IF NOT EXISTS auth_version INTEGER NOT NULL DEFAULT 0;")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_auth_sessions_user_version ON auth_sessions(LOWER(BTRIM(username)), auth_version);")
        if _table_exists(cur, "auth_tokens"):
            cur.execute("ALTER TABLE auth_tokens ADD COLUMN IF NOT EXISTS auth_version INTEGER NOT NULL DEFAULT 0;")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_auth_tokens_user_version ON auth_tokens(LOWER(BTRIM(username)), auth_version);")
