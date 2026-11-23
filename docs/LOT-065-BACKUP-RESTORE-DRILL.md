# LOT-065 offline backup and restore drill

This implementation adds a local immutable backup package and an isolated
restore verifier for the filesystem storage adapter.

## Create, verify and restore

```sh
python scripts/storage_backup.py create \
  --source-root ./data/storage \
  --backup-root ./recovery/backups \
  --backup-id drill-20261120-001 \
  --source-commit FULL_40_CHAR_COMMIT_SHA \
  --runtime "CPython 3.12"

python scripts/storage_backup.py verify \
  --backup-dir ./recovery/backups/drill-20261120-001

python scripts/storage_backup.py restore \
  --backup-dir ./recovery/backups/drill-20261120-001 \
  --restore-root ./recovery/isolated-restore-001
```

The backup manifest records the source commit/runtime, exact relative file
inventory, byte lengths, per-file SHA-256, inventory digest and manifest
digest. Transient advisory lock files and in-progress temporary files are
excluded; symlinks and non-regular files are rejected. Source inventory is
checked before and after copying; a changing source aborts the backup.
Backup IDs are immutable and no-clobber.

Verification is read-only: it validates canonical manifest bytes, exact
payload file and directory inventory, and every file's length/hash. Restore
first verifies the package, writes into a private sibling staging directory,
checks the restored inventory and runs read-only storage reconciliation.
Only a verified restore directory is atomically renamed into the requested
previously absent destination. Corrupt pointers, commit receipts, publication
receipts or objects prevent restore completion.

## Boundaries that remain

This is a **local recovery drill**, not an independent backup service:
- A second directory on the same machine/filesystem shares the primary
  failure domain. It does not meet the independent-domain backup requirement.
- The package is checksummed, not encrypted or cryptographically signed.
- The operator must quiesce writers during backup. Double inventory detects
  ordinary concurrent mutation but does not replace a transactional snapshot
  from a storage backend.
- No RPO/RTO is claimed; those require measured restore drills and approved
  operational targets.
- No automatic retention, legal hold, key recovery, remote replication,
  hosted scheduler or production restore credential is introduced.

The restore receipt is printed by the CLI and should be retained in the
separate recovery evidence system. A successful local restore does not by
itself make G7 pass for production.
