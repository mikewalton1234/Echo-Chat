#!/usr/bin/env python3
"""Static checks for beta.441 emoticon boot preloading."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MIN_BETA = 441


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
boot_js = read("static/js/chat_parts/0048_boot_presence_dom.js")
routes_auth = read("routes_auth.py")
routes_admin = read("routes_admin_tools.py")
setup_py = read("interactive_setup.py")
readme = read("README.md")
doc = read("docs/EMOTICON_BOOT_PRELOAD_beta441.md")

for token in [
    "assetPreloadPromise",
    "assetsPreloaded",
    "preloadedSrcs: new Set()",
    "function ecEmoticonBootPreloadEnabled()",
    "function ecEmoticonBootPreloadLimit()",
    "function ecEmoticonBootPreloadConcurrency()",
    "function ecOnBrowserIdle(callback",
    "function ecPreloadEmoticonImage(entry)",
    "async function ecPreloadCodeEmoticonAssets(opts = {})",
    "function ecPrimeEmoticonsOnChatBoot(opts = {})",
    "ensureCodeEmoticonsLoaded({ retryOnEmpty: true })",
    "requestIdleCallback",
    "new Image()",
    "ec:emoticon-assets-preloaded",
    "window.ecPreloadCodeEmoticonAssets = ecPreloadCodeEmoticonAssets",
    "window.ecPrimeEmoticonsOnChatBoot = ecPrimeEmoticonsOnChatBoot",
    "ecPrimeEmoticonsOnChatBoot({ reason: \"module-load\" })",
]:
    require(picker_js, token, "static/js/chat_parts/0008_emoji_picker.js")

require(boot_js, "ecPrimeEmoticonsOnChatBoot({ reason: \"dom-boot\" })", "static/js/chat_parts/0048_boot_presence_dom.js")

for token in [
    '"emoticons_boot_preload_enabled": _client_bool_setting("emoticons_boot_preload_enabled", True)',
    '"emoticons_boot_preload_limit": _client_int_setting("emoticons_boot_preload_limit", 180, minimum=0, maximum=240)',
    '"emoticons_boot_preload_concurrency": _client_int_setting("emoticons_boot_preload_concurrency", 4, minimum=1, maximum=8)',
]:
    require(routes_auth, token, "routes_auth.py")

for token in [
    '"emoticons_boot_preload_enabled": "bool"',
    '"emoticons_boot_preload_limit": "rawstr"',
    '"emoticons_boot_preload_concurrency": "rawstr"',
    'patch["emoticons_boot_preload_limit"] = max(0, min(240',
    'patch["emoticons_boot_preload_concurrency"] = max(1, min(8',
]:
    require(routes_admin, token, "routes_admin_tools.py")

for rel in ["server_config.example.json", "settings.example.json"]:
    data = json.loads(read(rel))
    if data.get("emoticons_boot_preload_enabled") is not True:
        fail(f"{rel} should default emoticons_boot_preload_enabled to true")
    if data.get("emoticons_boot_preload_limit") != 180:
        fail(f"{rel} should default emoticons_boot_preload_limit to 180")
    if data.get("emoticons_boot_preload_concurrency") != 4:
        fail(f"{rel} should default emoticons_boot_preload_concurrency to 4")

for token in [
    '"emoticons_boot_preload_enabled": True',
    '"emoticons_boot_preload_limit": 180',
    '"emoticons_boot_preload_concurrency": 4',
]:
    require(setup_py, token, "interactive_setup.py")

for token in [
    "emoticon",
    "image assets warm up automatically",
]:
    require(readme, token, "README.md")

for token in [
    "ecPrimeEmoticonsOnChatBoot()",
    "catalog-only boot loading",
    "python tools/emoticon_boot_preload_doctor.py",
]:
    require(doc, token, "docs/EMOTICON_BOOT_PRELOAD_beta441.md")

print("PASS: beta.441 emoticon boot preload static checks passed")
