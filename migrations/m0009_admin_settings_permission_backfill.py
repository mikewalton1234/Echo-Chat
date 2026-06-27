from __future__ import annotations

VERSION = "0009_admin_settings_permission_backfill"
NAME = "Backfill admin settings permission into existing RBAC tables"
KIND = "python"


def upgrade(conn) -> None:
    """Ensure upgraded databases grant settings/config permission to admins.

    The beta.81 code introduced `admin:settings` and changed several admin
    settings endpoints to require it. Fresh databases got the permission through
    the baseline seed path, but databases that already had migration 0001 marked
    as applied did not rerun the baseline seed. This migration is intentionally
    idempotent so beta.80/beta.81/beta.82/beta.83/beta.84 installs converge.
    """
    with conn.cursor() as cur:
        cur.execute("INSERT INTO roles (name) VALUES (%s) ON CONFLICT (name) DO NOTHING;", ("admin",))
        cur.execute("INSERT INTO permissions (name) VALUES (%s) ON CONFLICT (name) DO NOTHING;", ("admin:settings",))
        cur.execute("INSERT INTO permissions (name) VALUES (%s) ON CONFLICT (name) DO NOTHING;", ("admin:basic",))
        cur.execute("INSERT INTO permissions (name) VALUES (%s) ON CONFLICT (name) DO NOTHING;", ("admin:manage_roles",))
        cur.execute(
            """
            INSERT INTO role_permissions (role_id, permission_id)
            SELECT r.id, p.id
              FROM roles r
              JOIN permissions p ON p.name IN (%s, %s, %s)
             WHERE r.name = %s
            ON CONFLICT (role_id, permission_id) DO NOTHING;
            """,
            ("admin:basic", "admin:settings", "admin:manage_roles", "admin"),
        )
    conn.commit()
