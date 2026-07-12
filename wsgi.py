"""wsgi.py

Gunicorn entrypoint for HuiChat.

Run (single instance example):
  HUI_SOCKETIO_ASYNC=threading \
  gunicorn -k gthread -w 1 --threads 100 -b 127.0.0.1:5000 wsgi:app

Scale-out example:
  Start separate one-worker instances on ports 5000-5009 behind sticky Caddy/Nginx routing,
  with HUI_SOCKETIO_MESSAGE_QUEUE=redis://127.0.0.1:6379/1.

Notes:
- Keep Gunicorn at -w 1 per Hui Chat instance; do not run Gunicorn with multiple workers for Socket.IO.
- Do NOT start the janitor loop inside Gunicorn workers; run janitor_runner.py
  as a separate systemd service.
"""

from __future__ import annotations

from env_loader import load_project_dotenv

load_project_dotenv()

import os

# ---- Shared Socket.IO async bootstrap ----
from socketio_async_bootstrap import HUI_SOCKETIO_ASYNC

from pathlib import Path

from constants import CONFIG_FILE
from main import load_settings, apply_env_overrides
from server_init import create_app


def _resolve_config_path() -> Path:
    # Prefer explicit env path when running under systemd.
    p = (
        os.environ.get("HUI_CONFIG")
        or os.environ.get("HUI_CONFIG_FILE")
        or os.environ.get("HUI_SETTINGS")
        or CONFIG_FILE
    )
    return Path(p)


_settings_path = _resolve_config_path()
_settings = load_settings(_settings_path)
apply_env_overrides(_settings)

# Create the Flask app + Socket.IO integration.
app, socketio = create_app(_settings, limiter=None, settings_file=_settings_path)

# Expose these for tooling / introspection.
app.config["HUI_GUNICORN"] = True
app.config["HUI_SETTINGS_PATH"] = str(_settings_path)
