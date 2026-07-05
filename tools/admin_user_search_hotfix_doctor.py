#!/usr/bin/env python3
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
checks = [
    ("routes_admin_tools.py", "def _admin_table_columns"),
    ("routes_admin_tools.py", "def _admin_table_exists"),
    ("routes_admin_tools.py", 'schema_tolerant'),
    ("routes_admin_tools.py", 'enhanced user search failed; falling back to username-only search'),
    ("routes_admin_tools.py", 'email_hash_col'),
    ("routes_admin_tools.py", 'email_encrypted_select'),
    ("admin_panel_inject.py", 'legacy_admin_users'),
    ("admin_panel_inject.py", "/admin/users?"),
]
failed = 0
for rel, needle in checks:
    p = ROOT / rel
    text = p.read_text(errors="replace") if p.exists() else ""
    if needle in text:
        print(f"PASS {rel}: {needle}")
    else:
        print(f"FAIL {rel}: missing {needle}")
        failed += 1
sys.exit(1 if failed else 0)
