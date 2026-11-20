#!/usr/bin/env python3
"""Create, verify or restore an offline Lottery storage backup package."""
from __future__ import annotations

import argparse
import json
import sys

from lottery.backup import BackupError, create_backup, restore_backup, verify_backup


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    create = commands.add_parser("create")
    create.add_argument("--source-root", required=True)
    create.add_argument("--backup-root", required=True)
    create.add_argument("--backup-id", required=True)
    create.add_argument("--source-commit", required=True)
    create.add_argument("--runtime", required=True)

    verify = commands.add_parser("verify")
    verify.add_argument("--backup-dir", required=True)

    restore = commands.add_parser("restore")
    restore.add_argument("--backup-dir", required=True)
    restore.add_argument("--restore-root", required=True)

    args = parser.parse_args()
    try:
        if args.command == "create":
            result = create_backup(
                args.source_root,
                args.backup_root,
                backup_id=args.backup_id,
                source_commit=args.source_commit,
                runtime=args.runtime,
            )
        elif args.command == "verify":
            result = verify_backup(args.backup_dir)
        else:
            result = restore_backup(args.backup_dir, args.restore_root)
    except (BackupError, OSError) as exc:
        print(f"storage backup operation failed closed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
