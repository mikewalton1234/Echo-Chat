#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
EMOJI_DIR="$ROOT_DIR/static/vendor/emoji-picker-element"
DATA_DIR="$ROOT_DIR/static/vendor/emoji-picker-element-data/en/emojibase"
mkdir -p "$EMOJI_DIR" "$DATA_DIR"
PICKER_URL="https://cdn.jsdelivr.net/npm/emoji-picker-element@1.29.1/picker.js"
DATABASE_URL="https://cdn.jsdelivr.net/npm/emoji-picker-element@1.29.1/database.js"
DATA_URL="https://cdn.jsdelivr.net/npm/emoji-picker-element-data@1.8.0/en/emojibase/data.json"
fetch() {
  local url="$1"
  local out="$2"
  if command -v curl >/dev/null 2>&1; then
    curl -fL "$url" -o "$out"
  elif command -v wget >/dev/null 2>&1; then
    wget -O "$out" "$url"
  else
    echo "Need curl or wget installed." >&2
    exit 1
  fi
}
fetch "$PICKER_URL" "$EMOJI_DIR/picker.js"
fetch "$DATABASE_URL" "$EMOJI_DIR/database.js"
fetch "$DATA_URL" "$DATA_DIR/data.json"
echo "Vendored emoji picker files downloaded successfully."
