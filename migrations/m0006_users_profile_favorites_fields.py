from __future__ import annotations

VERSION = "0006_users_profile_favorites_fields"
NAME = "Ensure users favorite profile fields exist"
KIND = "python"


def upgrade(conn) -> None:
    from database import ensure_users_profile_columns

    ensure_users_profile_columns()
