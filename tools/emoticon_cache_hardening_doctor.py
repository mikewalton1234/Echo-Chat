#!/usr/bin/env python3
"""Static checks for beta.442 emoticon cache hardening."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MIN_BETA = 442


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def fail(message: str) -> None:
    print(f"FAIL: {message}")
    sys.exit(1)


def require(text: str, token: str, rel: str) -> None:
    if token not in text:
        fail(f"{rel} missing {token!r}")


def beta_number(version: str) -> int:
    match = re.search(r"beta\.(\d+)", version)
    if not match:
        fail(f"VERSION.txt has unexpected beta version: {version!r}")
    return int(match.group(1))


version = read("VERSION.txt").strip()
if beta_number(version) < MIN_BETA:
    fail(f"VERSION.txt is {version!r}, expected beta.{MIN_BETA} or newer")

picker_js = read("static/js/chat_parts/0008_emoji_picker.js")
routes_main = read("routes_main.py")
emoticon_catalog = read("emoticon_catalog.py")
routes_admin = read("routes_admin_tools.py")
setup_py = read("interactive_setup.py")
server_init = read("server_init.py")
doc = read("docs/EMOTICON_CACHE_HARDENING_beta442.md")

for token in [
    'cache: "force-cache"',
    'ecVersionedStaticUrl("/api/emoticons/catalog")',
]:
    require(picker_js, token, "static/js/chat_parts/0008_emoji_picker.js")

for token in [
    'def _emoticon_catalog_cache_seconds() -> int:',
    'hashlib.sha256(canonical.encode("utf-8")).hexdigest()',
    'request.if_none_match.contains(etag)',
    'resp.set_etag(etag)',
    'stale-while-revalidate',
    'public, max-age=31536000, immutable',
    'public, max-age=604800',
]:
    require(routes_main, token, "routes_main.py")

for token in [
    'from urllib.parse import quote',
    'def _file_cache_token(path: Path | None) -> str:',
    'def _versioned_local_emoticon_url(filename: str, path: Path | None = None) -> str:',
    'def _versioned_static_emoticon_url(filename: str) -> str:',
    'return _versioned_local_emoticon_url(filename, candidate)',
    'static_candidates = [_versioned_static_emoticon_url(name) for name in _candidate_local_files(row)]',
]:
    require(emoticon_catalog, token, "emoticon_catalog.py")

for token in [
    '"emoticons_catalog_cache_seconds": "rawstr"',
    '"emoticons_catalog_cache_seconds": 86400',
    'patch["emoticons_catalog_cache_seconds"] = max(0, min(31536000',
]:
    require(routes_admin, token, "routes_admin_tools.py")

require(setup_py, '"emoticons_catalog_cache_seconds": 86400', "interactive_setup.py")
require(server_init, '"/static/emoticons/"', "server_init.py")

for rel in ["server_config.example.json", "settings.example.json"]:
    data = json.loads(read(rel))
    if data.get("emoticons_catalog_cache_seconds") != 86400:
        fail(f"{rel} should default emoticons_catalog_cache_seconds to 86400")

for token in [
    "cache: \"no-store\"",
    "ETag-backed",
    "max-age=31536000",
    "emoticons_catalog_cache_seconds",
]:
    require(doc, token, "docs/EMOTICON_CACHE_HARDENING_beta442.md")

print("PASS: beta.442 emoticon cache hardening static checks passed")
