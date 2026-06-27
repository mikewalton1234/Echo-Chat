#!/usr/bin/env python3
"""Tracked migration discovery and execution helpers."""

from __future__ import annotations

import hashlib
import importlib.util
import logging
from pathlib import Path

from db.core import _acquire_conn, _release_conn
from db.shared import MIGRATIONS_DIR, SCHEMA_META_TABLE, MigrationSpec


# A small, explicit compatibility set for beta builds where a migration file
# was corrected after local databases had already recorded a checksum. Applied
# migrations remain immutable in normal cases; follow-up fixes must use a new
# migration version.
_COMPATIBLE_CHECKSUMS: dict[str, set[str]] = {
    "0012_profile_safety_privacy_badges": {
        "80c9c38c453fae407d6fb2fbae2f1d0781141b572de7259755132cee53acb945",
        "6af0728a882c36cbab0185b096941650947e68290a360e07b22236769c2706e1",
    },
}


def _checksums_compatible(version: str, db_checksum: str | None, file_checksum: str | None) -> bool:
    if not db_checksum or not file_checksum:
        return False
    if db_checksum == file_checksum:
        return True
    allowed = _COMPATIBLE_CHECKSUMS.get(str(version), set())
    return str(db_checksum) in allowed and str(file_checksum) in allowed

def _ensure_schema_meta_table(conn) -> None:
    with conn.cursor() as cur:
        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {SCHEMA_META_TABLE} (
                version     TEXT PRIMARY KEY,
                name        TEXT NOT NULL,
                kind        TEXT NOT NULL DEFAULT 'python',
                checksum    TEXT NOT NULL,
                applied_at  TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
                success     BOOLEAN NOT NULL DEFAULT TRUE,
                notes       TEXT
            );
            """
        )
    conn.commit()


def _checksum_path(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_python_migration(path: Path) -> MigrationSpec:
    spec = importlib.util.spec_from_file_location(f"echochat_migration_{path.stem}", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load migration module: {path.name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    version = str(getattr(module, 'VERSION', '')).strip()
    name = str(getattr(module, 'NAME', path.stem)).strip()
    kind = str(getattr(module, 'KIND', 'python')).strip() or 'python'
    upgrade = getattr(module, 'upgrade', None)
    if not version:
        raise RuntimeError(f"Migration {path.name} is missing VERSION")
    if not callable(upgrade):
        raise RuntimeError(f"Migration {path.name} is missing callable upgrade(conn)")
    return MigrationSpec(
        version=version,
        name=name,
        kind=kind,
        checksum=_checksum_path(path),
        upgrade=upgrade,
        source_path=path,
    )


def list_available_migrations() -> list[dict]:
    migrations: list[MigrationSpec] = []
    if MIGRATIONS_DIR.exists():
        for path in sorted(MIGRATIONS_DIR.glob('m*.py')):
            if path.name == '__init__.py':
                continue
            migrations.append(_load_python_migration(path))
    return [
        {
            'version': m.version,
            'name': m.name,
            'kind': m.kind,
            'checksum': m.checksum,
            'path': str(m.source_path.relative_to(Path(__file__).resolve().parent.parent)),
        }
        for m in migrations
    ]


def _get_applied_migration_rows(conn) -> dict[str, dict]:
    _ensure_schema_meta_table(conn)
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT version, checksum, applied_at, success, notes FROM {SCHEMA_META_TABLE};"
        )
        rows = cur.fetchall() or []
    out = {}
    for version, checksum, applied_at, success, notes in rows:
        out[str(version)] = {
            'checksum': str(checksum),
            'applied_at': applied_at,
            'success': bool(success),
            'notes': notes,
        }
    return out


def apply_migrations() -> dict:
    """Apply all pending migrations in version order.

    The current framework uses Python migrations so we can reuse the project's
    existing idempotent bootstrap helpers while moving toward explicit, tracked
    schema evolution.
    """
    conn, from_pool = _acquire_conn()
    applied_versions: list[str] = []
    skipped_versions: list[str] = []
    try:
        available = []
        if MIGRATIONS_DIR.exists():
            for path in sorted(MIGRATIONS_DIR.glob('m*.py')):
                if path.name == '__init__.py':
                    continue
                available.append(_load_python_migration(path))
        applied = _get_applied_migration_rows(conn)

        for migration in available:
            prior = applied.get(migration.version)
            if prior:
                if not _checksums_compatible(migration.version, prior.get('checksum'), migration.checksum):
                    raise RuntimeError(
                        f"Migration checksum mismatch for {migration.version}: "
                        f"db={prior.get('checksum')} file={migration.checksum}"
                    )
                skipped_versions.append(migration.version)
                continue

            logging.info("Applying migration %s (%s)", migration.version, migration.name)
            migration.upgrade(conn)
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    INSERT INTO {SCHEMA_META_TABLE} (version, name, kind, checksum, success, notes)
                    VALUES (%s, %s, %s, %s, TRUE, %s)
                    ON CONFLICT (version) DO NOTHING;
                    """,
                    (
                        migration.version,
                        migration.name,
                        migration.kind,
                        migration.checksum,
                        f"Applied from {migration.source_path.name}",
                    ),
                )
            conn.commit()
            applied_versions.append(migration.version)

        return {
            'applied': applied_versions,
            'skipped': skipped_versions,
            'available': [m.version for m in available],
            'latest': available[-1].version if available else None,
        }
    finally:
        _release_conn(conn, from_pool)
