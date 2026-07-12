#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ ! -f "main.py" ]]; then
  echo "Hui Chat main.py not found in: $ROOT_DIR" >&2
  exit 1
fi

if [[ -z "${VIRTUAL_ENV:-}" && -x "$ROOT_DIR/.venv/bin/activate" ]]; then
  # shellcheck disable=SC1091
  source "$ROOT_DIR/.venv/bin/activate"
fi

# Match python main.py behavior for admins who use this helper directly.
if [[ -f "$ROOT_DIR/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT_DIR/.env"
  set +a
fi

export HUI_CONFIG="${HUI_CONFIG:-$ROOT_DIR/server_config.json}"
export HUI_RUN_MODE="${HUI_RUN_MODE:-production}"
export HUI_PRODUCTION_MODE="${HUI_PRODUCTION_MODE:-1}"
export HUI_WORKERS="${HUI_WORKERS:-1}"
export HUI_PRODUCTION_WORKERS="${HUI_PRODUCTION_WORKERS:-$HUI_WORKERS}"
export HUI_SOCKETIO_ASYNC="${HUI_SOCKETIO_ASYNC:-threading}"
export HUI_GUNICORN_WORKER_CLASS="${HUI_GUNICORN_WORKER_CLASS:-gthread}"
export HUI_FORWARDED_ALLOW_IPS="${HUI_FORWARDED_ALLOW_IPS:-127.0.0.1}"

exec python main.py --production
