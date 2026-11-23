from __future__ import annotations

import hashlib
import json
import math
import tempfile
import unittest
from pathlib import Path

from lottery.subset_model.artifact import canonicalize
from lottery.readiness_receipts import (
    FAULTS, GATE_REQUIRED_CHECKS, GATE_TYPES, ReceiptVerificationError, verify_receipt_set,
    verify_release_manifest_v2,
)


_G3_FIXTURE_CACHE: tuple[dict[str, bytes], bytes, bytes, bytes] | None = None


def _build_g3_fixture(root: Path) -> dict[str, bytes]:
    global _G3_FIXTURE_CACHE
    ledger_path = root / "G3-terminal-ledger.jsonl"
    if _G3_FIXTURE_CACHE is not None:
        ledger_path.write_bytes(_G3_FIXTURE_CACHE[1])
        (root / "G3-run-manifest.json").write_bytes(_G3_FIXTURE_CACHE[2])
        (root / "G3-model-artifacts.jsonl").write_bytes(_G3_FIXTURE_CACHE[3])
        return _G3_FIXTURE_CACHE[0]
    model_ids = {
        "candidate": "exponential_family", "uniform": "uniform",
        "expanding": "expanding", "ewma": "ewma",
    }
    targets = [
        f"{9054 + (17077 * index // 2648):05d}" for index in range(2649)
    ]
    cutoffs = [f"{int(targets[0]) - 1:05d}", *targets[:-1]]
    from datetime import date, timedelta
    target_dates = [(date(2000, 1, 1) + timedelta(days=i)).isoformat() for i in range(2649)]
    cutoff_dates = [date(1999, 12, 31).isoformat(), *target_dates[:-1]]
    target_hash = hashlib.sha256(canonicalize(targets)).hexdigest()
    snapshot_hash = "9f4cc51b76fd258dd056e0b86f675192d3d9a41c2901f771cab778c65ec2b6aa"
    target_manifest_hash = hashlib.sha256(canonicalize({
        "targets": [
            {"target_draw_id": target, "target_draw_date": target_dates[index]}
            for index, target in enumerate(targets)
        ]
    })).hexdigest()
    prereg = {
        "schema": "lottery.g3-preregistration/v1", "protocol_id": "LOT-055-v1",
        "experiment_id": hashlib.sha256(b"g3-fixture-experiment").hexdigest(), "experiment_class": "confirmatory",
        "outcomes_observed_at_registration": False, "snapshot_sha256": snapshot_hash,
        "target_manifest_sha256": target_manifest_hash, "model_ids": model_ids,
        "bootstrap_replicates": 1000, "block_length": 50, "bootstrap_seed": 20261118,
        "bootstrap_seeds_by_zone": {"front": 20261118, "back": 20261119},
        "bootstrap_seeds_by_zone_and_comparison": {
            "front": {"uniform": 20261118, "expanding": 20261119, "ewma": 20261120},
            "back": {"uniform": 20261119, "expanding": 20261120, "ewma": 20261121},
        },
        "multiplicity_family": ["candidate_vs_uniform:front", "candidate_vs_uniform:back"],
        "alpha": 0.05, "calibration_method": "preregistered-randomized-pit-v1",
        "calibration_tolerance": 0.05, "holdout_accessed": False,
    }
    chronology = {
        "schema": "lottery.g3-chronological-targets/v1", "snapshot_sha256": snapshot_hash,
        "target_manifest_sha256": target_manifest_hash, "snapshot_row_count": 2949,
        "target_ids": targets, "target_ids_sha256": target_hash,
        "target_dates": target_dates, "training_cutoff_ids": cutoffs,
        "training_cutoff_dates": cutoff_dates, "minimum_training_draws": 300,
        "strictly_before_target": True, "equipment_fields_used": False, "holdout_accessed": False,
    }
    rows = []
    for role in ("candidate", "uniform", "expanding", "ewma"):
        model_id = model_ids[role]
        for zone in ("front", "back"):
            uniform_nll = math.log(324632 if zone == "front" else 66)
            nll = {
                "candidate": uniform_nll - 0.2, "uniform": uniform_nll,
                "expanding": uniform_nll + 0.1, "ewma": uniform_nll + 0.1,
            }[role]
            for index, target in enumerate(targets):
                row = {
                    "run_id": "g3-fixture-run", "target_draw_id": target,
                    "target_draw_date": target_dates[index], "zone": zone,
                    "model_family": {
                        "candidate": "complete_subset_exponential",
                        "uniform": "uniform_analytic",
                        "expanding": "conditional_poisson", "ewma": "conditional_poisson",
                    }[role],
                    "model_name": model_id,
                    "artifact_id": None if role == "uniform" else "sha256:" + hashlib.sha256(
                        (role + zone + target).encode()
                    ).hexdigest(),
                    "diagnostic_ref": None, "snapshot_sha256": snapshot_hash,
                    "training_first_draw_id": "07001", "training_last_draw_id": cutoffs[index],
                    "training_row_count": 300 + index, "training_dates_strictly_before_target": True,
                    "model_configuration_hash": "sha256:" + "d" * 64,
                    "feature_schema_hash": "sha256:" + "e" * 64,
                    "optimizer_solver_status": "analytic_closed_form" if role == "uniform" else "converged",
                    "converged": True, "failure_reason": None, "terminal_status": "scored",
                    "observed_subset": [1, 2, 3, 4, 5] if zone == "front" else [1, 2],
                    "predicted_log_probability": -nll, "negative_log_score": nll,
                    "pairing_key": "g3-fixture-run:" + zone + ":" + target,
                }
                row["record_sha256"] = "sha256:" + hashlib.sha256(canonicalize(row)).hexdigest()
                rows.append(row)
    ledger_raw = b"".join(canonicalize(row) + b"\n" for row in rows)
    ledger_path.write_bytes(ledger_raw)
    model_artifacts_path = root / "G3-model-artifacts.jsonl"
    model_artifacts_raw = b"{}\n" * 15894
    model_artifacts_path.write_bytes(model_artifacts_raw)
    run_manifest_path = root / "G3-run-manifest.json"
    run_manifest = {
        "schema": "lot-055-run-manifest-v1",
        "run_id": "g3-fixture-run",
        "experiment_id": "g3-fixture-experiment",
        "experiment_class": "confirmatory",
        "confirmatory_eligible": True,
        "confirmatory_ineligibility_reason": None,
        "snapshot": {"sha256": snapshot_hash, "row_count": 2949},
        "target_manifest": {
            "target_count_per_zone": 2649,
            "first_target_draw_id": targets[0],
            "last_target_draw_id": targets[-1],
            "target_list_sha256": "sha256:" + target_manifest_hash,
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
                "zone": zone, "model_name": model_ids[role],
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
        "model_artifact_count": 15894,
        "expected_target_record_count": 21192,
        "actual_target_record_count": 21192,
        "terminal_status_counts": {
            "scored": 21192, "fit_failed": 0,
            "artifact_invalid": 0, "probability_invalid": 0, "runner_error": 0,
        },
        "output_files": {
            "target-score-ledger.jsonl": {
                "sha256": hashlib.sha256(ledger_raw).hexdigest(),
                "bytes": len(ledger_raw),
            },
            "model-artifacts.jsonl": {
                "sha256": hashlib.sha256(model_artifacts_raw).hexdigest(),
                "bytes": len(model_artifacts_raw),
            },
        },
    }
    run_manifest["manifest_sha256"] = "sha256:" + hashlib.sha256(
        canonicalize(run_manifest)
    ).hexdigest()
    run_manifest_raw = canonicalize(run_manifest) + b"\n"
    run_manifest_path.write_bytes(run_manifest_raw)
    denominator = {
        "schema": "lottery.g3-terminal-ledger-index/v1", "target_ids_sha256": target_hash,
        "model_ids": model_ids, "zones": ["front", "back"], "expected_target_count": 2649,
        "expected_record_count": 21192, "terminal_record_count": 21192,
        "status_counts": {"scored": 21192},
        "ledger": {"path": ledger_path.name, "sha256": hashlib.sha256(ledger_raw).hexdigest()},
        "run_manifest": {
            "path": run_manifest_path.name,
            "sha256": hashlib.sha256(run_manifest_raw).hexdigest(),
        },
        "model_artifacts": {
            "path": model_artifacts_path.name,
            "sha256": hashlib.sha256(model_artifacts_raw).hexdigest(),
        },
    }
    zone_reports = {}
    for zone in ("front", "back"):
        uniform_nll = math.log(324632 if zone == "front" else 66)
        zone_reports[zone] = {
            "scored_pairs": 2649,
            "mean_nll": {
                "candidate": uniform_nll - 0.2, "uniform": uniform_nll,
                "expanding": uniform_nll + 0.1, "ewma": uniform_nll + 0.1,
            },
            "candidate_vs_uniform_mean_delta": -0.2,
            "candidate_vs_uniform_ci95": [-0.2, -0.2],
            "candidate_vs_expanding_ci95_upper": -0.3,
            "candidate_vs_ewma_ci95_upper": -0.3,
        }
    baseline = {
        "schema": "lottery.g3-baseline-comparison/v1", "target_ids_sha256": target_hash,
        "target_count": 2649, "candidate_model_id": model_ids["candidate"],
        "baseline_model_ids": {key: model_ids[key] for key in ("uniform", "expanding", "ewma")},
        "zones": zone_reports,
    }
    multiplicity = {
        "schema": "lottery.g3-holm-control/v1", "target_ids_sha256": target_hash,
        "bootstrap_replicates": 1000, "block_length": 50, "bootstrap_seed": 20261118,
        "bootstrap_seeds_by_zone": {"front": 20261118, "back": 20261119},
        "bootstrap_seeds_by_zone_and_comparison": {
            "front": {"uniform": 20261118, "expanding": 20261119, "ewma": 20261120},
            "back": {"uniform": 20261119, "expanding": 20261120, "ewma": 20261121},
        },
        "method": "holm-step-down-one-sided-centered-moving-block-bootstrap", "alpha": 0.05,
        "hypotheses": [
            {"hypothesis_id": "candidate_vs_uniform:front", "p_value": 1 / 1001,
             "holm_adjusted_p_value": 2 / 1001, "ci95_lower": -0.2, "ci95_upper": -0.2},
            {"hypothesis_id": "candidate_vs_uniform:back", "p_value": 1 / 1001,
             "holm_adjusted_p_value": 2 / 1001, "ci95_lower": -0.2, "ci95_upper": -0.2},
        ],
    }
    calibration = {
        "schema": "lottery.g3-calibration/v1", "target_ids_sha256": target_hash,
        "method": "preregistered-randomized-pit-v1",
        "zones": {
            "front": {"target_count": 2649, "per_target_abs_errors": [0.01] * 2649, "max_abs_error": 0.01},
            "back": {"target_count": 2649, "per_target_abs_errors": [0.01] * 2649, "max_abs_error": 0.01},
        },
    }
    reports = {
        "preregistration": prereg, "chronological_targets": chronology,
        "complete_denominator": denominator, "baseline_comparison": baseline,
        "multiplicity_control": multiplicity, "calibration": calibration,
    }
    encoded = {key: canonicalize(value) for key, value in reports.items()}
    _G3_FIXTURE_CACHE = (encoded, ledger_raw, run_manifest_raw, model_artifacts_raw)
    return encoded


class TypedReadinessReceiptTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.manifest = {
            "schema": "lottery.release-manifest/v1",
            "release_id": "receipt-test-001",
            "release_ref": "a" * 40,
            "source_commit": "a" * 40,
            "workflow_policy_sha256": "1" * 64,
            "dependency_lock_sha256": "2" * 64,
            "readiness_policy_sha256": "3" * 64,
            "snapshot_sha256": "9f4cc51b76fd258dd056e0b86f675192d3d9a41c2901f771cab778c65ec2b6aa",
            "lot042_accessed": False,
        }
        self.gates = []
        self.faults = []
        g3_evidence = _build_g3_fixture(self.root)
        for gate_id, receipt_type in GATE_TYPES.items():
            name = gate_id + ".json"
            receipt = {
                "schema": "lottery.gate-receipt/v1",
                "receipt_type": receipt_type,
                "gate_id": gate_id,
                "release_id": self.manifest["release_id"],
                "source_commit": self.manifest["source_commit"],
                "release_manifest_sha256": "sha256:" + hashlib.sha256(canonicalize(self.manifest)).hexdigest(),
                "result": "PASS",
                "checks": [],
                "generated_at_utc": "2026-11-23T12:00:00Z",
            }
            for check_id in GATE_REQUIRED_CHECKS[gate_id]:
                evidence_name = gate_id + "-" + check_id + ".txt"
                if gate_id == "G3":
                    evidence_raw = g3_evidence[check_id]
                elif gate_id == "G2":
                    zones = [
                        {"zone": "front", "population_size": 35, "selection_size": 5,
                         "expected_support_count": 324632, "enumerated_support_count": 324632},
                        {"zone": "back", "population_size": 12, "selection_size": 2,
                         "expected_support_count": 66, "enumerated_support_count": 66},
                    ]
                    if check_id == "full_support":
                        evidence = {"schema": "lottery.g2-full-support/v1", "zones": zones}
                    elif check_id == "normalization":
                        evidence = {"schema": "lottery.g2-normalization/v1", "zones": [
                            {"zone": zone, "probability_sum": 1.0, "minimum_probability": 0.0, "max_abs_error": 0.0}
                            for zone in ("front", "back")
                        ]}
                    elif check_id == "exact_subset_probability":
                        evidence = {"schema": "lottery.g2-exact-probability/v1", "zones": [
                            {"zone": "front", "enumerated_subset_count": 324632, "probability_sum": 1.0, "minimum_probability": 0.0, "max_abs_oracle_error": 0.0},
                            {"zone": "back", "enumerated_subset_count": 66, "probability_sum": 1.0, "minimum_probability": 0.0, "max_abs_oracle_error": 0.0},
                        ]}
                    elif check_id == "conditional_poisson":
                        evidence = {"schema": "lottery.g2-conditional-poisson/v1", "algorithm": "log_elementary_symmetric_dp", "oracle_cases": 100, "max_abs_probability_error": 0.0, "max_abs_marginal_error": 0.0, "all_finite": True}
                    elif check_id == "deterministic_sampler":
                        evidence = {"schema": "lottery.g2-deterministic-sampler/v1", "algorithm": "backward_dp", "seed": 7, "samples_per_zone": 1000, "replay_identical": True, "invalid_sample_count": 0}
                    else:
                        evidence = {"schema": "lottery.g2-numerical-stability/v1", "stress_cases": 100, "non_finite_count": 0, "max_abs_normalization_error": 0.0, "minimum_probability": 0.0}
                    evidence_raw = json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode()
                else:
                    evidence_raw = (gate_id + ":" + check_id + "\\n").encode()
                (self.root / evidence_name).write_bytes(evidence_raw)
                receipt["checks"].append({
                    "check_id": check_id,
                    "status": "PASS",
                    "evidence": {
                        "path": evidence_name,
                        "sha256": hashlib.sha256(evidence_raw).hexdigest(),
                    },
                })
            self.gates.append({"gate_id": gate_id, "receipt": self.write(name, receipt)})
        for fault_id in FAULTS:
            evidence_name = fault_id + "-evidence.txt"
            evidence_raw = (fault_id + " isolated fault evidence\n").encode()
            (self.root / evidence_name).write_bytes(evidence_raw)
            receipt = {
                "schema": "lottery.fault-receipt/v1",
                "fault_id": fault_id,
                "release_id": self.manifest["release_id"],
                "source_commit": self.manifest["source_commit"],
                "release_manifest_sha256": "sha256:" + hashlib.sha256(canonicalize(self.manifest)).hexdigest(),
                "injection_method": "deterministic-fixture",
                "expected_state": "fail_closed",
                "observed_state": "fail_closed",
                "recovery_action": "discard_staged_output",
                "output_publication": "none",
                "runner_commit": "b" * 40,
                "evidence": {"path": evidence_name, "sha256": hashlib.sha256(evidence_raw).hexdigest()},
                "generated_at_utc": "2026-11-23T12:00:00Z",
            }
            self.faults.append({"fault_id": fault_id, "receipt": self.write(fault_id + ".json", receipt)})

    def write(self, name, value):
        raw = canonicalize(value)
        (self.root / name).write_bytes(raw)
        return {"path": name, "sha256": hashlib.sha256(raw).hexdigest()}

    def rewrite(self, reference, mutate):
        path = self.root / reference["path"]
        receipt = json.loads(path.read_text(encoding="utf-8"))
        mutate(receipt)
        raw = canonicalize(receipt)
        path.write_bytes(raw)
        reference["sha256"] = hashlib.sha256(raw).hexdigest()

    def verify(self):
        return verify_receipt_set(self.manifest, self.gates, self.faults, self.root)

    def test_complete_typed_receipt_inventory_derives_shadow_only(self):
        report = self.verify()
        self.assertEqual(report["readiness"], "NOT_READY")
        self.assertEqual(report["receipt_completeness"], "COMPLETE")
        self.assertFalse(report["shadow_authorized"])
        self.assertFalse(report["production_ready"])
        self.assertIn("integrity only", report["authenticity_note"])

    def test_mutable_release_ref_is_rejected_before_receipt_evaluation(self):
        self.manifest["release_ref"] = "main"
        with self.assertRaisesRegex(ReceiptVerificationError, "invalid or mutable"):
            self.verify()

    def test_v2_manifest_binds_full_release_tuple_to_actual_bytes(self):
        names = (
            "workflow_policy", "dependency_lock", "readiness_policy", "canonical_snapshot",
            "source_evidence_ledger", "runtime_toolchain", "sbom", "security_scan",
            "experiment_registration", "champion_registry_snapshot", "sampler_rng",
            "storage_commit_receipts", "backup_generation", "independent_restore_receipt",
        )
        evidence = {}
        for name in names:
            raw = (name + "\\n").encode()
            path = name + ".bin"
            (self.root / path).write_bytes(raw)
            evidence[name] = {"path": path, "sha256": hashlib.sha256(raw).hexdigest()}
        for collection in ("evaluation_manifests", "model_artifacts"):
            raw = (collection + "\\n").encode()
            path = collection + ".bin"
            (self.root / path).write_bytes(raw)
            evidence[collection] = [{"path": path, "sha256": hashlib.sha256(raw).hexdigest()}]
        manifest = {
            "schema": "lottery.release-manifest/v2",
            "release_id": "v2-release",
            "release_ref": "c" * 40,
            "source_commit": "c" * 40,
            "lot042_accessed": False,
            "evidence": evidence,
        }
        report = verify_release_manifest_v2(manifest, self.root)
        self.assertEqual(len(report["verified_evidence"]), 16)
        self.assertTrue(report["release_manifest_sha256"].startswith("sha256:"))

    def test_v2_manifest_rejects_missing_or_mutated_release_evidence(self):
        names = (
            "workflow_policy", "dependency_lock", "readiness_policy", "canonical_snapshot",
            "source_evidence_ledger", "runtime_toolchain", "sbom", "security_scan",
            "experiment_registration", "champion_registry_snapshot", "sampler_rng",
            "storage_commit_receipts", "backup_generation", "independent_restore_receipt",
        )
        evidence = {}
        for name in names:
            raw = name.encode()
            path = name + ".bin"
            (self.root / path).write_bytes(raw)
            evidence[name] = {"path": path, "sha256": hashlib.sha256(raw).hexdigest()}
        for collection in ("evaluation_manifests", "model_artifacts"):
            raw = collection.encode()
            path = collection + ".bin"
            (self.root / path).write_bytes(raw)
            evidence[collection] = [{"path": path, "sha256": hashlib.sha256(raw).hexdigest()}]
        manifest = {
            "schema": "lottery.release-manifest/v2", "release_id": "v2-release",
            "release_ref": "c" * 40, "source_commit": "c" * 40,
            "lot042_accessed": False, "evidence": evidence,
        }
        manifest["evidence"]["sbom"]["sha256"] = "f" * 64
        with self.assertRaisesRegex(ReceiptVerificationError, "SHA-256 mismatch"):
            verify_release_manifest_v2(manifest, self.root)

    def test_v2_manifest_with_mismatched_g3_snapshot_fails_closed(self):
        names = (
            "workflow_policy", "dependency_lock", "readiness_policy", "canonical_snapshot",
            "source_evidence_ledger", "runtime_toolchain", "sbom", "security_scan",
            "experiment_registration", "champion_registry_snapshot", "sampler_rng",
            "storage_commit_receipts", "backup_generation", "independent_restore_receipt",
        )
        evidence = {}
        for name in names:
            raw = (name + "\\n").encode()
            path = "manifest-" + name + ".bin"
            (self.root / path).write_bytes(raw)
            evidence[name] = {"path": path, "sha256": hashlib.sha256(raw).hexdigest()}
        for collection in ("evaluation_manifests", "model_artifacts"):
            if collection == "evaluation_manifests":
                path = "G3-run-manifest.json"
                raw = (self.root / path).read_bytes()
            else:
                path = "G3-model-artifacts.jsonl"
                raw = (self.root / path).read_bytes()
            evidence[collection] = [{"path": path, "sha256": hashlib.sha256(raw).hexdigest()}]
        self.manifest = {
            "schema": "lottery.release-manifest/v2", "release_id": "v2-release",
            "release_ref": "c" * 40, "source_commit": "c" * 40,
            "lot042_accessed": False, "evidence": evidence,
        }
        manifest_digest = "sha256:" + hashlib.sha256(canonicalize(self.manifest)).hexdigest()
        for item in self.gates:
            self.rewrite(item["receipt"], lambda r: (
                r.__setitem__("release_id", self.manifest["release_id"]),
                r.__setitem__("source_commit", self.manifest["source_commit"]),
                r.__setitem__("release_manifest_sha256", manifest_digest),
            ))
        for item in self.faults:
            self.rewrite(item["receipt"], lambda r: (
                r.__setitem__("release_id", self.manifest["release_id"]),
                r.__setitem__("source_commit", self.manifest["source_commit"]),
                r.__setitem__("release_manifest_sha256", manifest_digest),
            ))
        with self.assertRaisesRegex(ReceiptVerificationError, "run manifest is missing, non-confirmatory"):
            verify_receipt_set(self.manifest, self.gates, self.faults, self.root)

    def test_malformed_inventory_identifiers_fail_closed_without_type_errors(self):
        bad_gates = list(self.gates)
        bad_gates[0] = {"gate_id": ["G0"], "receipt": self.gates[0]["receipt"]}
        with self.assertRaisesRegex(ReceiptVerificationError, "malformed entry"):
            verify_receipt_set(self.manifest, bad_gates, self.faults, self.root)
        bad_faults = list(self.faults)
        bad_faults[0] = {"fault_id": ["F01"], "receipt": self.faults[0]["receipt"]}
        with self.assertRaisesRegex(ReceiptVerificationError, "malformed entry"):
            verify_receipt_set(self.manifest, self.gates, bad_faults, self.root)

    def test_one_generic_receipt_cannot_be_reused_for_all_gates(self):
        for index in range(1, len(self.gates)):
            self.gates[index]["receipt"] = dict(self.gates[0]["receipt"])
        with self.assertRaisesRegex(ReceiptVerificationError, "does not bind this release and gate|unique per gate"):
            self.verify()

    def test_gate_receipt_type_must_match_gate(self):
        self.rewrite(self.gates[0]["receipt"], lambda r: r.__setitem__("receipt_type", GATE_TYPES["G1"]))
        with self.assertRaisesRegex(ReceiptVerificationError, "does not bind"):
            self.verify()

    def test_receipt_must_bind_exact_release_manifest_digest(self):
        self.rewrite(self.gates[0]["receipt"], lambda r: r.__setitem__("release_manifest_sha256", "sha256:" + "f" * 64))
        with self.assertRaisesRegex(ReceiptVerificationError, "does not bind"):
            self.verify()

    def test_gate_checks_must_all_pass(self):
        self.rewrite(self.gates[0]["receipt"], lambda r: r["checks"][0].__setitem__("status", "FAIL"))
        with self.assertRaisesRegex(ReceiptVerificationError, "did not pass"):
            self.verify()

    def test_gate_specific_check_inventory_is_mandatory(self):
        self.rewrite(self.gates[0]["receipt"], lambda r: r["checks"].pop())
        with self.assertRaisesRegex(ReceiptVerificationError, "required check inventory mismatch"):
            self.verify()

    def test_gate_check_evidence_digest_is_verified(self):
        receipt_path = self.root / self.gates[0]["receipt"]["path"]
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        evidence_path = self.root / receipt["checks"][0]["evidence"]["path"]
        evidence_path.write_text("tampered", encoding="utf-8")
        with self.assertRaisesRegex(ReceiptVerificationError, "SHA-256 mismatch"):
            self.verify()

    def test_g2_rejects_hash_valid_but_non_normalized_probability_evidence(self):
        gate = next(item for item in self.gates if item["gate_id"] == "G2")
        receipt_path = self.root / gate["receipt"]["path"]
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        check = next(item for item in receipt["checks"] if item["check_id"] == "normalization")
        evidence_path = self.root / check["evidence"]["path"]
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        evidence["zones"][0]["probability_sum"] = 0.5
        raw = json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode()
        evidence_path.write_bytes(raw)
        self.rewrite(
            gate["receipt"],
            lambda value: next(
                item for item in value["checks"] if item["check_id"] == "normalization"
            )["evidence"].__setitem__("sha256", hashlib.sha256(raw).hexdigest()),
        )
        with self.assertRaisesRegex(ReceiptVerificationError, "not normalized/nonnegative"):
            self.verify()

    def test_gate_check_evidence_cannot_be_reused_across_gates(self):
        g0_path = self.root / self.gates[0]["receipt"]["path"]
        g0_receipt = json.loads(g0_path.read_text(encoding="utf-8"))
        shared = g0_receipt["checks"][0]["evidence"]
        self.rewrite(
            self.gates[1]["receipt"],
            lambda receipt: receipt["checks"][0].__setitem__("evidence", shared),
        )
        with self.assertRaisesRegex(ReceiptVerificationError, "must be unique"):
            self.verify()

    def test_fault_receipt_requires_recovery_action_and_no_output_publication(self):
        self.rewrite(self.faults[0]["receipt"], lambda r: r.__setitem__("recovery_action", ""))
        with self.assertRaisesRegex(ReceiptVerificationError, "fault receipt contract mismatch"):
            self.verify()
        self.setUp()
        self.rewrite(self.faults[0]["receipt"], lambda r: r.__setitem__("output_publication", "partial"))
        with self.assertRaisesRegex(ReceiptVerificationError, "fault receipt contract mismatch"):
            self.verify()

    def test_fault_receipt_binds_evidence_bytes(self):
        evidence = self.root / self.faults[0]["receipt"]["path"]
        receipt = json.loads(evidence.read_text(encoding="utf-8"))
        (self.root / receipt["evidence"]["path"]).write_text("changed", encoding="utf-8")
        with self.assertRaisesRegex(ReceiptVerificationError, "SHA-256 mismatch"):
            self.verify()

    def test_lot042_access_blocks_shadow_even_when_all_receipts_pass(self):
        self.manifest["lot042_accessed"] = True
        self.setUp()
        self.manifest["lot042_accessed"] = True
        # Rebind every receipt to the changed manifest so only isolation blocks.
        for item in self.gates:
            self.rewrite(item["receipt"], lambda r: r.__setitem__(
                "release_manifest_sha256",
                "sha256:" + hashlib.sha256(canonicalize(self.manifest)).hexdigest(),
            ))
        for item in self.faults:
            self.rewrite(item["receipt"], lambda r: r.__setitem__(
                "release_manifest_sha256",
                "sha256:" + hashlib.sha256(canonicalize(self.manifest)).hexdigest(),
            ))
        report = self.verify()
        self.assertEqual(report["readiness"], "NOT_READY")
        self.assertEqual(report["receipt_completeness"], "BLOCKED_LOT042")
        self.assertFalse(report["shadow_authorized"])


if __name__ == "__main__":
    unittest.main()
