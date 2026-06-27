"""Audit notes and guardrails for all-room E2EE strict mode."""

from __future__ import annotations


def public_room_e2ee_impact_report(settings: dict | None = None) -> dict:
    settings = settings or {}
    strict = bool(settings.get("require_room_e2ee", False))
    impacted_features = [
        {
            "key": "plaintext_moderation",
            "label": "Server-side text moderation",
            "impact": "Public-room message text is ciphertext, so keyword/profanity/body inspection cannot run on the server.",
            "mitigation": "Keep metadata rate limits, room locks, slow mode, mutes, kicks, bans, and report-based moderation enabled.",
        },
        {
            "key": "message_search",
            "label": "Public-room message search/transcripts",
            "impact": "Server-side search cannot index encrypted public-room text unless clients provide a separate searchable index, which would weaken privacy.",
            "mitigation": "Leave all-room strict mode off if admin-readable public-room search is required.",
        },
        {
            "key": "admin_visibility",
            "label": "Admin visibility into public-room content",
            "impact": "Admins can still see metadata and live events, but not plaintext public-room message bodies from the server.",
            "mitigation": "Use user reports, abuse metadata, per-room controls, and incident mode rather than content inspection.",
        },
        {
            "key": "antiabuse_classification",
            "label": "Content-kind classification",
            "impact": "GIF/torrent/file/text classification must come from trusted envelope metadata because plaintext inference is unavailable.",
            "mitigation": "Keep event payload limits and per-kind rate limits active; do not depend on plaintext body parsing.",
        },
    ]
    return {
        "strict_enabled": strict,
        "ack_required_to_enable": True,
        "ack_payload_key": "confirm_all_room_e2ee_impact",
        "summary": "All-room E2EE strict mode protects public-room message bodies but limits server-side moderation, text search, transcript inspection, and body-based abuse classification.",
        "impacted_features": impacted_features,
        "recommended_default": False,
        "safe_defaults": {
            "require_dm_e2ee": True,
            "require_group_e2ee": True,
            "require_private_room_e2ee": True,
            "require_room_e2ee": False,
        },
    }
