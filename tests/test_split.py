import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lottery.split import split_chronologically
from lottery.validate import DatasetValidationError


def draw(draw_id, day):
    return {
        "draw_id": draw_id,
        "draw_date": f"2026-01-{day:02d}",
        "front_numbers": [1, 2, 3, 4, 5],
        "back_numbers": [1, 2],
        "source_id": "test",
    }


class ChronologicalSplitTests(unittest.TestCase):
    def test_splits_contiguously_and_preserves_chronology(self):
        rows = [draw(f"260{i:02d}", i) for i in range(1, 11)]
        result = split_chronologically(rows, train_fraction=0.6, validation_fraction=0.2)
        parts = result["partitions"]
        self.assertEqual([len(parts[name]) for name in ("train", "validation", "test")], [6, 2, 2])
        self.assertLess(parts["train"][-1]["draw_date"], parts["validation"][0]["draw_date"])
        self.assertLess(parts["validation"][-1]["draw_date"], parts["test"][0]["draw_date"])

    def test_same_date_rows_never_split(self):
        rows = [
            draw("26001", 1),
            draw("26002", 2),
            draw("26003", 2),
            draw("26004", 3),
            draw("26005", 4),
        ]
        result = split_chronologically(rows, train_fraction=0.4, validation_fraction=0.2)
        partitions = result["partitions"]
        owners = {
            row["draw_date"]: name
            for name, values in partitions.items()
            for row in values
        }
        self.assertEqual(owners["2026-01-02"], "validation")
        self.assertEqual(sum(row["draw_date"] == "2026-01-02" for row in partitions["validation"]), 2)

    def test_rejects_unsorted_input(self):
        rows = [draw("26002", 2), draw("26001", 1), draw("26003", 3)]
        with self.assertRaises(DatasetValidationError):
            split_chronologically(rows)

    def test_rejects_insufficient_date_groups(self):
        rows = [draw("26001", 1), draw("26002", 1), draw("26003", 2)]
        with self.assertRaisesRegex(ValueError, "three distinct"):
            split_chronologically(rows)

    def test_rejects_invalid_fractions(self):
        rows = [draw(f"260{i:02d}", i) for i in range(1, 5)]
        for train, validation in ((0, 0.2), (0.7, 0), (0.8, 0.2), (1.1, 0.1)):
            with self.subTest(train=train, validation=validation):
                with self.assertRaises(ValueError):
                    split_chronologically(rows, train_fraction=train, validation_fraction=validation)

    def test_deterministic_partition_output(self):
        rows = [draw(f"260{i:02d}", i) for i in range(1, 8)]
        first = split_chronologically(rows)
        second = split_chronologically(rows)
        self.assertEqual(first, second)
        self.assertEqual(
            json.dumps(first["partitions"], sort_keys=True),
            json.dumps(second["partitions"], sort_keys=True),
        )


if __name__ == "__main__":
    unittest.main()
