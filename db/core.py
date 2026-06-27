#!/usr/bin/env python3
"""Core database connection, identity, and app bootstrap helpers."""

from __future__ import annotations

import logging
import os

import psycopg2
from psycopg2.pool import PoolError
from flask import g

from constants import get_db_connection_string, sanitize_postgres_dsn, redact_postgres_dsn
from db.bootstrap import ensure_database_ready
from db import shared


def prepare_runtime_database(settings: dict) -> dict:
    """Normalize runtime DSNs and best-effort prepare the target database."""
    runtime_dsn = str(sanitize_postgres_dsn(str(settings.get("database_url") or get_db_connection_string(settings))))
    bootstrap_dsn = (
        os.getenv("ECHOCHAT_DB_BOOTSTRAP_URL")
        or os.getenv("DATABASE_BOOTSTRAP_URL")
        or settings.get("database_bootstrap_url")
        or ""
    )
    settings["database_url"] = runtime_dsn
    if bootstrap_dsn:
        settings["database_bootstrap_url"] = str(bootstrap_dsn)
    ensure_database_ready(runtime_dsn, recreate=False, bootstrap_dsn=bootstrap_dsn or None)
    return {"runtime_dsn": runtime_dsn, "bootstrap_dsn": bootstrap_dsn or None}

def init_db_pool(minconn: int = 1, maxconn: int = 50, dsn: str | None = None) -> None:
    """Initialise a global ThreadedConnectionPool.

    Safe to call multiple times (no-op after first init).
    """
    if shared._POOL is not None:
        return

    shared._DSN = str(sanitize_postgres_dsn(dsn or get_db_connection_string()))

    try:
        shared._POOL = shared.ThreadedConnectionPool(
            minconn=int(minconn),
            maxconn=int(maxconn),
            dsn=shared._DSN,
        )
        logging.info("✅  Postgres connection pool ready (min=%s max=%s)", minconn, maxconn)
    except Exception as e:
        shared._POOL = None
        logging.warning("⚠️  Could not initialise Postgres pool; falling back to direct connects: %s", e)


def _acquire_conn():
    """Acquire a connection either from the pool or by direct connect.

    Returns (conn, from_pool: bool)

    If the pool is temporarily exhausted or cannot hand out a connection,
    open a short-lived direct connection instead of failing the request. This
    keeps bursty UI traffic (admin polling, reconnects, multiple tabs) from
    turning one saturated pool into user-visible room/PM failures.
    """
    if shared._POOL is not None:
        try:
            return shared._POOL.getconn(), True
        except PoolError as e:
            logging.warning("Postgres pool exhausted; opening temporary direct connection: %s", e)
        except Exception as e:
            logging.warning("Postgres pool getconn failed; opening temporary direct connection: %s", e)
    return psycopg2.connect(shared._DSN or get_db_connection_string()), False


def _release_conn(conn, from_pool: bool) -> None:
    if conn is None:
        return
    if shared._POOL is not None and from_pool:
        try:
            # Ensure a clean connection is returned to the pool.
            conn.rollback()
        except Exception:
            pass
        shared._POOL.putconn(conn)
    else:
        conn.close()

def get_db() -> psycopg2.extensions.connection:
    """
    Return one psycopg2 connection per Flask request context (stored in g.db).
    Uses get_db_connection_string() for runtime evaluation.
    """
    if not hasattr(g, "db"):
        conn, from_pool = _acquire_conn()
        g.db = conn
        g.db_from_pool = from_pool
    return g.db


def close_db(error=None):
    """
    Teardown: close the connection stored in g.db (if any).
    Called automatically via app.teardown_appcontext.
    """
    db_conn = g.pop("db", None)
    from_pool = bool(g.pop("db_from_pool", False))
    if db_conn is not None:
        try:
            _release_conn(db_conn, from_pool)
        except Exception as e:
            logging.error("Error releasing DB connection: %s", e)
    if error:
        logging.error("DB teardown error: %s", error)

def init_database():
    """Apply tracked schema migrations and seed baseline data when needed."""
    logging.info("🔧  Initialising DB via tracked migrations…")
    from db.migrations import apply_migrations

    result = apply_migrations()
    applied = result.get("applied") or []
    skipped = result.get("skipped") or []
    logging.info("Migration result: applied=%s skipped=%s", ", ".join(applied) if applied else "none", ", ".join(skipped) if skipped else "none")
    # Log the *effective* runtime DSN used by the pool/direct connection layer.
    # This matters when Echo-Chat is started with --config or env overrides: the
    # default server_config.json may point somewhere else, and logging that older
    # value makes wrong-database investigations misleading.
    effective_dsn = shared._DSN or get_db_connection_string()
    logging.info("✅  DB ready at %s", redact_postgres_dsn(effective_dsn))
    try:
        logging.info("Tracked schema state: %s", get_schema_version())
    except Exception:
        pass
    return result


def get_db_identity() -> dict:
    """Return runtime identity information for the current DB connection.

    Helps detect 'wrong database / wrong role' mistakes quickly.
    """
    conn = get_db()
    out = {
        "current_user": None,
        "current_database": None,
        "server_addr": None,
        "server_port": None,
        "server_version": None,
    }
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT current_user, current_database(), inet_server_addr(), inet_server_port(), version();"
            )
            row = cur.fetchone()
        if row:
            out["current_user"] = row[0]
            out["current_database"] = row[1]
            out["server_addr"] = str(row[2]) if row[2] is not None else None
            out["server_port"] = int(row[3]) if row[3] is not None else None
            out["server_version"] = str(row[4]) if row[4] is not None else None
    except Exception as exc:
        out["error"] = str(exc)
    return out


def get_schema_version() -> str:
    """Best-effort schema version string."""
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT to_regclass('public.echochat_schema_meta');")
            row = cur.fetchone()
            reg = row[0] if row else None
            if reg:
                cur.execute(
                    "SELECT version, applied_at FROM echochat_schema_meta WHERE success = TRUE ORDER BY applied_at DESC, version DESC LIMIT 1;"
                )
                latest = cur.fetchone()
                cur.execute("SELECT count(*) FROM echochat_schema_meta WHERE success = TRUE;")
                applied_count = int((cur.fetchone() or [0])[0] or 0)
                if latest and latest[0]:
                    return f"{latest[0]} ({applied_count} applied migrations)"
            cur.execute("SELECT count(*) FROM pg_tables WHERE schemaname='public';")
            n_tables = cur.fetchone()[0]
        return f"untracked schema (public tables={n_tables})"
    except Exception as exc:
        return f"unknown ({exc})"

def init_app(app):
    """
    Call in server_init.py after creating the Flask app:

        from database import init_app as init_db
        app = Flask(__name__)
        init_db(app)

    This runs init_database() once and registers teardown.
    """
    init_database()
    app.teardown_appcontext(close_db)
