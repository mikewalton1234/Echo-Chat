"""Bulk migration and key-rotation helpers for encrypted profile fields."""

from __future__ import annotations

from typing import Any

from database import get_db
from sensitive_fields_crypto import (
    SENSITIVE_FIELD_PREFIX,
    decrypt_sensitive_field,
    encrypt_sensitive_field,
    is_encrypted_sensitive_field,
    reencrypt_sensitive_field,
    sensitive_field_key_available,
    sensitive_field_previous_keys_available,
)

PROFILE_FIELD_NAMES = ("phone", "address", "location_text")
_FIELD_AAD = {
    "phone": "users.phone",
    "address": "users.address",
    "location_text": "users.location_text",
}


def _emptyish(value: Any) -> bool:
    return value is None or str(value) == ""


def profile_field_encryption_counts(settings: dict | None = None) -> dict:
    """Return profile-field encryption posture counts for the admin dashboard."""
    settings = settings or {}
    out = {
        "users_total": 0,
        "phone_encrypted": 0,
        "address_encrypted": 0,
        "location_encrypted": 0,
        "phone_plaintext": 0,
        "address_plaintext": 0,
        "location_plaintext": 0,
        "encrypted_undecryptable": 0,
        "current_key_available": sensitive_field_key_available(settings),
        "previous_keys_available": sensitive_field_previous_keys_available(settings),
    }
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute("SELECT id, phone, address, location_text FROM users ORDER BY id;")
        rows = cur.fetchall() or []
    out["users_total"] = len(rows)
    for _id, phone, address, location_text in rows:
        for column, value in (("phone", phone), ("address", address), ("location", location_text)):
            if _emptyish(value):
                continue
            text = str(value)
            if is_encrypted_sensitive_field(text):
                out[f"{column}_encrypted"] += 1
                if not decrypt_sensitive_field(text, settings, field_name=_FIELD_AAD["location_text" if column == "location" else column]):
                    out["encrypted_undecryptable"] += 1
            else:
                out[f"{column}_plaintext"] += 1
    return out


def encrypt_plaintext_profile_fields(settings: dict | None = None, *, limit: int = 2500, dry_run: bool = False) -> dict:
    """Encrypt legacy plaintext phone/address/location_text rows in bulk."""
    settings = settings or {}
    result = {"ok": True, "mode": "encrypt_plaintext", "scanned": 0, "updated_users": 0, "updated_fields": 0, "skipped_no_key": False, "dry_run": bool(dry_run)}
    if not sensitive_field_key_available(settings):
        result["ok"] = False
        result["skipped_no_key"] = True
        result["error"] = "Missing HUI_PROFILE_FIELD_KEY or stable SECRET_KEY"
        return result
    limit = max(1, min(int(limit or 2500), 100000))
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute("SELECT id, phone, address, location_text FROM users ORDER BY id LIMIT %s;", (limit,))
        rows = cur.fetchall() or []
        result["scanned"] = len(rows)
        for user_id, phone, address, location_text in rows:
            patch = {}
            for column, value in (("phone", phone), ("address", address), ("location_text", location_text)):
                if _emptyish(value) or is_encrypted_sensitive_field(value):
                    continue
                enc = encrypt_sensitive_field(value, settings, field_name=_FIELD_AAD[column])
                if enc != value:
                    patch[column] = enc
            if patch:
                result["updated_users"] += 1
                result["updated_fields"] += len(patch)
                if not dry_run:
                    sets = ", ".join(f"{col} = %s" for col in patch)
                    params = list(patch.values()) + [user_id]
                    cur.execute(f"UPDATE users SET {sets} WHERE id = %s;", params)
        if not dry_run:
            conn.commit()
    return result


def rotate_profile_field_envelopes(settings: dict | None = None, *, limit: int = 2500, dry_run: bool = False) -> dict:
    """Re-encrypt all decryptable sensitive profile fields under the active key.

    Deployment flow: set HUI_PROFILE_FIELD_KEY to the new key, place the
    old key(s) in HUI_PROFILE_FIELD_PREVIOUS_KEYS, run this action, verify
    encrypted_undecryptable is zero, then remove previous keys.
    """
    settings = settings or {}
    result = {
        "ok": True,
        "mode": "rotate",
        "scanned": 0,
        "updated_users": 0,
        "updated_fields": 0,
        "undecryptable_fields": 0,
        "skipped_no_key": False,
        "previous_keys_available": sensitive_field_previous_keys_available(settings),
        "dry_run": bool(dry_run),
    }
    if not sensitive_field_key_available(settings):
        result["ok"] = False
        result["skipped_no_key"] = True
        result["error"] = "Missing HUI_PROFILE_FIELD_KEY or stable SECRET_KEY"
        return result
    limit = max(1, min(int(limit or 2500), 100000))
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute("SELECT id, phone, address, location_text FROM users ORDER BY id LIMIT %s;", (limit,))
        rows = cur.fetchall() or []
        result["scanned"] = len(rows)
        for user_id, phone, address, location_text in rows:
            patch = {}
            for column, value in (("phone", phone), ("address", address), ("location_text", location_text)):
                if _emptyish(value):
                    continue
                new_value, changed, decryptable = reencrypt_sensitive_field(value, settings, field_name=_FIELD_AAD[column])
                if not decryptable:
                    result["undecryptable_fields"] += 1
                    continue
                if changed:
                    patch[column] = new_value
            if patch:
                result["updated_users"] += 1
                result["updated_fields"] += len(patch)
                if not dry_run:
                    sets = ", ".join(f"{col} = %s" for col in patch)
                    params = list(patch.values()) + [user_id]
                    cur.execute(f"UPDATE users SET {sets} WHERE id = %s;", params)
        if not dry_run:
            conn.commit()
    if result["undecryptable_fields"]:
        result["ok"] = False
        result["error"] = "Some encrypted profile fields could not be decrypted with the active or previous keys"
    return result
