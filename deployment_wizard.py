"""Production deployment wizard helpers for Echo-Chat.

This module is deliberately dependency-light. It can run before Flask, the
application database, or production services are online. The goal is to turn the
saved setup choices into a concrete deployment plan plus reviewable artifacts:

* a deployment checklist
* a systemd service template
* a systemd EnvironmentFile template
* Caddy/Nginx reverse proxy configs

The helpers avoid silently publishing placeholder domains. If no real public URL
is configured, the generated kit stays LAN/no-domain oriented.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse
import os
import shlex

from public_beta_readiness import build_public_beta_readiness, format_public_beta_readiness_report, infer_hosting_mode
from redis_socketio_readiness import build_redis_socketio_report, format_redis_socketio_report
from reverse_proxy_generator import backend_url, has_real_public_domain, write_proxy_configs


@dataclass(frozen=True)
class DeploymentKitFile:
    kind: str
    path: str


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on", "production", "prod"}


def _safe_int(value: Any, default: int) -> int:
    try:
        out = int(value)
        return out if out > 0 else default
    except Exception:
        return default


def _public_url(settings: dict[str, Any]) -> str:
    return str(settings.get("public_base_url") or "").strip().rstrip("/")


def _public_origin(settings: dict[str, Any]) -> str:
    public = _public_url(settings)
    parsed = urlparse(public)
    if not parsed.scheme or not parsed.netloc:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}"


def _project_dir(settings: dict[str, Any]) -> str:
    return str(settings.get("systemd_working_directory") or settings.get("deployment_working_directory") or "/opt/echochat/Echo-Chat-main").strip() or "/opt/echochat/Echo-Chat-main"


def _venv_python(settings: dict[str, Any]) -> str:
    return str(settings.get("systemd_python") or settings.get("deployment_python") or f"{_project_dir(settings)}/.venv/bin/python").strip()


def _service_user(settings: dict[str, Any]) -> str:
    return str(settings.get("systemd_service_user") or settings.get("deployment_user") or "echochat").strip() or "echochat"


def _service_group(settings: dict[str, Any]) -> str:
    return str(settings.get("systemd_service_group") or settings.get("deployment_group") or _service_user(settings)).strip() or _service_user(settings)


def _env_file(settings: dict[str, Any]) -> str:
    return str(settings.get("systemd_env_file") or settings.get("deployment_env_file") or "/etc/echochat/echochat.env").strip() or "/etc/echochat/echochat.env"


def _redact_url_secret(raw: Any) -> str:
    value = str(raw or "").strip()
    if not value:
        return ""
    try:
        parsed = urlparse(value)
        if not parsed.scheme or not parsed.netloc:
            return value
        host = parsed.hostname or ""
        netloc = host
        if parsed.port:
            netloc += f":{parsed.port}"
        if parsed.username or parsed.password:
            user = parsed.username or "user"
            netloc = f"{user}:CHANGE_ME@{netloc}"
        return urlunparse((parsed.scheme, netloc, parsed.path or "", "", parsed.query or "", parsed.fragment or ""))
    except Exception:
        return value


def _csv(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple, set)):
        return ",".join(str(item).strip() for item in value if str(item).strip())
    return ""


def _ice_url_values(raw: Any) -> list[str]:
    values: list[str] = []
    if isinstance(raw, str):
        candidates = [part.strip() for part in raw.split(",")]
    elif isinstance(raw, dict):
        urls = raw.get("urls")
        candidates = [str(item).strip() for item in urls] if isinstance(urls, (list, tuple, set)) else [str(urls or "").strip()]
    elif isinstance(raw, (list, tuple, set)):
        candidates = []
        for item in raw:
            candidates.extend(_ice_url_values(item))
    else:
        candidates = []
    for candidate in candidates:
        if candidate and candidate not in values:
            values.append(candidate)
    return values


def _configured_turn_urls(settings: dict[str, Any]) -> list[str]:
    urls: list[str] = []
    for key in (
        "turn_urls",
        "p2p_ice_servers",
        "p2p_ice",
        "webrtc_ice_servers",
        "ice_servers",
        "voice_ice_servers",
        "voice_webcam_ice_servers",
    ):
        for url in _ice_url_values(settings.get(key)):
            if url.lower().startswith(("turn:", "turns:")) and url not in urls:
                urls.append(url)
    return urls


def _configured_turn_username(settings: dict[str, Any]) -> str:
    explicit = str(settings.get("turn_username") or "").strip()
    if explicit:
        return explicit
    for key in ("p2p_ice_servers", "p2p_ice", "webrtc_ice_servers", "ice_servers", "voice_ice_servers", "voice_webcam_ice_servers"):
        raw = settings.get(key)
        entries = raw if isinstance(raw, (list, tuple, set)) else [raw]
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            urls = _ice_url_values(entry)
            if not any(url.lower().startswith(("turn:", "turns:")) for url in urls):
                continue
            username = str(entry.get("username") or "").strip()
            if username:
                return username
    return ""


def _has_sms_2fa_settings(settings: dict[str, Any]) -> bool:
    return bool(
        _truthy(settings.get("enable_sms_two_factor"))
        or _truthy(settings.get("enable_two_factor_beta"))
        or str(settings.get("twilio_account_sid") or "").strip()
        or str(settings.get("twilio_auth_token") or "").strip()
        or str(settings.get("twilio_verify_service_sid") or "").strip()
    )


def _dynamic_dns_enabled_value(settings: dict[str, Any]) -> str:
    return "1" if _truthy(settings.get("dynamic_dns_enabled")) else "0"


def _existing_parent(path: Path) -> Path:
    current = path
    while not current.exists() and current.parent != current:
        current = current.parent
    return current


def validate_deployment_kit_output_dir(output_dir: str | Path, *, repo_root: str | Path | None = None) -> Path:
    """Return a safe deployment-kit output directory or raise ValueError.

    The kit writes generic names such as README.md and install-commands.sh.
    Refuse paths where those names would overwrite the project itself or a
    protected system directory.
    """
    raw = str(output_dir or "").strip()
    if not raw:
        raise ValueError("Deployment kit output folder cannot be blank.")
    out = Path(raw).expanduser()
    if out.exists() and not out.is_dir():
        raise ValueError(f"Deployment kit output path is not a directory: {out}")

    parent = _existing_parent(out)
    try:
        resolved = parent.resolve() / out.relative_to(parent)
    except Exception:
        resolved = out.resolve() if out.exists() else parent.resolve() / out.name
    resolved = resolved.resolve(strict=False)

    repo = Path(repo_root or Path(__file__).resolve().parent).resolve(strict=False)
    protected = {Path('/'), Path('/etc'), Path('/usr'), Path('/var'), Path('/opt'), Path('/bin'), Path('/sbin'), Path('/lib'), Path('/lib64')}
    if resolved in protected:
        raise ValueError(f"Refusing to write deployment kit directly into protected system directory: {resolved}")
    if resolved == repo:
        raise ValueError("Refusing to write deployment kit into the project root because it would overwrite README.md and other project files. Use deploy/generated-deployment instead.")
    if resolved.exists() and (resolved / "main.py").exists() and (resolved / "VERSION.txt").exists():
        raise ValueError(f"Refusing to write deployment kit into an Echo-Chat source directory: {resolved}")
    return resolved


def _deployment_status(settings: dict[str, Any]) -> str:
    mode = infer_hosting_mode(settings)
    if mode == "public_beta" and has_real_public_domain(settings):
        return "public-domain"
    if mode == "public_beta":
        return "blocked-placeholder-or-missing-domain"
    if mode == "no_domain_yet":
        return "no-domain-yet"
    if mode == "advanced":
        return "advanced"
    return "lan"


def build_deployment_plan(settings: dict[str, Any], *, settings_file: str | Path = "server_config.json", repo_root: str | Path | None = None) -> dict[str, Any]:
    """Return a beginner-friendly production deployment plan for saved settings."""
    settings = dict(settings or {})
    repo_root = Path(repo_root or Path(__file__).resolve().parent)
    readiness = build_public_beta_readiness(settings, settings_file=settings_file, repo_root=repo_root)
    redis_report = build_redis_socketio_report(settings, live_check=False)
    status = _deployment_status(settings)
    public_url = _public_url(settings)
    workers = _safe_int(settings.get("production_workers"), 1)
    worker_class = str(settings.get("production_worker_class") or "gthread").strip() or "gthread"
    async_mode = str(settings.get("production_async_mode") or "threading").strip() or "threading"
    bind = str(settings.get("production_bind") or settings.get("server_host") or settings.get("host") or "127.0.0.1")
    if ":" not in bind:
        bind = f"{bind}:{_safe_int(settings.get('server_port') or settings.get('port'), 5000)}"

    steps: list[dict[str, str]] = []
    if status in {"lan", "no-domain-yet", "blocked-placeholder-or-missing-domain"}:
        steps.append({
            "title": "Keep this server LAN-only until there is a real HTTPS address",
            "detail": "Do not invite internet testers while public_base_url is blank, HTTP, or a placeholder domain.",
            "command": "python main.py --hosting-help",
        })
    else:
        steps.append({
            "title": "Confirm DNS and public HTTPS reverse proxy",
            "detail": "Point your domain/subdomain at this host, then expose only ports 80 and 443 to the internet.",
            "command": "python main.py --generate-proxy-config all --proxy-output-dir deploy/generated-deployment",
        })

    steps.extend([
        {
            "title": "Install Python production dependencies",
            "detail": "Use the project virtual environment so systemd and manual starts run the same interpreter.",
            "command": "python -m venv .venv && source .venv/bin/activate && python -m pip install --upgrade pip && python -m pip install -r requirements.txt",
        },
        {
            "title": "Use the beginner-safe Socket.IO production topology",
            "detail": f"Current plan: workers={workers}, worker_class={worker_class}, async={async_mode}. Keep workers=1 until you build sticky multi-instance routing.",
            "command": "python main.py --redis-socketio-check --redis-live-check",
        },
        {
            "title": "Generate deployment kit files",
            "detail": "Writes systemd, env, proxy, and checklist files to a reviewable folder.",
            "command": "python main.py --write-deployment-kit --deployment-kit-output-dir deploy/generated-deployment",
        },
        {
            "title": "Run the final public beta readiness check",
            "detail": "The command exits non-zero on warn/fail so it can also be used in scripts.",
            "command": "python main.py --public-beta-check",
        },
    ])

    safe_to_invite = bool(status == "public-domain" and readiness.get("overall") == "pass")
    return {
        "status": status,
        "public_url": public_url,
        "public_origin": _public_origin(settings),
        "backend_url": backend_url(settings),
        "run_mode": str(settings.get("run_mode") or "development"),
        "production_workers": workers,
        "production_worker_class": worker_class,
        "production_async_mode": async_mode,
        "safe_to_invite": safe_to_invite,
        "readiness": readiness,
        "redis_socketio": redis_report,
        "steps": steps,
    }


def format_deployment_plan(plan: dict[str, Any]) -> str:
    """Render a terminal-friendly deployment plan."""
    marker = "READY" if plan.get("safe_to_invite") else "NOT READY"
    lines = [
        "Echo-Chat Production Deployment Plan",
        "",
        f"Status: {marker}",
        f"Profile: {plan.get('status')}",
        f"Public URL: {plan.get('public_url') or '(not set)'}",
        f"Backend URL: {plan.get('backend_url') or '(unknown)'}",
        f"Run mode: {plan.get('run_mode')}",
        f"Gunicorn: workers={plan.get('production_workers')}, worker={plan.get('production_worker_class')}, async={plan.get('production_async_mode')}",
        "",
        "Recommended steps:",
    ]
    for idx, step in enumerate(plan.get("steps") or [], start=1):
        lines.append(f"{idx}. {step.get('title')}")
        detail = str(step.get("detail") or "").strip()
        if detail:
            lines.append(f"   {detail}")
        command = str(step.get("command") or "").strip()
        if command:
            lines.append(f"   $ {command}")
    lines.extend([
        "",
        "Public beta readiness summary:",
        f"  {plan.get('readiness', {}).get('pass_count', 0)} pass, {plan.get('readiness', {}).get('warn_count', 0)} warn, {plan.get('readiness', {}).get('fail_count', 0)} fail",
        "",
        "Redis + Socket.IO summary:",
        f"  {plan.get('redis_socketio', {}).get('pass_count', 0)} pass, {plan.get('redis_socketio', {}).get('warn_count', 0)} warn, {plan.get('redis_socketio', {}).get('fail_count', 0)} fail",
    ])
    if not plan.get("safe_to_invite"):
        lines.extend([
            "",
            "Do not invite internet testers yet. Fix every FAIL and review every WARN first.",
        ])
    return "\n".join(lines).rstrip() + "\n"


def generate_systemd_service(settings: dict[str, Any]) -> str:
    """Generate a single-instance systemd unit for the current deployment profile."""
    workdir = _project_dir(settings)
    python_bin = _venv_python(settings)
    env_file = _env_file(settings)
    user = _service_user(settings)
    group = _service_group(settings)
    needs_redis = bool(str(settings.get("socketio_message_queue") or settings.get("rate_limit_storage_uri") or "").startswith("redis://"))
    after = "network-online.target" + (" redis.service" if needs_redis else "")
    return f"""# Echo-Chat generated systemd service
