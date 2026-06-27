#!/usr/bin/env python3
"""permissions.py

Role/permission guards for Echo Chat (PostgreSQL).

This module provides:
  - require_admin: lightweight JWT-backed admin guard
  - get_user_permissions: RBAC permission resolution
  - require_permission: declarative RBAC decorator

SQLite support has been removed.
"""

from __future__ import annotations

import functools
import logging
from typing import Callable, Set

from flask import jsonify
from flask_jwt_extended import (
    get_jwt_identity,
    verify_jwt_in_request,
)

from database import get_db


def _safe_verify_jwt(optional: bool = False) -> str | None:
    """Return JWT identity if present/valid, else None."""
    try:
        verify_jwt_in_request(optional=optional)
        return get_jwt_identity()
    except Exception:
        return None


# Explicit RBAC inheritance rules.  These are intentionally conservative:
# a narrow permission never implies a broader/sensitive one such as
# ``admin:settings`` or ``admin:manage_roles``.  Instead, high-risk powers imply
# the lower powers needed to view the admin UI and complete that same workflow.
_PERMISSION_INHERITANCE: dict[str, set[str]] = {
    "admin:settings": {"admin:basic"},
    "admin:assign_role": {"admin:basic"},
    "admin:manage_roles": {"admin:basic", "admin:assign_role"},
    "admin:ban_ip": {"admin:basic", "admin:logout_user"},
    "admin:reset_password": {"admin:basic", "admin:logout_user"},
    "admin:logout_user": {"admin:basic"},
    "moderation:kick_user": {"moderation:mute_user"},
    "moderation:ban_room": {"moderation:kick_user", "moderation:mute_user"},
    "moderation:suspend_user": {"moderation:mute_user"},
    "moderation:shadowban": {"moderation:mute_user"},
    "room:lock": {"room:readonly"},
    "room:delete": {"room:lock", "room:readonly"},
}


def _expand_permission_hierarchy(perms: Set[str]) -> Set[str]:
    """Return effective permissions after applying transitive RBAC inheritance rules."""
    effective = {str(p or "").strip() for p in (perms or set()) if str(p or "").strip()}
    pending = list(effective)
    while pending:
        perm = pending.pop()
        for inherited in _PERMISSION_INHERITANCE.get(perm, set()):
            if inherited not in effective:
                effective.add(inherited)
                pending.append(inherited)
    return effective


def get_user_permissions(username: str) -> Set[str]:
    """Resolve effective permissions for a username via RBAC tables."""
    if not username:
        return set()

    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT p.name
                  FROM users u
                  JOIN user_roles ur ON ur.user_id = u.id
                  JOIN role_permissions rp ON rp.role_id = ur.role_id
                  JOIN permissions p ON p.id = rp.permission_id
                 WHERE u.username = %s;
                """,
                (username,),
            )
            rows = cur.fetchall()
        return _expand_permission_hierarchy({r[0] for r in rows})
    except Exception as e:
        logging.error("RBAC lookup failed for %s: %s", username, e)
        return set()


def check_user_permission(username: str, permission: str) -> bool:
    """True if user has permission through RBAC."""
    return permission in get_user_permissions(username)


def require_permission(permission: str) -> Callable:
    """Decorator: require a specific RBAC permission."""

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            username = _safe_verify_jwt(optional=False)
            if not username:
                return jsonify({"error": "Unauthorized"}), 401

            perms = get_user_permissions(username)
            if permission not in perms:
                logging.warning("Permission denied: %s lacks '%s'", username, permission)
                return jsonify({"error": "Permission denied", "required": permission}), 403

            return func(*args, **kwargs)

        wrapper._echochat_required_permission = permission  # type: ignore[attr-defined]
        wrapper._echochat_admin_route_gate = True  # type: ignore[attr-defined]
        return wrapper

    return decorator


def require_admin(func: Callable) -> Callable:
    """Decorator for admin-only routes.

    Requires a valid access JWT plus live RBAC permissions. Session flags are
    intentionally not trusted here because they can go stale after a role
    change until the browser refreshes.
    """

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        username = _safe_verify_jwt(optional=False)
        if not username:
            return jsonify({"error": "Unauthorized"}), 401

        perms = get_user_permissions(username)
        if "admin:basic" in perms:
            return func(*args, **kwargs)

        return jsonify({"error": "Admin access required."}), 403

    wrapper._echochat_required_permission = "admin:basic"  # type: ignore[attr-defined]
    wrapper._echochat_admin_route_gate = True  # type: ignore[attr-defined]
    return wrapper
