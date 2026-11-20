import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from lottery import storage as storage_module
from lottery.storage import (
    FileSystemObjectStore,
    IdempotencyConflict,
    StalePointer,
    StorageError,
)


class FileSystemObjectStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = FileSystemObjectStore(Path(self.temp.name) / "store")

    def tearDown(self):
        self.temp.cleanup()

    def stage_validate_commit(self, key="draw-snapshot-v1", content=b"canonical snapshot"):
        staged = self.store.stage(
            idempotency_key=key,
            content=content,
            media_type="application/x-ndjson",
            schema_version="draw-snapshot/v1",
            producer_commit="a" * 40,
            producer_runtime="CPython 3.12",
        )
        self.store.validate(
            operation_id=staged["operation_id"],
            validator=lambda raw: raw.startswith(b"canonical"),
            validator_id="test-canonical-snapshot/v1",
        )
        committed = self.store.commit(operation_id=staged["operation_id"])
        return staged, committed

    def test_idempotent_stage_reuses_identical_inputs_and_rejects_changed_inputs(self):
        first = self.store.stage(
            idempotency_key="same-operation",
            content=b"payload",
            media_type="application/octet-stream",
            schema_version="blob/v1",
            producer_commit="b" * 40,
            producer_runtime="CPython 3.12",
        )
        retry = self.store.stage(
            idempotency_key="same-operation",
            content=b"payload",
            media_type="application/octet-stream",
            schema_version="blob/v1",
            producer_commit="b" * 40,
            producer_runtime="CPython 3.12",
        )
        self.assertEqual(first, retry)
        with self.assertRaises(IdempotencyConflict):
            self.store.stage(
                idempotency_key="same-operation",
                content=b"changed",
                media_type="application/octet-stream",
                schema_version="blob/v1",
                producer_commit="b" * 40,
                producer_runtime="CPython 3.12",
            )

    def test_commit_requires_validation_and_pointer_is_cas_published(self):
        staged = self.store.stage(
            idempotency_key="inventory-1",
            content=b"canonical snapshot",
            media_type="application/x-ndjson",
            schema_version="inventory/v1",
            producer_commit="c" * 40,
            producer_runtime="CPython 3.12",
        )
        with self.assertRaises(StorageError):
            self.store.commit(operation_id=staged["operation_id"])
        self.store.validate(operation_id=staged["operation_id"])
        self.store.commit(operation_id=staged["operation_id"])
        pointer = self.store.publish_pointer(
            name="active-inventory",
            operation_id=staged["operation_id"],
            expected_generation=0,
        )
        self.assertEqual(pointer["generation"], 1)
        self.assertEqual(self.store.read_pointer("active-inventory"), pointer)
        retry = self.store.publish_pointer(
            name="active-inventory",
            operation_id=staged["operation_id"],
            expected_generation=0,
        )
        self.assertEqual(retry, pointer)
        other, _ = self.stage_validate_commit(
            key="inventory-2", content=b"canonical snapshot v2"
        )
        with self.assertRaises(StalePointer):
            self.store.publish_pointer(
                name="active-inventory",
                operation_id=other["operation_id"],
                expected_generation=0,
            )

    def test_semantic_validation_failure_never_creates_commit(self):
        staged = self.store.stage(
            idempotency_key="invalid-object",
            content=b"bad",
            media_type="application/octet-stream",
            schema_version="opaque/v1",
            producer_commit="d" * 40,
            producer_runtime="CPython 3.12",
        )
        with self.assertRaises(StorageError):
            self.store.validate(
                operation_id=staged["operation_id"],
                validator=lambda raw: False,
                validator_id="reject-all/v1",
            )
        with self.assertRaises(StorageError):
            self.store.commit(operation_id=staged["operation_id"])
        self.assertFalse(self.store._commit_path(staged["operation_id"]).exists())

    def test_reconciliation_is_read_only_and_reports_unpublished_stages(self):
        staged, _ = self.stage_validate_commit(key="committed-but-not-published")
        report = self.store.reconcile()
        self.assertTrue(report["read_only"])
        self.assertEqual(report["committed_unreferenced"], [staged["operation_id"]])
        self.assertFalse(self.store.pointers.exists())

    def test_retry_recovers_crash_after_pointer_replace_before_receipt(self):
        staged, _ = self.stage_validate_commit(key="crash-publication")
        real_write_once = storage_module._atomic_immutable

        def fail_publication_receipt(path, raw):
            if path.parent == self.store.publications:
                raise OSError("simulated crash before publication receipt")
            return real_write_once(path, raw)

        with patch("lottery.storage._atomic_immutable", side_effect=fail_publication_receipt):
            with self.assertRaisesRegex(OSError, "simulated crash"):
                self.store.publish_pointer(
                    name="active-inventory",
                    operation_id=staged["operation_id"],
                    expected_generation=0,
                )
        pointer = self.store.read_pointer("active-inventory")
        self.assertEqual(pointer["generation"], 1)
        before_recovery = self.store.reconcile()
        self.assertEqual(
            before_recovery["missing_publication_receipts"],
            [f"active-inventory:{staged['operation_id']}"],
        )
        recovered = self.store.publish_pointer(
            name="active-inventory",
            operation_id=staged["operation_id"],
            expected_generation=0,
        )
        self.assertEqual(recovered, pointer)
        self.assertTrue(
            (self.store.publications / f"active-inventory.{staged['operation_id']}.json").exists()
        )
        self.assertEqual(self.store.reconcile()["missing_publication_receipts"], [])

    def test_reconciliation_detects_corrupt_publication_receipt(self):
        staged, _ = self.stage_validate_commit(key="corrupt-publication-receipt")
        self.store.publish_pointer(
            name="active-model",
            operation_id=staged["operation_id"],
            expected_generation=0,
        )
        receipt_path = self.store.publications / f"active-model.{staged['operation_id']}.json"
        receipt_path.write_bytes(b"{}")
        report = self.store.reconcile()
        self.assertEqual(
            report["corrupt_publication_receipts"],
            [f"active-model:{staged['operation_id']}"],
        )

    def test_reconciliation_distinguishes_orphan_objects_and_corrupt_receipts(self):
        staged, _ = self.stage_validate_commit(key="orphan-after-receipt-corruption")
        operation_id = staged["operation_id"]
        object_hash = staged["content_sha256"]
        self.store._commit_path(operation_id).write_bytes(b"{")
        report = self.store.reconcile()
        self.assertIn(operation_id, report["corrupt_commit_receipts"])
        self.assertIn(object_hash, report["orphan_objects"])
        self.assertNotIn(object_hash, report["corrupt_objects"])

    def test_pointer_detects_tampered_object_bytes(self):
        staged, _ = self.stage_validate_commit(key="tamper-me")
        pointer = self.store.publish_pointer(
            name="active-model",
            operation_id=staged["operation_id"],
            expected_generation=0,
        )
        object_path = self.store._object_path(pointer["object_sha256"])
        object_path.write_bytes(b"tampered")
        with self.assertRaises(StorageError):
            self.store.read_pointer("active-model")


if __name__ == "__main__":
    unittest.main()
