#!/usr/bin/env python3
"""Deep S19 deployment/ops doctor for Echo-Chat.

This rechecks the static service templates and the generated deployment helpers.
The first S19 doctor focused on generated kit output.  This deeper doctor also
protects the checked-in templates because operators often copy those directly
while testing.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from deployment_wizard import generate_janitor_service, write_deployment_kit  # noqa: E402


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _assert_contains(failures: list[str], label: str, text: str, tokens: list[str]) -> None:
    for token in tokens:
        if token not in text:
            failures.append(f"{label} missing token: {token}")


def _assert_not_contains(failures: list[str], label: str, text: str, tokens: list[str]) -> None:
    for token in tokens:
        if token in text:
            failures.append(f"{label} contains unsafe/stale token: {token}")


def _check_web_unit(failures: list[str], rel: str, *, direct_gunicorn: bool = False, template: bool = False) -> None:
    text = _read(rel)
    required = [
        "ExecStartPre=",
        "tools/config_doctor.py --config",
        "--redis-socketio-check",
        "ECHOCHAT_CONFIG=",
        "ECHOCHAT_WORKERS=1",
        "EnvironmentFile=/etc/echochat/echochat.env",
        "ReadWritePaths=/opt/echochat/Echo-Chat-main/uploads",
        "ReadWritePaths=/opt/echochat/Echo-Chat-main/private_uploads",
        "ReadWritePaths=/opt/echochat/Echo-Chat-main/instance",
        "ReadWritePaths=/opt/echochat/Echo-Chat-main/static/uploads",
        "ReadWritePaths=/opt/echochat/Echo-Chat-main/server_config.json",
        "After=network-online.target redis.service",
    ]
    if not direct_gunicorn:
        required.append("ECHOCHAT_PRODUCTION_WORKERS=1")
        required.append("main.py --production")
    else:
        required.append("gunicorn_conf.py")
    if template:
        required.extend(["ECHOCHAT_BIND=127.0.0.1:%i", "ECHOCHAT_PRODUCTION_BIND=127.0.0.1:%i"])
    _assert_contains(failures, rel, text, required)
    _assert_not_contains(failures, rel, text, ["ECHOCHAT_WORKERS=2", "WEB_CONCURRENCY=2", "chmod 600 /etc/echochat/echochat.env"])


def _check_janitor_unit(failures: list[str], rel: str) -> None:
    text = _read(rel)
    _assert_contains(failures, rel, text, [
        "ExecStartPre=",
        "tools/config_doctor.py --config",
        "janitor_runner.py --config",
        "After=network-online.target redis.service",
        "Wants=network-online.target redis.service",
        "ReadWritePaths=/opt/echochat/Echo-Chat-main/private_uploads",
        "ReadWritePaths=/opt/echochat/Echo-Chat-main/uploads",
        "ReadWritePaths=/opt/echochat/Echo-Chat-main/instance",
    ])
    _assert_not_contains(failures, rel, text, ["main.py --production", "gunicorn"])


def main() -> int:
    failures: list[str] = []

    _check_web_unit(failures, "deploy/systemd/echochat.service")
    _check_web_unit(failures, "deploy/systemd/echochat@.service", template=True)
    _check_web_unit(failures, "deploy/systemd/echochat-gunicorn.service", direct_gunicorn=True)
    _check_janitor_unit(failures, "deploy/systemd/echochat-janitor.service")

    readme = _read("deploy/systemd/README.md")
    _assert_contains(failures, "deploy/systemd/README.md", readme, [
        "sudo chown root:echochat /etc/echochat/echochat.env",
        "sudo chmod 640 /etc/echochat/echochat.env",
        "Keep only one `echochat-janitor.service` active",
        "python tools/deployment_ops_deep_doctor.py",
    ])
    _assert_not_contains(failures, "deploy/systemd/README.md", readme, [
        "sudo chmod 600 /etc/echochat/echochat.env",
        "sudo chown root:root /etc/echochat/echochat.env",
    ])

    sample = {
        "systemd_working_directory": "/tmp/Echo Chat S19 Deep",
        "systemd_python": "/tmp/Echo Chat S19 Deep/.venv/bin/python",
        "systemd_env_file": "/etc/echo chat/echochat.env",
        "socketio_message_queue": "rediss://127.0.0.1:6380/1",
        "shared_state_redis_url": "redis://127.0.0.1:6379/2",
        "rate_limit_storage_uri": "redis://127.0.0.1:6379/0",
        "production_instance_count": 3,
    }
    generated_janitor = generate_janitor_service(sample)
    _assert_contains(failures, "generated janitor service", generated_janitor, [
        "After=network-online.target redis.service",
        "Wants=network-online.target redis.service",
        "janitor_runner.py --config",
        'WorkingDirectory="/tmp/Echo Chat S19 Deep"',
    ])

    with tempfile.TemporaryDirectory(prefix="echochat-s19-deep-kit-") as tmp:
        out = Path(tmp) / "kit"
        write_deployment_kit(sample, out, proxy="all", settings_file=ROOT / "server_config.json", repo_root=ROOT)
        for name in ("echochat.service", "echochat@.service", "echochat-janitor.service", "install-commands.sh"):
            text = (out / name).read_text(encoding="utf-8")
            _assert_contains(failures, f"generated {name}", text, ["tools/config_doctor.py --config"] if name.endswith(".service") else ["sudo install -d"])
        generated_install = (out / "install-commands.sh").read_text(encoding="utf-8")
        _assert_contains(failures, "generated install-commands.sh", generated_install, [
            "sudo chown root:echochat",
            "sudo chmod 640",
            "echochat-janitor.service",
        ])

    if failures:
        print("❌ Deployment/ops deep doctor failed")
        for failure in failures:
            print(f"   - {failure}")
        return 1

    print("✅ Deployment/ops deep doctor passed")
    print("   checks: static systemd templates, Redis-aware janitor ordering, env-file permissions, runtime ReadWritePaths, generated kit consistency")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
