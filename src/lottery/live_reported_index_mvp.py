"""Generate live reported-index candidates from a verified append-only A2 view."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from .ball_set_evidence import _next_draw_id, _allowed_url
from .ingest import _atomic_write_new
from .reported_index_pilot import (
    _canonical,
    _sha,
    _verify_view,
)
from .tickets import generate_ticket_candidates
from .validate import DatasetValidationError, validate_records


class LiveReportedIndexMVPError(ValueError):
    pass


TRUST_STATUS = "manifest_complete_not_officially_authenticated"


def _read_jsonl(path: Path) -> tuple[list[dict[str, Any]], bytes]:
    raw = path.read_bytes()
    try:
        rows = [json.loads(line) for line in raw.decode("utf-8").splitlines() if line.strip()]
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LiveReportedIndexMVPError(f"invalid JSONL at {path}: {exc}") from exc
    if not rows:
        raise LiveReportedIndexMVPError(f"empty JSONL input: {path}")
    return rows, raw


def _read_json(path: Path) -> tuple[dict[str, Any], bytes]:
    raw = path.read_bytes()
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LiveReportedIndexMVPError(f"invalid JSON at {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise LiveReportedIndexMVPError(f"expected JSON object at {path}")
    return value, raw


def _verify_pilot(pilot_path: Path, frozen_manifest: dict[str, Any], frozen_sha: str) -> tuple[dict[str, Any], str]:
    pilot, raw = _read_json(pilot_path)
    pilot_sha = pilot.get("report_sha256")
    body = {key: value for key, value in pilot.items() if key != "report_sha256"}
    if not isinstance(pilot_sha, str) or _sha(_canonical(body)) != pilot_sha:
        raise LiveReportedIndexMVPError("pilot report hash mismatch")
    if (pilot.get("schema_version") != "lottery.reported-index-pilot/v1"
            or pilot.get("view_manifest_sha256") != frozen_sha
            or pilot.get("view_sha256") != frozen_manifest.get("output_sha256")
            or pilot.get("reported_index_pilot_status") != "research_only_complete"
            or pilot.get("target_counts") != {"1": 160, "2": 147, "3": 160}
            or pilot.get("inference", {}).get("comparison_count") != 12
            or pilot.get("physical_identity_claim") != "none"
            or pilot.get("physical_model_eligibility") != "blocked_regime_unresolved"
            or pilot.get("predictive_efficacy_claim") != "none"
            or pilot.get("production_ready") is not False
            or pilot.get("automatic_promotion") is not False
            or pilot.get("holdout_accessed") is not False
            or pilot.get("holdout_feedback_used") is not False):
        raise LiveReportedIndexMVPError("pilot receipt is not bound to the frozen research-only evaluation")
    return pilot, pilot_sha


def build_live_reported_index_mvp(
    frozen_view_path: Path,
    frozen_manifest_path: Path,
    live_view_path: Path,
    live_manifest_path: Path,
    candidate_dataset_path: Path,
    candidate_manifest_path: Path,
    pilot_report_path: Path,
    *,
    tickets_per_strategy: int = 5,
    seed: int = 20261119,
    alpha: float = 100.0,
    half_life: float = 100.0,
    code_commit: str,
) -> dict[str, Any]:
    if not isinstance(code_commit, str) or not re.fullmatch(r"[0-9a-f]{40}", code_commit):
        raise LiveReportedIndexMVPError("code_commit must be a full lowercase 40-character Git SHA")

    frozen_rows, frozen_manifest, frozen_manifest_sha = _verify_view(
        frozen_view_path, frozen_manifest_path
    )
    pilot, pilot_sha = _verify_pilot(pilot_report_path, frozen_manifest, frozen_manifest_sha)

    candidate_rows, candidate_raw = _read_jsonl(candidate_dataset_path)
    try:
        candidate_validation = validate_records(candidate_rows)
    except DatasetValidationError as exc:
        raise LiveReportedIndexMVPError(f"append-only candidate dataset is invalid: {exc}") from exc
    candidate_manifest, candidate_manifest_raw = _read_json(candidate_manifest_path)
    candidate_sha = _sha(candidate_raw)
    candidate_manifest_sha = _sha(candidate_manifest_raw)
    candidate_manifest_body = {
        key: value for key, value in candidate_manifest.items() if key != "manifest_sha256"
    }
    if (candidate_manifest.get("manifest_sha256") != _sha(_canonical(candidate_manifest_body))
            or candidate_manifest.get("output_file") != candidate_dataset_path.name
            or candidate_manifest.get("output_bytes") != len(candidate_raw)
            or candidate_manifest.get("appended_record_count") != len(candidate_manifest.get("appended_draw_ids", []))
            or candidate_manifest.get("output_sha256") != candidate_sha
            or candidate_manifest.get("validation") != candidate_validation
            or candidate_manifest.get("provenance_complete") is not True
            or candidate_manifest.get("trust_status") != TRUST_STATUS
            or candidate_manifest.get("source_completeness_verified") is not False
            or candidate_manifest.get("verified_overlap_draw_count") != len(frozen_rows)
            or candidate_manifest.get("base_inventory_sha256") != frozen_manifest["inventory_sha256"]
            or candidate_manifest.get("coverage_report_sha256") != frozen_manifest["coverage_report_sha256"]
            or candidate_manifest.get("observation_ledger_sha256") != frozen_manifest["observation_ledger_sha256"]):
        raise LiveReportedIndexMVPError("candidate dataset manifest does not verify the A2 append-only candidate")

    live_rows, live_raw = _read_jsonl(live_view_path)
    live_manifest, live_manifest_raw = _read_json(live_manifest_path)
    live_manifest_sha = live_manifest.get("manifest_sha256")
    live_manifest_body = {
        key: value for key, value in live_manifest.items() if key != "manifest_sha256"
    }
    if not isinstance(live_manifest_sha, str) or _sha(_canonical(live_manifest_body)) != live_manifest_sha:
        raise LiveReportedIndexMVPError("live index view manifest hash mismatch")
    if (live_manifest.get("schema_version") != "lottery.reported-set-index-live-view/v1"
            or live_manifest.get("output_sha256") != _sha(live_raw)
            or live_manifest.get("frozen_pilot_view_manifest_sha256") != frozen_manifest_sha
            or live_manifest.get("candidate_dataset_sha256") != candidate_sha
            or live_manifest.get("candidate_dataset_manifest_sha256") != candidate_manifest_sha
            or live_manifest.get("coverage_report_sha256") != frozen_manifest["coverage_report_sha256"]
            or live_manifest.get("observation_ledger_sha256") != frozen_manifest["observation_ledger_sha256"]
            or live_manifest.get("inventory_sha256") != frozen_manifest["inventory_sha256"]
            or live_manifest.get("inventory_trust_status") != TRUST_STATUS
            or live_manifest.get("training_eligibility") != "blocked_regime_unresolved"
            or live_manifest.get("physical_identity_claim") != "none"
            or live_manifest.get("model_scope") != "reported_set_index_only_not_physical_identity"
            or live_manifest.get("source_completeness_verified") is not False
            or live_manifest.get("verified_overlap_draw_count") != len(frozen_rows)):
        raise LiveReportedIndexMVPError("live index view does not match its frozen and append-only inputs")

    candidate_by_id = {row["draw_id"]: row for row in candidate_rows}
    if len(candidate_by_id) != len(candidate_rows):
        raise LiveReportedIndexMVPError("candidate dataset contains duplicate draw IDs")
    frozen_by_id = {row["draw_id"]: row for row in frozen_rows}
    live_by_id = {row.get("draw_id"): row for row in live_rows}
    if len(live_by_id) != len(live_rows) or len(live_rows) != live_manifest.get("record_count"):
        raise LiveReportedIndexMVPError("live view contains duplicate IDs or invalid record count")
    chronological_keys = [(row.get("draw_date"), row.get("draw_id")) for row in live_rows]
    if chronological_keys != sorted(chronological_keys):
        raise LiveReportedIndexMVPError("live view rows are not chronologically ordered")
    if candidate_rows[-1]["draw_id"] != live_rows[-1]["draw_id"]:
        raise LiveReportedIndexMVPError("candidate dataset and live view do not share the same latest draw")
    if not set(frozen_by_id).issubset(live_by_id):
        raise LiveReportedIndexMVPError("live view is missing frozen pilot rows")

    for draw_id, frozen in frozen_by_id.items():
        live = live_by_id[draw_id]
        for key in (
            "draw_date", "front_numbers", "back_numbers", "reported_set_index",
            "source_id", "observation_ids", "source_urls", "inventory_sha256",
            "coverage_report_sha256", "observation_ledger_sha256",
        ):
            if live.get(key) != frozen.get(key):
                raise LiveReportedIndexMVPError(f"live view changed frozen pilot row {draw_id} field {key}")

    appended_ids = sorted(set(live_by_id) - set(frozen_by_id), key=lambda value: (
        live_by_id[value]["draw_date"], value
    ))
    if (appended_ids != live_manifest.get("appended_draw_ids")
            or appended_ids != candidate_manifest.get("appended_draw_ids")):
        raise LiveReportedIndexMVPError("live view and candidate manifest appended IDs differ")
    previous_id = frozen_manifest["last_draw"]
    previous_date = frozen_rows[-1]["draw_date"]
    for draw_id in appended_ids:
        row = live_by_id[draw_id]
        if not _next_draw_id(previous_id, draw_id) or row["draw_date"] <= previous_date:
            raise LiveReportedIndexMVPError("live view appended draw is not strictly sequential")
        previous_id, previous_date = draw_id, row["draw_date"]

    candidate_ids = set(candidate_by_id)
    live_counts = {"1": 0, "2": 0, "3": 0}
    for row in live_rows:
        draw_id = row.get("draw_id")
        candidate = candidate_by_id.get(draw_id)
        if candidate is None:
            raise LiveReportedIndexMVPError(f"live draw {draw_id} is absent from candidate dataset")
        if (row.get("draw_date") != candidate.get("draw_date")
                or row.get("front_numbers") != candidate.get("front_numbers")
                or row.get("back_numbers") != candidate.get("back_numbers")
                or row.get("source_id") != candidate.get("source_id")):
            raise LiveReportedIndexMVPError(f"live draw {draw_id} differs from candidate dataset")
        if (row.get("draw_result_verified") is not True
                or row.get("eligible_for_live_candidate_generation") is not True
                or row.get("eligible_for_reported_index_pilot") is not False
                or row.get("eligible_for_physical_model") is not False
                or row.get("training_eligibility") != "blocked_regime_unresolved"
                or row.get("equipment_regime_id") is not None
                or row.get("physical_ball_set_id") is not None
                or row.get("model_scope") != "reported_set_index_only_not_physical_identity"
                or row.get("source_authority_class") != "A2"
                or not isinstance(row.get("source_observation_id"), str)
                or not isinstance(row.get("source_draw_result_sha256"), str)
                or not re.fullmatch(r"[0-9a-f]{64}", row["source_draw_result_sha256"])
                or type(row.get("reported_set_index")) is not int
                or row["reported_set_index"] not in (1, 2, 3)
                or row.get("source_observation_id") not in row.get("observation_ids", [])):
            raise LiveReportedIndexMVPError(f"live draw {draw_id} violates A2 candidate eligibility boundary")
        try:
            _allowed_url(row["source_draw_result_url"])
        except (KeyError, ValueError) as exc:
            raise LiveReportedIndexMVPError(f"live draw {draw_id} has invalid A2 source URL") from exc
        if (len(row.get("front_draw_order", [])) != 5
                or set(row["front_draw_order"]) != set(row["front_numbers"])
                or len(row.get("back_draw_order", [])) != 2
                or set(row["back_draw_order"]) != set(row["back_numbers"])):
            raise LiveReportedIndexMVPError(f"live draw {draw_id} has invalid source draw order")
        if draw_id in appended_ids:
            if (row.get("evidence_status") != "primary_verified_new_draw"
                    or row["source_id"] != f"sha256:{row['source_draw_result_sha256']}"):
                raise LiveReportedIndexMVPError(f"new live draw {draw_id} lacks A2 append provenance")
        elif row.get("evidence_status") != "primary_verified":
            raise LiveReportedIndexMVPError(f"frozen live draw {draw_id} changed evidence status")
        live_counts[str(row["reported_set_index"])] += 1

    frozen_counts = frozen_manifest["set_index_counts"]
    expected_counts = {key: frozen_counts[key] for key in ("1", "2", "3")}
    for draw_id in appended_ids:
        key = str(live_by_id[draw_id]["reported_set_index"])
        expected_counts[key] += 1
    if (live_counts != expected_counts
            or live_manifest.get("set_index_counts") != live_counts
            or live_manifest.get("first_draw") != frozen_manifest["first_draw"]
            or live_manifest.get("last_draw") != max(live_rows, key=lambda row: (row["draw_date"], row["draw_id"]))["draw_id"]):
        raise LiveReportedIndexMVPError("live view counts or draw window are inconsistent")
    if not set(live_by_id).issubset(candidate_ids):
        raise LiveReportedIndexMVPError("live view contains a draw outside the candidate dataset")

    groups: dict[str, list[dict[str, Any]]] = {str(index): [] for index in (1, 2, 3)}
    for row in live_rows:
        groups[str(row["reported_set_index"])].append(row)
    index_batches: dict[str, Any] = {}
    total_tickets = 0
    for index in ("1", "2", "3"):
        batch = generate_ticket_candidates(
            groups[index],
            tickets_per_strategy=tickets_per_strategy,
            seed=seed + int(index) * 1_000_003,
            alpha=alpha,
            half_life=half_life,
            code_commit=code_commit,
        )
        if (batch.get("code_commit") != code_commit
                or batch.get("training_draw_count") != live_counts[index]
                or batch.get("total_tickets") != tickets_per_strategy * 3):
            raise LiveReportedIndexMVPError(f"live candidate batch contract failed for index {index}")
        total_tickets += batch["total_tickets"]
        index_batches[index] = {
            "reported_set_index": int(index),
            "seed": seed + int(index) * 1_000_003,
            "training_draw_count": len(groups[index]),
            "training_first_draw_id": groups[index][0]["draw_id"],
            "training_last_draw_id": groups[index][-1]["draw_id"],
            "training_dataset_fingerprint": batch["training_dataset_fingerprint"],
            "generation_run_id": batch["generation_run_id"],
            "strategy_metadata": batch["strategy_metadata"],
            "model_configuration": batch["model_configuration"],
            "rng": batch["rng"],
            "sampler_version": batch["sampler_version"],
            "strategies": batch["strategies"],
            "limitations": batch["limitations"],
        }

    body = {
        "schema_version": "lottery.live-reported-index-mvp/v1",
        "purpose": "live_exploratory_reported_index_conditioned_ticket_candidates",
        "code_commit": code_commit,
        "generated_seed": seed,
        "alpha": alpha,
        "ewma_half_life_draws": half_life,
        "tickets_per_strategy_per_index": tickets_per_strategy,
        "total_tickets": total_tickets,
        "strategy_lanes": ["uniform", "expanding", "ewma"],
        "frozen_pilot_view_manifest_sha256": frozen_manifest_sha,
        "live_view_manifest_sha256": live_manifest_sha,
        "live_view_sha256": _sha(live_raw),
        "candidate_dataset_sha256": candidate_sha,
        "candidate_dataset_manifest_sha256": candidate_manifest_sha,
        "pilot_report_sha256": pilot_sha,
        "appended_draw_ids": appended_ids,
        "live_set_index_counts": live_counts,
        "latest_draw_id": live_rows[-1]["draw_id"],
        "latest_draw_date": live_rows[-1]["draw_date"],
        "inventory_trust_status": TRUST_STATUS,
        "source_completeness_verified": False,
        "training_scope": "only_prior_draws_with_the_same_reported_set_index",
        "model_scope": "reported_set_index_only_not_physical_identity",
        "physical_identity_claim": "none",
        "physical_model_eligibility": "blocked_regime_unresolved",
        "pilot_decision": pilot["decision"],
        "significant_index_specific_improvements": pilot.get("significant_index_specific_improvements", []),
        "predictive_efficacy_claim": "none",
        "holdout_accessed": False,
        "holdout_feedback_used": False,
        "automatic_promotion": False,
        "production_ready": False,
        "index_batches": index_batches,
        "limitations": [
            "Reported set index is a source-reported category, not a stable physical ball-set identity.",
            "The full candidate history remains manifest_complete_not_officially_authenticated; only the 2019+ overlap and appended draws are A2 cross-checked.",
            "All estimator lanes are emitted; no lane is selected from the pilot results.",
            "Conditional-Poisson sampling is a rejective distribution assumption, not a demonstrated physical mechanism or predictive edge.",
            "These are exploratory candidates, not predictions or guarantees.",
        ],
    }
    return {**body, "report_sha256": _sha(_canonical(body))}


def write_live_reported_index_mvp(report: dict[str, Any], output_dir: Path) -> Path:
    stem = (
        f"live-reported-index-mvp-{report['live_view_manifest_sha256'][:10]}-"
        f"{report['pilot_report_sha256'][:10]}-{report['code_commit'][:10]}"
    )
    path = output_dir / f"{stem}.json"
    content = (json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    if path.exists():
        if path.read_bytes() != content:
            raise LiveReportedIndexMVPError(f"immutable live candidate artifact conflicts: {path}")
        return path
    try:
        _atomic_write_new(path, content)
    except FileExistsError:
        if path.read_bytes() != content:
            raise LiveReportedIndexMVPError(f"immutable live candidate artifact conflicts: {path}")
    return path
