import json
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import tempfile
import unittest

from lottery.forecast import (
    ForecastLedgerError,
    append_forecast,
    create_forecast_event,
    verify_ledger,
)


def make_draw(index):
    return {
        "draw_id": f"26{index:03d}",
        "draw_date": f"2026-01-{index:02d}",
        "front_numbers": [1, 2, 3, 4, 5],
        "back_numbers": [1, 2],
        "source_id": "test",
    }


class ForecastLedgerTests(unittest.TestCase):
    def setUp(self):
        self.rows = [make_draw(i) for i in range(1, 4)]
        self.now = datetime(2026, 2, 1, 10, 0, tzinfo=timezone.utc)
        self.kwargs = {
            "target_draw_id": "26004",
            "target_draw_at": "2026-02-02T20:00:00+08:00",
            "training_sha256": hashlib.sha256(b"training").hexdigest(),
            "code_commit": "a" * 40,
            "generated_at": self.now,
        }

    def test_forecast_contains_fixed_models_and_valid_probability_mass(self):
        event = create_forecast_event(self.rows, **self.kwargs)
        self.assertEqual(set(event["models"]), {"uniform", "expanding", "ewma"})
        for model in event["models"].values():
            self.assertAlmostEqual(sum(model["front_inclusion_probabilities"]), 5)
            self.assertAlmostEqual(sum(model["back_inclusion_probabilities"]), 2)
        self.assertEqual(event["training_draw_count"], 3)
        self.assertEqual(event["training_last_draw_id"], "26003")

    def test_target_must_be_strictly_in_future(self):
        kwargs = dict(self.kwargs, target_draw_at="2026-02-01T10:00:00+00:00")
        with self.assertRaisesRegex(ForecastLedgerError, "strictly in the future"):
            create_forecast_event(self.rows, **kwargs)

    def test_target_date_must_follow_training_data(self):
        kwargs = dict(self.kwargs, target_draw_at="2026-01-03T20:00:00+08:00", generated_at=datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc))
        with self.assertRaisesRegex(ForecastLedgerError, "later than every training"):
            create_forecast_event(self.rows, **kwargs)

    def test_target_timestamp_requires_timezone(self):
        kwargs = dict(self.kwargs, target_draw_at="2026-02-02T20:00:00")
        with self.assertRaisesRegex(ForecastLedgerError, "include a timezone"):
            create_forecast_event(self.rows, **kwargs)

    def test_commit_and_dataset_hash_are_validated(self):
        kwargs = dict(self.kwargs, code_commit="main")
        with self.assertRaisesRegex(ForecastLedgerError, "full 40-character"):
            create_forecast_event(self.rows, **kwargs)
        kwargs = dict(self.kwargs, training_sha256="bad")
        with self.assertRaisesRegex(ForecastLedgerError, "SHA-256"):
            create_forecast_event(self.rows, **kwargs)

    def test_append_and_verify_hash_chain(self):
        with tempfile.TemporaryDirectory() as temp:
            ledger = Path(temp) / "forecast.jsonl"
            first = create_forecast_event(self.rows, **self.kwargs)
            first_result = append_forecast(ledger, first)
            self.assertEqual(first_result["sequence"], 1)
            state = verify_ledger(ledger)
            self.assertEqual(state["events"], 1)
            self.assertEqual(state["last_event_hash"], first_result["event_hash"])

            second_kwargs = dict(
                self.kwargs,
                target_draw_id="26005",
                target_draw_at="2026-02-03T20:00:00+08:00",
                generated_at=datetime(2026, 2, 2, 10, 0, tzinfo=timezone.utc),
            )
            second = create_forecast_event(self.rows, **second_kwargs)
            self.assertEqual(append_forecast(ledger, second)["sequence"], 2)
            self.assertEqual(verify_ledger(ledger)["events"], 2)

    def test_duplicate_target_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            ledger = Path(temp) / "forecast.jsonl"
            event = create_forecast_event(self.rows, **self.kwargs)
            append_forecast(ledger, event)
            with self.assertRaisesRegex(ForecastLedgerError, "already exists"):
                append_forecast(ledger, event)

    def test_tampering_is_detected(self):
        with tempfile.TemporaryDirectory() as temp:
            ledger = Path(temp) / "forecast.jsonl"
            event = create_forecast_event(self.rows, **self.kwargs)
            append_forecast(ledger, event)
            data = json.loads(ledger.read_text(encoding="utf-8"))
            data["models"]["uniform"]["front_inclusion_probabilities"][0] += 0.01
            ledger.write_text(json.dumps(data) + "\\n", encoding="utf-8")
            with self.assertRaisesRegex(ForecastLedgerError, "hash mismatch"):
                verify_ledger(ledger)


if __name__ == "__main__":
    unittest.main()
