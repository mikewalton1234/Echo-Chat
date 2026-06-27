#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from flask import Flask

from main import load_settings, apply_env_overrides, configure_logging
from constants import server_display_name
from database import init_db_pool, apply_migrations, list_available_migrations, get_schema_version


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Echo-Chat migration tool for the configured server")
    p.add_argument("--config", default="server_config.json", help="path to server config JSON")
    p.add_argument("--list", action="store_true", help="list available migrations")
    p.add_argument("--schema-version", action="store_true", help="print current schema version")
    p.add_argument("--migrate", action="store_true", help="apply pending migrations")
    return p.parse_args()


def _init_db(settings: dict) -> None:
    init_db_pool(
        minconn=int(settings.get("db_pool_min", 1)),
        maxconn=max(50, int(settings.get("db_pool_max", 50))),
        dsn=str(settings.get("database_url")) if settings.get("database_url") else None,
    )


def main() -> None:
    args = parse_args()
    cfg_path = Path(args.config)
    settings = load_settings(cfg_path)
    apply_env_overrides(settings)
    configure_logging(settings)
    print(f"Migration tool for {server_display_name(settings)}")

    if args.list and not (args.migrate or args.schema_version):
        items = list_available_migrations()
        if not items:
            print("No migrations found.")
        else:
            for item in items:
                print(f"{item['version']}  {item['name']}  [{item['kind']}]  {item['path']}")
        return

    do_migrate = bool(args.migrate or not (args.list or args.schema_version))

    app = Flask(__name__)
    with app.app_context():
        _init_db(settings)
        if args.list:
            items = list_available_migrations()
            if not items:
                print("No migrations found.")
            else:
                for item in items:
                    print(f"{item['version']}  {item['name']}  [{item['kind']}]  {item['path']}")
        if do_migrate:
            result = apply_migrations()
            print("Applied:", ", ".join(result.get("applied") or []) or "none")
            print("Skipped:", ", ".join(result.get("skipped") or []) or "none")
        if args.schema_version:
            print(get_schema_version())


if __name__ == '__main__':
    main()
