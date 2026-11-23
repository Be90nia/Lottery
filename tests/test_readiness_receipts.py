from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from lottery.subset_model.artifact import canonicalize
from lottery.readiness_receipts import (
    FAULTS, GATE_REQUIRED_CHECKS, GATE_TYPES, ReceiptVerificationError, verify_receipt_set,
    verify_release_manifest_v2,
)


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
            "snapshot_sha256": "4" * 64,
            "lot042_accessed": False,
        }
        self.gates = []
        self.faults = []
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
                if gate_id == "G2":
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

    def test_v2_manifest_integrates_with_complete_receipt_set(self):
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
            raw = (collection + "\\n").encode()
            path = "manifest-" + collection + ".bin"
            (self.root / path).write_bytes(raw)
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
        report = verify_receipt_set(self.manifest, self.gates, self.faults, self.root)
        self.assertEqual(report["receipt_completeness"], "COMPLETE")
        self.assertEqual(len(report["release_manifest_evidence"]), 16)
        self.assertFalse(report["shadow_authorized"])

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
