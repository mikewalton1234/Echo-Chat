#!/usr/bin/env python3
"""Static checks for beta.443 local emoticon path normalization."""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MIN_BETA = 443


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

routes_main = read("routes_main.py")
security_py = read("security.py")
doc = read("docs/EMOTICON_PATH_TYPE_FIX_beta443.md")

for token in [
    "def _safe_emoticon_file_path(root, name: str) -> Path | None:",
    "safe_path = safe_existing_file_under(root, name)",
    "candidate = Path(safe_path)",
    "return candidate if candidate.is_file() else None",
    "path = _safe_emoticon_file_path(root, name)",
    "path = _safe_emoticon_file_path(root, safe_name)",
    "send_file(path, mimetype=mimetypes.guess_type(str(path))[0]",
]:
    require(routes_main, token, "routes_main.py")

serve_start = routes_main.find('@app.get("/emoticons/<path:filename>")')
serve_end = routes_main.find('def _profile_notification_settings_for', serve_start)
if serve_start < 0 or serve_end < 0:
    fail("could not isolate serve_local_emoticon route")
serve_slice = routes_main[serve_start:serve_end]
if "path = safe_existing_file_under(root, safe_name)" in serve_slice:
    fail("serve_local_emoticon still assigns raw string path from safe_existing_file_under")
if "path and path.is_file()" in serve_slice:
    fail("serve_local_emoticon still calls .is_file() on an unknown path type")

selftest_start = routes_main.find('@app.get("/api/emoticons/selftest")')
selftest_end = routes_main.find('@app.get("/emoticons/<path:filename>")', selftest_start)
if selftest_start < 0 or selftest_end < 0:
    fail("could not isolate emoticon selftest route")
selftest_slice = routes_main[selftest_start:selftest_end]
if "path = safe_existing_file_under(root, name)" in selftest_slice:
    fail("emoticon selftest still assigns raw string path from safe_existing_file_under")
if "path and path.is_file()" in selftest_slice:
    fail("emoticon selftest still calls .is_file() on an unknown path type")

require(security_py, "def safe_existing_file_under(root: str | os.PathLike, candidate: str | os.PathLike) -> str | None:", "security.py")
for token in [
    "AttributeError: 'str' object has no attribute 'is_file'",
    "_safe_emoticon_file_path(root, name)",
    "Cache-Control: public, max-age=31536000, immutable",
]:
    require(doc, token, "docs/EMOTICON_PATH_TYPE_FIX_beta443.md")

print("PASS: beta.443 emoticon path type static checks passed")
