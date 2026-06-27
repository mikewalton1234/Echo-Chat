#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ ! -f "wsgi.py" ]]; then
  echo "Chat server wsgi.py not found in: $ROOT_DIR" >&2
  exit 1
fi

if [[ -z "${VIRTUAL_ENV:-}" && -x "$ROOT_DIR/.venv/bin/python" ]]; then
  # shellcheck disable=SC1091
  source "$ROOT_DIR/.venv/bin/activate"
fi

if ! command -v gunicorn >/dev/null 2>&1; then
  echo "gunicorn is not installed in the active environment." >&2
  echo "Install dependencies first: python -m pip install -r requirements.txt" >&2
  exit 1
fi

export ECHOCHAT_CONFIG="${ECHOCHAT_CONFIG:-$ROOT_DIR/server_config.json}"
export ECHOCHAT_SOCKETIO_ASYNC="${ECHOCHAT_SOCKETIO_ASYNC:-threading}"
export ECHOCHAT_BIND="${ECHOCHAT_BIND:-0.0.0.0:5000}"
export ECHOCHAT_RUN_MODE="${ECHOCHAT_RUN_MODE:-production}"
export ECHOCHAT_WORKERS="${ECHOCHAT_WORKERS:-1}"
export ECHOCHAT_GUNICORN_WORKER_CLASS="${ECHOCHAT_GUNICORN_WORKER_CLASS:-gthread}"
export ECHOCHAT_GUNICORN_THREADS="${ECHOCHAT_GUNICORN_THREADS:-100}"
export ECHOCHAT_GUNICORN_LOGLEVEL="${ECHOCHAT_GUNICORN_LOGLEVEL:-info}"

if ! python - <<'PY' >/dev/null 2>&1
from gunicorn.util import load_class
import simple_websocket
load_class('gthread')
PY
then
  echo "Default Gunicorn gthread/simple-websocket production runtime is not available in this environment." >&2
  echo "Fix: python -m pip install -r requirements.txt" >&2
  echo "Or run: scripts/install_production_deps.sh" >&2
  exit 2
fi

if [[ "$ECHOCHAT_GUNICORN_WORKER_CLASS" == "eventlet" ]]; then
  if ! python - <<'PY' >/dev/null 2>&1
from gunicorn.util import load_class
import eventlet
load_class('eventlet')
PY
  then
    echo "eventlet was selected, but the eventlet/Gunicorn worker is not available." >&2
    echo "Fix: python -m pip install -r requirements-eventlet.txt" >&2
    echo "Or leave ECHOCHAT_GUNICORN_WORKER_CLASS unset to use the default gthread worker." >&2
    exit 2
  fi
fi

SERVER_NAME="$(python -c 'import json, os; p=os.environ.get("ECHOCHAT_CONFIG") or "server_config.json";
try:
 data=json.load(open(p, "r", encoding="utf-8")); print((str(data.get("server_name") or "Echo-Chat").strip() or "Echo-Chat"))
except Exception:
 print("Echo-Chat")' 2>/dev/null || printf 'Echo-Chat')"

cat <<MSG
Starting $SERVER_NAME in production mode with Gunicorn.
  config:  $ECHOCHAT_CONFIG
  bind:    $ECHOCHAT_BIND
  workers: $ECHOCHAT_WORKERS
  async:   $ECHOCHAT_SOCKETIO_ASYNC
  worker:  $ECHOCHAT_GUNICORN_WORKER_CLASS
  threads: $ECHOCHAT_GUNICORN_THREADS

Notes:
- The default production path is gthread/threading for compatibility.
- For more than 1 worker, use separate single-worker instances behind a sticky load balancer and Redis.
- Run janitor_runner.py separately when using multiple instances.
MSG

exec gunicorn -c "$ROOT_DIR/gunicorn_conf.py" wsgi:app
