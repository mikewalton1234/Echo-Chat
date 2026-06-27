#!/usr/bin/env python3
"""janitor_runner.py

Run the EchoChat background cleanup loop as a dedicated process.

Why?
- If you run EchoChat under Gunicorn with N workers, starting the janitor thread
  inside each worker creates N janitors.
- Running this as a single service keeps cleanup predictable and light.

Usage:
  python janitor_runner.py --config server_config.json

Or via env:
  ECHOCHAT_CONFIG=/path/to/server_config.json python janitor_runner.py
"""

from __future__ import annotations

import argparse
import os
import time
from pathlib import Path

from constants import CONFIG_FILE
from main import load_settings, apply_env_overrides, configure_logging
from database import init_db_pool
from db.core import prepare_runtime_database
from janitor import start_janitor


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="EchoChat janitor runner")
    p.add_argument(
        "--config",
        default=os.environ.get("ECHOCHAT_CONFIG") or CONFIG_FILE,
        help="path to server config JSON",
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()
    settings_path = Path(args.config)

    settings = load_settings(settings_path)
    apply_env_overrides(settings)

    # Use the same logging configuration and effective database target as the server.
    configure_logging(settings)
    prepare_runtime_database(settings)
    try:
        cfg_min = int(settings.get("db_pool_min", 1))
    except Exception:
        cfg_min = 1
    try:
        cfg_max = int(settings.get("db_pool_max", 50))
    except Exception:
        cfg_max = 50
    if cfg_max < 1:
        cfg_max = 1
    init_db_pool(
        minconn=max(1, cfg_min),
        maxconn=max(max(1, cfg_min), cfg_max),
        dsn=str(settings.get("database_url")) if settings.get("database_url") else None,
    )

    # A standalone janitor has no local Socket.IO sessions.  It will still use
    # live room counts when Redis shared state is configured; otherwise it falls
    # back to persisted counters only.
    start_janitor(settings, use_live_counts=False)
    # Keep the process alive forever.
    while True:
        time.sleep(3600)


if __name__ == "__main__":
    main()
