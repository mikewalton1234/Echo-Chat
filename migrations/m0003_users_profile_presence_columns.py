from __future__ import annotations

VERSION = "0003_users_profile_presence_columns"
NAME = "Ensure users profile and presence-history columns exist"
KIND = "python"


def upgrade(conn) -> None:
    from database import ensure_users_profile_columns

    ensure_users_profile_columns(conn, commit=False)
