#!/usr/bin/env python3
"""janitor_runner.py

Run the HuiChat background cleanup loop as a dedicated process.

Why?
- If you run HuiChat under Gunicorn or multiple one-worker instances, starting
  cleanup in every web process can create duplicate janitors.
- Running this as a single service keeps cleanup predictable and light.

Usage:
  python janitor_runner.py --config server_config.json

Or via env:
  HUI_CONFIG=/path/to/server_config.json python janitor_runner.py
"""

from __future__ import annotations

from env_loader import load_project_dotenv

load_project_dotenv()

import argparse
import json
import os
import time
from pathlib import Path

from constants import CONFIG_FILE
from main import load_settings, apply_env_overrides, configure_logging
from database import init_db_pool
from db.core import prepare_runtime_database
from janitor import configure_janitor_runtime, run_janitor_cycle, start_janitor


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="HuiChat janitor runner")
    p.add_argument(
        "--config",
        default=os.environ.get("HUI_CONFIG") or CONFIG_FILE,
        help="path to server config JSON",
    )
    p.add_argument(
        "--once",
        action="store_true",
        help="run one cleanup cycle and exit; useful for smoke tests and systemd diagnostics",
    )
    p.add_argument(
        "--json",
        action="store_true",
        help="when used with --once, print the structured cleanup result as JSON",
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
    configure_janitor_runtime(settings)
    if args.once:
        result = run_janitor_cycle(settings, use_live_counts=False)
        if args.json:
            print(json.dumps(result, sort_keys=True, default=str))
        else:
            status = "ok" if result.get("ok") else "failed"
            print(f"Janitor cycle {status}: failed_tasks={result.get('failed_tasks') or []}")
        raise SystemExit(0 if result.get("ok") else 2)

    start_janitor(settings, use_live_counts=False)
    # Keep the process alive forever.
    while True:
        time.sleep(3600)


if __name__ == "__main__":
    main()
