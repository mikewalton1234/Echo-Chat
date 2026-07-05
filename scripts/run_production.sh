#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ ! -f "main.py" ]]; then
  echo "Echo-Chat main.py not found in: $ROOT_DIR" >&2
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

export ECHOCHAT_CONFIG="${ECHOCHAT_CONFIG:-$ROOT_DIR/server_config.json}"
export ECHOCHAT_RUN_MODE="${ECHOCHAT_RUN_MODE:-production}"
export ECHOCHAT_PRODUCTION_MODE="${ECHOCHAT_PRODUCTION_MODE:-1}"
export ECHOCHAT_WORKERS="${ECHOCHAT_WORKERS:-1}"
export ECHOCHAT_PRODUCTION_WORKERS="${ECHOCHAT_PRODUCTION_WORKERS:-$ECHOCHAT_WORKERS}"
export ECHOCHAT_SOCKETIO_ASYNC="${ECHOCHAT_SOCKETIO_ASYNC:-threading}"
export ECHOCHAT_GUNICORN_WORKER_CLASS="${ECHOCHAT_GUNICORN_WORKER_CLASS:-gthread}"
export ECHOCHAT_FORWARDED_ALLOW_IPS="${ECHOCHAT_FORWARDED_ALLOW_IPS:-127.0.0.1}"

exec python main.py --production