# Generated by: python main.py --write-deployment-kit
# Review WorkingDirectory, User/Group, and EnvironmentFile before installing.

[Unit]
Description=Chat server powered by Echo-Chat
After={after}
Wants={after}

[Service]
Type=simple
WorkingDirectory={workdir}
EnvironmentFile={env_file}
Environment=PYTHONUNBUFFERED=1
ExecStart={python_bin} main.py --production
Restart=on-failure
RestartSec=3
TimeoutStopSec=25
User={user}
Group={group}

# Moderate hardening. Add ReadWritePaths for custom upload/temp locations.
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ProtectHome=true
RestrictSUIDSGID=true
LockPersonality=true
ReadWritePaths={workdir}/logs
ReadWritePaths={workdir}/server_config.json
ReadWritePaths={workdir}/uploads
ReadWritePaths={workdir}/private_uploads
ReadWritePaths={workdir}/instance

[Install]
WantedBy=multi-user.target
"""


def generate_environment_file(settings: dict[str, Any]) -> str:
    """Generate a reviewable systemd EnvironmentFile template."""
    public = _public_url(settings) or "https://YOUR-REAL-DOMAIN"
    origin = _public_origin(settings) or public
    config_path = f"{_project_dir(settings)}/server_config.json"
    db_url = _redact_url_secret(settings.get("database_url") or "postgresql://echochat:CHANGE_ME@localhost:5432/echochat")
    rate_url = str(settings.get("rate_limit_storage_uri") or "redis://127.0.0.1:6379/0")
    queue = str(settings.get("socketio_message_queue") or "redis://127.0.0.1:6379/1")
    shared = str(settings.get("shared_state_redis_url") or "redis://127.0.0.1:6379/2")
    bind = str(settings.get("production_bind") or "127.0.0.1:5000")
    return f"""# Echo-Chat generated systemd EnvironmentFile
