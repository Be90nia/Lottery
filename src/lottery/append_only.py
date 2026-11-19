"""Fail-closed append-only reconciliation of a validated full draw snapshot."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import urllib.parse
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .ingest import IngestionError, _parse_page
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


def _json_pointer(payload: Any, pointer: str) -> Any:
    if not isinstance(pointer, str) or not pointer.startswith("/") or pointer == "/":
        raise AppendOnlyError("pagination metadata JSON pointer is invalid")
    current = payload
    for raw_token in pointer[1:].split("/"):
        token = raw_token.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict) and token in current:
            current = current[token]
        elif isinstance(current, list) and token.isdigit() and int(token) < len(current):
            current = current[int(token)]
        else:
            raise AppendOnlyError(f"pagination metadata pointer does not resolve: {pointer}")
    return current


def _verify_source_completeness_attestation(
    manifest: dict[str, Any],
    candidate: list[dict[str, Any]],
    snapshots_dir: Path,
) -> dict[str, Any]:
    attestation = manifest.get("source_completeness_attestation")
    required_attestation_keys = {
        "schema", "source_total_records", "source_total_pages", "page_size",
        "metadata_page_no", "total_records_pointer", "total_pages_pointer", "pages",
    }
    if not isinstance(attestation, dict) or set(attestation) != required_attestation_keys:
        raise AppendOnlyError(
            "source pagination completeness attestation is missing or has an invalid schema"
        )
    if attestation.get("schema") != "sporttery-pagination-attestation-v1":
        raise AppendOnlyError("unsupported source pagination attestation schema")
    if type(attestation.get("source_total_records")) is not int or attestation["source_total_records"] < 1:
        raise AppendOnlyError("source total record count must be a positive integer")
    if type(attestation.get("source_total_pages")) is not int or attestation["source_total_pages"] < 1:
        raise AppendOnlyError("source total page count must be a positive integer")
    if type(attestation.get("page_size")) is not int or not 1 <= attestation["page_size"] <= 100:
        raise AppendOnlyError("attested page size must be an integer in 1..100")
    if type(attestation.get("metadata_page_no")) is not int or attestation.get("metadata_page_no") != 1:
        raise AppendOnlyError("pagination totals must be attested from source page 1")
    total_records = attestation["source_total_records"]
    total_pages = attestation["source_total_pages"]
    page_size = attestation["page_size"]
    if total_pages != (total_records + page_size - 1) // page_size:
        raise AppendOnlyError("source total pages do not reconcile with total records and page size")
    if manifest.get("source_completeness_verified") is not True:
        raise AppendOnlyError(
            "source pagination completeness is not independently verified; refusing publication"
        )
    if manifest.get("provenance_complete") is not True:
        raise AppendOnlyError("source pagination attestation requires complete page provenance")
    if not snapshots_dir.is_dir():
        raise AppendOnlyError("raw snapshot directory is missing")

    pages = attestation.get("pages")
    snapshots = manifest.get("snapshots")
    if (not isinstance(pages, list) or len(pages) != total_pages
            or not isinstance(snapshots, list) or len(snapshots) != total_pages):
        raise AppendOnlyError("attested page inventory does not match source total pages")
    if type(manifest.get("snapshot_count")) is not int or manifest.get("snapshot_count") != total_pages:
        raise AppendOnlyError("candidate snapshot_count does not match source total pages")
    if manifest.get("snapshot_sha256") != [page.get("sha256") for page in pages if isinstance(page, dict)]:
        raise AppendOnlyError("candidate snapshot SHA inventory does not match pagination attestation")

    source_rows: list[dict[str, Any]] = []
    source_ids_by_draw: dict[str, str] = {}
    seen_draw_ids: set[str] = set()
    run_ids: set[str] = set()
    verified_pages: list[dict[str, Any]] = []
    metadata_payload: dict[str, Any] | None = None
    api_path = "/gateway/lottery/getHistoryPageListV1.qry"

    for expected_page_no, (page, snapshot) in enumerate(zip(pages, snapshots), 1):
        if (not isinstance(page, dict)
                or set(page) != {"page_no", "raw_file", "sha256", "records"}
                or type(page.get("page_no")) is not int
                or page["page_no"] != expected_page_no):
            raise AppendOnlyError("attested page numbers must be contiguous from page 1")
        if not isinstance(snapshot, dict):
            raise AppendOnlyError("snapshot manifest entry must be an object")
        raw_file = page.get("raw_file")
        digest = page.get("sha256")
        records = page.get("records")
        if (not isinstance(raw_file, str) or Path(raw_file).name != raw_file
                or not raw_file.endswith(".json")
                or not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)
                or type(records) is not int or records < 1):
            raise AppendOnlyError(f"page {expected_page_no}: attestation entry is invalid")
        if (type(snapshot.get("page_no")) is not int or snapshot.get("page_no") != expected_page_no
                or snapshot.get("raw_file") != raw_file
                or snapshot.get("sha256") != digest
                or type(snapshot.get("records")) is not int or snapshot.get("records") != records
                or type(snapshot.get("bytes")) is not int
                or snapshot.get("sidecar_manifest") != f"{Path(raw_file).stem}.manifest.json"
                or not isinstance(snapshot.get("run_id"), str) or not snapshot.get("run_id")
                or snapshot.get("provenance_complete") is not True):
            raise AppendOnlyError(f"page {expected_page_no}: snapshot manifest differs from attestation")

        raw_path = snapshots_dir / raw_file
        sidecar_path = snapshots_dir / f"{Path(raw_file).stem}.manifest.json"
        if not raw_path.is_file() or not sidecar_path.is_file():
            raise AppendOnlyError(f"page {expected_page_no}: raw snapshot or sidecar is missing")
        raw = raw_path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != digest:
            raise AppendOnlyError(f"page {expected_page_no}: raw snapshot SHA-256 mismatch")
        try:
            sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
            payload = json.loads(raw.decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise AppendOnlyError(f"page {expected_page_no}: raw snapshot or sidecar is invalid JSON") from exc
        if not isinstance(sidecar, dict) or not isinstance(payload, dict):
            raise AppendOnlyError(f"page {expected_page_no}: raw snapshot and sidecar must be objects")
        source_url = sidecar.get("url")
        parsed = urllib.parse.urlsplit(source_url) if isinstance(source_url, str) else None
        query = urllib.parse.parse_qs(parsed.query) if parsed is not None else {}
        retrieved_at = sidecar.get("retrieved_at")
        timestamp_valid = False
        if isinstance(retrieved_at, str):
            try:
                retrieved = datetime.fromisoformat(retrieved_at.replace("Z", "+00:00"))
                timestamp_valid = retrieved.tzinfo is not None and retrieved.utcoffset() is not None
            except ValueError:
                timestamp_valid = False
        if (sidecar.get("source") != "Sporttery public historical draw API"
                or sidecar.get("raw_file") != raw_file
                or not isinstance(sidecar.get("content_type"), str)
                or "json" not in sidecar.get("content_type", "").lower()
                or sidecar.get("sha256") != digest
                or type(sidecar.get("bytes")) is not int or sidecar.get("bytes") != len(raw)
                or snapshot.get("bytes") != len(raw)
                or snapshot.get("run_id") != sidecar.get("run_id")
                or type(sidecar.get("http_status")) is not int or sidecar.get("http_status") != 200
                or type(sidecar.get("page_no")) is not int or sidecar.get("page_no") != expected_page_no
                or not isinstance(sidecar.get("run_id"), str) or not sidecar.get("run_id")
                or not timestamp_valid
                or parsed is None or parsed.scheme != "https"
                or parsed.hostname != "webapi.sporttery.cn" or parsed.path != api_path
                or query.get("gameNo") != ["85"] or query.get("provinceId") != ["0"]
                or query.get("isVerify") != ["1"]
                or query.get("pageNo") != [str(expected_page_no)]
                or query.get("pageSize") != [str(page_size)]):
            raise AppendOnlyError(f"page {expected_page_no}: official-source sidecar provenance is invalid")
        run_ids.add(sidecar["run_id"])

        value = payload.get("value")
        if not isinstance(value, dict) or not isinstance(value.get("list"), list):
            raise AppendOnlyError(f"page {expected_page_no}: raw response has no value.list array")
        if len(value["list"]) != records:
            raise AppendOnlyError(f"page {expected_page_no}: attested record count differs from raw page")
        expected_records = (
            page_size if expected_page_no < total_pages
            else total_records - page_size * (total_pages - 1)
        )
        if records != expected_records:
            raise AppendOnlyError(f"page {expected_page_no}: page record count violates source pagination totals")
        if expected_page_no == 1:
            metadata_payload = payload
        try:
            parsed_rows = _parse_page(raw, expected_page_no, f"sha256:{digest}")
        except IngestionError as exc:
            raise AppendOnlyError(f"page {expected_page_no}: source page parsing failed: {exc}") from exc
        for parsed_row in parsed_rows:
            row_dict = {
                "draw_id": parsed_row.draw_id,
                "draw_date": parsed_row.draw_date,
                "front_numbers": parsed_row.front_numbers,
                "back_numbers": parsed_row.back_numbers,
                "front_draw_order": parsed_row.front_draw_order,
                "back_draw_order": parsed_row.back_draw_order,
                "source_unsort_drawresult": parsed_row.source_unsort_drawresult,
                "source_equipment_count": parsed_row.source_equipment_count,
            }
            if parsed_row.draw_id in seen_draw_ids:
                raise AppendOnlyError(f"duplicate draw ID across source pages: {parsed_row.draw_id}")
            seen_draw_ids.add(parsed_row.draw_id)
            source_ids_by_draw[parsed_row.draw_id] = f"sha256:{digest}"
            source_rows.append(row_dict)
        verified_pages.append({"page_no": expected_page_no, "sha256": digest, "records": records})

    if len(run_ids) != 1:
        raise AppendOnlyError("all source pages must belong to one immutable fetch run")
    if len(source_rows) != total_records or len(candidate) != total_records:
        raise AppendOnlyError("source total records do not match parsed pages and candidate rows")
    if any(row.get("source_id") != source_ids_by_draw.get(row["draw_id"]) for row in candidate):
        raise AppendOnlyError("candidate source_id does not reference the raw page that contains each draw")
    if metadata_payload is None:
        raise AppendOnlyError("source page 1 metadata is missing")
    if (type(_json_pointer(metadata_payload, attestation["total_records_pointer"])) is not int
            or _json_pointer(metadata_payload, attestation["total_records_pointer"]) != total_records
            or type(_json_pointer(metadata_payload, attestation["total_pages_pointer"])) is not int
            or _json_pointer(metadata_payload, attestation["total_pages_pointer"]) != total_pages):
        raise AppendOnlyError("source page 1 pagination metadata does not match attested totals")

    source_rows.sort(key=lambda row: (row["draw_date"], row["draw_id"]))
    if [_semantic(row) for row in source_rows] != [_semantic(row) for row in candidate]:
        raise AppendOnlyError("candidate rows do not exactly reconcile to the attested raw source pages")

    return {
        "schema": attestation["schema"],
        "source_total_records": total_records,
        "source_total_pages": total_pages,
        "page_size": page_size,
        "verified_page_sha256": [page["sha256"] for page in verified_pages],
        "attestation_sha256": hashlib.sha256(
            json.dumps(attestation, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
    }


def reconcile_append_only(
    current_path: Path,
    candidate_path: Path,
    candidate_manifest_path: Path,
    output_path: Path,
    receipt_path: Path,
    snapshots_dir: Path,
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
    snapshot_root = snapshots_dir.resolve()
    if any(path.is_relative_to(snapshot_root) for path in resolved_outputs):
        raise AppendOnlyError("publication outputs must not be placed inside the raw snapshot directory")

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
    source_attestation_receipt = _verify_source_completeness_attestation(
        manifest, candidate, snapshots_dir
    )
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
        "source_completeness_attestation": source_attestation_receipt,
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
    parser.add_argument("--snapshots-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = reconcile_append_only(
            args.current, args.candidate, args.candidate_manifest,
            args.output, args.receipt, args.snapshots_dir,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, AppendOnlyError, DatasetValidationError) as exc:
        print(f"DRAW_APPEND_ONLY_FAILED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
