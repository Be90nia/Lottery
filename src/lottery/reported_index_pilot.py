"""Research-only rolling-origin pilot for source-reported set indices.

This module never assigns physical equipment identities and never accesses LOT-042.
"""
from __future__ import annotations

import hashlib
import json
import math
import random
from pathlib import Path
from typing import Any

from .backtest import (
    BACK_PICK, BACK_SIZE, DEFAULT_ALPHA, FRONT_PICK, FRONT_SIZE,
    _probabilities, _scores, _validate_rows,
)
from .conditional_poisson import ConditionalPoisson
from .ingest import _atomic_write_new
from .reported_set_index import (
    PILOT_EXPECTED_FIRST_DRAW,
    PILOT_EXPECTED_LAST_DRAW,
    PILOT_EXPECTED_RECORD_COUNT,
    PILOT_EXPECTED_SET_COUNTS,
    PILOT_PROTOCOL_VERSION,
    ReportedSetIndexError,
)


class ReportedIndexPilotError(ValueError):
    pass


MIN_TRAIN_PER_INDEX = 200
PILOT_EXPECTED_TARGET_COUNTS = {"1": 160, "2": 147, "3": 160}
ALPHA = DEFAULT_ALPHA
EWMA_HALF_LIFE = 100.0
BLOCK_LENGTH = 10
BOOTSTRAP_REPLICATES = 10_000
SIGN_FLIP_REPLICATES = 10_000
RANDOM_SEED = 20261119
MIN_COMPLETE_BLOCKS = 10
MODELS = ("uniform", "expanding", "ewma")
ZONES = (
    ("front", "front_numbers", FRONT_SIZE, FRONT_PICK),
    ("back", "back_numbers", BACK_SIZE, BACK_PICK),
)


