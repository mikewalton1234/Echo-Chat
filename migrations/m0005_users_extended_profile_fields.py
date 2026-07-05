from __future__ import annotations

VERSION = "0005_users_extended_profile_fields"
NAME = "Ensure users extended profile fields exist"
KIND = "python"


def upgrade(conn) -> None:
    from database import ensure_users_profile_columns

    ensure_users_profile_columns(conn, commit=False)
