import unittest

from scripts.verify_official_order_crosswalks import selected_random_sample_ids, verify


class OfficialOrderCrosswalkTests(unittest.TestCase):
    def record(self):
        return {
            "draw_id": "26083",
            "draw_date": "2026-07-25",
            "front_numbers": [14, 15, 16, 23, 26],
            "back_numbers": [7, 9],
            "front_draw_order": [15, 16, 23, 26, 14],
            "back_draw_order": [9, 7],
            "equipment_set": 3,
            "source_url": "https://www.cqtcw.net/example",
            "source_capture_status": "url_transcribed_not_archived",
            "source_label_order": "本期出球顺序",
            "source_label_equipment": "本期使用第3套摇奖球",
        }

    def candidate(self):
        return {
            "draw_id": "26083",
            "draw_date": "2026-07-25",
            "front_numbers": [14, 15, 16, 23, 26],
            "back_numbers": [7, 9],
            "front_draw_order": [15, 16, 23, 26, 14],
            "back_draw_order": [9, 7],
            "equipment_code_legacy": 3,
        }

    def test_exact_official_crosswalk_passes(self):
        result = verify(
            [self.candidate()],
            {"schema": "test/v1", "records": [self.record()]},
        )
        self.assertEqual(result["compared_records"], 1)
        self.assertEqual(result["errors"], [])

    def test_order_mismatch_fails(self):
        candidate = self.candidate()
        candidate["front_draw_order"] = [14, 15, 16, 23, 26]
        result = verify(
            [candidate],
            {"schema": "test/v1", "records": [self.record()]},
        )
        self.assertTrue(any("front_draw_order mismatch" in item for item in result["errors"]))

    def test_equipment_mismatch_fails(self):
        candidate = self.candidate()
        candidate["equipment_code_legacy"] = 2
        result = verify(
            [candidate],
            {"schema": "test/v1", "records": [self.record()]},
        )
        self.assertTrue(any("equipment_code_legacy mismatch" in item for item in result["errors"]))

    def test_duplicate_crosswalk_draw_id_fails(self):
        result = verify(
            [self.candidate()],
            {"schema": "test/v1", "records": [self.record(), self.record()]},
        )
        self.assertTrue(any("duplicate crosswalk draw_id" in item for item in result["errors"]))

    def test_stratified_random_sample_selection_is_reproducible(self):
        candidates = []
        for draw_id in ("11001", "11002", "11003", "12001", "12002", "12003"):
            candidates.append({
                "draw_id": draw_id,
                "draw_date": "2011-01-01" if draw_id.startswith("11") else "2012-01-01",
                "front_draw_order": [1, 2, 3, 4, 5],
                "back_draw_order": [1, 2],
                "equipment_code_legacy": 1,
            })
        registry = {
            "records": [{"draw_id": "11001", "sample_group": "purposive_convenience"}],
            "source_selection": {
                "random_sample_seed": 20261118,
                "selected_ids": ["11003", "12002"],
            },
        }
        self.assertEqual(
            selected_random_sample_ids(candidates, registry),
            ["11003", "12002"],
        )

    def test_non_permutation_official_order_fails(self):
        record = self.record()
        record["front_draw_order"] = [15, 16, 23, 26, 26]
        result = verify(
            [self.candidate()],
            {"schema": "test/v1", "records": [record]},
        )
        self.assertTrue(any("official front order is not a permutation" in item for item in result["errors"]))


if __name__ == "__main__":
    unittest.main()
