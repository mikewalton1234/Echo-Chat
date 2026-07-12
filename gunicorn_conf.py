"""gunicorn_conf.py

Default Gunicorn config for Hui Chat + Flask-SocketIO.

The default production path uses Gunicorn gthread + Flask-SocketIO threading
mode. Keep Gunicorn at one worker per Hui Chat instance; scale with multiple
one-worker instances behind sticky reverse-proxy routing and a Redis Socket.IO
message queue.

Environment variables:
  HUI_BIND=127.0.0.1:5000
  HUI_WORKERS=1
  HUI_GUNICORN_LOGLEVEL=info
  HUI_GUNICORN_ACCESSLOG=-
  HUI_GUNICORN_ERRORLOG=-
  HUI_GUNICORN_TIMEOUT=60
  HUI_GUNICORN_WORKER_CLASS=gthread
  HUI_FORWARDED_ALLOW_IPS=127.0.0.1

Recommended Redis split for scaled deployments:
  HUI_RATE_LIMIT_STORAGE_URI=redis://127.0.0.1:6379/0
  HUI_SOCKETIO_MESSAGE_QUEUE=redis://127.0.0.1:6379/1
  HUI_SHARED_STATE_REDIS_URL=redis://127.0.0.1:6379/2
"""

from __future__ import annotations

from env_loader import load_project_dotenv

load_project_dotenv()

import os


def _env_int(name: str, default: int, *, minimum: int | None = None, maximum: int | None = None) -> int:
    raw = os.environ.get(name, str(default))
    try:
        value = int(str(raw).strip())
    except Exception:
        value = int(default)
    if minimum is not None and value < minimum:
        value = int(minimum)
    if maximum is not None and value > maximum:
        value = int(maximum)
    return value


bind = os.environ.get("HUI_BIND", "127.0.0.1:5000")
workers = _env_int("HUI_WORKERS", 1, minimum=1)
threads = _env_int("HUI_GUNICORN_THREADS", 100, minimum=1)
worker_class = os.environ.get("HUI_GUNICORN_WORKER_CLASS", "gthread").strip() or "gthread"

# Make the effective worker count visible to app startup code.
raw_env = [f"WEB_CONCURRENCY={workers}"]

# WebSockets/polling keep connections open; avoid overly low timeouts.
timeout = _env_int("HUI_GUNICORN_TIMEOUT", 60, minimum=1)
keepalive = _env_int("HUI_GUNICORN_KEEPALIVE", 5, minimum=1)
worker_connections = _env_int("HUI_GUNICORN_WORKER_CONNECTIONS", 1000, minimum=1)

loglevel = os.environ.get("HUI_GUNICORN_LOGLEVEL", "info")
accesslog = os.environ.get("HUI_GUNICORN_ACCESSLOG", "-")
errorlog = os.environ.get("HUI_GUNICORN_ERRORLOG", "-")

# Trust forwarded headers only from the local reverse proxy by default.
# Do not use '*' unless Gunicorn is completely unreachable by untrusted clients.
forwarded_allow_ips = os.environ.get("HUI_FORWARDED_ALLOW_IPS", "127.0.0.1")
