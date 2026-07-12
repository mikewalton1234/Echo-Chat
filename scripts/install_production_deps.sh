#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ -z "${VIRTUAL_ENV:-}" && -x "$ROOT_DIR/.venv/bin/activate" ]]; then
  # shellcheck disable=SC1091
  source "$ROOT_DIR/.venv/bin/activate"
fi

PYTHON_BIN="${PYTHON:-python}"

echo "Installing Hui Chat production dependencies into: $("$PYTHON_BIN" -c 'import sys; print(sys.executable)')"
"$PYTHON_BIN" -m pip install --upgrade pip
"$PYTHON_BIN" -m pip install -r requirements.txt

echo
echo "Production dependency check:"
"$PYTHON_BIN" - <<'PY'
from gunicorn.util import load_class
import simple_websocket
load_class('gthread')
print('OK: gunicorn gthread + simple-websocket production runtime is available')
PY

echo
cat <<'MSG'
Default production mode now uses:
  HUI_SOCKETIO_ASYNC=threading
  HUI_GUNICORN_WORKER_CLASS=gthread
  HUI_GUNICORN_THREADS=100

Optional Eventlet mode is still possible for advanced installs:
  python -m pip install -r requirements-eventlet.txt
  HUI_SOCKETIO_ASYNC=eventlet HUI_GUNICORN_WORKER_CLASS=eventlet python main.py --production
MSG
