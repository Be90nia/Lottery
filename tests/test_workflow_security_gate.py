import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.check_workflow_security import validate_subset_research_gate


class WorkflowSecurityGateOrderingTests(unittest.TestCase):
    def test_provenance_gate_precedes_all_registry_mutation_and_evaluation(self):
        lines = [
            "- name: Verify append-only CP child registration source comment before any evaluation",
            "  --registration docs/LOT055_CP_CALIBRATION_REGISTRATION_2026-11-26.json",
            "  --legacy-registration docs/G3_DIAGNOSTIC_REGISTRATION_2026-11-22.json",
            '  --repository "$GITHUB_REPOSITORY"',
            "- name: Restore append-only registry and LOT-065 object history",
            "- name: Append verified historical G3 execution to the persistent registry",
            "- name: Run full frozen 2,649-target exact-subset evaluation",
            "workflow_dispatch:",
        ]
        self.assertEqual(validate_subset_research_gate(lines), [])

    def test_rejects_gate_moved_after_restore(self):
        lines = [
            "- name: Restore append-only registry and LOT-065 object history",
            "- name: Verify append-only CP child registration source comment before any evaluation",
            "  --registration docs/LOT055_CP_CALIBRATION_REGISTRATION_2026-11-26.json",
            "  --legacy-registration docs/G3_DIAGNOSTIC_REGISTRATION_2026-11-22.json",
            '  --repository "$GITHUB_REPOSITORY"',
            "- name: Append verified historical G3 execution to the persistent registry",
            "- name: Run full frozen 2,649-target exact-subset evaluation",
            "workflow_dispatch:",
        ]
        self.assertTrue(any("must precede" in item for item in validate_subset_research_gate(lines)))

    def test_rejects_cp_branch_in_automatic_push_allowlist(self):
        lines = [
            "on:",
            "  push:",
            "    branches:",
            "      - feat/lot055-cp-calibration-lineage",
            "- name: Verify append-only CP child registration source comment before any evaluation",
            "  --registration docs/LOT055_CP_CALIBRATION_REGISTRATION_2026-11-26.json",
            "  --legacy-registration docs/G3_DIAGNOSTIC_REGISTRATION_2026-11-22.json",
            '  --repository "$GITHUB_REPOSITORY"',
            "- name: Restore append-only registry and LOT-065 object history",
            "- name: Append verified historical G3 execution to the persistent registry",
            "- name: Run full frozen 2,649-target exact-subset evaluation",
            "workflow_dispatch:",
        ]
        self.assertTrue(any("excluded from automatic" in item for item in validate_subset_research_gate(lines)))


if __name__ == "__main__":
    unittest.main()
