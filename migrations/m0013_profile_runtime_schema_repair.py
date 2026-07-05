from __future__ import annotations

VERSION = "0013_profile_runtime_schema_repair"
NAME = "Profile runtime schema repair after beta 109"
KIND = "python"


def _existing_columns(cur, table_name: str) -> set[str]:
    cur.execute(
        """
        SELECT column_name
          FROM information_schema.columns
         WHERE table_schema = 'public'
           AND table_name = %s;
        """,
        (table_name,),
    )
    return {str(row[0]) for row in (cur.fetchall() or [])}


def _add_column_if_missing(cur, table_name: str, column_name: str, ddl: str) -> None:
    if column_name not in _existing_columns(cur, table_name):
        cur.execute(ddl)


def upgrade(conn) -> None:
    """Repair profile schema without mutating already-applied migration 0012.

    Beta 109 fixed the body of migration 0012 after some databases had already
    recorded the original 0012 checksum. That correctly triggered the tracked
    migration checksum guard on startup. This follow-up migration keeps 0012
    immutable and performs the missing idempotent schema repair under a new
    version number.
    """

    with conn.cursor() as cur:
        _add_column_if_missing(
            cur,
            "users",
            "profile_post_default_visibility",
            "ALTER TABLE users ADD COLUMN profile_post_default_visibility TEXT NOT NULL DEFAULT 'friends';",
        )
        cur.execute(
            """
            UPDATE users
               SET profile_post_default_visibility = 'friends'
             WHERE profile_post_default_visibility IS NULL
                OR BTRIM(profile_post_default_visibility) = '';
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS profile_posts (
                id               SERIAL PRIMARY KEY,
                author_username  TEXT NOT NULL,
                body             TEXT,
                visibility       TEXT NOT NULL DEFAULT 'friends',
                image_url        TEXT,
                gif_url          TEXT,
                link_url         TEXT,
                is_pinned        BOOLEAN NOT NULL DEFAULT FALSE,
                is_featured      BOOLEAN NOT NULL DEFAULT FALSE,
                created_at       TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at       TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
                deleted_at       TIMESTAMP WITH TIME ZONE,
                edited_at        TIMESTAMP WITH TIME ZONE,
                edit_count       INTEGER NOT NULL DEFAULT 0,
                moderated_by     TEXT,
                moderated_reason TEXT,
                moderated_at     TIMESTAMP WITH TIME ZONE
            );
            """
        )
        for column_name, ddl in {
            "link_url": "ALTER TABLE profile_posts ADD COLUMN link_url TEXT;",
            "deleted_at": "ALTER TABLE profile_posts ADD COLUMN deleted_at TIMESTAMP WITH TIME ZONE;",
            "edited_at": "ALTER TABLE profile_posts ADD COLUMN edited_at TIMESTAMP WITH TIME ZONE;",
            "edit_count": "ALTER TABLE profile_posts ADD COLUMN edit_count INTEGER NOT NULL DEFAULT 0;",
            "moderated_by": "ALTER TABLE profile_posts ADD COLUMN moderated_by TEXT;",
            "moderated_reason": "ALTER TABLE profile_posts ADD COLUMN moderated_reason TEXT;",
            "moderated_at": "ALTER TABLE profile_posts ADD COLUMN moderated_at TIMESTAMP WITH TIME ZONE;",
        }.items():
            _add_column_if_missing(cur, "profile_posts", column_name, ddl)

        cur.execute("CREATE INDEX IF NOT EXISTS idx_profile_posts_author_created ON profile_posts(author_username, created_at DESC);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_profile_posts_author_featured ON profile_posts(author_username, is_featured, created_at DESC);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_profile_posts_author_pinned ON profile_posts(author_username, is_pinned, created_at DESC);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_profile_posts_moderation ON profile_posts(deleted_at, moderated_at, updated_at DESC);")

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS profile_post_reactions (
                post_id    INTEGER NOT NULL REFERENCES profile_posts(id) ON DELETE CASCADE,
                username   TEXT NOT NULL,
                reaction   TEXT NOT NULL DEFAULT 'like',
                created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (post_id, username, reaction)
            );
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_profile_post_reactions_user ON profile_post_reactions(username, created_at DESC);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_profile_post_reactions_post ON profile_post_reactions(post_id, reaction);")

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS profile_post_comments (
                id              SERIAL PRIMARY KEY,
                post_id         INTEGER NOT NULL REFERENCES profile_posts(id) ON DELETE CASCADE,
                author_username TEXT NOT NULL,
                body            TEXT NOT NULL,
                created_at      TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at      TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
                deleted_at      TIMESTAMP WITH TIME ZONE,
                deleted_by      TEXT,
                deleted_reason  TEXT
            );
            """
        )
        _add_column_if_missing(cur, "profile_post_comments", "deleted_by", "ALTER TABLE profile_post_comments ADD COLUMN deleted_by TEXT;")
        _add_column_if_missing(cur, "profile_post_comments", "deleted_reason", "ALTER TABLE profile_post_comments ADD COLUMN deleted_reason TEXT;")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_profile_post_comments_post_created ON profile_post_comments(post_id, created_at DESC, id DESC) WHERE deleted_at IS NULL;")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_profile_post_comments_author_created ON profile_post_comments(author_username, created_at DESC) WHERE deleted_at IS NULL;")

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS profile_post_reports (
                id                SERIAL PRIMARY KEY,
                reporter_username TEXT NOT NULL,
                post_id           INTEGER NOT NULL REFERENCES profile_posts(id) ON DELETE CASCADE,
                comment_id        INTEGER REFERENCES profile_post_comments(id) ON DELETE SET NULL,
                target_username   TEXT NOT NULL,
                reason            TEXT NOT NULL DEFAULT 'other',
                details           TEXT,
                status            TEXT NOT NULL DEFAULT 'open',
                reviewed_by       TEXT,
                reviewed_at       TIMESTAMP WITH TIME ZONE,
                action_taken      TEXT,
                created_at        TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at        TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_profile_post_reports_status_created ON profile_post_reports(status, created_at DESC);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_profile_post_reports_post_created ON profile_post_reports(post_id, created_at DESC);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_profile_post_reports_target_created ON profile_post_reports(target_username, created_at DESC);")
        cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_profile_post_reports_open_reporter_target ON profile_post_reports(reporter_username, post_id, COALESCE(comment_id, 0)) WHERE status = 'open';")

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS user_profile_badges (
                id          SERIAL PRIMARY KEY,
                username    TEXT NOT NULL,
                badge_key   TEXT NOT NULL,
                label       TEXT NOT NULL,
                assigned_by TEXT,
                reason      TEXT,
                created_at  TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(username, badge_key)
            );
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_user_profile_badges_username ON user_profile_badges(username, created_at DESC);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_user_profile_badges_key ON user_profile_badges(badge_key);")

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS notifications (
                id            SERIAL PRIMARY KEY,
                user_id       INTEGER NOT NULL,
                notification  TEXT NOT NULL,
                type          TEXT,
                is_read       BOOLEAN DEFAULT FALSE,
                timestamp     TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_profile_notifications_user_unread ON notifications(user_id, is_read, timestamp DESC) WHERE type LIKE 'profile_post_%';")

