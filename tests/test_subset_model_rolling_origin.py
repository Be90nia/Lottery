import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from run_subset_rolling_origin import run


class OfficialSnapshotRollingOriginTests(unittest.TestCase):
    """Run the full frozen 2,649-target denominator, retaining fit failures."""
    def test_all_2649_frozen_targets_have_terminal_records(self):
        snapshot = ROOT / "data/processed/draws-20261118.jsonl"
        output = ROOT / "subset-model-rolling-origin.json"
        result = run(snapshot, output)
        self.assertEqual(result["target_count_per_zone"], 2649)
        self.assertEqual(result["first_target_draw"], "09054")
        self.assertEqual(result["last_target_draw"], "26131")
        self.assertTrue(output.exists())
        for zone in (result["front"], result["back"]):
            self.assertEqual(len(zone["target_records"]), 2649)
            self.assertTrue(zone["complete_coverage"], msg=zone["fit_status_counts"])
            self.assertEqual(zone["scored_target_count"], 2649)
        self.assertFalse(result["production_ready"])


if __name__ == "__main__":
    unittest.main()
