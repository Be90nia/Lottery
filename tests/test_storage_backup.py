from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from lottery import backup as backup_module
from lottery.backup import BackupError, create_backup, restore_backup, verify_backup
from lottery.storage import FileSystemObjectStore


class StorageBackupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store_root = self.root / "primary"
        self.backup_root = self.root / "backups"
        self.store = FileSystemObjectStore(self.store_root)

    def create_committed_pointer(self, *, tamper=False):
        staged = self.store.stage(
            idempotency_key="backup-drill-inventory",
            content=b"canonical inventory bytes",
            media_type="application/x-ndjson",
            schema_version="inventory/v1",
            producer_commit="a" * 40,
            producer_runtime="CPython 3.12",
        )
        self.store.validate(operation_id=staged["operation_id"])
        self.store.commit(operation_id=staged["operation_id"])
        pointer = self.store.publish_pointer(
            name="active-inventory",
            operation_id=staged["operation_id"],
            expected_generation=0,
        )
        if tamper:
            self.store._object_path(pointer["object_sha256"]).write_bytes(b"tampered bytes")
        return staged, pointer

    def create(self, backup_id="backup-001"):
        return create_backup(
            self.store_root,
            self.backup_root,
            backup_id=backup_id,
            source_commit="b" * 40,
            runtime="CPython 3.12",
        )

    def test_backup_verify_and_isolated_restore_reconstruct_pointer(self):
        staged, pointer = self.create_committed_pointer()
        created = self.create()
        verified = verify_backup(created["backup_path"])
        self.assertTrue(verified["verified"])
        restored_root = self.root / "restore-isolated"
        receipt = restore_backup(created["backup_path"], restored_root)
        self.assertTrue(receipt["verified"])
        self.assertEqual(receipt["file_count"], created["file_count"])
        restored = FileSystemObjectStore(restored_root)
        self.assertEqual(restored.read_pointer("active-inventory"), pointer)
        self.assertEqual(
            restored._object_path(pointer["object_sha256"]).read_bytes(),
            b"canonical inventory bytes",
        )
        self.assertEqual(restored.reconcile()["dangling_pointers"], [])

    def test_backup_is_no_clobber_and_excludes_only_transient_lock_files(self):
        self.create_committed_pointer()
        lock_file = self.store_root / "manual-operation.lock"
        lock_file.write_bytes(b"lock-state")
        created = self.create()
        manifest = json.loads((Path(created["backup_path"]) / "manifest.json").read_text())
        paths = [entry["path"] for entry in manifest["files"]]
        self.assertNotIn("manual-operation.lock", paths)
        with self.assertRaisesRegex(BackupError, "already exists"):
            self.create()

    def test_tampered_payload_and_extra_files_fail_verification(self):
        self.create_committed_pointer()
        created = self.create()
        payload = Path(created["backup_path"]) / "payload"
        first = next(path for path in payload.rglob("*") if path.is_file())
        first.write_bytes(b"tampered")
        with self.assertRaisesRegex(BackupError, "integrity mismatch"):
            verify_backup(created["backup_path"])

    def test_backup_rejects_unlisted_empty_directories(self):
        self.create_committed_pointer()
        created = self.create()
        (Path(created["backup_path"]) / "payload" / "unexpected-empty").mkdir()
        with self.assertRaisesRegex(BackupError, "unexpected empty directories"):
            verify_backup(created["backup_path"])

    def test_source_mutation_during_copy_aborts_backup(self):
        self.store_root.mkdir()
        source_file = self.store_root / "snapshot.json"
        source_file.write_bytes(b"before")
        real_inventory = backup_module._inventory
        calls = 0

        def mutate_after_first_inventory(root):
            nonlocal calls
            calls += 1
            result = real_inventory(root)
            if calls == 1:
                source_file.write_bytes(b"after")
            return result

        with patch("lottery.backup._inventory", side_effect=mutate_after_first_inventory):
            with self.assertRaisesRegex(BackupError, "source changed"):
                self.create()
        self.assertFalse((self.backup_root / "backup-001").exists())

    def test_restore_rejects_existing_destination_even_when_empty(self):
        self.create_committed_pointer()
        created = self.create()
        empty = self.root / "empty-destination"
        empty.mkdir()
        with self.assertRaisesRegex(BackupError, "must not already exist"):
            restore_backup(created["backup_path"], empty)

    def test_restore_rejects_nonempty_destination(self):
        self.create_committed_pointer()
        created = self.create()
        destination = self.root / "not-empty"
        destination.mkdir()
        (destination / "keep.txt").write_text("keep")
        with self.assertRaisesRegex(BackupError, "empty"):
            restore_backup(created["backup_path"], destination)
        self.assertEqual((destination / "keep.txt").read_text(), "keep")

    def test_restore_reconciliation_rejects_corrupt_storage_even_when_backup_hashes_match(self):
        self.create_committed_pointer(tamper=True)
        created = self.create()
        with self.assertRaisesRegex(BackupError, "integrity failures"):
            restore_backup(created["backup_path"], self.root / "restore-corrupt")

    def test_backup_rejects_symlinked_storage_entries(self):
        self.store_root.mkdir()
        external = self.root / "external.txt"
        external.write_text("outside")
        (self.store_root / "linked.txt").symlink_to(external)
        with self.assertRaisesRegex(BackupError, "symlink"):
            self.create()

    def test_backup_root_cannot_be_nested_inside_source(self):
        self.store_root.mkdir()
        with self.assertRaisesRegex(BackupError, "inside source_root"):
            create_backup(
                self.store_root,
                self.store_root / "backups",
                backup_id="nested",
                source_commit="b" * 40,
                runtime="CPython 3.12",
            )


if __name__ == "__main__":
    unittest.main()
