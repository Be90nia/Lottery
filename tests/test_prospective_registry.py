from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import unittest

from lottery.prospective_registry import (
    INVENTORY_SCHEMA,
    TARGET_SCHEMA,
    RegistryScheduleError,
    build_registry_schedule,
    assert_registry_unchanged,
)
from lottery.subset_model.artifact import canonicalize


def digest(value):
    return hashlib.sha256(canonicalize(value)).hexdigest()


def sealed(value, field):
    value[field] = "sha256:" + digest({k: v for k, v in value.items() if k != field})
    return value


def artifact(zone, cutoff="26130"):
    return {
        "zone": zone,
        "model_family": "complete_subset_exponential",
        "population_size": 35 if zone == "front" else 12,
        "selection_size": 5 if zone == "front" else 2,
        "model_configuration": {"solver": "L-BFGS-B", "lambda": 1.0},
        "model_configuration_hash": "sha256:" + "1" * 64,
        "feature_schema_hash": "sha256:" + "2" * 64,
        "training": {
            "first_draw_id": "09054", "last_draw_id": cutoff,
            "snapshot_sha256": "3" * 64, "row_count": 300,
        },
        "training_snapshot_sha256": "3" * 64,
        "training_cutoff_draw_id": cutoff,
        "training_row_count": 300,
    }


class FakeLifecycle:
    def __init__(self, slots=None, mutate_after_first=False):
        self.registry = {
            "schema_version": "lottery.champion-registry/v1",
            "generation": 9,
            "slots": slots or {},
            "last_operation_id": "operation-9",
        }
        self.artifacts = {}
        self.mutate_after_first = mutate_after_first
        self.reads = 0

    def snapshot(self):
        self.reads += 1
        value = self.registry
        if self.mutate_after_first and self.reads == 2:
            value = {**self.registry, "generation": 10}
        return value

    def _load_artifact(self, artifact_id):
        return self.artifacts[artifact_id]


def fixture():
    pop = "pooled-equipment-blind"
    slots = {}
    artifacts = {}
    for zone in ("front", "back"):
        champion_id = "sha256:" + (("a" if zone == "front" else "b") * 64)
        candidate_id = "sha256:" + (("c" if zone == "front" else "d") * 64)
        artifacts[champion_id] = artifact(zone)
        artifacts[candidate_id] = artifact(zone)
        slots[f"{pop}|{zone}"] = {
            "population_key": pop, "zone": zone,
            "champion_artifact_id": champion_id,
            "challenger_artifact_id": candidate_id,
            "shadow_artifact_id": None,
            "validation": {candidate_id: {"eligible": True}},
            "suspended": False,
        }
    lifecycle = FakeLifecycle(slots)
    lifecycle.artifacts = artifacts
    target = sealed({
        "schema": TARGET_SCHEMA,
        "authority": "official_verified",
        "targets": [{
            "target_draw_id": "26131",
            "expected_at_utc": "2026-11-20T14:00:00+00:00",
            "target_cutoff_utc": "2026-11-21T12:00:00+00:00",
            "target_draw_at_utc": "2026-11-21T13:00:00+00:00",
            "target_cutoff_timezone_source": "official_schedule/v1",
        }],
    }, "manifest_id")
    inventory = sealed({
        "schema": INVENTORY_SCHEMA,
        "authority": "official_verified",
        "draw_dates": {
            "09054": "2020-01-01", "26130": "2026-11-20",
            "26131": "2026-11-21",
        },
    }, "inventory_id")
    return lifecycle, target, inventory


