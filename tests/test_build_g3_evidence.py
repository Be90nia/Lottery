import hashlib
import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from scripts.build_g3_evidence import (
    G3EvidenceBuildError,
    _holm,
    _read_snapshot,
    _strict_json,
)


class G3EvidenceAdapterTests(unittest.TestCase):
    def test_holm_step_down_is_deterministic(self):
        adjusted = _holm({"front": 0.01, "back": 0.04})
        self.assertEqual(adjusted, {"front": 0.02, "back": 0.04})

    def test_duplicate_json_keys_are_rejected(self):
        with self.assertRaisesRegex(G3EvidenceBuildError, "duplicate JSON key"):
            _strict_json(b'{"run_id":"a","run_id":"b"}', "fixture")

    def test_snapshot_preflight_derives_strict_target_boundary(self):
        rows = []
        first = date(2007, 1, 1)
        for index in range(2949):
            if index < 300:
                draw_id = f"{7001 + index:05d}"
            else:
                draw_id = f"{9054 + ((26131 - 9054) * (index - 300) // 2648):05d}"
            rows.append({
                "draw_id": draw_id,
                "draw_date": (first + timedelta(days=index)).isoformat(),
                "front_numbers": [1, 2, 3, 4, 5],
                "back_numbers": [1, 2],
            })
        raw = b"".join(
            json.dumps(row, separators=(",", ":")).encode("utf-8") + b"\n"
            for row in rows
        )
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "snapshot.jsonl"
            path.write_bytes(raw)
            actual = hashlib.sha256(raw).hexdigest()
            _, parsed = _read_snapshot(path, actual)
            self.assertEqual(len(parsed), 2949)
            self.assertEqual(parsed[300]["draw_id"], "09054")
            self.assertEqual(parsed[-1]["draw_id"], "26131")
            with self.assertRaisesRegex(G3EvidenceBuildError, "SHA-256 mismatch"):
                _read_snapshot(path, "0" * 64)


if __name__ == "__main__":
    unittest.main()
