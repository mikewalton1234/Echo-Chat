"""gunicorn_conf.py

Default Gunicorn config for Echo-Chat + Flask-SocketIO.

The default production path uses Gunicorn gthread + Flask-SocketIO threading
mode. Keep Gunicorn at one worker per Echo-Chat instance; scale with multiple
one-worker instances behind sticky reverse-proxy routing and a Redis Socket.IO
message queue.

Environment variables:
  ECHOCHAT_BIND=127.0.0.1:5000
  ECHOCHAT_WORKERS=1
  ECHOCHAT_GUNICORN_LOGLEVEL=info
  ECHOCHAT_GUNICORN_ACCESSLOG=-
  ECHOCHAT_GUNICORN_ERRORLOG=-
  ECHOCHAT_GUNICORN_TIMEOUT=60
  ECHOCHAT_GUNICORN_WORKER_CLASS=gthread
  ECHOCHAT_FORWARDED_ALLOW_IPS=127.0.0.1

Recommended Redis split for scaled deployments:
  ECHOCHAT_RATE_LIMIT_STORAGE_URI=redis://127.0.0.1:6379/0
  ECHOCHAT_SOCKETIO_MESSAGE_QUEUE=redis://127.0.0.1:6379/1
  ECHOCHAT_SHARED_STATE_REDIS_URL=redis://127.0.0.1:6379/2
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


bind = os.environ.get("ECHOCHAT_BIND", "127.0.0.1:5000")
workers = _env_int("ECHOCHAT_WORKERS", 1, minimum=1)
threads = _env_int("ECHOCHAT_GUNICORN_THREADS", 100, minimum=1)
worker_class = os.environ.get("ECHOCHAT_GUNICORN_WORKER_CLASS", "gthread").strip() or "gthread"

# Make the effective worker count visible to app startup code.
raw_env = [f"WEB_CONCURRENCY={workers}"]

# WebSockets/polling keep connections open; avoid overly low timeouts.
timeout = _env_int("ECHOCHAT_GUNICORN_TIMEOUT", 60, minimum=1)
keepalive = _env_int("ECHOCHAT_GUNICORN_KEEPALIVE", 5, minimum=1)
worker_connections = _env_int("ECHOCHAT_GUNICORN_WORKER_CONNECTIONS", 1000, minimum=1)

loglevel = os.environ.get("ECHOCHAT_GUNICORN_LOGLEVEL", "info")
accesslog = os.environ.get("ECHOCHAT_GUNICORN_ACCESSLOG", "-")
errorlog = os.environ.get("ECHOCHAT_GUNICORN_ERRORLOG", "-")

# Trust forwarded headers only from the local reverse proxy by default.
# Do not use '*' unless Gunicorn is completely unreachable by untrusted clients.
forwarded_allow_ips = os.environ.get("ECHOCHAT_FORWARDED_ALLOW_IPS", "127.0.0.1")
