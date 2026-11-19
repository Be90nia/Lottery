"""Fail-closed append-only publication of a complete candidate draw snapshot.

This module produces a reviewed candidate file only. It does not authenticate
the upstream source or mutate the canonical dataset.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any

from .validate import validate_jsonl, validate_records


class PublicationError(ValueError):
    """Raised when a candidate snapshot cannot safely extend current history."""


SEMANTIC_FIELDS = (
    "draw_date", "front_numbers", "back_numbers", "front_draw_order",
    "back_draw_order", "source_unsort_drawresult", "source_equipment_count",
)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        raise
    rows = []
    for number, line in enumerate(lines, 1):
        if not line.strip():
            raise PublicationError(f"{path}: blank line {number} is forbidden")
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise PublicationError(f"{path}: invalid JSON on line {number}") from exc
        if not isinstance(row, dict):
            raise PublicationError(f"{path}: line {number} must be an object")
        rows.append(row)
    return rows


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    temp = Path(name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    except Exception:
        temp.unlink(missing_ok=True)
        raise


def _canonical_rows(rows: list[dict[str, Any]]) -> bytes:
    return "".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
        for row in rows
    ).encode("utf-8")


def reconcile_append_only(
    current_path: Path,
    candidate_path: Path,
    candidate_manifest_path: Path,
    output_path: Path,
    receipt_path: Path,
) -> dict[str, Any]:
    paths = [p.resolve() for p in (
        current_path, candidate_path, candidate_manifest_path, output_path, receipt_path
    )]
    if len(set(paths)) != len(paths):
        raise PublicationError("current, candidate, manifest, output, and receipt paths must be distinct")
    if not current_path.is_file() or not candidate_path.is_file():
        raise PublicationError("current and candidate JSONL files must both exist")

    current_validation = validate_jsonl(current_path)
    candidate_validation = validate_jsonl(candidate_path)
    current = _read_jsonl(current_path)
    candidate = _read_jsonl(candidate_path)
    try:
        manifest = json.loads(candidate_manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PublicationError("candidate manifest is missing or invalid JSON") from exc
    if not isinstance(manifest, dict):
        raise PublicationError("candidate manifest must be an object")
    if manifest.get("output_sha256") != _sha(candidate_path):
        raise PublicationError("candidate manifest output_sha256 does not match candidate bytes")
    if manifest.get("validation") != candidate_validation:
        raise PublicationError("candidate manifest validation summary does not match candidate")
    if manifest.get("provenance_complete") is not True:
        raise PublicationError("candidate snapshot provenance is incomplete")
    if manifest.get("trust_status") != "manifest_complete_not_officially_authenticated":
        raise PublicationError("candidate trust status is not the expected unverified state")
    if type(manifest.get("snapshot_count")) is not int or manifest["snapshot_count"] < 1:
        raise PublicationError("candidate manifest must reference at least one raw snapshot")
    snapshots = manifest.get("snapshots")
    if not isinstance(snapshots, list) or len(snapshots) != manifest["snapshot_count"]:
        raise PublicationError("candidate manifest snapshot inventory is incomplete")
    for item in snapshots:
        if (not isinstance(item, dict)
                or item.get("provenance_complete") is not True
                or not isinstance(item.get("sha256"), str)
                or len(item["sha256"]) != 64):
            raise PublicationError("candidate manifest contains an invalid snapshot entry")

    current_by_id = {row["draw_id"]: row for row in current}
    candidate_by_id = {row["draw_id"]: row for row in candidate}
    missing = sorted(set(current_by_id) - set(candidate_by_id))
    if missing:
        raise PublicationError(f"candidate is not a full snapshot; missing existing draw IDs: {missing[:10]}")

    for draw_id, old in current_by_id.items():
        new = candidate_by_id[draw_id]
        for field in SEMANTIC_FIELDS:
            if old.get(field) != new.get(field):
                raise PublicationError(f"historical correction or metadata conflict for {draw_id}: {field}")

    current_last = max((row["draw_date"], row["draw_id"]) for row in current)
    additions = [
        row for row in candidate
        if row["draw_id"] not in current_by_id
    ]
    for row in additions:
        if (row["draw_date"], row["draw_id"]) <= current_last:
            raise PublicationError(
                f"new draw {row['draw_id']} is not strictly later than current history"
            )

    # Preserve current rows byte-semantically (including their original source_id)
    # and append only genuinely new candidate rows.
    additions.sort(key=lambda row: (row["draw_date"], row["draw_id"]))
    merged = current + additions
    merged_validation = validate_records(merged)
    current_sha = _sha(current_path)
    candidate_sha = _sha(candidate_path)
    if not additions:
        receipt = {
            "schema_version": 1,
            "status": "no_new_draws",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "current_sha256": current_sha,
            "candidate_sha256": candidate_sha,
            "output_written": False,
            "canonical_dataset_modified": False,
            "added_draw_count": 0,
            "current_validation": current_validation,
            "candidate_validation": candidate_validation,
        }
    else:
        if output_path.exists():
            raise PublicationError("output_path already exists; refusing to overwrite a prior candidate")
        payload = _canonical_rows(merged)
        _atomic_write(output_path, payload)
        output_sha = hashlib.sha256(payload).hexdigest()
        receipt = {
            "schema_version": 1,
            "status": "append_candidate_created",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "current_sha256": current_sha,
            "candidate_sha256": candidate_sha,
            "output_sha256": output_sha,
            "output_path": str(output_path),
            "output_written": True,
            "canonical_dataset_modified": False,
            "added_draw_count": len(additions),
            "added_draw_ids": [row["draw_id"] for row in additions],
            "merged_validation": merged_validation,
            "trust_status": "manifest_complete_not_officially_authenticated",
            "promotion_authorized": False,
        }
        output_manifest = {
            "schema_version": 1,
            "status": "append_candidate_untrusted",
            "created_at": receipt["created_at"],
            "input_current_sha256": current_sha,
            "input_candidate_sha256": candidate_sha,
            "output_sha256": output_sha,
            "validation": merged_validation,
            "trust_status": "manifest_complete_not_officially_authenticated",
            "promotion_authorized": False,
        }
        _atomic_write(
            output_path.with_suffix(output_path.suffix + ".manifest.json"),
            (json.dumps(output_manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8"),
        )
    _atomic_write(
        receipt_path,
        (json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8"),
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
            args.current, args.candidate, args.candidate_manifest, args.output, args.receipt
        )
    except (OSError, ValueError) as exc:
        parser.exit(1, f"PUBLICATION_REJECTED: {exc}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