# Copy to {_env_file(settings)} and chmod 600.
# Replace CHANGE_ME values before production.

ECHOCHAT_PERSIST_SECRETS=0
ECHOCHAT_CONFIG={shlex.quote(config_path)}

SECRET_KEY=CHANGE_ME_GENERATE_WITH_python_-c_import_secrets_print_secrets.token_urlsafe_64
JWT_SECRET_KEY=CHANGE_ME_GENERATE_A_DIFFERENT_LONG_RANDOM_VALUE
DATABASE_URL={shlex.quote(db_url)}

ECHOCHAT_RUN_MODE=production
ECHOCHAT_PRODUCTION_MODE=1
ECHOCHAT_PRODUCTION_BIND={shlex.quote(bind)}
ECHOCHAT_PRODUCTION_WORKERS={_safe_int(settings.get('production_workers'), 1)}
# Direct gunicorn_conf.py aliases; keep these aligned with the production values above.
ECHOCHAT_BIND={shlex.quote(bind)}
ECHOCHAT_WORKERS={_safe_int(settings.get('production_workers'), 1)}
ECHOCHAT_SOCKETIO_ASYNC={shlex.quote(str(settings.get('production_async_mode') or 'threading'))}
ECHOCHAT_GUNICORN_WORKER_CLASS={shlex.quote(str(settings.get('production_worker_class') or 'gthread'))}
ECHOCHAT_GUNICORN_THREADS={_safe_int(settings.get('production_threads') or settings.get('gunicorn_threads'), 100)}

