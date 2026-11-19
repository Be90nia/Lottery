"""Build an append-only draw candidate from Jiangsu A2 announcement pages.

The pre-2019 baseline remains an unauthenticated candidate; this module verifies
post-2019 overlap and appends only strictly sequential, source-backed new draws.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from .ball_set_coverage import (
    _read_jsonl as _coverage_read_jsonl,
    _safe_raw_path,
    _verify_observation,
    build_ball_set_coverage,
)
from .ball_set_evidence import (
    BallSetEvidenceError,
    _next_draw_id,
    _read_ledger,
    parse_draw_result,
)
from .ingest import _atomic_write_new
from .reported_index_pilot import _verify_view
from .validate import DatasetValidationError, validate_records


class JiangsuDrawCandidateError(ValueError):
    pass


TRUST_STATUS = "manifest_complete_not_officially_authenticated"


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical(value: dict[str, Any]) -> bytes:
    return json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def _read_manifest(path: Path, raw: bytes, validation: dict[str, Any]) -> tuple[dict[str, Any], str]:
    try:
        manifest_bytes = path.read_bytes()
        manifest = json.loads(manifest_bytes.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise JiangsuDrawCandidateError(f"inventory manifest is unreadable: {exc}") from exc
    if (not isinstance(manifest, dict)
            or manifest.get("output_sha256") != _sha(raw)
            or manifest.get("validation") != validation
            or manifest.get("provenance_complete") is not True
            or manifest.get("trust_status") != TRUST_STATUS):
        raise JiangsuDrawCandidateError("pinned inventory manifest does not verify the input baseline")
    return manifest, _sha(manifest_bytes)


def _write_immutable(path: Path, content: bytes) -> None:
    if path.exists():
        if path.read_bytes() != content:
            raise JiangsuDrawCandidateError(f"immutable source candidate artifact conflicts: {path}")
        return
    try:
        _atomic_write_new(path, content)
    except FileExistsError:
        if path.read_bytes() != content:
            raise JiangsuDrawCandidateError(f"immutable source candidate artifact conflicts: {path}")


def build_jiangsu_draw_candidate(
    inventory_path: Path,
    inventory_manifest_path: Path,
    coverage_path: Path,
    ledger_path: Path,
    archive_dir: Path,
    frozen_view_path: Path,
    frozen_view_manifest_path: Path,
    output_dir: Path,
    live_view_dir: Path,
    *,
    code_commit: str,
) -> dict[str, Any]:
    if not isinstance(code_commit, str) or not re.fullmatch(r"[0-9a-f]{40}", code_commit):
        raise JiangsuDrawCandidateError("code_commit must be a full lowercase 40-character Git SHA")

    inventory, inventory_raw = _coverage_read_jsonl(inventory_path)
    try:
        inventory_validation = validate_records(inventory)
    except DatasetValidationError as exc:
        raise JiangsuDrawCandidateError(f"pinned inventory is invalid: {exc}") from exc
    inventory_manifest, inventory_manifest_sha = _read_manifest(
        inventory_manifest_path, inventory_raw, inventory_validation
    )
    inventory_sha = _sha(inventory_raw)
    inventory_by_id = {row["draw_id"]: row for row in inventory}
    latest_inventory = inventory[-1]

    try:
        coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise JiangsuDrawCandidateError(f"coverage report is unreadable: {exc}") from exc
    if not isinstance(coverage, dict) or coverage.get("schema_version") != "lottery.ball-set-coverage/v1":
        raise JiangsuDrawCandidateError("unsupported ball-set coverage report")
    if coverage.get("inventory_sha256") != inventory_sha:
        raise JiangsuDrawCandidateError("coverage report is bound to a different inventory")
    ledger_raw = ledger_path.read_bytes()
    if coverage.get("observation_ledger_sha256") != _sha(ledger_raw):
        raise JiangsuDrawCandidateError("coverage report is bound to a different observation ledger")
    coverage_code_commit = coverage.get("code_commit")
    if not isinstance(coverage_code_commit, str) or not re.fullmatch(r"[0-9a-f]{40}", coverage_code_commit):
        raise JiangsuDrawCandidateError("coverage report is not bound to a full source commit SHA")
    replay = build_ball_set_coverage(
        inventory_path, ledger_path, archive_dir, code_commit=coverage_code_commit
    )
    if replay.get("report_sha256") != coverage.get("report_sha256"):
        raise JiangsuDrawCandidateError("coverage report does not replay from raw A2 evidence")

    frozen_rows, frozen_manifest, frozen_manifest_sha = _verify_view(
        frozen_view_path, frozen_view_manifest_path
    )
    if (frozen_manifest.get("inventory_sha256") != inventory_sha
            or frozen_manifest.get("coverage_report_sha256") != coverage.get("report_sha256")
            or frozen_manifest.get("observation_ledger_sha256") != _sha(ledger_raw)):
        raise JiangsuDrawCandidateError("frozen pilot view is not bound to current evidence inputs")

    observations = _read_ledger(ledger_path)
    observations_by_id = {item["observation_id"]: item for item in observations}
    live_rows: list[dict[str, Any]] = []
    overlap_count = 0
    overlap_mismatches: list[dict[str, Any]] = []
    provenance_rows: list[dict[str, Any]] = []

    def verified_source_result(observation_id: str, expected_row: dict[str, Any]) -> tuple[dict[str, Any], Any, bytes]:
        observation = observations_by_id.get(observation_id)
        if observation is None:
            raise JiangsuDrawCandidateError(f"coverage references unknown observation {observation_id}")
        source = observation.get("source")
        if not isinstance(source, dict) or source.get("authority_class") != "A2":
            raise JiangsuDrawCandidateError(f"observation {observation_id} is not from the approved A2 source")
        state, set_index, final_url = _verify_observation(
            observation, {"draw_id": observation["draw_id"], "draw_date": observation["draw_date"]}, archive_dir
        )
        if (state != "primary_verified" or set_index != observation.get("reported_set_index")
                or (expected_row.get("reported_set_index") is not None
                    and set_index != expected_row.get("reported_set_index"))):
            raise JiangsuDrawCandidateError(
                f"observation {observation_id} failed raw evidence/label verification: {state}"
            )
        raw_path = _safe_raw_path(archive_dir, source.get("raw_object_ref"))
        raw = raw_path.read_bytes()
        result = parse_draw_result(raw, final_url, source.get("content_type", ""))
        if (observation.get("draw_id") != expected_row.get("draw_id")
                or observation.get("draw_date") != expected_row.get("draw_date")):
            raise JiangsuDrawCandidateError("announcement draw identity differs from expected row")
        return observation, result, raw

    for frozen in frozen_rows:
        draw_id = frozen["draw_id"]
        base = inventory_by_id.get(draw_id)
        if base is None or base["draw_date"] != frozen["draw_date"]:
            raise JiangsuDrawCandidateError(f"frozen pilot draw {draw_id} is absent from pinned inventory")
        ids = frozen.get("observation_ids")
        if not isinstance(ids, list) or len(ids) != 1:
            raise JiangsuDrawCandidateError(f"frozen pilot draw {draw_id} lacks one unambiguous A2 observation")
        observation, result, raw = verified_source_result(
            ids[0], {**base, "reported_set_index": frozen["reported_set_index"]}
        )
        if observation.get("observation_status") != "primary_verified":
            raise JiangsuDrawCandidateError(f"frozen draw {draw_id} is not a primary-verified observation")
        if (list(result.front_numbers) != base["front_numbers"]
                or list(result.back_numbers) != base["back_numbers"]):
            overlap_mismatches.append({
                "draw_id": draw_id,
                "inventory_front": base["front_numbers"],
                "source_front": list(result.front_numbers),
                "inventory_back": base["back_numbers"],
                "source_back": list(result.back_numbers),
            })
            continue
        if (base.get("front_draw_order") is not None
                and list(result.front_draw_order) != base["front_draw_order"]):
            overlap_mismatches.append({"draw_id": draw_id, "field": "front_draw_order"})
            continue
        if (base.get("back_draw_order") is not None
                and list(result.back_draw_order) != base["back_draw_order"]):
            overlap_mismatches.append({"draw_id": draw_id, "field": "back_draw_order"})
            continue
        overlap_count += 1
        source = observation["source"]
        live_rows.append({
            **frozen,
            "front_draw_order": list(result.front_draw_order),
            "back_draw_order": list(result.back_draw_order),
            "source_draw_result_sha256": source["body_sha256"],
            "source_authority_class": source["authority_class"],
            "source_authority_name": source["source_authority_name"],
            "source_observation_id": observation["observation_id"],
            "source_draw_result_url": source["final_url"],
            "draw_result_verified": True,
            "eligible_for_live_candidate_generation": True,
            "eligible_for_reported_index_pilot": False,
        })
        provenance_rows.append({
            "draw_id": draw_id,
            "observation_id": observation["observation_id"],
            "source_body_sha256": source["body_sha256"],
            "source_url": source["final_url"],
            "reported_set_index": observation["reported_set_index"],
            "verification": "A2_draw_result_matches_pinned_inventory",
        })

    if overlap_mismatches:
        raise JiangsuDrawCandidateError(
            f"{len(overlap_mismatches)} A2 draw-result mismatches against pinned inventory; first={overlap_mismatches[0]}"
        )
    if overlap_count != len(frozen_rows):
        raise JiangsuDrawCandidateError("not every frozen pilot row was cross-verified against A2 draw results")

    out_of_inventory = coverage.get("out_of_inventory_observations")
    if (not isinstance(out_of_inventory, list)
            or len(out_of_inventory) != coverage.get("summary", {}).get("out_of_inventory_observation_count")):
        raise JiangsuDrawCandidateError("coverage report out-of-inventory count is inconsistent")
    if coverage.get("summary", {}).get("primary_verified_draws") != overlap_count:
        raise JiangsuDrawCandidateError("coverage primary-verified count differs from A2 result cross-check")
    new_rows: list[dict[str, Any]] = []
    new_live_rows: list[dict[str, Any]] = []
    for item in out_of_inventory:
        if (item.get("observation_status") != "official_label_pending_inventory"
                or item.get("inventory_crosswalk_status") != "not_in_inventory"
                or item.get("raw_evidence_verified") is not True):
            raise JiangsuDrawCandidateError("out-of-inventory evidence is not eligible for guarded append")
        observation, result, raw = verified_source_result(
            item["observation_id"], {
                "draw_id": item["draw_id"],
                "draw_date": item["draw_date"],
                "reported_set_index": item["reported_set_index"],
            }
        )
        if observation.get("observation_status") != "official_label_pending_inventory":
            raise JiangsuDrawCandidateError("out-of-inventory observation status changed during verification")
        source = observation["source"]
        digest = _sha(raw)
        new_row = {
            "draw_id": observation["draw_id"],
            "draw_date": observation["draw_date"],
            "front_numbers": list(result.front_numbers),
            "back_numbers": list(result.back_numbers),
            "front_draw_order": list(result.front_draw_order),
            "back_draw_order": list(result.back_draw_order),
            "source_unsort_drawresult": None,
            "source_equipment_count": None,
            "source_id": f"sha256:{digest}",
        }
        new_rows.append(new_row)
        new_live_rows.append({
            "draw_id": observation["draw_id"],
            "draw_date": observation["draw_date"],
            "front_numbers": list(result.front_numbers),
            "back_numbers": list(result.back_numbers),
            "front_draw_order": list(result.front_draw_order),
            "back_draw_order": list(result.back_draw_order),
            "source_id": f"sha256:{digest}",
            "reported_set_index": observation["reported_set_index"],
            "evidence_status": "primary_verified_new_draw",
            "observation_ids": [observation["observation_id"]],
            "source_urls": [source["final_url"]],
            "source_draw_result_sha256": digest,
            "source_authority_class": source["authority_class"],
            "source_authority_name": source["source_authority_name"],
            "source_observation_id": observation["observation_id"],
            "source_draw_result_url": source["final_url"],
            "inventory_sha256": inventory_sha,
            "coverage_report_sha256": coverage["report_sha256"],
            "observation_ledger_sha256": _sha(ledger_raw),
            "equipment_regime_id": None,
            "physical_ball_set_id": None,
            "eligible_for_reported_index_pilot": False,
            "eligible_for_physical_model": False,
            "eligible_for_live_candidate_generation": True,
            "training_eligibility": "blocked_regime_unresolved",
            "model_scope": "reported_set_index_only_not_physical_identity",
            "draw_result_verified": True,
        })
        provenance_rows.append({
            "draw_id": observation["draw_id"],
            "observation_id": observation["observation_id"],
            "source_body_sha256": digest,
            "source_url": source["final_url"],
            "reported_set_index": observation["reported_set_index"],
            "verification": "A2_new_draw_append_candidate",
        })

    new_rows.sort(key=lambda row: (row["draw_date"], row["draw_id"]))
    previous_id = latest_inventory["draw_id"]
    previous_date = latest_inventory["draw_date"]
    for row in new_rows:
        if not _next_draw_id(previous_id, row["draw_id"]) or row["draw_date"] <= previous_date:
            raise JiangsuDrawCandidateError(
                f"out-of-inventory draw {row['draw_id']} is not the next chronological draw after {previous_id}"
            )
        previous_id, previous_date = row["draw_id"], row["draw_date"]

    candidate_rows = inventory + new_rows
    try:
        validation = validate_records(candidate_rows)
    except DatasetValidationError as exc:
        raise JiangsuDrawCandidateError(f"append-only candidate dataset is invalid: {exc}") from exc
    candidate_bytes = b"".join(
        (json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
        for row in candidate_rows
    )
    candidate_sha = _sha(candidate_bytes)
    candidate_stem = f"jiangsu-draw-candidate-{coverage['report_sha256'][:16]}"
    candidate_path = output_dir / f"{candidate_stem}.jsonl"
    candidate_manifest_path = candidate_path.with_suffix(candidate_path.suffix + ".manifest.json")
    candidate_manifest_body = {
        "schema_version": "lottery.jiangsu-draw-candidate/v1",
        "source": "Jiangsu Provincial Sports Lottery Management Center A2 per-draw announcement pages",
        "code_commit": code_commit,
        "base_inventory_sha256": inventory_sha,
        "base_inventory_manifest_sha256": inventory_manifest_sha,
        "coverage_report_sha256": coverage["report_sha256"],
        "observation_ledger_sha256": _sha(ledger_raw),
        "verified_overlap_draw_count": overlap_count,
        "verified_overlap_mismatch_count": 0,
        "verified_overlap_first_draw": frozen_rows[0]["draw_id"],
        "verified_overlap_last_draw": frozen_rows[-1]["draw_id"],
        "appended_draw_ids": [row["draw_id"] for row in new_rows],
        "appended_record_count": len(new_rows),
        "new_draw_provenance": [row for row in provenance_rows if row["verification"] == "A2_new_draw_append_candidate"],
        "provenance_complete": True,
        "source_completeness_verified": False,
        "trust_status": TRUST_STATUS,
        "validation": validation,
        "output_file": candidate_path.name,
        "output_sha256": candidate_sha,
        "output_bytes": len(candidate_bytes),
    }
    candidate_manifest = {
        **candidate_manifest_body,
        "manifest_sha256": _sha(_canonical(candidate_manifest_body)),
    }
    candidate_manifest_bytes = (json.dumps(
        candidate_manifest, ensure_ascii=False, sort_keys=True, indent=2
    ) + "\n").encode("utf-8")
    _write_immutable(candidate_path, candidate_bytes)
    _write_immutable(candidate_manifest_path, candidate_manifest_bytes)

    live_rows.sort(key=lambda row: (row["draw_date"], row["draw_id"]))
    live_rows.extend(new_live_rows)
    live_rows.sort(key=lambda row: (row["draw_date"], row["draw_id"]))
    live_counts = {"1": 0, "2": 0, "3": 0}
    for row in live_rows:
        live_counts[str(row["reported_set_index"])] += 1
    live_bytes = b"".join(
        (json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
        for row in live_rows
    )
    live_stem = f"reported-set-index-live-{coverage['report_sha256'][:16]}"
    live_path = live_view_dir / f"{live_stem}.jsonl"
    live_manifest_path = live_path.with_suffix(live_path.suffix + ".manifest.json")
    live_manifest_body = {
        "schema_version": "lottery.reported-set-index-live-view/v1",
        "frozen_pilot_view_manifest_sha256": frozen_manifest_sha,
        "inventory_sha256": inventory_sha,
        "candidate_dataset_sha256": candidate_sha,
        "candidate_dataset_manifest_sha256": _sha(candidate_manifest_bytes),
        "coverage_report_sha256": coverage["report_sha256"],
        "observation_ledger_sha256": _sha(ledger_raw),
        "record_count": len(live_rows),
        "set_index_counts": live_counts,
        "first_draw": live_rows[0]["draw_id"],
        "last_draw": live_rows[-1]["draw_id"],
        "appended_draw_ids": [row["draw_id"] for row in new_rows],
        "verified_overlap_draw_count": overlap_count,
        "source_completeness_verified": False,
        "inventory_trust_status": inventory_manifest["trust_status"],
        "training_eligibility": "blocked_regime_unresolved",
        "physical_identity_claim": "none",
        "model_scope": "reported_set_index_only_not_physical_identity",
        "code_commit": code_commit,
        "output_sha256": _sha(live_bytes),
    }
    live_manifest = {
        **live_manifest_body,
        "manifest_sha256": _sha(_canonical(live_manifest_body)),
    }
    live_manifest_bytes = (json.dumps(
        live_manifest, ensure_ascii=False, sort_keys=True, indent=2
    ) + "\n").encode("utf-8")
    _write_immutable(live_path, live_bytes)
    _write_immutable(live_manifest_path, live_manifest_bytes)

    body = {
        "schema_version": "lottery.jiangsu-draw-candidate-receipt/v1",
        "code_commit": code_commit,
        "base_inventory_sha256": inventory_sha,
        "candidate_dataset_sha256": candidate_sha,
        "candidate_manifest_sha256": _sha(candidate_manifest_bytes),
        "coverage_report_sha256": coverage["report_sha256"],
        "observation_ledger_sha256": _sha(ledger_raw),
        "frozen_pilot_view_manifest_sha256": frozen_manifest_sha,
        "live_view_sha256": _sha(live_bytes),
        "live_view_manifest_sha256": _sha(live_manifest_bytes),
        "verified_overlap_draw_count": overlap_count,
        "appended_draw_ids": [row["draw_id"] for row in new_rows],
        "live_set_index_counts": live_counts,
        "inventory_trust_status": TRUST_STATUS,
        "source_completeness_verified": False,
        "canonical_dataset_modified": False,
        "physical_identity_claim": "none",
        "physical_model_eligibility": "blocked_regime_unresolved",
        "holdout_accessed": False,
        "predictive_efficacy_claim": "none",
        "candidate_path": str(candidate_path),
        "candidate_manifest_path": str(candidate_manifest_path),
        "live_view_path": str(live_path),
        "live_view_manifest_path": str(live_manifest_path),
    }
    return {**body, "receipt_sha256": _sha(_canonical(body))}
