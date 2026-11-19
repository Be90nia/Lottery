import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lottery.reported_set_index import (
    ReportedSetIndexError,
    build_reported_set_index_view,
    write_reported_set_index_view,
)


def canonical(value):
    return json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def inventory_rows():
    return [
        {
            "draw_id": "26001", "draw_date": "2026-01-01",
            "front_numbers": [1, 2, 3, 4, 5], "back_numbers": [1, 2],
            "source_id": "sha256:inventory-1",
        },
        {
            "draw_id": "26002", "draw_date": "2026-01-02",
            "front_numbers": [2, 3, 4, 5, 6], "back_numbers": [2, 3],
            "source_id": "sha256:inventory-2",
        },
        {
            "draw_id": "26003", "draw_date": "2026-01-03",
            "front_numbers": [3, 4, 5, 6, 7], "back_numbers": [3, 4],
            "source_id": "sha256:inventory-3",
        },
    ]


def evidence_row(draw_id, draw_date, set_index=None, status="unobserved"):
    return {
        "draw_id": draw_id,
        "draw_date": draw_date,
        "reported_set_index": set_index,
        "status": status,
        "eligible": False,
        "exclusion_reason": "regime_unresolved" if status == "primary_verified" else None,
        "equipment_regime_id": None,
        "physical_ball_set_id": None,
        "observation_ids": [f"obs-{draw_id}"] if status == "primary_verified" else [],
        "source_urls": [f"https://www.js-lottery.com/cms/post-{draw_id}.html"] if status == "primary_verified" else [],
    }


def coverage_for(inventory_raw, ledger_raw):
    payload = {
        "schema_version": "lottery.ball-set-coverage/v1",
        "inventory_sha256": sha(inventory_raw),
        "inventory_trust_status": "candidate_unverified",
        "observation_ledger_sha256": sha(ledger_raw),
        "source_domains": ["www.js-lottery.com"],
        "code_commit": "a" * 40,
        "summary": {
            "inventory_draws": 3,
            "primary_verified_draws": 2,
            "set_index_counts": {"1": 1, "2": 1, "3": 0},
            "regime_assignment_count": 0,
            "eligible_slot_targets": 0,
            "training_eligibility": "blocked_regime_unresolved",
        },
        "per_draw": [
            evidence_row("26001", "2026-01-01", 1, "primary_verified"),
            evidence_row("26002", "2026-01-02", 2, "primary_verified"),
            evidence_row("26003", "2026-01-03"),
        ],
    }
    return {
        **payload,
        "report_sha256": sha(canonical(payload)),
        "generated_at_utc": "2026-11-19T00:00:00+00:00",
    }


class ReportedSetIndexViewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.inventory = self.root / "inventory.jsonl"
        self.ledger = self.root / "observations.jsonl"
        self.coverage = self.root / "coverage.json"
        self.archive = self.root / "archive"
        self.archive.mkdir()
        self.inventory_raw = b"".join(
            (json.dumps(row, sort_keys=True) + "\n").encode()
            for row in inventory_rows()
        )
        self.ledger_raw = b'{"event_hash":"fixture"}\n'
        self.inventory.write_bytes(self.inventory_raw)
        self.ledger.write_bytes(self.ledger_raw)
        self.report = coverage_for(self.inventory_raw, self.ledger_raw)
        self.coverage.write_text(json.dumps(self.report), encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def build(self):
        with patch(
            "lottery.reported_set_index.build_ball_set_coverage",
            return_value={"report_sha256": self.report["report_sha256"]},
        ) as replay:
            result = build_reported_set_index_view(
                self.inventory, self.coverage, self.ledger, self.archive
            )
        replay.assert_called_once_with(
            self.inventory, self.ledger, self.archive, code_commit="a" * 40
        )
        return result

    def test_builds_only_primary_verified_reported_indices_and_keeps_physical_gate_blocked(self):
        rows, manifest = self.build()
        self.assertEqual(len(rows), 2)
        self.assertEqual([row["reported_set_index"] for row in rows], [1, 2])
        self.assertTrue(all(row["eligible_for_physical_model"] is False for row in rows))
        self.assertTrue(all(row["equipment_regime_id"] is None for row in rows))
        self.assertTrue(all(row["physical_ball_set_id"] is None for row in rows))
        self.assertTrue(all(row["training_eligibility"] == "blocked_regime_unresolved" for row in rows))
        self.assertEqual(manifest["set_index_counts"], {"1": 1, "2": 1, "3": 0})
        self.assertEqual(manifest["training_eligibility"], "blocked_regime_unresolved")
        self.assertEqual(manifest["physical_identity_claim"], "none")

    def test_versioned_artifact_is_write_once_and_idempotent(self):
        rows, manifest = self.build()
        output, sidecar = write_reported_set_index_view(rows, manifest, self.root / "out")
        original = output.read_bytes(), sidecar.read_bytes()
        output2, sidecar2 = write_reported_set_index_view(rows, manifest, self.root / "out")
        self.assertEqual((output2.read_bytes(), sidecar2.read_bytes()), original)
        self.assertEqual(output, output2)
        self.assertEqual(sidecar, sidecar2)
        output.write_bytes(b"tampered")
        with self.assertRaisesRegex(ReportedSetIndexError, "conflicts"):
            write_reported_set_index_view(rows, manifest, self.root / "out")

    def test_coverage_report_tampering_is_rejected_before_replay(self):
        self.report["summary"]["primary_verified_draws"] = 99
        self.coverage.write_text(json.dumps(self.report), encoding="utf-8")
        with patch("lottery.reported_set_index.build_ball_set_coverage") as replay:
            with self.assertRaisesRegex(ReportedSetIndexError, "coverage report SHA-256"):
                build_reported_set_index_view(
                    self.inventory, self.coverage, self.ledger, self.archive
                )
        replay.assert_not_called()

    def test_inventory_hash_mismatch_is_rejected(self):
        payload = {
            key: value for key, value in self.report.items()
            if key not in {"report_sha256", "generated_at_utc"}
        }
        payload["inventory_sha256"] = "0" * 64
        self.report = {
            **payload,
            "report_sha256": sha(canonical(payload)),
            "generated_at_utc": "2026-11-19T00:00:00+00:00",
        }
        self.coverage.write_text(json.dumps(self.report), encoding="utf-8")
        with self.assertRaisesRegex(ReportedSetIndexError, "different draw inventory"):
            self.build()

    def test_boolean_set_index_is_rejected(self):
        self.report["per_draw"][0]["reported_set_index"] = True
        payload = {
            key: value for key, value in self.report.items()
            if key not in {"report_sha256", "generated_at_utc"}
        }
        self.report["report_sha256"] = sha(canonical(payload))
        self.coverage.write_text(json.dumps(self.report), encoding="utf-8")
        with self.assertRaisesRegex(ReportedSetIndexError, "invalid reported set index"):
            self.build()

    def test_regime_assignment_is_not_silently_accepted(self):
        self.report["per_draw"][0]["physical_ball_set_id"] = "physical-set-1"
        payload = {
            key: value for key, value in self.report.items()
            if key not in {"report_sha256", "generated_at_utc"}
        }
        self.report["report_sha256"] = sha(canonical(payload))
        self.coverage.write_text(json.dumps(self.report), encoding="utf-8")
        with self.assertRaisesRegex(ReportedSetIndexError, "unexpected regime/identity assignment"):
            self.build()


if __name__ == "__main__":
    unittest.main()
