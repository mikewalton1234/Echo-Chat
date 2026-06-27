#!/usr/bin/env python3
"""emailer.py

SMTP sender for Echo-Chat transactional email (password reset now, account
verification later).

Design goals:
  - Production-safe: never print reset links or message bodies to logs.
  - Provider-neutral: works with Brevo, Resend, SMTP2GO, MailerSend, SES, etc.
  - Secrets-safe: environment variables override server_config.json.
  - No fake success: if SMTP is not configured, return a hard failure.

Supported settings keys / env vars:
  smtp_enabled                 ECHOCHAT_SMTP_ENABLED / SMTP_ENABLED
  smtp_host / smtp_server       ECHOCHAT_SMTP_HOST / SMTP_HOST
  smtp_port                    ECHOCHAT_SMTP_PORT / SMTP_PORT
  smtp_username / smtp_user     ECHOCHAT_SMTP_USERNAME / SMTP_USERNAME
  smtp_password / smtp_pass     ECHOCHAT_SMTP_PASSWORD / SMTP_PASSWORD
  smtp_use_starttls / smtp_tls  ECHOCHAT_SMTP_STARTTLS / SMTP_STARTTLS
  smtp_use_ssl / smtp_ssl       ECHOCHAT_SMTP_SSL / SMTP_SSL
  smtp_from / from_email        ECHOCHAT_SMTP_FROM / SMTP_FROM
  smtp_timeout_seconds          ECHOCHAT_SMTP_TIMEOUT / SMTP_TIMEOUT
  smtp_provider                 optional provider hint (brevo, custom, etc.)
"""

from __future__ import annotations

import logging
import os
import re
import smtplib
import socket
import ssl
from email.message import EmailMessage
from constants import DEFAULT_SERVER_NAME
from email.utils import formataddr, formatdate, make_msgid, parseaddr


_BOOL_TRUE = {"1", "true", "yes", "y", "on"}
_BOOL_FALSE = {"0", "false", "no", "n", "off"}
_HEADER_BREAK_RE = re.compile(r"[\r\n]")
_SMTP_RETRY_STAGES = {"connect", "connect_ssl", "ehlo", "starttls", "ehlo_after_starttls", "login"}
_PLACEHOLDER_FROM_DOMAINS = {
    "localhost",
    "localdomain",
    "yourdomain.com",
    "example.com",
    "example.net",
    "example.org",
    # EchoChat does not own this domain for arbitrary installs. Treat it as a
    # dangerous sample/default unless the admin deliberately removes this guard.
    "echochat.com",
    "smtp-brevo.com",
}


def _mark_smtp_stage(exc: BaseException, stage: str) -> BaseException:
    try:
        setattr(exc, "_echochat_smtp_stage", stage)
    except Exception:
        pass
    return exc


def _smtp_stage(exc: BaseException) -> str:
    return str(getattr(exc, "_echochat_smtp_stage", "") or "")


def _is_timeoutish_smtp_error(exc: BaseException) -> bool:
    timeout_types = (TimeoutError, socket.timeout, smtplib.SMTPConnectError, smtplib.SMTPServerDisconnected)
    if isinstance(exc, timeout_types):
        return True
    return "timed out" in str(exc).lower()


def _get(settings: dict, *keys, default=None):
    for k in keys:
        if k in settings and settings[k] not in (None, ""):
            return settings[k]
    return default


def _display_server_name(settings: dict | None) -> str:
    """Return the configured public server name for email display headers."""
    raw = str((settings or {}).get("server_name") or DEFAULT_SERVER_NAME).strip() or DEFAULT_SERVER_NAME
    # Header display names cannot safely contain line breaks; keep the fallback branded.
    if _HEADER_BREAK_RE.search(raw):
        return DEFAULT_SERVER_NAME
    return raw


def _env(*names: str) -> str | None:
    for name in names:
        value = os.getenv(name)
        if value is not None and str(value).strip() != "":
            return str(value).strip()
    return None


