#!/usr/bin/env python3
"""Legacy moderation routes.

The modern Admin Panel owns mutating moderation actions.  These legacy URLs are
kept only as compatibility/read-only pointers so old bookmarks fail closed
instead of bypassing granular RBAC and recent admin re-authentication.
"""

from __future__ import annotations

from flask import jsonify, render_template_string, request, session

from database import get_db
from moderation import list_active_sanctions
from permissions import require_admin
from security import log_audit_event


def register_moderation_routes(app, settings, limiter=None):
    def _limit(rule, **kwargs):
        if limiter is None:
            return lambda f: f
        try:
            return limiter.limit(rule, **kwargs)
        except Exception:
            return lambda f: f

    @app.route("/moderation", methods=["GET", "POST"])
    @_limit(settings.get("rate_limit_moderation") or "60 per minute", methods=["POST"])
    @require_admin
    def moderation_panel():
        actor = str(session.get("username") or "unknown")
        if request.method == "POST":
            username = (request.form.get("username") or "").strip() or "-"
            action = (request.form.get("action") or "legacy_moderation_post").strip().lower()
            try:
                log_audit_event(
                    actor,
                    "blocked_legacy_moderation_action",
                    username,
                    f"/moderation POST disabled; requested action={action}; use Admin Panel moderation routes",
                )
            except Exception:
                pass
            wants_json = "application/json" in str(request.headers.get("Accept") or "").lower()
            payload = {
                "success": False,
                "ok": False,
                "error": "The legacy /moderation write form is disabled. Use the Admin Panel moderation tools instead.",
                "code": "legacy_moderation_action_disabled",
                "admin_route": "/admin",
            }
            if wants_json:
                return jsonify(payload), 409
            return render_template_string(
                """
                <h2>Legacy Moderation Disabled</h2>
                <p>The old /moderation write form is disabled so moderation actions go through the modern Admin Panel checks.</p>
                <p><a href="/admin">Open Admin Panel</a></p>
                <pre>{{ payload }}</pre>
                """,
                payload=payload,
            ), 409

        sanctions = list_active_sanctions("*")
        return render_template_string(
            """
            <h2>Legacy Moderation Panel</h2>
            <p><strong>Write actions are disabled here.</strong> Use the modern <a href="/admin">Admin Panel</a> for mute, kick, ban, suspend, and shadowban actions.</p>
            <h3>Active Sanctions</h3>
            <table border="1">
                <tr><th>User</th><th>Type</th><th>Reason</th><th>Expires</th></tr>
                {% for u, t, r, e in sanctions %}
                    <tr>
                        <td>{{ u }}</td>
                        <td>{{ t }}</td>
                        <td>{{ r }}</td>
                        <td>{{ e }}</td>
                    </tr>
                {% endfor %}
            </table>
            """,
            sanctions=sanctions,
        )

    @app.route("/audit-log")
    @require_admin
    def view_audit_log():
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT actor, action, target, timestamp, details
                  FROM audit_log
                 ORDER BY timestamp DESC
                 LIMIT 100;
                """
            )
            rows = cur.fetchall()

        return render_template_string(
            """
            <h2>Audit Log</h2>
            <p>Read-only legacy audit view. Use the Admin Panel for full moderation and security workflows.</p>
            <table border="1">
              <tr>
                <th>Actor</th><th>Action</th><th>Target</th><th>Time</th><th>Details</th>
              </tr>
              {% for actor, action, target, ts, details in logs %}
                <tr>
                  <td>{{ actor }}</td>
                  <td>{{ action }}</td>
                  <td>{{ target }}</td>
                  <td>{{ ts }}</td>
                  <td>{{ details }}</td>
                </tr>
              {% endfor %}
            </table>
            """,
            logs=rows,
        )
