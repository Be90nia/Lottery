"""Crash-safe local content-addressed storage primitives (offline adapter).

This adapter provides staged writes, immutable validation/commit receipts,
compare-and-swap pointers and read-only reconciliation. It is not an
independent backup domain or a production cloud object-store implementation.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import tempfile
from typing import Callable, Any

from .ledger_lock import ledger_lock
from .subset_model.artifact import canonicalize, parse_json_strict, ArtifactValidationError


OBJECT_SCHEMA = "lottery.storage-object/v1"
STAGE_SCHEMA = "lottery.storage-stage/v1"
VALIDATION_SCHEMA = "lottery.storage-validation/v1"
COMMIT_SCHEMA = "lottery.storage-commit/v1"
POINTER_SCHEMA = "lottery.storage-pointer/v1"


class StorageError(RuntimeError):
    """Raised when storage integrity or a state transition is invalid."""


class IdempotencyConflict(StorageError):
    """Raised when an idempotency key is reused with different inputs."""


class StalePointer(StorageError):
    """Raised when a pointer compare-and-swap generation is stale."""


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _atomic_immutable(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            if path.read_bytes() != raw:
                raise StorageError(f"immutable storage collision at {path}")
        if hasattr(os, "O_DIRECTORY"):
            directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def _atomic_replace(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        if hasattr(os, "O_DIRECTORY"):
            directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def _read_canonical(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
        value = parse_json_strict(raw)
    except (OSError, ArtifactValidationError) as exc:
        raise StorageError(f"storage receipt is missing or invalid: {path}") from exc
    if not isinstance(value, dict) or canonicalize(value) != raw:
        raise StorageError(f"storage receipt is not canonical JSON: {path}")
    return value


def _safe_name(value: str, field: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", value):
        raise ValueError(f"{field} must be a canonical 1-128 character identifier")
    return value


class FileSystemObjectStore:
    """Local durable-object adapter with explicit commit and pointer receipts."""

    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.staging = self.root / "staging"
        self.operations = self.root / "operations"
        self.validations = self.root / "validations"
        self.commits = self.root / "commits"
        self.objects = self.root / "objects" / "sha256"
        self.pointers = self.root / "pointers"
        self.publications = self.root / "publications"

    def _operation_id(self, idempotency_key: str) -> str:
        if not isinstance(idempotency_key, str) or not idempotency_key or len(idempotency_key) > 512:
            raise ValueError("idempotency_key must be a non-empty string of at most 512 characters")
        return _sha(idempotency_key.encode("utf-8"))

    def _stage_path(self, operation_id: str) -> Path:
        return self.staging / f"{operation_id}.bin"

    def _operation_path(self, operation_id: str) -> Path:
        return self.operations / f"{operation_id}.json"

    def _validation_path(self, operation_id: str) -> Path:
        return self.validations / f"{operation_id}.json"

    def _commit_path(self, operation_id: str) -> Path:
        return self.commits / f"{operation_id}.json"

    def _object_path(self, content_sha256: str) -> Path:
        if not isinstance(content_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", content_sha256):
            raise StorageError("object SHA-256 is malformed")
        return self.objects / content_sha256[:2] / f"{content_sha256}.bin"

    def stage(
        self,
        *,
        idempotency_key: str,
        content: bytes,
        media_type: str,
        schema_version: str,
        producer_commit: str,
        producer_runtime: str,
    ) -> dict[str, Any]:
        if not isinstance(content, bytes):
            raise TypeError("content must be bytes")
        if not isinstance(media_type, str) or not media_type:
            raise ValueError("media_type must be a non-empty string")
        if not isinstance(schema_version, str) or not schema_version:
            raise ValueError("schema_version must be a non-empty string")
        if not isinstance(producer_commit, str) or not producer_commit:
            raise ValueError("producer_commit must be a non-empty string")
        if not isinstance(producer_runtime, str) or not producer_runtime:
            raise ValueError("producer_runtime must be a non-empty string")
        operation_id = self._operation_id(idempotency_key)
        content_hash = _sha(content)
        manifest = {
            "schema": STAGE_SCHEMA,
            "operation_id": operation_id,
            "idempotency_key_sha256": operation_id,
            "content_sha256": content_hash,
            "byte_length": len(content),
            "media_type": media_type,
            "schema_version": schema_version,
            "producer_commit": producer_commit,
            "producer_runtime": producer_runtime,
        }
        manifest_raw = canonicalize(manifest)
        operation_path = self._operation_path(operation_id)
        with ledger_lock(operation_path):
            if operation_path.exists():
                existing = _read_canonical(operation_path)
                if canonicalize(existing) != manifest_raw:
                    raise IdempotencyConflict("idempotency key was reused with different canonical inputs")
                staged = self._stage_path(operation_id)
                self._verify_bytes(staged, content_hash, len(content))
                return existing
            staged = self._stage_path(operation_id)
            if staged.exists():
                self._verify_bytes(staged, content_hash, len(content))
            else:
                _atomic_immutable(staged, content)
            self._verify_bytes(staged, content_hash, len(content))
            _atomic_immutable(operation_path, manifest_raw)
            return manifest

    def _verify_bytes(self, path: Path, expected_hash: str, expected_length: int) -> bytes:
        try:
            raw = path.read_bytes()
        except OSError as exc:
            raise StorageError(f"staged or committed object is missing: {path}") from exc
        if len(raw) != expected_length or _sha(raw) != expected_hash:
            raise StorageError(f"object byte length or SHA-256 mismatch: {path}")
        return raw

    def validate(
        self,
        *,
        operation_id: str,
        validator: Callable[[bytes], bool] | None = None,
        validator_id: str = "bytes-only/v1",
    ) -> dict[str, Any]:
        operation_id = _safe_name(operation_id, "operation_id")
        operation = _read_canonical(self._operation_path(operation_id))
        raw = self._verify_bytes(
            self._stage_path(operation_id), operation["content_sha256"], operation["byte_length"]
        )
        if validator is not None and validator(raw) is not True:
            raise StorageError("semantic object validator rejected staged bytes")
        if not isinstance(validator_id, str) or not validator_id:
            raise ValueError("validator_id must be a non-empty string")
        receipt = {
            "schema": VALIDATION_SCHEMA,
            "operation_id": operation_id,
            "content_sha256": operation["content_sha256"],
            "byte_length": operation["byte_length"],
            "schema_version": operation["schema_version"],
            "validator_id": validator_id,
            "validation_mode": "semantic" if validator is not None else "bytes_only",
            "validated": True,
        }
        path = self._validation_path(operation_id)
        with ledger_lock(path):
            _atomic_immutable(path, canonicalize(receipt))
            existing = _read_canonical(path)
            if existing != receipt:
                raise StorageError("validation receipt conflicts with prior immutable result")
            return existing

    def commit(self, *, operation_id: str) -> dict[str, Any]:
        operation_id = _safe_name(operation_id, "operation_id")
        operation = _read_canonical(self._operation_path(operation_id))
        validation_path = self._validation_path(operation_id)
        validation = _read_canonical(validation_path)
        if (validation.get("operation_id") != operation_id
                or validation.get("content_sha256") != operation["content_sha256"]
                or validation.get("validated") is not True):
            raise StorageError("a matching passing validation receipt is required before commit")
        staged = self._stage_path(operation_id)
        raw = self._verify_bytes(staged, operation["content_sha256"], operation["byte_length"])
        object_path = self._object_path(operation["content_sha256"])
        _atomic_immutable(object_path, raw)
        stored = self._verify_bytes(object_path, operation["content_sha256"], operation["byte_length"])
        if stored != raw:
            raise StorageError("read-back bytes differ from staged input")
        validation_raw = validation_path.read_bytes()
        receipt = {
            "schema": COMMIT_SCHEMA,
            "operation_id": operation_id,
            "content_sha256": operation["content_sha256"],
            "byte_length": operation["byte_length"],
            "object_key": str(object_path.relative_to(self.root)),
            "stage_manifest_sha256": _sha(self._operation_path(operation_id).read_bytes()),
            "validation_receipt_sha256": _sha(validation_raw),
            "committed": True,
        }
        path = self._commit_path(operation_id)
        with ledger_lock(path):
            _atomic_immutable(path, canonicalize(receipt))
            existing = _read_canonical(path)
            if existing != receipt:
                raise StorageError("commit receipt conflicts with prior immutable result")
            return existing

    def publish_pointer(
        self,
        *,
        name: str,
        operation_id: str,
        expected_generation: int,
    ) -> dict[str, Any]:
        name = _safe_name(name, "pointer name")
        operation_id = _safe_name(operation_id, "operation_id")
        if type(expected_generation) is not int or expected_generation < 0:
            raise ValueError("expected_generation must be a non-negative integer")
        operation = _read_canonical(self._operation_path(operation_id))
        commit = _read_canonical(self._commit_path(operation_id))
        if (commit.get("operation_id") != operation_id
                or commit.get("content_sha256") != operation.get("content_sha256")
                or commit.get("committed") is not True):
            raise StorageError("pointer publication requires a matching immutable commit receipt")
        object_path = self._object_path(commit["content_sha256"])
        self._verify_bytes(object_path, commit["content_sha256"], commit["byte_length"])
        pointer_path = self.pointers / f"{name}.json"
        publication_path = self.publications / f"{name}.{operation_id}.json"
        with ledger_lock(pointer_path):
            if publication_path.exists():
                existing = _read_canonical(publication_path)
                pointer = _read_canonical(pointer_path)
                if (pointer.get("last_operation_id") != operation_id
                        or existing.get("object_sha256") != commit["content_sha256"]):
                    raise StorageError("prior publication receipt conflicts with current pointer")
                return pointer
            if pointer_path.exists():
                current = self.read_pointer(name)
                generation = current.get("generation")
                # Recover a crash after the atomic pointer replacement but
                # before its immutable publication receipt was written.
                if (current.get("last_operation_id") == operation_id
                        and current.get("object_sha256") == commit["content_sha256"]):
                    recovered_receipt = {
                        "schema": "lottery.storage-publication/v1",
                        "pointer_name": name,
                        "generation": generation,
                        "object_sha256": commit["content_sha256"],
                        "operation_id": operation_id,
                        "previous_object_sha256": current.get("previous_object_sha256"),
                    }
                    _atomic_immutable(publication_path, canonicalize(recovered_receipt))
                    return current
            else:
                current = None
                generation = 0
            if generation != expected_generation:
                raise StalePointer(f"pointer generation is {generation}, expected {expected_generation}")
            new_pointer = {
                "schema": POINTER_SCHEMA,
                "name": name,
                "generation": generation + 1,
                "object_sha256": commit["content_sha256"],
                "commit_receipt_sha256": _sha(self._commit_path(operation_id).read_bytes()),
                "previous_object_sha256": current.get("object_sha256") if current else None,
                "last_operation_id": operation_id,
            }
            _atomic_replace(pointer_path, canonicalize(new_pointer))
            receipt = {
                "schema": "lottery.storage-publication/v1",
                "pointer_name": name,
                "generation": generation + 1,
                "object_sha256": commit["content_sha256"],
                "operation_id": operation_id,
                "previous_object_sha256": current.get("object_sha256") if current else None,
            }
            _atomic_immutable(publication_path, canonicalize(receipt))
            return new_pointer

    def read_pointer(self, name: str) -> dict[str, Any]:
        name = _safe_name(name, "pointer name")
        pointer = _read_canonical(self.pointers / f"{name}.json")
        if (pointer.get("schema") != POINTER_SCHEMA or pointer.get("name") != name
                or type(pointer.get("generation")) is not int or pointer["generation"] < 1):
            raise StorageError("pointer schema or generation is invalid")
        receipt_hash = pointer.get("commit_receipt_sha256")
        if not isinstance(receipt_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", receipt_hash):
            raise StorageError("pointer commit receipt digest is invalid")
        operation_id = _safe_name(pointer.get("last_operation_id"), "operation_id")
        commit_path = self._commit_path(operation_id)
        commit_raw = commit_path.read_bytes()
        commit = _read_canonical(commit_path)
        if (_sha(commit_raw) != receipt_hash
                or commit.get("operation_id") != operation_id
                or commit.get("content_sha256") != pointer["object_sha256"]
                or commit.get("committed") is not True
                or type(commit.get("byte_length")) is not int):
            raise StorageError("pointer does not resolve to its committed object")
        object_path = self._object_path(pointer.get("object_sha256"))
        self._verify_bytes(object_path, pointer["object_sha256"], commit["byte_length"])
        return pointer

    def reconcile(self) -> dict[str, Any]:
        """Read-only inventory; it never adopts, deletes, repairs or rewrites objects."""
        report: dict[str, Any] = {
            "schema": "lottery.storage-reconciliation/v1",
            "staged_without_validation": [],
            "validated_without_commit": [],
            "committed_unreferenced": [],
            "dangling_pointers": [],
            "corrupt_objects": [],
            "pointer_count": 0,
            "object_count": 0,
            "read_only": True,
        }
        referenced: set[str] = set()
        commits_by_hash: dict[str, list[str]] = {}
        for path in sorted(self.commits.glob("*.json")):
            receipt = _read_canonical(path)
            digest = receipt.get("content_sha256")
            if isinstance(digest, str):
                commits_by_hash.setdefault(digest, []).append(path.stem)
                try:
                    object_path = self._object_path(digest)
                    self._verify_bytes(object_path, digest, receipt["byte_length"])
                except (StorageError, OSError, KeyError):
                    report["corrupt_objects"].append(digest)
        for path in sorted(self.operations.glob("*.json")):
            operation_id = path.stem
            if not self._validation_path(operation_id).exists():
                report["staged_without_validation"].append(operation_id)
            elif not self._commit_path(operation_id).exists():
                report["validated_without_commit"].append(operation_id)
        for path in sorted(self.pointers.glob("*.json")):
            report["pointer_count"] += 1
            try:
                pointer = self.read_pointer(path.stem)
                referenced.add(pointer["object_sha256"])
            except (StorageError, OSError, KeyError):
                report["dangling_pointers"].append(path.stem)
        for digest, operation_ids in commits_by_hash.items():
            if digest not in referenced:
                report["committed_unreferenced"].extend(operation_ids)
        report["object_count"] = sum(1 for _ in self.objects.glob("*/*.bin"))
        for path in self.objects.glob("*/*.bin"):
            if path.stem not in commits_by_hash:
                report["corrupt_objects"].append(path.stem)
        for key in ("staged_without_validation", "validated_without_commit",
                    "committed_unreferenced", "dangling_pointers", "corrupt_objects"):
            report[key] = sorted(set(report[key]))
        return report
