from __future__ import annotations

VERSION = "0007_users_recent_room_sharing"
NAME = "Ensure users recent room sharing fields exist"
KIND = "python"


def upgrade(conn) -> None:
    from database import ensure_users_profile_columns

    ensure_users_profile_columns(conn, commit=False)
