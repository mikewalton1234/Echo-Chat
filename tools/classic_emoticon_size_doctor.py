#!/usr/bin/env python3
"""Static doctor for beta.354 classic emoticon size preferences."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def fail(msg: str) -> None:
    print(f"❌ {msg}")
    raise SystemExit(1)


def main() -> int:
    html = read("templates/chat.html")
    css = read("static/css/chat.css")
    state_js = read("static/js/chat_parts/0002_state_storage.js")
    picker_js = read("static/js/chat_parts/0008_emoji_picker.js")
    settings_js = read("static/js/chat_parts/0047_settings_modal.js")
    boot_js = read("static/js/chat_parts/0048_boot_presence_dom.js")

    for token in ["setEmoticonSize", "setEmoticonSizeVal", "Emoticon size"]:
        if token not in html:
            fail(f"settings UI missing {token}")
    range_match = re.search(r'id="setEmoticonSize"[^>]+min="22"[^>]+max="56"[^>]+step="2"', html)
    if not range_match:
        fail("emoticon size range must be clamped from 22 to 56 in 2px steps")

    for token in [
        "emoticonSize: Settings.get(\"emoticonSize\", 26)",
    ]:
        if token not in state_js:
            fail(f"state defaults missing {token}")

    for token in [
        "--ec-emoticon-inline-size",
        "--ec-emoticon-picker-size",
        "--ec-emoticon-token-size",
        "var(--ec-emoticon-inline-size, 26px)",
        "max-width: calc(var(--ec-emoticon-inline-size, 26px) * 3)",
        "width: auto;",
        "var(--ec-emoticon-picker-size, 34px)",
        "var(--ec-emoticon-token-size, 30px)",
    ]:
        if token not in css:
            fail(f"CSS variable/style missing {token}")

    for token in [
        "function ecClampEmoticonSize",
        "function ecApplyEmoticonSizePrefs",
        "window.ecApplyEmoticonSizePrefs",
        "setEmoticonSizeVal",
    ]:
        if token not in picker_js:
            fail(f"emoticon sizing JS missing {token}")

    for token in [
        "emoticonSize: 26",
        "'emoticonSize'",
        "ecApplyEmoticonSizePrefs(emoSize)",
        "Settings.set(\"emoticonSize\"",
        "prevEmoticonSize",
    ]:
        if token not in settings_js:
            fail(f"settings persistence/preview missing {token}")

    for token in [
        "ecApplyEmoticonSizePrefs(UIState.prefs.emoticonSize)",
        "setEmoticonSize",
    ]:
        if token not in boot_js:
            fail(f"boot/live preview missing {token}")

    print("✅ Classic emoticon size doctor passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