ECHOCHAT_PUBLIC_BASE_URL={shlex.quote(public)}
ECHOCHAT_ALLOWED_ORIGINS={shlex.quote(_csv(settings.get('allowed_origins')) or origin)}
ECHOCHAT_CORS_ALLOWED_ORIGINS={shlex.quote(_csv(settings.get('cors_allowed_origins')) or origin)}
ECHOCHAT_COOKIE_SECURE={'1' if _truthy(settings.get('cookie_secure')) else '0'}
ECHOCHAT_COOKIE_SAMESITE={shlex.quote(str(settings.get('cookie_samesite') or 'Lax'))}
ECHOCHAT_TRUST_PROXY_HEADERS={'1' if _truthy(settings.get('trust_proxy_headers')) else '0'}
ECHOCHAT_PROXY_FIX_HOPS={_safe_int(settings.get('proxy_fix_hops'), 1)}
ECHOCHAT_ENABLE_HEALTH_ENDPOINT={'1' if _truthy(settings.get('enable_health_check_endpoint')) else '0'}
ECHOCHAT_HEALTH_ENDPOINT={shlex.quote(str(settings.get('health_check_endpoint') or '/health'))}

ECHOCHAT_RATE_LIMIT_STORAGE_URI={shlex.quote(rate_url)}
ECHOCHAT_SOCKETIO_MESSAGE_QUEUE={shlex.quote(queue)}
ECHOCHAT_SHARED_STATE_REDIS_URL={shlex.quote(shared)}
ECHOCHAT_SOCKETIO_TRANSPORTS={shlex.quote(_csv(settings.get('socketio_transports')) or 'polling')}

