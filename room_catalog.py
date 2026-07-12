#!/usr/bin/env python3
"""Official Hui Chat room catalog loading/normalization helpers.

The official room browser, database preload, and room-media code all consume
``chat_rooms.json``.  Keep parsing here so one malformed catalog entry cannot
silently break a different subsystem or make startup prune the wrong rows.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parent
DEFAULT_ROOM_CATALOG_PATH = ROOT_DIR / "chat_rooms.json"
EMPTY_ROOM_CATALOG: dict[str, Any] = {"version": 2, "categories": []}


def _safe_catalog_version(value: Any, *, default: int = 2) -> int:
    try:
        version = int(value)
    except Exception:
        version = default
    return max(2, min(version, 99))


def _clean_text(value: Any, *, max_len: int = 120) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return text[:max_len]


def normalize_catalog_station(entry: Any) -> dict[str, str] | None:
    """Normalize one station row without trusting admin-edited JSON blindly."""
    if not isinstance(entry, dict):
        return None
    label = _clean_text(entry.get("label") or entry.get("name"), max_len=80)
    provider = _clean_text(entry.get("provider"), max_len=80)
    page_url = _clean_text(entry.get("page_url") or entry.get("url"), max_len=600)
    embed_url = _clean_text(entry.get("embed_url"), max_len=600)
    if not label and not page_url and not embed_url:
        return None
    out: dict[str, str] = {}
    if label:
        out["label"] = label
    if provider:
        out["provider"] = provider
    if page_url:
        out["page_url"] = page_url
    if embed_url:
        out["embed_url"] = embed_url
    return out or None


def normalize_catalog_room_entry(entry: Any) -> dict[str, Any] | None:
    """Normalize one official room entry to the object shape used by the UI."""
    if isinstance(entry, str):
        name = _clean_text(entry, max_len=80)
        return {"name": name} if name else None
    if not isinstance(entry, dict):
        return None
    name = _clean_text(entry.get("name"), max_len=80)
    if not name:
        return None

    out: dict[str, Any] = {"name": name}
    description = _clean_text(entry.get("description"), max_len=240)
    topic = _clean_text(entry.get("topic"), max_len=160)
    if description:
        out["description"] = description
    if topic:
        out["topic"] = topic

    tags = entry.get("tags") or []
    if isinstance(tags, list):
        clean_tags: list[str] = []
        seen_tags: set[str] = set()
        for tag in tags:
            clean = _clean_text(tag, max_len=40)
            key = clean.lower()
            if clean and key not in seen_tags:
                seen_tags.add(key)
                clean_tags.append(clean)
            if len(clean_tags) >= 8:
                break
        if clean_tags:
            out["tags"] = clean_tags

    features = entry.get("features") or []
    if isinstance(features, list):
        clean_features: list[str] = []
        seen_features: set[str] = set()
        for flag in features:
            clean = _clean_text(flag, max_len=64)
            key = clean.lower()
            if clean and key not in seen_features:
                seen_features.add(key)
                clean_features.append(clean)
            if len(clean_features) >= 12:
                break
        if clean_features:
            out["features"] = clean_features

    stations = entry.get("stations") or []
    if isinstance(stations, list):
        clean_stations: list[dict[str, str]] = []
        for station in stations:
            normalized = normalize_catalog_station(station)
            if normalized:
                clean_stations.append(normalized)
            if len(clean_stations) >= 16:
                break
        if clean_stations:
            out["stations"] = clean_stations

    return out


def normalize_room_catalog_data(data: Any) -> dict[str, Any]:
    """Return a stable official catalog dict for any supported JSON schema.

    Supported shapes:
      - current object schema: {version, categories:[{name, subcategories:[...]}]}
      - legacy list schema: ["Lobby", {"name":"Support"}, ...]
    """
    if isinstance(data, list):
        rooms: list[dict[str, Any]] = []
        seen: set[str] = set()
        for entry in data:
            room = normalize_catalog_room_entry(entry)
            if not room:
                continue
            key = str(room.get("name") or "").strip().lower()
            if not key or key in seen:
                continue
            seen.add(key)
            rooms.append(room)
        return {
            "version": 2,
            "categories": [{"name": "Rooms", "subcategories": [{"name": "All", "rooms": rooms}]}],
        }

    if not isinstance(data, dict):
        return dict(EMPTY_ROOM_CATALOG)

    categories = data.get("categories") or []
    if not isinstance(categories, list):
        categories = []

    normalized_categories: list[dict[str, Any]] = []
    global_seen_rooms: set[str] = set()
    for category in categories:
        if not isinstance(category, dict):
            continue
        category_name = _clean_text(category.get("name"), max_len=80)
        if not category_name:
            continue
        subcategories = category.get("subcategories") or []
        if not isinstance(subcategories, list):
            subcategories = []
        normalized_subcategories: list[dict[str, Any]] = []
        for subcategory in subcategories:
            if not isinstance(subcategory, dict):
                continue
            subcategory_name = _clean_text(subcategory.get("name"), max_len=80)
            if not subcategory_name:
                continue
            rooms = subcategory.get("rooms") or []
            if not isinstance(rooms, list):
                rooms = []
            normalized_rooms: list[dict[str, Any]] = []
            for room_entry in rooms:
                room = normalize_catalog_room_entry(room_entry)
                if not room:
                    continue
                key = str(room.get("name") or "").strip().lower()
                if not key or key in global_seen_rooms:
                    continue
                global_seen_rooms.add(key)
                normalized_rooms.append(room)
            normalized_subcategories.append({"name": subcategory_name, "rooms": normalized_rooms})
        normalized_categories.append({"name": category_name, "subcategories": normalized_subcategories})

    return {"version": _safe_catalog_version(data.get("version", 2)), "categories": normalized_categories}


def read_official_room_catalog(path: str | Path | None = None, *, logger: logging.Logger | None = None) -> dict[str, Any]:
    """Read and normalize ``chat_rooms.json`` with safe empty fallback."""
    catalog_path = Path(path) if path is not None else DEFAULT_ROOM_CATALOG_PATH
    log = logger or logging.getLogger(__name__)
    try:
        raw = catalog_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        log.warning("Official room catalog not found: %s", catalog_path)
        return dict(EMPTY_ROOM_CATALOG)
    except OSError as exc:
        log.error("Could not read official room catalog %s: %s", catalog_path, exc)
        return dict(EMPTY_ROOM_CATALOG)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        log.error("Bad official room catalog JSON %s: %s", catalog_path, exc)
        return dict(EMPTY_ROOM_CATALOG)
    except Exception as exc:
        log.error("Could not parse official room catalog %s: %s", catalog_path, exc)
        return dict(EMPTY_ROOM_CATALOG)
    return normalize_room_catalog_data(data)


def official_room_names_from_catalog(catalog: dict[str, Any] | None) -> list[str]:
    """Return unique official room names in catalog order."""
    names: list[str] = []
    seen: set[str] = set()
    if not isinstance(catalog, dict):
        return names
    for category in catalog.get("categories") or []:
        if not isinstance(category, dict):
            continue
        for subcategory in category.get("subcategories") or []:
            if not isinstance(subcategory, dict):
                continue
            for room in subcategory.get("rooms") or []:
                name = ""
                if isinstance(room, str):
                    name = _clean_text(room, max_len=80)
                elif isinstance(room, dict):
                    name = _clean_text(room.get("name"), max_len=80)
                if not name:
                    continue
                key = name.lower()
                if key in seen:
                    continue
                seen.add(key)
                names.append(name)
    return names


def official_room_names_from_data(data: Any) -> list[str]:
    """Compatibility helper for callers that already loaded JSON data."""
    return official_room_names_from_catalog(normalize_room_catalog_data(data))


def catalog_has_room(catalog: dict[str, Any] | None, room_name: str) -> bool:
    target = _clean_text(room_name, max_len=80).lower()
    if not target:
        return False
    return any(name.lower() == target for name in official_room_names_from_catalog(catalog))



def find_catalog_room_location(catalog: dict[str, Any] | None, room_name: str) -> dict[str, Any] | None:
    """Return official room metadata plus category/subcategory for a room name.

    The returned shape is intentionally small and JSON-safe so Socket.IO join
    acknowledgements and browser room rows can preserve official-room context
    without trusting stale selected-row state.
    """
    target = _clean_text(room_name, max_len=80).lower()
    if not target or not isinstance(catalog, dict):
        return None
    for category in catalog.get("categories") or []:
        if not isinstance(category, dict):
            continue
        category_name = _clean_text(category.get("name"), max_len=80)
        for subcategory in category.get("subcategories") or []:
            if not isinstance(subcategory, dict):
                continue
            subcategory_name = _clean_text(subcategory.get("name"), max_len=80)
            for room in subcategory.get("rooms") or []:
                normalized = normalize_catalog_room_entry(room)
                if normalized and str(normalized.get("name") or "").strip().lower() == target:
                    return {
                        "name": str(normalized.get("name") or "").strip(),
                        "category": category_name,
                        "subcategory": subcategory_name,
                        "meta": normalized,
                    }
    return None


def find_catalog_room_entry(catalog: dict[str, Any] | None, room_name: str) -> dict[str, Any] | None:
    target = _clean_text(room_name, max_len=80).lower()
    if not target or not isinstance(catalog, dict):
        return None
    for category in catalog.get("categories") or []:
        if not isinstance(category, dict):
            continue
        for subcategory in category.get("subcategories") or []:
            if not isinstance(subcategory, dict):
                continue
            for room in subcategory.get("rooms") or []:
                normalized = normalize_catalog_room_entry(room)
                if normalized and str(normalized.get("name") or "").strip().lower() == target:
                    return normalized
    return None
