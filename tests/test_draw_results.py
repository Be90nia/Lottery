import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from lottery.ball_set_evidence import collect_ball_set_evidence
from lottery.draw_results import (
    DrawResultLedgerError, read_draw_result_ledger, verify_draw_result_record,
)

URL = "https://www.js-lottery.com/cms/post-148224.html"


def page(draw_id="26128", date="2026年11月9日", numbers="03 13 20 25 34 09 12"):
    return (
        "<html><body>"
        f"<h1>中国体育彩票超级大乐透第{draw_id}期开奖公告</h1>"
        f"<p>开奖日期：{date}</p>"
        "<p>本期使用第3套摇奖球</p>"
        f"<p>本期开奖号码：{numbers}</p>"
        "<footer>江苏省体育彩票管理中心版权所有</footer>"
        "</body></html>"
    ).encode("utf-8")


class DrawResultLedgerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.archive = self.root / "archive"
        self.inventory = self.root / "inventory.jsonl"
        self.inventory.write_text(json.dumps({
            "draw_id": "26128", "draw_date": "2026-11-09",
            "front_numbers": [3, 13, 20, 25, 34], "back_numbers": [9, 12],
            "source_id": "sha256:fixture",
        }) + "\n", encoding="utf-8")
        self.observations = self.root / "observations.jsonl"
        self.results = self.root / "draw-results.jsonl"
        self.receipt = self.root / "receipt.json"
        self.registry = self.root / "registry.json"
        self.registry.write_text(json.dumps({
            "schema_version": 1, "authority_class": "A2",
            "authority_name": "Jiangsu Provincial Sports Lottery Management Center",
            "seed_draw_id": "26128", "seed_draw_date": "2026-11-09", "seed_url": URL,
        }), encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def collect(self, body, *, seed_id="26128", seed_date="2026-11-09"):
        registry = json.loads(self.registry.read_text())
        registry["seed_draw_id"] = seed_id
        registry["seed_draw_date"] = seed_date
        self.registry.write_text(json.dumps(registry), encoding="utf-8")
        fetched = {
            "requested_url": URL, "final_url": URL, "redirect_chain": [],
            "retrieved_at_utc": "2026-11-19T00:00:00+00:00", "http_status": 200,
            "content_type": "text/html; charset=utf-8", "body": body, "headers": {},
        }
        with patch("lottery.ball_set_evidence.fetch_announcement", return_value=fetched):
            return collect_ball_set_evidence(
                self.registry, self.archive, self.observations,
                receipt_path=self.receipt, draw_inventory_path=self.inventory,
                draw_result_ledger_path=self.results, delay_seconds=0, max_forward_pages=5,
            )

    def test_inventory_match_is_hash_chained_and_reproducible(self):
        self.collect(page())
        records = read_draw_result_ledger(self.results)
        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertEqual(record["draw_result_status"], "inventory_matched")
        self.assertEqual(record["front_numbers"], [3, 13, 20, 25, 34])
        self.assertEqual(record["back_numbers"], [9, 12])
        self.assertEqual(record["prev_hash"], "0" * 64)
        verified = verify_draw_result_record(record, json.loads(self.inventory.read_text()), self.archive)
        self.assertEqual(verified["status"], "inventory_matched")

    def test_future_draw_is_verified_but_remains_inventory_pending(self):
        self.collect(page("26129", "2026年11月11日", "02 12 14 17 33 07 08"),
                     seed_id="26129", seed_date="2026-11-11")
        record = read_draw_result_ledger(self.results)[0]
        self.assertEqual(record["draw_result_status"], "pending_inventory")
        verified = verify_draw_result_record(record, None, self.archive)
        self.assertEqual(verified["status"], "pending_inventory")
        self.assertEqual(verified["front_numbers"], [2, 12, 14, 17, 33])

    def test_candidate_inventory_number_mismatch_fails_closed(self):
        self.collect(page(numbers="01 13 20 25 34 09 12"))
        record = read_draw_result_ledger(self.results)[0]
        self.assertEqual(record["draw_result_status"], "draw_result_mismatch")
        self.assertEqual(self.receipt.exists(), True)
        receipt = json.loads(self.receipt.read_text())
        self.assertEqual(receipt["status"], "review_required")

    def test_draw_result_ledger_hash_chain_detects_tampering(self):
        self.collect(page())
        lines = self.results.read_text(encoding="utf-8").splitlines()
        record = json.loads(lines[0])
        record["front_numbers"][0] = 1
        lines[0] = json.dumps(record)
        self.results.write_text("\n".join(lines) + "\n", encoding="utf-8")
        with self.assertRaisesRegex(DrawResultLedgerError, "event hash mismatch"):
            read_draw_result_ledger(self.results)


if __name__ == "__main__":
    unittest.main()
