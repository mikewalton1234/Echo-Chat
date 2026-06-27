"""Plain-English hosting guidance for Echo-Chat admins.

This module is intentionally dependency-free so it can run before the database,
Flask, PostgreSQL, Redis, or production dependencies are installed.
"""

from __future__ import annotations

from typing import Any


def format_hosting_help(settings: dict[str, Any] | None = None) -> str:
    settings = settings or {}
    public_url = str(settings.get("public_base_url") or "").strip().rstrip("/")
    mode = str(settings.get("hosting_mode") or "lan").strip().lower().replace("-", "_").replace(" ", "_")
    if mode in {"no_domain", "pending_domain", "domain_needed", "domain_later"}:
        mode = "no_domain_yet"

    lines = [
        "Echo-Chat Hosting Help",
        "",
        f"Current hosting mode: {mode}",
        f"Current public URL: {public_url or '(not set)'}",
        "",
        "Pick one path:",
        "",
        "1. LAN/home testing - easiest right now",
        "   Use this while you do not have a domain or HTTPS hostname.",
        "   Open Echo-Chat from phones/computers on your Wi-Fi using http://SERVER-LAN-IP:5000.",
        "   Settings: hosting_mode=lan, https=false, cookie_secure=false, auto_allow_lan_origins=true.",
        "",
        "2. No domain yet - safe waiting room",
        "   Use hosting_mode=no_domain_yet when you want internet hosting later but do not have a real HTTPS address yet.",
        "   This keeps LAN-safe settings and blocks fake public-beta assumptions.",
        "   Do not invite internet testers yet, and do not port-forward Echo-Chat's raw app port as a substitute for HTTPS.",
        "   Next: buy a domain, use Dynamic DNS with HTTPS, or use a trusted tunnel service that gives you an HTTPS hostname.",
        "",
        "3. HTTPS tunnel hostname",
        "   A tunnel hostname can be used like a public beta URL only if it is stable HTTPS and is the exact URL testers open.",
        "   Set hosting_mode=public_beta and public_base_url to that HTTPS tunnel URL, then run --public-beta-check.",
        "",
        "4. Public beta with a real domain",
        "   Use when you own a domain/subdomain such as https://chat.yourdomain.com.",
        "   DNS or Dynamic DNS must point to your public server IP, ports 80/443 must reach Caddy/Nginx,",
        "   and Echo-Chat should stay behind the proxy on 127.0.0.1:5000.",
        "",
        "5. Advanced/custom",
        "   Use only if you already understand reverse proxies, tunnels, load balancers, and TLS.",
        "",
        "Safe commands:",
        "   python main.py --setup",
        "   python main.py --hosting-help",
        "   python main.py --generate-proxy-config all",
        "   python main.py --public-beta-check",
        "",
        "Important: chat.example.com, example.com, and YOUR-REAL-DOMAIN are placeholders.",
        "They are never real public beta addresses for your server.",
    ]
    return "\n".join(lines).rstrip() + "\n"
