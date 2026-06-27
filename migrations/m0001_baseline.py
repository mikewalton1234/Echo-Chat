from __future__ import annotations

VERSION = "0001_baseline"
NAME = "Adopt legacy bootstrap schema into migration framework"
KIND = "python"


def upgrade(conn) -> None:
    """Bootstrap the current legacy schema into the migration system.

    This migration intentionally reuses the existing idempotent schema/bootstrap
    helpers so fresh databases and long-lived legacy databases converge onto the
    same baseline without requiring a giant handwritten SQL dump.
    """
    from database import _legacy_bootstrap_schema

    _legacy_bootstrap_schema()
