"""Build an evidence-bound view keyed by source-reported set index.

This view deliberately does not assign equipment regimes or physical ball identities.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .ball_set_coverage import BallSetCoverageError, build_ball_set_coverage
from .ingest import _atomic_write_new
from .validate import DatasetValidationError, validate_records


class ReportedSetIndexError(ValueError):
    pass


PILOT_PROTOCOL_VERSION = "reported-set-index-pilot-v1"
PILOT_EXPECTED_SET_COUNTS = {"1": 360, "2": 347, "3": 360}
PILOT_EXPECTED_RECORD_COUNT = 1067
PILOT_EXPECTED_FIRST_DRAW = "19101"
PILOT_EXPECTED_LAST_DRAW = "26131"


def _canonical(value: dict[str, Any]) -> bytes:
    return json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def build_reported_set_index_view(
    inventory_path: Path,
    coverage_path: Path,
    ledger_path: Path,
    archive_dir: Path,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    inventory_raw = inventory_path.read_bytes()
    ledger_raw = ledger_path.read_bytes()
    try:
        inventory = [
            json.loads(line)
            for line in inventory_raw.decode("utf-8").splitlines()
            if line.strip()
        ]
        coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReportedSetIndexError(f"inventory or coverage report is invalid JSON: {exc}") from exc
    try:
        validate_records(inventory)
    except DatasetValidationError as exc:
        raise ReportedSetIndexError(f"draw inventory is invalid: {exc}") from exc

    if not isinstance(coverage, dict) or coverage.get("schema_version") != "lottery.ball-set-coverage/v1":
        raise ReportedSetIndexError("unsupported ball-set coverage report schema")
    report_hash = coverage.get("report_sha256")
    payload = {
        key: value for key, value in coverage.items()
        if key not in {"report_sha256", "generated_at_utc"}
    }
    computed_report_hash = _sha(_canonical(payload))
    if not isinstance(report_hash, str) or report_hash != computed_report_hash:
        raise ReportedSetIndexError("coverage report SHA-256 does not match its contents")
    inventory_sha = _sha(inventory_raw)
    ledger_sha = _sha(ledger_raw)
    if coverage.get("inventory_sha256") != inventory_sha:
        raise ReportedSetIndexError("coverage report is bound to a different draw inventory")
    if coverage.get("observation_ledger_sha256") != ledger_sha:
        raise ReportedSetIndexError("coverage report is bound to a different observation ledger")

    # Rebuild the coverage from the exact ledger and raw archive. This replays
    # the hash chain and reparses every referenced raw announcement.
    try:
        rebuilt = build_ball_set_coverage(
            inventory_path,
            ledger_path,
            archive_dir,
            code_commit=coverage.get("code_commit", "local"),
        )
    except (OSError, ValueError, BallSetCoverageError) as exc:
        raise ReportedSetIndexError(f"raw evidence replay failed: {exc}") from exc
    if rebuilt.get("report_sha256") != report_hash:
        raise ReportedSetIndexError("coverage report does not match replayed raw evidence")

    summary = coverage.get("summary")
    per_draw = coverage.get("per_draw")
    if not isinstance(summary, dict) or not isinstance(per_draw, list):
        raise ReportedSetIndexError("coverage report is missing summary or per_draw inventory")
    if summary.get("inventory_draws") != len(inventory) or len(per_draw) != len(inventory):
        raise ReportedSetIndexError("coverage report does not cover the complete pinned inventory")
    if (summary.get("training_eligibility") != "blocked_regime_unresolved"
            or summary.get("regime_assignment_count") != 0
            or summary.get("eligible_slot_targets") != 0):
        raise ReportedSetIndexError("coverage report unexpectedly activates regime or physical-slot eligibility")
    if coverage.get("inventory_trust_status") != "candidate_unverified":
        raise ReportedSetIndexError("unexpected inventory trust status")

    inventory_by_id = {row["draw_id"]: row for row in inventory}
    seen: set[str] = set()
    view_rows: list[dict[str, Any]] = []
    set_counts = {"1": 0, "2": 0, "3": 0}
    for evidence in per_draw:
        if not isinstance(evidence, dict):
            raise ReportedSetIndexError("per_draw entry must be an object")
        draw_id = evidence.get("draw_id")
        draw = inventory_by_id.get(draw_id)
        if draw is None or draw_id in seen:
            raise ReportedSetIndexError(f"coverage draw ID is missing, duplicated, or outside inventory: {draw_id!r}")
        seen.add(draw_id)
        if evidence.get("draw_date") != draw["draw_date"]:
            raise ReportedSetIndexError(f"coverage date differs from inventory for draw {draw_id}")
        if evidence.get("status") != "primary_verified":
            continue
        set_index = evidence.get("reported_set_index")
        if type(set_index) is not int or set_index not in (1, 2, 3):
            raise ReportedSetIndexError(f"verified draw {draw_id} has an invalid reported set index")
        if (evidence.get("eligible") is not False
                or evidence.get("exclusion_reason") != "regime_unresolved"
                or evidence.get("equipment_regime_id") is not None
                or evidence.get("physical_ball_set_id") is not None):
            raise ReportedSetIndexError(f"verified draw {draw_id} has an unexpected regime/identity assignment")
        observation_ids = evidence.get("observation_ids")
        source_urls = evidence.get("source_urls")
        if (not isinstance(observation_ids, list) or not observation_ids
                or not all(isinstance(item, str) and item for item in observation_ids)
                or not isinstance(source_urls, list) or not source_urls
                or not all(isinstance(item, str) and item.startswith("https://") for item in source_urls)):
            raise ReportedSetIndexError(f"verified draw {draw_id} is missing evidence references")

        set_counts[str(set_index)] += 1
        view_rows.append({
            "draw_id": draw_id,
            "draw_date": draw["draw_date"],
            "front_numbers": draw["front_numbers"],
            "back_numbers": draw["back_numbers"],
            "source_id": draw["source_id"],
            "reported_set_index": set_index,
            "evidence_status": "primary_verified",
            "observation_ids": observation_ids,
            "source_urls": source_urls,
            "inventory_sha256": inventory_sha,
            "coverage_report_sha256": report_hash,
            "observation_ledger_sha256": ledger_sha,
            "equipment_regime_id": None,
            "physical_ball_set_id": None,
            "eligible_for_reported_index_pilot": True,
            "eligible_for_physical_model": False,
            "training_eligibility": "blocked_regime_unresolved",
            "model_scope": "reported_set_index_only_not_physical_identity",
        })

    if len(seen) != len(inventory):
        raise ReportedSetIndexError("coverage report omits one or more inventory draw IDs")
    if len(view_rows) != summary.get("primary_verified_draws"):
        raise ReportedSetIndexError("primary_verified count differs from the derived view")
    if set_counts != summary.get("set_index_counts"):
        raise ReportedSetIndexError("set-index counts differ from the coverage summary")
    if (set_counts != PILOT_EXPECTED_SET_COUNTS
            or len(view_rows) != PILOT_EXPECTED_RECORD_COUNT):
        raise ReportedSetIndexError(
            "reported-index counts differ from the frozen pilot preregistration; version the protocol before evaluation"
        )

    view_rows.sort(key=lambda row: (row["draw_date"], row["draw_id"]))
    if (view_rows[0]["draw_id"] != PILOT_EXPECTED_FIRST_DRAW
            or view_rows[-1]["draw_id"] != PILOT_EXPECTED_LAST_DRAW):
        raise ReportedSetIndexError(
            "reported-index draw window differs from the frozen pilot preregistration"
        )
    output_bytes = b"".join(
        (json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
        for row in view_rows
    )
    manifest = {
        "schema_version": "lottery.reported-set-index-view/v1",
        "pilot_protocol_version": PILOT_PROTOCOL_VERSION,
        "inventory_sha256": inventory_sha,
        "inventory_trust_status": coverage["inventory_trust_status"],
        "coverage_report_sha256": report_hash,
        "observation_ledger_sha256": ledger_sha,
        "source_domains": coverage.get("source_domains", []),
        "coverage_source_completeness_verified": coverage.get("source_completeness_verified") is True,
        "record_count": len(view_rows),
        "set_index_counts": set_counts,
        "first_draw": view_rows[0]["draw_id"] if view_rows else None,
        "last_draw": view_rows[-1]["draw_id"] if view_rows else None,
        "date_start": view_rows[0]["draw_date"] if view_rows else None,
        "date_end": view_rows[-1]["draw_date"] if view_rows else None,
        "output_sha256": _sha(output_bytes),
        "training_eligibility": "blocked_regime_unresolved",
        "reported_index_pilot_status": "preregistered_research_only",
        "physical_model_eligibility": "blocked_regime_unresolved",
        "physical_identity_claim": "none",
        "model_scope": "reported_set_index_only_not_physical_identity",
    }
    manifest["manifest_sha256"] = _sha(_canonical(manifest))
    return view_rows, manifest


def write_reported_set_index_view(
    view_rows: list[dict[str, Any]], manifest: dict[str, Any], output_dir: Path
) -> tuple[Path, Path]:
    report_hash = manifest["coverage_report_sha256"]
    stem = f"reported-set-index-{report_hash[:16]}"
    output_path = output_dir / f"{stem}.jsonl"
    manifest_path = output_dir / f"{stem}.manifest.json"
    output_bytes = b"".join(
        (json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
        for row in view_rows
    )
    manifest_bytes = (json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    artifacts = ((output_path, output_bytes), (manifest_path, manifest_bytes))
    # Validate every existing path before publishing either missing member.
    for path, content in artifacts:
        if path.exists() and path.read_bytes() != content:
            raise ReportedSetIndexError(f"immutable reported set-index artifact conflicts: {path}")
    for path, content in artifacts:
        if not path.exists():
            try:
                _atomic_write_new(path, content)
            except FileExistsError:
                if path.read_bytes() != content:
                    raise ReportedSetIndexError(f"immutable reported set-index artifact conflicts: {path}")
    return output_path, manifest_path
