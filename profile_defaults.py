#!/usr/bin/env python3
"""Profile default helpers shared by registration, setup, and admin-created accounts."""

from __future__ import annotations

import secrets
import urllib.parse

DICEBEAR_API_BASE = "https://api.dicebear.com/10.x"
DEFAULT_AVATAR_STYLES = (
    "avataaars",
    "personas",
    "lorelei",
    "adventurer",
    "pixel-art",
    "bottts",
    "fun-emoji",
    "thumbs",
    "initials",
    "identicon",
)
DEFAULT_AVATAR_BACKGROUNDS = (
    "dbeafe",
    "e0f2fe",
    "ede9fe",
    "dcfce7",
    "fef3c7",
    "ffe4e6",
)


def build_dicebear_avatar_url(
    username: str,
    *,
    style: str = "avataaars",
    seed: str | None = None,
    background_color: str = "dbeafe",
    border_radius: int = 50,
    flip: bool = False,
) -> str:
    """Return a DiceBear HTTP API SVG avatar URL."""
    clean_style = (style or "avataaars").strip().lower().replace("_", "-")
    if clean_style not in DEFAULT_AVATAR_STYLES:
        clean_style = "avataaars"
    uname = (username or "user").strip().lower() or "user"
    clean_seed = (seed or uname).strip()[:96] or uname
    clean_bg = (background_color or "dbeafe").strip().lower().lstrip("#")
    if len(clean_bg) != 6 or any(ch not in "0123456789abcdef" for ch in clean_bg):
        clean_bg = "dbeafe"
    try:
        radius = max(0, min(50, int(border_radius)))
    except Exception:
        radius = 50
    q = {
        "seed": clean_seed,
        "backgroundColor": clean_bg,
        "borderRadius": str(radius),
    }
    if flip:
        q["flip"] = "true"
    return f"{DICEBEAR_API_BASE}/{urllib.parse.quote(clean_style)}/svg?{urllib.parse.urlencode(q)}"


def build_default_avatar_url(username: str, *, randomize: bool = True) -> str:
    """Return a DiceBear avatar URL for a new account.

    New accounts get a stable URL stored in the database. DiceBear uses the seed
    to generate deterministic SVG avatars, so the saved URL keeps producing the
    same visual avatar for that user.
    """
    uname = (username or "user").strip().lower() or "user"
    if randomize:
        style = secrets.choice(DEFAULT_AVATAR_STYLES)
        bg = secrets.choice(DEFAULT_AVATAR_BACKGROUNDS)
        token = secrets.token_urlsafe(10)
        seed = f"new-{uname}-{token}"
    else:
        import hashlib

        digest = hashlib.sha256(uname.encode("utf-8", "ignore")).digest()
        style = DEFAULT_AVATAR_STYLES[digest[0] % len(DEFAULT_AVATAR_STYLES)]
        bg = DEFAULT_AVATAR_BACKGROUNDS[digest[1] % len(DEFAULT_AVATAR_BACKGROUNDS)]
        seed = f"default-{style}-{uname}-{digest[2]}"

    return build_dicebear_avatar_url(uname, style=style, seed=seed, background_color=bg, border_radius=50)
