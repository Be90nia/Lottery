"""Tests for frozen exact-set evaluation primitives."""
import math
import unittest

from lottery.exact_backtest import (holm_adjust, moving_block_bootstrap_ci, uniform_exact_nll,
                                    evaluate_rolling_origin, verify_frozen_snapshot,
                                    verify_target_manifest)


def draw(index, front, back):
    return {"draw_id": f"{index:05d}", "draw_date": f"2020-01-{index:02d}",
            "front_numbers": front, "back_numbers": back}


class ExactBacktestPrimitiveTests(unittest.TestCase):
    def test_holm_six_hypothesis_family(self):
        values = {"a": .001, "b": .004, "c": .01, "d": .02, "e": .04, "f": .5}
        self.assertEqual(holm_adjust(values, expected_family_size=6),
                         {"a": .006, "b": .02, "c": .04, "d": .06, "e": .08, "f": .5})

    def test_holm_rejects_wrong_family_size(self):
        with self.assertRaises(ValueError):
            holm_adjust({"front": .01}, expected_family_size=6)

    def test_bootstrap_requires_full_block_and_is_reproducible(self):
        values = [float(index - 25) for index in range(50)]
        first = moving_block_bootstrap_ci(values, replicates=100, block_length=50, seed=71)
        second = moving_block_bootstrap_ci(values, replicates=100, block_length=50, seed=71)
        self.assertEqual(first, second)
        with self.assertRaises(ValueError):
            moving_block_bootstrap_ci(values[:49], block_length=50, seed=71)

    def test_uniform_exact_set_score(self):
        self.assertAlmostEqual(uniform_exact_nll(35, 5), math.log(math.comb(35, 5)), places=12)

    def test_target_manifest_hash_and_unique_ids(self):
        import hashlib
        raw = b'{"target_draw_ids":["00002","00003"]}'
        digest = hashlib.sha256(raw).hexdigest()
        self.assertEqual(verify_target_manifest(raw, expected_sha256=digest), ("00002", "00003"))
        with self.assertRaises(ValueError):
            verify_target_manifest(raw, expected_sha256="0" * 64)

    def test_snapshot_preflight_rejects_hash_and_checks_exact_targets(self):
        import hashlib
        rows = [
            draw(1, [1, 2, 3, 4, 5], [1, 2]),
            draw(2, [2, 3, 4, 5, 6], [2, 3]),
        ]
        import json
        raw = ("\n".join(json.dumps(row, separators=(",", ":")) for row in rows) + "\n").encode()
        digest = hashlib.sha256(raw).hexdigest()
        checked = verify_frozen_snapshot(raw, expected_sha256=digest,
                                          expected_row_count=2, expected_target_ids=("00002",),
                                          min_train=1)
        self.assertEqual(len(checked), 2)
        with self.assertRaises(ValueError):
            verify_frozen_snapshot(raw, expected_sha256="0" * 64,
                                   expected_row_count=2, expected_target_ids=("00002",),
                                   min_train=1)

    def test_terminal_ledger_keeps_failed_targets(self):
        rows = [draw(1, [1, 2, 3, 4, 5], [1, 2]),
                draw(2, [2, 3, 4, 5, 6], [2, 3]),
                draw(3, [3, 4, 5, 6, 7], [3, 4])]
        def scorer_factory(train, zone):
            if zone == "back" and train[-1]["draw_id"] == "00002":
                raise RuntimeError("synthetic fit failure")
            return lambda subset: -uniform_exact_nll(35, 5) if zone == "front" else -uniform_exact_nll(12, 2)
        report = evaluate_rolling_origin(rows, target_ids=("00003",), min_train=2,
                                          model_factories={"candidate": scorer_factory},
                                          snapshot_sha256="0" * 64)
        self.assertEqual(report["terminal_record_count"], 4)
        failed = [record for record in report["records"] if record["status"] != "scored"]
        self.assertEqual(len(failed), 1)
        self.assertEqual(failed[0]["zone"], "back")
        self.assertEqual(report["summary"]["candidate"]["back"]["scored_targets"], 0)


if __name__ == "__main__":
    unittest.main()
