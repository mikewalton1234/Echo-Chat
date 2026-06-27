#!/usr/bin/env python3
"""Dynamic DNS helpers for Echo-Chat.

This module is intentionally explicit: Echo-Chat never updates an external DNS
provider unless the admin enables DDNS and runs the helper/update path.  Runtime
validation rejects private/loopback provider endpoints so a malicious or
mistyped update URL cannot turn this helper into a local-network request tool.
"""

from __future__ import annotations

import ipaddress
import logging
import os
import re
import socket
import urllib.parse
from typing import Any

import requests  # third-party
from requests.auth import HTTPBasicAuth


_PROVIDER_DEFAULT_UPDATE_URLS = {
    "no-ip": "https://dynupdate.no-ip.com/nic/update",
    "noip": "https://dynupdate.no-ip.com/nic/update",
    "dynu": "https://api.dynu.com/nic/update",
    "dnsomatic": "https://updates.dnsomatic.com/nic/update",
    "custom": "",
}
_HOSTNAME_RE = re.compile(r"^(?=.{1,253}\.?$)(?!-)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}\.?$", re.IGNORECASE)
_PLACEHOLDER_DDNS_HOSTS = {
    "example.com",
    "example.net",
    "example.org",
    "chat.example.com",
    "yourdomain.com",
    "your-domain.com",
    "your-real-domain.com",
    "your-ddns-host.example.com",
}


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on", "enabled"}


def _env_first(*names: str) -> str:
    for name in names:
        value = os.getenv(name)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _env_bool(*names: str) -> bool | None:
    for name in names:
        value = os.getenv(name)
        if value is None:
            continue
        raw = str(value).strip().lower()
        if raw in {"1", "true", "yes", "y", "on", "enabled"}:
            return True
        if raw in {"0", "false", "no", "n", "off", "disabled"}:
            return False
    return None


def _is_public_dns_target(host: str) -> bool:
    """Return True only when every resolved address is globally routable."""
    host = str(host or "").strip().strip("[]").lower()
    if not host or host == "localhost" or host.endswith(".local"):
        return False
    try:
        ip = ipaddress.ip_address(host)
        return bool(getattr(ip, "is_global", False) and not (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ))
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except Exception:
        return False
    saw_public = False
    for info in infos:
        raw_ip = (info[4] or [""])[0]
        try:
            ip = ipaddress.ip_address(str(raw_ip).split("%", 1)[0])
        except ValueError:
            return False
        if not bool(getattr(ip, "is_global", False) and not (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        )):
            return False
        saw_public = True
    return saw_public


def _valid_dynamic_dns_domain(raw_domain: Any) -> bool:
    """Validate the hostname the provider should update, without DNS lookups."""
    domain = str(raw_domain or "").strip().lower().rstrip(".")
    if not domain:
        return False
    if "://" in domain or "/" in domain or "?" in domain or "#" in domain or any(ch.isspace() for ch in domain):
        return False
    if domain in {"localhost", "local"} or domain.endswith(".local"):
        return False
    if domain in _PLACEHOLDER_DDNS_HOSTS or domain.endswith(".example.com") or domain.endswith(".example.net") or domain.endswith(".example.org"):
        return False
    return bool(_HOSTNAME_RE.match(domain))


def _valid_dynamic_dns_update_url_syntax(raw_url: Any) -> bool:
    """Validate provider URL shape without making DNS/network calls."""
    try:
        raw = str(raw_url or "").strip()
        if not raw or len(raw) > 2048 or any(ch.isspace() for ch in raw):
            return False
        parsed = urllib.parse.urlparse(raw)
        if parsed.scheme not in {"http", "https"}:
            return False
        if parsed.username or parsed.password:
            return False
        if not parsed.hostname:
            return False
        port = int(parsed.port or (443 if parsed.scheme == "https" else 80))
        return 0 < port <= 65535
    except Exception:
        return False


def _safe_dynamic_dns_update_url(raw_url: str | None) -> str | None:
    """Validate the admin-configured DDNS endpoint before the server calls it."""
    try:
        raw = str(raw_url or "").strip()
        if not _valid_dynamic_dns_update_url_syntax(raw):
            return None
        parsed = urllib.parse.urlparse(raw)
        host = parsed.hostname or ""
        if not _is_public_dns_target(host):
            return None
        return raw
    except Exception:
        return None


