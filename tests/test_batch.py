from contextlib import contextmanager
import hashlib
import tempfile
import unittest
from pathlib import Path

from lottery.batch import BatchPublicationError, ThreeSlotBatchPublisher
from lottery.storage import FileSystemObjectStore
from lottery.subset_model.artifact import canonicalize
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
                    "training_snapshot_sha256": sha(f"training-{index}"),
                    "training_row_count": 2948,
                    "training_first_draw_id": "07001",
                    "training_last_draw_id": "26130",
                    "population_evidence_sha256": sha(f"population-evidence-{index}"),
                    "evaluation_manifest_sha256": sha(f"evaluation-manifest-{index}-{zone}"),
                    "evaluation_receipt_sha256": sha(f"evaluation-receipt-{index}-{zone}"),
                    "shadow_receipt_sha256": None,
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

    def publish(
        self, *, key="batch-001", n=2, sampler=None, generation=0,
        lifecycle=None, master_seed=None, seed_commitment=None,
    ):
        if master_seed is None:
            master_seed = b"lottery-test-master-seed-material-2026"
        if sampler is None:
            sampler = lambda population, front, back, count, front_seed, back_seed: [
                {"front": [1, 2, 3, 4, 5], "back": [1, 2]}
                for _ in range(count)
            ]
        return self.publisher.publish(
            lifecycle=lifecycle or self.lifecycle,
            population_keys=self.population_keys,
            approval_verifier=lambda approval, expected: True,
            tickets_per_slot=n,
            idempotency_key=key,
            master_seed=master_seed,
            seed_material_ref="secret-store://lottery/test-batch-seed",
            seed_commitment_sha256=seed_commitment or hashlib.sha256(master_seed).hexdigest(),
            rng_algorithm="hmac-sha256-derived/python-mt19937-v1",
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
        self.assertEqual(
            manifest["registry_snapshot_sha256"],
            hashlib.sha256(canonicalize(manifest["registry_snapshot"])).hexdigest(),
        )
        for slot in manifest["slots"]:
            self.assertIn("ticket_id", slot["tickets"][0])
            self.assertEqual(
                slot["front_artifact_provenance"]["training_snapshot_sha256"],
                slot["back_artifact_provenance"]["training_snapshot_sha256"],
            )
            self.assertEqual(
                slot["front_artifact_provenance"]["population_evidence_sha256"],
                slot["back_artifact_provenance"]["population_evidence_sha256"],
            )
        self.assertEqual(self.store.read_pointer("published-batch"), result["pointer"])
        self.assertEqual(self.lifecycle.calls, 2)

    def test_sampler_failure_publishes_nothing(self):
        calls = {"count": 0}

        def fail_second(population, front, back, count, front_seed, back_seed):
            calls["count"] += 1
            if calls["count"] == 2:
                raise RuntimeError("sampler failed")
            return [{"front": [1, 2, 3, 4, 5], "back": [1, 2]}] * count

        with self.assertRaisesRegex(BatchPublicationError, "sampler failed"):
            self.publish(sampler=fail_second)
        self.assertFalse(self.store.pointers.exists())
        self.assertFalse(self.store.operations.exists())

    def test_invalid_ticket_is_rejected_before_any_storage_write(self):
        def invalid(population, front, back, count, front_seed, back_seed):
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
            self.publish(sampler=lambda population, front, back, count, front_seed, back_seed: [])

    def test_batch_size_is_bounded_before_registry_resolution(self):
        with self.assertRaisesRegex(BatchPublicationError, "frozen offline limit of 100"):
            self.publish(n=101)
        self.assertEqual(self.lifecycle.calls, 0)
        self.assertFalse(self.store.operations.exists())

    def test_stale_pointer_cas_does_not_replace_prior_batch(self):
        first = self.publish(key="batch-first")
        with self.assertRaisesRegex(BatchPublicationError, "pointer generation"):
            self.publish(key="batch-second", generation=0)
        self.assertEqual(self.store.read_pointer("published-batch"), first["pointer"])


    def test_seed_commitment_must_match_protected_master_seed(self):
        with self.assertRaisesRegex(BatchPublicationError, "match the supplied master seed"):
            self.publish(seed_commitment=sha("wrong-seed"))

    def test_rng_streams_are_slot_and_zone_specific_and_reproducible(self):
        first = self.publish(key="rng-first", n=1)
        replay = self.publish(key="rng-first", n=1, generation=1)
        different_request = self.publish(key="rng-second", n=1, generation=1)
        first_streams = [
            (slot["rng_streams"]["front"]["stream_id"], slot["rng_streams"]["back"]["stream_id"])
            for slot in first["manifest"]["slots"]
        ]
        replay_streams = [
            (slot["rng_streams"]["front"]["stream_id"], slot["rng_streams"]["back"]["stream_id"])
            for slot in replay["manifest"]["slots"]
        ]
        different_streams = [
            (slot["rng_streams"]["front"]["stream_id"], slot["rng_streams"]["back"]["stream_id"])
            for slot in different_request["manifest"]["slots"]
        ]
        self.assertEqual(first_streams, replay_streams)
        self.assertNotEqual(first_streams, different_streams)
        self.assertEqual(
            [ticket["ticket_id"] for slot in first["manifest"]["slots"] for ticket in slot["tickets"]],
            [ticket["ticket_id"] for slot in replay["manifest"]["slots"] for ticket in slot["tickets"]],
        )
        flattened = [stream for pair in first_streams for stream in pair]
        self.assertEqual(len(flattened), 6)
        self.assertEqual(len(set(flattened)), 6)
        self.assertEqual(
            first["manifest"]["seed_material_ref"],
            "secret-store://lottery/test-batch-seed",
        )
        self.assertEqual(
            first["manifest"]["seed_derivation"],
            "HMAC-SHA256(lottery.three-slot-rng.v1, request_id, population_key, zone, artifact_id, rng_algorithm, sampler_version)",
        )
        self.assertNotIn(
            b"lottery-test-master-seed-material-2026",
            canonicalize(first["manifest"]),
        )


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
