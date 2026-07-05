#!/usr/bin/env python3
"""Build a sanitized Echo-Chat release package.

This script is intentionally self-contained and stdlib-only so it can run from
an extracted source folder before dependencies are installed. It creates:
  - a release zip with local secrets/runtime state excluded;
  - a .sha256 file for that zip;
  - a JSON manifest describing the package and packaging policy.

Security/reproducibility notes:
  - Symlinks are never packaged. This prevents a malicious or accidental link
    inside the project from pulling in files outside the source tree.
  - Archive paths are validated and always nested under a single package root.
  - Zip member timestamps and permissions are normalized so rebuilds are stable
    when source content is stable.
  - The manifest avoids writing absolute local source paths.
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import re
import stat
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
VERSION_FILE = ROOT / "VERSION.txt"
DETERMINISTIC_ZIP_DATE = (2024, 1, 1, 0, 0, 0)

# Directory names that should never be packaged as source release content.
EXCLUDED_DIR_NAMES = {
    ".git",
    ".hg",
    ".svn",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "venv",
    "env",
    "ENV",
    "__pycache__",
    "node_modules",
    "dist",
    "build",
    "coverage",
    "htmlcov",
    ".vscode",
    ".idea",
    "logs",
    "uploads",
    "downloads",
    "private_uploads",
    "mail_spool",
    "backups",
    "certs",
    "instance",
}

# Individual file names that are local/runtime/secret-bearing by convention.
EXCLUDED_FILE_NAMES = {
    ".env",
    ".env.local",
    ".env.production",
    ".env.development",
    "server_config.json",
    "settings.json",
    "secrets.json",
    "server_key.key",
    "release_manifest.json",
    "release-report.md",
}

# Extension/glob filters for artifacts, keys, caches, databases, and logs.
EXCLUDED_GLOBS = (
    "*.pyc",
    "*.pyo",
    "*.pyd",
    "*.log",
    "*.tmp",
    "*.bak",
    "*.sqlite",
    "*.sqlite3",
    "*.db",
    "*.pem",
    "*.key",
    "*.crt",
    "*.csr",
    "*.p12",
    "*.pfx",
    "*.zip",
    "*.tar",
    "*.tar.gz",
    "*.tgz",
    "*.sha256",
    "Echo-Chat-v*.zip",
)

ALLOWED_DOTENV_TEMPLATES = {".env.example"}


def _read_version() -> str:
    version = VERSION_FILE.read_text(encoding="utf-8").strip()
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:-[A-Za-z0-9_.-]+)?", version):
        raise SystemExit(f"Unsafe or invalid VERSION.txt value: {version!r}")
    return version


def _slug(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip())
    value = re.sub(r"-+", "-", value).strip("-._")
    return value or "release"


def _rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def _is_inside(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except Exception:
        return False


def _safe_archive_name(package_root: str, rel: str) -> str:
    rel_path = PurePosixPath(rel)
    if rel_path.is_absolute() or ".." in rel_path.parts or any(part == "" for part in rel_path.parts):
        raise SystemExit(f"Unsafe release archive path: {rel!r}")
    arcname = PurePosixPath(package_root) / rel_path
    if arcname.is_absolute() or ".." in arcname.parts:
        raise SystemExit(f"Unsafe release archive member: {str(arcname)!r}")
    return str(arcname)


def should_exclude(path: Path, *, output_dir: Path | None = None) -> tuple[bool, str | None]:
    """Return (exclude, reason) for a project path."""

    rel = _rel(path)
    name = path.name

    if path.is_symlink():
        return True, "symlink"

    # Refuse regular-file paths that somehow resolve outside the source root.
    # This is mostly defensive because symlinks are already excluded above.
    if path.exists() and not _is_inside(path, ROOT):
        return True, "outside_source_root"

    if output_dir and _is_inside(path, output_dir):
        return True, "output_dir"

    parts = set(path.relative_to(ROOT).parts)
    matched_dir = sorted(parts.intersection(EXCLUDED_DIR_NAMES))
    if matched_dir:
        return True, f"excluded_dir:{matched_dir[0]}"

    if name in ALLOWED_DOTENV_TEMPLATES:
        return False, None

    if name in EXCLUDED_FILE_NAMES:
        return True, f"excluded_file:{name}"

    if name.startswith(".env.") and name not in ALLOWED_DOTENV_TEMPLATES:
        return True, "dotenv_secret_variant"

    for pattern in EXCLUDED_GLOBS:
        if fnmatch.fnmatch(name, pattern) or fnmatch.fnmatch(rel, pattern):
            return True, f"excluded_glob:{pattern}"

    return False, None


def iter_package_files(output_dir: Path | None = None) -> tuple[list[Path], dict[str, int]]:
    files: list[Path] = []
    excluded_counts: dict[str, int] = {}
    for current, dirnames, filenames in os.walk(ROOT, followlinks=False):
        cur = Path(current)

        # Prune excluded directories early so large runtime trees are never walked.
        kept_dirs = []
        for dirname in dirnames:
            candidate = cur / dirname
            excluded, reason = should_exclude(candidate, output_dir=output_dir)
            if excluded:
                excluded_counts[reason or "excluded"] = excluded_counts.get(reason or "excluded", 0) + 1
            else:
                kept_dirs.append(dirname)
        dirnames[:] = kept_dirs

        for filename in filenames:
            candidate = cur / filename
            excluded, reason = should_exclude(candidate, output_dir=output_dir)
            if excluded:
                excluded_counts[reason or "excluded"] = excluded_counts.get(reason or "excluded", 0) + 1
                continue
            if not candidate.is_file():
                excluded_counts["not_regular_file"] = excluded_counts.get("not_regular_file", 0) + 1
                continue
            files.append(candidate)
    return sorted(files, key=lambda p: _rel(p)), excluded_counts


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _zip_mode(path: Path) -> int:
    """Return normalized POSIX permissions for a release member."""
    rel = _rel(path)
    if rel.startswith("scripts/") and path.suffix in {".sh"}:
        return 0o755
    if path.suffix == ".py" and (rel.startswith("scripts/") or rel.startswith("tools/")):
        # These scripts also run via "python script.py", but keeping executable
        # mode for helper entry points is convenient and deterministic.
        return 0o755
    return 0o644


def _write_zip_member(zf: zipfile.ZipFile, *, package_root: str, path: Path) -> None:
    rel = _rel(path)
    arcname = _safe_archive_name(package_root, rel)
    info = zipfile.ZipInfo(arcname, date_time=DETERMINISTIC_ZIP_DATE)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    mode = _zip_mode(path)
    info.external_attr = (stat.S_IFREG | mode) << 16
    data = path.read_bytes()
    zf.writestr(info, data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)


def build_package(output_dir: Path, label: str) -> dict:
    version = _read_version()
    label = _slug(label)
    output_dir.mkdir(parents=True, exist_ok=True)
    package_root = f"Echo-Chat-v{version}-{label}"
    zip_path = output_dir / f"{package_root}.zip"
    sha_path = output_dir / f"{zip_path.name}.sha256"
    manifest_path = output_dir / f"{package_root}.release_manifest.json"

    files, excluded_counts = iter_package_files(output_dir=output_dir)
    if not files:
        raise SystemExit("No files selected for release package")

    for artifact in (zip_path, sha_path, manifest_path):
        if artifact.exists():
            artifact.unlink()

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for path in files:
            _write_zip_member(zf, package_root=package_root, path=path)

    zip_hash = sha256_file(zip_path)
    sha_path.write_text(f"{zip_hash}  {zip_path.name}\n", encoding="utf-8")

    manifest = {
        "project": "Echo-Chat",
        "version": version,
        "package_name": zip_path.name,
        "package_root": package_root,
        "package_sha256": zip_hash,
        "package_bytes": zip_path.stat().st_size,
        "file_count": len(files),
        "built_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "source_root_name": ROOT.name,
        "safety_policy": {
            "excluded_dir_names": sorted(EXCLUDED_DIR_NAMES),
            "excluded_file_names": sorted(EXCLUDED_FILE_NAMES),
            "excluded_globs": list(EXCLUDED_GLOBS),
            "allowed_dotenv_templates": sorted(ALLOWED_DOTENV_TEMPLATES),
            "symlinks_excluded": True,
            "outside_root_files_excluded": True,
            "absolute_source_path_omitted": True,
            "single_package_root_required": True,
            "deterministic_zip_timestamp": "%04d-%02d-%02dT%02d:%02d:%02dZ" % DETERMINISTIC_ZIP_DATE,
            "normalized_zip_permissions": {"default_file": "0644", "script_entrypoint": "0755"},
        },
        "excluded_counts": dict(sorted(excluded_counts.items())),
        "verify_commands": [
            f"sha256sum -c {sha_path.name}",
            "python tools/release_packaging_doctor.py",
            "python tools/release_packaging_deep_doctor.py",
            "python tools/config_doctor.py --config server_config.json",
            "python main.py --preflight",
        ],
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build sanitized Echo-Chat release zip, checksum, and manifest")
    parser.add_argument("--output-dir", default="dist", help="Directory where release artifacts will be written")
    parser.add_argument("--label", default="ui02-room-message-rendering", help="Package filename suffix after the version")
    parser.add_argument("--json", action="store_true", help="Print manifest JSON instead of a short human summary")
    args = parser.parse_args(list(argv) if argv is not None else None)

    manifest = build_package(Path(args.output_dir).resolve(), args.label)
    if args.json:
        print(json.dumps(manifest, indent=2, sort_keys=True))
    else:
        print(f"Built {manifest['package_name']}")
        print(f"SHA256 {manifest['package_sha256']}")
        print(f"Files {manifest['file_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