class RegistryScheduleTests(unittest.TestCase):
    def build(self, lifecycle, target, inventory, **kw):
        return build_registry_schedule(
            lifecycle, target, inventory,
            now=datetime.fromisoformat("2026-11-20T14:01:00+00:00"),
            code_commit="e" * 40,
            target_manifest_verifier=lambda value: True,
            inventory_verifier=lambda value: True,
            **kw,
        )

    def test_builds_paired_champion_and_shadow_candidate_slots(self):
        lifecycle, target, inventory = fixture()
        schedule = self.build(lifecycle, target, inventory)
        rows = schedule["expected_forecasts"]
        self.assertEqual(len(rows), 4)
        self.assertEqual({r["lifecycle_state"] for r in rows}, {"champion", "shadow"})
        self.assertEqual({r["zone"] for r in rows}, {"front", "back"})
        self.assertEqual({r["registry_generation"] for r in rows}, {9})
        self.assertTrue(all(r["training_last_draw_date"] == "2026-11-20" for r in rows))
        assert_registry_unchanged(lifecycle, schedule, schedule_verifier=lambda value: True)

    def test_missing_front_back_champion_pair_fails_closed(self):
        lifecycle, target, inventory = fixture()
        del lifecycle.registry["slots"]["pooled-equipment-blind|back"]
        with self.assertRaisesRegex(RegistryScheduleError, "complete front/back"):
            self.build(lifecycle, target, inventory)

    def test_ineligible_or_one_sided_candidate_blocks_entire_population(self):
        lifecycle, target, inventory = fixture()
        slot = lifecycle.registry["slots"]["pooled-equipment-blind|back"]
        slot["validation"][slot["challenger_artifact_id"]]["eligible"] = False
        with self.assertRaisesRegex(RegistryScheduleError, "retrospective eligibility"):
            self.build(lifecycle, target, inventory)
        lifecycle, target, inventory = fixture()
        lifecycle.registry["slots"]["pooled-equipment-blind|back"]["challenger_artifact_id"] = None
        with self.assertRaisesRegex(RegistryScheduleError, "incomplete front/back challenger"):
            self.build(lifecycle, target, inventory)

    def test_missing_trust_verifier_or_rejected_evidence_fails_closed(self):
        lifecycle, target, inventory = fixture()
        with self.assertRaisesRegex(RegistryScheduleError, "signing/verifier callbacks are required"):
            build_registry_schedule(
                lifecycle, target, inventory,
                now=datetime.fromisoformat("2026-11-20T14:01:00+00:00"),
                code_commit="e" * 40,
            )
        with self.assertRaisesRegex(RegistryScheduleError, "authority verifier rejected"):
            self.build(lifecycle, target, inventory, target_manifest_verifier=lambda value: False)

    def test_training_crosswalk_missing_and_registry_race_fail_closed(self):
        lifecycle, target, inventory = fixture()
        del inventory["draw_dates"]["26130"]
        inventory = sealed({k: v for k, v in inventory.items() if k != "inventory_id"}, "inventory_id")
        with self.assertRaisesRegex(RegistryScheduleError, "no canonical inventory date"):
            self.build(lifecycle, target, inventory)
        lifecycle, target, inventory = fixture()
        lifecycle.mutate_after_first = True
        with self.assertRaisesRegex(RegistryScheduleError, "changed while schedule"):
            self.build(lifecycle, target, inventory)

    def test_schedule_is_rejected_if_registry_changes_after_build(self):
        lifecycle, target, inventory = fixture()
        schedule = self.build(lifecycle, target, inventory)
        lifecycle.registry = {**lifecycle.registry, "generation": 10}
        with self.assertRaisesRegex(RegistryScheduleError, "changed after schedule"):
            assert_registry_unchanged(lifecycle, schedule, schedule_verifier=lambda value: True)

    def test_target_calendar_cannot_be_guessed_or_backdated(self):
        lifecycle, target, inventory = fixture()
        target["targets"][0]["target_cutoff_utc"] = "2026-11-20T14:00:00+00:00"
        target = sealed({k: v for k, v in target.items() if k != "manifest_id"}, "manifest_id")
        with self.assertRaisesRegex(RegistryScheduleError, "generated/expected < cutoff"):
            self.build(lifecycle, target, inventory)


if __name__ == "__main__":
    unittest.main()
