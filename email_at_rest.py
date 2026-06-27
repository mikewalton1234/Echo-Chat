"""Encrypted-at-rest email helpers for EchoChat users.

New writes store email lookup material as:
  - users.email_hash: deterministic keyed HMAC over normalized email
  - users.email_encrypted: AES-GCM envelope for display/send workflows

The legacy users.email column remains readable for old rows, but new encrypted
writes set it to NULL so raw email addresses are not kept in the main user row.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

EMAIL_ENCRYPTED_PREFIX = "ecemail:v1:"
_EMAIL_FIELD_KEY_ENV = "ECHOCHAT_EMAIL_FIELD_KEY"
_EMAIL_HASH_KEY_ENV = "ECHOCHAT_EMAIL_HASH_KEY"
_AAD = b"EchoChat user email encrypted at rest v1"
_ENC_DERIVE_PREFIX = b"EchoChat email encryption key v1\n"
_HASH_DERIVE_PREFIX = b"EchoChat email lookup hash key v1\n"
_HASH_MSG_PREFIX = b"EchoChat normalized email v1\n"


def _truthy(value: Any, default: bool = True) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def email_encryption_enabled(settings: dict | None = None) -> bool:
    settings = settings or {}
    return _truthy(settings.get("encrypt_email_at_rest"), True)


def normalize_email(value: Any) -> str:
    return str(value or "").strip().lower()


def _email_key_material(settings: dict | None = None) -> str:
    settings = settings or {}
    return (
        os.getenv(_EMAIL_FIELD_KEY_ENV)
        or str(settings.get("email_field_encryption_key") or "").strip()
        or os.getenv("ECHOCHAT_PROFILE_FIELD_KEY")
        or str(settings.get("profile_field_encryption_key") or "").strip()
        or os.getenv("SECRET_KEY")
        or str(settings.get("secret_key") or "").strip()
    )


def _hash_key_material(settings: dict | None = None) -> str:
    settings = settings or {}
    return (
        os.getenv(_EMAIL_HASH_KEY_ENV)
        or str(settings.get("email_hash_key") or "").strip()
        or _email_key_material(settings)
    )


def email_field_key_available(settings: dict | None = None) -> bool:
    return bool(_email_key_material(settings))


def email_hash_key_available(settings: dict | None = None) -> bool:
    return bool(_hash_key_material(settings))


def _derive_enc_key(settings: dict | None = None) -> bytes | None:
    material = _email_key_material(settings)
    if not material:
        return None
    return hashlib.sha256(_ENC_DERIVE_PREFIX + material.encode("utf-8")).digest()


def _derive_hash_key(settings: dict | None = None) -> bytes | None:
    material = _hash_key_material(settings)
    if not material:
        return None
    return hashlib.sha256(_HASH_DERIVE_PREFIX + material.encode("utf-8")).digest()


def _b64u_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64u_decode(raw: str) -> bytes:
    raw = str(raw or "")
    raw += "=" * (-len(raw) % 4)
    return base64.urlsafe_b64decode(raw.encode("ascii"))


def is_encrypted_email(value: Any) -> bool:
    return isinstance(value, str) and value.startswith(EMAIL_ENCRYPTED_PREFIX)


def hash_email(value: Any, settings: dict | None = None) -> str:
    """Return a stable lookup hash for a normalized email.

    Prefer keyed HMAC when ECHOCHAT_EMAIL_HASH_KEY / ECHOCHAT_EMAIL_FIELD_KEY /
    SECRET_KEY exists. A deterministic SHA-256 fallback keeps dev databases usable
    but production should provide a stable key and keep it backed up.
    """
    email = normalize_email(value)
    if not email:
        return ""
    key = _derive_hash_key(settings)
    msg = _HASH_MSG_PREFIX + email.encode("utf-8")
    if key:
        return "h1:" + hmac.new(key, msg, hashlib.sha256).hexdigest()
    return "s1:" + hashlib.sha256(msg).hexdigest()


def encrypt_email(value: Any, settings: dict | None = None) -> str | None:
    email = normalize_email(value)
    if not email:
        return None
    if is_encrypted_email(email):
        return email
    if not email_encryption_enabled(settings):
        return email
    key = _derive_enc_key(settings)
    if not key:
        return email
    nonce = os.urandom(12)
    ct = AESGCM(key).encrypt(nonce, email.encode("utf-8"), _AAD)
    return EMAIL_ENCRYPTED_PREFIX + _b64u_encode(nonce + ct)


def decrypt_email(value: Any, settings: dict | None = None) -> str:
    if value is None:
        return ""
    text = str(value or "").strip()
    if not text:
        return ""
    if not is_encrypted_email(text):
        return normalize_email(text)
    key = _derive_enc_key(settings)
    if not key:
        return ""
    try:
        packed = _b64u_decode(text[len(EMAIL_ENCRYPTED_PREFIX):])
        if len(packed) < 13:
            return ""
        nonce, ct = packed[:12], packed[12:]
        return AESGCM(key).decrypt(nonce, ct, _AAD).decode("utf-8", "replace")
    except Exception:
        return ""


def display_email(legacy_email: Any = None, encrypted_email: Any = None, settings: dict | None = None) -> str:
    """Return plaintext email for display/send from encrypted or legacy values."""
    plain = decrypt_email(encrypted_email, settings)
    if plain:
        return plain
    return normalize_email(legacy_email)


def prepare_email_storage(value: Any, settings: dict | None = None) -> tuple[str | None, str | None, str | None]:
    """Return (legacy_email, email_hash, email_encrypted) for INSERT/UPDATE.

    When email encryption is enabled and a field key is available, legacy_email is
    NULL and the email lives in email_encrypted. Otherwise, legacy_email keeps the
    normalized plaintext value for local/dev compatibility.
    """
    email = normalize_email(value)
    if not email:
        return None, None, None
    h = hash_email(email, settings)
    enc = encrypt_email(email, settings)
    if email_encryption_enabled(settings) and enc and is_encrypted_email(enc):
        return None, h, enc
    return email, h, enc


def submitted_email_matches(submitted: Any, *, legacy_email: Any = None, email_hash_value: Any = None, email_encrypted: Any = None, settings: dict | None = None) -> bool:
    submitted_norm = normalize_email(submitted)
    if not submitted_norm:
        return False
    stored_hash = str(email_hash_value or "").strip()
    if stored_hash and stored_hash == hash_email(submitted_norm, settings):
        return True
    stored_plain = display_email(legacy_email, email_encrypted, settings)
    return bool(stored_plain and stored_plain == submitted_norm)
