#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from constants import CHAT_PARTS_DIR, CHAT_SCRIPT_PARTS


def main() -> int:
    expected = {Path(p).name for p in CHAT_SCRIPT_PARTS}
    existing = {p.name for p in CHAT_PARTS_DIR.glob("*.js") if p.is_file()}
    stale = sorted(existing - expected)
    if not stale:
        print("No stale chat_parts files found.")
        return 0
    print("Removing stale chat_parts files:")
    for name in stale:
        target = CHAT_PARTS_DIR / name
        print(f" - {name}")
        target.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
