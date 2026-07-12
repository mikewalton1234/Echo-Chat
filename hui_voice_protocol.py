"""Hui Voice protocol policy helpers.

This module owns the Hui Chat voice-room control-plane defaults.  It does not
route media through an external server; it gives the server and browser one
consistent place for capacity, protocol naming, and media defaults.
"""

from __future__ import annotations

from typing import Any, Mapping

from webrtc_ice_config import ice_server_summary

HUI_VOICE_PROTOCOL_ID = "hui-voice-v1"
HUI_VOICE_DEFAULT_ROOM_USERS = 100
HUI_VOICE_MAX_ROOM_USERS = 500

HUI_VOICE_QUALITY_PROFILES = {
    "low": {"label": "Low bandwidth", "sample_rate": 16000, "max_bitrate": 24000},
    "balanced": {"label": "Balanced", "sample_rate": 24000, "max_bitrate": 40000},
    "high": {"label": "High quality", "sample_rate": 48000, "max_bitrate": 64000},
}
HUI_VOICE_DEFAULT_QUALITY = "balanced"

HUI_WEBCAM_QUALITY_PROFILES = {
    # Lower quality looks better when we lower resolution before bitrate.  This
    # avoids smearing a high-resolution picture into too few bits.
    "low": {
        "label": "Low data / sharper",
        "width": 320,
        "height": 180,
        "frameRate": 12,
        "max_bitrate": 160000,
        "preferred_codecs": ["H264", "VP8", "VP9"],
        "content_hint": "detail",
        "degradation_preference": "maintain-framerate",
    },
    "balanced": {
        "label": "Balanced",
        "width": 640,
        "height": 360,
        "frameRate": 18,
        "max_bitrate": 550000,
        "preferred_codecs": ["H264", "VP8", "VP9"],
        "content_hint": "motion",
        "degradation_preference": "balanced",
    },
    "high": {
        "label": "High quality",
        "width": 1280,
        "height": 720,
        "frameRate": 24,
        "max_bitrate": 1500000,
        "preferred_codecs": ["H264", "VP8", "VP9", "AV1"],
        "content_hint": "motion",
        "degradation_preference": "balanced",
    },
}
HUI_WEBCAM_DEFAULT_QUALITY = "balanced"


def hui_voice_audio_quality(settings: Mapping[str, Any] | None) -> str:
    """Return the admin-selected voice quality profile name."""
    settings = settings or {}
    raw = str(settings.get("voice_audio_quality") or HUI_VOICE_DEFAULT_QUALITY).strip().lower()
    return raw if raw in HUI_VOICE_QUALITY_PROFILES else HUI_VOICE_DEFAULT_QUALITY


def hui_webcam_quality(settings: Mapping[str, Any] | None) -> str:
    """Return the admin/user default webcam quality profile name."""
    settings = settings or {}
    raw = str(
        settings.get("webcam_quality")
        or settings.get("hui_webcam_quality")
        or HUI_WEBCAM_DEFAULT_QUALITY
    ).strip().lower()
    return raw if raw in HUI_WEBCAM_QUALITY_PROFILES else HUI_WEBCAM_DEFAULT_QUALITY


def hui_voice_bool(settings: Mapping[str, Any] | None, key: str, default: bool) -> bool:
    """Parse voice-related booleans from JSON, env-loaded strings, or native bools."""
    settings = settings or {}
    raw = settings.get(key, default)
    if isinstance(raw, bool):
        return raw
    if raw is None:
        return bool(default)
    text = str(raw).strip().lower()
    if text in {"1", "true", "yes", "on", "enabled"}:
        return True
    if text in {"0", "false", "no", "off", "disabled"}:
        return False
    return bool(default)


def hui_voice_room_limit(settings: Mapping[str, Any] | None) -> int:
    """Return the configured max voice users per room.

    Missing/blank values default to 100.  A deliberate value of 0 still means
    unlimited for admins who explicitly want that behavior.
    """
    settings = settings or {}
    raw = settings.get("voice_max_room_peers", None)
    if raw is None or str(raw).strip() == "":
        return HUI_VOICE_DEFAULT_ROOM_USERS
    try:
        n = int(str(raw).strip())
    except Exception:
        return HUI_VOICE_DEFAULT_ROOM_USERS
    if n < 0:
        return 0
    if n > HUI_VOICE_MAX_ROOM_USERS:
        return HUI_VOICE_MAX_ROOM_USERS
    return n


def hui_voice_room_capacity(current_users: int, settings: Mapping[str, Any] | None) -> dict[str, Any]:
    """Return capacity metadata for a room roster count."""
    current = max(0, int(current_users or 0))
    limit = hui_voice_room_limit(settings)
    full = bool(limit > 0 and current >= limit)
    remaining = None if limit <= 0 else max(0, limit - current)
    return {
        "protocol": HUI_VOICE_PROTOCOL_ID,
        "limit": limit,
        "current": current,
        "remaining": remaining,
        "full": full,
        "display_limit": "unlimited" if limit <= 0 else str(limit),
    }


def hui_voice_client_config(settings: Mapping[str, Any] | None) -> dict[str, Any]:
    """Return non-secret voice protocol metadata safe for the browser."""
    settings = settings or {}
    limit = hui_voice_room_limit(settings)
    quality = hui_voice_audio_quality(settings)
    profile = HUI_VOICE_QUALITY_PROFILES[quality]
    return {
        "voice_protocol": HUI_VOICE_PROTOCOL_ID,
        "voice_max_room_peers": limit,
        "voice_default_room_peers": HUI_VOICE_DEFAULT_ROOM_USERS,
        "voice_room_limit_adjustable": True,
        "voice_audio_quality": quality,
        "voice_audio_quality_label": profile["label"],
        "voice_audio_sample_rate": int(profile["sample_rate"]),
        "voice_audio_max_bitrate": int(profile["max_bitrate"]),
        "voice_auto_quality": hui_voice_bool(settings, "voice_auto_quality", True),
        "voice_noise_cancellation": hui_voice_bool(settings, "voice_noise_cancellation", True),
        "voice_echo_cancellation": hui_voice_bool(settings, "voice_echo_cancellation", True),
        "voice_auto_gain_control": hui_voice_bool(settings, "voice_auto_gain_control", True),
        "voice_default_push_to_talk": hui_voice_bool(settings, "voice_default_push_to_talk", True),
        "voice_quality_profiles": HUI_VOICE_QUALITY_PROFILES,
        "webcam_enabled": hui_voice_bool(settings, "webcam_enabled", True),
        "hui_webcam_enabled": hui_voice_bool(settings, "hui_webcam_enabled", True),
        "webcam_quality": hui_webcam_quality(settings),
        "hui_webcam_quality": hui_webcam_quality(settings),
        "webcam_quality_profiles": HUI_WEBCAM_QUALITY_PROFILES,
        "webcam_codec_strategy": str(settings.get("webcam_codec_strategy") or "prefer-compatible").strip().lower(),
        "webcam_transport": "hui-webrtc-mesh",
        "webrtc_ice_summary": ice_server_summary(settings),
    }
