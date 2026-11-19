from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class SyncWorkflowContractTests(unittest.TestCase):
    def test_official_sync_builds_only_a_guarded_append_candidate(self):
        workflow = (ROOT / ".github/workflows/official-draw-sync-mvp.yml").read_text(encoding="utf-8")
        self.assertIn("timeout-minutes: 90", workflow)
        self.assertIn("id: validate_candidate", workflow)
        self.assertIn("id: append_only", workflow)
        self.assertIn("scripts/reconcile_draws.py", workflow)
        self.assertIn("--current data/candidates/pinned-draws-20261118.jsonl", workflow)
        self.assertIn("--candidate-manifest sync-run/processed/candidate.jsonl.manifest.json", workflow)
        self.assertIn('--snapshots-dir "$RAW_DIR"', workflow)
        self.assertIn("--output sync-run/processed/append-only-candidate.jsonl", workflow)
        self.assertIn("--receipt sync-run/processed/append-only-receipt.json", workflow)
        self.assertIn("steps.append_only.outcome == 'failure'", workflow)
        self.assertIn('"canonical_dataset_modified": False', workflow)
        self.assertNotIn("contents: write", workflow)

    def test_reported_index_workflow_runs_pilot_before_emitting_all_lanes(self):
        workflow = (ROOT / ".github/workflows/ball-set-evidence.yml").read_text(encoding="utf-8")
        self.assertIn("id: reported_view", workflow)
        self.assertIn("id: pilot", workflow)
        self.assertIn("id: candidates", workflow)
        self.assertIn("scripts/build_reported_set_index_view.py", workflow)
        self.assertIn("scripts/run_reported_set_index_pilot.py", workflow)
        self.assertIn("scripts/build_jiangsu_draw_candidate.py", workflow)
        self.assertIn("scripts/run_mvp.py", workflow)
        self.assertIn("scripts/run_live_reported_index_mvp.py", workflow)
        self.assertIn("--tickets-per-strategy 5", workflow)
        self.assertIn("actions: read", workflow)
        self.assertIn("contents: read", workflow)
        self.assertIn("steps.pilot.outcome == 'success'", workflow)


if __name__ == "__main__":
    unittest.main()
