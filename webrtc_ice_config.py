"""WebRTC ICE server configuration helpers for Echo-Chat.

The browser WebRTC path needs ICE servers for P2P file transfers, voice, and
webcam.  STUN can discover peer-reflexive/public candidates; TURN relays media
or data when direct/STUN connectivity fails behind restrictive NATs/firewalls.
"""

from __future__ import annotations

import json
import os
from typing import Any, Mapping

DEFAULT_ICE_SERVERS: list[dict[str, Any]] = [
    {"urls": "stun:stun.l.google.com:19302"},
    {"urls": "stun:stun1.l.google.com:19302"},
]

_ALLOWED_ICE_SCHEMES = ("stun:", "stuns:", "turn:", "turns:")
_STANDARD_ICE_KEYS = {"urls", "username", "credential", "credentialType"}
_P2P_ICE_ENV_NAMES = ("ECHOCHAT_P2P_ICE_SERVERS_JSON", "ECHOCHAT_WEBRTC_ICE_SERVERS_JSON", "WEBRTC_ICE_SERVERS_JSON")
_VOICE_ICE_ENV_NAMES = ("ECHOCHAT_VOICE_ICE_SERVERS_JSON", "ECHOCHAT_WEBCAM_ICE_SERVERS_JSON")
_TURN_URL_ENV_NAMES = ("ECHOCHAT_TURN_URLS", "TURN_URLS")
_TURN_USERNAME_ENV_NAMES = ("ECHOCHAT_TURN_USERNAME", "TURN_USERNAME")
_TURN_CREDENTIAL_ENV_NAMES = ("ECHOCHAT_TURN_CREDENTIAL", "ECHOCHAT_TURN_PASSWORD", "TURN_CREDENTIAL", "TURN_PASSWORD")


def _env_str(*names: str) -> str:
    for name in names:
        value = os.getenv(name)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _is_valid_ice_url(value: Any) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    # Browser RTCIceServer URLs are not full HTTP URLs, but they still need a
    # usable scheme + target. Reject whitespace/control characters and bare
    # values like "turn:" so setup/admin cannot report unusable ICE as valid.
    if any(ord(ch) < 32 or ch.isspace() for ch in text):
        return False
    low = text.lower()
    for prefix in _ALLOWED_ICE_SCHEMES:
        if low.startswith(prefix):
            return bool(text[len(prefix) :].strip())
    return False


def _normalize_urls(value: Any) -> list[str]:
    if isinstance(value, (list, tuple)):
        urls = [str(v or "").strip() for v in value]
    else:
        urls = [str(value or "").strip()]
    out: list[str] = []
    seen: set[str] = set()
    for url in urls:
        if not _is_valid_ice_url(url):
            continue
        if url in seen:
            continue
        seen.add(url)
        out.append(url)
    return out


def normalize_ice_servers(value: Any, *, allow_credentials: bool = True) -> list[dict[str, Any]]:
    """Normalize strings/lists/dicts into browser-safe RTCIceServer objects.

    Accepted input forms:
    - comma-separated URL string
    - JSON string containing one RTCIceServer object or a list
    - list of URLs and/or RTCIceServer dicts
    - single RTCIceServer dict
    """
    if value is None or value == "":
        return []

    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return []
        if raw.startswith("[") or raw.startswith("{"):
            try:
                parsed = json.loads(raw)
            except Exception:
                parsed = None
            if parsed is not None:
                return normalize_ice_servers(parsed, allow_credentials=allow_credentials)
        value = [part.strip() for part in raw.split(",") if part.strip()]

    if isinstance(value, Mapping):
        items = [value]
    elif isinstance(value, (list, tuple)):
        items = list(value)
    else:
        return []

    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        obj: dict[str, Any]
        if isinstance(item, str):
            urls = _normalize_urls(item)
            obj = {"urls": urls[0]} if len(urls) == 1 else ({"urls": urls} if urls else {})
        elif isinstance(item, Mapping):
            urls = _normalize_urls(item.get("urls"))
            obj = {"urls": urls[0]} if len(urls) == 1 else ({"urls": urls} if urls else {})
            if obj and allow_credentials:
                for key in ("username", "credential", "credentialType"):
                    raw_val = item.get(key)
                    if raw_val is not None and str(raw_val).strip() != "":
                        obj[key] = str(raw_val).strip()
        else:
            obj = {}

        if not obj:
            continue
        dedupe_key = json.dumps(obj, sort_keys=True, ensure_ascii=False)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        # Never pass non-standard/custom keys through to RTCPeerConnection.
        out.append({k: v for k, v in obj.items() if k in _STANDARD_ICE_KEYS})
    return out


