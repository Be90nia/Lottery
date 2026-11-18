import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lottery.validate import DatasetValidationError, validate_records


def record(draw_id="26131", draw_date="2026-11-16", front=None, back=None):
    return {
        "draw_id": draw_id,
        "draw_date": draw_date,
        "front_numbers": front if front is not None else [2, 11, 18, 19, 29],
        "back_numbers": back if back is not None else [4, 7],
        "source_id": "sha256:fixture",
    }


class DatasetValidationTests(unittest.TestCase):
    def test_valid_dataset(self):
        report = validate_records([record()])
        self.assertEqual(report["records"], 1)
        self.assertEqual(report["unique_draw_ids"], 1)

    def test_empty_dataset_rejected(self):
        with self.assertRaises(DatasetValidationError):
            validate_records([])

    def test_duplicate_draw_id_rejected(self):
        with self.assertRaises(DatasetValidationError):
            validate_records([record(), record(draw_date="2026-11-17")])

    def test_unsorted_dataset_rejected(self):
        with self.assertRaises(DatasetValidationError):
            validate_records([
                record("26132", "2026-11-17"),
                record("26131", "2026-11-16"),
            ])

    def test_invalid_front_zone_rejected(self):
        with self.assertRaises(DatasetValidationError):
            validate_records([record(front=[1, 1, 3, 4, 5])])

    def test_invalid_date_rejected(self):
        with self.assertRaises(DatasetValidationError):
            validate_records([record(draw_date="2026-02-30")])

    def test_raw_source_order_must_be_string_or_null(self):
        row = record()
        row["source_unsort_drawresult"] = [2, 11, 18, 19, 29, 4, 7]
        with self.assertRaises(DatasetValidationError):
            validate_records([row])

    def test_raw_source_order_must_match_parsed_order(self):
        row = record()
        row["front_draw_order"] = [11, 2, 18, 19, 29]
        row["back_draw_order"] = [4, 7]
        row["source_unsort_drawresult"] = "02 11 18 19 29 04 07"
        with self.assertRaises(DatasetValidationError):
            validate_records([row])

    def test_raw_source_metadata_is_optional_and_preserved(self):
        row = record()
        row["source_unsort_drawresult"] = "02 11 18 19 29 04 07"
        row["front_draw_order"] = [2, 11, 18, 19, 29]
        row["back_draw_order"] = [4, 7]
        row["source_equipment_count"] = 2
        self.assertEqual(validate_records([row])["records"], 1)

    def test_invalid_draw_order_rejected(self):
        row = record()
        row["front_draw_order"] = [2, 11, 18, 19, 28]
        row["back_draw_order"] = [4, 7]
        with self.assertRaises(DatasetValidationError):
            validate_records([row])


if __name__ == "__main__":
    unittest.main()
