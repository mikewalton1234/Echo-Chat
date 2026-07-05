from __future__ import annotations

VERSION = "0020_admin_rbac_hardening"
NAME = "Admin RBAC permission hardening and backfill"
KIND = "python"


DEFAULT_PERMISSIONS = [
    "admin:basic",
    "admin:settings",
    "admin:audit",
    "admin:test_lab",
    "admin:create_user",
    "admin:delete_user",
    "admin:set_recovery_pin",
    "admin:set_user_status",
    "admin:set_user_quota",
    "admin:revoke_2fa",
    "admin:broadcast",
    "admin:assign_role",
    "admin:manage_roles",
    "admin:ban_ip",
    "admin:reset_password",
    "admin:logout_user",
    "moderation:mute_user",
    "moderation:kick_user",
    "moderation:ban_room",
    "moderation:suspend_user",
    "moderation:shadowban",
    "room:lock",
    "room:readonly",
    "room:clear",
    "room:delete",
    "profile:moderate",
    "user:delete_self",
    "user:edit_profile",
]

MODERATOR_PERMISSIONS = [
    "moderation:mute_user",
    "moderation:kick_user",
    "moderation:ban_room",
    "room:readonly",
    "room:clear",
    "profile:moderate",
]

VIEWER_PERMISSIONS = ["user:edit_profile"]


def _table_exists(cur, table_name: str) -> bool:
    cur.execute("SELECT to_regclass(%s);", (f"public.{table_name}",))
    row = cur.fetchone()
    return bool(row and row[0])


def _column_exists(cur, table_name: str, column_name: str) -> bool:
    cur.execute(
        """
        SELECT 1
          FROM information_schema.columns
         WHERE table_schema = 'public'
           AND table_name = %s
           AND column_name = %s
         LIMIT 1;
        """,
        (table_name, column_name),
    )
    return cur.fetchone() is not None


def _ensure_role_permissions(cur, role_name: str, permissions: list[str]) -> None:
    cur.execute("SELECT id FROM roles WHERE name = %s;", (role_name,))
    row = cur.fetchone()
    if not row:
        return
    role_id = row[0]
    for permission in permissions:
        cur.execute("SELECT id FROM permissions WHERE name = %s;", (permission,))
        prow = cur.fetchone()
        if not prow:
            continue
        cur.execute(
            """
            INSERT INTO role_permissions (role_id, permission_id)
            VALUES (%s, %s)
            ON CONFLICT (role_id, permission_id) DO NOTHING;
            """,
            (role_id, prow[0]),
        )


def upgrade(conn) -> None:
    with conn.cursor() as cur:
        required_tables = {"roles", "permissions", "role_permissions", "user_roles"}
        if not all(_table_exists(cur, table) for table in required_tables):
            # Baseline migration handles first creation. This migration is a
            # convergence/backfill layer for databases that already have RBAC.
            return

        for role_name in ("admin", "moderator", "viewer"):
            cur.execute("INSERT INTO roles (name) VALUES (%s) ON CONFLICT (name) DO NOTHING;", (role_name,))

        for permission in DEFAULT_PERMISSIONS:
            cur.execute("INSERT INTO permissions (name) VALUES (%s) ON CONFLICT (name) DO NOTHING;", (permission,))

        _ensure_role_permissions(cur, "admin", DEFAULT_PERMISSIONS)
        _ensure_role_permissions(cur, "moderator", MODERATOR_PERMISSIONS)
        _ensure_role_permissions(cur, "viewer", VIEWER_PERMISSIONS)

        if _table_exists(cur, "users") and _column_exists(cur, "users", "is_admin"):
            # Preserve legacy setup/adminctl users: if a user was marked admin
            # before RBAC was repaired, give them the actual RBAC admin role.
            cur.execute(
                """
                INSERT INTO user_roles (user_id, role_id)
                SELECT u.id, r.id
                  FROM users u
                  JOIN roles r ON r.name = 'admin'
                 WHERE COALESCE(u.is_admin, FALSE) = TRUE
                ON CONFLICT (user_id, role_id) DO NOTHING;
                """
            )

            # Keep the legacy UI convenience column in sync with effective RBAC.
            cur.execute(
                """
                UPDATE users u
                   SET is_admin = EXISTS (
                        SELECT 1
                          FROM user_roles ur
                          JOIN role_permissions rp ON rp.role_id = ur.role_id
                          JOIN permissions p ON p.id = rp.permission_id
                         WHERE ur.user_id = u.id
                           AND p.name = 'admin:basic'
                   )
                 WHERE u.is_admin IS DISTINCT FROM EXISTS (
                        SELECT 1
                          FROM user_roles ur
                          JOIN role_permissions rp ON rp.role_id = ur.role_id
                          JOIN permissions p ON p.id = rp.permission_id
                         WHERE ur.user_id = u.id
                           AND p.name = 'admin:basic'
                   );
                """
            )
