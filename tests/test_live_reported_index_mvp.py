import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lottery.live_reported_index_mvp import (
    LiveReportedIndexMVPError,
    build_live_reported_index_mvp,
)


TRUST = "manifest_complete_not_officially_authenticated"
MODEL_SCOPE = "reported_set_index_only_not_physical_identity"


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def jsonl(rows):
    return b"".join(
        (json.dumps(row, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n").encode()
        for row in rows
    )


def make_row(draw_id, date, index, start, back, source_id, observation_id):
    front = list(range(start, start + 5))
    back_numbers = [back, back + 1]
    return {
        "draw_id": draw_id,
        "draw_date": date,
        "front_numbers": front,
        "back_numbers": back_numbers,
        "front_draw_order": front,
        "back_draw_order": list(reversed(back_numbers)),
        "source_unsort_drawresult": None,
        "source_equipment_count": None,
        "source_id": source_id,
        "reported_set_index": index,
        "evidence_status": "primary_verified",
        "observation_ids": [observation_id],
        "source_urls": [f"https://www.js-lottery.com/cms/post-{draw_id}.html"],
        "inventory_sha256": "b" * 64,
        "coverage_report_sha256": "c" * 64,
        "observation_ledger_sha256": "d" * 64,
        "equipment_regime_id": None,
        "physical_ball_set_id": None,
        "eligible_for_reported_index_pilot": True,
        "eligible_for_physical_model": False,
        "training_eligibility": "blocked_regime_unresolved",
        "model_scope": MODEL_SCOPE,
    }


def make_inputs(root):
    root.mkdir(parents=True, exist_ok=True)
    frozen_rows = [
        make_row("26129", "2026-11-12", 3, 1, 1, "sha256:base-26129", "obs-26129"),
        make_row("26130", "2026-11-14", 1, 6, 3, "sha256:base-26130", "obs-26130"),
        make_row("26131", "2026-11-16", 2, 11, 5, "sha256:base-26131", "obs-26131"),
    ]
    frozen_path = root / "frozen.jsonl"
    frozen_raw = jsonl(frozen_rows)
    frozen_path.write_bytes(frozen_raw)
    frozen_manifest_body = {
        "schema_version": "lottery.reported-set-index-view/v1",
        "pilot_protocol_version": "reported-set-index-pilot-v1",
        "inventory_sha256": "b" * 64,
        "inventory_trust_status": "candidate_unverified",
        "coverage_report_sha256": "c" * 64,
        "observation_ledger_sha256": "d" * 64,
        "code_commit": "e" * 40,
        "record_count": 3,
        "set_index_counts": {"1": 1, "2": 1, "3": 1},
        "first_draw": "26129",
        "last_draw": "26131",
        "output_sha256": sha(frozen_raw),
        "training_eligibility": "blocked_regime_unresolved",
        "physical_model_eligibility": "blocked_regime_unresolved",
        "physical_identity_claim": "none",
        "model_scope": MODEL_SCOPE,
    }
    frozen_manifest = {
        **frozen_manifest_body,
        "manifest_sha256": sha(canonical(frozen_manifest_body)),
    }
    frozen_manifest_path = root / "frozen.manifest.json"
    frozen_manifest_path.write_text(json.dumps(frozen_manifest), encoding="utf-8")

    candidate_rows = [
        {key: row[key] for key in (
            "draw_id", "draw_date", "front_numbers", "back_numbers",
            "front_draw_order", "back_draw_order", "source_unsort_drawresult",
            "source_equipment_count", "source_id",
        )}
        for row in frozen_rows
    ]
    new_digest = "f" * 64
    new_row = {
        "draw_id": "26132",
        "draw_date": "2026-11-18",
        "front_numbers": [16, 17, 18, 19, 20],
        "back_numbers": [7, 8],
        "front_draw_order": [20, 16, 17, 18, 19],
        "back_draw_order": [8, 7],
        "source_unsort_drawresult": None,
        "source_equipment_count": None,
        "source_id": f"sha256:{new_digest}",
    }
    candidate_rows.append(new_row)
    candidate_path = root / "candidate.jsonl"
    candidate_raw = jsonl(candidate_rows)
    candidate_path.write_bytes(candidate_raw)
    from lottery.validate import validate_records
    validation = validate_records(candidate_rows)
    candidate_manifest = {
        "schema_version": "lottery.jiangsu-draw-candidate/v1",
        "output_sha256": sha(candidate_raw),
        "validation": validation,
        "provenance_complete": True,
        "source_completeness_verified": False,
        "trust_status": TRUST,
        "base_inventory_sha256": "b" * 64,
        "coverage_report_sha256": "c" * 64,
        "observation_ledger_sha256": "d" * 64,
        "verified_overlap_draw_count": 3,
        "appended_draw_ids": ["26132"],
    }
    candidate_manifest_path = root / "candidate.jsonl.manifest.json"
    candidate_manifest_raw = (json.dumps(candidate_manifest, sort_keys=True) + "\n").encode()
    candidate_manifest_path.write_bytes(candidate_manifest_raw)

    live_rows = []
    for i, frozen in enumerate(frozen_rows):
        live = dict(frozen)
        live.update({
            "eligible_for_reported_index_pilot": False,
            "eligible_for_live_candidate_generation": True,
            "draw_result_verified": True,
            "front_draw_order": list(frozen["front_draw_order"]),
            "back_draw_order": list(frozen["back_draw_order"]),
            "source_draw_result_sha256": f"{i + 1:064x}",
            "source_authority_class": "A2",
            "source_authority_name": "Jiangsu Provincial Sports Lottery Management Center",
            "source_observation_id": frozen["observation_ids"][0],
            "source_draw_result_url": frozen["source_urls"][0],
        })
        live_rows.append(live)
    live_rows.append({
        "draw_id": "26132",
        "draw_date": "2026-11-18",
        "front_numbers": [16, 17, 18, 19, 20],
        "back_numbers": [7, 8],
        "front_draw_order": [20, 16, 17, 18, 19],
        "back_draw_order": [8, 7],
        "source_id": f"sha256:{new_digest}",
        "reported_set_index": 1,
        "evidence_status": "primary_verified_new_draw",
        "observation_ids": ["obs-26132"],
        "source_urls": ["https://www.js-lottery.com/cms/post-26132.html"],
        "source_draw_result_sha256": new_digest,
        "source_authority_class": "A2",
        "source_authority_name": "Jiangsu Provincial Sports Lottery Management Center",
        "source_observation_id": "obs-26132",
        "source_draw_result_url": "https://www.js-lottery.com/cms/post-26132.html",
        "inventory_sha256": "b" * 64,
        "coverage_report_sha256": "c" * 64,
        "observation_ledger_sha256": "d" * 64,
        "equipment_regime_id": None,
        "physical_ball_set_id": None,
        "eligible_for_reported_index_pilot": False,
        "eligible_for_physical_model": False,
        "eligible_for_live_candidate_generation": True,
        "training_eligibility": "blocked_regime_unresolved",
        "model_scope": MODEL_SCOPE,
        "draw_result_verified": True,
    })
    live_path = root / "live.jsonl"
    live_raw = jsonl(live_rows)
    live_path.write_bytes(live_raw)
    live_manifest_body = {
        "schema_version": "lottery.reported-set-index-live-view/v1",
        "frozen_pilot_view_manifest_sha256": frozen_manifest["manifest_sha256"],
        "inventory_sha256": "b" * 64,
        "candidate_dataset_sha256": sha(candidate_raw),
        "candidate_dataset_manifest_sha256": sha(candidate_manifest_raw),
        "coverage_report_sha256": "c" * 64,
        "observation_ledger_sha256": "d" * 64,
        "record_count": 4,
        "set_index_counts": {"1": 2, "2": 1, "3": 1},
        "first_draw": "26129",
        "last_draw": "26132",
        "appended_draw_ids": ["26132"],
        "verified_overlap_draw_count": 3,
        "source_completeness_verified": False,
        "inventory_trust_status": TRUST,
        "training_eligibility": "blocked_regime_unresolved",
        "physical_identity_claim": "none",
        "model_scope": MODEL_SCOPE,
        "code_commit": "e" * 40,
        "output_sha256": sha(live_raw),
    }
    live_manifest = {
        **live_manifest_body,
        "manifest_sha256": sha(canonical(live_manifest_body)),
    }
    live_manifest_path = root / "live.manifest.json"
    live_manifest_path.write_text(json.dumps(live_manifest), encoding="utf-8")

    pilot_body = {
        "schema_version": "lottery.reported-index-pilot/v1",
        "view_manifest_sha256": frozen_manifest["manifest_sha256"],
        "view_sha256": frozen_manifest["output_sha256"],
        "reported_index_pilot_status": "research_only_complete",
        "target_counts": {"1": 160, "2": 147, "3": 160},
        "inference": {"comparison_count": 12},
        "physical_identity_claim": "none",
        "physical_model_eligibility": "blocked_regime_unresolved",
        "predictive_efficacy_claim": "none",
        "production_ready": False,
        "automatic_promotion": False,
        "holdout_accessed": False,
        "holdout_feedback_used": False,
        "decision": "no_confirmed_index_specific_improvement_over_uniform",
        "significant_index_specific_improvements": [],
    }
    pilot = {**pilot_body, "report_sha256": sha(canonical(pilot_body))}
    pilot_path = root / "pilot.json"
    pilot_path.write_text(json.dumps(pilot), encoding="utf-8")
    return frozen_path, frozen_manifest_path, live_path, live_manifest_path, candidate_path, candidate_manifest_path, pilot_path


class LiveReportedIndexMVPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (
            self.frozen, self.frozen_manifest, self.live, self.live_manifest,
            self.candidate, self.candidate_manifest, self.pilot,
        ) = make_inputs(self.root)
        self.patches = [
            patch("lottery.reported_index_pilot.PILOT_EXPECTED_RECORD_COUNT", 3),
            patch("lottery.reported_index_pilot.PILOT_EXPECTED_SET_COUNTS", {"1": 1, "2": 1, "3": 1}),
            patch("lottery.reported_index_pilot.PILOT_EXPECTED_FIRST_DRAW", "26129"),
            patch("lottery.reported_index_pilot.PILOT_EXPECTED_LAST_DRAW", "26131"),
            patch("lottery.live_reported_index_mvp.generate_ticket_candidates", side_effect=self.fake_generator),
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
            "model_configuration": {"alpha": alpha, "ewma_half_life_draws": half_life},
            "rng": {"algorithm": "Python random.Random (MT19937)", "seed": seed},
            "sampler_version": "conditional-poisson-rejective-v1",
            "strategies": {"uniform": [], "expanding": [], "ewma": []},
            "limitations": ["research-only"],
        }

    def build(self):
        return build_live_reported_index_mvp(
            self.frozen, self.frozen_manifest, self.live, self.live_manifest,
            self.candidate, self.candidate_manifest, self.pilot,
            tickets_per_strategy=5, seed=123, code_commit="e" * 40,
        )

    def test_generates_live_candidates_from_verified_appended_draw(self):
        report = self.build()
        self.assertEqual(report["total_tickets"], 45)
        self.assertEqual(report["appended_draw_ids"], ["26132"])
        self.assertEqual(report["live_set_index_counts"], {"1": 2, "2": 1, "3": 1})
        self.assertEqual(report["latest_draw_id"], "26132")
        self.assertEqual(report["index_batches"]["1"]["training_draw_count"], 2)
        self.assertEqual(report["index_batches"]["1"]["training_last_draw_id"], "26132")
        self.assertFalse(report["holdout_accessed"])
        self.assertFalse(report["automatic_promotion"])
        self.assertEqual(report["physical_model_eligibility"], "blocked_regime_unresolved")

    def test_tampered_live_manifest_fails_closed(self):
        manifest = json.loads(self.live_manifest.read_text())
        manifest["appended_draw_ids"] = []
        self.live_manifest.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(LiveReportedIndexMVPError, "manifest hash mismatch"):
            self.build()

    def test_new_draw_must_be_sequential(self):
        live_rows = [json.loads(line) for line in self.live.read_text().splitlines()]
        live_rows[-1]["draw_id"] = "26133"
        live_rows[-1]["draw_date"] = "2026-11-20"
        live_raw = jsonl(live_rows)
        self.live.write_bytes(live_raw)
        live_manifest = json.loads(self.live_manifest.read_text())
        live_manifest.pop("manifest_sha256")
        live_manifest["output_sha256"] = sha(live_raw)
        live_manifest["last_draw"] = "26133"
        live_manifest["appended_draw_ids"] = ["26133"]
        live_manifest["manifest_sha256"] = sha(canonical(live_manifest))
        self.live_manifest.write_text(json.dumps(live_manifest), encoding="utf-8")
        with self.assertRaisesRegex(LiveReportedIndexMVPError, "appended draw is not strictly sequential"):
            self.build()


if __name__ == "__main__":
    unittest.main()
