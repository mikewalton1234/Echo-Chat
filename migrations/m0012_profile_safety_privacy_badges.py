from __future__ import annotations

VERSION = "0012_profile_safety_privacy_badges"
NAME = "Profile post reporting, room-member privacy, and profile badges"
KIND = "python"


def upgrade(conn) -> None:
    from database import ensure_profile_post_engagement_schema

    ensure_profile_post_engagement_schema()
