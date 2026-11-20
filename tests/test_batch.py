from contextlib import contextmanager
import hashlib
import tempfile
import unittest
from pathlib import Path

from lottery.batch import BatchPublicationError, ThreeSlotBatchPublisher
from lottery.storage import FileSystemObjectStore
from lottery.subset_model.lifecycle import LifecycleError


def sha(label):
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


class FakeLifecycle:
    def __init__(self, *, change_generation=False, fail=False, mixed_family=False):
        self.calls = 0
        self.change_generation = change_generation
        self.fail = fail
        self.mixed_family = mixed_family
        self.snapshot = {
            "registry_generation": 7,
            "champion_generation": 7,
            "slots": [
                {
                    "population_key": f"regime-a|reported_set_index={index}",
                    "zone": zone,
                    "artifact_id": "sha256:" + sha(f"{index}-{zone}"),
                    "artifact_sha256": sha(f"{index}-{zone}"),
                    "model_family": "complete_subset_exponential",
                    "artifact_schema": "lottery.subset-probability-model/v1",
                    "feature_schema_hash": sha("shared-feature-schema"),
                    "population_size": 35 if zone == "front" else 12,
                    "selection_size": 5 if zone == "front" else 2,
                    "training_cutoff_draw_id": "26130",
                    "approval_sha256": sha(f"approval-{index}-{zone}"),
                }
                for index in (1, 2, 3)
                for zone in ("front", "back")
            ],
        }
        if self.mixed_family:
            self.snapshot["slots"][0]["model_family"] = "incompatible_model_family"

    def resolve_three_slot_generation(self, population_keys, *, approval_verifier):
        self.calls += 1
        if self.fail or approval_verifier is None:
            raise LifecycleError("verified Champion registry unavailable")
        result = dict(self.snapshot)
        if self.change_generation and self.calls > 1:
            result["registry_generation"] = 8
            result["champion_generation"] = 8
        return result


    @contextmanager
    def generation_guard(self, expected_generation):
        if self.snapshot["registry_generation"] != expected_generation:
            raise LifecycleError("Champion registry generation changed before dependent publication")
        yield self.snapshot


class ThreeSlotBatchPublisherTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = FileSystemObjectStore(Path(self.temp.name) / "store")
        self.publisher = ThreeSlotBatchPublisher(self.store)
        self.lifecycle = FakeLifecycle()
        self.population_keys = [
            "regime-a|reported_set_index=1",
            "regime-a|reported_set_index=2",
            "regime-a|reported_set_index=3",
        ]

    def tearDown(self):
        self.temp.cleanup()

    def publish(self, *, key="batch-001", n=2, sampler=None, generation=0, lifecycle=None):
        if sampler is None:
            sampler = lambda population, front, back, count: [
                {"front": [1, 2, 3, 4, 5], "back": [1, 2]}
                for _ in range(count)
            ]
        return self.publisher.publish(
            lifecycle=lifecycle or self.lifecycle,
            population_keys=self.population_keys,
            approval_verifier=lambda approval, expected: True,
            tickets_per_slot=n,
            idempotency_key=key,
            seed_commitment_sha256=sha("seed-commitment"),
            rng_algorithm="hmac-sha256-counter-v1",
            sampler_version="exact-subset-sampler/v1",
            producer_commit="a" * 40,
            producer_runtime="CPython 3.12",
            pointer_name="published-batch",
            expected_pointer_generation=generation,
            sampler=sampler,
            actor="test-suite",
        )

    def test_publishes_exact_3n_atomically_and_retains_duplicate_tickets(self):
        result = self.publish(n=2)
        manifest = result["manifest"]
        self.assertEqual(result["ticket_count"], 6)
        self.assertEqual(manifest["slot_count"], 3)
        self.assertEqual(manifest["total_ticket_count"], 6)
        self.assertEqual([len(slot["tickets"]) for slot in manifest["slots"]], [2, 2, 2])
        self.assertEqual(manifest["duplicate_ticket_count"], 5)
        self.assertEqual(manifest["within_slot_duplicate_ticket_count"], 3)
        self.assertEqual(manifest["cross_slot_duplicate_ticket_count"], 2)
        self.assertEqual(self.store.read_pointer("published-batch"), result["pointer"])
        self.assertEqual(self.lifecycle.calls, 2)

    def test_sampler_failure_publishes_nothing(self):
        calls = {"count": 0}

        def fail_second(population, front, back, count):
            calls["count"] += 1
            if calls["count"] == 2:
                raise RuntimeError("sampler failed")
            return [{"front": [1, 2, 3, 4, 5], "back": [1, 2]}] * count

        with self.assertRaisesRegex(BatchPublicationError, "sampler failed"):
            self.publish(sampler=fail_second)
        self.assertFalse(self.store.pointers.exists())
        self.assertFalse(self.store.operations.exists())

    def test_invalid_ticket_is_rejected_before_any_storage_write(self):
        def invalid(population, front, back, count):
            return [{"front": [1, 1, 2, 3, 4], "back": [1, 2]}] * count

        with self.assertRaisesRegex(BatchPublicationError, "front ticket"):
            self.publish(sampler=invalid)
        self.assertFalse(self.store.operations.exists())
        self.assertFalse(self.store.pointers.exists())

    def test_registry_generation_change_during_sampling_blocks_publication(self):
        lifecycle = FakeLifecycle(change_generation=True)
        with self.assertRaisesRegex(BatchPublicationError, "registry changed"):
            self.publish(lifecycle=lifecycle)
        self.assertFalse(self.store.operations.exists())
        self.assertFalse(self.store.pointers.exists())

    def test_mixed_model_families_within_a_zone_are_rejected(self):
        lifecycle = FakeLifecycle(mixed_family=True)
        with self.assertRaisesRegex(BatchPublicationError, "compatible model/schema contract"):
            self.publish(lifecycle=lifecycle)
        self.assertFalse(self.store.operations.exists())
        self.assertFalse(self.store.pointers.exists())

    def test_missing_verified_registry_blocks_batch(self):
        lifecycle = FakeLifecycle(fail=True)
        with self.assertRaisesRegex(BatchPublicationError, "verified three-slot"):
            self.publish(lifecycle=lifecycle)
        self.assertFalse(self.store.operations.exists())

    def test_sampler_must_return_exactly_n_tickets(self):
        with self.assertRaisesRegex(BatchPublicationError, "expected exactly"):
            self.publish(sampler=lambda population, front, back, count: [])

    def test_stale_pointer_cas_does_not_replace_prior_batch(self):
        first = self.publish(key="batch-first")
        with self.assertRaisesRegex(BatchPublicationError, "pointer generation"):
            self.publish(key="batch-second", generation=0)
        self.assertEqual(self.store.read_pointer("published-batch"), first["pointer"])


    def test_registry_change_after_object_commit_blocks_pointer_publication(self):
        lifecycle = FakeLifecycle()
        original_commit = self.store.commit

        def commit_then_change_registry(*, operation_id):
            result = original_commit(operation_id=operation_id)
            lifecycle.snapshot["registry_generation"] = 8
            return result

        self.store.commit = commit_then_change_registry
        with self.assertRaisesRegex(BatchPublicationError, "before batch pointer publication"):
            self.publish(lifecycle=lifecycle)
        self.assertFalse(self.store.pointers.exists())
        # The immutable object may be orphaned for reconciliation, but no
        # visible batch pointer can refer to a stale Champion generation.
        self.assertTrue(self.store.operations.exists())


if __name__ == "__main__":
    unittest.main()
