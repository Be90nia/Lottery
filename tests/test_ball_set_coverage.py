import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from lottery.ball_set_coverage import (
    BallSetCoverageError, build_ball_set_coverage, write_ball_set_coverage_report,
)
from lottery.ball_set_evidence import collect_ball_set_evidence

BASE = "https://www.js-lottery.com/cms/post-148224.html"


def page(label=3, draw_id="26128", date="2026年11月9日"):
    label_text = f"<p>本期使用第{label}套摇奖球</p>" if label is not None else ""
    return (
        "<html><body>"
        f"<h1>中国体育彩票超级大乐透第{draw_id}期开奖公告</h1>"
        f"<p>开奖日期：{date}</p>{label_text}"
        "<footer>江苏省体育彩票管理中心版权所有</footer>"
        "</body></html>"
    ).encode("utf-8")


def fetched(url, body, retrieved="2026-11-19T00:00:00+00:00"):
    return {"requested_url": url, "final_url": url, "redirect_chain": [],
            "retrieved_at_utc": retrieved, "http_status": 200,
            "content_type": "text/html; charset=utf-8", "body": body, "headers": {}}


class BallSetCoverageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.inventory = self.root / "inventory.jsonl"
        rows = [
            {"draw_id": "26128", "draw_date": "2026-11-09",
             "front_numbers": [3, 13, 20, 25, 34], "back_numbers": [9, 12],
             "source_id": "sha256:fixture-26128"},
            {"draw_id": "26129", "draw_date": "2026-11-11",
             "front_numbers": [2, 12, 14, 17, 33], "back_numbers": [7, 8],
             "source_id": "sha256:fixture-26129"},
        ]
        self.inventory.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
        self.archive = self.root / "archive"
        self.ledger = self.root / "observations.jsonl"
        self.receipt = self.root / "receipt.json"
        self.registry = self.root / "registry.json"
        self.registry.write_text(json.dumps({
            "schema_version": 1, "authority_class": "A2",
            "authority_name": "Jiangsu Provincial Sports Lottery Management Center",
            "seed_draw_id": "26128", "seed_draw_date": "2026-11-09", "seed_url": BASE,
        }), encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def collect(self, body, retrieved="2026-11-19T00:00:00+00:00"):
        with patch("lottery.ball_set_evidence.fetch_announcement",
                   return_value=fetched(BASE, body, retrieved)):
            return collect_ball_set_evidence(
                self.registry, self.archive, self.ledger,
                receipt_path=self.receipt, draw_inventory_path=self.inventory,
                delay_seconds=0, max_forward_pages=5,
            )

    def report(self):
        return build_ball_set_coverage(
            self.inventory, self.ledger, self.archive, code_commit="a" * 40
        )

    def test_verified_label_requires_raw_bytes_manifest_and_inventory_match(self):
        self.collect(page(3))
        report = self.report()
        self.assertEqual(report["summary"]["primary_verified_draws"], 1)
        self.assertEqual(report["summary"]["set_index_counts"], {"1": 0, "2": 0, "3": 1})
        self.assertEqual(report["per_draw"][0]["status"], "primary_verified")
        self.assertEqual(report["per_draw"][0]["reported_set_index"], 3)
        self.assertFalse(report["per_draw"][0]["eligible"])
        self.assertEqual(report["per_draw"][0]["exclusion_reason"], "regime_unresolved")
        self.assertEqual(report["per_set"]["3"]["denominator_status"], "unknown_regime_boundary")
        self.assertEqual(report["summary"]["eligible_slot_targets"], 0)
    def test_missing_official_footer_never_enters_verified_view(self):
        raw = page(3).replace("<footer>江苏省体育彩票管理中心版权所有</footer>".encode("utf-8"), b"")
        self.collect(raw)
        report = self.report()
        self.assertEqual(report["per_draw"][0]["status"], "source_authority_unverified")
        self.assertEqual(report["summary"]["primary_verified_draws"], 0)


    def test_missing_label_is_not_inferred(self):
        self.collect(page(None))
        report = self.report()
        self.assertEqual(report["per_draw"][0]["status"], "missing_official_label")
        self.assertEqual(report["summary"]["primary_verified_draws"], 0)

    def test_source_revision_requires_review_excludes_prior_verified_label(self):
        self.collect(page(3))
        self.collect(page(2), retrieved="2026-11-19T01:00:00+00:00")
        report = self.report()
        self.assertEqual(report["per_draw"][0]["status"], "source_revision_requires_review")
        self.assertEqual(report["summary"]["primary_verified_draws"], 0)
    def test_same_semantic_source_revision_keeps_label_verified(self):
        original = page(3)
        self.collect(original)
        revised = original.replace(b"</body>", b"<!-- harmless page chrome revision --></body>")
        self.collect(revised, retrieved="2026-11-19T01:00:00+00:00")
        records = [json.loads(line) for line in self.ledger.read_text().splitlines()]
        self.assertEqual(records[1]["observation_status"], "source_revision_same_semantics")
        report = self.report()
        self.assertEqual(report["per_draw"][0]["status"], "primary_verified")
        self.assertEqual(report["per_draw"][0]["reported_set_index"], 3)


    def test_conflict_record_excludes_draw_from_verified_view(self):
        raw = page(3).replace(
            "本期使用第3套摇奖球".encode("utf-8"),
            "本期使用第3套摇奖球 本期使用第2套摇奖球".encode("utf-8"),
        )
        self.collect(raw)
        report = self.report()
        self.assertEqual(report["per_draw"][0]["status"], "conflicting_official_sources")
        self.assertEqual(report["summary"]["primary_verified_draws"], 0)


    def test_tampered_raw_object_is_excluded(self):
        self.collect(page(3))
        raw = next((self.archive / "raw").glob("*.html"))
        raw.write_bytes(raw.read_bytes() + b"tampered")
        report = self.report()
        self.assertEqual(report["per_draw"][0]["status"], "parse_error")
        self.assertEqual(report["summary"]["raw_observation_objects_invalid"], 1)

    def test_report_hash_is_deterministic_and_outputs_are_atomic(self):
        self.collect(page(1))
        first = self.report()
        second = self.report()
        self.assertEqual(first["report_sha256"], second["report_sha256"])
        out_json, out_csv, out_md = (self.root / "coverage.json", self.root / "coverage.csv", self.root / "coverage.md")
        protected = {self.inventory.resolve(), self.ledger.resolve()}
        write_ball_set_coverage_report(first, output_json=out_json, output_csv=out_csv,
                                       output_markdown=out_md, protected_paths=protected)
        self.assertEqual(json.loads(out_json.read_text())["report_sha256"], first["report_sha256"])
        self.assertIn("regime_unresolved", out_md.read_text())
        with self.assertRaisesRegex(BallSetCoverageError, "overwrite an input"):
            write_ball_set_coverage_report(first, output_json=self.inventory, output_csv=out_csv,
                                           output_markdown=out_md, protected_paths=protected)

    def test_out_of_inventory_observation_is_reported_separately(self):
        second = "https://www.js-lottery.com/cms/post-148233.html"
        third = "https://www.js-lottery.com/cms/post-148247.html"
        pages = {
            BASE: fetched(BASE, page(3).replace(
                b"</body>", '<a href="/cms/post-148233.html">中国体育彩票超级大乐透第26129期开奖公告</a></body>'.encode("utf-8")
            )),
            second: fetched(second, page(2, "26129", "2026年11月11日").replace(
                b"</body>", '<a href="/cms/post-148247.html">中国体育彩票超级大乐透第26130期开奖公告</a></body>'.encode("utf-8")
            )),
            third: fetched(third, page(1, "26130", "2026年11月14日")),
        }
        with patch("lottery.ball_set_evidence.fetch_announcement", side_effect=lambda url: pages[url]):
            collect_ball_set_evidence(
                self.registry, self.archive, self.ledger,
                receipt_path=self.receipt, draw_inventory_path=self.inventory,
                delay_seconds=0, max_forward_pages=5,
            )
        report = self.report()
        self.assertEqual(report["out_of_inventory_observation_count"], 1)
        self.assertEqual(report["out_of_inventory_observations"][0]["draw_id"], "26130")
        self.assertEqual(report["out_of_inventory_observations"][0]["reported_set_index"], 1)
        self.assertEqual(report["out_of_inventory_observations"][0]["exclusion_reason"], "inventory_crosswalk_pending")
        self.assertEqual(report["per_draw"][0]["status"], "primary_verified")



if __name__ == "__main__":
    unittest.main()
