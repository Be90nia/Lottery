from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from lottery.readiness import (
    FAULTS,
    GATES,
    ReadinessError,
    evaluate_readiness,
    load_json,
    write_readiness_report,
)


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


class ReadinessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.evidence = self.root / "evidence"
        self.evidence.mkdir()
        self.proof = self.evidence / "receipt.txt"
        self.proof.write_text("verified evidence\n", encoding="utf-8")
        self.proof_hash = sha(self.proof.read_bytes())
        self.manifest = {
            "schema": "lottery.release-manifest/v1",
            "release_id": "release-test-001",
            "release_ref": "a" * 40,
            "source_commit": "a" * 40,
            "workflow_policy_sha256": "1" * 64,
            "dependency_lock_sha256": "2" * 64,
            "snapshot_sha256": "3" * 64,
            "lot042_accessed": False,
        }
        self.gates = [
            {
                "gate_id": gate,
                "status": "PASS" if gate in ("G0", "G1", "G2", "G3") else "BLOCKED",
                "evidence": [{"path": "receipt.txt", "sha256": self.proof_hash}]
                if gate in ("G0", "G1", "G2", "G3") else [],
            }
            for gate in GATES
        ]
        self.faults = [
            {
                "fault_id": fault,
                "status": "PASS" if fault in ("F01", "F03", "F04", "F05") else "BLOCKED",
                "injected": True,
                "expected_state": "fail_closed",
                "observed_state": "fail_closed",
                "evidence": {"path": "receipt.txt", "sha256": self.proof_hash},
            }
            for fault in FAULTS
        ]

    def test_offline_validation_requires_g0_to_g3_and_core_faults(self):
        report = evaluate_readiness(self.manifest, self.gates, self.faults, self.evidence)
        self.assertEqual(report["readiness"], "READY_FOR_OFFLINE_VALIDATION")
        self.assertFalse(report["production_ready"])
        self.assertEqual(report["release_manifest_sha256"][:7], "sha256:")

    def test_shadow_requires_every_gate_and_fault(self):
        for gate in self.gates:
            gate["status"] = "PASS"
            gate["evidence"] = [{"path": "receipt.txt", "sha256": self.proof_hash}]
        for fault in self.faults:
            fault["status"] = "PASS"
        report = evaluate_readiness(self.manifest, self.gates, self.faults, self.evidence)
        self.assertEqual(report["readiness"], "READY_FOR_SHADOW")
        self.assertFalse(report["production_ready"])

    def test_missing_gate_and_fault_results_fail_closed_with_named_blockers(self):
        report = evaluate_readiness(
            self.manifest, self.gates[:-1], self.faults[:-1], self.evidence
        )
        self.assertEqual(report["readiness"], "READY_FOR_OFFLINE_VALIDATION")
        self.assertIn("G8:missing_gate_result", report["blockers"])
        self.assertIn("F15:missing_fault_result", report["blockers"])

    def test_pass_without_evidence_is_downgraded(self):
        self.gates[0]["evidence"] = []
        report = evaluate_readiness(self.manifest, self.gates, self.faults, self.evidence)
        self.assertEqual(report["readiness"], "NOT_READY")
        self.assertEqual(report["gate_states"]["G0"], "FAIL")
        self.assertIn("G0:pass_without_evidence", report["blockers"])

    def test_evidence_hash_mismatch_fails_gate(self):
        self.gates[0]["evidence"][0]["sha256"] = "f" * 64
        report = evaluate_readiness(self.manifest, self.gates, self.faults, self.evidence)
        self.assertEqual(report["gate_states"]["G0"], "FAIL")
        self.assertEqual(report["readiness"], "NOT_READY")

    def test_path_traversal_and_symlinks_are_rejected(self):
        self.gates[0]["evidence"] = [{"path": "../outside", "sha256": self.proof_hash}]
        report = evaluate_readiness(self.manifest, self.gates, self.faults, self.evidence)
        self.assertEqual(report["gate_states"]["G0"], "FAIL")
        link = self.evidence / "linked.txt"
        try:
            link.symlink_to(self.proof)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks unavailable")
        self.gates[0]["evidence"] = [{"path": "linked.txt", "sha256": self.proof_hash}]
        report = evaluate_readiness(self.manifest, self.gates, self.faults, self.evidence)
        self.assertEqual(report["gate_states"]["G0"], "FAIL")

    def test_fault_mismatch_or_uninjected_fault_is_not_a_pass(self):
        self.faults[0]["observed_state"] = "published_partial_output"
        self.faults[1]["injected"] = False
        report = evaluate_readiness(self.manifest, self.gates, self.faults, self.evidence)
        self.assertNotEqual(report["fault_states"]["F01"], "PASS")
        self.assertNotEqual(report["fault_states"]["F02"], "PASS")
        self.assertIn("F02:blocked", report["blockers"])
        self.assertEqual(report["readiness"], "NOT_READY")

    def test_protected_holdout_access_blocks_every_readiness_state(self):
        self.manifest["lot042_accessed"] = True
        for gate in self.gates:
            gate["status"] = "PASS"
            gate["evidence"] = [{"path": "receipt.txt", "sha256": self.proof_hash}]
        for fault in self.faults:
            fault["status"] = "PASS"
        report = evaluate_readiness(self.manifest, self.gates, self.faults, self.evidence)
        self.assertEqual(report["readiness"], "NOT_READY")
        self.assertTrue(any("LOT-042" in blocker for blocker in report["blockers"]))

    def test_mutable_release_ref_and_duplicate_gate_are_rejected(self):
        self.manifest["release_ref"] = "main"
        with self.assertRaisesRegex(ReadinessError, "mutable refs"):
            evaluate_readiness(self.manifest, self.gates, self.faults, self.evidence)
        self.manifest["release_ref"] = self.manifest["source_commit"]
        with self.assertRaisesRegex(ReadinessError, "duplicate gate_results"):
            evaluate_readiness(self.manifest, self.gates + [self.gates[0]], self.faults, self.evidence)

    def test_report_is_immutable_no_clobber(self):
        report = evaluate_readiness(self.manifest, self.gates, self.faults, self.evidence)
        output = self.root / "readiness.json"
        write_readiness_report(report, output)
        original = output.read_bytes()
        with self.assertRaisesRegex(ReadinessError, "already exists"):
            write_readiness_report(report, output)
        self.assertEqual(output.read_bytes(), original)

    def test_machine_readable_policy_matches_evaluator_constants(self):
        policy_path = Path(__file__).resolve().parents[1] / "schemas" / "readiness-policy-v1.json"
        policy = json.loads(policy_path.read_text(encoding="utf-8"))
        self.assertEqual(policy["schema"], "lottery.readiness-policy/v1")
        self.assertEqual(tuple(policy["gates"]), GATES)
        self.assertEqual(tuple(policy["faults"]), FAULTS)
        self.assertEqual(tuple(policy["offline"]["required_gates"]), ("G0", "G1", "G2", "G3"))
        self.assertFalse(policy["production"]["enabled"])

    def test_strict_json_rejects_duplicate_keys(self):
        path = self.root / "duplicate.json"
        path.write_text('{"a":1,"a":2}', encoding="utf-8")
        with self.assertRaisesRegex(ReadinessError, "duplicate JSON key"):
            load_json(path)


if __name__ == "__main__":
    unittest.main()