def effective_dynamic_dns_settings(settings: dict[str, Any] | None) -> dict[str, Any]:
    """Merge saved config with DDNS environment variables.

    Environment variables are deliberately supported so production installs can
    keep provider passwords out of server_config.json:
      - ECHOCHAT_DYNAMIC_DNS_PASSWORD / ECHOCHAT_DDNS_PASSWORD / DDNS_PASSWORD
      - matching *_USERNAME, *_DOMAIN, *_UPDATE_URL, and *_ENABLED names.
    """
    settings = dict(settings or {})
    provider = _env_first("ECHOCHAT_DYNAMIC_DNS_PROVIDER", "ECHOCHAT_DDNS_PROVIDER", "DDNS_PROVIDER") or str(settings.get("dynamic_dns_provider") or "No-IP").strip() or "No-IP"
    provider_key = provider.strip().lower().replace(" ", "-")
    default_url = _PROVIDER_DEFAULT_UPDATE_URLS.get(provider_key, "")
    enabled_env = _env_bool("ECHOCHAT_DYNAMIC_DNS_ENABLED", "ECHOCHAT_DDNS_ENABLED", "DDNS_ENABLED")

    return {
        "enabled": bool(enabled_env if enabled_env is not None else _truthy(settings.get("dynamic_dns_enabled"))),
        "provider": provider,
        "username": _env_first("ECHOCHAT_DYNAMIC_DNS_USERNAME", "ECHOCHAT_DDNS_USERNAME", "DDNS_USERNAME") or str(settings.get("dynamic_dns_username") or "").strip(),
        "password": _env_first("ECHOCHAT_DYNAMIC_DNS_PASSWORD", "ECHOCHAT_DDNS_PASSWORD", "DDNS_PASSWORD") or str(settings.get("dynamic_dns_password") or ""),
        "domain": _env_first("ECHOCHAT_DYNAMIC_DNS_DOMAIN", "ECHOCHAT_DDNS_DOMAIN", "DDNS_DOMAIN") or str(settings.get("dynamic_dns_domain") or "").strip(),
        "update_url": _env_first("ECHOCHAT_DYNAMIC_DNS_UPDATE_URL", "ECHOCHAT_DDNS_UPDATE_URL", "DDNS_UPDATE_URL") or str(settings.get("dynamic_dns_update_url") or default_url).strip(),
        "public_ip_url": _env_first("ECHOCHAT_DYNAMIC_DNS_PUBLIC_IP_URL", "ECHOCHAT_DDNS_PUBLIC_IP_URL", "DDNS_PUBLIC_IP_URL") or str(settings.get("dynamic_dns_public_ip_url") or "https://api.ipify.org").strip(),
    }


def dynamic_dns_setup_errors(settings: dict[str, Any] | None) -> list[str]:
    """Return configuration errors without contacting the DDNS provider."""
    cfg = effective_dynamic_dns_settings(settings)
    if not cfg["enabled"]:
        return []
    errors: list[str] = []
    if not cfg["username"]:
        errors.append("Dynamic DNS is enabled, but the provider username is missing.")
    if not cfg["password"]:
        errors.append("Dynamic DNS is enabled, but the provider password/token is missing. Store it in config for LAN testing or set ECHOCHAT_DYNAMIC_DNS_PASSWORD / DDNS_PASSWORD in production.")
    if not _valid_dynamic_dns_domain(cfg["domain"]):
        errors.append("Dynamic DNS is enabled, but the hostname/domain is missing, invalid, local-only, or still a placeholder.")
    if not _valid_dynamic_dns_update_url_syntax(cfg["update_url"]):
        errors.append("Dynamic DNS is enabled, but the provider update URL must be an http(s) URL without embedded credentials.")
    if str(cfg.get("public_ip_url") or "").strip() != "https://api.ipify.org":
        # Keep the public-IP source fixed unless this is deliberately changed in code.
        errors.append("Dynamic DNS public IP lookup URL must remain https://api.ipify.org.")
    return errors


def build_dynamic_dns_report(settings: dict[str, Any] | None, *, live_check: bool = False) -> dict[str, Any]:
    """Return a reviewable DDNS helper report.

    live_check=True validates that the provider update URL resolves only to public
    IP addresses but does not update the DNS record.
    """
    cfg = effective_dynamic_dns_settings(settings)
    errors = dynamic_dns_setup_errors(settings)
    warnings: list[str] = []
    endpoint_public = None
    safe_update_url = None
    if cfg["enabled"] and not errors and live_check:
        safe_update_url = _safe_dynamic_dns_update_url(cfg["update_url"])
        endpoint_public = bool(safe_update_url)
        if not safe_update_url:
            errors.append("Dynamic DNS provider update URL did not resolve to a safe public endpoint.")
    if not cfg["enabled"]:
        warnings.append("Dynamic DNS is disabled. This is fine if your public IP is static, you use a tunnel, or you update DNS somewhere else.")
    return {
        "enabled": cfg["enabled"],
        "provider": cfg["provider"],
        "domain": cfg["domain"],
        "update_url": cfg["update_url"],
        "has_username": bool(cfg["username"]),
        "has_password": bool(cfg["password"]),
        "endpoint_public": endpoint_public,
        "overall": "fail" if errors else ("warn" if warnings else "pass"),
        "errors": errors,
        "warnings": warnings,
    }


