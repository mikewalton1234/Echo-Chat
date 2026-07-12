"""Reverse proxy config generator for Hui Chat public beta hosting.

The generator is intentionally dependency-free and safe to run before the
application database exists. It reads the saved setup values and produces
beginner-friendly Caddy and Nginx examples for one or more local Hui Chat backends.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
import datetime as _dt
import ipaddress

from health_status import normalize_public_probe_path


@dataclass(frozen=True)
class ProxyConfigBundle:
    proxy: str
    path: str
    content: str


def _clean_url(value: Any) -> str:
    return str(value or "").strip().rstrip("/")


def _public_url(settings: dict[str, Any]) -> str:
    # Intentionally do not silently fall back to chat.example.com. Generating
    # public-beta configs for a fake placeholder domain confused admins and can
    # lead to broken deployments. Blank means "no domain yet".
    return _clean_url(settings.get("public_base_url") or "")


def _looks_like_placeholder_domain(host_or_url: Any) -> bool:
    value = str(host_or_url or "").strip().lower()
    if not value:
        return False
    parsed = urlparse(value if "://" in value else f"https://{value}")
    host = (parsed.hostname or value).strip().lower().rstrip(".")
    if not host:
        return False
    placeholder_hosts = {
        "chat.example.com",
        "example.com",
        "example.net",
        "example.org",
        "yourdomain.com",
        "your-domain.com",
        "your-real-domain.com",
        "your-real-domain.example",
        "your-domain.example",
    }
    return host in placeholder_hosts or host.endswith(".example.com") or host.endswith(".example.net") or host.endswith(".example.org")


def has_real_public_domain(settings: dict[str, Any]) -> bool:
    public = _public_url(settings)
    parsed = urlparse(public)
    host = parsed.hostname or ""
    return bool(parsed.scheme in {"http", "https"} and host and not _looks_like_placeholder_domain(public))


def _public_host(settings: dict[str, Any]) -> str:
    parsed = urlparse(_public_url(settings))
    return parsed.netloc or ""


def _public_hostname(settings: dict[str, Any]) -> str:
    parsed = urlparse(_public_url(settings))
    return (parsed.hostname or "").strip().lower().rstrip(".")


def _public_scheme(settings: dict[str, Any]) -> str:
    parsed = urlparse(_public_url(settings))
    return (parsed.scheme or "").lower()


def _lan_proxy_port(settings: dict[str, Any]) -> int:
    return _safe_int(settings.get("reverse_proxy_lan_port") or settings.get("lan_proxy_port"), 8080)


def _safe_int(value: Any, default: int) -> int:
    try:
        out = int(value)
        return out if out > 0 else default
    except Exception:
        return default


def _backend_host_from_settings(settings: dict[str, Any]) -> str:
    explicit = str(settings.get("reverse_proxy_backend_host") or "").strip()
    if explicit:
        return explicit
    bind = str(settings.get("production_bind") or "").strip()
    if bind and ":" in bind:
        host = bind.rsplit(":", 1)[0].strip().strip("[]")
        if host and host not in {"0.0.0.0", "::"}:
            return host
    raw_host = str(settings.get("server_host") or settings.get("host") or "127.0.0.1").strip()
    if raw_host in {"", "0.0.0.0", "::"}:
        return "127.0.0.1"
    return raw_host


def _backend_port_from_settings(settings: dict[str, Any]) -> int:
    explicit = str(settings.get("reverse_proxy_backend_port") or "").strip()
    if explicit:
        return _safe_int(explicit, 5000)
    bind = str(settings.get("production_bind") or "").strip()
    if bind and ":" in bind:
        return _safe_int(bind.rsplit(":", 1)[1], 5000)
    return _safe_int(settings.get("server_port") or settings.get("port"), 5000)


def _format_backend_host(host: str) -> str:
    value = str(host or "127.0.0.1").strip().strip("[]") or "127.0.0.1"
    try:
        parsed = ipaddress.ip_address(value)
        if parsed.version == 6:
            return f"[{value}]"
    except ValueError:
        pass
    return value


def backend_url(settings: dict[str, Any]) -> str:
    return backend_urls(settings)[0]




def _instance_count(settings: dict[str, Any]) -> int:
    return max(1, min(10, _safe_int(settings.get("production_instance_count") or settings.get("production_instances") or settings.get("instance_count"), 1)))


def _backend_base_port(settings: dict[str, Any]) -> int:
    explicit = str(settings.get("reverse_proxy_backend_port") or "").strip()
    if explicit:
        return _safe_int(explicit, 5000)
    if settings.get("production_instance_base_port") or settings.get("instance_base_port"):
        return _safe_int(settings.get("production_instance_base_port") or settings.get("instance_base_port"), 5000)
    return _backend_port_from_settings(settings)


def backend_urls(settings: dict[str, Any]) -> list[str]:
    host = _format_backend_host(_backend_host_from_settings(settings))
    base_port = _backend_base_port(settings)
    return [f"http://{host}:{base_port + offset}" for offset in range(_instance_count(settings))]


def _caddy_reverse_proxy_block(settings: dict[str, Any], indent: str = "    ") -> str:
    upstreams = " ".join(backend_urls(settings))
    sticky = f"{indent}    lb_policy cookie hui_lb\n" if _instance_count(settings) > 1 else ""
    return (
        f"{indent}reverse_proxy {upstreams} {{\n"
        f"{sticky}"
        f"{indent}    header_up Host {{host}}\n"
        f"{indent}    header_up X-Real-IP {{remote_host}}\n"
        f"{indent}    header_up X-Forwarded-For {{remote_host}}\n"
        f"{indent}    header_up X-Forwarded-Proto {{scheme}}\n"
        f"{indent}}}"
    )


def _nginx_proxy_target(settings: dict[str, Any]) -> str:
    return "http://hui_chat_backend" if _instance_count(settings) > 1 else backend_urls(settings)[0]


def _nginx_upstream_block(settings: dict[str, Any]) -> str:
    if _instance_count(settings) <= 1:
        return ""
    servers = "\n".join(f"    server {url.replace('http://', '')};" for url in backend_urls(settings))
    return f"upstream hui_chat_backend {{\n    ip_hash;\n{servers}\n}}\n\n"

def _max_request_size(settings: dict[str, Any]) -> str:
    # Nginx accepts m/k suffixes. Round up so configured request limits are not
    # accidentally lower than Hui Chat's own max_request_bytes.
    bytes_value = _safe_int(settings.get("max_request_bytes"), 30 * 1024 * 1024)
    mib = max(1, (bytes_value + 1024 * 1024 - 1) // (1024 * 1024))
    return f"{mib}m"


def _health_path(settings: dict[str, Any]) -> str:
    return normalize_public_probe_path(settings.get("health_check_endpoint"), "/health")


def _existing_parent(path: Path) -> Path:
    current = path
    while not current.exists() and current.parent != current:
        current = current.parent
    return current


def validate_proxy_output_dir(output_dir: str | Path, *, repo_root: str | Path | None = None) -> Path:
    """Return a safe reverse-proxy output directory or raise ValueError.

    The generator writes generic names such as ``README.md`` and ``Caddyfile``.
    Refuse the project root, Hui Chat source folders, and high-level system
    directories so a helper command cannot overwrite real project/deployment
    files by accident.
    """
    raw = str(output_dir or "").strip()
    if not raw:
        raise ValueError("Reverse proxy output folder cannot be blank.")
    out = Path(raw).expanduser()
    if out.exists() and not out.is_dir():
        raise ValueError(f"Reverse proxy output path is not a directory: {out}")

    parent = _existing_parent(out)
    try:
        resolved = parent.resolve() / out.relative_to(parent)
    except Exception:
        resolved = out.resolve() if out.exists() else parent.resolve() / out.name
    resolved = resolved.resolve(strict=False)

    repo = Path(repo_root or Path(__file__).resolve().parent).resolve(strict=False)
    protected = {Path('/'), Path('/etc'), Path('/usr'), Path('/var'), Path('/opt'), Path('/bin'), Path('/sbin'), Path('/lib'), Path('/lib64')}
    if resolved in protected:
        raise ValueError(f"Refusing to write reverse proxy configs directly into protected system directory: {resolved}")
    if resolved == repo:
        raise ValueError("Refusing to write reverse proxy configs into the project root because it would overwrite README.md and other project files. Use deploy/generated-proxy instead.")
    if resolved.exists() and (resolved / "main.py").exists() and (resolved / "VERSION.txt").exists():
        raise ValueError(f"Refusing to write reverse proxy configs into an Hui Chat source directory: {resolved}")
    return resolved


def _generation_header(settings: dict[str, Any], proxy_name: str) -> str:
    generated = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    return (
        f"# Hui Chat {proxy_name} reverse proxy config\n"
        f"# Generated: {generated}\n"
        f"# Public URL: {_public_url(settings)}\n"
        f"# Backend: {backend_url(settings)}\n"
        "# Review before production use, especially certificate paths, firewall rules, and DNS.\n"
    )


def generate_caddyfile(settings: dict[str, Any]) -> str:
    """Return a Caddyfile for Hui Chat.

    With a real public domain this is a public HTTPS reverse proxy config.
    Without a real domain it becomes a LAN-only HTTP helper on port 8080 so
    admins do not accidentally publish a fake chat.example.com deployment.
    """
    health_path = _health_path(settings)
    header = _generation_header(settings, "Caddy")
    proxy_block = _caddy_reverse_proxy_block(settings)
    if not has_real_public_domain(settings):
        lan_port = _lan_proxy_port(settings)
        return f"""{header}