# Optional email / SMTP
ECHOCHAT_SMTP_ENABLED={'1' if _truthy(settings.get('smtp_enabled')) else '0'}
ECHOCHAT_SMTP_HOST={shlex.quote(str(settings.get('smtp_host') or 'smtp-relay.brevo.com'))}
ECHOCHAT_SMTP_PORT={_safe_int(settings.get('smtp_port'), 587)}
ECHOCHAT_SMTP_USERNAME=CHANGE_ME_OR_LEAVE_BLANK
ECHOCHAT_SMTP_PASSWORD=CHANGE_ME_OR_LEAVE_BLANK
ECHOCHAT_SMTP_FROM={shlex.quote(str(settings.get('smtp_from') or 'Echo-Chat <no-reply@localhost>'))}
ECHOCHAT_SMTP_STARTTLS={'1' if _truthy(settings.get('smtp_use_starttls', True)) else '0'}
ECHOCHAT_SMTP_SSL={'1' if _truthy(settings.get('smtp_use_ssl')) else '0'}
ECHOCHAT_SMTP_TIMEOUT={_safe_int(settings.get('smtp_timeout_seconds'), 20)}

# Optional SMS 2FA / Twilio Verify
ECHOCHAT_ENABLE_SMS_TWO_FACTOR={'1' if _truthy(settings.get('enable_sms_two_factor')) else '0'}
ECHOCHAT_ENABLE_TWO_FACTOR_BETA={'1' if _truthy(settings.get('enable_two_factor_beta')) else '0'}
ECHOCHAT_TWILIO_VERIFY_CHANNEL={shlex.quote(str(settings.get('two_factor_sms_channel') or 'sms'))}
ECHOCHAT_TWILIO_ACCOUNT_SID={shlex.quote(str(settings.get('twilio_account_sid') or 'CHANGE_ME_OR_LEAVE_BLANK'))}
ECHOCHAT_TWILIO_AUTH_TOKEN=CHANGE_ME_OR_LEAVE_BLANK
ECHOCHAT_TWILIO_VERIFY_SERVICE_SID={shlex.quote(str(settings.get('twilio_verify_service_sid') or 'CHANGE_ME_OR_LEAVE_BLANK'))}
ECHOCHAT_TWO_FACTOR_LOGIN_TIMEOUT_SECONDS={_safe_int(settings.get('two_factor_login_timeout_seconds'), 600)}

# Optional Dynamic DNS helper. Password/token is always a placeholder in generated files.
ECHOCHAT_DYNAMIC_DNS_ENABLED={_dynamic_dns_enabled_value(settings)}
ECHOCHAT_DYNAMIC_DNS_PROVIDER={shlex.quote(str(settings.get('dynamic_dns_provider') or 'No-IP'))}
ECHOCHAT_DYNAMIC_DNS_DOMAIN={shlex.quote(str(settings.get('dynamic_dns_domain') or ''))}
ECHOCHAT_DYNAMIC_DNS_USERNAME={shlex.quote(str(settings.get('dynamic_dns_username') or 'CHANGE_ME_OR_LEAVE_BLANK'))}
ECHOCHAT_DYNAMIC_DNS_PASSWORD=CHANGE_ME_OR_LEAVE_BLANK
ECHOCHAT_DYNAMIC_DNS_UPDATE_URL={shlex.quote(str(settings.get('dynamic_dns_update_url') or 'https://dynupdate.no-ip.com/nic/update'))}

