import tempfile
import unittest
from pathlib import Path

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
        with self.assertRaises(StalePointer):
            self.store.publish_pointer(
                name="active-inventory",
                operation_id=staged["operation_id"],
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
