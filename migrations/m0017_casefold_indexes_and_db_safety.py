from __future__ import annotations

VERSION = "0017_casefold_indexes_and_db_safety"
NAME = "Casefold username indexes and DB safety indexes"
KIND = "python"


def _table_exists(cur, table_name: str) -> bool:
    cur.execute("SELECT to_regclass(%s);", (f"public.{table_name}",))
    row = cur.fetchone()
    return bool(row and row[0])


def _column_exists(cur, table_name: str, column_name: str) -> bool:
    cur.execute(
        """
        SELECT 1
          FROM information_schema.columns
         WHERE table_schema='public'
           AND table_name=%s
           AND column_name=%s;
        """,
        (table_name, column_name),
    )
    return cur.fetchone() is not None


def _create_index(cur, ddl: str) -> None:
    cur.execute(ddl)


def _fail_if_casefold_username_duplicates(cur) -> None:
    if not _table_exists(cur, "users"):
        return
    cur.execute(
        """
        SELECT LOWER(BTRIM(username)) AS username_key,
               COUNT(*) AS n,
               ARRAY_AGG(username ORDER BY id) AS usernames
          FROM users
         WHERE username IS NOT NULL AND BTRIM(username) <> ''
         GROUP BY LOWER(BTRIM(username))
        HAVING COUNT(*) > 1
         LIMIT 10;
        """
    )
    rows = cur.fetchall() or []
    if rows:
        examples = "; ".join(f"{r[0]} => {', '.join(map(str, r[2] or []))}" for r in rows)
        raise RuntimeError(
            "Cannot create case-insensitive username uniqueness because duplicates exist. "
            "Run `python tools/db_username_casefold_doctor.py` and rename/merge duplicates first. "
            f"Examples: {examples}"
        )


def upgrade(conn) -> None:
    with conn.cursor() as cur:
        _fail_if_casefold_username_duplicates(cur)

        if _table_exists(cur, "users") and _column_exists(cur, "users", "username"):
            _create_index(
                cur,
                """
                CREATE UNIQUE INDEX IF NOT EXISTS users_username_lower_unique
                ON users (LOWER(BTRIM(username)));
                """,
            )
            _create_index(cur, "CREATE INDEX IF NOT EXISTS idx_users_username_lower ON users (LOWER(BTRIM(username)));" )
            if _column_exists(cur, "users", "email_hash"):
                _create_index(cur, "CREATE INDEX IF NOT EXISTS idx_users_email_hash ON users (email_hash) WHERE email_hash IS NOT NULL AND BTRIM(email_hash) <> '';" )
            if _column_exists(cur, "users", "status"):
                _create_index(cur, "CREATE INDEX IF NOT EXISTS idx_users_status_lower ON users (LOWER(BTRIM(status)));" )

        # Common LOWER(...) lookups used by friends/block/invite/permission paths.
        table_indexes = [
            ("friend_requests", ("to_user", "request_status"), "idx_friend_requests_lower_to_status", "(LOWER(BTRIM(to_user)), request_status)"),
            ("friend_requests", ("from_user", "request_status"), "idx_friend_requests_lower_from_status", "(LOWER(BTRIM(from_user)), request_status)"),
            ("friend_requests", ("from_user", "to_user"), "idx_friend_requests_lower_pair", "(LOWER(BTRIM(from_user)), LOWER(BTRIM(to_user)))"),
            ("blocks", ("blocker", "blocked"), "idx_blocks_lower_pair", "(LOWER(BTRIM(blocker)), LOWER(BTRIM(blocked)))"),
            ("offline_messages", ("receiver", "id"), "idx_offline_messages_lower_receiver_id", "(LOWER(BTRIM(receiver)), id)"),
            ("offline_messages", ("sender", "receiver", "id"), "idx_offline_messages_lower_pair_id", "(LOWER(BTRIM(sender)), LOWER(BTRIM(receiver)), id)"),
            ("private_messages", ("sender", "recipient", "id"), "idx_private_messages_lower_pair_id", "(LOWER(BTRIM(sender)), LOWER(BTRIM(recipient)), id)"),
            ("pending_messages", ("receiver_username", "sender_username", "id"), "idx_pending_messages_lower_pair_id", "(LOWER(BTRIM(receiver_username)), LOWER(BTRIM(sender_username)), id)"),
            ("custom_room_invites", ("room_name", "invited_user"), "idx_custom_room_invites_lower_room_user", "(LOWER(BTRIM(room_name)), LOWER(BTRIM(invited_user)))"),
            ("custom_room_members", ("room_name", "member_user"), "idx_custom_room_members_lower_room_user", "(LOWER(BTRIM(room_name)), LOWER(BTRIM(member_user)))"),
            ("room_invites", ("room_name", "invited_user"), "idx_room_invites_lower_room_user", "(LOWER(BTRIM(room_name)), LOWER(BTRIM(invited_user)))"),
            ("user_recent_rooms", ("username", "joined_at"), "idx_user_recent_rooms_lower_username_joined", "(LOWER(BTRIM(username)), joined_at DESC)"),
            ("profile_posts", ("author_username", "created_at"), "idx_profile_posts_lower_author_created", "(LOWER(BTRIM(author_username)), created_at DESC)"),
            ("profile_post_comments", ("author_username", "created_at"), "idx_profile_post_comments_lower_author_created", "(LOWER(BTRIM(author_username)), created_at DESC)"),
            ("user_profile_badges", ("username", "created_at"), "idx_user_profile_badges_lower_username", "(LOWER(BTRIM(username)), created_at DESC)"),
            ("user_profile_notification_settings", ("username",), "idx_profile_notification_settings_lower_username", "(LOWER(BTRIM(username)))"),
        ]
        for table, columns, index, expr in table_indexes:
            if _table_exists(cur, table) and all(_column_exists(cur, table, c) for c in columns):
                _create_index(cur, f"CREATE INDEX IF NOT EXISTS {index} ON {table} {expr};")

        # Keep route/admin notification reads fast and ensure these tables exist at startup.
        if _table_exists(cur, "user_profile_notification_settings"):
            _create_index(cur, "CREATE INDEX IF NOT EXISTS idx_profile_notification_settings_updated ON user_profile_notification_settings(updated_at DESC);")
        if _table_exists(cur, "notifications"):
            _create_index(cur, "CREATE INDEX IF NOT EXISTS idx_notifications_user_read_ts ON notifications(user_id, is_read, timestamp DESC);")
            _create_index(cur, "CREATE INDEX IF NOT EXISTS idx_profile_notifications_user_unread ON notifications(user_id, is_read, timestamp DESC) WHERE type LIKE 'profile_post_%';")
