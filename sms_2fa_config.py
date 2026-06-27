"""SMS 2FA / Twilio Verify configuration helpers.

These helpers keep setup-time validation and runtime readiness checks aligned.
Secrets may be stored in server_config.json for local testing, but production
should normally provide them through environment variables.
"""

from __future__ import annotations

import os
from typing import Any, Dict


_ALLOWED_VERIFY_CHANNELS = {"sms", "whatsapp"}


def _env_str(*names: str) -> str:
    for name in names:
        value = os.getenv(name)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _safe_int(value: Any, default: int, *, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except Exception:
        parsed = default
    return max(minimum, min(maximum, parsed))


def normalize_twilio_channel(value: Any) -> str:
    """Return a supported Twilio Verify channel for phone-based 2FA."""
    channel = str(value or "sms").strip().lower()
    return channel if channel in _ALLOWED_VERIFY_CHANNELS else "sms"


def effective_twilio_settings(settings: Dict[str, Any] | None) -> Dict[str, Any]:
    """Return runtime-effective SMS 2FA settings, honoring env secrets.

    main.apply_env_overrides also overlays these credentials. This helper is
    still used by setup and routes so direct tests/standalone setup runs follow
    the same secret lookup rules.
    """
    src = dict(settings or {})
    account_sid = _env_str("ECHOCHAT_TWILIO_ACCOUNT_SID", "TWILIO_ACCOUNT_SID") or str(src.get("twilio_account_sid") or "").strip()
    auth_token = _env_str("ECHOCHAT_TWILIO_AUTH_TOKEN", "TWILIO_AUTH_TOKEN") or str(src.get("twilio_auth_token") or "").strip()
    service_sid = _env_str("ECHOCHAT_TWILIO_VERIFY_SERVICE_SID", "TWILIO_VERIFY_SERVICE_SID") or str(src.get("twilio_verify_service_sid") or "").strip()
    beta_enabled = bool(src.get("enable_two_factor_beta", False))
    sms_enabled = bool(src.get("enable_sms_two_factor", False))
    channel = normalize_twilio_channel(src.get("two_factor_sms_channel") or "sms")
    timeout = _safe_int(src.get("two_factor_login_timeout_seconds"), 600, minimum=60, maximum=3600)
    return {
        "enable_two_factor_beta": beta_enabled,
        "enable_sms_two_factor": sms_enabled,
        "two_factor_sms_channel": channel,
        "twilio_account_sid": account_sid,
        "twilio_auth_token": auth_token,
        "twilio_verify_service_sid": service_sid,
        "two_factor_login_timeout_seconds": timeout,
        "ready": beta_enabled and sms_enabled and bool(account_sid and auth_token and service_sid),
    }


def twilio_setup_errors(settings: Dict[str, Any] | None) -> list[str]:
    """Return non-network setup errors for SMS 2FA/Twilio Verify."""
    cfg = effective_twilio_settings(settings)
    beta_enabled = bool(cfg.get("enable_two_factor_beta"))
    sms_enabled = bool(cfg.get("enable_sms_two_factor"))
    if not beta_enabled and not sms_enabled:
        return []

    errors: list[str] = []
    if sms_enabled and not beta_enabled:
        errors.append("SMS 2FA is enabled, but the base two-factor feature flag is off.")
    if beta_enabled and not sms_enabled:
        errors.append("Two-factor beta is enabled, but SMS 2FA is off; turn both on for Twilio Verify SMS login.")
    if not str(cfg.get("twilio_account_sid") or "").strip():
        errors.append("SMS 2FA is enabled, but Twilio Account SID is missing. Use server_config.json or ECHOCHAT_TWILIO_ACCOUNT_SID.")
    if not str(cfg.get("twilio_auth_token") or "").strip():
        errors.append("SMS 2FA is enabled, but Twilio Auth Token is missing. Store it in config or use ECHOCHAT_TWILIO_AUTH_TOKEN / TWILIO_AUTH_TOKEN.")
    if not str(cfg.get("twilio_verify_service_sid") or "").strip():
        errors.append("SMS 2FA is enabled, but Twilio Verify Service SID is missing. Use server_config.json or ECHOCHAT_TWILIO_VERIFY_SERVICE_SID.")
    channel = str(cfg.get("two_factor_sms_channel") or "sms")
    if channel not in _ALLOWED_VERIFY_CHANNELS:
        errors.append("SMS 2FA channel must be sms or whatsapp.")
    return errors


def twilio_ready(settings: Dict[str, Any] | None) -> bool:
    return bool(effective_twilio_settings(settings).get("ready"))