# Optional WebRTC TURN relay. STUN-only can be blank; TURN needs URL, username, and credential.
ECHOCHAT_TURN_URLS={shlex.quote(','.join(_configured_turn_urls(settings)))}
ECHOCHAT_TURN_USERNAME={shlex.quote(_configured_turn_username(settings) or 'CHANGE_ME_OR_LEAVE_BLANK')}
ECHOCHAT_TURN_CREDENTIAL=CHANGE_ME_OR_LEAVE_BLANK
"""


def _install_commands(settings: dict[str, Any]) -> str:
    env_file = _env_file(settings)
    user = _service_user(settings)
    return f"""# Review generated files before running these commands.
sudo useradd --system --home-dir {_project_dir(settings)} --shell /usr/bin/nologin {user} 2>/dev/null || true
sudo mkdir -p {Path(env_file).parent}
sudo cp echochat.env.example {env_file}
sudo chmod 600 {env_file}
sudo cp echochat.service /etc/systemd/system/echochat.service
sudo systemctl daemon-reload
sudo systemctl enable --now echochat.service
sudo systemctl status echochat.service --no-pager
"""


def write_deployment_kit(settings: dict[str, Any], output_dir: str | Path, *, proxy: str = "all", settings_file: str | Path = "server_config.json", repo_root: str | Path | None = None) -> list[DeploymentKitFile]:
    """Write a reviewable deployment kit folder and return file metadata."""
    settings = dict(settings or {})
    repo_root = Path(repo_root or Path(__file__).resolve().parent)
    out = validate_deployment_kit_output_dir(output_dir, repo_root=repo_root)
    out.mkdir(parents=True, exist_ok=True)
    written: list[DeploymentKitFile] = []

    proxy_written = write_proxy_configs(settings, out / "proxy", proxy=proxy)
    for item in proxy_written:
        written.append(DeploymentKitFile(f"proxy:{item.proxy}", item.path))

    plan = build_deployment_plan(settings, settings_file=settings_file, repo_root=repo_root)
    readiness_text = format_public_beta_readiness_report(plan["readiness"])
    redis_text = format_redis_socketio_report(plan["redis_socketio"])

    files = {
        "README.md": "# Echo-Chat generated deployment kit\n\n"
        + "Generated files are templates. Review paths, users, secrets, DNS, firewall, and certificate choices before installing.\n\n"
        + f"Public URL: `{plan.get('public_url') or '(not set)'}`\n\n"
        + f"Backend: `{plan.get('backend_url')}`\n\n"
        + "## Install commands\n\n```bash\n" + _install_commands(settings) + "```\n\n"
        + "## Checks\n\n```bash\npython main.py --redis-socketio-check --redis-live-check\npython main.py --public-beta-check\n```\n\n"
        + "## Generated folders\n\n- `proxy/` contains Caddy/Nginx reverse proxy templates.\n- `echochat.service` is the systemd service template.\n- `echochat.env.example` is the secret/config environment template.\n- `deployment-plan.txt`, `public-beta-readiness.txt`, and `redis-socketio-check.txt` are review reports.\n",
        "deployment-plan.txt": format_deployment_plan(plan),
        "public-beta-readiness.txt": readiness_text,
        "redis-socketio-check.txt": redis_text,
        "echochat.service": generate_systemd_service(settings),
        "echochat.env.example": generate_environment_file(settings),
        "install-commands.sh": "#!/usr/bin/env bash\nset -euo pipefail\n" + _install_commands(settings),
    }
    for name, content in files.items():
        path = out / name
        path.write_text(content, encoding="utf-8")
        if name.endswith(".sh"):
            try:
                path.chmod(path.stat().st_mode | 0o111)
            except Exception:
                pass
        written.append(DeploymentKitFile("deployment", str(path)))
    return written


def format_deployment_kit_report(settings: dict[str, Any], written: list[DeploymentKitFile]) -> str:
    plan = build_deployment_plan(settings)
    lines = [
        "Echo-Chat Deployment Kit Generator",
        "",
        f"Status: {'READY' if plan.get('safe_to_invite') else 'REVIEW REQUIRED'}",
        f"Profile: {plan.get('status')}",
        f"Public URL: {plan.get('public_url') or '(not set)'}",
        f"Backend: {plan.get('backend_url')}",
        "",
        "Generated files:",
    ]
    for item in written:
        lines.append(f"  - {item.kind}: {item.path}")
    lines.extend([
        "",
        "Next commands:",
        "  python main.py --redis-socketio-check --redis-live-check",
        "  python main.py --dynamic-dns-check",
        "  python main.py --public-beta-check",
        "",
        "Review the generated README.md before copying systemd/proxy files into /etc.",
    ])
    return "\n".join(lines).rstrip() + "\n"
