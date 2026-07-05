from __future__ import annotations

VERSION = "0015_users_email_encrypted_columns"
NAME = "Encrypted-at-rest user email lookup columns"
KIND = "python"


def upgrade(conn) -> None:
    """Add email_hash/email_encrypted columns for encrypted email storage."""
    with conn.cursor() as cur:
        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS email_hash TEXT;")
        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS email_encrypted TEXT;")
        cur.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS users_email_hash_unique
                ON users (email_hash)
             WHERE email_hash IS NOT NULL AND BTRIM(email_hash) <> '';
            """
        )
