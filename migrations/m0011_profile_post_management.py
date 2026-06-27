from __future__ import annotations

VERSION = "0011_profile_post_management"
NAME = "Profile post editing, notifications, and admin moderation controls"
KIND = "python"


def upgrade(conn) -> None:
    from database import ensure_profile_post_engagement_schema

    ensure_profile_post_engagement_schema()
