import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from lottery.readiness import (
    ReadinessError,
    build_readiness_report,
    verify_readiness_report,
    write_readiness_report,
)


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def make_manifest():
    return {
        "schema_version": "lottery.release-manifest/v1",
        "release_id": "lottery-test-release",
        "source_commit": "a" * 40,
        "protected_release_ref": "refs/tags/test-release",
        "policy_version": "LOT-067-v1",
        "holdout_accessed": False,
        "workflow_action_pins": [],
        "runtime": {"python": "3.12", "dependency_lock_sha256": None},
        "data": {"snapshot_sha256": None, "evidence_ledger_sha256": None},
        "model_artifacts": [],
        "experiments": {"registry_sha256": None, "evaluation_manifest_sha256": None},
        "champion": {"registry_generation": "generation-1", "slots": []},
        "sampler": {"algorithm": "conditional-poisson-v1", "rng_version": "python-random-v1"},
        "feedback": {"ledger_sha256": None, "monitoring_policy_sha256": None},
        "storage": {"commit_receipt_sha256": None, "backup_generation": None,
                    "restore_drill_receipt_sha256": None},
        "security": {"sbom_sha256": None, "security_scan_sha256": None,
                     "provenance_sha256": None, "signer_id": None,
                     "rollback_drill_receipt_sha256": None},
        "activation": {"scheduled_collection_enabled": False, "shadow_only": False,
                       "user_facing_serving_enabled": False,
                       "automatic_promotion_enabled": False},
    }


def make_gates(evidence_paths, *, pass_through=4):
    gates = []
    for index in range(9):
        gate_id = f"G{index}"
        if index < pass_through:
            gates.append({
                "gate_id": gate_id,
                "status": "PASS",
                "summary": f"{gate_id} fixture passed",
                "evidence": [evidence_paths[index]],
                "blockers": [],
                "fault_tests": [{
                    "test_id": f"{gate_id}-fault-1",
                    "expected_state": "fail_closed",
                    "observed_state": "fail_closed",
                    "passed": True,
                }],
            })
        else:
            gates.append({
                "gate_id": gate_id,
                "status": "UNKNOWN",
                "summary": f"{gate_id} not yet accepted",
                "evidence": [],
                "blockers": [f"{gate_id} evidence not implemented"],
                "fault_tests": [],
            })
    return {"schema_version": "lottery.release-gates/v1", "gates": gates}


class ReadinessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.evidence_root = self.root / "evidence"
        self.evidence_root.mkdir()
        self.evidence_paths = []
        for index in range(9):
            name = f"gate-{index}.json"
            raw = json.dumps({"gate": index}, sort_keys=True).encode()
            (self.evidence_root / name).write_bytes(raw)
            self.evidence_paths.append({"path": name, "sha256": sha(raw)})
        self.manifest_path = self.root / "release-manifest.json"
        self.gates_path = self.root / "gate-results.json"
        self.report_path = self.root / "readiness-report.json"
        self.manifest = make_manifest()
        self.gates = make_gates(self.evidence_paths)
        self.write_inputs()

    def tearDown(self):
        self.temp.cleanup()

    def write_inputs(self):
        self.manifest_path.write_text(json.dumps(self.manifest), encoding="utf-8")
        self.gates_path.write_text(json.dumps(self.gates), encoding="utf-8")

    def test_offline_readiness_requires_only_g0_through_g3(self):
        report = build_readiness_report(
            self.manifest_path, self.gates_path, self.evidence_root
        )
        self.assertEqual(report["readiness_state"], "READY_FOR_OFFLINE_VALIDATION")
        self.assertEqual(report["gate_statuses"]["G4"], "UNKNOWN")
        self.assertEqual(len(report["verified_evidence"]), 4)
        self.assertFalse(report["activation_performed"])
        self.assertFalse(report["serving_enabled_by_report"])
        self.assertEqual(report["production_approval"], "not_implemented_fail_closed")

    def test_pass_without_verified_evidence_is_rejected(self):
        self.gates["gates"][0]["evidence"] = []
        self.write_inputs()
        with self.assertRaisesRegex(ReadinessError, "without at least one verified evidence"):
            build_readiness_report(self.manifest_path, self.gates_path, self.evidence_root)

    def test_evidence_hash_mismatch_is_rejected(self):
        (self.evidence_root / "gate-0.json").write_text("tampered", encoding="utf-8")
        with self.assertRaisesRegex(ReadinessError, "hash mismatch"):
            build_readiness_report(self.manifest_path, self.gates_path, self.evidence_root)

    def test_evidence_path_escape_is_rejected(self):
        self.gates["gates"][0]["evidence"] = [{"path": "../outside", "sha256": "0" * 64}]
        self.write_inputs()
        with self.assertRaisesRegex(ReadinessError, "relative path|escapes evidence root"):
            build_readiness_report(self.manifest_path, self.gates_path, self.evidence_root)

    def test_holdout_access_denies_every_readiness_stage(self):
        self.manifest["holdout_accessed"] = True
        self.write_inputs()
        report = build_readiness_report(
            self.manifest_path, self.gates_path, self.evidence_root
        )
        self.assertEqual(report["readiness_state"], "NOT_READY")
        self.assertTrue(report["blocking_reasons"])
        self.assertTrue(report["holdout_accessed"])

    def test_offline_readiness_is_denied_if_collection_or_serving_is_enabled(self):
        self.manifest["activation"]["scheduled_collection_enabled"] = True
        self.write_inputs()
        report = build_readiness_report(
            self.manifest_path, self.gates_path, self.evidence_root
        )
        self.assertEqual(report["readiness_state"], "NOT_READY")

    def test_shadow_requires_all_g0_through_g7_and_three_compatible_slots(self):
        self.gates = make_gates(self.evidence_paths, pass_through=8)
        self.manifest["activation"]["shadow_only"] = True
        slots = []
        for index in range(3):
            slots.append({
                "artifact_id": f"artifact-{index}",
                "artifact_sha256": str(index + 1) * 64,
                "registry_generation": "generation-1",
                "eligible": True,
            })
        self.manifest["champion"]["slots"] = slots
        self.write_inputs()
        report = build_readiness_report(
            self.manifest_path, self.gates_path, self.evidence_root
        )
        self.assertEqual(report["readiness_state"], "READY_FOR_SHADOW")
        self.assertEqual(report["gate_statuses"]["G7"], "PASS")
        self.assertEqual(report["gate_statuses"]["G8"], "UNKNOWN")

    def test_g5_cannot_pass_with_two_slots(self):
        self.gates = make_gates(self.evidence_paths, pass_through=8)
        self.manifest["activation"]["shadow_only"] = True
        self.manifest["champion"]["slots"] = [{
            "artifact_id": "only-one",
            "artifact_sha256": "1" * 64,
            "registry_generation": "generation-1",
            "eligible": True,
        }]
        self.write_inputs()
        with self.assertRaisesRegex(ReadinessError, "exactly three Champion slots"):
            build_readiness_report(self.manifest_path, self.gates_path, self.evidence_root)

    def test_mixed_registry_generation_invalidates_g5(self):
        self.gates = make_gates(self.evidence_paths, pass_through=8)
        self.manifest["activation"]["shadow_only"] = True
        self.manifest["champion"]["slots"] = [{
            "artifact_id": f"artifact-{index}",
            "artifact_sha256": str(index + 1) * 64,
            "registry_generation": "generation-2" if index == 2 else "generation-1",
            "eligible": True,
        } for index in range(3)]
        self.write_inputs()
        with self.assertRaisesRegex(ReadinessError, "mixed registry generation"):
            build_readiness_report(self.manifest_path, self.gates_path, self.evidence_root)

    def test_failed_fault_injection_receipt_cannot_be_marked_pass(self):
        self.gates["gates"][0]["fault_tests"][0]["passed"] = False
        self.write_inputs()
        with self.assertRaisesRegex(ReadinessError, "failed fault-injection"):
            build_readiness_report(self.manifest_path, self.gates_path, self.evidence_root)

    def test_missing_gate_and_duplicate_gate_are_rejected(self):
        self.gates["gates"].pop()
        self.write_inputs()
        with self.assertRaisesRegex(ReadinessError, "missing required gates"):
            build_readiness_report(self.manifest_path, self.gates_path, self.evidence_root)
        self.gates["gates"] = make_gates(self.evidence_paths)["gates"]
        self.gates["gates"][-1] = dict(self.gates["gates"][0])
        self.write_inputs()
        with self.assertRaisesRegex(ReadinessError, "duplicate gate_id"):
            build_readiness_report(self.manifest_path, self.gates_path, self.evidence_root)

    def test_report_is_immutable_and_verification_binds_all_inputs(self):
        report = build_readiness_report(
            self.manifest_path, self.gates_path, self.evidence_root
        )
        write_readiness_report(report, self.report_path)
        self.assertEqual(
            write_readiness_report(report, self.report_path).read_bytes(),
            self.report_path.read_bytes(),
        )
        verified = verify_readiness_report(
            self.report_path, self.manifest_path, self.gates_path, self.evidence_root
        )
        self.assertEqual(verified["report_sha256"], report["report_sha256"])
        self.manifest["source_commit"] = "b" * 40
        self.write_inputs()
        with self.assertRaisesRegex(ReadinessError, "does not match current"):
            verify_readiness_report(
                self.report_path, self.manifest_path, self.gates_path, self.evidence_root
            )


if __name__ == "__main__":
    unittest.main()
