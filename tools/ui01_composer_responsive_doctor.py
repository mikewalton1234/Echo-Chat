#!/usr/bin/env python3
"""Static UI01 checks for the classic room composer responsive layout."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def require(haystack: str, needle: str, label: str) -> None:
    if needle not in haystack:
        raise SystemExit(f"❌ UI01 composer responsive doctor failed: missing {label}: {needle!r}")


def main() -> int:
    chat_css = read("static/css/chat.css")
    mobile_css = read("static/css/mobile.css")
    mobile_js = read("static/js/chat_parts/0050_mobile_layout.js")
    template = read("templates/chat.html")

    require(chat_css, "Beta.355 UI01: responsive classic room composer sizing", "desktop responsive CSS marker")
    require(chat_css, "@media (max-width: 1100px)", "desktop wrap breakpoint")
    require(chat_css, "@media (max-width: 760px)", "small-browser compact breakpoint")
    require(chat_css, "@media (max-width: 520px)", "very-small-browser breakpoint")
    require(chat_css, "overflow-wrap: anywhere", "safe input wrapping")
    require(chat_css, "max-height: 62px", "narrow toolbar max-height guard")
    require(chat_css, ".ecClassicTextBtn .ecToolBtnLabel", "voice/webcam label hiding rule")

    require(mobile_css, "Beta.355 UI01: mobile classic composer", "mobile responsive CSS marker")
    require(mobile_css, "grid-template-columns: minmax(0, 1fr) auto auto", "mobile input/tools/send columns")
    require(mobile_css, "is-mobile-compose-tools-open", "mobile tools-open state")
    require(mobile_css, "max-height: 76px", "mobile open toolbar height guard")

    require(mobile_js, 'btn.textContent = "Tools"', "mobile Tools button label")
    require(mobile_js, "mobileComposerBound", "single mobile button binding guard")

    require(template, "ecToolBtnLabel", "voice/webcam text spans")
    require(template, 'id="btnRoomEmbedVoice"', "voice toolbar button")
    require(template, 'id="btnRoomEmbedCam"', "webcam toolbar button")
    require(template, 'id="roomEmbedTorrentBtn"', "torrent toolbar button")

    print("✅ UI01 composer responsive doctor passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
