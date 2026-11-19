import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from lottery.append_only import AppendOnlyError, _atomic_write_new, reconcile_append_only


def row(draw_id, draw_date, front=None):
    return {
        "draw_id": draw_id,
        "draw_date": draw_date,
        "front_numbers": front or [1, 2, 3, 4, 5],
        "back_numbers": [1, 2],
        "source_id": "sha256:fixture",
        "front_draw_order": None,
        "back_draw_order": None,
        "source_unsort_drawresult": None,
        "source_equipment_count": None,
    }


def write_rows(path, rows):
    path.write_text(
        "".join(json.dumps(item, sort_keys=True) + "\n" for item in rows),
        encoding="utf-8",
    )


def write_manifest(candidate, manifest_path, snapshots_dir, page_size=100):
    rows = [
        json.loads(line)
        for line in candidate.read_text(encoding="utf-8").splitlines()
    ]
    snapshots_dir.mkdir(parents=True, exist_ok=True)
    total_pages = (len(rows) + page_size - 1) // page_size
    run_id = "fixture-fetch-run"
    snapshots = []
    pages = []
    source_ids = {}
    snapshot_hashes = []
    retrieved_at = "2026-11-19T15:00:00+00:00"

    for page_no in range(1, total_pages + 1):
        page_rows = rows[(page_no - 1) * page_size:page_no * page_size]
        items = [{
            "lotteryDrawNum": item["draw_id"],
            "lotteryDrawTime": item["draw_date"],
            "lotteryDrawResult": " ".join(
                str(number) for number in item["front_numbers"] + item["back_numbers"]
            ),
            "lotteryUnsortDrawresult": item.get("source_unsort_drawresult"),
            "lotteryEquipmentCount": item.get("source_equipment_count"),
        } for item in page_rows]
        raw_payload = {
            "success": True,
            "value": {
                "list": items,
                "total": len(rows),
                "totalPage": total_pages,
            },
        }
        raw = json.dumps(raw_payload, sort_keys=True).encode("utf-8")
        raw_file = f"page-{page_no:03d}.json"
        raw_path = snapshots_dir / raw_file
        raw_path.write_bytes(raw)
        digest = hashlib.sha256(raw).hexdigest()
        source_ids.update({item["draw_id"]: f"sha256:{digest}" for item in page_rows})
        source_url = (
            "https://webapi.sporttery.cn/gateway/lottery/getHistoryPageListV1.qry"
            f"?gameNo=85&provinceId=0&pageSize={page_size}&isVerify=1&pageNo={page_no}"
        )
        sidecar_name = f"{Path(raw_file).stem}.manifest.json"
        sidecar = {
            "source": "Sporttery public historical draw API",
            "url": source_url,
            "final_url": source_url,
            "redirect_chain": [],
            "http_status": 200,
            "content_type": "application/json",
            "sha256": digest,
            "bytes": len(raw),
            "raw_file": raw_file,
            "page_no": page_no,
            "run_id": run_id,
            "retrieved_at": retrieved_at,
        }
        (snapshots_dir / sidecar_name).write_text(
            json.dumps(sidecar, sort_keys=True), encoding="utf-8"
        )
        records = len(page_rows)
        snapshots.append({
            "raw_file": raw_file,
            "sha256": digest,
            "bytes": len(raw),
            "records": records,
            "page_no": page_no,
            "run_id": run_id,
            "sidecar_manifest": sidecar_name,
            "provenance_complete": True,
        })
        pages.append({
            "page_no": page_no,
            "raw_file": raw_file,
            "sha256": digest,
            "records": records,
        })
        snapshot_hashes.append(digest)

    for item in rows:
        item["source_id"] = source_ids[item["draw_id"]]
    write_rows(candidate, rows)
    attestation = {
        "schema": "sporttery-pagination-attestation-v1",
        "source_total_records": len(rows),
        "source_total_pages": total_pages,
        "page_size": page_size,
        "metadata_page_no": 1,
        "total_records_pointer": "/value/total",
        "total_pages_pointer": "/value/totalPage",
        "pages": pages,
    }
    manifest_path.write_text(json.dumps({
        "output_sha256": hashlib.sha256(candidate.read_bytes()).hexdigest(),
        "trust_status": "manifest_complete_not_officially_authenticated",
        "provenance_complete": True,
        "source_completeness_verified": True,
        "source_completeness_attestation": attestation,
        "snapshot_count": total_pages,
        "snapshot_sha256": snapshot_hashes,
        "snapshots": snapshots,
        "validation": {"records": len(rows)},
    }), encoding="utf-8")


class AppendOnlyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.current = self.root / "current.jsonl"
        self.candidate = self.root / "candidate.jsonl"
        self.manifest = self.root / "candidate.manifest.json"
        self.output = self.root / "published.jsonl"
        self.receipt = self.root / "receipt.json"
        self.snapshots_dir = self.root / "raw-snapshots"
        self.old = [
            row("26130", "2026-11-14"),
            row("26131", "2026-11-16"),
        ]
        write_rows(self.current, self.old)

    def tearDown(self):
        self.temp.cleanup()

    def prepare(self, rows, page_size=100):
        write_rows(self.candidate, rows)
        write_manifest(self.candidate, self.manifest, self.snapshots_dir, page_size)

    def run_gate(self):
        return reconcile_append_only(
            self.current, self.candidate, self.manifest,
            self.output, self.receipt, self.snapshots_dir,
        )

    def test_multi_page_attestation_checks_full_and_terminal_page_counts(self):
        self.prepare(self.old + [row("26132", "2026-11-18")], page_size=2)
        receipt = self.run_gate()
        self.assertEqual(receipt["status"], "appended")
        self.assertEqual(receipt["source_completeness_attestation"]["source_total_pages"], 2)
        self.assertEqual(len(receipt["source_completeness_attestation"]["verified_page_sha256"]), 2)

    def test_append_and_hash_receipt(self):
        self.prepare(self.old + [row("26132", "2026-11-18")])
        receipt = self.run_gate()
        self.assertEqual(receipt["status"], "appended")
        self.assertEqual(receipt["appended_draw_ids"], ["26132"])
        self.assertEqual(
            hashlib.sha256(self.output.read_bytes()).hexdigest(),
            receipt["output_sha256"],
        )

    def test_no_new_draw_is_idempotent_and_writes_no_output(self):
        self.prepare(self.old)
        receipt = self.run_gate()
        self.assertEqual(receipt["status"], "no_new_draws")
        self.assertFalse(self.output.exists())

    def test_missing_history_rejected(self):
        self.prepare([self.old[-1]])
        with self.assertRaisesRegex(AppendOnlyError, "not a full snapshot"):
            self.run_gate()

    def test_correction_rejected_without_overwrite(self):
        self.prepare([
            self.old[0],
            row("26131", "2026-11-16", [1, 2, 3, 4, 6]),
        ])
        with self.assertRaisesRegex(AppendOnlyError, "historical correction"):
            self.run_gate()
        self.assertFalse(self.output.exists())

    def test_chronology_regression_rejected(self):
        self.prepare([
            self.old[0],
            row("26129", "2026-11-15"),
            self.old[1],
        ])
        with self.assertRaisesRegex(AppendOnlyError, "not strictly after"):
            self.run_gate()

    def test_candidate_hash_mismatch_rejected(self):
        self.prepare(self.old)
        self.candidate.write_text(
            self.candidate.read_text().rstrip("\n") + " ",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(AppendOnlyError, "output_sha256"):
            self.run_gate()

    def test_incomplete_source_manifest_rejected(self):
        self.prepare(self.old + [row("26132", "2026-11-18")])
        manifest = json.loads(self.manifest.read_text(encoding="utf-8"))
        manifest["trust_status"] = "candidate_unverified"
        self.manifest.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(AppendOnlyError, "complete official-source"):
            self.run_gate()

    def test_boolean_completeness_flag_without_attestation_is_rejected(self):
        self.prepare(self.old + [row("26132", "2026-11-18")])
        manifest = json.loads(self.manifest.read_text(encoding="utf-8"))
        manifest.pop("source_completeness_attestation")
        self.manifest.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(AppendOnlyError, "attestation is missing"):
            self.run_gate()

    def test_raw_snapshot_hash_is_reverified_at_publication(self):
        self.prepare(self.old + [row("26132", "2026-11-18")])
        raw = self.snapshots_dir / "page-001.json"
        raw.write_bytes(raw.read_bytes() + b" ")
        with self.assertRaisesRegex(AppendOnlyError, "raw snapshot SHA-256 mismatch"):
            self.run_gate()

    def test_redirected_source_sidecar_is_rejected_at_publication(self):
        self.prepare(self.old + [row("26132", "2026-11-18")])
        raw = self.snapshots_dir / "page-001.json"
        sidecar = self.snapshots_dir / "page-001.manifest.json"
        metadata = json.loads(sidecar.read_text(encoding="utf-8"))
        metadata["redirect_chain"] = ["https://example.invalid/redirect-target"]
        sidecar.write_text(json.dumps(metadata), encoding="utf-8")
        with self.assertRaisesRegex(AppendOnlyError, "official-source sidecar provenance is invalid"):
            self.run_gate()

    def test_source_pagination_metadata_is_rechecked_from_raw_page(self):
        self.prepare(self.old + [row("26132", "2026-11-18")])
        manifest = json.loads(self.manifest.read_text(encoding="utf-8"))
        manifest["source_completeness_attestation"]["total_records_pointer"] = "/value/missing"
        self.manifest.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(AppendOnlyError, "metadata pointer does not resolve"):
            self.run_gate()

    def test_candidate_rows_must_match_raw_source_pages(self):
        rows = self.old + [row("26132", "2026-11-18")]
        self.prepare(rows)
        changed = rows[:-1] + [row("26132", "2026-11-18", [1, 2, 3, 4, 6])]
        manifest = json.loads(self.manifest.read_text(encoding="utf-8"))
        source_digest = manifest["source_completeness_attestation"]["pages"][0]["sha256"]
        for item in changed:
            item["source_id"] = f"sha256:{source_digest}"
        write_rows(self.candidate, changed)
        manifest["output_sha256"] = hashlib.sha256(self.candidate.read_bytes()).hexdigest()
        self.manifest.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(AppendOnlyError, "do not exactly reconcile"):
            self.run_gate()

    def test_unverified_source_pagination_is_rejected_even_with_complete_page_manifests(self):
        self.prepare(self.old + [row("26132", "2026-11-18")])
        manifest = json.loads(self.manifest.read_text(encoding="utf-8"))
        manifest["source_completeness_verified"] = False
        self.manifest.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(AppendOnlyError, "pagination completeness is not independently verified"):
            self.run_gate()

    def test_source_reference_change_is_not_a_result_correction(self):
        revised = [dict(item, source_id="sha256:new") for item in self.old]
        self.prepare(revised + [row("26132", "2026-11-18")])
        self.assertEqual(self.run_gate()["status"], "appended")
        published = [
            json.loads(line)
            for line in self.output.read_text(encoding="utf-8").splitlines()
        ]
        self.assertEqual(published[0]["source_id"], "sha256:fixture")

    def test_publication_must_not_write_into_immutable_raw_snapshot_directory(self):
        self.prepare(self.old + [row("26132", "2026-11-18")])
        with self.assertRaisesRegex(AppendOnlyError, "inside the raw snapshot directory"):
            reconcile_append_only(
                self.current, self.candidate, self.manifest,
                self.snapshots_dir / "published.jsonl",
                self.receipt, self.snapshots_dir,
            )

    def test_output_must_not_overwrite_current_dataset(self):
        self.prepare(self.old + [row("26132", "2026-11-18")])
        with self.assertRaisesRegex(AppendOnlyError, "paths must be distinct"):
            reconcile_append_only(
                self.current, self.candidate, self.manifest,
                self.current, self.receipt, self.snapshots_dir,
            )

    def test_receipt_must_not_overwrite_candidate_manifest(self):
        self.prepare(self.old)
        with self.assertRaisesRegex(AppendOnlyError, "paths must be distinct"):
            reconcile_append_only(
                self.current, self.candidate, self.manifest,
                self.output, self.manifest, self.snapshots_dir,
            )

    def test_unverified_source_completeness_cannot_claim_no_new_draws(self):
        self.prepare(self.old)
        manifest = json.loads(self.manifest.read_text(encoding="utf-8"))
        manifest["source_completeness_verified"] = False
        self.manifest.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(AppendOnlyError, "pagination completeness is not independently verified"):
            self.run_gate()
        self.assertFalse(self.output.exists())
        self.assertFalse(self.receipt.exists())

    def test_atomic_publication_primitive_never_clobbers_existing_path(self):
        target = self.root / "atomic.json"
        _atomic_write_new(target, b"first")
        with self.assertRaisesRegex(AppendOnlyError, "refusing to overwrite existing artifact"):
            _atomic_write_new(target, b"second")
        self.assertEqual(target.read_bytes(), b"first")
        self.assertEqual(list(self.root.glob("atomic.json.*.tmp")), [])

    def test_existing_publication_is_never_overwritten(self):
        self.prepare(self.old + [row("26132", "2026-11-18")])
        self.output.write_text("preserve-me", encoding="utf-8")
        with self.assertRaisesRegex(AppendOnlyError, "refusing to overwrite existing publication"):
            self.run_gate()
        self.assertEqual(self.output.read_text(encoding="utf-8"), "preserve-me")
        self.assertFalse(self.receipt.exists())

    def test_existing_receipt_is_never_overwritten(self):
        self.prepare(self.old + [row("26132", "2026-11-18")])
        self.receipt.write_text("preserve-me", encoding="utf-8")
        with self.assertRaisesRegex(AppendOnlyError, "refusing to overwrite existing receipt"):
            self.run_gate()
        self.assertEqual(self.receipt.read_text(encoding="utf-8"), "preserve-me")
        self.assertFalse(self.output.exists())

    def test_cli_help_imports_the_append_only_module(self):
        completed = subprocess.run(
            [sys.executable, "scripts/reconcile_draws.py", "--help"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("--candidate-manifest", completed.stdout)
        self.assertIn("--snapshots-dir", completed.stdout)
        self.assertIn("--current", completed.stdout)


if __name__ == "__main__":
    unittest.main()
