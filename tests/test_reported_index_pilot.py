import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lottery.reported_index_pilot import (
    ReportedIndexPilotError,
    build_reported_index_pilot,
    write_reported_index_pilot,
)


def canonical(value):
    return json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def make_view(root):
    rows = []
    index_cycle = [1, 2, 3] * 4
    for i, set_index in enumerate(index_cycle, 1):
        draw_id = f"260{i:02d}"
        day = f"{i:02d}"
        front_start = ((i - 1) % 30) + 1
        front = list(range(front_start, front_start + 5))
        back_start = ((i - 1) % 11) + 1
        back = sorted([back_start, back_start + 1])
        rows.append({
            "draw_id": draw_id,
            "draw_date": f"2026-01-{day}",
            "front_numbers": front,
            "back_numbers": back,
            "source_id": f"sha256:inventory-{i}",
            "reported_set_index": set_index,
            "evidence_status": "primary_verified",
            "observation_ids": [f"obs-{draw_id}"],
            "source_urls": [f"https://www.js-lottery.com/cms/post-{draw_id}.html"],
            "inventory_sha256": "a" * 64,
            "coverage_report_sha256": "b" * 64,
            "observation_ledger_sha256": "c" * 64,
            "equipment_regime_id": None,
            "physical_ball_set_id": None,
            "eligible_for_reported_index_pilot": True,
            "eligible_for_physical_model": False,
            "training_eligibility": "blocked_regime_unresolved",
            "model_scope": "reported_set_index_only_not_physical_identity",
        })
    view_path = root / "view.jsonl"
    raw = b"".join(
        (json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n").encode()
        for row in rows
    )
    view_path.write_bytes(raw)
    manifest = {
        "schema_version": "lottery.reported-set-index-view/v1",
        "pilot_protocol_version": "reported-set-index-pilot-v1",
        "inventory_sha256": "a" * 64,
        "inventory_trust_status": "candidate_unverified",
        "coverage_report_sha256": "b" * 64,
        "observation_ledger_sha256": "c" * 64,
        "record_count": 12,
        "set_index_counts": {"1": 4, "2": 4, "3": 4},
        "first_draw": "26001",
        "last_draw": "26012",
        "output_sha256": sha(raw),
        "training_eligibility": "blocked_regime_unresolved",
        "physical_model_eligibility": "blocked_regime_unresolved",
        "physical_identity_claim": "none",
        "model_scope": "reported_set_index_only_not_physical_identity",
    }
    manifest["manifest_sha256"] = sha(canonical(manifest))
    manifest_path = root / "view.manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return view_path, manifest_path, rows


class ReportedIndexPilotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.view, self.manifest, self.rows = make_view(self.root)
        self.patches = [
            patch("lottery.reported_index_pilot.PILOT_EXPECTED_RECORD_COUNT", 12),
            patch("lottery.reported_index_pilot.PILOT_EXPECTED_SET_COUNTS", {"1": 4, "2": 4, "3": 4}),
            patch("lottery.reported_index_pilot.PILOT_EXPECTED_FIRST_DRAW", "26001"),
            patch("lottery.reported_index_pilot.PILOT_EXPECTED_LAST_DRAW", "26012"),
            patch("lottery.reported_index_pilot.MIN_TRAIN_PER_INDEX", 2),
            patch("lottery.reported_index_pilot.PILOT_EXPECTED_TARGET_COUNTS", {"1": 2, "2": 2, "3": 2}),
            patch("lottery.reported_index_pilot.BLOCK_LENGTH", 1),
            patch("lottery.reported_index_pilot.MIN_COMPLETE_BLOCKS", 2),
            patch("lottery.reported_index_pilot.BOOTSTRAP_REPLICATES", 50),
            patch("lottery.reported_index_pilot.SIGN_FLIP_REPLICATES", 50),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def test_runs_three_separate_causal_index_models_and_holm_family(self):
        report = build_reported_index_pilot(
            self.view, self.manifest, code_commit="d" * 40
        )
        self.assertEqual(report["target_counts"], {"1": 2, "2": 2, "3": 2})
        self.assertEqual(report["inference"]["comparison_count"], 12)
        self.assertEqual(len(report["comparisons"]), 12)
        self.assertEqual(len(report["score_rows"]), 6)
        self.assertFalse(report["holdout_accessed"])
        self.assertFalse(report["holdout_feedback_used"])
        self.assertFalse(report["production_ready"])
        self.assertEqual(report["physical_model_eligibility"], "blocked_regime_unresolved")
        self.assertEqual(report["predictive_efficacy_claim"], "none")
        self.assertEqual(len(report["report_sha256"]), 64)
        for comparison in report["comparisons"].values():
            self.assertGreaterEqual(comparison["block_sign_flip_p_value_one_sided_improvement"], 0)
            self.assertLessEqual(comparison["holm_adjusted_p_value"], 1)
        for row in report["score_rows"]:
            for model_scores in row["model_scores"].values():
                for zone in ("front", "back"):
                    self.assertLessEqual(
                        model_scores[zone]["maximum_marginal_calibration_residual"], 1e-8
                    )

    def test_pilot_report_is_write_once_and_idempotent(self):
        report = build_reported_index_pilot(
            self.view, self.manifest, code_commit="d" * 40
        )
        output = write_reported_index_pilot(report, self.root / "reports")
        original = output.read_bytes()
        self.assertEqual(
            write_reported_index_pilot(report, self.root / "reports").read_bytes(),
            original,
        )
        output.write_bytes(b"tampered")
        with self.assertRaisesRegex(ReportedIndexPilotError, "conflicts"):
            write_reported_index_pilot(report, self.root / "reports")

    def test_physical_identity_assignment_is_rejected(self):
        self.rows[0]["physical_ball_set_id"] = "set-1"
        raw = b"".join(
            (json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n").encode()
            for row in self.rows
        )
        self.view.write_bytes(raw)
        manifest = json.loads(self.manifest.read_text())
        manifest["output_sha256"] = sha(raw)
        body = {key: value for key, value in manifest.items() if key != "manifest_sha256"}
        manifest["manifest_sha256"] = sha(canonical(body))
        self.manifest.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(ReportedIndexPilotError, "physical-regime boundary"):
            build_reported_index_pilot(self.view, self.manifest, code_commit="d" * 40)

    def test_manifest_tampering_is_rejected(self):
        manifest = json.loads(self.manifest.read_text())
        manifest["inventory_sha256"] = "f" * 64
        self.manifest.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(ReportedIndexPilotError, "manifest hash mismatch"):
            build_reported_index_pilot(self.view, self.manifest, code_commit="d" * 40)

    def test_inadequate_number_of_blocks_suppresses_inference(self):
        with patch("lottery.reported_index_pilot.MIN_COMPLETE_BLOCKS", 10):
            report = build_reported_index_pilot(
                self.view, self.manifest, code_commit="d" * 40
            )
        self.assertEqual(report["score_coverage"]["complete_coverage"], True)
        self.assertEqual(report["inference"]["status"], "suppressed_insufficient_blocks")
        self.assertEqual(report["inference"]["comparison_count"], 0)
        self.assertEqual(report["comparisons"], {})
        self.assertEqual(
            report["reported_index_pilot_status"], "inference_suppressed_insufficient_blocks"
        )

    def test_fit_failure_is_preserved_and_suppresses_the_full_holm_family(self):
        from lottery.reported_index_pilot import _calibrated_nll

        def fail_one(train, target, *, field, pool_size, pick, model):
            if (target["draw_id"] == "26007" and model == "ewma"
                    and field == "front_numbers"):
                raise ReportedIndexPilotError(
                    "ewma calibration failed at target 26007 (front_numbers): max_iterations"
                )
            return _calibrated_nll(
                train, target, field=field, pool_size=pool_size, pick=pick, model=model
            )

        with patch("lottery.reported_index_pilot._calibrated_nll", side_effect=fail_one):
            report = build_reported_index_pilot(
                self.view, self.manifest, code_commit="d" * 40
            )
        self.assertEqual(report["reported_index_pilot_status"], "incomplete_with_explicit_failures")
        self.assertFalse(report["score_coverage"]["complete_coverage"])
        self.assertEqual(report["score_coverage"]["expected_model_zone_target_records"], 36)
        self.assertEqual(report["score_coverage"]["scored_model_zone_target_records"], 35)
        self.assertEqual(report["score_coverage"]["failure_count"], 1)
        self.assertEqual(report["inference"]["status"], "suppressed_incomplete_coverage")
        self.assertEqual(report["inference"]["comparison_count"], 0)
        self.assertEqual(report["comparisons"], {})
        self.assertEqual(len(report["failures"]), 1)
        failure = report["failures"][0]
        self.assertEqual(failure["target_draw_id"], "26007")
        self.assertEqual(failure["model"], "ewma")
        self.assertEqual(failure["zone"], "front")
        self.assertEqual(failure["terminal_status"], "fit_failed")
        failed_row = next(row for row in report["score_rows"] if row["target_draw_id"] == "26007")
        self.assertEqual(
            failed_row["model_scores"]["ewma"]["front"]["terminal_status"], "fit_failed"
        )
        self.assertIsNone(failed_row["model_scores"]["ewma"]["front"]["exact_subset_nll"])


if __name__ == "__main__":
    unittest.main()
