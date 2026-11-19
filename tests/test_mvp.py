import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

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
            self.assertEqual(document["batch"]["code_commit"], "a" * 40)
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

    def test_existing_batch_output_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            dataset = root / "draws.jsonl"
            output = root / "mvp.json"
            dataset.write_text("".join(json.dumps(draw(i)) + "\n" for i in range(1, 8)), encoding="utf-8")
            output.write_text("preserve-me", encoding="utf-8")
            with self.assertRaisesRegex(FileExistsError, "refusing to overwrite"):
                run_mvp(dataset, output, code_commit="a" * 40)
            self.assertEqual(output.read_text(encoding="utf-8"), "preserve-me")
            self.assertEqual(list(root.glob("mvp.json.*.tmp")), [])

    def test_code_commit_is_required_for_auditable_batch(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            dataset = root / "draws.jsonl"
            output = root / "mvp.json"
            dataset.write_text("".join(json.dumps(draw(i)) + "\n" for i in range(1, 8)), encoding="utf-8")
            with patch.dict(os.environ, {}, clear=True):
                with self.assertRaisesRegex(ValueError, "GITHUB_SHA"):
                    run_mvp(dataset, output)
            self.assertFalse(output.exists())

    def test_generation_identity_binds_code_commit(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            dataset = root / "draws.jsonl"
            dataset.write_text("".join(json.dumps(draw(i)) + "\n" for i in range(1, 8)), encoding="utf-8")
            first = run_mvp(dataset, root / "first.json", seed=73, code_commit="a" * 40)
            second = run_mvp(dataset, root / "second.json", seed=73, code_commit="b" * 40)
            self.assertNotEqual(
                first["batch"]["generation_run_id"],
                second["batch"]["generation_run_id"],
            )
            self.assertNotEqual(
                first["batch"]["strategies"]["uniform"][0]["ticket_id"],
                second["batch"]["strategies"]["uniform"][0]["ticket_id"],
            )

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
                 "--tickets-per-strategy", "2", "--seed", "73", "--code-commit", "c" * 40,
                 "--output", str(output)],
                check=False, capture_output=True, text=True,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            document = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(document["receipt"]["published_ticket_count"], 6)
            self.assertEqual(document["batch"]["total_tickets"], 6)

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
