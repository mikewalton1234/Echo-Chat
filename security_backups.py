"""Security-operation backup/restore helpers.

These snapshots are intentionally narrow. They capture only the user fields that
key-rotation and at-rest-encryption actions rewrite, so admins can roll back an
accidental key/migration operation without dumping password hashes or tokens.

New backups are encrypted by default. A legacy plaintext JSON restore path is
kept so older backups can still be used, but newly-created files should be
``.json.enc`` AES-GCM envelopes.
"""

from __future__ import annotations

import base64
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import json
import os
import re
import tempfile
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from database import get_db
from secret_manager import resolve_secret, stable_email_field_key_material, stable_profile_field_key_material, stable_secret_key_material

BACKUP_ROOT = Path("backups/security")
BACKUP_VERSION = 1
ENCRYPTED_BACKUP_VERSION = 2
ENCRYPTED_BACKUP_PREFIX = "ecsecbackup:v1:"
_BACKUP_RE = re.compile(r"[^a-zA-Z0-9_.-]+")
_BACKUP_KEY_ENV = "ECHOCHAT_SECURITY_BACKUP_KEY"
_AAD = b"EchoChat encrypted security backup v1"
_KEY_DERIVE_PREFIX = b"EchoChat security backup encryption key v1\n"

USER_BACKUP_COLUMNS = (
    "email",
    "email_hash",
    "email_encrypted",
    "phone",
    "address",
    "location_text",
)


def _truthy(value: Any, default: bool = True) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def security_backup_encryption_enabled(settings: dict | None = None) -> bool:
    """Return whether security backups must be encrypted on write."""
    settings = settings or {}
    return _truthy(settings.get("encrypt_security_backups"), True)


def _security_backup_key_material(settings: dict | None = None) -> str:
    settings = settings or {}
    return (
        resolve_secret(settings, "security_backup_encryption_key")
        or stable_profile_field_key_material(settings)
        or stable_email_field_key_material(settings)
    )


def security_backup_key_available(settings: dict | None = None) -> bool:
    return bool(_security_backup_key_material(settings))


def _derive_key(settings: dict | None = None) -> bytes | None:
    material = _security_backup_key_material(settings)
    if not material:
        return None
    return hashlib.sha256(_KEY_DERIVE_PREFIX + material.encode("utf-8")).digest()


def _b64u_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64u_decode(raw: str) -> bytes:
    raw = str(raw or "")
    raw += "=" * (-len(raw) % 4)
    return base64.urlsafe_b64decode(raw.encode("ascii"))


def _safe_label(label: str) -> str:
    clean = _BACKUP_RE.sub("-", str(label or "manual").strip()).strip(".-_")
    return clean[:60] or "manual"


def _backup_dir(settings: dict | None = None) -> Path:
    settings = settings or {}
    root = str(settings.get("security_backup_dir") or os.getenv("ECHOCHAT_SECURITY_BACKUP_DIR") or BACKUP_ROOT)
    return Path(root)


def _build_plain_payload(label: str, rows: list) -> dict:
    return {
        "version": BACKUP_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "label": str(label or "manual"),
        "table": "users",
        "columns": ["id", "username", *USER_BACKUP_COLUMNS],
        "row_count": len(rows),
        "rows": [
            {
                "id": int(r[0]),
                "username": r[1],
                "email": r[2],
                "email_hash": r[3],
                "email_encrypted": r[4],
                "phone": r[5],
                "address": r[6],
                "location_text": r[7],
            }
            for r in rows
        ],
    }


def _encrypt_payload(payload: dict, settings: dict | None = None) -> dict:
    key = _derive_key(settings)
    if not key:
        raise RuntimeError("Missing ECHOCHAT_SECURITY_BACKUP_KEY, ECHOCHAT_PROFILE_FIELD_KEY, ECHOCHAT_EMAIL_FIELD_KEY, or stable SECRET_KEY")
    nonce = os.urandom(12)
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ciphertext = AESGCM(key).encrypt(nonce, raw, _AAD)
    return {
        "version": ENCRYPTED_BACKUP_VERSION,
        "encrypted": True,
        "envelope": ENCRYPTED_BACKUP_PREFIX,
        "cipher": "AES-256-GCM",
        "created_at": payload.get("created_at"),
        "label": payload.get("label"),
        "table": payload.get("table"),
        "columns": payload.get("columns"),
        "row_count": payload.get("row_count"),
        "nonce": _b64u_encode(nonce),
        "ciphertext": _b64u_encode(ciphertext),
    }


def _decrypt_payload(envelope: dict, settings: dict | None = None) -> dict:
    key = _derive_key(settings)
    if not key:
        raise RuntimeError("Missing security backup decryption key")
    nonce = _b64u_decode(str(envelope.get("nonce") or ""))
    ciphertext = _b64u_decode(str(envelope.get("ciphertext") or ""))
    if len(nonce) != 12 or not ciphertext:
        raise RuntimeError("Invalid encrypted security backup envelope")
    raw = AESGCM(key).decrypt(nonce, ciphertext, _AAD)
    return json.loads(raw.decode("utf-8"))


