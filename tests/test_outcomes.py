import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest

from lottery.forecast import append_forecast, create_forecast_event, _event_hash
from lottery.outcomes import (
    OutcomeLedgerError, append_outcome, create_outcome_event,
    score_ledgers, verify_outcome_ledger,
)


def draw(index):
    return {"draw_id": f"260{index}", "draw_date": f"2026-01-0{index}",
            "front_numbers": [1, 2, 3, 4, 5], "back_numbers": [1, 2],
            "source_id": "test"}


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
            "published_at": "2026-02-02T20:30:00+08:00",
            "captured_at": "2026-02-02T20:31:00+08:00",
            "source_url": "https://webapi.sporttery.cn/gateway/lottery/result",
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
        with self.assertRaisesRegex(OutcomeLedgerError, "official sporttery.cn"):
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



if __name__ == "__main__":
    unittest.main()
