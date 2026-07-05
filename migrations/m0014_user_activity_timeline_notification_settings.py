from __future__ import annotations

VERSION = "0014_user_activity_timeline_notification_settings"
NAME = "Admin user activity timeline and profile notification settings"
KIND = "python"


def upgrade(conn) -> None:
    """Add per-user profile notification preferences.

    The activity timeline itself is assembled from existing audit/session/message/
    profile tables, so only the user-facing notification preferences need new
    persistent schema.
    """

    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS user_profile_notification_settings (
                username              TEXT PRIMARY KEY,
                notify_likes          BOOLEAN NOT NULL DEFAULT TRUE,
                notify_comments       BOOLEAN NOT NULL DEFAULT TRUE,
                notify_admin_notices  BOOLEAN NOT NULL DEFAULT TRUE,
                notify_report_updates BOOLEAN NOT NULL DEFAULT TRUE,
                notify_profile_views  BOOLEAN NOT NULL DEFAULT FALSE,
                notify_friend_posts   BOOLEAN NOT NULL DEFAULT TRUE,
                updated_at            TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_profile_notification_settings_updated
                ON user_profile_notification_settings(updated_at DESC);
            """
        )