def format_dynamic_dns_report(report: dict[str, Any]) -> str:
    lines = [
        "Echo-Chat Dynamic DNS Helper",
        "",
        f"Status: {str(report.get('overall') or 'warn').upper()}",
        f"Enabled: {'yes' if report.get('enabled') else 'no'}",
        f"Provider: {report.get('provider') or '(not set)'}",
        f"Hostname: {report.get('domain') or '(not set)'}",
        f"Update URL: {report.get('update_url') or '(not set)'}",
        f"Username present: {'yes' if report.get('has_username') else 'no'}",
        f"Password/token present: {'yes' if report.get('has_password') else 'no'}",
    ]
    if report.get("endpoint_public") is not None:
        lines.append(f"Provider endpoint public-safe: {'yes' if report.get('endpoint_public') else 'no'}")
    if report.get("errors"):
        lines.extend(["", "Errors:"])
        lines.extend(f"  - {item}" for item in report.get("errors") or [])
    if report.get("warnings"):
        lines.extend(["", "Warnings:"])
        lines.extend(f"  - {item}" for item in report.get("warnings") or [])
    lines.extend([
        "",
        "Run `python main.py --dynamic-dns-update` only when you are ready to send the update request to your provider.",
    ])
    return "\n".join(lines).rstrip() + "\n"


def update_dynamic_dns(settings: dict[str, Any] | None) -> dict[str, Any]:
    """Retrieve the current public IP and update the configured DNS record."""
    cfg = effective_dynamic_dns_settings(settings)
    report = build_dynamic_dns_report(settings, live_check=True)
    if not cfg["enabled"]:
        logging.info("Dynamic DNS is disabled; no update sent.")
        return {**report, "updated": False, "message": "Dynamic DNS is disabled."}
    if report.get("errors"):
        logging.error("Dynamic DNS update blocked by configuration errors: %s", "; ".join(report.get("errors") or []))
        return {**report, "updated": False, "message": "Configuration errors blocked the update."}

    update_url = _safe_dynamic_dns_update_url(cfg["update_url"])
    if not update_url:
        logging.error("Dynamic DNS update URL is missing or not a safe public HTTP(S) endpoint.")
        return {**report, "overall": "fail", "updated": False, "message": "Update URL is not a safe public endpoint."}

    try:
        ip_response = requests.get("https://api.ipify.org", timeout=8)
        ip_response.raise_for_status()
        current_ip = ip_response.text.strip()
        ipaddress.ip_address(current_ip)
        logging.info("Current public IP: %s", current_ip)
    except Exception as e:
        logging.error("Failed to retrieve current IP address: %s", e)
        return {**report, "overall": "fail", "updated": False, "message": f"Failed to retrieve public IP: {e}"}

    params = {"hostname": cfg["domain"], "myip": current_ip}
    try:
        response = requests.get(
            update_url,
            params=params,
            auth=HTTPBasicAuth(cfg["username"], cfg["password"]),
            timeout=10,
        )
        body = response.text[:500]
        if 200 <= response.status_code < 300:
            logging.info("Dynamic DNS update successful: %s", body)
            return {**report, "overall": "pass", "updated": True, "public_ip": current_ip, "provider_status_code": response.status_code, "provider_response": body, "message": "Dynamic DNS update successful."}
        logging.error("Dynamic DNS update failed: HTTP %s: %s", response.status_code, body)
        return {**report, "overall": "fail", "updated": False, "public_ip": current_ip, "provider_status_code": response.status_code, "provider_response": body, "message": "Provider rejected the Dynamic DNS update."}
    except Exception as e:
        logging.error("Error during Dynamic DNS update: %s", e)
        return {**report, "overall": "fail", "updated": False, "public_ip": current_ip, "message": f"Error during Dynamic DNS update: {e}"}


def format_dynamic_dns_update_result(result: dict[str, Any]) -> str:
    lines = [format_dynamic_dns_report(result).rstrip(), ""]
    lines.append(f"Update sent: {'yes' if result.get('updated') else 'no'}")
    if result.get("public_ip"):
        lines.append(f"Public IP: {result.get('public_ip')}")
    if result.get("provider_status_code"):
        lines.append(f"Provider HTTP status: {result.get('provider_status_code')}")
    if result.get("message"):
        lines.append(f"Result: {result.get('message')}")
    return "\n".join(lines).rstrip() + "\n"


def test_dynamic_dns_update(settings: dict[str, Any] | None) -> None:
    """Legacy console wrapper kept for older helper scripts."""
    print("Testing Dynamic DNS update...")
    print(format_dynamic_dns_update_result(update_dynamic_dns(settings)))
    print("Check your DDNS provider's dashboard/logs for verification.")
