#!/usr/bin/env python3
"""Generate Caddy/Nginx reverse proxy configs for Echo-Chat.

Run from the project root:
    python scripts/generate_reverse_proxy_config.py --proxy all --output-dir deploy/generated-proxy
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from reverse_proxy_generator import format_proxy_generation_report, write_proxy_configs


def _fallback_settings() -> dict:
    return {
        "server_name": "Echo-Chat",
        "server_host": "127.0.0.1",
        "server_port": 5000,
        "public_base_url": "https://chat.example.com",
        "trust_proxy_headers": True,
        "auto_allow_lan_origins": False,
        "allowed_origins": ["https://chat.example.com"],
        "cors_allowed_origins": ["https://chat.example.com"],
        "max_request_bytes": 31457280,
        "health_check_endpoint": "/health",
    }


def load_settings(path: Path) -> dict:
    settings = _fallback_settings()
    if path.exists():
        loaded = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            settings.update(loaded)
    return settings


def main() -> int:
    parser = argparse.ArgumentParser(description="generate Echo-Chat reverse proxy configs")
    parser.add_argument("--config", default="server_config.json", help="path to server config JSON")
    parser.add_argument("--proxy", choices=["all", "caddy", "nginx"], default="all", help="which config to generate")
    parser.add_argument("--output-dir", default="deploy/generated-proxy", help="where to write generated config files")
    args = parser.parse_args()

    settings = load_settings(ROOT / args.config)
    written = write_proxy_configs(settings, ROOT / args.output_dir, proxy=args.proxy, repo_root=ROOT)
    print(format_proxy_generation_report(settings, written))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
