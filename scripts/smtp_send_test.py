#!/usr/bin/env python3
"""smtp_send_test.py

Quick one-off test for Echo-Chat SMTP settings in server_config.json.

Usage:
  python scripts/smtp_send_test.py you@domain.com

It will load server_config.json from repo root (same directory as main.py) and send
a plaintext test email using emailer.send_email().
"""

from __future__ import annotations

import json
import os
import sys

# Allow running from scripts/
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

from emailer import send_email  # noqa: E402
from constants import server_display_name  # noqa: E402


def _server_display_name(settings: dict | None = None) -> str:
    return server_display_name(settings)


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: python scripts/smtp_send_test.py <to_email>")
        return 2

    to_email = sys.argv[1].strip()
    cfg_path = os.path.join(ROOT, "server_config.json")
    if not os.path.exists(cfg_path):
        print(f"Missing {cfg_path}. Run: python main.py --setup")
        return 2

    with open(cfg_path, "r", encoding="utf-8") as f:
        settings = json.load(f)

    server_label = _server_display_name(settings)
    ok, info = send_email(
        settings,
        to_email=to_email,
        subject=f"{server_label} SMTP test",
        body_text=f"If you received this, {server_label} SMTP is configured correctly.",
    )

    print("OK" if ok else "FAIL", info)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