# LAN-ONLY / NO DOMAIN YET
# Use this only on your home network while you do not have a real domain.
# Open http://SERVER-LAN-IP:{lan_port} from another device on the same LAN.
# This is NOT public beta hosting and will not create public HTTPS certificates.

http://:{lan_port} {{
    encode zstd gzip

{proxy_block}

    @health path {health_path}
}}
""".lstrip()

    host = _public_host(settings)
    return f"""{header}
{host} {{
    encode zstd gzip

    # Caddy automatically manages HTTPS certificates for public DNS names.
    # Make sure DNS A/AAAA records point to this server and ports 80/443 are open.
    # Multiple Hui Chat instances use cookie stickiness so Socket.IO polling stays on one backend.

{proxy_block}

    # Optional health endpoint. Enable it in Hui Chat before using uptime checks.
    @health path {health_path}
}}
""".lstrip()


def generate_nginx_config(settings: dict[str, Any]) -> str:
    """Return an Nginx server config.

    With a real public domain this config includes HTTPS and Socket.IO/WebSocket
    proxy headers. Without a real domain it generates a LAN-only port 8080
    template so the admin has a safe testing path.
    """
    proxy_target = _nginx_proxy_target(settings)
    upstream_block = _nginx_upstream_block(settings)
    body_size = _max_request_size(settings)
    health_path = _health_path(settings)
    header = _generation_header(settings, "Nginx")
    if not has_real_public_domain(settings):
        lan_port = _lan_proxy_port(settings)
        return f"""{header}
