#!/usr/bin/env python3
"""Independently audit the official DLT raw ZIP against its processed snapshot.

This proves archive integrity, parser reproducibility, and recorded HTTPS endpoint
metadata. It deliberately does not claim cryptographic source authenticity.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import urllib.parse
import zipfile
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lottery.ingest import PARSER_VERSION, _add_draw, _parse_page  # noqa: E402

COLLECTOR_VERSION = "raw-snapshot-collector/1.0.0"


class AuditError(ValueError):
    pass


def _json(raw: bytes, label: str) -> Any:
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise AuditError(f"{label}: invalid UTF-8 JSON") from exc


def _utc(value: Any, label: str) -> datetime:
    if not isinstance(value, str):
        raise AuditError(f"{label}: timestamp missing")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise AuditError(f"{label}: invalid timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise AuditError(f"{label}: timestamp must include a timezone")
    return parsed


def _load_jsonl(raw: bytes, label: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for number, line in enumerate(raw.splitlines(), 1):
        if not line.strip():
            raise AuditError(f"{label}:{number}: blank JSONL row")
        value = _json(line, f"{label}:{number}")
        if not isinstance(value, dict):
            raise AuditError(f"{label}:{number}: row must be an object")
        rows.append(value)
    return rows


def audit_archive(
    archive_path: Path,
    processed_path: Path,
    processed_manifest_path: Path,
    crosswalk_path: Path | None = None,
    expected_pages: int = 30,
    expected_records: int = 2949,
) -> dict[str, Any]:
    archive_bytes = archive_path.read_bytes()
    archive_sha256 = hashlib.sha256(archive_bytes).hexdigest()
    processed_bytes = processed_path.read_bytes()
    processed_sha256 = hashlib.sha256(processed_bytes).hexdigest()
    processed_manifest = _json(processed_manifest_path.read_bytes(), str(processed_manifest_path))
    if not isinstance(processed_manifest, dict):
        raise AuditError("processed manifest must be an object")

    with zipfile.ZipFile(archive_path) as archive:
        bad_member = archive.testzip()
        if bad_member is not None:
            raise AuditError(f"ZIP CRC/readability failure: {bad_member}")
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise AuditError("ZIP contains duplicate entry names")
        for name in names:
            path = PurePosixPath(name)
            if path.is_absolute() or "\\" in name or any(part in ("", ".", "..") for part in path.parts):
                if name != "dlt_official_raw/":
                    raise AuditError(f"unsafe ZIP member path: {name!r}")

        root = "dlt_official_raw/"
        collection_names = [n for n in names if re.fullmatch(r"dlt_official_raw/collection-[^/]+\.manifest\.json", n)]
        page_names = sorted(n for n in names if re.fullmatch(r"dlt_official_raw/page-\d{5}-[0-9a-f]{12}\.json", n))
        sidecar_names = sorted(n for n in names if re.fullmatch(r"dlt_official_raw/page-\d{5}-[0-9a-f]{12}\.manifest\.json", n))
        if collection_names.__len__() != 1 or len(page_names) != expected_pages or len(sidecar_names) != expected_pages:
            raise AuditError(
                f"archive inventory mismatch: collection={len(collection_names)}, "
                f"raw_pages={len(page_names)}, sidecars={len(sidecar_names)}"
            )
        expected_names = {root, *collection_names, *page_names, *sidecar_names}
        if set(names) != expected_names:
            unexpected = sorted(set(names) - expected_names)
            raise AuditError(f"unexpected or unclassified ZIP entries: {unexpected[:5]}")

        collection_raw = archive.read(collection_names[0])
        collection = _json(collection_raw, "collection manifest")
        if not isinstance(collection, dict):
            raise AuditError("collection manifest must be an object")
        if collection.get("total_pages") != expected_pages or collection.get("total_records") != expected_records:
            raise AuditError("collection manifest totals do not match the audited snapshot")

        sidecars_by_page: dict[int, tuple[str, dict[str, Any]]] = {}
        raw_hashes: list[str] = []
        parsed_rows: dict[str, Any] = {}
        retrieved: list[datetime] = []
        run_ids: set[str] = set()
        page_record_counts: list[int] = []
        for name in page_names:
            match = re.fullmatch(r"dlt_official_raw/page-(\d{5})-([0-9a-f]{12})\.json", name)
            assert match is not None
            page_no, short_hash = int(match.group(1)), match.group(1) and match.group(2)
            sidecar_name = name[:-5] + ".manifest.json"
            if sidecar_name not in sidecar_names:
                raise AuditError(f"page {page_no}: sidecar missing")
            raw = archive.read(name)
            digest = hashlib.sha256(raw).hexdigest()
            if digest[:12] != short_hash:
                raise AuditError(f"page {page_no}: filename digest prefix mismatch")
            sidecar = _json(archive.read(sidecar_name), sidecar_name)
            if not isinstance(sidecar, dict):
                raise AuditError(f"page {page_no}: sidecar must be an object")
            expected_sidecar = {
                "source": "Sporttery public historical draw API",
                "http_status": 200,
                "sha256": digest,
                "raw_file": name.rsplit("/", 1)[-1],
                "page_no": page_no,
                "parser_version": COLLECTOR_VERSION,
            }
            mismatches = {
                key: {"actual": sidecar.get(key), "expected": expected}
                for key, expected in expected_sidecar.items()
                if sidecar.get(key) != expected
            }
            if mismatches:
                raise AuditError(f"page {page_no}: sidecar identity/hash/status mismatch: {mismatches}")
            source_url = sidecar.get("url")
            parsed_url = urllib.parse.urlsplit(source_url) if isinstance(source_url, str) else None
            query = urllib.parse.parse_qs(parsed_url.query) if parsed_url else {}
            if (
                parsed_url is None or parsed_url.scheme != "https"
                or parsed_url.hostname != "webapi.sporttery.cn"
                or parsed_url.path != "/gateway/lottery/getHistoryPageListV1.qry"
                or query.get("gameNo") != ["85"]
                or query.get("pageNo") != [str(page_no)]
            ):
                raise AuditError(f"page {page_no}: non-canonical official endpoint metadata")
            content_type = sidecar.get("content_type")
            if not isinstance(content_type, str) or "json" not in content_type.lower():
                raise AuditError(f"page {page_no}: content type is not JSON")
            retrieved.append(_utc(sidecar.get("retrieved_at"), f"page {page_no}"))
            run_id = sidecar.get("run_id")
            if not isinstance(run_id, str) or not run_id:
                raise AuditError(f"page {page_no}: run_id missing")
            run_ids.add(run_id)
            rows = _parse_page(raw, page_no, "sha256:" + digest)
            page_record_counts.append(len(rows))
            for row in rows:
                _add_draw(parsed_rows, row)
            raw_hashes.append(digest)
            sidecars_by_page[page_no] = (sidecar_name, sidecar)

        if set(sidecars_by_page) != set(range(1, expected_pages + 1)):
            raise AuditError("page numbers are not a complete 1..N sequence")
        if len(run_ids) != 1:
            raise AuditError("sidecars do not belong to one collection run")
        if len(retrieved) != expected_pages or (max(retrieved) - min(retrieved)).total_seconds() > 600:
            raise AuditError("retrieval timestamps are incomplete or span more than ten minutes")
        if sum(page_record_counts) != expected_records or len(parsed_rows) != expected_records:
            raise AuditError("raw page record total or unique draw count mismatch")
        if page_record_counts != [100] * (expected_pages - 1) + [expected_records - 100 * (expected_pages - 1)]:
            raise AuditError("page-size/terminal-page coverage mismatch")

    expected_hashes = processed_manifest.get("snapshot_sha256")
    if expected_hashes != raw_hashes:
        raise AuditError("processed manifest snapshot hash inventory differs from raw ZIP")
    snapshots = processed_manifest.get("snapshots")
    if not isinstance(snapshots, list) or len(snapshots) != expected_pages:
        raise AuditError("processed manifest snapshot inventory is incomplete")
    for page_no, (item, digest) in enumerate(zip(snapshots, raw_hashes), 1):
        if (
            not isinstance(item, dict) or item.get("sha256") != digest
            or item.get("provenance_complete") is not True
            or item.get("records") != page_record_counts[page_no - 1]
        ):
            raise AuditError(f"processed manifest page {page_no} does not match raw evidence")
    if processed_manifest.get("snapshot_count") != expected_pages:
        raise AuditError("processed manifest snapshot_count mismatch")
    if processed_manifest.get("trust_status") != "manifest_complete_not_officially_authenticated":
        raise AuditError("processed manifest trust status was improperly promoted")

    ordered = sorted(parsed_rows.values(), key=lambda row: (row.draw_date, row.draw_id))
    rebuilt = b"".join(
        (json.dumps(asdict(row), ensure_ascii=False) + "\n").encode("utf-8")
        for row in ordered
    )
    if rebuilt != processed_bytes:
        raise AuditError("processed JSONL is not byte-for-byte reproducible from raw ZIP")
    if hashlib.sha256(rebuilt).hexdigest() != processed_manifest.get("output_sha256"):
        raise AuditError("processed manifest output_sha256 mismatch")
    if processed_manifest.get("validation", {}).get("records") != expected_records:
        raise AuditError("processed manifest validation record count mismatch")

    crosswalk_report = None
    if crosswalk_path is not None:
        registry = _json(crosswalk_path.read_bytes(), str(crosswalk_path))
        records = registry.get("records") if isinstance(registry, dict) else None
        if not isinstance(records, list):
            raise AuditError("crosswalk registry records missing")
        by_id = {row.draw_id: row for row in ordered}
        mismatches: list[str] = []
        for record in records:
            draw_id = str(record.get("draw_id", ""))
            row = by_id.get(draw_id)
            if row is None:
                mismatches.append(f"{draw_id}: absent from canonical snapshot")
                continue
            pairs = (
                ("draw_date", row.draw_date),
                ("front_numbers", row.front_numbers),
                ("back_numbers", row.back_numbers),
                ("front_draw_order", row.front_draw_order),
                ("back_draw_order", row.back_draw_order),
                ("equipment_set", row.source_equipment_count),
            )
            for field, actual in pairs:
                if record.get(field) != actual:
                    mismatches.append(f"{draw_id}: {field} mismatch")
        if mismatches:
            raise AuditError("crosswalk mismatch: " + "; ".join(mismatches[:8]))
        crosswalk_report = {
            "records": len(records),
            "all_match_canonical_snapshot": True,
            "source_capture_status": registry.get("source_capture_status"),
            "sample_design": registry.get("sample_design"),
        }

    return {
        "schema": "lottery.g1-official-snapshot-audit/v1",
        "archive": {"path": str(archive_path), "bytes": len(archive_bytes), "sha256": archive_sha256},
        "collection_manifest_sha256": hashlib.sha256(collection_raw).hexdigest(),
        "collection_manifest_keys": sorted(collection),
        "collection_manifest": collection,
        "raw_pages": expected_pages,
        "sidecars": expected_pages,
        "raw_records": sum(page_record_counts),
        "unique_draws": len(parsed_rows),
        "page_record_counts": page_record_counts,
        "retrieval_start_utc": min(retrieved).astimezone(timezone.utc).isoformat(),
        "retrieval_end_utc": max(retrieved).astimezone(timezone.utc).isoformat(),
        "run_id_count": len(run_ids),
        "collector_version": COLLECTOR_VERSION,
        "importer_parser_version": PARSER_VERSION,
        "raw_snapshot_hashes_match_processed_manifest": True,
        "processed_rebuild_byte_identical": True,
        "processed_sha256": processed_sha256,
        "crosswalk": crosswalk_report,
        "trust_status": "manifest_complete_not_officially_authenticated",
        "authenticity_limit": "HTTPS endpoint metadata and byte integrity do not prove source producer identity or physical draw authenticity.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, default=Path("data/incoming/dlt_official_raw.zip"))
    parser.add_argument("--processed", type=Path, default=Path("data/processed/draws-20261118.jsonl"))
    parser.add_argument("--processed-manifest", type=Path, default=Path("data/processed/draws-20261118.jsonl.manifest.json"))
    parser.add_argument("--crosswalks", type=Path, default=Path("data/metadata_verification/official_order_crosswalks_20261118.json"))
    parser.add_argument("--output", type=Path, default=Path("official-snapshot-source-audit.json"))
    args = parser.parse_args()
    try:
        report = audit_archive(args.archive, args.processed, args.processed_manifest, args.crosswalks)
    except (AuditError, OSError, zipfile.BadZipFile, KeyError, TypeError) as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
