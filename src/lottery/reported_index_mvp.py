"""Emit exploratory ticket lanes for each source-reported set index."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from .ingest import _atomic_write_new
from .reported_index_pilot import (
    PILOT_EXPECTED_SET_COUNTS,
    ReportedIndexPilotError,
    _canonical,
    _sha,
    _verify_view,
)
from .tickets import generate_ticket_candidates


class ReportedIndexMVPError(ValueError):
    pass


def build_reported_index_mvp(
    view_path: Path,
    view_manifest_path: Path,
    pilot_report_path: Path,
    *,
    tickets_per_strategy: int = 5,
    seed: int = 20261119,
    alpha: float = 100.0,
    half_life: float = 100.0,
    code_commit: str,
) -> dict[str, Any]:
    if (not isinstance(code_commit, str) or not re.fullmatch(r"[0-9a-f]{40}", code_commit)):
        raise ReportedIndexMVPError("code_commit must be a full lowercase 40-character Git SHA")
    rows, view_manifest, view_manifest_sha = _verify_view(view_path, view_manifest_path)
    try:
        pilot = json.loads(pilot_report_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReportedIndexMVPError(f"pilot report is unreadable: {exc}") from exc
    if not isinstance(pilot, dict) or pilot.get("schema_version") != "lottery.reported-index-pilot/v1":
        raise ReportedIndexMVPError("unsupported reported-index pilot report")
    pilot_sha = pilot.get("report_sha256")
    pilot_body = {key: value for key, value in pilot.items() if key != "report_sha256"}
    if not isinstance(pilot_sha, str) or _sha(_canonical(pilot_body)) != pilot_sha:
        raise ReportedIndexMVPError("pilot report hash mismatch")
    if (pilot.get("view_manifest_sha256") != view_manifest_sha
            or pilot.get("view_sha256") != view_manifest.get("output_sha256")
            or pilot.get("reported_index_pilot_status") != "research_only_complete"
            or pilot.get("physical_model_eligibility") != "blocked_regime_unresolved"
            or pilot.get("physical_identity_claim") != "none"
            or pilot.get("predictive_efficacy_claim") != "none"
            or pilot.get("production_ready") is not False
            or pilot.get("automatic_promotion") is not False
            or pilot.get("holdout_accessed") is not False
            or pilot.get("holdout_feedback_used") is not False
            or pilot.get("target_counts") != {"1": 160, "2": 147, "3": 160}
            or pilot.get("inference", {}).get("comparison_count") != 12):
        raise ReportedIndexMVPError("pilot receipt does not match the frozen research-only boundary")

    groups: dict[str, list[dict[str, Any]]] = {str(index): [] for index in (1, 2, 3)}
    for row in rows:
        groups[str(row["reported_set_index"])].append(row)
    actual_counts = {key: len(value) for key, value in groups.items()}
    if actual_counts != PILOT_EXPECTED_SET_COUNTS:
        raise ReportedIndexMVPError("reported-index candidate counts differ from preregistered inventory")

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
                or batch.get("training_draw_count") != PILOT_EXPECTED_SET_COUNTS[index]
                or batch.get("total_tickets") != tickets_per_strategy * 3):
            raise ReportedIndexMVPError(f"candidate batch contract failed for reported index {index}")
        total_tickets += batch["total_tickets"]
        index_batches[index] = {
            "reported_set_index": int(index),
            "training_draw_count": len(groups[index]),
            "training_first_draw_id": groups[index][0]["draw_id"],
            "training_last_draw_id": groups[index][-1]["draw_id"],
            "training_dataset_fingerprint": batch["training_dataset_fingerprint"],
            "generation_run_id": batch["generation_run_id"],
            "strategy_metadata": batch["strategy_metadata"],
            "strategies": batch["strategies"],
            "limitations": batch["limitations"],
        }

    body = {
        "schema_version": "lottery.reported-index-mvp/v1",
        "purpose": "exploratory_reported_index_conditioned_ticket_candidates",
        "code_commit": code_commit,
        "generated_seed": seed,
        "tickets_per_strategy_per_index": tickets_per_strategy,
        "total_tickets": total_tickets,
        "index_count": 3,
        "strategy_count_per_index": 3,
        "strategy_lanes": ["uniform", "expanding", "ewma"],
        "view_manifest_sha256": view_manifest_sha,
        "view_sha256": view_manifest["output_sha256"],
        "pilot_report_sha256": pilot_sha,
        "inventory_sha256": view_manifest["inventory_sha256"],
        "coverage_report_sha256": view_manifest["coverage_report_sha256"],
        "observation_ledger_sha256": view_manifest["observation_ledger_sha256"],
        "inventory_trust_status": view_manifest["inventory_trust_status"],
        "reported_index_label_status": "primary_verified_in_frozen_development_window",
        "training_scope": "only_prior_draws_with_the_same_reported_set_index",
        "model_scope": "reported_set_index_only_not_physical_identity",
        "physical_identity_claim": "none",
        "equipment_regime_id": None,
        "physical_ball_set_id": None,
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
            "Reported set index is not a stable physical ball-set identity.",
            "The pinned draw-number inventory remains candidate_unverified and not officially authenticated.",
            "All estimator lanes are emitted; no lane is selected based on the pilot results.",
            "Conditional-Poisson sampling is a rejective distribution assumption, not a demonstrated physical mechanism or predictive edge.",
            "These are legal exploratory candidates, not predictions or guarantees.",
        ],
    }
    return {**body, "report_sha256": _sha(_canonical(body))}


def write_reported_index_mvp(report: dict[str, Any], output_dir: Path) -> Path:
    stem = (
        f"reported-index-mvp-{report['view_manifest_sha256'][:10]}-"
        f"{report['pilot_report_sha256'][:10]}-{report['code_commit'][:10]}"
    )
    path = output_dir / f"{stem}.json"
    content = (json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    if path.exists():
        if path.read_bytes() != content:
            raise ReportedIndexMVPError(f"immutable reported-index MVP artifact conflicts: {path}")
        return path
    try:
        _atomic_write_new(path, content)
    except FileExistsError:
        if path.read_bytes() != content:
            raise ReportedIndexMVPError(f"immutable reported-index MVP artifact conflicts: {path}")
    return path
