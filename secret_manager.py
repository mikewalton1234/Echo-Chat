"""Central secret resolution/generation helpers for Hui Chat.

The important rule: runtime-only one-off secrets must never be used for
session/JWT stability or at-rest encryption. Missing secrets are generated as
stable values and written to a protected .env file when JSON secret persistence
is disabled.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import secrets
import stat
from typing import Any, Iterable

from secrets_policy import persist_secrets_enabled

PLACEHOLDER_RE = re.compile(
    r"(?:^$|change[-_ ]?me|changeme|your[-_ ]|example|placeholder|generate_with|"
    r"generate[-_ ]?a|different[-_ ]?long[-_ ]?random|token_urlsafe|secret_here)",
    re.I,
)

SECRET_KEY_ENV_ALIASES = ("SECRET_KEY", "HUI_SECRET_KEY", "HUI_FLASK_SECRET_KEY")
JWT_SECRET_ENV_ALIASES = ("JWT_SECRET_KEY", "HUI_JWT_SECRET", "HUI_JWT_SECRET_KEY")
PROFILE_KEY_ENV_ALIASES = ("HUI_PROFILE_FIELD_KEY", "PROFILE_FIELD_ENCRYPTION_KEY")
EMAIL_FIELD_KEY_ENV_ALIASES = ("HUI_EMAIL_FIELD_KEY", "EMAIL_FIELD_ENCRYPTION_KEY")
EMAIL_HASH_KEY_ENV_ALIASES = ("HUI_EMAIL_HASH_KEY", "EMAIL_HASH_KEY")
BACKUP_KEY_ENV_ALIASES = ("HUI_SECURITY_BACKUP_KEY", "SECURITY_BACKUP_ENCRYPTION_KEY")
PRIVACY_HASH_KEY_ENV_ALIASES = ("HUI_PRIVACY_HASH_KEY", "PRIVACY_RETENTION_HASH_KEY")

SETTING_ALIASES = {
    "secret_key": ("secret_key", "flask_secret_key", "session_secret", "session_secret_key"),
    "jwt_secret": ("jwt_secret", "jwt_secret_key"),
    "profile_field_encryption_key": ("profile_field_encryption_key",),
    "email_field_encryption_key": ("email_field_encryption_key",),
    "email_hash_key": ("email_hash_key",),
    "security_backup_encryption_key": ("security_backup_encryption_key",),
    "privacy_retention_hash_key": ("privacy_retention_hash_key",),
}

ENV_ALIASES = {
    "secret_key": SECRET_KEY_ENV_ALIASES,
    "jwt_secret": JWT_SECRET_ENV_ALIASES,
    "profile_field_encryption_key": PROFILE_KEY_ENV_ALIASES,
    "email_field_encryption_key": EMAIL_FIELD_KEY_ENV_ALIASES,
    "email_hash_key": EMAIL_HASH_KEY_ENV_ALIASES,
    "security_backup_encryption_key": BACKUP_KEY_ENV_ALIASES,
    "privacy_retention_hash_key": PRIVACY_HASH_KEY_ENV_ALIASES,
}

PRIMARY_ENV = {
    "secret_key": "SECRET_KEY",
    "jwt_secret": "JWT_SECRET_KEY",
    "profile_field_encryption_key": "HUI_PROFILE_FIELD_KEY",
    "email_field_encryption_key": "HUI_EMAIL_FIELD_KEY",
    "email_hash_key": "HUI_EMAIL_HASH_KEY",
    "security_backup_encryption_key": "HUI_SECURITY_BACKUP_KEY",
    "privacy_retention_hash_key": "HUI_PRIVACY_HASH_KEY",
}

GENERATED_ENV_ORDER = (
    "SECRET_KEY",
    "JWT_SECRET_KEY",
    "HUI_PROFILE_FIELD_KEY",
    "HUI_EMAIL_FIELD_KEY",
    "HUI_EMAIL_HASH_KEY",
    "HUI_SECURITY_BACKUP_KEY",
    "HUI_PRIVACY_HASH_KEY",
)


def is_placeholder_secret(value: Any) -> bool:
    text = str(value or "").strip()
    return not text or bool(PLACEHOLDER_RE.search(text))


def is_strong_secret(value: Any, *, min_len: int = 32) -> bool:
    text = str(value or "").strip()
    return len(text) >= min_len and not is_placeholder_secret(text)


def _clean(value: Any) -> str:
    text = str(value or "").strip()
    return "" if is_placeholder_secret(text) else text


def _first_env(names: Iterable[str]) -> str:
    for name in names:
        value = _clean(os.getenv(name))
        if value:
            return value
    return ""


def _first_setting(settings: dict | None, keys: Iterable[str]) -> str:
    settings = settings or {}
    for key in keys:
        value = _clean(settings.get(key))
        if value:
            return value
    return ""


def resolve_secret(settings: dict | None, canonical: str) -> str:
    """Resolve a stable secret, ignoring blank/placeholder values."""
    return _first_env(ENV_ALIASES.get(canonical, ())) or _first_setting(settings, SETTING_ALIASES.get(canonical, (canonical,)))


def stable_secret_key_material(settings: dict | None = None) -> str:
    return resolve_secret(settings, "secret_key")


def stable_profile_field_key_material(settings: dict | None = None) -> str:
    return resolve_secret(settings, "profile_field_encryption_key") or stable_secret_key_material(settings)


def stable_email_field_key_material(settings: dict | None = None) -> str:
    return resolve_secret(settings, "email_field_encryption_key") or stable_profile_field_key_material(settings)


def stable_email_hash_key_material(settings: dict | None = None) -> str:
    return resolve_secret(settings, "email_hash_key") or stable_email_field_key_material(settings)


def stable_security_backup_key_material(settings: dict | None = None) -> str:
    return resolve_secret(settings, "security_backup_encryption_key") or stable_profile_field_key_material(settings) or stable_email_field_key_material(settings)


def stable_privacy_hash_key_material(settings: dict | None = None) -> str:
    return resolve_secret(settings, "privacy_retention_hash_key") or stable_secret_key_material(settings)


def generate_secret_value() -> str:
    return secrets.token_urlsafe(64)


def default_env_path(settings_file: Path | None = None) -> Path:
    override = os.getenv("HUI_ENV_FILE") or os.getenv("ENV_FILE")
    if override:
        return Path(override)
    base = Path(settings_file).resolve().parent if settings_file else Path.cwd()
    return base / ".env"


def _parse_env_lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    try:
        return path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return []



def read_env_value(path: Path, name: str) -> str:
    assignment_re = re.compile(r"^\s*" + re.escape(name) + r"\s*=\s*(.*)\s*$")
    for line in _parse_env_lines(path):
        m = assignment_re.match(line)
        if not m:
            continue
        raw = m.group(1).strip()
        if (raw.startswith('"') and raw.endswith('"')) or (raw.startswith("'") and raw.endswith("'")):
            raw = raw[1:-1]
        return _clean(raw)
    return ""

def write_env_secrets(secrets_map: dict[str, str], *, path: Path | None = None) -> Path:
    """Write or update secret values in a chmod 0600 env file."""
    path = Path(path or default_env_path())
    path.parent.mkdir(parents=True, exist_ok=True)
    existing_lines = _parse_env_lines(path)
    wanted = {str(k): str(v).strip() for k, v in secrets_map.items() if str(v or "").strip()}
    seen: set[str] = set()
    out: list[str] = []
    assignment_re = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=")
    for line in existing_lines:
        m = assignment_re.match(line)
        if not m:
            out.append(line)
            continue
        key = m.group(1)
        if key in wanted:
            out.append(f"{key}={wanted[key]}")
            seen.add(key)
        else:
            out.append(line)
    if wanted and (not out or out[-1].strip()):
        out.append("")
    for key in GENERATED_ENV_ORDER:
        if key in wanted and key not in seen:
            out.append(f"{key}={wanted[key]}")
            seen.add(key)
    for key in sorted(set(wanted) - seen):
        out.append(f"{key}={wanted[key]}")
    path.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")
    try:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    except Exception:
        pass
    return path


def ensure_secret(settings: dict, canonical: str, *, settings_file: Path | None = None, generate: bool = True) -> tuple[str, bool, Path | None]:
    """Return (secret, generated, env_path_written)."""
    settings = settings if settings is not None else {}
    existing = resolve_secret(settings, canonical)
    if existing:
        primary = PRIMARY_ENV.get(canonical)
        if primary and not os.getenv(primary):
            os.environ[primary] = existing
        settings[canonical] = existing
        return existing, False, None
    if not generate:
        return "", False, None
    primary = PRIMARY_ENV.get(canonical, canonical.upper())
    env_path = default_env_path(settings_file)
    existing_file_value = read_env_value(env_path, primary)
    if existing_file_value:
        os.environ[primary] = existing_file_value
        settings[canonical] = existing_file_value
        return existing_file_value, False, None
    value = generate_secret_value()
    settings[canonical] = value
    primary = PRIMARY_ENV.get(canonical, canonical.upper())
    os.environ[primary] = value
    written: Path | None = None
    if not persist_secrets_enabled(settings) or os.getenv("HUI_AUTO_WRITE_ENV_SECRETS", "1").strip().lower() not in {"0", "false", "no", "off"}:
        written = write_env_secrets({primary: value}, path=default_env_path(settings_file))
    return value, True, written


def ensure_core_runtime_secrets(settings: dict, *, settings_file: Path | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {"generated": [], "env_file": None}
    for canonical in ("secret_key", "jwt_secret"):
        _value, generated, env_path = ensure_secret(settings, canonical, settings_file=settings_file)
        if generated:
            result["generated"].append(canonical)
        if env_path:
            result["env_file"] = str(env_path)
    return result


def generate_secret_bundle(*, include_crypto: bool = True) -> dict[str, str]:
    bundle = {
        "SECRET_KEY": generate_secret_value(),
        "JWT_SECRET_KEY": generate_secret_value(),
    }
    if include_crypto:
        bundle.update(
            {
                "HUI_PROFILE_FIELD_KEY": generate_secret_value(),
                "HUI_EMAIL_FIELD_KEY": generate_secret_value(),
                "HUI_EMAIL_HASH_KEY": generate_secret_value(),
                "HUI_SECURITY_BACKUP_KEY": generate_secret_value(),
                "HUI_PRIVACY_HASH_KEY": generate_secret_value(),
            }
        )
    return bundle


def format_env_bundle(bundle: dict[str, str]) -> str:
    return "\n".join(f"{key}={value}" for key, value in bundle.items()) + "\n"


def missing_core_or_crypto(settings: dict | None = None, *, include_crypto: bool = True) -> list[str]:
    missing = []
    checks = [
        ("SECRET_KEY", stable_secret_key_material(settings)),
        ("JWT_SECRET_KEY", resolve_secret(settings, "jwt_secret")),
    ]
    if include_crypto:
        checks.extend(
            [
                ("HUI_PROFILE_FIELD_KEY or stable SECRET_KEY", stable_profile_field_key_material(settings)),
                ("HUI_EMAIL_FIELD_KEY", resolve_secret(settings, "email_field_encryption_key")),
                ("HUI_EMAIL_HASH_KEY", resolve_secret(settings, "email_hash_key")),
                ("HUI_SECURITY_BACKUP_KEY", resolve_secret(settings, "security_backup_encryption_key")),
                ("HUI_PRIVACY_HASH_KEY", resolve_secret(settings, "privacy_retention_hash_key")),
            ]
        )
    for label, value in checks:
        if not value:
            missing.append(label)
    return missing
