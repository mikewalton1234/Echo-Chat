from __future__ import annotations

VERSION = "0002_users_security_columns"
NAME = "Ensure users security columns for login and account security"
KIND = "python"


def upgrade(conn) -> None:
    from database import ensure_users_security_columns, ensure_user_verified_column

    ensure_users_security_columns()
    ensure_user_verified_column()
