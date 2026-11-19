"""Fail-closed append-only publication of a complete candidate draw snapshot.

This module produces a reviewed candidate file only. It does not authenticate
the upstream source or mutate the canonical dataset.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any
from urllib.parse import parse_qs, urlsplit

from .ingest import IngestionError, PARSER_VERSION, _add_draw, _parse_page
from .validate import validate_records


class PublicationError(ValueError):
    """Raised when a candidate snapshot cannot safely extend current history."""


SEMANTIC_FIELDS = (
    "draw_date", "front_numbers", "back_numbers", "front_draw_order",
    "back_draw_order", "source_unsort_drawresult", "source_equipment_count",
)


def _read_jsonl(path: Path) -> tuple[list[dict[str, Any]], bytes, dict[str, Any]]:
    try:
        raw = path.read_bytes()
        lines = raw.decode("utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        raise PublicationError(f"{path}: cannot read UTF-8 JSONL: {exc}") from exc
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
    try:
        validation = validate_records(rows)
    except ValueError as exc:
        raise PublicationError(f"{path}: dataset validation failed: {exc}") from exc
    return rows, raw, validation

def _atomic_write_new(path: Path, content: bytes) -> None:
    """Atomically create a new evidence file without ever replacing an existing path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    temp = Path(name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        # A same-directory hard link is an atomic no-replace publish operation.
        os.link(temp, path)
    except Exception:
        temp.unlink(missing_ok=True)
        raise
    temp.unlink(missing_ok=True)


def _verify_raw_snapshots(
    snapshots_dir: Path,
    manifest: dict[str, Any],
    snapshots: list[dict[str, Any]],
    candidate: list[dict[str, Any]],
    completeness: dict[str, Any],
) -> None:
    if not snapshots_dir.is_dir():
        raise PublicationError("raw snapshot directory does not exist")
    run_id = manifest.get("run_id")
    if (not isinstance(run_id, str) or len(run_id) != 32
            or any(char not in "0123456789abcdef" for char in run_id)):
        raise PublicationError("candidate manifest fetch run ID is invalid")
    reconstructed: dict[str, Any] = {}
    raw_record_count = 0
    for item in snapshots:
        raw_name = item["raw_file"]
        sidecar_name = item.get("sidecar_manifest")
        if (Path(raw_name).name != raw_name or raw_name in ("", ".", "..")
                or not isinstance(sidecar_name, str)
                or Path(sidecar_name).name != sidecar_name):
            raise PublicationError("snapshot manifest contains an unsafe raw/sidecar filename")
        raw_path = snapshots_dir / raw_name
        sidecar_path = snapshots_dir / sidecar_name
        if (raw_path.resolve().parent != snapshots_dir.resolve()
                or sidecar_path.resolve().parent != snapshots_dir.resolve()
                or not raw_path.is_file() or not sidecar_path.is_file()):
            raise PublicationError("raw snapshot or sidecar is missing/outside the declared run directory")
        raw = raw_path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        if digest != item["sha256"] or len(raw) != item.get("bytes"):
            raise PublicationError(f"raw snapshot hash/size mismatch: {raw_name}")
        try:
            sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PublicationError(f"raw snapshot sidecar is invalid: {sidecar_name}") from exc
        if not isinstance(sidecar, dict):
            raise PublicationError(f"raw snapshot sidecar must be an object: {sidecar_name}")
        if (sidecar.get("sha256") != digest or sidecar.get("raw_file") != raw_name
                or sidecar.get("page_no") != item["page_no"]
                or sidecar.get("run_id") != run_id
                or sidecar.get("http_status") != 200
                or sidecar.get("parser_version") != PARSER_VERSION
                or not isinstance(sidecar.get("content_type"), str)
                or "application/json" not in sidecar["content_type"].lower()):
            raise PublicationError(f"raw snapshot sidecar does not match its page object: {sidecar_name}")
        retrieved_at = sidecar.get("retrieved_at")
        try:
            parsed_timestamp = datetime.fromisoformat(retrieved_at)
        except (TypeError, ValueError) as exc:
            raise PublicationError(f"raw snapshot retrieval timestamp is invalid: {sidecar_name}") from exc
        if parsed_timestamp.tzinfo is None or parsed_timestamp.utcoffset() is None:
            raise PublicationError(f"raw snapshot retrieval timestamp lacks timezone: {sidecar_name}")
        source_url = sidecar.get("url")
        parsed_url = urlsplit(source_url) if isinstance(source_url, str) else None
        query = parse_qs(parsed_url.query) if parsed_url else {}
        if (parsed_url is None or parsed_url.scheme != "https"
                or parsed_url.hostname != "webapi.sporttery.cn"
                or parsed_url.path != "/gateway/lottery/getHistoryPageListV1.qry"
                or parsed_url.port not in (None, 443)
                or parsed_url.username is not None or parsed_url.password is not None
                or parsed_url.fragment
                or query.get("gameNo") != ["85"] or query.get("provinceId") != ["0"]
                or query.get("isVerify") != ["1"]
                or query.get("pageNo") != [str(item["page_no"])]
                or query.get("pageSize") != [str(completeness["page_size"])]):
            raise PublicationError(f"raw snapshot URL is not the exact approved page request: {sidecar_name}")
        try:
            parsed_rows = _parse_page(raw, item["page_no"], f"sha256:{digest}")
        except IngestionError as exc:
            raise PublicationError(f"raw snapshot parser rejected {raw_name}: {exc}") from exc
        if len(parsed_rows) != item["records"]:
            raise PublicationError(f"raw snapshot record count mismatch: {raw_name}")
        raw_record_count += len(parsed_rows)
        for row in parsed_rows:
            try:
                _add_draw(reconstructed, row)
            except IngestionError as exc:
                raise PublicationError(f"raw snapshots conflict on draw {row.draw_id}: {exc}") from exc

    candidate_by_id = {row["draw_id"]: row for row in candidate}
    if raw_record_count != len(candidate) or set(reconstructed) != set(candidate_by_id):
        raise PublicationError("raw snapshot records do not reconstruct the candidate draw inventory")
    for draw_id, parsed_row in reconstructed.items():
        parsed_record = asdict(parsed_row)
        candidate_row = candidate_by_id[draw_id]
        for field in SEMANTIC_FIELDS:
            if parsed_record.get(field) != candidate_row.get(field):
                raise PublicationError(f"candidate does not match archived raw snapshot for {draw_id}: {field}")


def _next_draw_id(previous: str, candidate: str) -> bool:
    if (not previous.isdigit() or not candidate.isdigit()
            or len(previous) != 5 or len(candidate) != 5):
        return False
    previous_year, previous_sequence = int(previous[:2]), int(previous[2:])
    candidate_year, candidate_sequence = int(candidate[:2]), int(candidate[2:])
    if candidate_year == previous_year:
        return candidate_sequence == previous_sequence + 1
    return (candidate_year == previous_year + 1
            and candidate_sequence == 1 and previous_sequence >= 100)


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
    snapshots_dir: Path,
) -> dict[str, Any]:
    output_manifest_path = output_path.with_suffix(output_path.suffix + ".manifest.json")
    paths = [p.resolve() for p in (
        current_path, candidate_path, candidate_manifest_path, output_path,
        output_manifest_path, receipt_path
    )]
    if len(set(paths)) != len(paths):
        raise PublicationError("current, candidate, manifest, output, and receipt paths must be distinct")
    if not current_path.is_file() or not candidate_path.is_file():
        raise PublicationError("current and candidate JSONL files must both exist")
    if receipt_path.exists():
        raise PublicationError("receipt_path already exists; refusing to overwrite prior evidence")

    current, current_raw, current_validation = _read_jsonl(current_path)
    candidate, candidate_raw, candidate_validation = _read_jsonl(candidate_path)
    try:
        manifest = json.loads(candidate_manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PublicationError("candidate manifest is missing or invalid JSON") from exc
    if not isinstance(manifest, dict):
        raise PublicationError("candidate manifest must be an object")
    if manifest.get("output_sha256") != hashlib.sha256(candidate_raw).hexdigest():
        raise PublicationError("candidate manifest output_sha256 does not match candidate bytes")
    if manifest.get("validation") != candidate_validation:
        raise PublicationError("candidate manifest validation summary does not match candidate")
    if manifest.get("provenance_complete") is not True:
        raise PublicationError("candidate snapshot provenance is incomplete")
    if manifest.get("trust_status") != "manifest_complete_not_officially_authenticated":
        raise PublicationError("candidate trust status is not the expected unverified state")
    if manifest.get("source_completeness_verified") is not True:
        raise PublicationError("source pagination completeness is unverified; refusing to append a partial snapshot")
    completeness = manifest.get("completeness_evidence")
    if not isinstance(completeness, dict) or completeness.get("method") != "official_pagination_metadata":
        raise PublicationError("official pagination completeness evidence is missing")
    if (type(completeness.get("reported_total_records")) is not int
            or completeness["reported_total_records"] != len(candidate)
            or type(completeness.get("reported_total_pages")) is not int
            or completeness["reported_total_pages"] < 1
            or type(completeness.get("page_size")) is not int
            or not 1 <= completeness["page_size"] <= 100):
        raise PublicationError("official pagination totals do not match the candidate snapshot")
    if type(manifest.get("snapshot_count")) is not int or manifest["snapshot_count"] < 1:
        raise PublicationError("candidate manifest must reference at least one raw snapshot")
    snapshots = manifest.get("snapshots")
    if not isinstance(snapshots, list) or len(snapshots) != manifest["snapshot_count"]:
        raise PublicationError("candidate manifest snapshot inventory is incomplete")
    for item in snapshots:
        if (not isinstance(item, dict)
                or item.get("provenance_complete") is not True
                or not isinstance(item.get("sha256"), str)
                or len(item["sha256"]) != 64
                or any(ch not in "0123456789abcdef" for ch in item["sha256"])
                or not isinstance(item.get("raw_file"), str)
                or not item["raw_file"]
                or type(item.get("page_no")) is not int or item["page_no"] < 1
                or type(item.get("records")) is not int or item["records"] < 0):
            raise PublicationError("candidate manifest contains an invalid snapshot entry")
    observed_pages = [item.get("page_no") for item in snapshots]
    expected_pages = list(range(1, len(snapshots) + 1))
    if observed_pages != expected_pages:
        raise PublicationError("candidate snapshot page inventory is incomplete or out of order")
    data_pages = [item for item in snapshots if type(item.get("records")) is int and item["records"] > 0]
    terminal_empty = bool(snapshots and snapshots[-1].get("records") == 0)
    if len(data_pages) != completeness["reported_total_pages"]:
        raise PublicationError("reported page count does not match observed non-empty pages")
    expected_snapshot_count = completeness["reported_total_pages"] + (1 if terminal_empty else 0)
    if len(snapshots) != expected_snapshot_count:
        raise PublicationError("snapshot inventory contains missing or unexpected terminal pages")
    if any(item.get("run_id") != manifest.get("run_id") for item in snapshots):
        raise PublicationError("snapshot inventory mixes fetch runs")
    _verify_raw_snapshots(snapshots_dir, manifest, snapshots, candidate, completeness)

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
    previous_draw_id = current_last[1]
    for row in additions:
        if row["draw_date"] <= current_last[0]:
            raise PublicationError(
                f"new draw {row['draw_id']} is not strictly later than current history"
            )
        if not _next_draw_id(previous_draw_id, row["draw_id"]):
            raise PublicationError(
                f"draw ID sequence has a gap or regression: {previous_draw_id} -> {row['draw_id']}"
            )
        previous_draw_id = row["draw_id"]

    # Preserve current rows semantically (including their original source_id)
    # and append only genuinely new candidate rows.
    additions.sort(key=lambda row: (row["draw_date"], row["draw_id"]))
    merged = current + additions
    merged_validation = validate_records(merged)
    current_sha = hashlib.sha256(current_raw).hexdigest()
    candidate_sha = hashlib.sha256(candidate_raw).hexdigest()
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
        if output_path.exists() or output_manifest_path.exists():
            raise PublicationError("output or output manifest already exists; refusing to overwrite a prior candidate")
        payload = _canonical_rows(merged)
        _atomic_write_new(output_path, payload)
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
        _atomic_write_new(
            output_manifest_path,
            (json.dumps(output_manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8"),
        )
    _atomic_write_new(
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
    parser.add_argument("--snapshots-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = reconcile_append_only(
            args.current, args.candidate, args.candidate_manifest, args.output, args.receipt,
            args.snapshots_dir,
        )
    except (OSError, ValueError) as exc:
        parser.exit(1, f"PUBLICATION_REJECTED: {exc}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
