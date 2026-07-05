from __future__ import annotations

VERSION = "0004_users_account_status_column"
NAME = "Ensure users account status column exists"
KIND = "python"


def upgrade(conn) -> None:
    from database import ensure_users_profile_columns

    ensure_users_profile_columns(conn, commit=False)
