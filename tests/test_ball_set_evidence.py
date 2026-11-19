import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from lottery.ball_set_evidence import (
    BallSetEvidenceError,
    collect_ball_set_evidence,
    parse_announcement,
    _next_draw_id,
)

BASE = "https://www.js-lottery.com/cms/post-148224.html"


def page(draw_id="26128", date="2026年11月9日", label=3, newer=None, footer=True):
    label_text = f"<p>本期使用第{label}套摇奖球</p>" if label is not None else ""
    footer_text = "<footer>江苏省体育彩票管理中心版权所有</footer>" if footer else ""
    link = ""
    if newer:
        next_id, href = newer
        link = f'<a href="{href}">中国体育彩票超级大乐透第{next_id}期开奖公告</a>'
    return (
        "<html><body>"
        f"<h1>中国体育彩票超级大乐透第{draw_id}期开奖公告</h1>"
        f"<p>开奖日期：{date}</p>{label_text}{link}{footer_text}"
        "</body></html>"
    ).encode("utf-8")


def fetched(url, body, status=200):
    return {
        "requested_url": url, "final_url": url, "redirect_chain": [],
        "retrieved_at_utc": "2026-11-19T00:00:00+00:00",
        "http_status": status, "content_type": "text/html; charset=utf-8",
        "body": body, "headers": {},
    }


class BallSetParserTests(unittest.TestCase):
    def test_explicit_indices_1_2_3_are_parsed(self):
        for index in (1, 2, 3):
            parsed = parse_announcement(page(label=index), BASE)
            self.assertEqual(parsed.draw_id, "26128")
            self.assertEqual(parsed.draw_date, "2026-11-09")
            self.assertEqual(parsed.reported_set_index, index)
            self.assertEqual(parsed.observation_status, "primary_verified")
            self.assertEqual(parsed.matched_text, f"本期使用第{index}套摇奖球")
            self.assertTrue(parsed.authority_footer_present)

    def test_missing_label_stays_unknown(self):
        parsed = parse_announcement(page(label=None), BASE)
        self.assertIsNone(parsed.reported_set_index)
        self.assertEqual(parsed.observation_status, "missing_label")

    def test_conflicting_labels_are_not_resolved(self):
        raw = page(label=1).replace("本期使用第1套摇奖球".encode(), "本期使用第1套摇奖球 本期使用第2套摇奖球".encode())
        parsed = parse_announcement(raw, BASE)
        self.assertIsNone(parsed.reported_set_index)
        self.assertEqual(parsed.observation_status, "conflict")

    def test_newer_article_link_is_resolved_and_old_link_ignored(self):
        raw = page(newer=("26129", "/cms/post-148233.html"))
        parsed = parse_announcement(raw, BASE)
        self.assertEqual(parsed.newer_links, (("26129", "https://www.js-lottery.com/cms/post-148233.html"),))
    def test_draw_id_sequence_and_year_rollover_are_bounded(self):
        self.assertTrue(_next_draw_id("26154", "26155"))
        self.assertTrue(_next_draw_id("26155", "27001"))
        self.assertFalse(_next_draw_id("26010", "27001"))
        self.assertFalse(_next_draw_id("26154", "26156"))


    def test_non_official_host_is_rejected(self):
        with self.assertRaisesRegex(BallSetEvidenceError, "not an approved official"):
            parse_announcement(page(), "https://example.com/fake.html")
    def test_meta_charset_is_used_when_header_has_none(self):
        html = page(label=2).decode("utf-8")
        raw = ('<meta charset="gbk">' + html).encode("gbk")
        parsed = parse_announcement(raw, BASE, "text/html")
        self.assertEqual(parsed.reported_set_index, 2)


    def test_missing_draw_id_or_date_is_rejected(self):
        with self.assertRaisesRegex(BallSetEvidenceError, "missing an explicit"):
            parse_announcement(b"<html><body>no draw details</body></html>", BASE)

    def test_unsupported_explicit_set_index_is_not_misclassified_as_missing(self):
        parsed = parse_announcement(page(label=4), BASE)
        self.assertIsNone(parsed.reported_set_index)
        self.assertEqual(parsed.observation_status, "unsupported_label")
        self.assertEqual(parsed.matched_text, "本期使用第4套摇奖球")


class BallSetArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.registry = self.root / "registry.json"
        self.registry.write_text(json.dumps({
            "schema_version": 1, "authority_class": "A2",
            "authority_name": "Jiangsu Provincial Sports Lottery Management Center",
            "seed_draw_id": "26128", "seed_draw_date": "2026-11-09",
            "seed_url": BASE,
        }), encoding="utf-8")
        self.inventory = self.root / "draw-inventory.jsonl"
        inventory_rows = [
            {"draw_id": "26128", "draw_date": "2026-11-09", "front_numbers": [3, 13, 20, 25, 34],
             "back_numbers": [9, 12], "source_id": "sha256:fixture-26128"},
            {"draw_id": "26129", "draw_date": "2026-11-11", "front_numbers": [2, 12, 14, 17, 33],
             "back_numbers": [7, 8], "source_id": "sha256:fixture-26129"},
        ]
        self.inventory.write_text("".join(json.dumps(row) + "\n" for row in inventory_rows), encoding="utf-8")
        self.archive = self.root / "archive"
        self.ledger = self.root / "observations.jsonl"
        self.receipt = self.root / "receipt.json"

    def tearDown(self):
        self.temp.cleanup()

    def collect(self, fake_fetch, max_pages=10):
        with patch("lottery.ball_set_evidence.fetch_announcement", side_effect=fake_fetch):
            return collect_ball_set_evidence(
                self.registry, self.archive, self.ledger,
                receipt_path=self.receipt, draw_inventory_path=self.inventory,
                delay_seconds=0, max_forward_pages=max_pages,
            )

    def test_walks_newer_chain_and_archives_raw_bytes_before_parse(self):
        next_url = "https://www.js-lottery.com/cms/post-148233.html"
        pages = {
            BASE: fetched(BASE, page(newer=("26129", "/cms/post-148233.html"))),
            next_url: fetched(next_url, page("26129", "2026年11月11日", 2)),
        }
        receipt = self.collect(lambda url: pages[url])
        self.assertEqual(receipt["status"], "captured")
        self.assertEqual([x["draw_id"] for x in receipt["pages_observed"]], ["26128", "26129"])
        records = [json.loads(line) for line in self.ledger.read_text().splitlines()]
        self.assertEqual([r["reported_set_index"] for r in records], [3, 2])
        self.assertTrue(all(r["observation_status"] == "primary_verified" for r in records))
        raw_files = list((self.archive / "raw").glob("*.html"))
        self.assertEqual(len(raw_files), 2)
        for raw_file in raw_files:
            digest = hashlib.sha256(raw_file.read_bytes()).hexdigest()
            self.assertEqual(raw_file.stem, digest)
        self.assertFalse(receipt["source_completeness_verified"])
        self.assertTrue(all(r["equipment_regime_id"] is None for r in records))

    def test_identical_latest_page_is_idempotent(self):
        self.collect(lambda url: fetched(url, page(newer=("26129", "/cms/post-148233.html")))
                     if url == BASE else fetched(url, page("26129", "2026年11月11日", 2)))
        next_url = "https://www.js-lottery.com/cms/post-148233.html"
        receipt = self.collect(lambda url: fetched(url, page("26129", "2026年11月11日", 2)))
        self.assertEqual(receipt["status"], "no_new_page")
        self.assertEqual(len(self.ledger.read_text().splitlines()), 2)
        self.assertEqual(receipt["observation_results"][0]["status"], "duplicate_noop")

    def test_changed_bytes_from_same_url_create_review_version(self):
        self.collect(lambda url: fetched(url, page()))
        revised = page("26128", "2026年11月9日", 2)
        receipt = self.collect(lambda url: fetched(url, revised))
        self.assertEqual(receipt["status"], "review_required")
        records = [json.loads(line) for line in self.ledger.read_text().splitlines()]
        self.assertEqual(len(records), 2)
        self.assertEqual(records[1]["observation_status"], "source_revision_requires_review")
        self.assertEqual(records[1]["supersedes_observation_id"], records[0]["observation_id"])
        self.assertEqual(records[0]["reported_set_index"], 3)
        self.assertEqual(records[1]["reported_set_index"], 2)

    def test_unpublished_next_draw_is_a_successful_noop(self):
        next_url = "https://www.js-lottery.com/cms/post-148233.html"
        def fake(url):
            if url == BASE:
                return fetched(url, page(newer=("26129", "/cms/post-148233.html")))
            return fetched(url, b"not found", status=404)
        receipt = self.collect(fake)
        self.assertEqual(receipt["status"], "not_yet_published")
        self.assertEqual(receipt["next_expected_draw_id"], "26129")
        self.assertEqual(len(self.ledger.read_text().splitlines()), 1)

    def test_chain_gap_fails_closed(self):
        receipt = self.collect(lambda url: fetched(url, page(newer=("26130", "/cms/post-148247.html"))))
        self.assertEqual(receipt["status"], "draw_mismatch")
        self.assertTrue(receipt["errors"])
        self.assertEqual(len(self.ledger.read_text().splitlines()), 1)

    def test_parse_failure_still_preserves_exact_raw_response(self):
        receipt = self.collect(lambda url: fetched(url, b"<html>unparseable</html>"))
        self.assertEqual(receipt["status"], "parse_error")
        raw_files = list((self.archive / "raw").glob("*.html"))
        self.assertEqual(len(raw_files), 1)
        self.assertEqual(raw_files[0].read_bytes(), b"<html>unparseable</html>")
        self.assertEqual(self.ledger.exists(), False)

    def test_source_unavailable_is_recorded_in_receipt(self):
        def fail(url):
            raise BallSetEvidenceError("HTTP 567 blocked")
        receipt = self.collect(fail)
        self.assertEqual(receipt["status"], "source_unavailable")
        self.assertIn("HTTP 567 blocked", receipt["errors"][0])
        self.assertTrue(self.receipt.exists())

    def test_label_outside_inventory_is_pending_not_primary_verified(self):
        next_url = "https://www.js-lottery.com/cms/post-148233.html"
        third_url = "https://www.js-lottery.com/cms/post-148247.html"
        pages = {
            BASE: fetched(BASE, page(newer=("26129", "/cms/post-148233.html"))),
            next_url: fetched(next_url, page("26129", "2026年11月11日", 2,
                                             newer=("26130", "/cms/post-148247.html"))),
            third_url: fetched(third_url, page("26130", "2026年11月14日", 1)),
        }
        receipt = self.collect(lambda url: pages[url])
        records = [json.loads(line) for line in self.ledger.read_text().splitlines()]
        self.assertEqual(receipt["inventory_crosswalk"]["not_in_inventory"], 1)
        self.assertEqual(records[-1]["observation_status"], "official_label_pending_inventory")
        self.assertEqual(records[-1]["reported_set_index"], 1)

    def test_inventory_date_mismatch_fails_closed(self):
        next_url = "https://www.js-lottery.com/cms/post-148233.html"
        pages = {
            BASE: fetched(BASE, page(newer=("26129", "/cms/post-148233.html"))),
            next_url: fetched(next_url, page("26129", "2026年11月12日", 2)),
        }
        receipt = self.collect(lambda url: pages[url])
        self.assertEqual(receipt["status"], "review_required")
        self.assertEqual(receipt["observation_results"][-1]["status"], "draw_mismatch")


if __name__ == "__main__":
    unittest.main()
