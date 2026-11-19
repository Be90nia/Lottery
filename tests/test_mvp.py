import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from lottery.mvp import run_mvp


def draw(index):
    return {
        "draw_id": f"26{index:03d}",
        "draw_date": f"2026-01-{index:02d}",
        "front_numbers": [1, 2, 3, 4, 5],
        "back_numbers": [1, 2],
        "source_id": "fixture",
    }


class MvpOrchestratorTests(unittest.TestCase):
    def test_run_publishes_atomic_three_lane_batch_and_receipt(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            dataset = root / "draws.jsonl"
            output = root / "out" / "mvp.json"
            raw = "".join(json.dumps(draw(i)) + "\n" for i in range(1, 8)).encode()
            dataset.write_bytes(raw)

            document = run_mvp(
                dataset, output, tickets_per_strategy=3, seed=91,
                code_commit="a" * 40,
            )
            persisted = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(document, persisted)
            self.assertEqual(document["receipt"]["status"], "candidate_batch_generated")
            self.assertEqual(document["receipt"]["dataset_sha256"], hashlib.sha256(raw).hexdigest())
            self.assertEqual(document["receipt"]["published_ticket_count"], 9)
            self.assertEqual(document["batch"]["total_tickets"], 9)
            self.assertEqual(set(document["batch"]["strategies"]), {"uniform", "expanding", "ewma"})
            self.assertEqual(document["receipt"]["automatic_sync_status"], "not_attempted")
            self.assertEqual(document["receipt"]["model_training_status"], "not_performed")
            self.assertEqual(document["receipt"]["model_promotion_status"], "not_performed")
            batch_bytes = json.dumps(
                document["batch"], ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
            self.assertEqual(document["receipt"]["batch_sha256"], hashlib.sha256(batch_bytes).hexdigest())
            self.assertEqual(list(output.parent.glob("mvp.json.*.tmp")), [])

    def test_output_cannot_overwrite_input_dataset(self):
        with tempfile.TemporaryDirectory() as temp:
            dataset = Path(temp) / "draws.jsonl"
            dataset.write_text("".join(json.dumps(draw(i)) + "\n" for i in range(1, 8)), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "must not overwrite"):
                run_mvp(dataset, dataset)
            self.assertTrue(dataset.exists())

    def test_cli_executes_end_to_end_pipeline(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            dataset = root / "draws.jsonl"
            output = root / "mvp.json"
            dataset.write_text("".join(json.dumps(draw(i)) + "\n" for i in range(1, 8)), encoding="utf-8")
            completed = subprocess.run(
                [sys.executable, "scripts/run_mvp.py", "--dataset", str(dataset),
                 "--tickets-per-strategy", "2", "--seed", "73", "--code-commit", "d" * 40,
                 "--output", str(output)],
                check=False, capture_output=True, text=True,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            document = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(document["receipt"]["published_ticket_count"], 6)
            self.assertEqual(document["batch"]["total_tickets"], 6)

    def test_existing_output_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            dataset = root / "draws.jsonl"
            output = root / "mvp.json"
            dataset.write_text("".join(json.dumps(draw(i)) + "\n" for i in range(1, 8)), encoding="utf-8")
            output.write_text("prior evidence", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "already exists"):
                run_mvp(dataset, output, code_commit="e" * 40)
            self.assertEqual(output.read_text(encoding="utf-8"), "prior evidence")

    def test_missing_code_commit_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            dataset = root / "draws.jsonl"
            dataset.write_text("".join(json.dumps(draw(i)) + "\n" for i in range(1, 8)), encoding="utf-8")
            with patch.dict(os.environ, {}, clear=True):
                with self.assertRaisesRegex(ValueError, "code_commit is required"):
                    run_mvp(dataset, root / "out.json")

    def test_invalid_dataset_never_publishes_output(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            dataset = root / "invalid.jsonl"
            output = root / "mvp.json"
            dataset.write_text("not-json\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                run_mvp(dataset, output)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
