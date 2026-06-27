"""Echo built-in media mode helpers.

This module owns the non-secret browser/admin configuration for Echo-Chat's
built-in WebRTC voice and webcam controls. It has no external media-server
integration.
"""
from __future__ import annotations

import os
from typing import Any, Dict

from echo_voice_protocol import echo_voice_bool


def media_permissions_policy(settings: Dict[str, Any]) -> str:
    """Return the effective Permissions-Policy needed for Echo voice/webcam.

    Browsers require both a secure context and a Permissions-Policy that does
    not deny camera/microphone. Keep this default explicit so diagnostics, the
    AV-mode endpoint, and Flask security headers all describe the same policy.
    """
    raw = str((settings or {}).get("permissions_policy") or "").strip()
    return raw or "geolocation=(), camera=(self), microphone=(self)"


def media_secure_context_policy(settings: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "requires_secure_context": True,
        "localhost_http_allowed": True,
        "allowed_localhost_hosts": ["localhost", "127.0.0.1", "::1"],
        "permissions_policy": media_permissions_policy(settings),
        "camera_feature": "camera",
        "microphone_feature": "microphone",
    }


def _truthy_env(name: str) -> bool | None:
    if os.getenv(name) is None:
        return None
    return str(os.getenv(name) or "").strip().lower() in {"1", "true", "yes", "on"}


def requested_av_mode(settings: Dict[str, Any]) -> str:
    """Return the admin-selected media mode: echo or standard."""
    env_mode = str(os.getenv("ECHOCHAT_AV_MODE") or os.getenv("AV_MODE") or "").strip().lower().replace("-", "_")
    if env_mode in {"echo", "standard", "webrtc", "built_in", "builtin"}:
        return "echo" if env_mode in {"webrtc", "built_in", "builtin"} else env_mode
    raw = str(settings.get("av_mode") or settings.get("voice_mode") or "").strip().lower().replace("-", "_")
    if raw in {"echo", "standard", "webrtc", "built_in", "builtin"}:
        return "echo" if raw in {"webrtc", "built_in", "builtin"} else raw
    return "echo" if echo_voice_bool(settings, "webcam_enabled", True) else "standard"


def webcam_policy(settings: Dict[str, Any]) -> Dict[str, Any]:
    """Return non-secret webcam access policy for clients/admin UI."""
    raw_mode = str(settings.get("webcam_approval_mode") or "owner_approval").strip().lower().replace("-", "_")
    aliases = {
        "ask": "owner_approval",
        "approval": "owner_approval",
        "owner": "owner_approval",
        "owner_approval": "owner_approval",
        "request": "owner_approval",
        "request_required": "owner_approval",
        "open": "open",
        "public": "open",
        "everyone": "open",
        "disabled": "disabled",
        "blocked": "disabled",
        "off": "disabled",
    }
    approval_mode = aliases.get(raw_mode, "owner_approval")

    try:
        max_viewers = int(settings.get("webcam_max_viewers", 0) or 0)
    except Exception:
        max_viewers = 0
    max_viewers = max(0, min(500, max_viewers))

    raw_default = str(settings.get("default_media_policy") or "user_choice").strip().lower().replace("-", "_")
    default_aliases = {
        "manual": "user_choice",
        "user": "user_choice",
        "user_choice": "user_choice",
        "voice": "voice_first",
        "voice_only": "voice_first",
        "voice_first": "voice_first",
        "webcam": "webcam_first",
        "camera": "webcam_first",
        "webcam_first": "webcam_first",
        "camera_first": "webcam_first",
        "both": "both_first",
        "both_first": "both_first",
    }
    default_media_policy = default_aliases.get(raw_default, "user_choice")

    return {
        "webcam_approval_mode": approval_mode,
        "webcam_max_viewers": max_viewers,
        "default_media_policy": default_media_policy,
        "server_enforced_webcam_permissions": False,
    }


def resolve_av_mode(settings: Dict[str, Any]) -> Dict[str, Any]:
    """Server-owned decision for the browser media controls."""
    requested = requested_av_mode(settings)
    voice_enabled = echo_voice_bool(settings, "voice_enabled", True)
    webcam_enabled = echo_voice_bool(settings, "webcam_enabled", echo_voice_bool(settings, "echo_webcam_enabled", True))
    policy = webcam_policy(settings)

    if not voice_enabled:
        mode = "standard"
        reason = "voice_disabled"
        label = "Media disabled"
    elif requested == "standard" and not webcam_enabled:
        mode = "standard"
        reason = "voice_only_mode"
        label = "Echo voice only"
    else:
        mode = "echo"
        reason = "webcam_enabled_overrides_voice_only" if requested == "standard" else "builtin_webrtc_media"
        label = "Echo built-in WebRTC voice/webcam"

    features = {
        "microphone": bool(voice_enabled),
        "webcam": bool(mode == "echo" and voice_enabled and webcam_enabled and policy.get("webcam_approval_mode") != "disabled"),
        "screen_share": False,
        "uses_standard_voice": bool(mode == "standard" and voice_enabled),
        "uses_echo_webrtc": bool(mode == "echo"),
        "server_enforced_webcam_permissions": False,
    }
    return {
        "requested_mode": requested,
        "mode": mode,
        "label": label,
        "reason": reason,
        "voice_enabled": voice_enabled,
        "webcam_policy": policy,
        "features": features,
    }


def client_av_config(settings: Dict[str, Any]) -> Dict[str, Any]:
    """Small non-secret config object safe to expose to the browser."""
    decision = resolve_av_mode(settings)
    return {
        "av_mode": decision["mode"],
        "av_requested_mode": decision["requested_mode"],
        "av_mode_reason": decision["reason"],
        "av_label": decision["label"],
        "webcam_policy": dict(decision.get("webcam_policy") or {}),
        "features": dict(decision.get("features") or {}),
        "secure_context": media_secure_context_policy(settings),
        "webcam_enabled": bool((decision.get("features") or {}).get("webcam", False)),
        "echo_webcam_enabled": bool((decision.get("features") or {}).get("webcam", False)),
    }
