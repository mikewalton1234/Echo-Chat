from __future__ import annotations

VERSION = "0008_profile_posts_and_featured"
NAME = "Ensure profile post and featured tables exist"
KIND = "python"


def upgrade(conn) -> None:
    from database import ensure_users_profile_columns

    ensure_users_profile_columns()
