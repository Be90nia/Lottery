import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lottery.reported_index_mvp import (
    ReportedIndexMVPError,
    build_reported_index_mvp,
    write_reported_index_mvp,
)


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def make_inputs(root):
    rows = []
    for i, set_index in enumerate([1, 2, 3] * 4, 1):
        draw_id = f"260{i:02d}"
        start = ((i - 1) % 30) + 1
        back_start = ((i - 1) % 11) + 1
        rows.append({
            "draw_id": draw_id,
            "draw_date": f"2026-01-{i:02d}",
            "front_numbers": list(range(start, start + 5)),
            "back_numbers": sorted([back_start, back_start + 1]),
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
    view = root / "view.jsonl"
    raw = b"".join(
        (json.dumps(row, sort_keys=True) + "\n").encode() for row in rows
    )
    view.write_bytes(raw)
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
    pilot_body = {
        "schema_version": "lottery.reported-index-pilot/v1",
        "view_manifest_sha256": manifest["manifest_sha256"],
        "view_sha256": manifest["output_sha256"],
        "reported_index_pilot_status": "research_only_complete",
        "physical_model_eligibility": "blocked_regime_unresolved",
        "physical_identity_claim": "none",
        "predictive_efficacy_claim": "none",
        "production_ready": False,
        "automatic_promotion": False,
        "holdout_accessed": False,
        "holdout_feedback_used": False,
        "inference": {"comparison_count": 12},
        "decision": "no_confirmed_index_specific_improvement_over_uniform",
    }
    pilot = {**pilot_body, "report_sha256": sha(canonical(pilot_body))}
    pilot_path = root / "pilot.json"
    pilot_path.write_text(json.dumps(pilot), encoding="utf-8")
    return view, manifest_path, pilot_path


class ReportedIndexMVPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.view, self.manifest, self.pilot = make_inputs(self.root)
        self.patches = [
            patch("lottery.reported_index_pilot.PILOT_EXPECTED_RECORD_COUNT", 12),
            patch("lottery.reported_index_pilot.PILOT_EXPECTED_SET_COUNTS", {"1": 4, "2": 4, "3": 4}),
            patch("lottery.reported_index_pilot.PILOT_EXPECTED_FIRST_DRAW", "26001"),
            patch("lottery.reported_index_pilot.PILOT_EXPECTED_LAST_DRAW", "26012"),
            patch("lottery.reported_index_mvp.PILOT_EXPECTED_SET_COUNTS", {"1": 4, "2": 4, "3": 4}),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    @staticmethod
    def fake_generator(rows, *, tickets_per_strategy, seed, alpha, half_life, code_commit):
        return {
            "code_commit": code_commit,
            "training_draw_count": len(rows),
            "total_tickets": tickets_per_strategy * 3,
            "training_dataset_fingerprint": sha(canonical(rows)),
            "generation_run_id": sha(f"{seed}:{len(rows)}".encode()),
            "strategy_metadata": {"uniform": {}, "expanding": {}, "ewma": {}},
            "strategies": {"uniform": [], "expanding": [], "ewma": []},
            "limitations": ["research-only"],
        }

    def test_generates_all_three_index_batches_without_selecting_a_winner(self):
        with patch("lottery.reported_index_mvp.generate_ticket_candidates", side_effect=self.fake_generator) as generate:
            report = build_reported_index_mvp(
                self.view, self.manifest, self.pilot,
                tickets_per_strategy=5, seed=123, code_commit="e" * 40,
            )
        self.assertEqual(generate.call_count, 3)
        self.assertEqual(report["total_tickets"], 45)
        self.assertEqual(set(report["index_batches"]), {"1", "2", "3"})
        self.assertEqual(report["pilot_decision"], "no_confirmed_index_specific_improvement_over_uniform")
        self.assertEqual(report["physical_identity_claim"], "none")
        self.assertEqual(report["physical_model_eligibility"], "blocked_regime_unresolved")
        self.assertFalse(report["holdout_accessed"])
        self.assertFalse(report["automatic_promotion"])
        self.assertEqual(len(report["report_sha256"]), 64)

    def test_pilot_view_hash_mismatch_fails_closed(self):
        pilot = json.loads(self.pilot.read_text())
        pilot["view_sha256"] = "0" * 64
        body = {key: value for key, value in pilot.items() if key != "report_sha256"}
        pilot["report_sha256"] = sha(canonical(body))
        self.pilot.write_text(json.dumps(pilot), encoding="utf-8")
        with patch("lottery.reported_index_mvp.generate_ticket_candidates") as generate:
            with self.assertRaisesRegex(ReportedIndexMVPError, "pilot receipt does not match"):
                build_reported_index_mvp(
                    self.view, self.manifest, self.pilot, code_commit="e" * 40
                )
        generate.assert_not_called()

    def test_tampered_pilot_hash_fails_closed(self):
        pilot = json.loads(self.pilot.read_text())
        pilot["decision"] = "selected_winner"
        self.pilot.write_text(json.dumps(pilot), encoding="utf-8")
        with self.assertRaisesRegex(ReportedIndexMVPError, "pilot report hash mismatch"):
            build_reported_index_mvp(
                self.view, self.manifest, self.pilot, code_commit="e" * 40
            )

    def test_candidate_artifact_is_write_once(self):
        with patch("lottery.reported_index_mvp.generate_ticket_candidates", side_effect=self.fake_generator):
            report = build_reported_index_mvp(
                self.view, self.manifest, self.pilot, code_commit="e" * 40
            )
        output = write_reported_index_mvp(report, self.root / "out")
        original = output.read_bytes()
        self.assertEqual(write_reported_index_mvp(report, self.root / "out").read_bytes(), original)
        output.write_bytes(b"tampered")
        with self.assertRaisesRegex(ReportedIndexMVPError, "conflicts"):
            write_reported_index_mvp(report, self.root / "out")


if __name__ == "__main__":
    unittest.main()
