"""gunicorn_conf.py

Default Gunicorn config for EchoChat + Flask-SocketIO.

The default production path uses Gunicorn gthread + Flask-SocketIO
threading mode. This avoids Eventlet worker-entrypoint failures on newer
Python environments while keeping WebSocket support through simple-websocket.

Environment variables:
  ECHOCHAT_BIND=0.0.0.0:5000
  ECHOCHAT_WORKERS=1
  ECHOCHAT_GUNICORN_LOGLEVEL=info
  ECHOCHAT_GUNICORN_ACCESSLOG=-
  ECHOCHAT_GUNICORN_ERRORLOG=-
  ECHOCHAT_GUNICORN_TIMEOUT=60
  ECHOCHAT_GUNICORN_WORKER_CLASS=gthread

Recommended:
  ECHOCHAT_SOCKETIO_ASYNC=threading
  REDIS_URL=redis://127.0.0.1:6379/0
"""

from __future__ import annotations

import os

bind = os.environ.get("ECHOCHAT_BIND", "0.0.0.0:5000")
workers = int(os.environ.get("ECHOCHAT_WORKERS", "1"))
threads = int(os.environ.get("ECHOCHAT_GUNICORN_THREADS", "100"))
worker_class = os.environ.get("ECHOCHAT_GUNICORN_WORKER_CLASS", "gthread").strip() or "gthread"

# Make the effective worker count visible to app startup code.
# EchoChat uses WEB_CONCURRENCY when deciding whether to force a
# WebSocket-only transport profile and when emitting multi-worker warnings.
raw_env = [f"WEB_CONCURRENCY={workers}"]

# WebSockets keep connections open; avoid overly low timeouts.
timeout = int(os.environ.get("ECHOCHAT_GUNICORN_TIMEOUT", "60"))
keepalive = int(os.environ.get("ECHOCHAT_GUNICORN_KEEPALIVE", "5"))
worker_connections = int(os.environ.get("ECHOCHAT_GUNICORN_WORKER_CONNECTIONS", "1000"))

loglevel = os.environ.get("ECHOCHAT_GUNICORN_LOGLEVEL", "info")
accesslog = os.environ.get("ECHOCHAT_GUNICORN_ACCESSLOG", "-")
errorlog = os.environ.get("ECHOCHAT_GUNICORN_ERRORLOG", "-")

# Important for Socket.IO upgrades through reverse proxies.
forwarded_allow_ips = os.environ.get("ECHOCHAT_FORWARDED_ALLOW_IPS", "*")
