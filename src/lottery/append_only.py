"""Fail-closed append-only reconciliation of a validated full draw snapshot."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .validate import DatasetValidationError, validate_records


class AppendOnlyError(ValueError):
    """Candidate history cannot safely extend the current dataset."""


def _read(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open(encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, 1):
            if not line.strip():
                raise AppendOnlyError(f"{path}: blank line {line_no}")
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise AppendOnlyError(f"{path}: invalid JSON line {line_no}") from exc
            if not isinstance(row, dict):
                raise AppendOnlyError(f"{path}: line {line_no} is not an object")
            rows.append(row)
    try:
        validate_records(rows)
    except DatasetValidationError as exc:
        raise AppendOnlyError(f"{path}: {exc}") from exc
    return rows


def _semantic(row: dict[str, Any]) -> tuple[Any, ...]:
    return (
        row["draw_id"], row["draw_date"],
        tuple(row["front_numbers"]), tuple(row["back_numbers"]),
        tuple(row.get("front_draw_order") or ()),
        tuple(row.get("back_draw_order") or ()),
        row.get("source_unsort_drawresult"),
        row.get("source_equipment_count"),
    )


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_write_new(path: Path, content: bytes) -> None:
    """Publish a fully fsynced file atomically without replacing an existing path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=path.name + ".", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        # A hard link publishes the completed inode atomically and, unlike
        # os.replace(), fails if another writer already created the destination.
        try:
            os.link(temporary, path)
        except FileExistsError as exc:
            raise AppendOnlyError(f"refusing to overwrite existing artifact: {path}") from exc
    finally:
        temporary.unlink(missing_ok=True)


def reconcile_append_only(
    current_path: Path,
    candidate_path: Path,
    candidate_manifest_path: Path,
    output_path: Path,
    receipt_path: Path,
) -> dict[str, Any]:
    protected = [current_path, candidate_path, candidate_manifest_path]
    destinations = [output_path, receipt_path]
    resolved_inputs = {path.resolve() for path in protected}
    resolved_outputs = [path.resolve() for path in destinations]
    if (
        len(set(resolved_outputs)) != len(resolved_outputs)
        or any(path in resolved_inputs for path in resolved_outputs)
    ):
        raise AppendOnlyError(
            "output and receipt paths must be distinct from each other and every input"
        )
    if receipt_path.exists():
        raise AppendOnlyError(f"refusing to overwrite existing receipt: {receipt_path}")

    current = _read(current_path)
    candidate = _read(candidate_path)
    try:
        manifest = json.loads(candidate_manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AppendOnlyError(f"candidate manifest unreadable: {exc}") from exc
    if not isinstance(manifest, dict):
        raise AppendOnlyError("candidate manifest must be an object")
    if manifest.get("output_sha256") != _hash(candidate_path):
        raise AppendOnlyError("candidate manifest output_sha256 does not match candidate bytes")
    if (
        manifest.get("trust_status") != "manifest_complete_not_officially_authenticated"
        or manifest.get("provenance_complete") is not True
    ):
        raise AppendOnlyError(
            "candidate must have complete official-source manifests; authenticity remains unverified"
        )
    validation_manifest = manifest.get("validation")
    if (
        not isinstance(validation_manifest, dict)
        or validation_manifest.get("records") != len(candidate)
    ):
        raise AppendOnlyError(
            "candidate manifest validation record count is missing or inconsistent"
        )

    old = {row["draw_id"]: row for row in current}
    new = {row["draw_id"]: row for row in candidate}
    missing = sorted(set(old) - set(new))
    if missing:
        raise AppendOnlyError(
            f"candidate is not a full snapshot; missing existing draw IDs: {missing[:10]}"
        )
    changed = sorted(
        draw_id for draw_id in old if _semantic(old[draw_id]) != _semantic(new[draw_id])
    )
    if changed:
        raise AppendOnlyError(
            "historical correction or metadata conflict for draw IDs "
            f"{changed[:10]}; refusing silent replacement"
        )

    latest = max(current, key=lambda row: (row["draw_date"], row["draw_id"]))
    additions = sorted(
        (row for row in candidate if row["draw_id"] not in old),
        key=lambda row: (row["draw_date"], row["draw_id"]),
    )
    boundary = (latest["draw_date"], latest["draw_id"])
    for row in additions:
        if (row["draw_date"], row["draw_id"]) <= boundary:
            raise AppendOnlyError(
                f"new draw {row['draw_id']} is not strictly after current chronology boundary"
            )

    if additions:
        if output_path.exists():
            raise AppendOnlyError(f"refusing to overwrite existing publication: {output_path}")
        merged = current + additions
        try:
            validation = validate_records(merged)
        except DatasetValidationError as exc:
            raise AppendOnlyError(f"merged dataset invalid: {exc}") from exc
        rendered = "".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
            for row in merged
        ).encode("utf-8")
        _atomic_write_new(output_path, rendered)
        status = "appended"
        output_sha = _hash(output_path)
    else:
        validation = validate_records(current)
        status = "no_new_draws"
        output_sha = _hash(current_path)

    receipt = {
        "schema_version": 1,
        "status": status,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "current_sha256": _hash(current_path),
        "candidate_sha256": _hash(candidate_path),
        "candidate_manifest_sha256": _hash(candidate_manifest_path),
        "candidate_snapshot_count": manifest.get("snapshot_count"),
        "candidate_trust_status": manifest["trust_status"],
        "output_sha256": output_sha,
        "previous_records": len(current),
        "candidate_records": len(candidate),
        "appended_records": len(additions),
        "appended_draw_ids": [row["draw_id"] for row in additions],
        "validation": validation,
        "publication": "new local artifact only; no model training or promotion",
    }
    _atomic_write_new(
        receipt_path,
        (json.dumps(receipt, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
    )
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--current", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--candidate-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = reconcile_append_only(
            args.current, args.candidate, args.candidate_manifest,
            args.output, args.receipt,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, AppendOnlyError, DatasetValidationError) as exc:
        print(f"DRAW_APPEND_ONLY_FAILED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
