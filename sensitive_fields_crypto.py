"""Small server-side encryption helper for sensitive user profile fields.

This protects fields that the server must occasionally read (for example SMS
2FA phone numbers and privacy-filtered profile location text) while keeping the
existing PostgreSQL schema compatible. Existing plaintext rows continue to read;
new writes are stored as authenticated AES-GCM envelopes when a key is available.
"""

from __future__ import annotations

import base64
import hashlib
import os
import re
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

SENSITIVE_FIELD_PREFIX = "ecenc:v1:"
_FIELD_KEY_ENV = "ECHOCHAT_PROFILE_FIELD_KEY"
_PREVIOUS_FIELD_KEYS_ENV = "ECHOCHAT_PROFILE_FIELD_PREVIOUS_KEYS"
_AAD_PREFIX = b"EchoChat sensitive profile field v1:"
_KEY_DERIVE_PREFIX = b"EchoChat profile-field encryption key v1\n"


def _truthy(value: Any, default: bool = True) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def sensitive_field_encryption_enabled(settings: dict | None = None) -> bool:
    """Return whether new sensitive profile-field writes should be encrypted."""
    settings = settings or {}
    return _truthy(settings.get("encrypt_sensitive_profile_fields"), True)




def _split_key_list(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, (list, tuple, set)):
        parts = raw
    else:
        text = str(raw or "")
        # Support comma/newline/semicolon separated env values without requiring JSON.
        parts = re.split(r"[\n,;]+", text)
    out: list[str] = []
    for part in parts:
        value = str(part or "").strip()
        if value and value not in out:
            out.append(value)
    return out

def _key_material(settings: dict | None = None) -> str:
    settings = settings or {}
    return (
        os.getenv(_FIELD_KEY_ENV)
        or str(settings.get("profile_field_encryption_key") or "").strip()
        or os.getenv("SECRET_KEY")
        or str(settings.get("secret_key") or "").strip()
    )


def sensitive_field_key_available(settings: dict | None = None) -> bool:
    return bool(_key_material(settings))


def _derive_key_from_material(material: str | None) -> bytes | None:
    material = str(material or "").strip()
    if not material:
        return None
    return hashlib.sha256(_KEY_DERIVE_PREFIX + material.encode("utf-8")).digest()


def _derive_key(settings: dict | None = None) -> bytes | None:
    return _derive_key_from_material(_key_material(settings))


def previous_profile_field_key_materials(settings: dict | None = None) -> list[str]:
    """Return previous profile-field encryption keys used only for read/rotation.

    Keep old keys out of server_config.json in production; prefer
    ECHOCHAT_PROFILE_FIELD_PREVIOUS_KEYS during a rotation window. Values can
    be comma, semicolon, or newline separated.
    """
    settings = settings or {}
    return _split_key_list(
        os.getenv(_PREVIOUS_FIELD_KEYS_ENV)
        or settings.get("profile_field_previous_keys")
        or settings.get("profile_field_old_keys")
    )


def sensitive_field_previous_keys_available(settings: dict | None = None) -> bool:
    return bool(previous_profile_field_key_materials(settings))


def _candidate_keys(settings: dict | None = None) -> list[bytes]:
    materials: list[str] = []
    current = _key_material(settings)
    if current:
        materials.append(current)
    for old in previous_profile_field_key_materials(settings):
        if old and old not in materials:
            materials.append(old)
    keys: list[bytes] = []
    for material in materials:
        key = _derive_key_from_material(material)
        if key and key not in keys:
            keys.append(key)
    return keys


def _b64u_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64u_decode(raw: str) -> bytes:
    raw = str(raw or "")
    raw += "=" * (-len(raw) % 4)
    return base64.urlsafe_b64decode(raw.encode("ascii"))


def _aad(field_name: str) -> bytes:
    clean = str(field_name or "users.profile").strip().lower()[:80]
    return _AAD_PREFIX + clean.encode("utf-8", "ignore")


def is_encrypted_sensitive_field(value: Any) -> bool:
    return isinstance(value, str) and value.startswith(SENSITIVE_FIELD_PREFIX)


def encrypt_sensitive_field(value: Any, settings: dict | None = None, *, field_name: str = "users.profile") -> str | None:
    """Encrypt a non-empty value, returning a versioned text envelope.

    If encryption is disabled or no key material exists, the original value is
    returned. That keeps local/dev installs from breaking, while production can
    enforce a stable key through SECRET_KEY or ECHOCHAT_PROFILE_FIELD_KEY.
    """
    if value is None:
        return None
    text = str(value)
    if text == "":
        return None
    if is_encrypted_sensitive_field(text):
        return text
    if not sensitive_field_encryption_enabled(settings):
        return text
    key = _derive_key(settings)
    if not key:
        return text
    nonce = os.urandom(12)
    ciphertext = AESGCM(key).encrypt(nonce, text.encode("utf-8"), _aad(field_name))
    return SENSITIVE_FIELD_PREFIX + _b64u_encode(nonce + ciphertext)


def decrypt_sensitive_field(value: Any, settings: dict | None = None, *, field_name: str = "users.profile") -> str:
    """Decrypt a versioned sensitive field; plaintext legacy values pass through.

    During key rotation, decryption tries the active key first and then
    ECHOCHAT_PROFILE_FIELD_PREVIOUS_KEYS / profile_field_previous_keys. That
    lets admins deploy a new current key while old envelopes remain readable
    until the rotation tool rewrites them.
    """
    if value is None:
        return ""
    text = str(value)
    if not text:
        return ""
    if not is_encrypted_sensitive_field(text):
        return text
    try:
        packed = _b64u_decode(text[len(SENSITIVE_FIELD_PREFIX):])
        if len(packed) < 13:
            return ""
        nonce, ciphertext = packed[:12], packed[12:]
    except Exception:
        return ""
    for key in _candidate_keys(settings):
        try:
            return AESGCM(key).decrypt(nonce, ciphertext, _aad(field_name)).decode("utf-8", "replace")
        except Exception:
            continue
    return ""


def reencrypt_sensitive_field(value: Any, settings: dict | None = None, *, field_name: str = "users.profile") -> tuple[str | None, bool, bool]:
    """Return (new_value, changed, decryptable) encrypted with the active key.

    Plaintext legacy values are encrypted. Envelopes decryptable with previous
    keys are re-encrypted under the current key. Undecryptable envelopes are
    left untouched and reported as not decryptable.
    """
    if value is None or str(value) == "":
        return None, False, True
    original = str(value)
    plaintext = decrypt_sensitive_field(original, settings, field_name=field_name)
    if is_encrypted_sensitive_field(original) and not plaintext:
        return original, False, False
    if plaintext == "":
        return None, original != "", True
    new_value = encrypt_sensitive_field(plaintext, settings, field_name=field_name)
    return new_value, new_value != original, True
