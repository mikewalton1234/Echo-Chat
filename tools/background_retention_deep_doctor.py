#!/usr/bin/env python3
"""Deep S18 static checks for background retention/cleanup.

This doctor covers follow-up risks that the first S18 pass intentionally left
for deeper review: false-positive janitor success when a cleanup helper returns
{"ok": false}, safe private-file blob cleanup, and transaction recovery for
optional privacy-retention diagnostics.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _function_body(rel: str, name: str) -> str:
    text = _read(rel)
    tree = ast.parse(text)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return ast.get_source_segment(text, node) or ""
    return ""


def main() -> int:
    failures: list[str] = []
    janitor = _read("janitor.py")
    cleanup = _read("maintenance_cleanup.py")
    privacy = _read("privacy_retention.py")
    routes = _read("routes_admin_tools.py")
    defaults = _read("main.py") + "\n" + _read("interactive_setup.py")

    run_task = _function_body("janitor.py", "_run_task")
    for token in [
        'result.get("ok") is False',
        'cycle["ok"] = False',
        'task_status = {"ok": result_ok',
        'task_status["error"] = str(result.get("error"))',
    ]:
        if token not in run_task:
            failures.append(f"_run_task does not propagate helper-level failure: {token}")

    run_cycle = _function_body("janitor.py", "run_janitor_cycle")
    for token in [
        "cleanup_revoked_private_files(settings, limit=private_file_limit)",
        "cleanup_orphan_private_file_blobs(settings, limit=private_file_limit)",
        '"revoked_private_files"',
        '"orphan_private_file_blobs"',
        '"private_file_cleanup_batch_limit"',
    ]:
        if token not in run_cycle:
            failures.append(f"run_janitor_cycle missing deep private-file cleanup token: {token}")

    for token in [
        "from security import safe_existing_file_under",
        "def cleanup_revoked_private_files",
        "def cleanup_orphan_private_file_blobs",
        "cleanup_revoked_private_files_enabled",
        "cleanup_orphan_private_file_blobs_enabled",
        "revoked_private_file_retention_days",
        "orphan_private_file_grace_minutes",
        "_PRIVATE_FILE_ID_RE",
        "_collect_old_private_blob_candidates",
        "_delete_confirmed_orphan_private_blobs",
        "WHERE file_id = ANY(%s)",
        "known[table] = set(candidates.get(table, {}).keys())",
        "db_lookup_failed",
        "safe_existing_file_under(root_path",
        '.glob("*.bin")',
        "DELETE FROM {table}",
        "COALESCE(revoked, FALSE) = TRUE",
    ]:
        if token not in cleanup:
            failures.append(f"maintenance_cleanup.py missing safe private-file cleanup token: {token}")
    if "DELETE FROM users" in cleanup:
        failures.append("background cleanup must never delete users")
    if "SELECT file_id FROM {table} LIMIT" in cleanup:
        failures.append("orphan blob cleanup must not infer orphan state from partial table scans")
    if "def _scan_orphan_bin_files" in cleanup:
        failures.append("legacy orphan scanner should be replaced by candidate + exact DB confirmation helpers")

    for token in [
        "def _rollback_after_optional_failure",
        "counts[\"auth_sessions_raw_old\"] = None\n                _rollback_after_optional_failure()",
        "counts[\"auth_tokens_raw_old\"] = None\n                _rollback_after_optional_failure()",
        "counts[\"password_reset_tokens_raw_old\"] = None\n                _rollback_after_optional_failure()",
        "counts[\"audit_details_raw_old\"] = None\n                    _rollback_after_optional_failure()",
    ]:
        if token not in privacy:
            failures.append(f"privacy_retention_counts missing optional-query rollback token: {token}")

    for token in [
        '"cleanup_revoked_private_files_enabled": "bool"',
        '"cleanup_orphan_private_file_blobs_enabled": "bool"',
        '"revoked_private_file_retention_days": "int"',
        '"orphan_private_file_grace_minutes": "int"',
        '"private_file_cleanup_batch_limit": "int"',
        'patch["revoked_private_file_retention_days"] = max(1, min(int(patch["revoked_private_file_retention_days"]), 3650))',
        'patch["orphan_private_file_grace_minutes"] = max(5, min(int(patch["orphan_private_file_grace_minutes"]), 24 * 60 * 30))',
        '"private_file_cleanup_batch_limit")',
    ]:
        if token not in routes:
            failures.append(f"routes_admin_tools.py missing private-file cleanup setting/clamp token: {token}")

    for token in [
        '"cleanup_revoked_private_files_enabled": True',
        '"cleanup_orphan_private_file_blobs_enabled": True',
        '"revoked_private_file_retention_days": 7',
        '"orphan_private_file_grace_minutes": 60',
        '"private_file_cleanup_batch_limit": 500',
    ]:
        if token not in defaults:
            failures.append(f"defaults missing deep S18 setting: {token}")

    if failures:
        print("❌ Background retention deep doctor failed")
        for failure in failures:
            print(f" - {failure}")
        return 1
    print("✅ Background retention deep doctor passed")
    print("   checks: helper-level failure propagation, private-file retention cleanup, exact-confirmed orphan blob cleanup, privacy count rollbacks")
    return 0


if __name__ == "__main__":
    sys.exit(main())