def parse_ice_servers_text(raw: Any) -> list[dict[str, Any]]:
    return normalize_ice_servers(raw, allow_credentials=True)


def _configured_p2p_ice_servers(settings: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    settings = settings or {}
    return normalize_ice_servers(
        settings.get("p2p_ice_servers")
        or settings.get("p2p_ice")
        or settings.get("webrtc_ice_servers")
        or settings.get("ice_servers")
    )


def _configured_voice_ice_servers(settings: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    settings = settings or {}
    return normalize_ice_servers(settings.get("voice_ice_servers"))


def _iter_urls(servers: list[dict[str, Any]]):
    for server in servers:
        urls = server.get("urls")
        if isinstance(urls, str):
            yield urls
        elif isinstance(urls, (list, tuple)):
            for url in urls:
                yield str(url or "")


def ice_servers_have_turn(servers: list[dict[str, Any]]) -> bool:
    return any(str(url).strip().lower().startswith(("turn:", "turns:")) for url in _iter_urls(servers))


def ice_servers_have_stun(servers: list[dict[str, Any]]) -> bool:
    return any(str(url).strip().lower().startswith(("stun:", "stuns:")) for url in _iter_urls(servers))


def _turn_env_credentials() -> tuple[str, str]:
    return _env_str(*_TURN_USERNAME_ENV_NAMES), _env_str(*_TURN_CREDENTIAL_ENV_NAMES)


def _apply_env_turn_credentials(servers: Any) -> list[dict[str, Any]]:
    normalized = normalize_ice_servers(servers)
    username, credential = _turn_env_credentials()
    if username or credential:
        return apply_turn_credentials(normalized, username=username, credential=credential, keep_existing=True)
    return normalized


def _env_turn_servers() -> list[dict[str, Any]]:
    raw = _env_str(*_TURN_URL_ENV_NAMES)
    if not raw:
        return []
    return _apply_env_turn_credentials(normalize_ice_servers(raw))


def env_ice_servers(*names: str) -> list[dict[str, Any]]:
    for name in names:
        raw = os.getenv(name)
        if raw and raw.strip():
            parsed = normalize_ice_servers(raw)
            if parsed:
                return _apply_env_turn_credentials(parsed)
    return []


def effective_ice_settings(settings: Mapping[str, Any] | None) -> dict[str, Any]:
    """Return runtime-effective ICE settings, honoring env secrets.

    Specific JSON/list environment variables win first. The simpler
    ECHOCHAT_TURN_URLS form is used for both P2P and voice/webcam unless a more
    specific env value is present. If setup saved TURN URLs but intentionally
    left credentials out of JSON, ECHOCHAT_TURN_USERNAME and
    ECHOCHAT_TURN_CREDENTIAL/PASSWORD are applied to those saved TURN entries.
    """

    settings = settings or {}
    turn_servers = _env_turn_servers()

    p2p_env = env_ice_servers(*_P2P_ICE_ENV_NAMES)
    if p2p_env:
        p2p = p2p_env
    elif turn_servers:
        p2p = turn_servers
    else:
        p2p = _apply_env_turn_credentials(_configured_p2p_ice_servers(settings)) or [dict(s) for s in DEFAULT_ICE_SERVERS]

    voice_env = env_ice_servers(*_VOICE_ICE_ENV_NAMES)
    if voice_env:
        voice = voice_env
    elif turn_servers:
        voice = turn_servers
    else:
        voice_configured = _configured_voice_ice_servers(settings)
        voice = _apply_env_turn_credentials(voice_configured) if voice_configured else [dict(s) for s in p2p]

    return {
        "p2p_ice_servers": p2p,
        "voice_ice_servers": voice,
        "summary": ice_server_summary_for_lists(p2p, voice),
    }


def p2p_ice_servers(settings: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    return list(effective_ice_settings(settings).get("p2p_ice_servers") or [])


def voice_ice_servers(settings: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    return list(effective_ice_settings(settings).get("voice_ice_servers") or [])


def redact_ice_servers(servers: Any) -> list[dict[str, Any]]:
    redacted: list[dict[str, Any]] = []
    for server in normalize_ice_servers(servers):
        item = dict(server)
        if "credential" in item:
            item["credential"] = "********"
        redacted.append(item)
    return redacted


def ice_servers_to_text(servers: Any, *, redact: bool = False) -> str:
    data = redact_ice_servers(servers) if redact else normalize_ice_servers(servers)
    if not data:
        return ""
    # JSON preserves username/credential fields better than a comma-separated URL list.
    return json.dumps(data, indent=2, ensure_ascii=False)


def first_turn_username(servers: Any) -> str:
    for server in normalize_ice_servers(servers):
        if ice_servers_have_turn([server]):
            val = str(server.get("username") or "").strip()
            if val:
                return val
    return ""


def apply_turn_credentials(
    servers: Any,
    username: str | None = None,
    credential: str | None = None,
    *,
    keep_existing: bool = True,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    username = str(username or "").strip()
    credential = str(credential or "").strip()
    for server in normalize_ice_servers(servers):
        item = dict(server)
        if ice_servers_have_turn([item]):
            if username:
                item["username"] = username
            elif not keep_existing:
                item.pop("username", None)
            if credential:
                item["credential"] = credential
                item.setdefault("credentialType", "password")
            elif not keep_existing:
                item.pop("credential", None)
        out.append(item)
    return out


def ice_server_summary_for_lists(p2p: list[dict[str, Any]], voice: list[dict[str, Any]]) -> dict[str, Any]:
    p2p_turn = ice_servers_have_turn(p2p)
    voice_turn = ice_servers_have_turn(voice)
    return {
        "p2p_count": len(p2p),
        "voice_count": len(voice),
        "p2p_has_stun": ice_servers_have_stun(p2p),
        "p2p_has_turn": p2p_turn,
        "voice_has_stun": ice_servers_have_stun(voice),
        "voice_has_turn": voice_turn,
        "turn_configured": p2p_turn or voice_turn,
        "stun_configured": ice_servers_have_stun(p2p) or ice_servers_have_stun(voice),
        "internet_ready": p2p_turn and voice_turn,
        "recommendation": "TURN relay configured" if p2p_turn and voice_turn else "Add a TURN relay for reliable internet/cellular/corporate-network webcam tests",
    }


def ice_server_summary(settings: Mapping[str, Any] | None) -> dict[str, Any]:
    return dict(effective_ice_settings(settings).get("summary") or {})


def turn_credential_errors(settings: Mapping[str, Any] | None) -> list[str]:
    """Return setup/admin validation errors for incomplete TURN entries."""

    errors: list[str] = []
    effective = effective_ice_settings(settings)
    for label, servers in (
        ("P2P/WebRTC", effective.get("p2p_ice_servers") or []),
        ("Voice/webcam", effective.get("voice_ice_servers") or []),
    ):
        for server in normalize_ice_servers(servers):
            if not ice_servers_have_turn([server]):
                continue
            if not str(server.get("username") or "").strip() or not str(server.get("credential") or "").strip():
                errors.append(
                    f"{label} TURN server {server.get('urls')} is missing username or credential. "
                    "Store them in the ICE JSON or set ECHOCHAT_TURN_USERNAME and ECHOCHAT_TURN_CREDENTIAL/TURN_PASSWORD."
                )
    # Avoid duplicate messages when voice falls back to the same P2P list.
    unique: list[str] = []
    seen: set[str] = set()
    for msg in errors:
        if msg not in seen:
            unique.append(msg)
            seen.add(msg)
    return unique
