from __future__ import annotations

VERSION = "0010_profile_post_engagement"
NAME = "Ensure profile post reactions and comments exist"
KIND = "python"


def upgrade(conn) -> None:
    from database import ensure_profile_post_engagement_schema

    ensure_profile_post_engagement_schema()
