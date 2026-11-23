import tempfile
import unittest
from pathlib import Path

from lottery.storage import FileSystemObjectStore, StorageError
from lottery.subset_model.artifact import canonicalize


class StorageCommitVerificationTests(unittest.TestCase):
    def test_commit_receipt_resolves_to_verified_read_back_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            store = FileSystemObjectStore(Path(directory) / "objects")
            payload = b'{"result":"complete"}'
            staged = store.stage(
                idempotency_key="execution-1:run_manifest.json",
                content=payload,
                media_type="application/json",
                schema_version="lottery.run-manifest/v1",
                producer_commit="a" * 40,
                producer_runtime="python-test",
            )
            operation_id = staged["operation_id"]
            store.validate(
                operation_id=operation_id,
                validator=lambda raw: raw == payload,
                validator_id="test-exact-bytes/v1",
            )
            committed = store.commit(operation_id=operation_id)
            verified = store.verify_commit(
                operation_id=operation_id,
                expected_content_sha256=staged["content_sha256"],
            )
            self.assertEqual(verified, committed)
            self.assertTrue(verified["committed"])

    def test_verifier_rejects_tampered_commit_cross_link(self):
        with tempfile.TemporaryDirectory() as directory:
            store = FileSystemObjectStore(Path(directory) / "objects")
            payload = b'{"result":"complete"}'
            staged = store.stage(
                idempotency_key="execution-2:result.json",
                content=payload,
                media_type="application/json",
                schema_version="lottery.result/v1",
                producer_commit="b" * 40,
                producer_runtime="python-test",
            )
            operation_id = staged["operation_id"]
            store.validate(
                operation_id=operation_id,
                validator=lambda raw: raw == payload,
                validator_id="test-exact-bytes/v1",
            )
            store.commit(operation_id=operation_id)
            receipt_path = store._commit_path(operation_id)
            receipt = store._read_canonical(receipt_path) if hasattr(store, "_read_canonical") else None
            if receipt is None:
                import json
                receipt = json.loads(receipt_path.read_text())
            receipt["content_sha256"] = "f" * 64
            receipt_path.write_bytes(canonicalize(receipt))
            with self.assertRaisesRegex(StorageError, "cross-links"):
                store.verify_commit(operation_id=operation_id)

    def test_verifier_rejects_bytes_only_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            store = FileSystemObjectStore(Path(directory) / "objects")
            staged = store.stage(
                idempotency_key="execution-4:bytes-only.json",
                content=b"{}",
                media_type="application/json",
                schema_version="lottery.run-manifest/v1",
                producer_commit="d" * 40,
                producer_runtime="python-test",
            )
            store.validate(operation_id=staged["operation_id"])
            store.commit(operation_id=staged["operation_id"])
            with self.assertRaisesRegex(StorageError, "validation receipt"):
                store.verify_commit(operation_id=staged["operation_id"])

    def test_verifier_rejects_missing_commit_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            store = FileSystemObjectStore(Path(directory) / "objects")
            staged = store.stage(
                idempotency_key="execution-3:manifest.json",
                content=b"{}",
                media_type="application/json",
                schema_version="lottery.run-manifest/v1",
                producer_commit="c" * 40,
                producer_runtime="python-test",
            )
            with self.assertRaises(StorageError):
                store.verify_commit(operation_id=staged["operation_id"])


if __name__ == "__main__":
    unittest.main()
