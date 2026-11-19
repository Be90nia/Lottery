from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "evaluation_receipt.py"


def score_rows(count: int = 200):
    result = []
    for index in range(count):
        models = {}
        for name, delta in (("candidate", -0.02), ("champion", 0.0), ("uniform", 0.0)):
            models[name] = {
                "front": {"brier": 0.2 + delta, "log_loss": 0.4 + delta},
                "back": {"brier": 0.3 + delta, "log_loss": 0.5 + delta},
            }
        result.append({"target_draw_id": f"{26001 + index:05d}", "model_scores": models})
    return result


class EvaluationReceiptCliTests(unittest.TestCase):
    def run_cli(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_build_verify_and_refuse_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scores = root / "scores.json"
            output = root / "receipt.json"
            scores.write_text(json.dumps({"score_rows": score_rows()}), encoding="utf-8")
            build_args = (
                "build", str(scores),
                "--candidate-model-id", "candidate-v2",
                "--champion-model-id", "champion-v1",
                "--dataset-sha256", "a" * 64,
                "--code-commit", "b" * 40,
                "--protocol-version", "frozen-v1",
                "--output", str(output),
            )
            built = self.run_cli(*build_args)
            self.assertEqual(built.returncode, 0, built.stderr)
            original = output.read_bytes()
            receipt = json.loads(original)
            self.assertEqual(receipt["decision"], "eligible_for_human_review")
            self.assertEqual(receipt["automatic_promotion"], False)

            verified = self.run_cli("verify", str(output))
            self.assertEqual(verified.returncode, 0, verified.stderr)
            self.assertTrue(json.loads(verified.stdout)["valid"])

            duplicate = self.run_cli(*build_args)
            self.assertEqual(duplicate.returncode, 1)
            self.assertIn("refusing to overwrite", duplicate.stderr)
            self.assertEqual(output.read_bytes(), original)

    def test_verify_rejects_tampered_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scores = root / "scores.json"
            output = root / "receipt.json"
            scores.write_text(json.dumps({"score_rows": score_rows()}), encoding="utf-8")
            built = self.run_cli(
                "build", str(scores),
                "--candidate-model-id", "candidate-v2",
                "--champion-model-id", "champion-v1",
                "--dataset-sha256", "a" * 64,
                "--code-commit", "b" * 40,
                "--protocol-version", "frozen-v1",
                "--output", str(output),
            )
            self.assertEqual(built.returncode, 0, built.stderr)
            receipt = json.loads(output.read_text(encoding="utf-8"))
            receipt["candidate_model_id"] = "tampered"
            output.write_text(json.dumps(receipt), encoding="utf-8")
            verified = self.run_cli("verify", str(output))
            self.assertEqual(verified.returncode, 1)
            self.assertIn("EVALUATION_RECEIPT_FAILED", verified.stderr)


if __name__ == "__main__":
    unittest.main()