# LAN-ONLY / NO DOMAIN YET
# Use this only on your home network while you do not have a real domain.
# Open http://SERVER-LAN-IP:{lan_port} from another device on the same LAN.
# This is NOT public beta hosting and does not configure HTTPS.

{upstream_block}map $http_upgrade $connection_upgrade {{
    default upgrade;
    '' close;
}}

server {{
    listen {lan_port};
    listen [::]:{lan_port};
    server_name _;

    client_max_body_size {body_size};
    proxy_read_timeout 3600s;
    proxy_send_timeout 3600s;
    proxy_connect_timeout 60s;

    location /socket.io/ {{
        proxy_pass {proxy_target};
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $connection_upgrade;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-Host $host;
        proxy_buffering off;
        proxy_cache_bypass $http_upgrade;
    }}

    location / {{
        proxy_pass {proxy_target};
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-Host $host;
        proxy_redirect off;
    }}

    location = {health_path} {{
        proxy_pass {proxy_target};
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
    }}
}}
""".lstrip()

    host = _public_hostname(settings)
    return f"""{header}
# Put the `upstream` and `map` blocks in the http {{ }} context. If your distro splits configs,
# place them in /etc/nginx/conf.d/hui-chat-map.conf or above the server blocks.
{upstream_block}map $http_upgrade $connection_upgrade {{
    default upgrade;
    '' close;
}}

