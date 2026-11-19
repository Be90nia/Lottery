import hashlib
import json
import multiprocessing
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest

from lottery.forecast import append_forecast, create_forecast_event, _event_hash
from lottery.outcomes import (
    OutcomeLedgerError, append_outcome, create_outcome_event,
    create_outcome_event_from_snapshot, main, score_ledgers, verify_outcome_ledger,
)


def draw(index):
    return {"draw_id": f"260{index}", "draw_date": f"2026-01-0{index}",
            "front_numbers": [1, 2, 3, 4, 5], "back_numbers": [1, 2],
            "source_id": "test"}



def _append_outcome_worker(path, event, barrier, results):
    try:
        barrier.wait(timeout=15)
        append_outcome(Path(path), event)
        results.put("ok")
    except Exception as exc:
        results.put(type(exc).__name__ + ":" + str(exc))


class OutcomeLedgerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.forecasts = root / "forecasts.jsonl"
        self.outcomes = root / "outcomes.jsonl"
        rows = [draw(1), draw(2), draw(3)]
        forecast = create_forecast_event(
            rows, target_draw_id="2604", target_draw_at="2026-02-02T20:00:00+08:00",
            training_sha256=hashlib.sha256(b"training").hexdigest(),
            code_commit="a" * 40,
            generated_at=datetime(2026, 2, 1, 10, 0, tzinfo=timezone.utc),
        )
        append_forecast(self.forecasts, forecast)
        self.kwargs = {
            "target_draw_id": "2604",
            "draw_date": "2026-02-02",
            "published_at": "2026-02-02T20:30:00+08:00",
            "captured_at": "2026-02-02T20:31:00+08:00",
            "source_url": "https://webapi.sporttery.cn/gateway/lottery/getHistoryPageListV1.qry?gameNo=85",
            "source_sha256": hashlib.sha256(b"raw official response").hexdigest(),
            "http_status": 200,
            "front_numbers": [2, 8, 12, 19, 31],
            "back_numbers": [3, 9],
            "recorded_at": datetime(2026, 2, 2, 13, 0, tzinfo=timezone.utc),
        }

    def tearDown(self):
        self.temp.cleanup()

    def test_record_verify_and_score(self):
        event = create_outcome_event(self.forecasts, **self.kwargs)
        result = append_outcome(self.outcomes, event)
        self.assertEqual(result["sequence"], 1)
        self.assertEqual(verify_outcome_ledger(self.outcomes)["events"], 1)
        report = score_ledgers(self.forecasts, self.outcomes)
        self.assertEqual(report["scored_draws"], 1)
        self.assertEqual(set(report["scores"][0]["models"]), {"uniform", "expanding", "ewma"})
        self.assertIn("brier_per_number", report["scores"][0]["models"]["uniform"]["front"])
        self.assertAlmostEqual(
            report["scores"][0]["models"]["uniform"]["front"]["brier_per_number"],
            6 / 49, places=12,
        )
        self.assertAlmostEqual(
            report["scores"][0]["models"]["uniform"]["back"]["brier_per_number"],
            5 / 36, places=12,
        )

    def test_rejects_outcome_draw_date_mismatch(self):
        kwargs = dict(self.kwargs, draw_date="2026-02-03")
        with self.assertRaisesRegex(OutcomeLedgerError, "does not match forecast target draw date"):
            create_outcome_event(self.forecasts, **kwargs)

    def test_score_rejects_correctly_hashed_outcome_with_wrong_draw_date(self):
        event = create_outcome_event(self.forecasts, **self.kwargs)
        append_outcome(self.outcomes, event)
        record = json.loads(self.outcomes.read_text(encoding="utf-8"))
        body = {key: value for key, value in record.items() if key != "event_hash"}
        body["draw_date"] = "2026-02-03"
        record = {**body, "event_hash": _event_hash(body)}
        self.outcomes.write_text(json.dumps(record) + "\n", encoding="utf-8")
        with self.assertRaisesRegex(OutcomeLedgerError, "draw date does not match"):
            score_ledgers(self.forecasts, self.outcomes)

    def test_rejects_publication_before_draw(self):
        kwargs = dict(self.kwargs, published_at="2026-02-02T19:59:00+08:00")
        with self.assertRaisesRegex(OutcomeLedgerError, "precedes target"):
            create_outcome_event(self.forecasts, **kwargs)

    def test_rejects_capture_before_publication(self):
        kwargs = dict(self.kwargs, captured_at="2026-02-02T20:29:00+08:00")
        with self.assertRaisesRegex(OutcomeLedgerError, "precedes publication"):
            create_outcome_event(self.forecasts, **kwargs)

    def test_rejects_non_official_source(self):
        kwargs = dict(self.kwargs, source_url="https://sporttery-cn.example/result")
        with self.assertRaisesRegex(OutcomeLedgerError, "exact HTTPS Sporttery history endpoint"):
            create_outcome_event(self.forecasts, **kwargs)

    def test_rejects_lookalike_official_subdomain(self):
        kwargs = dict(
            self.kwargs,
            source_url="https://attacker.sporttery.cn/gateway/lottery/getHistoryPageListV1.qry?gameNo=85",
        )
        with self.assertRaisesRegex(OutcomeLedgerError, "exact HTTPS Sporttery history endpoint"):
            create_outcome_event(self.forecasts, **kwargs)

    def test_rejects_wrong_path_on_official_host(self):
        kwargs = dict(
            self.kwargs,
            source_url="https://webapi.sporttery.cn/gateway/lottery/result?gameNo=85",
        )
        with self.assertRaisesRegex(OutcomeLedgerError, "exact HTTPS Sporttery history endpoint"):
            create_outcome_event(self.forecasts, **kwargs)

    def test_rejects_non_https_or_non_200(self):
        kwargs = dict(self.kwargs, source_url="http://webapi.sporttery.cn/result")
        with self.assertRaisesRegex(OutcomeLedgerError, "HTTPS"):
            create_outcome_event(self.forecasts, **kwargs)
        kwargs = dict(self.kwargs, http_status=206)
        with self.assertRaisesRegex(OutcomeLedgerError, "HTTP status"):
            create_outcome_event(self.forecasts, **kwargs)

    def test_rejects_invalid_numbers(self):
        kwargs = dict(self.kwargs, front_numbers=[1, 1, 2, 3, 4])
        with self.assertRaisesRegex(OutcomeLedgerError, "distinct integers"):
            create_outcome_event(self.forecasts, **kwargs)

    def test_rejects_unknown_target(self):
        kwargs = dict(self.kwargs, target_draw_id="unknown")
        with self.assertRaisesRegex(OutcomeLedgerError, "no pre-draw forecast"):
            create_outcome_event(self.forecasts, **kwargs)

    def test_duplicate_outcome_rejected(self):
        event = create_outcome_event(self.forecasts, **self.kwargs)
        append_outcome(self.outcomes, event)
        with self.assertRaisesRegex(OutcomeLedgerError, "already exists"):
            append_outcome(self.outcomes, event)

    def test_tampering_detected(self):
        event = create_outcome_event(self.forecasts, **self.kwargs)
        append_outcome(self.outcomes, event)
        record = json.loads(self.outcomes.read_text(encoding="utf-8"))
        record["front_numbers"][0] = 35
        self.outcomes.write_text(json.dumps(record) + "\n", encoding="utf-8")
        with self.assertRaisesRegex(OutcomeLedgerError, "hash mismatch"):
            verify_outcome_ledger(self.outcomes)


    def test_scoring_rejects_outcome_linked_to_wrong_forecast_hash(self):
        event = create_outcome_event(self.forecasts, **self.kwargs)
        append_outcome(self.outcomes, event)
        record = json.loads(self.outcomes.read_text(encoding="utf-8"))
        body = {key: value for key, value in record.items() if key != "event_hash"}
        body["forecast_event_hash"] = "f" * 64
        record = {**body, "event_hash": _event_hash(body)}
        self.outcomes.write_text(json.dumps(record) + "\n", encoding="utf-8")
        with self.assertRaisesRegex(OutcomeLedgerError, "does not link"):
            score_ledgers(self.forecasts, self.outcomes)

    def test_verifier_rejects_forged_outcome_metadata_even_with_valid_chain(self):
        event = create_outcome_event(self.forecasts, **self.kwargs)
        append_outcome(self.outcomes, event)
        record = json.loads(self.outcomes.read_text(encoding="utf-8"))
        body = {key: value for key, value in record.items() if key != "event_hash"}
        body["source_snapshot_sha256"] = "bad"
        record = {**body, "event_hash": _event_hash(body)}
        self.outcomes.write_text(json.dumps(record) + "\n", encoding="utf-8")
        with self.assertRaisesRegex(OutcomeLedgerError, "SHA-256"):
            verify_outcome_ledger(self.outcomes)

    def test_forecast_probability_mass_is_rechecked_before_outcome(self):
        record = json.loads(self.forecasts.read_text(encoding="utf-8"))
        body = {key: value for key, value in record.items() if key != "event_hash"}
        body["models"]["uniform"]["front_inclusion_probabilities"][0] += 0.01
        record = {**body, "event_hash": _event_hash(body)}
        self.forecasts.write_text(json.dumps(record) + "\n", encoding="utf-8")
        with self.assertRaisesRegex(OutcomeLedgerError, "invalid uniform front"):
            create_outcome_event(self.forecasts, **self.kwargs)



    def test_concurrent_duplicate_outcome_has_exactly_one_winner(self):
        event = create_outcome_event(self.forecasts, **self.kwargs)
        ctx = multiprocessing.get_context("spawn")
        barrier, results = ctx.Barrier(2), ctx.Queue()
        processes = [
            ctx.Process(target=_append_outcome_worker, args=(str(self.outcomes), event, barrier, results))
            for _ in range(2)
        ]
        for process in processes:
            process.start()
        outcomes = [results.get(timeout=20) for _ in processes]
        for process in processes:
            process.join(timeout=20)
            self.assertEqual(process.exitcode, 0)
        self.assertEqual(outcomes.count("ok"), 1, outcomes)
        self.assertEqual(sum("already exists" in value for value in outcomes), 1, outcomes)
        self.assertEqual(verify_outcome_ledger(self.outcomes)["events"], 1)

    def test_concurrent_distinct_outcomes_keep_chain_contiguous(self):
        second_forecast = create_forecast_event(
            [draw(1), draw(2), draw(3)],
            target_draw_id="2605",
            target_draw_at="2026-02-03T20:00:00+08:00",
            training_sha256=hashlib.sha256(b"training-2").hexdigest(),
            code_commit="b" * 40,
            generated_at=datetime(2026, 2, 2, 10, 0, tzinfo=timezone.utc),
        )
        append_forecast(self.forecasts, second_forecast)
        first_event = create_outcome_event(self.forecasts, **self.kwargs)
        second_kwargs = dict(
            self.kwargs,
            target_draw_id="2605",
            published_at="2026-02-03T20:30:00+08:00",
            captured_at="2026-02-03T20:31:00+08:00",
            recorded_at=datetime(2026, 2, 3, 13, 0, tzinfo=timezone.utc),
        )
        second_event = create_outcome_event(self.forecasts, **second_kwargs)
        ctx = multiprocessing.get_context("spawn")
        barrier, results = ctx.Barrier(2), ctx.Queue()
        processes = [
            ctx.Process(target=_append_outcome_worker, args=(str(self.outcomes), event, barrier, results))
            for event in (first_event, second_event)
        ]
        for process in processes:
            process.start()
        outcomes = [results.get(timeout=20) for _ in processes]
        for process in processes:
            process.join(timeout=20)
            self.assertEqual(process.exitcode, 0)
        self.assertEqual(outcomes.count("ok"), 2, outcomes)
        self.assertEqual(verify_outcome_ledger(self.outcomes)["events"], 2)





class OutcomeSnapshotBindingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.forecasts = self.root / "forecasts.jsonl"
        append_forecast(self.forecasts, create_forecast_event(
            [draw(1), draw(2), draw(3)],
            target_draw_id="2604",
            target_draw_at="2026-02-02T20:00:00+08:00",
            training_sha256=hashlib.sha256(b"training").hexdigest(),
            code_commit="c" * 40,
            generated_at=datetime(2026, 2, 1, 10, 0, tzinfo=timezone.utc),
        ))
        row = {
            "lotteryDrawNum": "2604",
            "lotteryDrawTime": "2026-02-02",
            "lotteryDrawResult": "02 08 12 19 31 03 09",
        }
        self.snapshot = self.root / "page.json"
        self.snapshot.write_text(json.dumps({"success": True, "value": {"list": [row]}}), encoding="utf-8")
        self.kwargs = {
            "target_draw_id": "2604",
            "published_at": "2026-02-02T20:30:00+08:00",
            "captured_at": "2026-02-02T20:31:00+08:00",
            "source_url": "https://webapi.sporttery.cn/gateway/lottery/getHistoryPageListV1.qry?gameNo=85&pageNo=1",
            "snapshot_path": self.snapshot,
            "http_status": 200,
        }

    def tearDown(self):
        self.temp.cleanup()

    def test_outcome_numbers_are_derived_from_exact_raw_snapshot(self):
        event = create_outcome_event_from_snapshot(self.forecasts, **self.kwargs)
        self.assertEqual(event["front_numbers"], [2, 8, 12, 19, 31])
        self.assertEqual(event["back_numbers"], [3, 9])
        self.assertEqual(event["source_snapshot_sha256"], hashlib.sha256(self.snapshot.read_bytes()).hexdigest())

    def test_snapshot_draw_date_must_match_forecast_target(self):
        payload = json.loads(self.snapshot.read_text(encoding="utf-8"))
        payload["value"]["list"][0]["lotteryDrawTime"] = "2026-02-03"
        self.snapshot.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaisesRegex(OutcomeLedgerError, "does not match forecast target draw date"):
            create_outcome_event_from_snapshot(self.forecasts, **self.kwargs)

    def test_snapshot_must_contain_exactly_one_matching_draw(self):
        kwargs = dict(self.kwargs, target_draw_id="not-in-snapshot")
        with self.assertRaisesRegex(OutcomeLedgerError, "exactly one record"):
            create_outcome_event_from_snapshot(self.forecasts, **kwargs)

    def test_snapshot_source_url_must_identify_dlt_endpoint(self):
        kwargs = dict(self.kwargs, source_url="https://webapi.sporttery.cn/other?gameNo=85")
        with self.assertRaisesRegex(OutcomeLedgerError, "exact HTTPS Sporttery history endpoint"):
            create_outcome_event_from_snapshot(self.forecasts, **kwargs)

    def test_snapshot_source_url_must_bind_game_number(self):
        kwargs = dict(self.kwargs, source_url="https://webapi.sporttery.cn/gateway/lottery/getHistoryPageListV1.qry?gameNo=86")
        with self.assertRaisesRegex(OutcomeLedgerError, "gameNo=85"):
            create_outcome_event_from_snapshot(self.forecasts, **kwargs)

    def test_cli_rejects_manual_numbers_that_disagree_with_snapshot(self):
        outcomes = self.root / "outcomes.jsonl"
        argv = [
            "outcome_ledger.py", "record",
            "--forecasts", str(self.forecasts),
            "--outcomes", str(outcomes),
            "--target-draw-id", "2604",
            "--published-at", "2026-02-02T20:30:00+08:00",
            "--captured-at", "2026-02-02T20:31:00+08:00",
            "--source-url", self.kwargs["source_url"],
            "--snapshot", str(self.snapshot),
            "--http-status", "200",
            "--front", "1,2,3,4,5",
            "--back", "1,2",
        ]
        from unittest.mock import patch
        with patch("sys.argv", argv):
            self.assertEqual(main(), 1)
        self.assertFalse(outcomes.exists())

if __name__ == "__main__":
    unittest.main()