def _canonical(value: dict[str, Any]) -> bytes:
    return json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _verify_view(view_path: Path, manifest_path: Path) -> tuple[list[dict[str, Any]], dict[str, Any], str]:
    raw = view_path.read_bytes()
    try:
        rows = [json.loads(line) for line in raw.decode("utf-8").splitlines() if line.strip()]
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReportedIndexPilotError(f"reported-index view or manifest is invalid JSON: {exc}") from exc
    if not isinstance(manifest, dict) or manifest.get("schema_version") != "lottery.reported-set-index-view/v1":
        raise ReportedIndexPilotError("unsupported reported-index view manifest")
    manifest_hash = manifest.get("manifest_sha256")
    body = {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    if not isinstance(manifest_hash, str) or _sha(_canonical(body)) != manifest_hash:
        raise ReportedIndexPilotError("reported-index view manifest hash mismatch")
    if manifest.get("pilot_protocol_version") != PILOT_PROTOCOL_VERSION:
        raise ReportedIndexPilotError("reported-index view is not bound to the frozen pilot protocol")
    if _sha(raw) != manifest.get("output_sha256"):
        raise ReportedIndexPilotError("reported-index view bytes do not match manifest")
    if (manifest.get("record_count") != PILOT_EXPECTED_RECORD_COUNT
            or manifest.get("set_index_counts") != PILOT_EXPECTED_SET_COUNTS
            or manifest.get("first_draw") != PILOT_EXPECTED_FIRST_DRAW
            or manifest.get("last_draw") != PILOT_EXPECTED_LAST_DRAW):
        raise ReportedIndexPilotError("reported-index view differs from frozen pilot inventory")
    if (manifest.get("training_eligibility") != "blocked_regime_unresolved"
            or manifest.get("physical_model_eligibility") != "blocked_regime_unresolved"
            or manifest.get("physical_identity_claim") != "none"
            or manifest.get("inventory_trust_status") != "candidate_unverified"
            or manifest.get("model_scope") != "reported_set_index_only_not_physical_identity"):
        raise ReportedIndexPilotError("view unexpectedly resolves physical identity, regime eligibility, or trust status")

    validated = _validate_rows(rows)
    if len(validated) != len(rows):
        raise ReportedIndexPilotError("view row validation changed row count")
    seen: set[str] = set()
    counts = {"1": 0, "2": 0, "3": 0}
    previous = None
    for row in rows:
        draw_id = row.get("draw_id")
        if not isinstance(draw_id, str) or draw_id in seen:
            raise ReportedIndexPilotError("view contains missing or duplicate draw IDs")
        seen.add(draw_id)
        key = (row.get("draw_date"), draw_id)
        if previous is not None and key <= previous:
            raise ReportedIndexPilotError("view rows are not in strict chronological order")
        previous = key
        index = row.get("reported_set_index")
        if type(index) is not int or index not in (1, 2, 3):
            raise ReportedIndexPilotError("view contains invalid reported set index")
        if (row.get("eligible_for_reported_index_pilot") is not True
                or row.get("eligible_for_physical_model") is not False
                or row.get("training_eligibility") != "blocked_regime_unresolved"
                or row.get("equipment_regime_id") is not None
                or row.get("physical_ball_set_id") is not None
                or row.get("evidence_status") != "primary_verified"
                or row.get("model_scope") != "reported_set_index_only_not_physical_identity"
                or row.get("inventory_sha256") != manifest["inventory_sha256"]
                or row.get("coverage_report_sha256") != manifest["coverage_report_sha256"]
                or row.get("observation_ledger_sha256") != manifest["observation_ledger_sha256"]
                or not isinstance(row.get("source_id"), str) or not row["source_id"]):
            raise ReportedIndexPilotError("view row crosses the preregistered physical-regime boundary or has invalid provenance")
        counts[str(index)] += 1
    if counts != PILOT_EXPECTED_SET_COUNTS:
        raise ReportedIndexPilotError("view set-index counts differ from frozen pilot counts")
    return rows, manifest, manifest_hash


def _calibrated_nll(
    train: list[dict[str, Any]], target: dict[str, Any], *,
    field: str, pool_size: int, pick: int, model: str,
) -> tuple[float, float, float, float]:
    probabilities = _probabilities(
        train, field, pool_size, pick,
        model=model, alpha=ALPHA, half_life=EWMA_HALF_LIFE,
    )
    brier, marginal_log_loss, _ = _scores(probabilities, target[field])
    if model == "uniform":
        sampler = ConditionalPoisson([0.0] * pool_size, pick)
        residual = 0.0
    else:
        calibration = ConditionalPoisson.calibrate(
            probabilities, pick, tolerance=1e-8, max_iterations=5000, history_size=10
        )
        if not calibration.converged:
            raise ReportedIndexPilotError(
                f"{model} calibration failed at target {target['draw_id']}: {calibration.terminal_status}"
            )
        sampler = ConditionalPoisson(calibration.centered_log_weights, pick)
        achieved = sampler.inclusion_marginals()
        residual = max(abs(actual - requested) for actual, requested in zip(achieved, probabilities))
        if not math.isfinite(residual) or residual > 1e-8:
            raise ReportedIndexPilotError(
                f"{model} calibration residual exceeds tolerance at target {target['draw_id']}"
            )
    exact_nll = -sampler.log_probability(sorted(target[field]))
    if not math.isfinite(exact_nll) or exact_nll < 0:
        raise ReportedIndexPilotError(f"invalid exact subset NLL at target {target['draw_id']}")
    return exact_nll, brier, marginal_log_loss, residual


def _moving_block_ci(values: list[float], *, seed: int) -> dict[str, Any]:
    n = len(values)
    if n < BLOCK_LENGTH:
        raise ReportedIndexPilotError("too few targets for the preregistered block bootstrap")
    rng = random.Random(seed)
    samples = []
    for _ in range(BOOTSTRAP_REPLICATES):
        sample: list[float] = []
        while len(sample) < n:
            start = rng.randrange(0, n - BLOCK_LENGTH + 1)
            sample.extend(values[start:start + BLOCK_LENGTH])
        samples.append(sum(sample[:n]) / n)
    samples.sort()
    return {
        "mean_delta": sum(values) / n,
        "ci_95_lower": samples[int(0.025 * (BOOTSTRAP_REPLICATES - 1))],
        "ci_95_upper": samples[int(0.975 * (BOOTSTRAP_REPLICATES - 1))],
        "replicates": BOOTSTRAP_REPLICATES,
        "block_length": BLOCK_LENGTH,
        "seed": seed,
    }


def _block_sign_flip_pvalue(values: list[float], *, seed: int) -> tuple[float, int]:
    complete = len(values) // BLOCK_LENGTH
    if complete < MIN_COMPLETE_BLOCKS:
        raise ReportedIndexPilotError(
            f"only {complete} complete blocks; need {MIN_COMPLETE_BLOCKS} for preregistered inference"
        )
    block_means = [
        sum(values[start:start + BLOCK_LENGTH]) / BLOCK_LENGTH
        for start in range(0, complete * BLOCK_LENGTH, BLOCK_LENGTH)
    ]
    observed = sum(block_means) / len(block_means)
    rng = random.Random(seed)
    extreme = 0
    for _ in range(SIGN_FLIP_REPLICATES):
        permuted = sum(
            value * (1.0 if rng.random() < 0.5 else -1.0)
            for value in block_means
        ) / len(block_means)
        if permuted <= observed:
            extreme += 1
    return (extreme + 1) / (SIGN_FLIP_REPLICATES + 1), complete


def _holm_adjust(pvalues: dict[str, float]) -> dict[str, float]:
    ordered = sorted(pvalues.items(), key=lambda item: item[1])
    adjusted: dict[str, float] = {}
    running = 0.0
    count = len(ordered)
    for rank, (key, pvalue) in enumerate(ordered):
        running = max(running, min(1.0, (count - rank) * pvalue))
        adjusted[key] = running
    return adjusted


def build_reported_index_pilot(
    view_path: Path, manifest_path: Path, *, code_commit: str
) -> dict[str, Any]:
    if (not isinstance(code_commit, str) or len(code_commit) != 40
            or any(char not in "0123456789abcdef" for char in code_commit)):
        raise ReportedIndexPilotError("code_commit must be a full lowercase 40-character Git SHA")
    rows, view_manifest, view_manifest_sha = _verify_view(view_path, manifest_path)
    per_index: dict[str, list[dict[str, Any]]] = {str(index): [] for index in (1, 2, 3)}
    for row in rows:
        per_index[str(row["reported_set_index"])].append(row)

    target_counts = {
        key: len(group) - MIN_TRAIN_PER_INDEX for key, group in per_index.items()
    }
    if target_counts != PILOT_EXPECTED_TARGET_COUNTS:
        raise ReportedIndexPilotError("same-index rolling-origin target counts differ from preregistration")

    score_rows: list[dict[str, Any]] = []
    comparisons: dict[str, dict[str, Any]] = {}
    raw_pvalues: dict[str, float] = {}
    delta_series: dict[str, list[float]] = {}
    model_summary: dict[str, Any] = {}
    for index in ("1", "2", "3"):
        group = per_index[index]
        index_summary = {
            "reported_set_index": int(index),
            "training_warmup_draws": MIN_TRAIN_PER_INDEX,
            "target_count": target_counts[index],
            "first_draw": group[0]["draw_id"],
            "last_draw": group[-1]["draw_id"],
            "models": {},
        }
        target_scores: dict[str, dict[str, list[float]]] = {
            model: {zone[0]: [] for zone in ZONES} for model in MODELS
        }
        target_brier: dict[str, dict[str, list[float]]] = {
            model: {zone[0]: [] for zone in ZONES} for model in MODELS
        }
        target_marginal_log_loss: dict[str, dict[str, list[float]]] = {
            model: {zone[0]: [] for zone in ZONES} for model in MODELS
        }
        calibration_residuals: dict[str, dict[str, list[float]]] = {
            model: {zone[0]: [] for zone in ZONES} for model in MODELS
        }

        for target_position in range(MIN_TRAIN_PER_INDEX, len(group)):
            train = group[:target_position]
            target = group[target_position]
            row_scores: dict[str, Any] = {
                "reported_set_index": int(index),
                "target_draw_id": target["draw_id"],
                "target_draw_date": target["draw_date"],
                "prior_same_index_count": len(train),
                "model_scores": {},
            }
            for model in MODELS:
                row_scores["model_scores"][model] = {}
                for zone, field, pool_size, pick in ZONES:
                    nll, brier, marginal_log_loss, residual = _calibrated_nll(
                        train, target, field=field, pool_size=pool_size,
                        pick=pick, model=model,
                    )
                    row_scores["model_scores"][model][zone] = {
                        "exact_subset_nll": nll,
                        "marginal_brier": brier,
                        "marginal_log_loss": marginal_log_loss,
                        "maximum_marginal_calibration_residual": residual,
                    }
                    target_scores[model][zone].append(nll)
                    target_brier[model][zone].append(brier)
                    target_marginal_log_loss[model][zone].append(marginal_log_loss)
                    calibration_residuals[model][zone].append(residual)
            score_rows.append(row_scores)

        for model in MODELS:
            index_summary["models"][model] = {}
            for zone, _, _, _ in ZONES:
                index_summary["models"][model][zone] = {
                    "mean_exact_subset_nll": sum(target_scores[model][zone]) / target_counts[index],
                    "mean_marginal_brier": sum(target_brier[model][zone]) / target_counts[index],
                    "mean_marginal_log_loss": sum(target_marginal_log_loss[model][zone]) / target_counts[index],
                    "maximum_calibration_residual": max(calibration_residuals[model][zone]),
                }
        model_summary[index] = index_summary

        for challenger in ("expanding", "ewma"):
            for zone, _, _, _ in ZONES:
                key = f"index_{index}:{challenger}:{zone}:exact_subset_nll"
                deltas = [
                    candidate - uniform
                    for candidate, uniform in zip(
                        target_scores[challenger][zone], target_scores["uniform"][zone]
                    )
                ]
                delta_series[key] = deltas
                seed = RANDOM_SEED + int(index) * 100 + (0 if challenger == "expanding" else 10) + (0 if zone == "front" else 1)
                ci = _moving_block_ci(deltas, seed=seed)
                pvalue, complete_blocks = _block_sign_flip_pvalue(deltas, seed=seed + 1)
                comparisons[key] = {
                    "reported_set_index": int(index),
                    "challenger": challenger,
                    "zone": zone,
                    "target_count": len(deltas),
                    "complete_non_overlapping_blocks": complete_blocks,
                    "mean_exact_subset_nll_delta_vs_uniform": ci["mean_delta"],
                    "moving_block_bootstrap_ci_95": ci,
                    "block_sign_flip_p_value_one_sided_improvement": pvalue,
                    "negative_delta_is_better": True,
                }
                raw_pvalues[key] = pvalue

    adjusted = _holm_adjust(raw_pvalues)
    for key, result in comparisons.items():
        result["holm_adjusted_p_value"] = adjusted[key]
        result["significant_after_holm_alpha_0_05"] = adjusted[key] < 0.05
        result["improved_and_significant_after_holm"] = (
            result["mean_exact_subset_nll_delta_vs_uniform"] < 0
            and adjusted[key] < 0.05
        )

    all_significant = [
        key for key, result in comparisons.items()
        if result["improved_and_significant_after_holm"]
    ]
    body = {
        "schema_version": "lottery.reported-index-pilot/v1",
        "pilot_protocol_version": PILOT_PROTOCOL_VERSION,
        "view_manifest_sha256": view_manifest_sha,
        "view_sha256": view_manifest["output_sha256"],
        "inventory_sha256": view_manifest["inventory_sha256"],
        "coverage_report_sha256": view_manifest["coverage_report_sha256"],
        "observation_ledger_sha256": view_manifest["observation_ledger_sha256"],
        "code_commit": code_commit,
        "training_warmup_draws_per_index": MIN_TRAIN_PER_INDEX,
        "target_counts": target_counts,
        "model_parameters": {
            "alpha": ALPHA,
            "ewma_half_life_draws": EWMA_HALF_LIFE,
            "sampler": "conditional-Poisson rejective fixed-size distribution",
            "sampler_calibration_tolerance": 1e-8,
        },
        "inference": {
            "primary_metric": "exact unordered-subset negative log likelihood",
            "secondary_metrics": ["marginal Brier", "marginal log loss", "calibration residual"],
            "comparison_count": len(comparisons),
            "block_length": BLOCK_LENGTH,
            "bootstrap_replicates": BOOTSTRAP_REPLICATES,
            "sign_flip_replicates": SIGN_FLIP_REPLICATES,
            "seed": RANDOM_SEED,
            "holm_family": "3 reported indices x 2 challengers x 2 zones = 12",
            "familywise_alpha": 0.05,
        },
        "per_index_summary": model_summary,
        "comparisons": comparisons,
        "score_rows": score_rows,
        "significant_index_specific_improvements": all_significant,
        "decision": (
            "some_index_specific_signal_requires_independent_replication"
            if all_significant else "no_confirmed_index_specific_improvement_over_uniform"
        ),
        "reported_index_pilot_status": "research_only_complete",
        "physical_identity_claim": "none",
        "physical_model_eligibility": "blocked_regime_unresolved",
        "predictive_efficacy_claim": "none",
        "production_ready": False,
        "automatic_promotion": False,
        "holdout_accessed": False,
        "holdout_feedback_used": False,
    }
    return {**body, "report_sha256": _sha(_canonical(body))}


def write_reported_index_pilot(report: dict[str, Any], output_dir: Path) -> Path:
    stem = (
        f"reported-set-index-pilot-{report['view_manifest_sha256'][:12]}-"
        f"{report['code_commit'][:12]}"
    )
    path = output_dir / f"{stem}.json"
    content = (json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    if path.exists():
        if path.read_bytes() != content:
            raise ReportedIndexPilotError(f"immutable pilot report conflicts: {path}")
        return path
    try:
        _atomic_write_new(path, content)
    except FileExistsError:
        if path.read_bytes() != content:
            raise ReportedIndexPilotError(f"immutable pilot report conflicts: {path}")
    return path
