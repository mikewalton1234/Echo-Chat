#!/usr/bin/env python3
"""S18 follow-up doctor for encrypted private-file blob cleanup safety.

This doctor checks the exact regression that would be dangerous in production:
old on-disk blobs must not be declared orphaned because the janitor only loaded
some rows from a large dm_files/group_files table.  The safe pattern is to scan a
bounded set of old disk candidates, query the DB for exactly those IDs, and only
then delete IDs absent from that exact lookup.
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
    cleanup = _read("maintenance_cleanup.py")
    orphan = _function_body("maintenance_cleanup.py", "cleanup_orphan_private_file_blobs")
    collector = _function_body("maintenance_cleanup.py", "_collect_old_private_blob_candidates")
    deleter = _function_body("maintenance_cleanup.py", "_delete_confirmed_orphan_private_blobs")

    required_cleanup_tokens = [
        "_PRIVATE_FILE_ID_RE",
        "_empty_orphan_blob_result",
        "_collect_old_private_blob_candidates",
        "_delete_confirmed_orphan_private_blobs",
        "WHERE file_id = ANY(%s)",
        "known[table] = set(candidates.get(table, {}).keys())",
        "db_lookup_failed",
        "No DB confirmation means no deletion",
    ]
    for token in required_cleanup_tokens:
        if token not in cleanup:
            failures.append(f"maintenance_cleanup.py missing cleanup-safety token: {token}")

    forbidden_tokens = [
        "SELECT file_id FROM {table} LIMIT",
        "_scan_orphan_bin_files",
            ]
    for token in forbidden_tokens:
        if token in cleanup:
            failures.append(f"maintenance_cleanup.py still has unsafe/old orphan scan token: {token}")

    for token in [
        "_PRIVATE_FILE_ID_RE.fullmatch(file_id)",
        "path.is_symlink()",
        "skipped_bad_name",
        "skipped_young",
        "safe_existing_file_under(root_path, path)",
        "candidates[file_id] = safe_path",
    ]:
        if token not in collector:
            failures.append(f"candidate collector missing conservative scan token: {token}")

    for token in [
        "if file_id in existing_ids",
        "safe_existing_file_under(root_path, path)",
        "Path(safe_again).stat().st_mtime > cutoff",
        "os.remove(safe_again)",
    ]:
        if token not in deleter:
            failures.append(f"confirmed orphan deleter missing final safety token: {token}")

    if "DELETE FROM dm_files" in orphan or "DELETE FROM group_files" in orphan:
        failures.append("orphan blob cleanup must not delete DB rows")
    if "os.remove" in orphan:
        failures.append("top-level orphan cleanup should delegate deletion through confirmed deleter")

    if failures:
        print("❌ Private file cleanup safety doctor failed")
        for failure in failures:
            print(f" - {failure}")
        return 1

    print("✅ Private file cleanup safety doctor passed")
    print("   checks: exact-candidate DB confirmation, no partial table scan, conservative blob deletion")
    return 0


if __name__ == "__main__":
    sys.exit(main())
