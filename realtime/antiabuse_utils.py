"""Helpers for anti-abuse classification and shared rate-limit metadata."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any


ROOM_MESSAGE_KIND_TEXT = "text"
ROOM_MESSAGE_KIND_GIF = "gif"
ROOM_MESSAGE_KIND_TORRENT = "torrent"
ROOM_MESSAGE_KIND_FILE = "file"

_ROOM_KIND_ALIASES = {
    "msg": ROOM_MESSAGE_KIND_TEXT,
    "message": ROOM_MESSAGE_KIND_TEXT,
    "plain": ROOM_MESSAGE_KIND_TEXT,
    "plaintext": ROOM_MESSAGE_KIND_TEXT,
    "text": ROOM_MESSAGE_KIND_TEXT,
    "gif": ROOM_MESSAGE_KIND_GIF,
    "image/gif": ROOM_MESSAGE_KIND_GIF,
    "torrent": ROOM_MESSAGE_KIND_TORRENT,
    "magnet": ROOM_MESSAGE_KIND_TORRENT,
    "file": ROOM_MESSAGE_KIND_FILE,
    "upload": ROOM_MESSAGE_KIND_FILE,
}

_SHA256_HEX_RE = re.compile(r"^[0-9a-f]{64}$")
_DUPLICATE_SPACE_RE = re.compile(r"\s+")


def normalize_room_message_kind(value: Any) -> str:
    raw = str(value or "").strip().lower()
    return _ROOM_KIND_ALIASES.get(raw, ROOM_MESSAGE_KIND_TEXT)


def normalize_duplicate_message_text(value: Any) -> str:
    if value is None:
        return ""
    raw = str(value)
    raw = _DUPLICATE_SPACE_RE.sub(" ", raw.strip().lower())
    return raw


def build_duplicate_message_signature(message: Any, *, message_kind: Any = None, normalize: bool = False) -> str:
    kind = normalize_room_message_kind(message_kind)
    body = normalize_duplicate_message_text(message) if normalize else str(message or "")
    payload = (f"{kind}\n{body}").encode("utf-8", errors="ignore")
    return hashlib.sha256(payload).hexdigest()


def coerce_duplicate_message_signature(value: Any) -> str | None:
    if value is None:
        return None
    raw = str(value).strip().lower()
    if not _SHA256_HEX_RE.fullmatch(raw):
        return None
    return raw


def infer_room_message_kind_from_plaintext(message: Any) -> str:
    if not isinstance(message, str):
        return ROOM_MESSAGE_KIND_TEXT
    raw = message.strip()
    if not raw:
        return ROOM_MESSAGE_KIND_TEXT
    if raw.lower().startswith("gif:"):
        return ROOM_MESSAGE_KIND_GIF
    try:
        obj = json.loads(raw)
    except Exception:
        obj = None
    if isinstance(obj, dict):
        kind = normalize_room_message_kind(obj.get("_ec") or obj.get("kind") or obj.get("type"))
        if kind != ROOM_MESSAGE_KIND_TEXT:
            return kind
        if str(obj.get("magnet") or "").strip() or str(obj.get("infohash") or obj.get("infohash_hex") or "").strip():
            return ROOM_MESSAGE_KIND_TORRENT
    return ROOM_MESSAGE_KIND_TEXT


def infer_room_message_kind(*, declared_kind: Any = None, plaintext: Any = None, cipher: Any = None) -> str:
    kind = normalize_room_message_kind(declared_kind)
    if declared_kind and kind != ROOM_MESSAGE_KIND_TEXT:
        return kind
    inferred = infer_room_message_kind_from_plaintext(plaintext)
    if inferred != ROOM_MESSAGE_KIND_TEXT:
        return inferred
    if cipher:
        return ROOM_MESSAGE_KIND_TEXT
    return ROOM_MESSAGE_KIND_TEXT
