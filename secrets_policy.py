"""secrets_policy.py

Central policy for whether EchoChat should persist *secrets* into server_config.json.

Why this exists:
- In production you typically want secrets in environment variables or a secret manager,
  not written back into a config file that may be copied, zipped, or committed.

Default behavior:
- Development/LAN mode stays backward compatible and may persist secrets.
- Production/public mode does *not* persist secrets unless explicitly allowed.

Override persistence:
  export ECHOCHAT_PERSIST_SECRETS=0  # never write secrets to server_config.json
  export ECHOCHAT_PERSIST_SECRETS=1  # explicitly allow legacy config persistence
"""

from __future__ import annotations

import os
from typing import Any, Dict
from urllib.parse import urlsplit


_TRUE_VALUES = {"1", "true", "yes", "y", "on"}
_FALSE_VALUES = {"0", "false", "no", "n", "off"}
_PRODUCTION_RUN_MODE_VALUES = {"production", "prod", "public", "public-beta", "public_beta"}


def _env_bool(name: str, default: bool | None = None) -> bool | None:
    v = os.getenv(name)
    if v is None:
        return default
    s = str(v).strip().lower()
    if s in _TRUE_VALUES:
        return True
    if s in _FALSE_VALUES:
        return False
    return default


def _truthy_setting(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in (_TRUE_VALUES | _PRODUCTION_RUN_MODE_VALUES)


def _looks_production(settings: Dict[str, Any] | None) -> bool:
    """Return True when settings describe production/public deployment."""
    if not settings:
        return False
    if _truthy_setting(settings.get("production_mode")):
        return True
    raw_mode = (
        settings.get("run_mode")
        or settings.get("server_mode")
        or settings.get("deployment_mode")
        or settings.get("hosting_mode")
        or ""
    )
    mode = str(raw_mode).strip().lower().replace(" ", "-")
    return mode in _PRODUCTION_RUN_MODE_VALUES or mode == "public-beta"


def persist_secrets_enabled(settings: Dict[str, Any] | None = None) -> bool:
    """Whether secret values should be written into server_config.json.

    Explicit ECHOCHAT_PERSIST_SECRETS always wins. Without that override, production
    and public deployments default to env/secret-manager-only secret storage.
    """
    env_override = _env_bool("ECHOCHAT_PERSIST_SECRETS", None)
    if env_override is not None:
        return bool(env_override)
    if _looks_production(settings):
        return False
    return True


# These are top-level keys in server_config.json that should be treated as secrets.
# Some identifiers (for example Twilio SIDs) are not passwords by themselves, but
# keeping provider account identifiers out of copied/zipped configs is safer.
SECRET_SETTING_KEYS = {
    # Flask/JWT/session secrets
    "secret_key",
    "jwt_secret",
    "profile_field_encryption_key",
    "profile_field_old_keys",
    "profile_field_previous_keys",
    "email_field_encryption_key",
    "email_hash_key",
    "security_backup_encryption_key",
    "privacy_retention_hash_key",
    "jwt_secret_key",
    "flask_secret_key",
    "session_secret",
    "session_secret_key",
    # Legacy/setup/admin secrets
    "admin_pass",
    "admin_password",
    "admin_password_hash",
    "owner_password",
    "recovery_pin",
    "recovery_pin_hash",
    # DB DSNs are handled below: passwordless local DSNs are safe to persist
    # for beginner setup, while DSNs containing credentials are scrubbed.
    # Third-party API keys
    "giphy_api_key",
    "media_api_key",
    "media_api_secret",
    # Twilio/SMS 2FA
    "twilio_account_sid",
    "twilio_auth_token",
    "twilio_verify_service_sid",
    # SMTP/email
    "smtp_password",
    "smtp_pass",
    "smtp_api_key",
    "mail_password",
    "email_password",
    # Dynamic DNS provider credentials
    "dynamic_dns_password",
    "dynamic_dns_token",
    # TURN/STUN/WebRTC credentials
    "turn_username",
    "turn_password",
    "turn_credential",
    "turn_secret",
    "webrtc_turn_username",
    "webrtc_turn_password",
    "webrtc_turn_credential",
    "voice_turn_username",
    "voice_turn_password",
    "voice_turn_credential",
}


# PostgreSQL DSN keys may be either non-secret local identifiers
#   postgresql://linux_user@localhost:5432/echochat
# or real secrets with embedded passwords
#   postgresql://linux_user:password@db-host:5432/echochat
# Keep passwordless local/LAN examples usable; scrub credential-bearing URLs.
PASSWORDLESS_PERSISTABLE_POSTGRES_DSN_KEYS = {
    "database_url",
    "database_bootstrap_url",
    "db_connection_string",
    "database_dsn",
    "postgres_dsn",
    "postgres_url",
}


def _is_postgres_url(value: Any) -> bool:
    try:
        raw = str(value or "").strip().lower()
        return raw.startswith(("postgresql://", "postgres://"))
    except Exception:
        return False

# URI settings can carry passwords inside the URL. Scrub them when credentials
# are present even if the key itself can also hold non-secret values like memory://.
SECRET_URI_SETTING_KEYS = {
    "redis_url",
    "redis_uri",
    "socketio_message_queue",
    "shared_state_redis_url",
    "rate_limit_storage_uri",
    "rate_limit_storage",
    "celery_broker_url",
    "broker_url",
    "cache_url",
}

# Nested credential fields, especially inside ICE/TURN server objects.
NESTED_SECRET_FIELD_NAMES = {
    "password",
    "pass",
    "secret",
    "api_secret",
    "api_key",
    "auth_token",
    "token",
    "credential",
    "credentials",
    "private_key",
    "client_secret",
}


def _url_contains_password(value: Any) -> bool:
    try:
        raw = str(value or "").strip()
        if not raw:
            return False
        parts = urlsplit(raw)
        return bool(parts.password)
    except Exception:
        return False


def _scrub_nested(value: Any) -> Any:
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            key_s = str(key)
            key_l = key_s.lower()
            if key_l in NESTED_SECRET_FIELD_NAMES:
                continue
            out[key_s] = _scrub_nested(item)
        return out
    if isinstance(value, list):
        return [_scrub_nested(item) for item in value]
    return value


def _scrub_mapping(settings: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for key, value in dict(settings or {}).items():
        key_s = str(key)
        key_l = key_s.lower()
        if key_l in SECRET_SETTING_KEYS:
            continue
        if key_l in PASSWORDLESS_PERSISTABLE_POSTGRES_DSN_KEYS:
            # Local setup DSNs without an embedded password are not secrets and
            # must remain in server_config.json, otherwise setup succeeds but
            # the next server start crashes with an empty PostgreSQL DSN.
            if not value or _url_contains_password(value) or not _is_postgres_url(value):
                continue
            out[key_s] = str(value).strip()
            continue
        if key_l in SECRET_URI_SETTING_KEYS and _url_contains_password(value):
            continue
        out[key_s] = _scrub_nested(value)
    return out


def scrub_secrets_for_persist(settings: Dict[str, Any]) -> Dict[str, Any]:
    """Return settings safe to write to server_config.json under the active policy."""
    if persist_secrets_enabled(settings):
        return dict(settings)
    return _scrub_mapping(settings)


def scrub_patch_for_persist(patch: Dict[str, Any], current_settings: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """Return a settings patch safe to persist under the active policy."""
    policy_source = current_settings if current_settings is not None else patch
    if persist_secrets_enabled(policy_source):
        return dict(patch)
    return _scrub_mapping(patch)
