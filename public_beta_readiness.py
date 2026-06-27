"""Public beta readiness checks for Echo-Chat.

These checks are intentionally conservative and mostly configuration-based.
They are safe to run before the database is ready and do not start network
listeners, create files, or mutate settings.
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

from health_status import normalize_public_probe_path


@dataclass(frozen=True)
class ReadinessItem:
    level: str
    code: str
    title: str
    detail: str
    fix: str = ""

    @property
    def ok(self) -> bool:
        return self.level == "pass"


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on", "production", "prod"}


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        if value.strip() == "*":
            return ["*"]
        return [part.strip().rstrip("/") for part in value.split(",") if part.strip()]
    if isinstance(value, (list, tuple, set)):
        return [str(part).strip().rstrip("/") for part in value if str(part).strip()]
    return [str(value).strip().rstrip("/")] if str(value).strip() else []


def _clean_url(value: Any) -> str:
    return str(value or "").strip().rstrip("/")


def _env_or_setting(settings: dict[str, Any], env_name: str, setting_name: str) -> str:
    return str(os.getenv(env_name) or settings.get(setting_name) or "").strip()


def _field_crypto_key_available(settings: dict[str, Any], *, field_env: str, field_setting: str, fallback_envs: Iterable[str] = ()) -> bool:
    for env_name in [field_env, *fallback_envs]:
        if str(os.getenv(env_name) or "").strip():
            return True
    if str(settings.get(field_setting) or "").strip():
        return True
    # SECRET_KEY/secret_key is a valid compatibility fallback in the runtime
    # encryption helpers. Public beta should still prefer dedicated env keys,
    # but readiness must reflect the real effective runtime behavior.
    return bool(str(os.getenv("SECRET_KEY") or settings.get("secret_key") or "").strip())


def _normalize_cookie_samesite(value: Any) -> str:
    raw = str(value or "Lax").strip().lower()
    if raw == "none":
        return "None"
    if raw == "strict":
        return "Strict"
    if raw == "lax" or not raw:
        return "Lax"
    return "Invalid"


def _normalise_endpoint_path(value: Any, default: str = "/health") -> str:
    return normalize_public_probe_path(value, default)


def _origin_from_url(url: str) -> str:
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return ""
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"


def _looks_like_placeholder_public_url(value: Any) -> bool:
    raw = str(value or "").strip().lower().rstrip("/")
    if not raw:
        return False
    parsed = urlparse(raw if "://" in raw else f"https://{raw}")
    host = (parsed.hostname or raw).strip().lower().rstrip(".")
    placeholder_hosts = {
        "chat.example.com",
        "example.com",
        "example.net",
        "example.org",
        "yourdomain.com",
        "your-domain.com",
        "your-real-domain.com",
        "your-domain.example",
        "your-real-domain.example",
    }
    return host in placeholder_hosts or host.endswith(".example.com") or host.endswith(".example.net") or host.endswith(".example.org")


def _has_real_public_url(value: Any) -> bool:
    raw = _clean_url(value)
    parsed = urlparse(raw)
    return bool(parsed.scheme in {"http", "https"} and parsed.hostname and not _looks_like_placeholder_public_url(raw))


def _is_local_host(host: str) -> bool:
    h = str(host or "").strip().lower().strip("[]")
    return h in {"", "localhost", "127.0.0.1", "::1"} or h.startswith("/var/run") or h.startswith("/tmp/")


def _is_private_host(host: str) -> bool:
    h = str(host or "").strip().lower().strip("[]")
    if _is_local_host(h):
        return True
    return (
        h.startswith("10.")
        or h.startswith("192.168.")
        or h.startswith("172.16.")
        or h.startswith("172.17.")
        or h.startswith("172.18.")
        or h.startswith("172.19.")
        or h.startswith("172.2")
        or h.startswith("172.30.")
        or h.startswith("172.31.")
    )


def _parse_dsn_host(dsn: str) -> str:
    try:
        parsed = urlparse(str(dsn or ""))
        return parsed.hostname or ""
    except Exception:
        return ""


def _git_tracked(path: str | Path, repo_root: str | Path | None = None) -> bool | None:
    root = Path(repo_root or ".").resolve()
    target = Path(path)
    try:
        result = subprocess.run(
            ["git", "ls-files", "--error-unmatch", str(target)],
            cwd=root,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=4,
        )
        return result.returncode == 0
    except Exception:
        return None


def infer_hosting_mode(settings: dict[str, Any]) -> str:
    raw = str(settings.get("hosting_mode") or settings.get("deployment_profile") or "").strip().lower().replace(" ", "_").replace("-", "_")
    if raw in {"local", "lan", "local_lan", "development", "dev"}:
        return "lan"
    if raw in {"no_domain", "no_domain_yet", "pending_domain", "domain_needed", "domain_later"}:
        return "no_domain_yet"
    if raw in {"public", "public_beta", "internet", "production"}:
        return "public_beta"
    if raw in {"advanced", "custom", "reverse_proxy"}:
        return "advanced"
    public_url = _clean_url(settings.get("public_base_url"))
    if public_url.startswith("https://") and not _looks_like_placeholder_public_url(public_url):
        return "public_beta"
    if _looks_like_placeholder_public_url(public_url):
        return "no_domain_yet"
    return "lan"


def apply_hosting_mode_preset(settings: dict[str, Any], mode: str, public_base_url: str = "") -> dict[str, Any]:
    """Return a copy of settings with safe defaults for a hosting profile."""
    out = dict(settings or {})
    mode = str(mode or "lan").strip().lower().replace(" ", "_").replace("-", "_")
    if mode in {"no_domain", "pending_domain", "domain_needed", "domain_later"}:
        mode = "no_domain_yet"
    if mode not in {"lan", "no_domain_yet", "public_beta", "advanced"}:
        mode = "lan"
    out["hosting_mode"] = mode

    if public_base_url:
        out["public_base_url"] = _clean_url(public_base_url)
    origin = _origin_from_url(_clean_url(out.get("public_base_url")))

    if mode == "no_domain_yet":
        # Safe waiting-room profile: same practical behavior as LAN testing, but
        # with an explicit reminder that the server is not internet-beta-ready.
        out["run_mode"] = out.get("run_mode") or "development"
        out["production_mode"] = str(out.get("run_mode") or "development").lower() == "production"
        out["public_base_url"] = ""
        out["cookie_secure"] = False
        out["allow_insecure_lan_cookie_fallback"] = True
        out["https"] = False
        out["trust_proxy_headers"] = False
        out["auto_allow_lan_origins"] = True
        origins = ["http://127.0.0.1:5000", "http://localhost:5000"]
        out["allowed_origins"] = origins
        out["cors_allowed_origins"] = list(origins)
        out.setdefault("rate_limit_storage_uri", "memory://")
        out.setdefault("rate_limit_storage", out.get("rate_limit_storage_uri"))
        return out

    if mode == "lan":
        out["run_mode"] = out.get("run_mode") or "development"
        out["production_mode"] = str(out.get("run_mode") or "development").lower() == "production"
        out["cookie_secure"] = False
        out["allow_insecure_lan_cookie_fallback"] = True
        out["https"] = False
        out["trust_proxy_headers"] = False
        out["auto_allow_lan_origins"] = True
        if not _as_list(out.get("allowed_origins")):
            origins = ["http://127.0.0.1:5000", "http://localhost:5000"]
            out["allowed_origins"] = origins
            out["cors_allowed_origins"] = list(origins)
        out.setdefault("rate_limit_storage_uri", "memory://")
        out.setdefault("rate_limit_storage", out.get("rate_limit_storage_uri"))
        return out

    if mode == "public_beta":
        out["run_mode"] = "production"
        out["production_mode"] = True
        out["cookie_secure"] = True
        out["allow_insecure_lan_cookie_fallback"] = False
        out["cookie_samesite"] = _normalize_cookie_samesite(out.get("cookie_samesite"))
        out["trust_proxy_headers"] = True
        out["proxy_fix_hops"] = max(1, min(int(out.get("proxy_fix_hops") or 1), 2))
        out["auto_allow_lan_origins"] = False
        out["enable_health_check_endpoint"] = True
        out["health_check_endpoint"] = _normalise_endpoint_path(out.get("health_check_endpoint"), "/health")
        out["production_workers"] = int(out.get("production_workers") or 1)
        out["production_async_mode"] = str(out.get("production_async_mode") or "threading")
        out["socketio_transports"] = out.get("socketio_transports") or ["polling"]
        # TLS is normally terminated by Caddy/Nginx. Keep Echo-Chat's built-in
        # HTTPS listener off unless the admin explicitly turns it on.
        out["https"] = bool(out.get("https", False))
        if origin:
            out["allowed_origins"] = [origin]
            out["cors_allowed_origins"] = [origin]
        if str(out.get("rate_limit_storage_uri") or "").strip() in {"", "memory://"}:
            out["rate_limit_storage_uri"] = "redis://127.0.0.1:6379/0"
            out["rate_limit_storage"] = out["rate_limit_storage_uri"]
        if not str(out.get("socketio_message_queue") or "").strip():
            out["socketio_message_queue"] = "redis://127.0.0.1:6379/1"
        if not str(out.get("shared_state_redis_url") or "").strip():
            out["shared_state_redis_url"] = "redis://127.0.0.1:6379/2"
        out["torrent_upload_enabled"] = _truthy(out.get("torrent_upload_enabled", True))
        out["torrent_scrape_enabled"] = _truthy(out.get("torrent_scrape_enabled", False))
        out.setdefault("allow_legacy_torrent_download_without_metadata", False)
        out.setdefault("max_user_file_storage_bytes", 250 * 1024 * 1024)
        out.setdefault("max_user_torrent_storage_bytes", 25 * 1024 * 1024)
        out.setdefault("max_torrent_total_size_bytes", 1024 * 1024 * 1024 * 1024)
        out["encrypt_sensitive_profile_fields"] = _truthy(out.get("encrypt_sensitive_profile_fields", True))
        out["encrypt_email_at_rest"] = _truthy(out.get("encrypt_email_at_rest", True))
        out["encrypt_security_backups"] = _truthy(out.get("encrypt_security_backups", True))
        out["privacy_retention_enabled"] = _truthy(out.get("privacy_retention_enabled", True))
        out.setdefault("privacy_ip_user_agent_retention_days", 30)
        out.setdefault("privacy_audit_detail_retention_days", 90)
        return out

    # Advanced/custom keeps most values untouched but records the profile.
    if origin and not _as_list(out.get("allowed_origins")):
        out["allowed_origins"] = [origin]
        out["cors_allowed_origins"] = [origin]
    return out


def build_public_beta_readiness(settings: dict[str, Any], *, settings_file: str | Path = "server_config.json", repo_root: str | Path | None = None) -> dict[str, Any]:
    items: list[ReadinessItem] = []
    mode = infer_hosting_mode(settings)
    public_url = _clean_url(settings.get("public_base_url"))
    origin = _origin_from_url(public_url)
    allowed = _as_list(settings.get("allowed_origins") or settings.get("cors_allowed_origins"))
    cors = _as_list(settings.get("cors_allowed_origins") or settings.get("allowed_origins"))
    run_mode = str(settings.get("run_mode") or "development").strip().lower()
    production_mode = run_mode == "production" or _truthy(settings.get("production_mode"))
    public_mode = mode == "public_beta"
    no_domain_mode = mode == "no_domain_yet"
    placeholder_public_url = _looks_like_placeholder_public_url(public_url)

    if public_mode:
        items.append(ReadinessItem("pass", "hosting-mode", "Hosting mode is public beta", "Setup is checking the server as an internet-facing beta deployment."))
    elif no_domain_mode:
        items.append(ReadinessItem("warn", "hosting-mode", "No domain yet", "Echo-Chat is in a safe waiting-room mode for LAN testing only.", "Get a real domain or HTTPS tunnel before inviting internet testers."))
    elif mode == "lan":
        items.append(ReadinessItem("warn", "hosting-mode", "Hosting mode is LAN/local", "This is fine for home testing, but not enough for public beta testers.", "In setup, choose Hosting mode: Public beta with domain + HTTPS after you have a domain."))
    else:
        items.append(ReadinessItem("warn", "hosting-mode", "Hosting mode is advanced/custom", "Echo-Chat will not automatically assume every public-beta safety default in advanced mode."))

    if public_mode:
        if placeholder_public_url:
            items.append(ReadinessItem("fail", "public-base-url", "Public base URL is still a placeholder", f"Current value: {public_url}", "Replace it with your real HTTPS domain before public beta."))
        elif public_url.startswith("https://") and origin:
            items.append(ReadinessItem("pass", "public-base-url", "Public base URL is HTTPS", f"{public_url}"))
        elif public_url:
            items.append(ReadinessItem("fail", "public-base-url", "Public base URL is not HTTPS", f"Current value: {public_url}", "Use a real domain with HTTPS, for example https://chat.yourdomain.com."))
        else:
            items.append(ReadinessItem("fail", "public-base-url", "Public base URL is missing", "Public beta mode needs the URL testers will open.", "Set public_base_url to https://chat.yourdomain.com after you have a domain."))
    else:
        if placeholder_public_url:
            items.append(ReadinessItem("warn", "public-base-url", "Public URL is a placeholder", f"Current value: {public_url}", "Clear it or replace it with your real HTTPS domain later."))
        elif public_url:
            items.append(ReadinessItem("warn", "public-base-url", "Public base URL is set outside public mode", f"Current value: {public_url}"))
        else:
            items.append(ReadinessItem("pass", "public-base-url", "No public URL required yet", "Set one after you get a domain or HTTPS tunnel."))

    if production_mode:
        items.append(ReadinessItem("pass", "production-mode", "Production startup mode enabled", "Plain python main.py can use the production runner when run_mode=production."))
    elif public_mode:
        items.append(ReadinessItem("fail", "production-mode", "Production startup mode is not enabled", f"run_mode={run_mode or '(blank)'}", "Set run_mode to production or launch with python main.py --production."))
    else:
        items.append(ReadinessItem("warn", "production-mode", "Development startup mode", "Acceptable for LAN testing only."))

    if not bool(settings.get("debug") or settings.get("server_debug")):
        items.append(ReadinessItem("pass", "debug", "Debug mode is disabled", "Good for online hosting."))
    elif public_mode:
        items.append(ReadinessItem("fail", "debug", "Debug mode is enabled", "Do not expose Flask debug mode to internet testers.", "Set debug=false and server_debug=false."))
    else:
        items.append(ReadinessItem("warn", "debug", "Debug mode is enabled", "Use only on trusted LAN during development."))

    if public_mode:
        if origin and origin in allowed and origin in cors:
            items.append(ReadinessItem("pass", "origins", "Allowed origins match the public URL", f"Allowed origin: {origin}"))
        elif "*" in allowed or "*" in cors:
            items.append(ReadinessItem("fail", "origins", "Wildcard origins are unsafe for public beta", "allowed_origins/cors_allowed_origins contains '*'.", f"Use only: {origin or 'https://chat.yourdomain.com'}"))
        else:
            items.append(ReadinessItem("fail", "origins", "Allowed origins do not match public URL", f"public origin={origin or '(missing)'}; allowed={allowed or '(none)'}; cors={cors or '(none)'}", "Set allowed_origins and cors_allowed_origins to the exact HTTPS public origin."))
        if not bool(settings.get("auto_allow_lan_origins", False)):
            items.append(ReadinessItem("pass", "lan-origins", "Auto LAN origins disabled", "Good for public beta mode."))
        else:
            items.append(ReadinessItem("warn", "lan-origins", "Auto LAN origins still enabled", "This is convenient for home testing, but public beta mode should usually use exact origins only.", "Set auto_allow_lan_origins=false."))
    else:
        items.append(ReadinessItem("pass", "origins", "LAN origin policy is flexible", "auto_allow_lan_origins can help phones connect to the same host/port on your LAN."))

    cookie_secure = bool(settings.get("cookie_secure"))
    cookie_samesite = _normalize_cookie_samesite(settings.get("cookie_samesite"))
    if public_mode:
        if cookie_secure:
            items.append(ReadinessItem("pass", "cookie-secure", "Secure cookies enabled", "Browser auth cookies will be marked Secure for HTTPS."))
        else:
            items.append(ReadinessItem("fail", "cookie-secure", "Secure cookies are disabled", "Public HTTPS beta should use Secure cookies.", "Set cookie_secure=true."))
        if cookie_samesite == "Invalid":
            items.append(ReadinessItem("fail", "cookie-samesite", "Cookie SameSite value is invalid", f"cookie_samesite={settings.get('cookie_samesite')!r}", "Use Lax, Strict, or None."))
        elif cookie_samesite == "None" and not cookie_secure:
            items.append(ReadinessItem("fail", "cookie-samesite", "SameSite=None requires Secure cookies", "Modern browsers reject SameSite=None cookies without Secure.", "Set cookie_secure=true or use cookie_samesite=Lax."))
        else:
            items.append(ReadinessItem("pass", "cookie-samesite", "Cookie SameSite policy is valid", f"cookie_samesite={cookie_samesite}"))
    else:
        if cookie_secure:
            items.append(ReadinessItem("warn", "cookie-secure", "Secure cookies enabled during LAN/HTTP mode", "If you open http://LAN-IP:5000, the browser may refuse auth cookies.", "Use HTTPS or set cookie_secure=false for LAN testing."))
        else:
            items.append(ReadinessItem("pass", "cookie-secure", "LAN cookie mode is HTTP-friendly", "cookie_secure=false is normal for local HTTP testing."))

    if public_mode:
        if not _truthy(settings.get("allow_insecure_lan_cookie_fallback", False)):
            items.append(ReadinessItem("pass", "lan-cookie-fallback", "Insecure LAN cookie fallback disabled", "Good for public beta mode."))
        else:
            items.append(ReadinessItem("fail", "lan-cookie-fallback", "Insecure LAN cookie fallback is enabled", "This is only for trusted LAN HTTP testing.", "Set allow_insecure_lan_cookie_fallback=false."))

    if public_mode:
        if _truthy(settings.get("enforce_same_origin_writes", True)):
            items.append(ReadinessItem("pass", "same-origin-writes", "Same-origin write guard enabled", "Cross-site POST/PUT/PATCH/DELETE requests are blocked before route logic."))
        else:
            items.append(ReadinessItem("fail", "same-origin-writes", "Same-origin write guard disabled", "Cookie-authenticated write APIs should not accept cross-site writes.", "Set enforce_same_origin_writes=true."))

    if public_mode:
        try:
            from secrets_policy import persist_secrets_enabled
            secrets_persist = bool(persist_secrets_enabled(settings))
        except Exception:
            secrets_persist = True
        if not secrets_persist:
            items.append(ReadinessItem("pass", "secret-persistence", "Config secret persistence disabled", "Production/public mode keeps secrets in environment variables or a secret manager."))
        else:
            items.append(ReadinessItem("fail", "secret-persistence", "Config secret persistence is enabled", "Public beta configs should not write API keys, database passwords, JWT secrets, or encryption keys to server_config.json.", "Set ECHOCHAT_PERSIST_SECRETS=0 or use public_beta/production mode defaults."))

        profile_encrypt = _truthy(settings.get("encrypt_sensitive_profile_fields", True))
        profile_key = _field_crypto_key_available(settings, field_env="ECHOCHAT_PROFILE_FIELD_KEY", field_setting="profile_field_encryption_key")
        if profile_encrypt and profile_key:
            items.append(ReadinessItem("pass", "profile-field-crypto", "Sensitive profile-field crypto ready", "Phone/address/location-style fields can be encrypted at rest."))
        elif profile_encrypt:
            items.append(ReadinessItem("fail", "profile-field-crypto", "Sensitive profile-field crypto key missing", "Encryption is enabled but no stable profile-field key is available.", "Set ECHOCHAT_PROFILE_FIELD_KEY before public beta."))
        else:
            items.append(ReadinessItem("fail", "profile-field-crypto", "Sensitive profile-field crypto disabled", "Public beta should not store sensitive profile/contact fields as plaintext.", "Set encrypt_sensitive_profile_fields=true and provide ECHOCHAT_PROFILE_FIELD_KEY."))

        email_encrypt = _truthy(settings.get("encrypt_email_at_rest", True))
        email_field_key = _field_crypto_key_available(settings, field_env="ECHOCHAT_EMAIL_FIELD_KEY", field_setting="email_field_encryption_key", fallback_envs=("ECHOCHAT_PROFILE_FIELD_KEY",))
        email_hash_key = bool(_env_or_setting(settings, "ECHOCHAT_EMAIL_HASH_KEY", "email_hash_key")) or email_field_key
        if email_encrypt and email_field_key and email_hash_key:
            items.append(ReadinessItem("pass", "email-at-rest-crypto", "Email at-rest encryption ready", "Email lookup hashes and display envelopes have effective keys."))
        elif email_encrypt:
            items.append(ReadinessItem("fail", "email-at-rest-crypto", "Email at-rest encryption key missing", "Encryption is enabled but email field/hash key material is incomplete.", "Set ECHOCHAT_EMAIL_FIELD_KEY and ECHOCHAT_EMAIL_HASH_KEY before public beta."))
        else:
            items.append(ReadinessItem("fail", "email-at-rest-crypto", "Email at-rest encryption disabled", "Public beta should not keep account emails as plaintext-only user rows.", "Set encrypt_email_at_rest=true and provide email encryption keys."))

        backup_encrypt = _truthy(settings.get("encrypt_security_backups", True))
        backup_key = _field_crypto_key_available(settings, field_env="ECHOCHAT_SECURITY_BACKUP_KEY", field_setting="security_backup_encryption_key", fallback_envs=("ECHOCHAT_PROFILE_FIELD_KEY", "ECHOCHAT_EMAIL_FIELD_KEY"))
        if backup_encrypt and backup_key:
            items.append(ReadinessItem("pass", "security-backups", "Encrypted security backups ready", "Security-operation backups will be written as encrypted .json.enc envelopes."))
        elif backup_encrypt:
            items.append(ReadinessItem("fail", "security-backups", "Security backup encryption key missing", "Backup encryption is enabled but no backup/profile/email/app key is available.", "Set ECHOCHAT_SECURITY_BACKUP_KEY before public beta."))
        else:
            items.append(ReadinessItem("fail", "security-backups", "Security backup encryption disabled", "Security-operation backups can contain emails and contact fields and must be encrypted for public beta.", "Set encrypt_security_backups=true."))

        try:
            privacy_days = int(settings.get("privacy_ip_user_agent_retention_days", 30) or 0)
        except Exception:
            privacy_days = 0
        try:
            audit_days = int(settings.get("privacy_audit_detail_retention_days", 90) or 0)
        except Exception:
            audit_days = 0
        if _truthy(settings.get("privacy_retention_enabled", True)) and privacy_days > 0 and audit_days > 0:
            items.append(ReadinessItem("pass", "privacy-retention", "Privacy retention cleanup enabled", f"IP/UA retention={privacy_days} days; audit detail retention={audit_days} days."))
        else:
            items.append(ReadinessItem("fail", "privacy-retention", "Privacy retention cleanup disabled", "Old IP/user-agent and audit details would stay raw indefinitely.", "Enable privacy_retention_enabled and set positive retention windows."))

    if public_mode:
        if not _truthy(settings.get("torrent_scrape_enabled", False)):
            items.append(ReadinessItem("pass", "torrent-scrape", "Torrent tracker scraping disabled", "The server will not make outbound tracker requests for user-supplied tracker URLs."))
        else:
            items.append(ReadinessItem("warn", "torrent-scrape", "Torrent tracker scraping enabled", "This creates an outbound request abuse surface even with SSRF checks.", "Leave torrent_scrape_enabled=false for public beta unless you also deploy strict shared rate limits and monitoring."))
        if not _truthy(settings.get("allow_legacy_torrent_download_without_metadata", False)):
            items.append(ReadinessItem("pass", "torrent-download-scope", "Legacy torrent downloads require metadata", "Old token-only torrent files are not downloadable unless scoped metadata exists."))
        else:
            items.append(ReadinessItem("warn", "torrent-download-scope", "Legacy torrent download fallback enabled", "Any logged-in user with an old torrent token may be able to download the file.", "Set allow_legacy_torrent_download_without_metadata=false."))

    if public_mode:
        try:
            max_user_file_storage = int(settings.get("max_user_file_storage_bytes") or 0)
        except Exception:
            max_user_file_storage = 0
        try:
            max_user_torrent_storage = int(settings.get("max_user_torrent_storage_bytes") or 0)
        except Exception:
            max_user_torrent_storage = 0
        try:
            max_torrent_payload = int(settings.get("max_torrent_total_size_bytes") or 0)
        except Exception:
            max_torrent_payload = 0

        if bool(settings.get("disable_file_transfer_globally", False)):
            items.append(ReadinessItem("pass", "file-sharing-global", "File sharing globally disabled", "Strongest option for a first public beta."))
        elif max_user_file_storage > 0:
            items.append(ReadinessItem("pass", "file-storage-quota", "Per-user file storage quota enabled", f"max_user_file_storage_bytes={max_user_file_storage}"))
        else:
            items.append(ReadinessItem("warn", "file-storage-quota", "Per-user file storage quota disabled", "Encrypted uploads cannot be content-scanned by the server, so storage abuse needs quotas.", "Set max_user_file_storage_bytes to a bounded value such as 262144000."))

        if max_user_torrent_storage > 0:
            items.append(ReadinessItem("pass", "torrent-storage-quota", "Per-user torrent storage quota enabled", f"max_user_torrent_storage_bytes={max_user_torrent_storage}"))
        else:
            items.append(ReadinessItem("warn", "torrent-storage-quota", "Per-user torrent storage quota disabled", "A user can upload many small .torrent files without a quota.", "Set max_user_torrent_storage_bytes to a bounded value such as 26214400."))

        if 0 < max_torrent_payload <= 1024 * 1024 * 1024 * 1024:
            items.append(ReadinessItem("pass", "torrent-payload-ceiling", "Torrent advertised payload ceiling bounded", f"max_torrent_total_size_bytes={max_torrent_payload}"))
        else:
            items.append(ReadinessItem("warn", "torrent-payload-ceiling", "Torrent advertised payload ceiling missing or very high", "Malicious torrents can advertise absurd file sets and confuse clients/UI.", "Set max_torrent_total_size_bytes to a practical ceiling such as 1099511627776."))

    if public_mode:
        if bool(settings.get("trust_proxy_headers")):
            try:
                hops = int(settings.get("proxy_fix_hops") or 1)
            except Exception:
                hops = 0
            if 1 <= hops <= 2:
                items.append(ReadinessItem("pass", "proxy-headers", "Proxy headers are trusted with a sane hop count", f"proxy_fix_hops={hops}"))
            elif hops <= 0:
                items.append(ReadinessItem("fail", "proxy-headers", "Proxy header hop count is invalid", f"proxy_fix_hops={settings.get('proxy_fix_hops')!r}", "Use proxy_fix_hops=1 when behind one local reverse proxy."))
            else:
                items.append(ReadinessItem("warn", "proxy-headers", "Proxy header hop count is broad", f"proxy_fix_hops={hops}", "Use the exact number of trusted local proxy hops, usually 1."))
        else:
            items.append(ReadinessItem("warn", "proxy-headers", "Proxy headers are not trusted", "If Caddy/Nginx terminates HTTPS, Echo-Chat should trust exactly that proxy hop.", "Set trust_proxy_headers=true and proxy_fix_hops=1 when behind one local reverse proxy."))

    if public_mode:
        try:
            socket_payload_max = int(settings.get("socketio_event_max_payload_bytes") or 65536)
        except Exception:
            socket_payload_max = 65536
        if socket_payload_max <= 131072:
            items.append(ReadinessItem("pass", "socketio-payload-ceiling", "Socket.IO event payload ceiling is bounded", f"socketio_event_max_payload_bytes={socket_payload_max}"))
        else:
            items.append(ReadinessItem("fail", "socketio-payload-ceiling", "Socket.IO event payload ceiling is too high", f"socketio_event_max_payload_bytes={socket_payload_max}", "Set socketio_event_max_payload_bytes to 65536 or at most 131072 for public beta."))

    from redis_socketio_readiness import build_redis_socketio_report

    redis_report = build_redis_socketio_report(settings, live_check=False)
    for raw_item in redis_report.get("items") or []:
        code = str(raw_item.get("code") or "redis-socketio")
        # Keep these integrated into the public beta report so the admin sees one
        # clear readiness list instead of a separate hidden Redis report.
        items.append(ReadinessItem(
            str(raw_item.get("level") or "warn"),
            f"redis-socketio:{code}",
            str(raw_item.get("title") or code),
            str(raw_item.get("detail") or ""),
            str(raw_item.get("fix") or ""),
        ))

    secret = str(settings.get("secret_key") or "")
    jwt = str(settings.get("jwt_secret") or settings.get("jwt_secret_key") or "")
    if len(secret) >= 32 and "change-me" not in secret.lower():
        items.append(ReadinessItem("pass", "secret-key", "Secret key is set", "Length looks suitable."))
    elif public_mode:
        items.append(ReadinessItem("fail", "secret-key", "Secret key is missing or weak", "Public beta requires a strong secret_key.", "Run setup and rotate/generate secrets."))
    else:
        items.append(ReadinessItem("warn", "secret-key", "Secret key is missing or weak", "Generate before public beta."))

    if len(jwt) >= 32 and "change-me" not in jwt.lower():
        items.append(ReadinessItem("pass", "jwt-secret", "JWT secret is set", "Length looks suitable."))
    elif public_mode:
        items.append(ReadinessItem("fail", "jwt-secret", "JWT secret is missing or weak", "Public beta requires a strong JWT secret.", "Run setup and rotate/generate JWT secret."))
    else:
        items.append(ReadinessItem("warn", "jwt-secret", "JWT secret is missing or weak", "Generate before public beta."))

    tracked = _git_tracked(settings_file, repo_root=repo_root)
    if tracked is True:
        items.append(ReadinessItem("fail", "config-git", "server_config.json appears tracked by Git", "This file can contain secrets and should not be pushed publicly.", "Remove it from Git and keep only server_config.example.json / .env.example."))
    elif tracked is False:
        items.append(ReadinessItem("pass", "config-git", "server_config.json is not tracked by Git", "Good for a public repository."))
    else:
        items.append(ReadinessItem("warn", "config-git", "Could not verify Git tracking", "Run git status before pushing."))

    database_url = str(settings.get("database_url") or "").strip()
    db_host = _parse_dsn_host(database_url)
    db_scheme = urlparse(database_url).scheme.lower() if database_url else ""
    if not database_url:
        items.append(ReadinessItem("fail" if public_mode else "warn", "database-url", "Database URL is missing", "Echo-Chat needs PostgreSQL before real beta testing."))
    elif db_scheme not in {"postgresql", "postgres", "postgresql+psycopg2"}:
        items.append(ReadinessItem("fail" if public_mode else "warn", "database-url", "Database URL is not PostgreSQL", f"scheme={db_scheme or '(missing)'}", "Use a PostgreSQL DATABASE_URL such as postgresql://user@localhost:5432/echochat."))
    elif _is_private_host(db_host):
        items.append(ReadinessItem("pass", "database-host", "Database host is private/local", db_host or "local socket/localhost"))
    else:
        items.append(ReadinessItem("warn", "database-host", "Database host is not local/private", db_host, "Verify PostgreSQL is not exposed publicly and pg_hba.conf is locked down."))

    bind = str(settings.get("production_bind") or "").strip() or f"{settings.get('server_host') or settings.get('host') or '0.0.0.0'}:{settings.get('server_port') or settings.get('port') or 5000}"
    if public_mode and (bind.startswith("0.0.0.0:") or bind.startswith("[::]:")):
        items.append(ReadinessItem("warn", "raw-bind", "Echo-Chat binds on all interfaces", bind, "Use firewall rules or bind to 127.0.0.1 behind Caddy/Nginx for public beta."))
    else:
        items.append(ReadinessItem("pass", "raw-bind", "Bind address reviewed", bind))

    endpoint_raw = str(settings.get("health_check_endpoint") or "/health").strip()
    endpoint = _normalise_endpoint_path(endpoint_raw, "/health")
    if public_mode and bool(settings.get("enable_health_check_endpoint")):
        if endpoint_raw and not endpoint_raw.startswith("/"):
            items.append(ReadinessItem("warn", "health", "Health endpoint path was missing leading slash", f"health_check_endpoint={endpoint_raw!r}; normalized={endpoint}", "Store it as /health or /healthz."))
        else:
            items.append(ReadinessItem("pass", "health", "Health endpoint enabled", endpoint))
    elif public_mode:
        items.append(ReadinessItem("warn", "health", "Health endpoint disabled", "Useful for reverse proxies and uptime checks.", "Set enable_health_check_endpoint=true."))
    else:
        items.append(ReadinessItem("pass", "health", "Health endpoint optional in LAN mode", endpoint))

    fail_count = sum(1 for item in items if item.level == "fail")
    warn_count = sum(1 for item in items if item.level == "warn")
    pass_count = sum(1 for item in items if item.level == "pass")
    overall = "fail" if fail_count else "warn" if warn_count else "pass"
    return {
        "overall": overall,
        "mode": mode,
        "pass_count": pass_count,
        "warn_count": warn_count,
        "fail_count": fail_count,
        "items": [item.__dict__ for item in items],
    }


def format_public_beta_readiness_report(report: dict[str, Any]) -> str:
    marker = {"pass": "PASS", "warn": "WARN", "fail": "FAIL"}
    lines = [
        "Echo-Chat Public Beta Readiness",
        "",
        f"Overall: {str(report.get('overall') or 'unknown').upper()}",
        f"Mode: {report.get('mode') or 'unknown'}",
        f"Summary: {report.get('pass_count', 0)} pass, {report.get('warn_count', 0)} warn, {report.get('fail_count', 0)} fail",
        "",
    ]
    for item in report.get("items") or []:
        level = str(item.get("level") or "warn")
        lines.append(f"{marker.get(level, 'CHECK')}  {item.get('title') or item.get('code')}")
        detail = str(item.get("detail") or "").strip()
        if detail:
            lines.append(f"      {detail}")
        fix = str(item.get("fix") or "").strip()
        if fix:
            lines.append(f"      Fix: {fix}")
    if str(report.get("mode") or "") == "no_domain_yet":
        lines.extend([
            "",
            "No-domain path:",
            "  1. Keep Echo-Chat in LAN testing mode.",
            "  2. Do not invite internet testers yet.",
            "  3. Get a domain, or use a tunnel provider that gives an HTTPS hostname.",
            "  4. Set public_base_url to that exact HTTPS address.",
            "  5. Re-run: python main.py --public-beta-check",
        ])
    return "\n".join(lines).rstrip() + "\n"


def public_beta_readiness_lines(settings: dict[str, Any], *, settings_file: str | Path = "server_config.json", repo_root: str | Path | None = None) -> list[str]:
    return format_public_beta_readiness_report(
        build_public_beta_readiness(settings, settings_file=settings_file, repo_root=repo_root)
    ).splitlines()
