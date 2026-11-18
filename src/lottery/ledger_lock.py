"""Cross-process advisory locks for append-only JSONL ledgers.

Locks are released by the operating system when a process exits. Keep lock
files in place: deleting/recreating a lock file while another process has it
open can split the lock domain. Advisory locks require cooperating writers.
"""
from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
import time
from typing import Iterator


class LedgerLockError(RuntimeError):
    """Raised when an OS-level ledger lock cannot be acquired."""


@contextmanager
def ledger_lock(ledger_path: Path, timeout: float = 30.0) -> Iterator[None]:
    lock_path = ledger_path.with_name(ledger_path.name + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    handle = os.fdopen(descriptor, "r+b", buffering=0)
    locked = False
    try:
        if os.name == "nt":
            import msvcrt

            # All contenders initialize the same byte offset; never append to
            # the lock file, which could create different lock regions.
            if os.fstat(handle.fileno()).st_size == 0:
                handle.seek(0)
                handle.write(b"\0")
                handle.flush()
            deadline = time.monotonic() + timeout
            while True:
                try:
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    locked = True
                    break
                except OSError as exc:
                    if time.monotonic() >= deadline:
                        raise LedgerLockError(
                            f"timed out acquiring ledger lock {lock_path}"
                        ) from exc
                    time.sleep(0.05)
        else:
            import fcntl

            deadline = time.monotonic() + timeout
            while True:
                try:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    locked = True
                    break
                except BlockingIOError as exc:
                    if time.monotonic() >= deadline:
                        raise LedgerLockError(
                            f"timed out acquiring ledger lock {lock_path}"
                        ) from exc
                    time.sleep(0.05)
        yield
    finally:
        if locked:
            if os.name == "nt":
                import msvcrt

                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()
