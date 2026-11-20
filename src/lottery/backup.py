"""Immutable local backup packages and isolated restore-drill verification.

This is an offline recovery adapter. A second directory on the same host is
not an independent backup failure domain and must not be represented as one.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import tempfile
from typing import Any

from .ledger_lock import ledger_lock
from .storage import FileSystemObjectStore, StorageError, _atomic_immutable, _read_canonical
from .subset_model.artifact import canonicalize, parse_json_strict, ArtifactValidationError

BACKUP_SCHEMA = "lottery.storage-backup/v1"
_BACKUP_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
_CORRUPTION_KEYS = (
    "dangling_pointers", "missing_publication_receipts",
    "corrupt_publication_receipts", "corrupt_commit_receipts", "corrupt_objects",
)


class BackupError(RuntimeError):
    """Raised when backup or restore integrity cannot be established."""


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _safe_relative(value: str) -> PurePosixPath:
    if not isinstance(value, str) or not value or "\\" in value or ":" in value:
        raise BackupError("backup file path must be a portable relative POSIX path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in ("", ".", "..") for part in path.parts):
        raise BackupError("backup file path traversal is forbidden")
    return path


def _excluded(name: str) -> bool:
    return name.endswith(".lock") or (name.startswith(".") and name.endswith(".tmp"))


def _inventory(root: Path) -> list[dict[str, Any]]:
    if not root.exists() or not root.is_dir() or root.is_symlink():
        raise BackupError("storage root must be an existing non-symlink directory")
    entries = []
    for directory, dirnames, filenames in os.walk(root, topdown=True, followlinks=False):
        base = Path(directory)
        kept_dirs = []
        for dirname in sorted(dirnames):
            child = base / dirname
            if child.is_symlink():
                raise BackupError(f"symlink directory is forbidden in storage root: {child}")
            kept_dirs.append(dirname)
        dirnames[:] = kept_dirs
        for filename in sorted(filenames):
            if _excluded(filename):
                continue
            path = base / filename
            if path.is_symlink() or not path.is_file():
                raise BackupError(f"non-regular storage entry is forbidden: {path}")
            before = path.stat()
            raw = path.read_bytes()
            after = path.stat()
            if (before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns
                    or len(raw) != after.st_size):
                raise BackupError(f"storage object changed while inventorying: {path}")
            relative = path.relative_to(root).as_posix()
            _safe_relative(relative)
            entries.append({
                "path": relative,
                "byte_length": len(raw),
                "sha256": _sha(raw),
            })
    entries.sort(key=lambda item: item["path"])
    return entries


def _inventory_hash(entries: list[dict[str, Any]]) -> str:
    return _sha(canonicalize(entries))


def create_backup(
    source_root: str | Path,
    backup_root: str | Path,
    *,
    backup_id: str,
    source_commit: str,
    runtime: str,
    storage_adapter_version: str = "filesystem-object-store/v1",
) -> dict[str, Any]:
    """Create a no-clobber local backup package after a stable double inventory."""
    if not isinstance(backup_id, str) or not _BACKUP_ID.fullmatch(backup_id):
        raise BackupError("backup_id must be a canonical 1-128 character identifier")
    if not isinstance(source_commit, str) or not _GIT_SHA.fullmatch(source_commit):
        raise BackupError("source_commit must be a full lowercase Git SHA")
    if not isinstance(runtime, str) or not runtime or not isinstance(storage_adapter_version, str) or not storage_adapter_version:
        raise BackupError("runtime and storage_adapter_version must be non-empty")
    source_input = Path(source_root)
    if source_input.is_symlink():
        raise BackupError("source_root cannot be a symlink")
    source = source_input.resolve(strict=True)
    if not source.is_dir():
        raise BackupError("source_root must be a directory")
    destination_input = Path(backup_root)
    if destination_input.is_symlink():
        raise BackupError("backup_root cannot be a symlink")
    destination = destination_input.resolve(strict=False)
    try:
        source.relative_to(destination)
        raise BackupError("backup_root cannot contain source_root")
    except ValueError:
        pass
    try:
        destination.relative_to(source)
        raise BackupError("backup_root cannot be inside source_root")
    except ValueError:
        pass
    destination.mkdir(parents=True, exist_ok=True)
    destination = destination.resolve(strict=True)

    final_dir = destination / backup_id
    lock_path = destination / f"{backup_id}.backup"
    with ledger_lock(lock_path):
        if final_dir.exists():
            raise BackupError("backup_id already exists; immutable no-clobber required")
        initial = _inventory(source)
        temporary = Path(tempfile.mkdtemp(prefix=f".{backup_id}.", dir=destination))
        try:
            payload_root = temporary / "payload"
            payload_root.mkdir()
            for entry in initial:
                relative = _safe_relative(entry["path"])
                source_path = source.joinpath(*relative.parts)
                target_path = payload_root.joinpath(*relative.parts)
                raw = source_path.read_bytes()
                if len(raw) != entry["byte_length"] or _sha(raw) != entry["sha256"]:
                    raise BackupError(f"source changed before backup copy: {entry['path']}")
                _atomic_immutable(target_path, raw)
                copied = target_path.read_bytes()
                if len(copied) != entry["byte_length"] or _sha(copied) != entry["sha256"]:
                    raise BackupError(f"backup read-back verification failed: {entry['path']}")

            final_inventory = _inventory(source)
            if final_inventory != initial:
                raise BackupError("storage root changed during backup; retry after quiescing writers")
            total_bytes = sum(item["byte_length"] for item in initial)
            body = {
                "schema": BACKUP_SCHEMA,
                "backup_id": backup_id,
                "created_at_utc": datetime.now(timezone.utc).isoformat(),
                "source_commit": source_commit,
                "runtime": runtime,
                "storage_adapter_version": storage_adapter_version,
                "file_count": len(initial),
                "total_bytes": total_bytes,
                "inventory_sha256": _inventory_hash(initial),
                "files": initial,
            }
            manifest = {**body, "manifest_sha256": _sha(canonicalize(body))}
            _atomic_immutable(temporary / "manifest.json", canonicalize(manifest))
            os.rename(temporary, final_dir)
            if hasattr(os, "O_DIRECTORY"):
                fd = os.open(destination, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(fd)
                finally:
                    os.close(fd)
            return {
                "backup_id": backup_id,
                "backup_path": str(final_dir),
                "manifest_sha256": manifest["manifest_sha256"],
                "file_count": len(initial),
                "total_bytes": total_bytes,
            }
        except Exception:
            shutil.rmtree(temporary, ignore_errors=True)
            raise


def verify_backup(backup_dir: str | Path) -> dict[str, Any]:
    """Verify the canonical manifest, exact file inventory, lengths and hashes."""
    root_input = Path(backup_dir)
    if root_input.is_symlink():
        raise BackupError("backup package cannot be a symlink")
    root = root_input.resolve(strict=True)
    if not root.is_dir() or (root / "manifest.json").is_symlink():
        raise BackupError("backup package or manifest must be a regular directory/file")
    try:
        manifest_raw = (root / "manifest.json").read_bytes()
        manifest = parse_json_strict(manifest_raw)
    except (OSError, ArtifactValidationError) as exc:
        raise BackupError("backup manifest is missing or invalid JSON") from exc
    if not isinstance(manifest, dict) or canonicalize(manifest) != manifest_raw:
        raise BackupError("backup manifest must be canonical JSON")
    required = {
        "schema", "backup_id", "created_at_utc", "source_commit", "runtime",
        "storage_adapter_version", "file_count", "total_bytes",
        "inventory_sha256", "files", "manifest_sha256",
    }
    if set(manifest) != required or manifest.get("schema") != BACKUP_SCHEMA:
        raise BackupError("backup manifest schema or fields are invalid")
    if (not isinstance(manifest["backup_id"], str)
            or not _BACKUP_ID.fullmatch(manifest["backup_id"])
            or root.name != manifest["backup_id"]):
        raise BackupError("backup ID does not match package directory")
    if (type(manifest["file_count"]) is not int or manifest["file_count"] < 0
            or type(manifest["total_bytes"]) is not int or manifest["total_bytes"] < 0
            or not isinstance(manifest["inventory_sha256"], str)
            or not _SHA256.fullmatch(manifest["inventory_sha256"])
            or not isinstance(manifest["manifest_sha256"], str)
            or not _SHA256.fullmatch(manifest["manifest_sha256"])):
        raise BackupError("backup count or manifest digest fields are invalid")
    if not isinstance(manifest["source_commit"], str) or not _GIT_SHA.fullmatch(manifest["source_commit"]):
        raise BackupError("backup source commit is invalid")
    try:
        created = datetime.fromisoformat(manifest["created_at_utc"].replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise BackupError("backup timestamp is invalid") from exc
    if created.tzinfo is None or created.utcoffset() is None:
        raise BackupError("backup timestamp must be timezone-aware")
    body = {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    if manifest["manifest_sha256"] != _sha(canonicalize(body)):
        raise BackupError("backup manifest digest mismatch")
    entries = manifest["files"]
    if not isinstance(entries, list):
        raise BackupError("backup files inventory must be an array")
    paths = []
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {"path", "byte_length", "sha256"}:
            raise BackupError("backup inventory entry shape is invalid")
        path = _safe_relative(entry["path"])
        if type(entry["byte_length"]) is not int or entry["byte_length"] < 0:
            raise BackupError("backup byte_length must be a non-negative integer")
        if not isinstance(entry["sha256"], str) or not _SHA256.fullmatch(entry["sha256"]):
            raise BackupError("backup file digest is invalid")
        paths.append(path.as_posix())
    if paths != sorted(set(paths)):
        raise BackupError("backup file paths must be unique and sorted")
    if manifest["file_count"] != len(entries) or manifest["total_bytes"] != sum(x["byte_length"] for x in entries):
        raise BackupError("backup inventory counts do not match manifest")
    if manifest["inventory_sha256"] != _inventory_hash(entries):
        raise BackupError("backup inventory digest mismatch")

    payload_root = root / "payload"
    if payload_root.is_symlink() or not payload_root.is_dir():
        raise BackupError("backup payload directory is missing")
    actual_paths = []
    actual_dirs = set()
    for directory, dirnames, filenames in os.walk(payload_root, topdown=True, followlinks=False):
        base = Path(directory)
        for dirname in dirnames:
            child_dir = base / dirname
            if child_dir.is_symlink():
                raise BackupError("backup contains a symlink directory")
            actual_dirs.add(child_dir.relative_to(payload_root).as_posix())
        for filename in filenames:
            path = base / filename
            if path.is_symlink() or not path.is_file():
                raise BackupError("backup contains a non-regular file")
            actual_paths.append(path.relative_to(payload_root).as_posix())
    if sorted(actual_paths) != paths:
        raise BackupError("backup payload contains missing or unexpected files")
    expected_dirs = set()
    for value in paths:
        parent = PurePosixPath(value).parent
        while parent.as_posix() not in ("", "."):
            expected_dirs.add(parent.as_posix())
            parent = parent.parent
    if actual_dirs != expected_dirs:
        raise BackupError("backup payload contains unexpected empty directories")
    for entry in entries:
        relative = _safe_relative(entry["path"])
        path = payload_root.joinpath(*relative.parts)
        raw = path.read_bytes()
        if len(raw) != entry["byte_length"] or _sha(raw) != entry["sha256"]:
            raise BackupError(f"backup payload integrity mismatch: {entry['path']}")
    root_files = sorted(p.name for p in root.iterdir())
    if root_files != ["manifest.json", "payload"]:
        raise BackupError("backup package contains unexpected top-level entries")
    return {
        "backup_id": manifest["backup_id"],
        "manifest_sha256": manifest["manifest_sha256"],
        "file_count": manifest["file_count"],
        "total_bytes": manifest["total_bytes"],
        "verified": True,
    }


def restore_backup(backup_dir: str | Path, restore_root: str | Path) -> dict[str, Any]:
    """Restore into a new isolated root and atomically expose it after verification."""
    summary = verify_backup(backup_dir)
    backup = Path(backup_dir).resolve(strict=True)
    destination_input = Path(restore_root)
    if destination_input.exists() or destination_input.is_symlink():
        raise BackupError("restore_root must not already exist; partial/overwriting restore is forbidden")
    destination = destination_input.resolve(strict=False)
    try:
        destination.relative_to(backup)
        raise BackupError("restore_root cannot be inside the backup package")
    except ValueError:
        pass
    destination.parent.mkdir(parents=True, exist_ok=True)
    manifest = _read_canonical(backup / "manifest.json")
    payload_root = backup / "payload"
    temporary = Path(tempfile.mkdtemp(
        prefix=f".{destination.name}.restore.", dir=destination.parent
    ))
    try:
        for entry in manifest["files"]:
            relative = _safe_relative(entry["path"])
            source = payload_root.joinpath(*relative.parts)
            target = temporary.joinpath(*relative.parts)
            _atomic_immutable(target, source.read_bytes())
        restored = _inventory(temporary)
        if restored != manifest["files"]:
            raise BackupError("restored file inventory differs from backup manifest")

        reconciliation = FileSystemObjectStore(temporary).reconcile()
        corruption = {
            key: reconciliation[key]
            for key in _CORRUPTION_KEYS
            if reconciliation.get(key)
        }
        if corruption:
            raise BackupError(
                f"restored storage reconciliation found integrity failures: {corruption}"
            )
        with ledger_lock(destination.parent / f"{destination.name}.restore"):
            if destination.exists():
                raise BackupError("restore_root appeared during restore; refusing overwrite")
            os.rename(temporary, destination)
            if hasattr(os, "O_DIRECTORY"):
                fd = os.open(destination.parent, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(fd)
                finally:
                    os.close(fd)
        return {
            "schema": "lottery.storage-restore-drill/v1",
            "backup_id": summary["backup_id"],
            "backup_manifest_sha256": summary["manifest_sha256"],
            "restored_inventory_sha256": _inventory_hash(restored),
            "file_count": len(restored),
            "total_bytes": sum(item["byte_length"] for item in restored),
            "verified": True,
            "reconciliation": reconciliation,
        }
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
