import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lottery.jiangsu_draw_candidate import (
    JiangsuDrawCandidateError,
    build_jiangsu_draw_candidate,
)
from lottery.validate import validate_records


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def page(draw_id, date, label, order_front, order_back, result_front, result_back):
    return (
        "<html><body>"
        f"<h1>超级大乐透第{draw_id}期开奖公告</h1>"
        f"<p>开奖日期：{date}</p>"
        f"<p>本期使用第{label}套摇奖球</p>"
        "<footer>江苏省体育彩票管理中心版权所有</footer>"
        "<table>"
        f"<tr><td>本期出球顺序：</td><td>{order_front}</td><td>{order_back}</td></tr>"
        f"<tr><td>本期开奖号码：</td><td>{result_front}</td><td>{result_back}</td></tr>"
        "</table></body></html>"
    ).encode("utf-8")


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()


def make_inputs(root, *, mismatch=False, new_draw_id="26132"):
    inventory = [
        {
            "draw_id": "26130", "draw_date": "2026-11-14",
            "front_numbers": [1, 2, 3, 4, 5], "back_numbers": [1, 2],
            "front_draw_order": [1, 2, 3, 4, 5], "back_draw_order": [2, 1],
            "source_unsort_drawresult": None, "source_equipment_count": None,
            "source_id": "sha256:base-26130",
        },
        {
            "draw_id": "26131", "draw_date": "2026-11-16",
            "front_numbers": [6, 7, 8, 9, 10], "back_numbers": [3, 4],
            "front_draw_order": [6, 7, 8, 9, 10], "back_draw_order": [4, 3],
            "source_unsort_drawresult": None, "source_equipment_count": None,
            "source_id": "sha256:base-26131",
        },
    ]
    inventory_path = root / "inventory.jsonl"
    inventory_raw = b"".join(
        (json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n").encode()
        for row in inventory
    )
    inventory_path.write_bytes(inventory_raw)
    validation = validate_records(inventory)
    inventory_manifest = {
        "output_sha256": sha(inventory_raw),
        "validation": validation,
        "provenance_complete": True,
        "trust_status": "manifest_complete_not_officially_authenticated",
    }
    inventory_manifest_path = root / "inventory.jsonl.manifest.json"
    inventory_manifest_path.write_text(json.dumps(inventory_manifest), encoding="utf-8")

    archive = root / "archive"
    raw_dir = archive / "raw"
    raw_dir.mkdir(parents=True)
    ledger_path = archive / "observations.jsonl"
    ledger_path.write_text("fixture ledger bytes\n", encoding="utf-8")
    ledger_sha = sha(ledger_path.read_bytes())
    code_commit = "d" * 40
    coverage_sha = "c" * 64

    specs = [
        ("26130", "2026-11-14", 1, "01 02 03 04 05", "02 01", "01 02 03 04 05", "01 02", "obs-26130"),
        ("26131", "2026-11-16", 2, "06 07 08 09 10", "04 03", "06 07 08 09 10", "03 04", "obs-26131"),
        (new_draw_id, "2026-11-18" if new_draw_id == "26132" else "2026-11-20",
         1, "15 11 12 13 14", "06 05", "11 12 13 14 15", "05 06", "obs-new"),
    ]
    observations = []
    for draw_id, date, index, order_f, order_b, result_f, result_b, obs_id in specs:
        if mismatch and draw_id == "26130":
            result_f = "01 02 03 04 06"
            order_f = result_f
        body = page(draw_id, date.replace("-", "年", 1).replace("-", "月") + "日", index,
                    order_f, order_b, result_f, result_b)
        digest = sha(body)
        raw_ref = f"raw/{digest}.html"
        (archive / raw_ref).write_bytes(body)
        observations.append({
            "observation_id": obs_id,
            "draw_id": draw_id,
            "draw_date": date,
            "reported_set_index": index,
            "observation_status": "primary_verified" if draw_id in ("26130", "26131") else "official_label_pending_inventory",
            "source": {
                "authority_class": "A2",
                "source_authority_name": "Jiangsu Provincial Sports Lottery Management Center",
                "raw_object_ref": raw_ref,
                "body_sha256": digest,
                "body_byte_length": len(body),
                "content_type": "text/html; charset=utf-8",
                "final_url": f"https://www.js-lottery.com/cms/post-{draw_id}.html",
            },
        })

    frozen_rows = []
    for row, obs in zip(inventory, observations[:2]):
        frozen_rows.append({
            **row,
            "reported_set_index": obs["reported_set_index"],
            "evidence_status": "primary_verified",
            "observation_ids": [obs["observation_id"]],
            "source_urls": [obs["source"]["final_url"]],
            "inventory_sha256": sha(inventory_raw),
            "coverage_report_sha256": coverage_sha,
            "observation_ledger_sha256": ledger_sha,
            "equipment_regime_id": None,
            "physical_ball_set_id": None,
            "eligible_for_reported_index_pilot": True,
            "eligible_for_physical_model": False,
            "training_eligibility": "blocked_regime_unresolved",
            "model_scope": "reported_set_index_only_not_physical_identity",
        })
    frozen_path = root / "frozen.jsonl"
    frozen_raw = b"".join(
        (json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n").encode()
        for row in frozen_rows
    )
    frozen_path.write_bytes(frozen_raw)
    frozen_manifest = {
        "schema_version": "lottery.reported-set-index-view/v1",
        "pilot_protocol_version": "reported-set-index-pilot-v1",
        "inventory_sha256": sha(inventory_raw),
        "inventory_trust_status": "candidate_unverified",
        "coverage_report_sha256": coverage_sha,
        "observation_ledger_sha256": ledger_sha,
        "code_commit": code_commit,
        "record_count": 2,
        "set_index_counts": {"1": 1, "2": 1, "3": 0},
        "first_draw": "26130",
        "last_draw": "26131",
        "output_sha256": sha(frozen_raw),
        "training_eligibility": "blocked_regime_unresolved",
        "physical_model_eligibility": "blocked_regime_unresolved",
        "physical_identity_claim": "none",
        "model_scope": "reported_set_index_only_not_physical_identity",
    }
    frozen_manifest["manifest_sha256"] = sha(canonical(frozen_manifest))
    frozen_manifest_path = root / "frozen.manifest.json"
    frozen_manifest_path.write_text(json.dumps(frozen_manifest), encoding="utf-8")

    coverage = {
        "schema_version": "lottery.ball-set-coverage/v1",
        "inventory_sha256": sha(inventory_raw),
        "observation_ledger_sha256": ledger_sha,
        "code_commit": code_commit,
        "report_sha256": coverage_sha,
        "summary": {
            "primary_verified_draws": 2,
            "out_of_inventory_observation_count": 1,
        },
        "out_of_inventory_observations": [{
            "draw_id": new_draw_id,
            "draw_date": "2026-11-18" if new_draw_id == "26132" else "2026-11-20",
            "observation_id": "obs-new",
            "observation_status": "official_label_pending_inventory",
            "inventory_crosswalk_status": "not_in_inventory",
            "raw_evidence_verified": True,
            "reported_set_index": 1,
        }],
    }
    coverage_path = root / "coverage.json"
    coverage_path.write_text(json.dumps(coverage), encoding="utf-8")
    return {
        "inventory_path": inventory_path,
        "inventory_manifest_path": inventory_manifest_path,
        "coverage_path": coverage_path,
        "ledger_path": ledger_path,
        "archive": archive,
        "frozen_path": frozen_path,
        "frozen_manifest_path": frozen_manifest_path,
        "observations": observations,
        "code_commit": code_commit,
        "coverage_sha": coverage_sha,
    }


class JiangsuDrawCandidateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.inputs = make_inputs(self.root)
        self.patches = [
            patch("lottery.reported_index_pilot.PILOT_EXPECTED_RECORD_COUNT", 2),
            patch("lottery.reported_index_pilot.PILOT_EXPECTED_SET_COUNTS", {"1": 1, "2": 1, "3": 0}),
            patch("lottery.reported_index_pilot.PILOT_EXPECTED_FIRST_DRAW", "26130"),
            patch("lottery.reported_index_pilot.PILOT_EXPECTED_LAST_DRAW", "26131"),
            patch("lottery.jiangsu_draw_candidate._read_ledger", return_value=self.inputs["observations"]),
            patch("lottery.jiangsu_draw_candidate._verify_observation", side_effect=lambda obs, row, archive: (
                "primary_verified", obs["reported_set_index"], obs["source"]["final_url"]
            )),
            patch("lottery.jiangsu_draw_candidate.build_ball_set_coverage", return_value={
                "report_sha256": self.inputs["coverage_sha"]
            }),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def build(self, inputs=None):
        data = inputs or self.inputs
        return build_jiangsu_draw_candidate(
            data["inventory_path"], data["inventory_manifest_path"],
            data["coverage_path"], data["ledger_path"], data["archive"],
            data["frozen_path"], data["frozen_manifest_path"],
            self.root / "candidates", self.root / "live-view",
            code_commit=data["code_commit"],
        )

    def test_crosschecks_overlap_and_appends_latest_draw(self):
        receipt = self.build()
        candidate = Path(receipt["candidate_path"])
        candidate_rows = [json.loads(line) for line in candidate.read_text().splitlines()]
        self.assertEqual([row["draw_id"] for row in candidate_rows], ["26130", "26131", "26132"])
        self.assertEqual(candidate_rows[-1]["front_numbers"], [11, 12, 13, 14, 15])
        self.assertEqual(candidate_rows[-1]["back_numbers"], [5, 6])
        self.assertEqual(receipt["verified_overlap_draw_count"], 2)
        self.assertEqual(receipt["appended_draw_ids"], ["26132"])
        self.assertFalse(receipt["canonical_dataset_modified"])
        manifest = json.loads(Path(receipt["candidate_manifest_path"]).read_text())
        self.assertTrue(manifest["provenance_complete"])
        self.assertFalse(manifest["source_completeness_verified"])
        self.assertEqual(manifest["trust_status"], "manifest_complete_not_officially_authenticated")
        live = [json.loads(line) for line in Path(receipt["live_view_path"]).read_text().splitlines()]
        self.assertEqual(len(live), 3)
        self.assertEqual(live[-1]["draw_id"], "26132")
        self.assertTrue(live[-1]["draw_result_verified"])
        self.assertTrue(live[-1]["eligible_for_live_candidate_generation"])
        self.assertFalse(live[-1]["eligible_for_reported_index_pilot"])
        self.assertEqual(receipt["live_set_index_counts"], {"1": 2, "2": 1, "3": 0})

    def test_historical_result_mismatch_fails_closed(self):
        inputs = make_inputs(self.root / "mismatch", mismatch=True)
        with self.assertRaisesRegex(JiangsuDrawCandidateError, "A2 draw-result mismatches"):
            self.build(inputs)

    def test_nonsequential_new_draw_fails_closed(self):
        inputs = make_inputs(self.root / "gap", new_draw_id="26133")
        with self.assertRaisesRegex(JiangsuDrawCandidateError, "not the next chronological draw"):
            self.build(inputs)


if __name__ == "__main__":
    unittest.main()
