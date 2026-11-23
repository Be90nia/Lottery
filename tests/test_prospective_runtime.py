from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import tempfile
import unittest

from lottery.prospective import ProspectiveLedger
from lottery.prospective_runtime import issue_registered_forecast
from test_prospective_registry import fixture


class Clock:
    def __init__(self, value):
        self.value = datetime.fromisoformat(value)

    def __call__(self):
        return self.value


class DistributionDigests:
    def distribution_sha256(self, artifact_id):
        return hashlib.sha256(artifact_id.encode()).hexdigest()


class ProspectiveRuntimeTests(unittest.TestCase):
    def test_registered_champion_and_shadow_slots_issue_immutable_forecasts(self):
        lifecycle, target, inventory = fixture()
        schedule = __import__("lottery.prospective_registry", fromlist=["build_registry_schedule"]).build_registry_schedule(
            lifecycle, target, inventory,
            now=datetime.fromisoformat("2026-11-20T14:01:00+00:00"),
            code_commit="e" * 40,
            target_manifest_verifier=lambda value: True,
            inventory_verifier=lambda value: True,
        )
        clock = Clock("2026-11-20T14:02:00+00:00")
        with tempfile.TemporaryDirectory() as directory:
            ledger = ProspectiveLedger(f"{directory}/ledger.jsonl", clock=clock)
            issued = []
            for record in schedule["expected_forecasts"]:
                ledger.register_expected_forecast(**record)
                issued.append(issue_registered_forecast(
                    lifecycle, ledger, schedule, record,
                    now=clock(), evaluator=DistributionDigests(), schedule_verifier=lambda value: True,
                ))
            self.assertEqual(len(issued), 4)
            self.assertEqual({item["status"] for item in issued}, {"eligible"})
            self.assertEqual({item["lifecycle_state"] for item in issued}, {"champion", "shadow"})
            self.assertEqual(ledger.coverage_report()["forecast_records"], 4)

    def test_forecast_after_cutoff_cannot_be_issued_even_if_schedule_exists(self):
        lifecycle, target, inventory = fixture()
        from lottery.prospective_registry import build_registry_schedule
        schedule = build_registry_schedule(
            lifecycle, target, inventory,
            now=datetime.fromisoformat("2026-11-20T14:01:00+00:00"),
            code_commit="e" * 40,
            target_manifest_verifier=lambda value: True,
            inventory_verifier=lambda value: True,
        )
        record = schedule["expected_forecasts"][0]
        with tempfile.TemporaryDirectory() as directory:
            clock = Clock("2026-11-21T12:01:00+00:00")
            ledger = ProspectiveLedger(f"{directory}/ledger.jsonl", clock=clock)
            # It cannot even register an expectation once the actual cutoff has passed.
            with self.assertRaisesRegex(Exception, "recorded after its cutoff"):
                ledger.register_expected_forecast(**record)


if __name__ == "__main__":
    unittest.main()
