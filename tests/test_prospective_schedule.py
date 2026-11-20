from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import tempfile
import unittest
from pathlib import Path

from lottery.prospective import ProspectiveLedger
from lottery.prospective_schedule import (
    ScheduleError,
    run_schedule,
    validate_schedule,
)
from lottery.subset_model.artifact import canonicalize


def sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


class Clock:
    def __init__(self, value: str):
        self.value = datetime.fromisoformat(value.replace("Z", "+00:00"))

    def __call__(self):
        return self.value


def make_record():
    return {
        "target_draw_id": "26132",
        "target_draw_at_utc": "2026-11-21T13:00:00+00:00",
        "target_cutoff_utc": "2026-11-21T12:00:00+00:00",
        "target_cutoff_timezone_source": "official_schedule/v1",
        "expected_at_utc": "2026-11-20T14:00:00+00:00",
        "zone": "front",
        "population_key": "pooled-equipment-blind",
        "front_artifact_sha256": sha("front-artifact"),
        "back_artifact_sha256": sha("back-artifact"),
        "active_registry_snapshot_id": sha("registry"),
        "lifecycle_state": "champion",
        "model_spec_sha256": sha("model-spec"),
        "training_snapshot_sha256": sha("training"),
        "training_first_draw_id": "09054",
        "training_last_draw_id": "26131",
        "training_row_count": 2948,
        "training_last_draw_date": "2026-11-20",
        "registry_generation": 7,
        "forecast_policy_version": "prospective-v1",
        "scoring_policy_version": "exact-set-nll/v1",
        "model_family": "complete_subset_exponential",
        "code_commit": "a" * 40,
        "runtime": "CPython 3.12",
    }


def make_schedule(records=None):
    body = {
        "schema": "lottery.prospective-schedule/v1",
        "lot042_accessed": False,
        "generated_at_utc": "2026-11-20T14:01:00+00:00",
        "expected_forecasts": records if records is not None else [make_record()],
    }
    body["schedule_id"] = "sha256:" + hashlib.sha256(canonicalize(body)).hexdigest()
    return body


class ProspectiveScheduleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "prospective.jsonl"
        self.clock = Clock("2026-11-20T14:02:00+00:00")
        self.ledger = ProspectiveLedger(self.path, clock=self.clock)
        self.schedule = make_schedule()

    def test_register_is_idempotent_and_binds_schedule_hash(self):
        first = run_schedule(self.schedule, self.ledger, mode="register", clock=self.clock)
        second = run_schedule(self.schedule, self.ledger, mode="register", clock=self.clock)
        self.assertEqual(first["status"], "complete")
        self.assertEqual(first["completed_count"], 1)
        self.assertEqual(second["completed_count"], 1)
        self.assertEqual(self.ledger.snapshot()["event_count"], 1)
        self.assertEqual(first["schedule_id"], self.schedule["schedule_id"])

    def test_finalize_creates_missing_record_only_after_cutoff(self):
        run_schedule(self.schedule, self.ledger, mode="register", clock=self.clock)
        self.clock.value = datetime.fromisoformat("2026-11-21T11:59:00+00:00")
        early = run_schedule(self.schedule, self.ledger, mode="finalize", clock=self.clock)
        self.assertEqual(early["status"], "partial_or_failed")
        self.assertEqual(early["failure_count"], 1)
        self.clock.value = datetime.fromisoformat("2026-11-21T12:01:00+00:00")
        final = run_schedule(self.schedule, self.ledger, mode="finalize", clock=self.clock)
        self.assertEqual(final["status"], "complete")
        self.assertEqual(final["completed_count"], 1)
        self.assertEqual(self.ledger.coverage_report()["forecast_missing_at_cutoff"], 1)
        retry = run_schedule(self.schedule, self.ledger, mode="finalize", clock=self.clock)
        self.assertEqual(retry["skipped_count"], 1)
        self.assertEqual(self.ledger.snapshot()["event_count"], 2)

    def test_bad_schedule_digest_and_duplicate_slot_fail_before_write(self):
        bad = dict(self.schedule)
        bad["expected_forecasts"] = [dict(make_record(), training_row_count=299)]
        with self.assertRaisesRegex(ScheduleError, "schedule_id"):
            validate_schedule(bad)
        duplicate = make_schedule([make_record(), make_record()])
        with self.assertRaisesRegex(ScheduleError, "duplicate expected forecast slot"):
            validate_schedule(duplicate)
        self.assertEqual(self.ledger.snapshot()["event_count"], 0)

    def test_schedule_must_explicitly_preserve_lot042_firewall(self):
        schedule = dict(self.schedule, lot042_accessed=True)
        schedule["schedule_id"] = "sha256:" + hashlib.sha256(
            canonicalize({k: v for k, v in schedule.items() if k != "schedule_id"})
        ).hexdigest()
        with self.assertRaisesRegex(ScheduleError, "LOT-042"):
            validate_schedule(schedule)
        self.assertEqual(self.ledger.snapshot()["event_count"], 0)

    def test_generated_after_cutoff_is_rejected(self):
        record = make_record()
        record["target_cutoff_utc"] = "2026-11-20T14:00:00+00:00"
        record["expected_at_utc"] = "2026-11-20T13:00:00+00:00"
        record["target_draw_at_utc"] = "2026-11-20T15:00:00+00:00"
        schedule = make_schedule([record])
        schedule["generated_at_utc"] = "2026-11-20T14:01:00+00:00"
        schedule["schedule_id"] = "sha256:" + hashlib.sha256(
            canonicalize({k: v for k, v in schedule.items() if k != "schedule_id"})
        ).hexdigest()
        with self.assertRaisesRegex(ScheduleError, "generated at/after"):
            validate_schedule(schedule)

    def test_schedule_preflight_prevents_partial_registration_on_invalid_entry(self):
        good = make_record()
        bad = dict(make_record(), target_draw_id="26133", expected_at_utc="2026-11-21T12:30:00+00:00")
        schedule = make_schedule([good, bad])
        with self.assertRaisesRegex(ScheduleError, "expectation < cutoff"):
            run_schedule(schedule, self.ledger, mode="register", clock=self.clock)
        self.assertEqual(self.ledger.snapshot()["event_count"], 0)


if __name__ == "__main__":
    unittest.main()
