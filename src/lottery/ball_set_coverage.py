"""Reproducible evidence coverage accounting; never adjudicates equipment regimes."""
from __future__ import annotations

import csv
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any

from .ball_set_evidence import (
    ALLOWED_HOSTS, OBSERVATION_SCHEMA, PARSER_VERSION, BallSetEvidenceError,
    parse_announcement,
)
from .ledger_lock import ledger_lock
from .validate import DatasetValidationError, validate_records


class BallSetCoverageError(ValueError):
    """Raised when inventory or evidence cannot be reproduced safely."""


def _sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical(value: dict[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def _read_jsonl(path: Path, *, optional: bool = False) -> tuple[list[dict[str, Any]], bytes]:
    if optional and not path.exists():
        return [], b""
    raw = path.read_bytes()
    rows = []
    try:
        for line_no, line in enumerate(raw.decode("utf-8").splitlines(), 1):
            if not line.strip():
                raise BallSetCoverageError(f"{path}: blank line {line_no}")
            rows.append(json.loads(line))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BallSetCoverageError(f"{path}: invalid JSONL: {exc}") from exc
    return rows, raw


def _safe_raw_path(archive_dir: Path, reference: str) -> Path:
    if not isinstance(reference, str) or not reference:
        raise BallSetCoverageError("raw_object_ref is missing")
    root = archive_dir.resolve()
    path = (root / reference).resolve()
    if not path.is_relative_to(root):
        raise BallSetCoverageError("raw_object_ref escapes archive directory")
    return path


def _verify_observation(
    observation: dict[str, Any], inventory_row: dict[str, Any], archive_dir: Path,
) -> tuple[str, int | None, str | None]:
    source = observation.get("source")
    if not isinstance(source, dict) or source.get("authority_class") not in ("A1", "A2"):
        return "non_primary_only", None, None
    if observation.get("observation_status") in (
        "conflict", "source_revision_requires_review", "draw_mismatch",
        "source_authority_unverified", "parse_error",
    ):
        return observation["observation_status"], None, source.get("final_url")
    try:
        raw_path = _safe_raw_path(archive_dir, source.get("raw_object_ref"))
        raw = raw_path.read_bytes()
        digest = _sha_bytes(raw)
        if digest != source.get("body_sha256") or len(raw) != source.get("body_byte_length"):
            return "raw_evidence_invalid", None, source.get("final_url")
        manifest_path = _safe_raw_path(archive_dir, source.get("manifest_object_ref"))
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for key in ("requested_url", "final_url", "retrieved_at_utc", "http_status",
                    "content_type", "body_byte_length", "body_sha256", "raw_object_ref"):
            if manifest.get(key) != source.get(key):
                return "raw_evidence_invalid", None, source.get("final_url")
        identity = {
            "draw_id": observation.get("draw_id"),
            "source_url": source.get("final_url"),
            "body_sha256": source.get("body_sha256"),
        }
        expected_id = _sha_bytes(json.dumps(
            identity, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
        ).encode("utf-8"))
        if observation.get("observation_id") != expected_id:
            return "raw_evidence_invalid", None, source.get("final_url")
        final_url = source.get("final_url")
        if not isinstance(final_url, str):
            return "parse_error", None, None
        parsed = parse_announcement(raw, final_url, source.get("content_type", ""))
    except (OSError, BallSetEvidenceError, ValueError, json.JSONDecodeError) as exc:
        return "parse_error", None, source.get("final_url")
    if parsed.draw_id != observation.get("draw_id") or parsed.draw_date != observation.get("draw_date"):
        return "draw_mismatch", None, source.get("final_url")
    if parsed.draw_id != inventory_row["draw_id"] or parsed.draw_date != inventory_row["draw_date"]:
        return "draw_mismatch", None, source.get("final_url")
    parser = observation.get("parser")
    if not isinstance(parser, dict) or parser.get("matched_text") != parsed.matched_text:
        return "parse_error", None, source.get("final_url")
    locator = parser.get("evidence_locator")
    if parsed.matched_text is not None:
        if (not isinstance(locator, dict)
                or locator.get("text_character_start") != parsed.evidence_start
                or locator.get("text_character_end") != parsed.evidence_end):
            return "parse_error", None, source.get("final_url")
    if parsed.observation_status == "conflict":
        return "conflict", None, final_url
    if parsed.observation_status == "missing_label":
        return "missing_label", None, final_url
    if parsed.observation_status == "unsupported_label":
        return "unsupported_label", None, final_url
    if parsed.reported_set_index not in (1, 2, 3):
        return "parse_error", None, final_url
    return "primary_verified", parsed.reported_set_index, final_url


def _atomic_write(path: Path, data: bytes, protected: set[Path]) -> None:
    resolved = path.resolve()
    if resolved in protected:
        raise BallSetCoverageError(f"output path would overwrite an input: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def build_ball_set_coverage(
    draw_inventory_path: Path, ledger_path: Path, archive_dir: Path, *,
    code_commit: str = "local",
) -> dict[str, Any]:
    inventory, inventory_raw = _read_jsonl(draw_inventory_path)
    try:
        validation = validate_records(inventory)
    except DatasetValidationError as exc:
        raise BallSetCoverageError(f"draw inventory is invalid: {exc}") from exc
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    with ledger_lock(ledger_path):
        observations, ledger_raw = _read_jsonl(ledger_path, optional=True)
    if any(not isinstance(item, dict) or item.get("schema_version") != OBSERVATION_SCHEMA for item in observations):
        raise BallSetCoverageError("observation ledger contains an unsupported record")
    observation_ids = [item.get("observation_id") for item in observations]
    if len(observation_ids) != len(set(observation_ids)):
        raise BallSetCoverageError("observation ledger contains duplicate observation IDs")
    inventory_by_id = {row["draw_id"]: row for row in inventory}
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in observations:
        grouped.setdefault(item.get("draw_id"), []).append(item)

    per_draw: list[dict[str, Any]] = []
    verified_rows: list[dict[str, Any]] = []
    raw_verified = 0
    raw_invalid = 0
    parser_versions = set()
    source_domains = set()
    status_counts: dict[str, int] = {}
    for row in inventory:
        draw_id = row["draw_id"]
        group = grouped.get(draw_id, [])
        evaluated: list[tuple[str, int | None, str | None]] = []
        for observation in group:
            parser = observation.get("parser")
            if isinstance(parser, dict) and parser.get("version"):
                parser_versions.add(parser["version"])
            source = observation.get("source", {})
            final_url = source.get("final_url") if isinstance(source, dict) else None
            if isinstance(final_url, str):
                from urllib.parse import urlsplit
                source_domains.add(urlsplit(final_url).hostname or "")
            result = _verify_observation(observation, row, archive_dir)
            evaluated.append(result)
            if result[0] == "primary_verified":
                raw_verified += 1
            elif result[0] in ("raw_evidence_invalid", "parse_error"):
                raw_invalid += 1

        states = [item[0] for item in evaluated]
        labels = {item[1] for item in evaluated if item[0] == "primary_verified"}
        if "source_revision_requires_review" in states:
            status, set_index = "source_revision_requires_review", None
        elif "conflict" in states or len(labels) > 1:
            status, set_index = "conflicting_official_sources", None
        elif "draw_mismatch" in states:
            status, set_index = "draw_mismatch", None
        elif "raw_evidence_invalid" in states or "parse_error" in states:
            status, set_index = "parse_error", None
        elif labels:
            status, set_index = "primary_verified", next(iter(labels))
        elif "unsupported_label" in states:
            status, set_index = "unsupported_label", None
        elif "missing_label" in states:
            status, set_index = "missing_official_label", None
        elif "official_label_pending_inventory" in states:
            status, set_index = "official_label_pending_inventory", None
        elif group:
            status, set_index = "non_primary_only", None
        else:
            status, set_index = "unobserved", None
        status_counts[status] = status_counts.get(status, 0) + 1
        source_urls = sorted({item[2] for item in evaluated if item[2]})
        row_report = {
            "draw_id": draw_id, "draw_date": row["draw_date"],
            "reported_set_index": set_index, "status": status,
            "observation_ids": sorted(item["observation_id"] for item in group),
            "source_urls": source_urls,
            "equipment_regime_id": None, "physical_ball_set_id": None,
            "prior_same_key_verified_count": None, "eligible": False,
            "exclusion_reason": "regime_unresolved" if status == "primary_verified" else status,
        }
        per_draw.append(row_report)
        if status == "primary_verified":
            verified_rows.append(row_report)

    out_of_inventory = sum(1 for item in observations if item.get("draw_id") not in inventory_by_id)
    years: dict[str, dict[str, Any]] = {}
    for item in per_draw:
        year = item["draw_date"][:4]
        bucket = years.setdefault(year, {
            "year": year, "inventory_draws": 0, "primary_verified": 0,
            "missing_official_label": 0, "unobserved": 0,
            "conflicting_official_sources": 0, "source_revision_requires_review": 0,
            "draw_mismatch": 0, "parse_error": 0, "unsupported_label": 0,
            "set_1": 0, "set_2": 0, "set_3": 0,
        })
        bucket["inventory_draws"] += 1
        if item["status"] in bucket:
            bucket[item["status"]] += 1
        if item["status"] == "primary_verified":
            bucket[f"set_{item['reported_set_index']}"] += 1

    per_set: dict[str, Any] = {}
    inventory_positions = {row["draw_id"]: i for i, row in enumerate(inventory)}
    for set_index in (1, 2, 3):
        matched = [row for row in verified_rows if row["reported_set_index"] == set_index]
        positions = sorted(inventory_positions[row["draw_id"]] for row in matched)
        gaps = [right - left for left, right in zip(positions, positions[1:])]
        date_gaps = []
        for left, right in zip(matched, matched[1:]):
            date_gaps.append((datetime.fromisoformat(right["draw_date"]) -
                              datetime.fromisoformat(left["draw_date"])).days)
        per_set[str(set_index)] = {
            "primary_verified_draws": len(matched),
            "first_draw_id": matched[0]["draw_id"] if matched else None,
            "first_draw_date": matched[0]["draw_date"] if matched else None,
            "last_draw_id": matched[-1]["draw_id"] if matched else None,
            "last_draw_date": matched[-1]["draw_date"] if matched else None,
            "calendar_years": sorted({row["draw_date"][:4] for row in matched}),
            "largest_gap_inventory_positions": max(gaps) if gaps else None,
            "longest_missing_inventory_run_between_verified": max((gap - 1 for gap in gaps), default=None),
            "largest_gap_elapsed_days": max(date_gaps) if date_gaps else None,
            "expected_draws": None,
            "coverage_rate": None,
            "denominator_status": "unknown_regime_boundary",
            "eligible_rolling_origin_targets": 0,
        }

    payload = {
        "schema_version": "lottery.ball-set-coverage/v1",
        "inventory_sha256": _sha_bytes(inventory_raw),
        "inventory_trust_status": "candidate_unverified",
        "inventory_validation": validation,
        "observation_ledger_sha256": _sha_bytes(ledger_raw),
        "observation_count": len(observations),
        "out_of_inventory_observation_count": out_of_inventory,
        "parser_versions": sorted(parser_versions | {PARSER_VERSION}),
        "source_domains": sorted(domain for domain in source_domains if domain),
        "summary": {
            "inventory_draws": len(inventory),
            "observed_draws": sum(1 for row in per_draw if row["status"] != "unobserved"),
            "primary_verified_draws": len(verified_rows),
            "primary_verified_coverage_rate": len(verified_rows) / len(inventory),
            "status_counts": status_counts,
            "set_index_counts": {str(i): per_set[str(i)]["primary_verified_draws"] for i in (1, 2, 3)},
            "raw_observation_objects_verified": raw_verified,
            "raw_observation_objects_invalid": raw_invalid,
            "regime_assignment_count": 0,
            "regime_assignment_coverage_rate": 0.0,
            "eligible_slot_targets": 0,
            "training_eligibility": "blocked_regime_unresolved",
        },
        "per_set": per_set,
        "by_year": [years[key] for key in sorted(years)],
        "per_draw": per_draw,
        "code_commit": code_commit,
    }
    report_hash = _sha_bytes(_canonical(payload))
    return {
        **payload, "report_sha256": report_hash,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    }


def write_ball_set_coverage_report(
    report: dict[str, Any], *, output_json: Path, output_csv: Path, output_markdown: Path,
    protected_paths: set[Path],
) -> None:
    outputs = [output_json, output_csv, output_markdown]
    resolved = [path.resolve() for path in outputs]
    if len(set(resolved)) != len(resolved) or any(path in protected_paths for path in resolved):
        raise BallSetCoverageError("coverage output paths must be distinct from each other and all inputs")
    json_bytes = (json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    columns = [
        "draw_id", "draw_date", "reported_set_index", "status", "observation_ids",
        "source_urls", "equipment_regime_id", "physical_ball_set_id",
        "prior_same_key_verified_count", "eligible", "exclusion_reason",
    ]
    from io import StringIO
    stream = StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    for row in report["per_draw"]:
        item = dict(row)
        item["observation_ids"] = ";".join(item["observation_ids"])
        item["source_urls"] = ";".join(item["source_urls"])
        writer.writerow(item)
    csv_bytes = stream.getvalue().encode("utf-8")
    summary = report["summary"]
    lines = [
        "# Ball-set evidence coverage",
        "",
        f"- Report SHA-256: `{report['report_sha256']}`",
        f"- Inventory SHA-256: `{report['inventory_sha256']}`",
        f"- Inventory trust: `{report['inventory_trust_status']}`",
        f"- Observation ledger SHA-256: `{report['observation_ledger_sha256']}`",
        f"- Generated: {report['generated_at_utc']}",
        "",
        "## Summary",
        "",
        f"- Inventory draws: {summary['inventory_draws']}",
        f"- Observed draws: {summary['observed_draws']}",
        f"- Primary-verified labels: {summary['primary_verified_draws']} ({summary['primary_verified_coverage_rate']:.2%})",
        f"- Per-set counts: {summary['set_index_counts']}",
        f"- Out-of-inventory observations: {report['out_of_inventory_observation_count']}",
        f"- Raw evidence objects verified/invalid: {summary['raw_observation_objects_verified']}/{summary['raw_observation_objects_invalid']}",
        f"- Regime assignments: {summary['regime_assignment_count']}",
        f"- Eligible set-conditioned targets: {summary['eligible_slot_targets']}",
        "",
        "## Per-year coverage",
        "",
        "| Year | Inventory | Verified | Missing label | Unobserved | Conflicts | Set 1 | Set 2 | Set 3 |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in report["by_year"]:
        lines.append(
            f"| {row['year']} | {row['inventory_draws']} | {row['primary_verified']} | "
            f"{row['missing_official_label']} | {row['unobserved']} | "
            f"{row['conflicting_official_sources']} | {row['set_1']} | {row['set_2']} | {row['set_3']} |"
        )
    lines.extend([
        "",
        "## Training eligibility",
        "",
        "All equipment regime and physical identity fields remain null. The two-set to three-set transition and identity continuity are unresolved. Every target has exclusion reason `regime_unresolved` and remains ineligible, regardless of label count. This report is evidence accounting, not a predictive or causal finding.",
        "",
    ])
    md_bytes = ("\n".join(lines)).encode("utf-8")
    _atomic_write(output_json, json_bytes, protected_paths)
    _atomic_write(output_csv, csv_bytes, protected_paths)
    _atomic_write(output_markdown, md_bytes, protected_paths)


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--draw-inventory", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--archive-dir", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-csv", type=Path, required=True)
    parser.add_argument("--output-markdown", type=Path, required=True)
    parser.add_argument("--code-commit", default=os.environ.get("GITHUB_SHA", "local"))
    args = parser.parse_args()
    try:
        report = build_ball_set_coverage(
            args.draw_inventory, args.ledger, args.archive_dir, code_commit=args.code_commit
        )
        protected = {args.draw_inventory.resolve(), args.ledger.resolve()}
        write_ball_set_coverage_report(
            report, output_json=args.output_json, output_csv=args.output_csv,
            output_markdown=args.output_markdown, protected_paths=protected,
        )
        print(json.dumps({
            "report_sha256": report["report_sha256"],
            "inventory_draws": report["summary"]["inventory_draws"],
            "primary_verified_draws": report["summary"]["primary_verified_draws"],
            "eligible_slot_targets": report["summary"]["eligible_slot_targets"],
        }, ensure_ascii=False, sort_keys=True))
        return 0
    except (OSError, ValueError, BallSetCoverageError) as exc:
        print(f"BALL_SET_COVERAGE_FAILED: {exc}", file=__import__("sys").stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
