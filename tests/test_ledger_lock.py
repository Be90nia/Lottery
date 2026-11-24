import multiprocessing
import os
from pathlib import Path
import tempfile
import unittest

from lottery.ledger_lock import LedgerLockError, ledger_lock


def _hold_lock(path, ready, release):
    with ledger_lock(Path(path)):
        ready.set()
        release.wait(timeout=15)


def _exit_with_lock_held(path, ready):
    with ledger_lock(Path(path)):
        ready.set()
        os._exit(0)


def _contend_first_lock_creation(path, barrier, results):
    try:
        barrier.wait(timeout=15)
        with ledger_lock(Path(path)):
            results.put("ok")
    except Exception as exc:
        results.put(type(exc).__name__ + ":" + str(exc))


class LedgerLockTests(unittest.TestCase):
    def test_lock_file_is_reused_and_persists(self):
        with tempfile.TemporaryDirectory() as temp:
            ledger = Path(temp) / "ledger.jsonl"
            lock_path = Path(str(ledger) + ".lock")
            with ledger_lock(ledger):
                self.assertTrue(lock_path.exists())
            self.assertTrue(lock_path.exists())
            with ledger_lock(ledger, timeout=0.2):
                self.assertTrue(lock_path.exists())

    def test_contender_times_out_while_another_process_holds_lock(self):
        with tempfile.TemporaryDirectory() as temp:
            ledger = Path(temp) / "ledger.jsonl"
            ctx = multiprocessing.get_context("spawn")
            ready, release = ctx.Event(), ctx.Event()
            process = ctx.Process(target=_hold_lock, args=(str(ledger), ready, release))
            process.start()
            self.assertTrue(ready.wait(timeout=10))
            try:
                with self.assertRaises(LedgerLockError):
                    with ledger_lock(ledger, timeout=0.15):
                        pass
            finally:
                release.set()
                process.join(timeout=10)
            self.assertEqual(process.exitcode, 0)

    def test_process_exit_releases_operating_system_lock(self):
        with tempfile.TemporaryDirectory() as temp:
            ledger = Path(temp) / "ledger.jsonl"
            ctx = multiprocessing.get_context("spawn")
            ready = ctx.Event()
            process = ctx.Process(target=_exit_with_lock_held, args=(str(ledger), ready))
            process.start()
            self.assertTrue(ready.wait(timeout=10))
            process.join(timeout=10)
            self.assertEqual(process.exitcode, 0)
            with ledger_lock(ledger, timeout=1):
                pass

    def test_concurrent_first_lock_creation_uses_one_lock_region(self):
        with tempfile.TemporaryDirectory() as temp:
            ledger = Path(temp) / "ledger.jsonl"
            ctx = multiprocessing.get_context("spawn")
            barrier, results = ctx.Barrier(4), ctx.Queue()
            processes = [
                ctx.Process(
                    target=_contend_first_lock_creation,
                    args=(str(ledger), barrier, results),
                )
                for _ in range(4)
            ]
            for process in processes:
                process.start()
            outcomes = [results.get(timeout=25) for _ in processes]
            for process in processes:
                process.join(timeout=10)
                self.assertEqual(process.exitcode, 0)
            self.assertEqual(outcomes, ["ok"] * 4)
            self.assertEqual(Path(str(ledger) + ".lock").stat().st_size, 1)


if __name__ == "__main__":
    unittest.main()