def _bool_value(value, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    raw = str(value if value is not None else "").strip().lower()
    if raw in _BOOL_TRUE:
        return True
    if raw in _BOOL_FALSE:
        return False
    return default




def _addr_part(mailbox: str) -> str:
    return str(parseaddr(str(mailbox or ""))[1] or "").strip().lower()


def _from_address_warning(provider: str, from_email: str) -> str | None:
    addr = _addr_part(from_email)
    if not addr or "@" not in addr:
        return "invalid_from_address"
    local, domain = addr.rsplit("@", 1)
    if not local or not domain or "." not in domain:
        return "invalid_from_address"
    if domain in _PLACEHOLDER_FROM_DOMAINS or domain.endswith(".local"):
        if provider in {"brevo", "resend", "smtp2go", "mailersend", "mailjet"}:
            return "invalid_from_placeholder"
        return "from_placeholder_not_deliverable"
    if addr in {"noreply@echochat.com", "no-reply@echochat.com", "noreplay@echochat.com"}:
        return "invalid_from_placeholder"
    return None


def smtp_from_warning(provider: str, from_email: str) -> str | None:
    """Return a stable warning code for an SMTP From/Sender address.

    This is used by setup, diagnostics, and runtime delivery guards. It cannot
    prove that a domain is verified inside Brevo/Resend/etc.; it rejects only
    syntactically invalid or obviously placeholder/local sender addresses.
    Provider dashboards remain the source of truth for verification status.
    """

    return _from_address_warning(str(provider or ""), str(from_email or ""))


def describe_smtp_settings(settings: dict) -> dict:
    """Return a redacted, human-readable view of the effective SMTP config."""
    cfg = _smtp_settings(settings or {})
    out = {
        "enabled": bool(cfg.get("enabled")),
        "provider": cfg.get("provider") or "custom",
        "host": cfg.get("host") or "",
        "port": int(cfg.get("port") or 0),
        "starttls": bool(cfg.get("starttls")),
        "use_ssl": bool(cfg.get("use_ssl")),
        "username_set": bool(cfg.get("username")),
        "password_set": bool(cfg.get("password")),
        "from_email": cfg.get("from_email") or "",
        "timeout": int(cfg.get("timeout") or 0),
        "mode_hint": cfg.get("mode_hint"),
        "from_warning": _from_address_warning(str(cfg.get("provider") or ""), str(cfg.get("from_email") or "")),
    }
    return out


def effective_smtp_settings(settings: dict) -> dict:
    """Return the same SMTP settings that runtime send_email() will use.

    Unlike describe_smtp_settings(), this includes the resolved username/password
    so setup diagnostics can verify the exact configuration path used by
    password-reset email. Callers must never log the returned password.
    """

    return dict(_smtp_settings(settings or {}))

def _safe_header(value: str, field_name: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        raise ValueError(f"missing_{field_name}")
    if _HEADER_BREAK_RE.search(raw):
        raise ValueError(f"invalid_{field_name}")
    return raw


def _safe_mailbox(value: str, *, default_display: str | None = None) -> str:
    """Validate and normalize one mailbox for message headers.

    This intentionally stays simple: it rejects header injection and requires a
    syntactically plausible address. Provider-side domain verification remains
    the source of truth for deliverability.
    """

    raw = _safe_header(value, "email")
    display, addr = parseaddr(raw)
    addr = str(addr or "").strip()
    if not addr or "@" not in addr or any(ch.isspace() for ch in addr):
        raise ValueError("invalid_email")
    if _HEADER_BREAK_RE.search(display):
        raise ValueError("invalid_email")
    return formataddr((display or default_display or "", addr))


def _int_value(value, default: int, *, min_value: int = 1, max_value: int = 120) -> int:
    try:
        out = int(value)
    except Exception:
        out = int(default)
    return max(min_value, min(max_value, out))


def _provider_hint(settings: dict, host: str) -> str:
    provider = str(_get(settings, "smtp_provider", default="") or "").strip().lower()
    host_l = str(host or "").strip().lower()
    if not provider and "brevo.com" in host_l:
        provider = "brevo"
    return provider


def _smtp_mode_hint(provider: str, host: str, port: int, starttls: bool, use_ssl: bool) -> str | None:
    if provider == "brevo" and "brevo.com" in str(host or "").lower():
        if use_ssl and port != 465:
            return "Brevo implicit TLS normally uses port 465; STARTTLS normally uses 587."
        if starttls and port not in {587, 2525}:
            return "Brevo STARTTLS normally uses port 587, with 2525 only as a fallback."
        if port == 2525 and starttls:
            return "Brevo recommends port 587 first; 2525 is a fallback for blocked networks."
    return None


def _smtp_settings(settings: dict) -> dict:
    env_enabled = _env("ECHOCHAT_SMTP_ENABLED", "SMTP_ENABLED")
    enabled = _bool_value(env_enabled, default=bool(_get(settings, "smtp_enabled", default=False)))

    host = _env("ECHOCHAT_SMTP_HOST", "SMTP_HOST") or _get(settings, "smtp_host", "smtp_server", default="")
    try:
        port = int(_env("ECHOCHAT_SMTP_PORT", "SMTP_PORT") or _get(settings, "smtp_port", default=587) or 587)
    except Exception:
        port = 587
    provider = _provider_hint(settings, str(host or ""))
    timeout = _int_value(_env("ECHOCHAT_SMTP_TIMEOUT", "SMTP_TIMEOUT") or _get(settings, "smtp_timeout_seconds", default=20), 20, min_value=3, max_value=120)

    username = _env("ECHOCHAT_SMTP_USERNAME", "ECHOCHAT_SMTP_USER", "SMTP_USERNAME", "SMTP_USER") or _get(settings, "smtp_username", "smtp_user", default="")
    password = _env("ECHOCHAT_SMTP_PASSWORD", "ECHOCHAT_SMTP_PASS", "SMTP_PASSWORD", "SMTP_PASS") or _get(settings, "smtp_password", "smtp_pass", default="")

    env_starttls = _env("ECHOCHAT_SMTP_STARTTLS", "SMTP_STARTTLS")
    starttls = _bool_value(env_starttls, default=bool(_get(settings, "smtp_use_starttls", "smtp_tls", default=True)))

    env_ssl = _env("ECHOCHAT_SMTP_SSL", "SMTP_SSL")
    use_ssl = _bool_value(env_ssl, default=bool(_get(settings, "smtp_use_ssl", "smtp_ssl", default=False)))
    if port in {465, 2465, 8465, 443}:
        use_ssl = True
    if use_ssl:
        # Runtime uses either implicit TLS or STARTTLS. Do not let a config that
        # has both flags true try to speak implicit TLS and STARTTLS at once.
        starttls = False

    server_display_name = _display_server_name(settings)
    from_email = _env("ECHOCHAT_SMTP_FROM", "SMTP_FROM") or _get(
        settings,
        "smtp_from",
        "from_email",
        default=f"{server_display_name} <no-reply@localhost>",
    )

    return {
        "server_display_name": server_display_name,
        "enabled": enabled,
        "host": str(host or "").strip(),
        "port": port,
        "username": str(username or "").strip(),
        "password": str(password or ""),
        "starttls": bool(starttls),
        "use_ssl": bool(use_ssl),
        "from_email": str(from_email or "").strip(),
        "provider": provider,
        "timeout": timeout,
        "mode_hint": _smtp_mode_hint(provider, str(host or ""), port, bool(starttls), bool(use_ssl)),
        "from_warning": _from_address_warning(provider, str(from_email or "")),
    }


def _send_with_config(cfg: dict, msg: EmailMessage) -> None:
    context = ssl.create_default_context()
    stage = "connect"
    try:
        if cfg["use_ssl"]:
            stage = "connect_ssl"
            with smtplib.SMTP_SSL(cfg["host"], cfg["port"], timeout=cfg["timeout"], context=context) as smtp:
                stage = "ehlo"
                smtp.ehlo()
                stage = "login"
                smtp.login(cfg["username"], cfg["password"])
                stage = "send"
                smtp.send_message(msg)
        else:
            stage = "connect"
            with smtplib.SMTP(cfg["host"], cfg["port"], timeout=cfg["timeout"]) as smtp:
                stage = "ehlo"
                smtp.ehlo()
                if cfg["starttls"]:
                    stage = "starttls"
                    smtp.starttls(context=context)
                    stage = "ehlo_after_starttls"
                    smtp.ehlo()
                stage = "login"
                smtp.login(cfg["username"], cfg["password"])
                stage = "send"
                smtp.send_message(msg)
    except Exception as exc:
        raise _mark_smtp_stage(exc, stage)


def _brevo_retry_candidates(cfg: dict, exc: BaseException) -> list[dict]:
    """Return safe Brevo retry modes after a pre-DATA timeout.

    Brevo documents 587 as the normal STARTTLS port, 2525 as the common
    fallback when 587 is blocked, and 465 as implicit TLS. Retry only before
    DATA/send_message so a successful delivery is not duplicated.
    """

    if cfg.get("provider") != "brevo":
        return []
    if "brevo.com" not in str(cfg.get("host") or "").lower():
        return []
    if _smtp_stage(exc) not in _SMTP_RETRY_STAGES:
        return []
    if not _is_timeoutish_smtp_error(exc):
        return []

    modes = [
        {"port": 587, "starttls": True, "use_ssl": False, "label": "587_starttls"},
        {"port": 2525, "starttls": True, "use_ssl": False, "label": "2525_starttls"},
        {"port": 465, "starttls": False, "use_ssl": True, "label": "465_ssl"},
    ]
    out = []
    current = (int(cfg.get("port") or 0), bool(cfg.get("starttls")), bool(cfg.get("use_ssl")))
    for mode in modes:
        candidate_key = (mode["port"], mode["starttls"], mode["use_ssl"])
        if candidate_key == current:
            continue
        retry_cfg = dict(cfg)
        retry_cfg["port"] = mode["port"]
        retry_cfg["starttls"] = mode["starttls"]
        retry_cfg["use_ssl"] = mode["use_ssl"]
        retry_cfg["retry_label"] = mode["label"]
        out.append(retry_cfg)
    return out


def _should_retry_brevo_587(cfg: dict, exc: BaseException) -> bool:
    """Backward-compatible helper kept for older tests/callers."""
    return any(int(c.get("port") or 0) == 587 for c in _brevo_retry_candidates(cfg, exc))


def send_email(settings: dict, *, to_email: str, subject: str, body_text: str, body_html: str | None = None) -> tuple[bool, str]:
    """Send an email.

    Returns (ok, info). If SMTP is not configured, returns
    (False, "not_configured"). The body is never written to logs because reset
    emails contain secrets.
    """

    try:
        to_header = _safe_mailbox(to_email)
        subject_header = _safe_header(subject, "subject")
    except ValueError as exc:
        return False, str(exc)

    cfg = _smtp_settings(settings or {})

    # Free relay providers almost always require SMTP auth. Keep this strict so
    # password reset cannot pretend to send through an incomplete config.
    if not cfg["enabled"] or not cfg["host"] or not cfg["username"] or not cfg["password"]:
        logging.error(
            "SMTP not configured/enabled; cannot send email (to=%s subject=%s)",
            to_header,
            subject_header,
        )
        return False, "not_configured"

    try:
        from_header = _safe_mailbox(cfg["from_email"], default_display=str(cfg.get("server_display_name") or DEFAULT_SERVER_NAME))
    except ValueError as exc:
        logging.error("SMTP From address is invalid: %s", exc)
        return False, str(exc)

    from_warning = cfg.get("from_warning")
    if from_warning in {"invalid_from_localhost", "invalid_from_placeholder", "from_placeholder_not_deliverable"}:
        logging.error(
            "SMTP From address is not deliverable for %s: %s warning=%s",
            cfg.get("provider") or "provider",
            cfg.get("from_email") or "",
            from_warning,
        )
        return False, "invalid_from_placeholder"

    msg = EmailMessage()
    msg["From"] = from_header
    msg["To"] = to_header
    msg["Subject"] = subject_header
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=_addr_part(from_header).split("@", 1)[-1] or None)
    msg.set_content(str(body_text or ""))
    if body_html:
        msg.add_alternative(str(body_html), subtype="html")

    try:
        if cfg.get("mode_hint"):
            logging.info("SMTP configuration hint: %s", cfg["mode_hint"])
        _send_with_config(cfg, msg)
        return True, "sent"
    except Exception as exc:
        for retry_cfg in _brevo_retry_candidates(cfg, exc):
            try:
                logging.warning(
                    "SMTP send to Brevo failed on %s:%s at stage=%s (%s); retrying on %s:%s ssl=%s starttls=%s",
                    cfg["host"],
                    cfg["port"],
                    _smtp_stage(exc) or "unknown",
                    type(exc).__name__,
                    retry_cfg["host"],
                    retry_cfg["port"],
                    retry_cfg["use_ssl"],
                    retry_cfg["starttls"],
                )
                _send_with_config(retry_cfg, msg)
                return True, f"sent_via_brevo_{retry_cfg.get('retry_label')}_fallback"
            except Exception as retry_exc:
                exc = retry_exc
                cfg = retry_cfg

        # Do not log body_text/body_html. They may contain a reset token.
        logging.warning(
            "SMTP send failed (%s:%s ssl=%s starttls=%s timeout=%ss stage=%s) to=%s subject=%s: %s",
            cfg["host"],
            cfg["port"],
            cfg["use_ssl"],
            cfg["starttls"],
            cfg["timeout"],
            _smtp_stage(exc) or "unknown",
            to_header,
            subject_header,
            exc,
        )
        return False, f"smtp_error:{type(exc).__name__}"