server {{
    listen 80;
    listen [::]:80;
    server_name {host};

    # Let Certbot/ACME answer challenges here if needed, otherwise redirect.
    location /.well-known/acme-challenge/ {{
        root /var/www/html;
    }}

    location / {{
        return 301 https://$host$request_uri;
    }}
}}

server {{
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name {host};

    # Replace these paths if you do not use Certbot.
    ssl_certificate /etc/letsencrypt/live/{host}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/{host}/privkey.pem;

    client_max_body_size {body_size};
    proxy_read_timeout 3600s;
    proxy_send_timeout 3600s;
    proxy_connect_timeout 60s;

    # Socket.IO endpoint. Supports polling and WebSocket upgrade.
    location /socket.io/ {{
        proxy_pass {proxy_target};
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $connection_upgrade;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-Host $host;
        proxy_buffering off;
        proxy_cache_bypass $http_upgrade;
    }}

    # Normal HTTP app traffic.
    location / {{
        proxy_pass {proxy_target};
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-Host $host;
        proxy_redirect off;
    }}

    # Optional health endpoint. Enable it in Hui Chat before using uptime checks.
    location = {health_path} {{
        proxy_pass {proxy_target};
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
    }}
}}
""".lstrip()


def proxy_readiness_notes(settings: dict[str, Any]) -> list[str]:
    notes: list[str] = []
    public = _public_url(settings)
    if not public:
        notes.append("No public domain is configured. Generated files are LAN-only helpers, not public beta configs.")
    elif _looks_like_placeholder_domain(public):
        notes.append("The public URL still looks like a placeholder. Replace it with your real domain before public beta.")
    elif not public.startswith("https://"):
        notes.append("Public URL should be HTTPS for real beta testers.")
    if has_real_public_domain(settings) and _public_host(settings) != _public_hostname(settings):
        notes.append("Public URL includes a non-default port or userinfo; generated Nginx uses only the hostname in server_name/certificate paths. Review listen/certificate settings manually.")
    if has_real_public_domain(settings) and not bool(settings.get("trust_proxy_headers")):
        notes.append("Set trust_proxy_headers=true when Caddy/Nginx terminates HTTPS in front of Hui Chat.")
    if has_real_public_domain(settings) and bool(settings.get("auto_allow_lan_origins")):
        notes.append("Disable auto_allow_lan_origins for public beta and use exact allowed_origins instead.")
    allowed = settings.get("allowed_origins") or settings.get("cors_allowed_origins") or []
    if "*" in allowed:
        notes.append("Do not use wildcard origins for public beta.")
    backend = backend_url(settings)
    if backend.startswith("http://0.0.0.0") or backend.startswith("http://[::]"):
        notes.append("Prefer a local backend such as http://127.0.0.1:5000 behind the reverse proxy.")
    return notes


def build_proxy_config_bundle(settings: dict[str, Any], proxy: str = "all") -> list[ProxyConfigBundle]:
    proxy = str(proxy or "all").strip().lower()
    if proxy not in {"all", "caddy", "nginx"}:
        raise ValueError("proxy must be one of: all, caddy, nginx")
    bundles: list[ProxyConfigBundle] = []
    if proxy in {"all", "caddy"}:
        bundles.append(ProxyConfigBundle("caddy", "Caddyfile", generate_caddyfile(settings)))
    if proxy in {"all", "nginx"}:
        bundles.append(ProxyConfigBundle("nginx", "hui-chat.nginx.conf", generate_nginx_config(settings)))
    return bundles


def write_proxy_configs(settings: dict[str, Any], output_dir: str | Path, proxy: str = "all", *, repo_root: str | Path | None = None) -> list[ProxyConfigBundle]:
    out = validate_proxy_output_dir(output_dir, repo_root=repo_root)
    out.mkdir(parents=True, exist_ok=True)
    written: list[ProxyConfigBundle] = []
    for bundle in build_proxy_config_bundle(settings, proxy):
        path = out / bundle.path
        path.write_text(bundle.content, encoding="utf-8")
        written.append(ProxyConfigBundle(bundle.proxy, str(path), bundle.content))
    readme = out / "README.md"
    notes = proxy_readiness_notes(settings)
    readme.write_text(
        "# Hui Chat generated reverse proxy configs\n\n"
        + (
            "**Status: LAN-only / no real public domain configured.**\n\n"
            if not has_real_public_domain(settings)
            else "**Status: public-domain reverse proxy templates.**\n\n"
        )
        + f"Public URL: `{_public_url(settings) or '(not set)'}`\n\n"
        + f"Backend: `{backend_url(settings)}`" + (f" plus {len(backend_urls(settings))-1} more backend(s)" if len(backend_urls(settings)) > 1 else "") + "\n\n"
        + "Generated files:\n"
        + "".join(f"- `{Path(item.path).name}` ({item.proxy})\n" for item in written)
        + "\nRecommended Hui Chat settings for public beta:\n\n"
        + "```json\n"
        + f"{{\n  \"public_base_url\": \"{_public_url(settings) or 'https://YOUR-REAL-DOMAIN'}\",\n  \"cookie_secure\": true,\n  \"trust_proxy_headers\": true,\n  \"proxy_fix_hops\": 1,\n  \"auto_allow_lan_origins\": false\n}}\n"
        + "```\n\n"
        + (
            "No-domain path:\n"
            "1. Keep testing on LAN with HTTP.\n"
            "2. Get a real domain or use a tunnel provider.\n"
            "3. Set public_base_url to the exact HTTPS address testers will open.\n"
            "4. Regenerate these proxy configs.\n\n"
            if not has_real_public_domain(settings)
            else ""
        )
        + ("Warnings to review:\n" + "".join(f"- {note}\n" for note in notes) if notes else "No generator warnings. Run `python main.py --public-beta-check` before inviting testers.\n"),
        encoding="utf-8",
    )
    return written


def format_proxy_generation_report(settings: dict[str, Any], written: list[ProxyConfigBundle]) -> str:
    real_domain = has_real_public_domain(settings)
    lines = [
        "Hui Chat Reverse Proxy Config Generator",
        "",
        f"Public URL: {_public_url(settings) or '(not set - no domain yet)'}",
        f"Backend: {backend_url(settings)}",
        f"Mode: {'public-domain reverse proxy' if real_domain else 'LAN-only / no domain yet'}",
        "",
        "Generated files:",
    ]
    for item in written:
        lines.append(f"  - {item.proxy}: {item.path}")
    notes = proxy_readiness_notes(settings)
    if notes:
        lines.extend(["", "Review before public beta:"])
        lines.extend(f"  - {note}" for note in notes)
    if real_domain:
        lines.extend([
            "",
            "Next steps:",
            "  1. Point DNS for your domain to this server.",
            "  2. Install Caddy or Nginx on the public host.",
            "  3. Copy the generated config into the proxy's config directory.",
            "  4. Open only ports 80/443 publicly; keep PostgreSQL, Redis, and the raw app port private.",
            "  5. Run: python main.py --public-beta-check",
        ])
    else:
        lan_port = _lan_proxy_port(settings)
        lines.extend([
            "",
            "No domain yet - safe next steps:",
            f"  1. Keep testing on your LAN at http://SERVER-LAN-IP:{lan_port} or http://SERVER-LAN-IP:5000.",
            "  2. Do not invite internet testers yet; this config is not public HTTPS.",
            "  3. Get a real domain, or use a tunnel service that gives you an HTTPS hostname.",
            "  4. Set public_base_url to that exact HTTPS address.",
            "  5. Regenerate: python main.py --generate-proxy-config all",
            "  6. Then run: python main.py --public-beta-check",
        ])
    return "\n".join(lines).rstrip() + "\n"
