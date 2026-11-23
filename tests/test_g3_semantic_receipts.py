from __future__ import annotations

import hashlib
import json
import math
import tempfile
import unittest
from pathlib import Path

from lottery.subset_model.artifact import canonicalize
from lottery.readiness_receipts import ReceiptVerificationError, _verify_g3_evidence_bundle


class G3SemanticEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.model_ids = {
            "candidate": "a" * 64,
            "uniform": "uniform-exact-v1",
            "expanding": "expanding-frequency-v1",
            "ewma": "ewma-conditional-poisson-v1",
        }
        start, end, count = 9054, 26131, 2649
        self.targets = [
            f"{start + ((end - start) * index // (count - 1)):05d}"
            for index in range(count)
        ]
        self.cutoffs = [f"{int(self.targets[0]) - 1:05d}", *self.targets[:-1]]
        self.target_hash = hashlib.sha256(canonicalize(self.targets)).hexdigest()
        self.snapshot_hash = "9f4cc51b76fd258dd056e0b86f675192d3d9a41c2901f771cab778c65ec2b6aa"
        self.target_manifest_hash = "b" * 64
        self.prereg = {
            "schema": "lottery.g3-preregistration/v1",
            "protocol_id": "LOT-055-v1",
            "experiment_id": "c" * 64,
            "experiment_class": "confirmatory",
            "outcomes_observed_at_registration": False,
            "snapshot_sha256": self.snapshot_hash,
            "target_manifest_sha256": self.target_manifest_hash,
            "model_ids": self.model_ids,
            "bootstrap_replicates": 1000,
            "block_length": 50,
            "bootstrap_seed": 20261118,
            "multiplicity_family": [
                "candidate_vs_uniform:front", "candidate_vs_uniform:back"
            ],
            "alpha": 0.05,
            "calibration_method": "preregistered-randomized-pit-v1",
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
            "training_cutoff_ids": self.cutoffs,
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
                    rows.append({
                        "model_id": model_id,
                        "zone": zone,
                        "target_draw_id": target,
                        "pairing_key": zone + ":" + target,
                        "training_count": 300 + index,
                        "train_cutoff_draw_id": self.cutoffs[index],
                        "strictly_before_target": True,
                        "status": "scored",
                        "nll": nll,
                    })
        self.ledger_raw = b"".join(canonicalize(row) + b"\n" for row in rows)
        self.ledger_path.write_bytes(self.ledger_raw)
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
                "candidate_vs_uniform_ci95": [-0.21, -0.19],
                "candidate_vs_expanding_ci95_upper": -0.2,
                "candidate_vs_ewma_ci95_upper": -0.2,
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
            "method": "holm-step-down-one-sided-centered-moving-block-bootstrap",
            "alpha": 0.05,
            "hypotheses": [
                {
                    "hypothesis_id": "candidate_vs_uniform:front",
                    "p_value": 0.001,
                    "holm_adjusted_p_value": 0.002,
                    "ci95_lower": -0.21,
                    "ci95_upper": -0.19,
                },
                {
                    "hypothesis_id": "candidate_vs_uniform:back",
                    "p_value": 0.002,
                    "holm_adjusted_p_value": 0.002,
                    "ci95_lower": -0.21,
                    "ci95_upper": -0.19,
                },
            ],
        }
        self.calibration = {
            "schema": "lottery.g3-calibration/v1",
            "target_ids_sha256": self.target_hash,
            "method": "preregistered-randomized-pit-v1",
            "zones": {
                "front": {"target_count": 2649, "max_abs_error": 0.01},
                "back": {"target_count": 2649, "max_abs_error": 0.01},
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

    def verify(self):
        return _verify_g3_evidence_bundle(self.raw, self.root)

    def test_complete_g3_evidence_reconciles_full_2649_target_ledger(self):
        verified = self.verify()
        self.assertEqual(verified, [{
            "path": self.ledger_path.name,
            "sha256": hashlib.sha256(self.ledger_raw).hexdigest(),
        }])

    def test_future_or_wrong_training_cutoff_is_rejected(self):
        lines = self.ledger_raw.splitlines()
        row = json.loads(lines[0])
        row["train_cutoff_draw_id"] = row["target_draw_id"]
        lines[0] = canonicalize(row)
        changed = b"\n".join(lines) + b"\n"
        self.ledger_path.write_bytes(changed)
        self.denominator["ledger"]["sha256"] = hashlib.sha256(changed).hexdigest()
        self.raw["complete_denominator"] = canonicalize(self.denominator)
        with self.assertRaisesRegex(ReceiptVerificationError, "violates target/cutoff pairing"):
            self.verify()

    def test_missing_terminal_record_is_rejected(self):
        changed = b"\n".join(self.ledger_raw.splitlines()[:-1]) + b"\n"
        self.ledger_path.write_bytes(changed)
        self.denominator["ledger"]["sha256"] = hashlib.sha256(changed).hexdigest()
        self.raw["complete_denominator"] = canonicalize(self.denominator)
        with self.assertRaisesRegex(ReceiptVerificationError, "line count differs"):
            self.verify()

    def test_non_uniform_uniform_baseline_is_rejected(self):
        lines = self.ledger_raw.splitlines()
        row = json.loads(lines[2649 * 2])
        row["nll"] += 0.01
        lines[2649 * 2] = canonicalize(row)
        changed = b"\n".join(lines) + b"\n"
        self.ledger_path.write_bytes(changed)
        self.denominator["ledger"]["sha256"] = hashlib.sha256(changed).hexdigest()
        self.raw["complete_denominator"] = canonicalize(self.denominator)
        with self.assertRaisesRegex(ReceiptVerificationError, "uniform exact-set baseline"):
            self.verify()

    def test_holm_adjusted_p_values_must_match_preregistered_family(self):
        self.multiplicity["hypotheses"][0]["holm_adjusted_p_value"] = 0.003
        self.raw["multiplicity_control"] = canonicalize(self.multiplicity)
        with self.assertRaisesRegex(ReceiptVerificationError, "Holm adjusted p-values"):
            self.verify()

    def test_posthoc_or_holdout_tainted_registration_is_rejected(self):
        self.prereg["outcomes_observed_at_registration"] = True
        self.raw["preregistration"] = canonicalize(self.prereg)
        with self.assertRaisesRegex(ReceiptVerificationError, "pre-outcome confirmatory"):
            self.verify()


if __name__ == "__main__":
    unittest.main()
