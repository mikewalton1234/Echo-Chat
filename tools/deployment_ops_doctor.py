#!/usr/bin/env python3
"""Static S19 deployment/operations doctor for Echo-Chat.

This checks the generated service templates and operator scripts for the most
important production-safety invariants:
  - one worker per web instance;
  - config/topology ExecStartPre gates in generated systemd services;
  - a separate janitor service with an explicit config path;
  - quoted paths so systemd/install scripts survive spaces in project folders;
  - install commands create/chown runtime writable directories;
  - production dependency script does not execute an unquoted PYTHON value.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from deployment_wizard import (  # noqa: E402
    generate_janitor_service,
    generate_systemd_instance_template,
    generate_systemd_service,
    write_deployment_kit,
)


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _assert_contains(failures: list[str], label: str, text: str, tokens: list[str]) -> None:
    for token in tokens:
        if token not in text:
            failures.append(f"{label} missing token: {token}")


def main() -> int:
    failures: list[str] = []
    sample = {
        "systemd_working_directory": "/tmp/Echo Chat S19",
        "systemd_python": "/tmp/Echo Chat S19/.venv/bin/python",
        "systemd_env_file": "/etc/echo chat/echochat.env",
        "rate_limit_storage_uri": "rediss://127.0.0.1:6380/0",
        "socketio_message_queue": "redis://127.0.0.1:6379/1",
        "shared_state_redis_url": "redis://127.0.0.1:6379/2",
        "production_instance_count": 2,
        "dm_upload_root": "secure dm",
        "group_upload_root": "secure group",
    }

    single = generate_systemd_service(sample)
    instance = generate_systemd_instance_template(sample)
    janitor = generate_janitor_service(sample)

    _assert_contains(failures, "single systemd service", single, [
        'WorkingDirectory="/tmp/Echo Chat S19"',
        'EnvironmentFile="/etc/echo chat/echochat.env"',
        "ExecStartPre=",
        "tools/config_doctor.py --config",
        "--redis-socketio-check",
        "ECHOCHAT_CONFIG=",
        "ECHOCHAT_PRODUCTION_WORKERS=1",
        "ECHOCHAT_WORKERS=1",
        "After=network-online.target redis.service",
        'ReadWritePaths="/tmp/Echo Chat S19/secure dm"',
        'ReadWritePaths="/tmp/Echo Chat S19/server_config.json"',
    ])
    if "ECHOCHAT_WORKERS=2" in single or "WEB_CONCURRENCY=2" in single:
        failures.append("single systemd service appears to allow unsafe multi-worker Socket.IO startup")

    _assert_contains(failures, "instance systemd service", instance, [
        "echochat@.service",
        'ECHOCHAT_BIND="127.0.0.1:%i"',
        "ECHOCHAT_PRODUCTION_WORKERS=1",
        "ECHOCHAT_WORKERS=1",
        "--redis-socketio-check",
    ])

    _assert_contains(failures, "janitor systemd service", janitor, [
        "janitor_runner.py --config",
        "tools/config_doctor.py --config",
        "Run exactly one janitor",
        'WorkingDirectory="/tmp/Echo Chat S19"',
        "After=network-online.target redis.service",
        "Wants=network-online.target redis.service",
    ])
    if "main.py --production" in janitor:
        failures.append("janitor service must not start the web server")

    deployment_wizard = _read("deployment_wizard.py")
    _assert_contains(failures, "deployment_wizard.py", deployment_wizard, [
        "def _systemd_quote",
        "def _runtime_path_values",
        "def _runtime_mkdir_commands",
        "sudo install -d -o",
        "sudo chown root:",
        "sudo chmod 640",
        "rediss://",
    ])

    install_deps = _read("scripts/install_production_deps.sh")
    _assert_contains(failures, "install_production_deps.sh", install_deps, [
        '"$PYTHON_BIN" -m pip install --upgrade pip',
        '"$PYTHON_BIN" -m pip install -r requirements.txt',
        '"$PYTHON_BIN" - <<',
    ])
    if "$PYTHON_BIN -m pip" in install_deps or "$PYTHON_BIN - <<" in install_deps:
        failures.append("install_production_deps.sh still contains unquoted $PYTHON_BIN execution")

    with tempfile.TemporaryDirectory(prefix="echochat-s19-kit-") as tmp:
        out = Path(tmp) / "kit"
        written = write_deployment_kit(sample, out, proxy="all", settings_file=ROOT / "server_config.json", repo_root=ROOT)
        names = {Path(item.path).name for item in written}
        for required in {"echochat.service", "echochat@.service", "echochat-janitor.service", "echochat.env.example", "install-commands.sh", "README.md"}:
            if required not in names:
                failures.append(f"deployment kit did not write {required}")
        install_commands = (out / "install-commands.sh").read_text(encoding="utf-8")
        _assert_contains(failures, "generated install-commands.sh", install_commands, [
            "sudo install -d -o echochat -g echochat -m 0750",
            "sudo systemctl daemon-reload",
            "echochat-janitor.service",
        ])

    if failures:
        print("❌ Deployment/ops doctor failed")
        for failure in failures:
            print(f"   - {failure}")
        return 1

    print("✅ Deployment/ops doctor passed")
    print("   checks: systemd preflight gates, one-worker services, separate janitor, Redis-aware janitor ordering, quoted paths, runtime dir install, dependency script quoting")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
