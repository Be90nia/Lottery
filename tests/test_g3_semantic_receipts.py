from __future__ import annotations

import hashlib
import json
import math
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from lottery.subset_model.artifact import canonicalize
from lottery.readiness_receipts import ReceiptVerificationError, _verify_g3_evidence_bundle


class G3SemanticEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.model_ids = {
            "candidate": "exponential_family",
            "uniform": "uniform",
            "expanding": "expanding",
            "ewma": "ewma",
        }
        start, end, count = 9054, 26131, 2649
        self.targets = [
            f"{start + ((end - start) * index // (count - 1)):05d}"
            for index in range(count)
        ]
        self.cutoffs = [f"{int(self.targets[0]) - 1:05d}", *self.targets[:-1]]
        self.target_dates = [(date(2000, 1, 1) + timedelta(days=i)).isoformat() for i in range(count)]
        self.cutoff_dates = [(date(1999, 12, 31)).isoformat(), *self.target_dates[:-1]]
        self.target_hash = hashlib.sha256(canonicalize(self.targets)).hexdigest()
        self.snapshot_hash = "9f4cc51b76fd258dd056e0b86f675192d3d9a41c2901f771cab778c65ec2b6aa"
        self.target_manifest_hash = hashlib.sha256(canonicalize({
            "targets": [
                {"target_draw_id": target, "target_draw_date": self.target_dates[index]}
                for index, target in enumerate(self.targets)
            ]
        })).hexdigest()
        self.prereg = {
            "schema": "lottery.g3-preregistration/v1",
            "protocol_id": "LOT-055-v1",
            "experiment_id": hashlib.sha256(b"g3-fixture-experiment").hexdigest(),
            "experiment_class": "confirmatory",
            "outcomes_observed_at_registration": False,
            "snapshot_sha256": self.snapshot_hash,
            "target_manifest_sha256": self.target_manifest_hash,
            "model_ids": self.model_ids,
            "bootstrap_replicates": 1000,
            "block_length": 50,
            "bootstrap_seed": 20261118,
            "bootstrap_seeds_by_zone": {"front": 20261118, "back": 20261119},
            "bootstrap_seeds_by_zone_and_comparison": {
                "front": {"uniform": 20261118, "expanding": 20261119, "ewma": 20261120},
                "back": {"uniform": 20261119, "expanding": 20261120, "ewma": 20261121},
            },
            "multiplicity_family": [
                "candidate_vs_uniform:front", "candidate_vs_uniform:back"
            ],
            "alpha": 0.05,
            "calibration_method": "marginal-inclusion-ece-10-bin-v1",
            "calibration_tolerance": 0.05,
            "holdout_accessed": False,
        }
        self.chronology = {
            "schema": "lottery.g3-chronological-targets/v1",
            "snapshot_sha256": self.snapshot_hash,
            "target_manifest_sha256": self.target_manifest_hash,
            "snapshot_row_count": 2949,
            "target_ids": self.targets,
            "target_ids_sha256": self.target_hash,
            "target_dates": self.target_dates,
            "training_cutoff_ids": self.cutoffs,
            "training_cutoff_dates": self.cutoff_dates,
            "minimum_training_draws": 300,
            "strictly_before_target": True,
            "equipment_fields_used": False,
            "holdout_accessed": False,
        }
        self.ledger_path = self.root / "g3-terminal-ledger.jsonl"
        rows = []
        for role in ("candidate", "uniform", "expanding", "ewma"):
            model_id = self.model_ids[role]
            for zone in ("front", "back"):
                uniform_nll = math.log(324632 if zone == "front" else 66)
                nll = {
                    "candidate": uniform_nll - 0.2,
                    "uniform": uniform_nll,
                    "expanding": uniform_nll + 0.1,
                    "ewma": uniform_nll + 0.1,
                }[role]
                for index, target in enumerate(self.targets):
                    row = {
                        "run_id": "g3-fixture-run",
                        "target_draw_id": target,
                        "target_draw_date": self.target_dates[index],
                        "zone": zone,
                        "model_family": {
                            "candidate": "complete_subset_exponential",
                            "uniform": "uniform_analytic",
                            "expanding": "conditional_poisson",
                            "ewma": "conditional_poisson",
                        }[role],
                        "model_name": model_id,
                        "artifact_id": None if role == "uniform" else "sha256:" + hashlib.sha256(
                            (role + zone + target).encode()
                        ).hexdigest(),
                        "diagnostic_ref": None,
                        "snapshot_sha256": self.snapshot_hash,
                        "training_first_draw_id": "07001",
                        "training_last_draw_id": self.cutoffs[index],
                        "training_row_count": 300 + index,
                        "training_dates_strictly_before_target": True,
                        "model_configuration_hash": "sha256:" + "d" * 64,
                        "feature_schema_hash": "sha256:" + "e" * 64,
                        "optimizer_solver_status": "analytic_closed_form" if role == "uniform" else "converged",
                        "converged": True,
                        "failure_reason": None,
                        "terminal_status": "scored",
                        "observed_subset": [1, 2, 3, 4, 5] if zone == "front" else [1, 2],
                        "predicted_log_probability": -nll,
                        "negative_log_score": nll,
                        "pairing_key": "g3-fixture-run:" + zone + ":" + target,
                    }
                    row["record_sha256"] = "sha256:" + hashlib.sha256(canonicalize(row)).hexdigest()
                    rows.append(row)
        self.ledger_raw = b"".join(canonicalize(row) + b"\n" for row in rows)
        self.ledger_path.write_bytes(self.ledger_raw)
        self.model_artifacts_path = self.root / "g3-model-artifacts.jsonl"
        self.model_artifacts_raw = b"{}\n" * (2649 * 2 * 3)
        self.model_artifacts_path.write_bytes(self.model_artifacts_raw)
        self.run_manifest_path = self.root / "g3-run-manifest.json"
        self.run_manifest = {
            "schema": "lot-055-run-manifest-v1",
            "run_id": "g3-fixture-run",
            "experiment_id": "g3-fixture-experiment",
            "experiment_class": "confirmatory",
            "confirmatory_eligible": True,
            "confirmatory_ineligibility_reason": None,
            "snapshot": {"sha256": self.snapshot_hash, "row_count": 2949},
            "target_manifest": {
                "target_count_per_zone": 2649,
                "first_target_draw_id": self.targets[0],
                "last_target_draw_id": self.targets[-1],
                "target_list_sha256": "sha256:" + self.target_manifest_hash,
            },
            "bootstrap": {
                "replicates": 1000, "block_length": 50, "seed": 20261118,
                "seeds_by_zone_and_comparison": {
                    "front": {"uniform": 20261118, "expanding": 20261119, "ewma": 20261120},
                    "back": {"uniform": 20261119, "expanding": 20261120, "ewma": 20261121},
                },
            },
            "models": [
                {
                    "zone": zone, "model_name": self.model_ids[role],
                    "model_family": {
                        "candidate": "complete_subset_exponential",
                        "uniform": "uniform_analytic",
                        "expanding": "conditional_poisson",
                        "ewma": "conditional_poisson",
                    }[role],
                    "model_configuration_hash": "sha256:" + "d" * 64,
                    "feature_schema_hash": "sha256:" + "e" * 64,
                }
                for zone in ("front", "back")
                for role in ("candidate", "uniform", "expanding", "ewma")
            ],
            "model_artifact_count": 2649 * 2 * 3,
            "expected_target_record_count": 2649 * 4 * 2,
            "actual_target_record_count": 2649 * 4 * 2,
            "terminal_status_counts": {
                "scored": 2649 * 4 * 2, "fit_failed": 0,
                "artifact_invalid": 0, "probability_invalid": 0, "runner_error": 0,
            },
            "output_files": {
                "target-score-ledger.jsonl": {
                    "sha256": hashlib.sha256(self.ledger_raw).hexdigest(),
                    "bytes": len(self.ledger_raw),
                },
                "model-artifacts.jsonl": {
                    "sha256": hashlib.sha256(self.model_artifacts_raw).hexdigest(),
                    "bytes": len(self.model_artifacts_raw),
                },
            },
        }
        self.run_manifest["manifest_sha256"] = "sha256:" + hashlib.sha256(
            canonicalize(self.run_manifest)
        ).hexdigest()
        self.run_manifest_raw = canonicalize(self.run_manifest) + b"\n"
        self.run_manifest_path.write_bytes(self.run_manifest_raw)
        self.denominator = {
            "schema": "lottery.g3-terminal-ledger-index/v1",
            "target_ids_sha256": self.target_hash,
            "model_ids": self.model_ids,
            "zones": ["front", "back"],
            "expected_target_count": 2649,
            "expected_record_count": 2649 * 4 * 2,
            "terminal_record_count": 2649 * 4 * 2,
            "status_counts": {"scored": 2649 * 4 * 2},
            "ledger": {
                "path": self.ledger_path.name,
                "sha256": hashlib.sha256(self.ledger_raw).hexdigest(),
            },
            "run_manifest": {
                "path": self.run_manifest_path.name,
                "sha256": hashlib.sha256(self.run_manifest_raw).hexdigest(),
            },
            "model_artifacts": {
                "path": self.model_artifacts_path.name,
                "sha256": hashlib.sha256(self.model_artifacts_raw).hexdigest(),
            },
        }
        zones = {}
        for zone in ("front", "back"):
            uniform_nll = math.log(324632 if zone == "front" else 66)
            zones[zone] = {
                "scored_pairs": 2649,
                "mean_nll": {
                    "candidate": uniform_nll - 0.2,
                    "uniform": uniform_nll,
                    "expanding": uniform_nll + 0.1,
                    "ewma": uniform_nll + 0.1,
                },
                "candidate_vs_uniform_mean_delta": -0.2,
                "candidate_vs_uniform_ci95": [-0.2, -0.2],
                "candidate_vs_expanding_ci95_upper": -0.3,
                "candidate_vs_ewma_ci95_upper": -0.3,
            }
        self.baseline = {
            "schema": "lottery.g3-baseline-comparison/v1",
            "target_ids_sha256": self.target_hash,
            "target_count": 2649,
            "candidate_model_id": self.model_ids["candidate"],
            "baseline_model_ids": {
                "uniform": self.model_ids["uniform"],
                "expanding": self.model_ids["expanding"],
                "ewma": self.model_ids["ewma"],
            },
            "zones": zones,
        }
        self.multiplicity = {
            "schema": "lottery.g3-holm-control/v1",
            "target_ids_sha256": self.target_hash,
            "bootstrap_replicates": 1000,
            "block_length": 50,
            "bootstrap_seed": 20261118,
            "bootstrap_seeds_by_zone": {"front": 20261118, "back": 20261119},
            "bootstrap_seeds_by_zone_and_comparison": {
                "front": {"uniform": 20261118, "expanding": 20261119, "ewma": 20261120},
                "back": {"uniform": 20261119, "expanding": 20261120, "ewma": 20261121},
            },
            "method": "holm-step-down-one-sided-centered-moving-block-bootstrap",
            "alpha": 0.05,
            "hypotheses": [
                {
                    "hypothesis_id": "candidate_vs_uniform:front",
                    "p_value": 1 / 1001,
                    "holm_adjusted_p_value": 2 / 1001,
                    "ci95_lower": -0.2,
                    "ci95_upper": -0.2,
                },
                {
                    "hypothesis_id": "candidate_vs_uniform:back",
                    "p_value": 1 / 1001,
                    "holm_adjusted_p_value": 2 / 1001,
                    "ci95_lower": -0.2,
                    "ci95_upper": -0.2,
                },
            ],
        }
        self.calibration = {
            "schema": "lottery.g3-calibration/v1",
            "target_ids_sha256": self.target_hash,
            "method": "marginal-inclusion-ece-10-bin-v1",
            "zones": {
                zone: {
                    "target_count": 2649,
                    "population_size": population_size,
                    "selection_size": selection_size,
                    "observation_count": 2649 * population_size,
                    "brier_score": 0.2,
                    "ece": 0.0,
                    "max_abs_bin_gap": 0.0,
                    "per_target_brier_scores": [0.2] * 2649,
                    "bins": [
                        {
                            "bin_index": index, "lower": index / 10, "upper": (index + 1) / 10,
                            "count": (2649 * population_size) // 10 + (1 if index < (2649 * population_size) % 10 else 0),
                            "mean_predicted_probability": (index + 0.5) / 10,
                            "observed_frequency": (index + 0.5) / 10,
                            "abs_gap": 0.0,
                        }
                        for index in range(10)
                    ],
                }
                for zone, population_size, selection_size in (("front", 35, 5), ("back", 12, 2))
            },
        }
        self.raw = {
            "preregistration": canonicalize(self.prereg),
            "chronological_targets": canonicalize(self.chronology),
            "complete_denominator": canonicalize(self.denominator),
            "baseline_comparison": canonicalize(self.baseline),
            "multiplicity_control": canonicalize(self.multiplicity),
            "calibration": canonicalize(self.calibration),
        }

    def _refresh_ledger_and_manifest_bindings(self):
        self.denominator["ledger"]["sha256"] = hashlib.sha256(self.ledger_path.read_bytes()).hexdigest()
        self.run_manifest["output_files"]["target-score-ledger.jsonl"] = {
            "sha256": hashlib.sha256(self.ledger_path.read_bytes()).hexdigest(),
            "bytes": len(self.ledger_path.read_bytes()),
        }
        body = {key: value for key, value in self.run_manifest.items() if key != "manifest_sha256"}
        self.run_manifest["manifest_sha256"] = "sha256:" + hashlib.sha256(canonicalize(body)).hexdigest()
        self.run_manifest_raw = canonicalize(self.run_manifest) + b"\n"
        self.run_manifest_path.write_bytes(self.run_manifest_raw)
        self.denominator["run_manifest"]["sha256"] = hashlib.sha256(self.run_manifest_raw).hexdigest()
        self.raw["complete_denominator"] = canonicalize(self.denominator)

    def verify(self):
        return _verify_g3_evidence_bundle(self.raw, self.root)

    def test_complete_g3_evidence_reconciles_full_2649_target_ledger(self):
        verified = self.verify()
        self.assertEqual(verified, [
            {"path": self.ledger_path.name, "sha256": hashlib.sha256(self.ledger_raw).hexdigest()},
            {"path": self.run_manifest_path.name, "sha256": hashlib.sha256(self.run_manifest_raw).hexdigest()},
            {"path": self.model_artifacts_path.name, "sha256": hashlib.sha256(self.model_artifacts_raw).hexdigest()},
        ])

    def test_future_or_wrong_training_cutoff_is_rejected(self):
        lines = self.ledger_raw.splitlines()
        row = json.loads(lines[0])
        row["training_last_draw_id"] = row["target_draw_id"]
        row["record_sha256"] = "sha256:" + hashlib.sha256(canonicalize({
            key: value for key, value in row.items() if key != "record_sha256"
        })).hexdigest()
        lines[0] = canonicalize(row)
        changed = b"\n".join(lines) + b"\n"
        self.ledger_path.write_bytes(changed)
        self._refresh_ledger_and_manifest_bindings()
        with self.assertRaisesRegex(ReceiptVerificationError, "violates target/cutoff/model identity"):
            self.verify()

    def test_missing_terminal_record_is_rejected(self):
        changed = b"\n".join(self.ledger_raw.splitlines()[:-1]) + b"\n"
        self.ledger_path.write_bytes(changed)
        self._refresh_ledger_and_manifest_bindings()
        with self.assertRaisesRegex(ReceiptVerificationError, "line count differs"):
            self.verify()

    def test_non_uniform_uniform_baseline_is_rejected(self):
        lines = self.ledger_raw.splitlines()
        row = json.loads(lines[2649 * 2])
        row["negative_log_score"] += 0.01
        row["predicted_log_probability"] = -row["negative_log_score"]
        row["record_sha256"] = "sha256:" + hashlib.sha256(canonicalize({
            key: value for key, value in row.items() if key != "record_sha256"
        })).hexdigest()
        lines[2649 * 2] = canonicalize(row)
        changed = b"\n".join(lines) + b"\n"
        self.ledger_path.write_bytes(changed)
        self._refresh_ledger_and_manifest_bindings()
        with self.assertRaisesRegex(ReceiptVerificationError, "uniform exact-set baseline"):
            self.verify()

    def test_holm_adjusted_p_values_must_match_preregistered_family(self):
        self.multiplicity["hypotheses"][0]["holm_adjusted_p_value"] = 0.004
        self.raw["multiplicity_control"] = canonicalize(self.multiplicity)
        with self.assertRaisesRegex(ReceiptVerificationError, "Holm adjusted p-values"):
            self.verify()

    def test_calibration_requires_all_target_level_diagnostics(self):
        self.calibration["zones"]["front"]["per_target_brier_scores"].pop()
        self.raw["calibration"] = canonicalize(self.calibration)
        with self.assertRaisesRegex(ReceiptVerificationError, "calibration target coverage/Brier score is invalid"):
            self.verify()

    def test_exploratory_run_manifest_cannot_be_promoted_by_confirmatory_receipt(self):
        self.run_manifest["experiment_class"] = "exploratory_diagnostic"
        self.run_manifest["confirmatory_eligible"] = False
        body = {key: value for key, value in self.run_manifest.items() if key != "manifest_sha256"}
        self.run_manifest["manifest_sha256"] = "sha256:" + hashlib.sha256(canonicalize(body)).hexdigest()
        self.run_manifest_raw = canonicalize(self.run_manifest) + b"\n"
        self.run_manifest_path.write_bytes(self.run_manifest_raw)
        self.denominator["run_manifest"]["sha256"] = hashlib.sha256(self.run_manifest_raw).hexdigest()
        self.raw["complete_denominator"] = canonicalize(self.denominator)
        with self.assertRaisesRegex(ReceiptVerificationError, "run manifest is missing, non-confirmatory"):
            self.verify()

    def test_run_manifest_ledger_digest_cannot_be_substituted(self):
        self.run_manifest["output_files"]["target-score-ledger.jsonl"]["sha256"] = "0" * 64
        body = {key: value for key, value in self.run_manifest.items() if key != "manifest_sha256"}
        self.run_manifest["manifest_sha256"] = "sha256:" + hashlib.sha256(canonicalize(body)).hexdigest()
        self.run_manifest_raw = canonicalize(self.run_manifest) + b"\n"
        self.run_manifest_path.write_bytes(self.run_manifest_raw)
        self.denominator["run_manifest"]["sha256"] = hashlib.sha256(self.run_manifest_raw).hexdigest()
        self.raw["complete_denominator"] = canonicalize(self.denominator)
        with self.assertRaisesRegex(ReceiptVerificationError, "run manifest is missing, non-confirmatory"):
            self.verify()

    def test_posthoc_or_holdout_tainted_registration_is_rejected(self):
        self.prereg["outcomes_observed_at_registration"] = True
        self.raw["preregistration"] = canonicalize(self.prereg)
        with self.assertRaisesRegex(ReceiptVerificationError, "pre-outcome confirmatory"):
            self.verify()


if __name__ == "__main__":
    unittest.main()
