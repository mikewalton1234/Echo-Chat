#!/usr/bin/env python3
"""Static checks for the neutral image emoticon catalog and GUI wiring."""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def main() -> int:
    failures: list[str] = []
    catalog_py = _read("emoticon_catalog.py")
    routes_main = _read("routes_main.py")
    picker_js = _read("static/js/chat_parts/0008_emoji_picker.js")
    render_js = _read("static/js/chat_parts/0020_chat_log_rendering.js")
    css = _read("static/css/chat.css")

    tree = ast.parse(catalog_py)
    builtin_node = None
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "BUILTIN_EMOTICONS":
                    builtin_node = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id == "BUILTIN_EMOTICONS":
                builtin_node = node.value
    try:
        builtins = ast.literal_eval(builtin_node) if builtin_node is not None else []
    except Exception:
        builtins = []
    total_entries = len(builtins)
    total_codes = 0
    local_files: set[str] = set()
    for row in builtins:
        if not isinstance(row, tuple) or len(row) < 6:
            failures.append("built-in rows must include name/label/local/external/codes/category")
            continue
        codes = row[4]
        total_codes += len(codes) if isinstance(codes, tuple) else 0
        if isinstance(row[2], str):
            local_files.add(row[2])
    if total_entries < 120:
        failures.append(f"expected full image emoticon catalog, found only {total_entries}")
    if total_codes < 180:
        failures.append(f"expected shortcut aliases for image emoticons, found only {total_codes}")
    if "1.gif" not in local_files or "113.gif" not in local_files:
        failures.append("catalog must map local numeric image files such as 1.gif and 113.gif")
    if ":)" not in catalog_py or ":))" not in catalog_py or ":-bd" not in catalog_py:
        failures.append("catalog missing common typed shortcuts")
    for asset in ["1.gif", "2.gif", "21.gif", "113.gif"]:
        if not (ROOT / "emoticons" / asset).is_file():
            failures.append(f"bundled local emoticon asset missing: emoticons/{asset}")
        if not (ROOT / "static" / "emoticons" / asset).is_file():
            failures.append(f"static fallback emoticon asset missing: static/emoticons/{asset}")
    for token in ["local_emoticon_root", "local_emoticon_roots", "_normalize_external_bases", "emoticons_custom_entries", "emoticons_external_asset_base_url", "emoticons_asset_mode", "emoticons_animation_stop_ms", "animation_stop_ms", "_DEFAULT_EXTERNAL_ASSET_BASE_URL", "fallback_srcs", "_external_asset_candidates_for_row", "static_candidates"]:
        if token not in catalog_py:
            failures.append(f"catalog missing {token}")
    for token in ['@app.get("/api/emoticons/catalog")', '@app.get("/api/emoticons/selftest")', '@app.get("/emoticons/<path:filename>")', 'for root in local_emoticon_roots(settings)', '_safe_emoticon_file_path(root, safe_name)']:
        if token not in routes_main:
            failures.append(f"routes_main missing {token}")
    catalog_route_slice = routes_main[routes_main.find('@app.get("/api/emoticons/catalog")'):routes_main.find('@app.get("/api/emoticons/selftest")')]
    if '@jwt_required' in catalog_route_slice:
        failures.append("catalog route should not depend on JWT timing; chat shell already requires auth")
    for token in ["ensureCodeEmoticonsLoaded", "ecAppendCodeEmoticons", "renderCodeEmoticonGrid", "/api/emoticons/catalog", "fallbackSrcs", "ecAttachImageFallback", "ecSetEmoticonImageSource", "ecFreezeAnimatedEmoticon", "ecScheduleEmoticonFreeze", "toDataURL", "drawImage", "codes", "ec-emoticonPendingText", "Loading emoticons", "is-loaded-image", "referrerPolicy", "ecEnsureRichComposer", "ec-richComposer", "ec-richEmoticonToken", "insertTextOrEmoticon", "ecRichComposerValueFromEditor"]:
        if token not in picker_js:
            failures.append(f"picker missing {token}")
    if "document.createElement(\"emoji-picker\")" in picker_js or "emoji-click" in picker_js:
        failures.append("old Unicode picker must not be mounted in the emoticon popover")
    if (ROOT / "static/vendor/emoji-picker-element").exists() or (ROOT / "static/vendor/emoji-picker-element-data").exists():
        failures.append("old Unicode picker vendor bundle should be removed from the server package")
    if "code.textContent = entry.code" in picker_js:
        failures.append("picker must not display shortcut text as visible labels")
    if "ecAppendChatTextSegment" not in render_js or "ecAppendCodeEmoticons" not in render_js:
        failures.append("message renderer must replace typed shortcuts in non-link text segments")
    for token in ["ec-codeEmoticonPanel", "ec-inlineEmoticon", "ec-codeEmoticonCode", "is-frozen-emoticon", "ec-richComposer", "ec-richComposerHiddenInput", "ec-richEmoticonImg"]:
        if token not in css:
            failures.append(f"CSS missing {token}")

    if failures:
        print("❌ Emoticon catalog doctor failed")
        for failure in failures:
            print(f" - {failure}")
        return 1
    print("✅ Emoticon catalog doctor passed")
    print(f"   image entries checked: {total_entries}")
    print(f"   shortcut aliases checked: {total_codes}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