def _atomic_write_json(path: Path, payload: dict) -> None:
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, sort_keys=True)
            fh.write("\n")
        os.replace(tmp_name, path)
        try:
            os.chmod(path, 0o600)
        except Exception:
            pass
    finally:
        try:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)
        except Exception:
            pass


def create_security_backup(label: str = "manual", settings: dict | None = None, *, limit: int = 100000) -> dict:
    settings = settings or {}
    limit = max(1, min(int(limit or 100000), 500000))
    root = _backup_dir(settings)
    root.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(root, 0o700)
    except Exception:
        pass
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    encrypt = security_backup_encryption_enabled(settings)
    if encrypt and not security_backup_key_available(settings):
        return {"ok": False, "error": "Security backup encryption is enabled, but no backup key is available", "encrypted": False, "label": str(label or "manual")}
    filename = f"echochat-security-{ts}-{_safe_label(label)}.json" + (".enc" if encrypt else "")
    path = root / filename
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, username, email, email_hash, email_encrypted, phone, address, location_text
              FROM users
             ORDER BY id
             LIMIT %s;
            """,
            (limit,),
        )
        rows = cur.fetchall() or []
    plain_payload = _build_plain_payload(label, rows)
    try:
        payload = _encrypt_payload(plain_payload, settings) if encrypt else plain_payload
        _atomic_write_json(path, payload)
    except Exception as exc:
        return {"ok": False, "error": str(exc), "encrypted": bool(encrypt), "label": str(label or "manual")}
    return {"ok": True, "path": str(path), "filename": filename, "row_count": len(rows), "label": str(label or "manual"), "encrypted": bool(encrypt)}


def _backup_files(root: Path) -> list[Path]:
    if not root.exists():
        return []
    files = list(root.glob("echochat-security-*.json.enc")) + list(root.glob("echochat-security-*.json"))
    return sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)


def list_security_backups(settings: dict | None = None, *, limit: int = 10) -> list[dict]:
    root = _backup_dir(settings)
    out = []
    for p in _backup_files(root)[: max(1, min(int(limit or 10), 50))]:
        meta = {"filename": p.name, "path": str(p), "size_bytes": p.stat().st_size, "modified_at": datetime.fromtimestamp(p.stat().st_mtime, timezone.utc).isoformat(), "encrypted": p.name.endswith(".enc")}
        try:
            with p.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
            meta["encrypted"] = bool(data.get("encrypted")) or p.name.endswith(".enc")
            meta["created_at"] = data.get("created_at")
            meta["label"] = data.get("label")
            meta["row_count"] = data.get("row_count")
        except Exception:
            meta["error"] = "unreadable"
        out.append(meta)
    return out


def _load_backup_payload(path: Path, settings: dict | None = None) -> dict:
    with path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    if bool(data.get("encrypted")) or path.name.endswith(".enc"):
        data = _decrypt_payload(data, settings)
    return data


def restore_security_backup(filename: str | None = None, settings: dict | None = None) -> dict:
    root = _backup_dir(settings)
    backups = list_security_backups(settings, limit=1)
    if filename:
        name = Path(str(filename)).name
        path = root / name
    elif backups:
        path = Path(backups[0]["path"])
    else:
        return {"ok": False, "error": "No security backup found"}
    try:
        real_root = root.resolve()
        real_path = path.resolve()
        if real_root not in real_path.parents and real_path != real_root:
            return {"ok": False, "error": "Invalid backup path"}
    except Exception:
        return {"ok": False, "error": "Invalid backup path"}
    if not path.exists():
        return {"ok": False, "error": "Backup file not found"}
    try:
        data = _load_backup_payload(path, settings)
    except Exception as exc:
        return {"ok": False, "error": f"Unable to read/decrypt security backup: {exc}"}
    if int(data.get("version") or 0) != BACKUP_VERSION or data.get("table") != "users":
        return {"ok": False, "error": "Unsupported security backup format"}
    rows = data.get("rows") or []
    conn = get_db()
    restored = 0
    with conn.cursor() as cur:
        for row in rows:
            user_id = row.get("id")
            username = row.get("username")
            if not user_id or not username:
                continue
            cur.execute(
                """
                UPDATE users
                   SET email = %s,
                       email_hash = %s,
                       email_encrypted = %s,
                       phone = %s,
                       address = %s,
                       location_text = %s
                 WHERE id = %s AND username = %s;
                """,
                (
                    row.get("email"),
                    row.get("email_hash"),
                    row.get("email_encrypted"),
                    row.get("phone"),
                    row.get("address"),
                    row.get("location_text"),
                    int(user_id),
                    username,
                ),
            )
            restored += int(cur.rowcount or 0)
        conn.commit()
    return {"ok": True, "path": str(path), "filename": path.name, "restored_users": restored, "row_count": len(rows), "encrypted": path.name.endswith(".enc")}
