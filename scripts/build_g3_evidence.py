"""Build typed G3 evidence documents from immutable LOT-055 run outputs.

This adapter never invents a preregistration or calibration result. It requires
an explicit registration record and, when absent, emits a BLOCKED calibration
document instead of fabricating target-level diagnostics.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import sys
from pathlib import Path
from typing import Any

from lottery.subset_model.artifact import canonicalize, verify_artifact
from lottery.subset_model.exponential import ExponentialFamily
from lottery.subset_model.uniform import build_uniform_feature_table
from lottery.readiness_receipts import _g3_moving_block_bootstrap

EXPECTED_SNAPSHOT_SHA256 = "9f4cc51b76fd258dd056e0b86f675192d3d9a41c2901f771cab778c65ec2b6aa"
EXPECTED_ROWS = 2949
MIN_TRAIN = 300
TARGET_COUNT = EXPECTED_ROWS - MIN_TRAIN
MODEL_IDS = {
    "candidate": "exponential_family",
    "uniform": "uniform",
    "expanding": "expanding",
    "ewma": "ewma",
}
ZONES = ("front", "back")
COMPARATORS = ("uniform", "expanding", "ewma")
BOOTSTRAP_METHOD = "holm-step-down-one-sided-centered-moving-block-bootstrap"


class G3EvidenceBuildError(ValueError):
    """Raised when immutable run inputs cannot safely be adapted into G3 evidence."""


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _strict_json(raw: bytes, label: str) -> dict[str, Any]:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise G3EvidenceBuildError(f"{label}: duplicate JSON key {key}")
            result[key] = value
        return result
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise G3EvidenceBuildError(f"{label}: invalid JSON") from exc
    if not isinstance(value, dict):
        raise G3EvidenceBuildError(f"{label}: expected JSON object")
    return value


def _read_snapshot(path: Path, expected_sha256: str) -> tuple[bytes, list[dict[str, Any]]]:
    raw = path.read_bytes()
    if _sha256(raw) != expected_sha256:
        raise G3EvidenceBuildError("frozen snapshot SHA-256 mismatch")
    try:
        rows = [_strict_json(line, f"snapshot line {index}") for index, line in enumerate(raw.splitlines(), 1)]
    except G3EvidenceBuildError:
        raise
    if len(rows) != EXPECTED_ROWS:
        raise G3EvidenceBuildError("frozen snapshot row count mismatch")
    required = {"draw_id", "draw_date", "front_numbers", "back_numbers"}
    ids, dates = [], []
    for index, row in enumerate(rows):
        if not required <= set(row):
            raise G3EvidenceBuildError(f"snapshot row {index} is missing required draw fields")
        draw_id, draw_date = row["draw_id"], row["draw_date"]
        if not isinstance(draw_id, str) or len(draw_id) != 5 or not draw_id.isdigit():
            raise G3EvidenceBuildError(f"snapshot row {index} has invalid draw ID")
        if not isinstance(draw_date, str) or len(draw_date) != 10:
            raise G3EvidenceBuildError(f"snapshot row {index} has invalid draw date")
        ids.append(draw_id)
        dates.append(draw_date)
        for field, population, picks in (("front_numbers", 35, 5), ("back_numbers", 12, 2)):
            values = row[field]
            if (not isinstance(values, list) or len(values) != picks
                    or any(type(value) is not int or not 1 <= value <= population for value in values)
                    or len(set(values)) != picks or values != sorted(values)):
                raise G3EvidenceBuildError(f"snapshot row {index} has invalid {field}")
    if ids != sorted(set(ids)) or dates != sorted(set(dates)):
        raise G3EvidenceBuildError("snapshot source order is not strictly chronological")
    if ids[300] != "09054" or ids[-1] != "26131":
        raise G3EvidenceBuildError("frozen target boundaries differ from LOT-055 preregistration")
    return raw, rows


def _bootstrap(values: list[float], seed: int) -> tuple[float, float, float]:
    return _g3_moving_block_bootstrap(tuple(values), seed)


def _holm(p_values: dict[str, float]) -> dict[str, float]:
    ordered = sorted(p_values.items(), key=lambda item: item[1])
    adjusted, running = {}, 0.0
    for rank, (hypothesis, p_value) in enumerate(ordered):
        running = max(running, min(1.0, (len(ordered) - rank) * p_value))
        adjusted[hypothesis] = running
    return adjusted


def build_g3_evidence_bundle(
    *, snapshot_path: Path, run_manifest_path: Path, ledger_path: Path,
    model_artifacts_path: Path, registration_path: Path, output_dir: Path, expected_snapshot_sha256: str,
    expected_run_manifest_sha256: str, calibration_path: Path | None = None,
) -> dict[str, Any]:
    """Create six G3 evidence files and an explicit non-authorizing build summary."""
    if expected_snapshot_sha256 != EXPECTED_SNAPSHOT_SHA256:
        raise G3EvidenceBuildError("only the frozen LOT-055 snapshot digest is supported")
    snapshot_raw, rows = _read_snapshot(snapshot_path, expected_snapshot_sha256)
    run_raw = run_manifest_path.read_bytes()
    if _sha256(run_raw) != expected_run_manifest_sha256:
        raise G3EvidenceBuildError("run manifest byte digest mismatch")
    run_manifest = _strict_json(run_raw, "run manifest")
    run_body = {key: value for key, value in run_manifest.items() if key != "manifest_sha256"}
    if run_manifest.get("manifest_sha256") != "sha256:" + _sha256(canonicalize(run_body)):
        raise G3EvidenceBuildError("run manifest internal digest mismatch")
    if run_manifest.get("schema") != "lot-055-run-manifest-v1":
        raise G3EvidenceBuildError("unsupported LOT-055 run manifest schema")
    if run_manifest.get("snapshot", {}).get("sha256") != expected_snapshot_sha256:
        raise G3EvidenceBuildError("run manifest snapshot digest mismatch")

    target_rows = rows[MIN_TRAIN:]
    target_list = [
        {"target_draw_id": row["draw_id"], "target_draw_date": row["draw_date"]}
        for row in target_rows
    ]
    target_manifest_digest = "sha256:" + _sha256(canonicalize({"targets": target_list}))
    if run_manifest.get("target_manifest", {}).get("target_list_sha256") != target_manifest_digest:
        raise G3EvidenceBuildError("run manifest target-list digest does not match the frozen snapshot")
    if (run_manifest.get("target_manifest", {}).get("target_count_per_zone") != TARGET_COUNT
            or run_manifest.get("target_manifest", {}).get("first_target_draw_id") != target_rows[0]["draw_id"]
            or run_manifest.get("target_manifest", {}).get("last_target_draw_id") != target_rows[-1]["draw_id"]):
        raise G3EvidenceBuildError("run manifest target denominator/bounds mismatch")

    registration = _strict_json(registration_path.read_bytes(), "G3 registration")
    if registration.get("schema") != "lottery.g3-preregistration/v1":
        raise G3EvidenceBuildError("registration must use lottery.g3-preregistration/v1")
    if registration.get("snapshot_sha256") != expected_snapshot_sha256:
        raise G3EvidenceBuildError("registration snapshot digest mismatch")
    if registration.get("target_manifest_sha256") != target_manifest_digest.removeprefix("sha256:"):
        raise G3EvidenceBuildError("registration target manifest digest mismatch")
    if registration.get("experiment_id") != hashlib.sha256(
        str(run_manifest.get("experiment_id", "")).encode("utf-8")
    ).hexdigest():
        raise G3EvidenceBuildError("registration does not identify this run's experiment")
    if registration.get("experiment_class") != run_manifest.get("experiment_class"):
        raise G3EvidenceBuildError("registration/run experiment class mismatch")

    ledger_raw = ledger_path.read_bytes()
    ledger_digest = _sha256(ledger_raw)
    model_artifacts_raw = model_artifacts_path.read_bytes()
    model_artifacts_digest = _sha256(model_artifacts_raw)
    declared_artifacts = run_manifest.get("output_files", {}).get("model-artifacts.jsonl", {})
    if (declared_artifacts.get("sha256") != model_artifacts_digest
            or declared_artifacts.get("bytes") != len(model_artifacts_raw)
            or run_manifest.get("model_artifact_count") != len(model_artifacts_raw.splitlines())
            or run_manifest.get("model_artifact_count") != 2649 * 2 * 3):
        raise G3EvidenceBuildError("model-artifact bytes/count do not match immutable run manifest")
    declared_ledger = run_manifest.get("output_files", {}).get("target-score-ledger.jsonl", {})
    if declared_ledger.get("sha256") != ledger_digest or declared_ledger.get("bytes") != len(ledger_raw):
        raise G3EvidenceBuildError("terminal ledger bytes do not match immutable run manifest")
    ledger = [_strict_json(line, f"terminal ledger line {index}") for index, line in enumerate(ledger_raw.splitlines(), 1)]
    expected_records = TARGET_COUNT * len(MODEL_IDS) * len(ZONES)
    if len(ledger) != expected_records or run_manifest.get("actual_target_record_count") != expected_records:
        raise G3EvidenceBuildError("terminal ledger does not cover the frozen model × zone × target denominator")
    if run_manifest.get("expected_target_record_count") != expected_records:
        raise G3EvidenceBuildError("run manifest expected denominator mismatch")

    target_ids = [item["target_draw_id"] for item in target_list]
    target_ids_hash = _sha256(canonicalize(target_ids))
    chronology = {
        "schema": "lottery.g3-chronological-targets/v1",
        "snapshot_sha256": expected_snapshot_sha256,
        "target_manifest_sha256": target_manifest_digest.removeprefix("sha256:"),
        "snapshot_row_count": EXPECTED_ROWS,
        "target_ids": target_ids,
        "target_ids_sha256": target_ids_hash,
        "target_dates": [item["target_draw_date"] for item in target_list],
        "training_cutoff_ids": [rows[index - 1]["draw_id"] for index in range(MIN_TRAIN, EXPECTED_ROWS)],
        "training_cutoff_dates": [rows[index - 1]["draw_date"] for index in range(MIN_TRAIN, EXPECTED_ROWS)],
        "minimum_training_draws": MIN_TRAIN,
        "strictly_before_target": True,
        "equipment_fields_used": False,
        "holdout_accessed": False,
    }

    status_counts = {key: 0 for key in (
        "scored", "fit_failed", "artifact_invalid", "probability_invalid", "runner_error"
    )}
    indexed = {}
    for row in ledger:
        key = (row.get("model_name"), row.get("zone"), row.get("target_draw_id"))
        if key in indexed:
            raise G3EvidenceBuildError(f"duplicate terminal ledger row {key}")
        if key[0] not in MODEL_IDS.values() or key[1] not in ZONES or key[2] not in set(target_ids):
            raise G3EvidenceBuildError(f"unexpected terminal ledger identity {key}")
        indexed[key] = row
        status = row.get("terminal_status")
        if status not in status_counts:
            raise G3EvidenceBuildError(f"unknown terminal status {status}")
        status_counts[status] += 1
    if len(indexed) != expected_records:
        raise G3EvidenceBuildError("terminal ledger has a missing model × zone × target row")
    for model in MODEL_IDS.values():
        for zone in ZONES:
            for target in target_ids:
                if (model, zone, target) not in indexed:
                    raise G3EvidenceBuildError("terminal ledger is missing a required model × zone × target row")
    if run_manifest.get("terminal_status_counts") != status_counts:
        raise G3EvidenceBuildError("run manifest terminal status counts do not match ledger")

    candidate_artifacts = {}
    for line_number, raw_artifact in enumerate(model_artifacts_raw.splitlines(), 1):
        try:
            artifact = verify_artifact(raw_artifact)
        except Exception as exc:
            raise G3EvidenceBuildError(f"model artifact line {line_number} failed content/schema verification: {exc}") from exc
        if artifact.get("model_family") == "complete_subset_exponential":
            key = (artifact.get("zone"), artifact.get("training_cutoff_draw_id"))
            if key in candidate_artifacts:
                raise G3EvidenceBuildError(f"duplicate candidate model artifact for {key}")
            candidate_artifacts[key] = artifact
    if len(candidate_artifacts) != TARGET_COUNT * len(ZONES):
        raise G3EvidenceBuildError("candidate model-artifact inventory does not cover every target and zone")

    calibration_zones = {}
    calibration_method = "marginal-inclusion-ece-10-bin-v1"
    for zone, population_size, selection_size in (("front", 35, 5), ("back", 12, 2)):
        first_artifact = next(
            artifact for (artifact_zone, _), artifact in candidate_artifacts.items()
            if artifact_zone == zone
        )
        schema = first_artifact.get("feature_schema")
        if not isinstance(schema, dict):
            raise G3EvidenceBuildError(f"{zone}: candidate artifact feature schema missing")
        candidate_names = schema.get("candidate_names")
        include_gap_variance = isinstance(candidate_names, list) and "gap_variance" in candidate_names
        table = build_uniform_feature_table(
            population_size, selection_size,
            include_gap_variance=include_gap_variance,
            feature_schema_version=schema.get("version", "lot-051-symmetric-v1"),
        )
        if (
            schema.get("candidate_names") != list(table.stats.candidate_feature_names)
            or schema.get("names") != list(table.stats.feature_names)
            or len(schema.get("uniform_means", [])) != len(table.stats.all_means)
            or len(schema.get("uniform_population_stds", [])) != len(table.stats.all_standard_deviations)
            or any(abs(float(left) - right) > 1e-12 for left, right in zip(schema["uniform_means"], table.stats.all_means))
            or any(abs(float(left) - right) > 1e-12 for left, right in zip(schema["uniform_population_stds"], table.stats.all_standard_deviations))
        ):
            raise G3EvidenceBuildError(f"{zone}: candidate feature schema differs from exact support table")
        model = ExponentialFamily(table)
        bin_counts = [0] * 10
        bin_predicted = [0.0] * 10
        bin_observed = [0] * 10
        per_target_brier = []
        for target in target_ids:
            record = indexed[(MODEL_IDS["candidate"], zone, target)]
            artifact = candidate_artifacts.get((zone, record.get("training_last_draw_id")))
            if artifact is None:
                raise G3EvidenceBuildError(f"{zone}/{target}: candidate fitted artifact missing")
            if (
                artifact.get("artifact_id") != record.get("artifact_id")
                or artifact.get("artifact_type") != "fitted_model"
                or artifact.get("training_snapshot_sha256") != expected_snapshot_sha256
                or artifact.get("training_cutoff_draw_id") != record.get("training_last_draw_id")
                or artifact.get("training_row_count") != record.get("training_row_count")
                or artifact.get("model_configuration_hash") != record.get("model_configuration_hash")
                or artifact.get("feature_schema_hash") != record.get("feature_schema_hash")
            ):
                raise G3EvidenceBuildError(f"{zone}/{target}: candidate artifact/ledger provenance mismatch")
            theta = artifact.get("parameters", {}).get("theta")
            if not isinstance(theta, list):
                raise G3EvidenceBuildError(f"{zone}/{target}: candidate theta missing")
            probabilities = model.inclusion_marginals(theta)
            observed_subset = record.get("observed_subset")
            if not isinstance(observed_subset, list) or len(observed_subset) != selection_size:
                raise G3EvidenceBuildError(f"{zone}/{target}: observed subset malformed")
            observed = set(observed_subset)
            squared_error = 0.0
            for item_index, probability in enumerate(probabilities, 1):
                outcome = 1 if item_index in observed else 0
                squared_error += (probability - outcome) ** 2
                bin_index = min(9, int(probability * 10))
                bin_counts[bin_index] += 1
                bin_predicted[bin_index] += probability
                bin_observed[bin_index] += outcome
            per_target_brier.append(squared_error / population_size)
        observation_count = TARGET_COUNT * population_size
        bins = []
        weighted_gap = 0.0
        gaps = []
        for index in range(10):
            count = bin_counts[index]
            mean_predicted = bin_predicted[index] / count if count else 0.0
            observed_frequency = bin_observed[index] / count if count else 0.0
            gap = abs(mean_predicted - observed_frequency)
            bins.append({
                "bin_index": index, "lower": index / 10, "upper": (index + 1) / 10,
                "count": count, "mean_predicted_probability": mean_predicted,
                "observed_frequency": observed_frequency, "abs_gap": gap,
            })
            weighted_gap += count * gap
            gaps.append(gap)
        calibration_zones[zone] = {
            "target_count": TARGET_COUNT,
            "population_size": population_size,
            "selection_size": selection_size,
            "observation_count": observation_count,
            "brier_score": sum(per_target_brier) / len(per_target_brier),
            "ece": weighted_gap / observation_count,
            "max_abs_bin_gap": max(gaps),
            "bins": bins,
            "per_target_brier_scores": per_target_brier,
        }
    generated_calibration = {
        "schema": "lottery.g3-calibration/v1",
        "target_ids_sha256": target_ids_hash,
        "method": calibration_method,
        "zones": calibration_zones,
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    staged_ledger = output_dir / "target-score-ledger.jsonl"
    staged_manifest = output_dir / "run_manifest.json"
    staged_artifacts = output_dir / "model-artifacts.jsonl"
    shutil.copyfile(ledger_path, staged_ledger)
    shutil.copyfile(run_manifest_path, staged_manifest)
    shutil.copyfile(model_artifacts_path, staged_artifacts)
    denominator = {
        "schema": "lottery.g3-terminal-ledger-index/v1",
        "target_ids_sha256": target_ids_hash,
        "model_ids": MODEL_IDS,
        "zones": list(ZONES),
        "expected_target_count": TARGET_COUNT,
        "expected_record_count": expected_records,
        "terminal_record_count": len(ledger),
        "status_counts": {key: value for key, value in status_counts.items() if value},
        "ledger": {"path": staged_ledger.name, "sha256": ledger_digest},
        "run_manifest": {"path": staged_manifest.name, "sha256": _sha256(staged_manifest.read_bytes())},
        "model_artifacts": {"path": staged_artifacts.name, "sha256": _sha256(staged_artifacts.read_bytes())},
    }

    bootstrap = run_manifest.get("bootstrap", {})
    seeds = bootstrap.get("seeds_by_zone_and_comparison", {})
    baseline_zones, hypotheses = {}, []
    complete_scores = all(status_counts["scored"] == expected_records for _ in [0])
    for zone in ZONES:
        zone_means, paired = {}, {}
        for role, model in MODEL_IDS.items():
            values = [
                indexed[(model, zone, target)].get("negative_log_score")
                for target in target_ids
                if indexed[(model, zone, target)].get("terminal_status") == "scored"
            ]
            if len(values) == TARGET_COUNT and all(type(value) in (int, float) and math.isfinite(value) for value in values):
                zone_means[role] = sum(values) / len(values)
            else:
                zone_means[role] = None
        intervals = {}
        for comparator in COMPARATORS:
            candidate, reference = MODEL_IDS["candidate"], MODEL_IDS[comparator]
            differences = []
            for target in target_ids:
                left, right = indexed[(candidate, zone, target)], indexed[(reference, zone, target)]
                if left.get("terminal_status") != "scored" or right.get("terminal_status") != "scored":
                    differences = []
                    break
                differences.append(float(left["negative_log_score"]) - float(right["negative_log_score"]))
            if len(differences) == TARGET_COUNT:
                seed = seeds.get(zone, {}).get(comparator)
                if type(seed) is not int:
                    raise G3EvidenceBuildError(f"missing preregistered bootstrap seed for {zone}/{comparator}")
                lower, upper, p_value = _bootstrap(differences, seed)
                intervals[comparator] = {"lower": lower, "upper": upper, "p_value": p_value, "mean": sum(differences) / len(differences)}
                paired[comparator] = differences
            else:
                intervals[comparator] = None
        baseline_zones[zone] = {
            "scored_pairs": len(paired.get("uniform", [])),
            "mean_nll": zone_means,
            "candidate_vs_uniform_mean_delta": intervals["uniform"]["mean"] if intervals["uniform"] else None,
            "candidate_vs_uniform_ci95": [intervals["uniform"]["lower"], intervals["uniform"]["upper"]] if intervals["uniform"] else None,
            "candidate_vs_expanding_ci95_upper": intervals["expanding"]["upper"] if intervals["expanding"] else None,
            "candidate_vs_ewma_ci95_upper": intervals["ewma"]["upper"] if intervals["ewma"] else None,
        }
        if intervals["uniform"]:
            hypotheses.append({
                "hypothesis_id": f"candidate_vs_uniform:{zone}",
                "p_value": intervals["uniform"]["p_value"],
                "ci95_lower": intervals["uniform"]["lower"],
                "ci95_upper": intervals["uniform"]["upper"],
            })

    raw_p = {item["hypothesis_id"]: item["p_value"] for item in hypotheses}
    adjusted = _holm(raw_p) if len(raw_p) == 2 else {}
    for item in hypotheses:
        item["holm_adjusted_p_value"] = adjusted.get(item["hypothesis_id"])

    preregistration = registration
    multiplicity = {
        "schema": "lottery.g3-holm-control/v1",
        "target_ids_sha256": target_ids_hash,
        "bootstrap_replicates": bootstrap.get("replicates"),
        "block_length": bootstrap.get("block_length"),
        "bootstrap_seed": bootstrap.get("seed"),
        "bootstrap_seeds_by_zone": registration.get("bootstrap_seeds_by_zone"),
        "bootstrap_seeds_by_zone_and_comparison": seeds,
        "method": BOOTSTRAP_METHOD,
        "alpha": registration.get("alpha"),
        "hypotheses": hypotheses,
    }

    if calibration_path is not None:
        calibration = _strict_json(calibration_path.read_bytes(), "G3 calibration")
    else:
        calibration = generated_calibration

    reports = {
        "preregistration": preregistration,
        "chronological_targets": chronology,
        "complete_denominator": denominator,
        "baseline_comparison": {
            "schema": "lottery.g3-baseline-comparison/v1",
            "target_ids_sha256": target_ids_hash,
            "target_count": TARGET_COUNT,
            "candidate_model_id": MODEL_IDS["candidate"],
            "baseline_model_ids": {key: MODEL_IDS[key] for key in COMPARATORS},
            "zones": baseline_zones,
        },
        "multiplicity_control": multiplicity,
        "calibration": calibration,
    }
    for name, report in reports.items():
        (output_dir / f"{name}.json").write_bytes(canonicalize(report) + b"\n")

    blockers = []
    if run_manifest.get("experiment_class") != "confirmatory" or run_manifest.get("confirmatory_eligible") is not True:
        blockers.append("run manifest explicitly marks this experiment as exploratory/non-confirmatory")
    if registration.get("outcomes_observed_at_registration") is not False:
        blockers.append("registration is not a verified pre-outcome registration")
    if (registration.get("calibration_method") != calibration_method
            or type(registration.get("calibration_tolerance")) not in (int, float)
            or registration.get("calibration_tolerance", 0) < 0.05
            or registration.get("outcomes_observed_at_registration") is not False):
        blockers.append("marginal-inclusion calibration was computed exploratorily but was not specified in a pre-outcome registration")
    if not complete_scores:
        blockers.append("one or more terminal ledger rows are not scored")
    for zone in ZONES:
        item = baseline_zones[zone]
        if item["candidate_vs_uniform_ci95"] is None or item["candidate_vs_uniform_ci95"][1] >= 0:
            blockers.append(f"{zone} candidate-vs-uniform 95% interval does not lie wholly below zero")
        for comparator in ("expanding", "ewma"):
            upper = item[f"candidate_vs_{comparator}_ci95_upper"]
            if upper is None or upper > 0:
                blockers.append(f"{zone} candidate fails non-regression against {comparator}")
    if len(adjusted) != 2 or any(value is None or value >= registration.get("alpha", 0.05) for value in adjusted.values()):
        blockers.append("the two co-primary Holm-adjusted tests do not both pass alpha")

    summary = {
        "schema": "lottery.g3-evidence-build-summary/v1",
        "status": "BLOCKED" if blockers else "EVIDENCE_COMPLETE_NOT_AUTHORIZED",
        "run_id": run_manifest.get("run_id"),
        "experiment_id": run_manifest.get("experiment_id"),
        "experiment_class": run_manifest.get("experiment_class"),
        "confirmatory_eligible": run_manifest.get("confirmatory_eligible"),
        "snapshot_sha256": expected_snapshot_sha256,
        "target_count_per_zone": TARGET_COUNT,
        "terminal_record_count": len(ledger),
        "model_artifact_count": run_manifest.get("model_artifact_count"),
        "model_artifacts_sha256": model_artifacts_digest,
        "terminal_status_counts": status_counts,
        "candidate_minus_uniform": {
            zone: baseline_zones[zone]["candidate_vs_uniform_mean_delta"] for zone in ZONES
        },
        "holm_adjusted_p_values": adjusted,
        "blockers": blockers,
        "calibration_status": (
            "PREREGISTERED_METHOD_MATCH"
            if registration.get("calibration_method") == calibration_method
            and registration.get("outcomes_observed_at_registration") is False
            else "EXPLORATORY_UNREGISTERED"
        ),
        "calibration_metrics": {
            zone: {
                "brier_score": calibration_zones[zone]["brier_score"],
                "ece": calibration_zones[zone]["ece"],
                "max_abs_bin_gap": calibration_zones[zone]["max_abs_bin_gap"],
            }
            for zone in ZONES
        },
        "readiness_authorized": False,
        "production_ready": False,
    }
    (output_dir / "G3-BUILD-SUMMARY.json").write_bytes(canonicalize(summary) + b"\n")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--expected-snapshot-sha256", required=True)
    parser.add_argument("--run-manifest", type=Path, required=True)
    parser.add_argument("--expected-run-manifest-sha256", required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--model-artifacts", type=Path, required=True)
    parser.add_argument("--registration", type=Path, required=True)
    parser.add_argument("--calibration", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        summary = build_g3_evidence_bundle(
            snapshot_path=args.snapshot, expected_snapshot_sha256=args.expected_snapshot_sha256,
            run_manifest_path=args.run_manifest,
            expected_run_manifest_sha256=args.expected_run_manifest_sha256,
            ledger_path=args.ledger, model_artifacts_path=args.model_artifacts,
            registration_path=args.registration, calibration_path=args.calibration,
            output_dir=args.output_dir,
        )
    except (OSError, G3EvidenceBuildError, ValueError, KeyError, TypeError) as exc:
        print(f"G3_EVIDENCE_BUILD_FAILED: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
