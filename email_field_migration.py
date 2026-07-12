"""Bulk migration helpers for encrypted-at-rest user emails."""

from __future__ import annotations

from typing import Any

from database import get_db
from email_at_rest import (
    EMAIL_ENCRYPTED_PREFIX,
    decrypt_email,
    display_email,
    email_encryption_enabled,
    email_field_key_available,
    email_hash_key_available,
    hash_email,
    is_encrypted_email,
    prepare_email_storage,
)


def _emptyish(value: Any) -> bool:
    return value is None or str(value).strip() == ""


def email_encryption_counts(settings: dict | None = None) -> dict:
    settings = settings or {}
    out = {
        "users_total": 0,
        "email_plaintext": 0,
        "email_encrypted": 0,
        "email_hash_present": 0,
        "email_hash_missing": 0,
        "email_undecryptable": 0,
        "enabled": email_encryption_enabled(settings),
        "field_key_available": email_field_key_available(settings),
        "hash_key_available": email_hash_key_available(settings),
    }
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, email, email_hash, email_encrypted
              FROM users
             ORDER BY id;
            """
        )
        rows = cur.fetchall() or []
    out["users_total"] = len(rows)
    for _id, legacy_email, email_hash_value, email_encrypted in rows:
        has_legacy = not _emptyish(legacy_email)
        has_encrypted = is_encrypted_email(email_encrypted)
        has_hash = not _emptyish(email_hash_value)
        if has_legacy:
            out["email_plaintext"] += 1
        if has_encrypted:
            out["email_encrypted"] += 1
            if not decrypt_email(email_encrypted, settings):
                out["email_undecryptable"] += 1
        if has_hash:
            out["email_hash_present"] += 1
        elif has_legacy or has_encrypted:
            out["email_hash_missing"] += 1
    return out


def encrypt_plaintext_emails(settings: dict | None = None, *, limit: int = 2500, dry_run: bool = False) -> dict:
    """Encrypt legacy plaintext emails and fill missing email_hash values."""
    settings = settings or {}
    result = {
        "ok": True,
        "mode": "encrypt_plaintext_emails",
        "scanned": 0,
        "updated_users": 0,
        "updated_fields": 0,
        "skipped_no_key": False,
        "dry_run": bool(dry_run),
    }
    if email_encryption_enabled(settings) and not email_field_key_available(settings):
        result["ok"] = False
        result["skipped_no_key"] = True
        result["error"] = "Missing HUI_EMAIL_FIELD_KEY, HUI_PROFILE_FIELD_KEY, or stable SECRET_KEY"
        return result
    limit = max(1, min(int(limit or 2500), 100000))
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute("SELECT id, email, email_hash, email_encrypted FROM users ORDER BY id LIMIT %s;", (limit,))
        rows = cur.fetchall() or []
        result["scanned"] = len(rows)
        for user_id, legacy_email, email_hash_value, email_encrypted in rows:
            plain = display_email(legacy_email, email_encrypted, settings)
            if not plain:
                continue
            legacy_to_store, hash_to_store, encrypted_to_store = prepare_email_storage(plain, settings)
            patch = {}
            # If encryption succeeded, remove old raw email from users.email.
            if legacy_email != legacy_to_store:
                patch["email"] = legacy_to_store
            if hash_to_store and str(email_hash_value or "") != hash_to_store:
                patch["email_hash"] = hash_to_store
            if encrypted_to_store and str(email_encrypted or "") != encrypted_to_store:
                patch["email_encrypted"] = encrypted_to_store
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
