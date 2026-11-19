"""Export reviewed, inventory-pending official draw results as candidate-only JSONL."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any

from lottery.ball_set_coverage import build_ball_set_coverage
from lottery.ball_set_evidence import _canonical_hash, _read_ledger
from lottery.draw_results import read_draw_result_ledger


def _atomic_write(path: Path, data: bytes, protected: set[Path]) -> None:
    resolved = path.resolve()
    if resolved in protected:
        raise ValueError("candidate output would overwrite an input")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def build_candidate_export(
    draw_inventory_path: Path, observation_ledger_path: Path,
    draw_result_ledger_path: Path, archive_dir: Path, *, code_commit: str = "local",
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    report = build_ball_set_coverage(
        draw_inventory_path, observation_ledger_path, draw_result_ledger_path,
        archive_dir, code_commit=code_commit,
    )
    observations = _read_ledger(observation_ledger_path)
    result_records = read_draw_result_ledger(draw_result_ledger_path)
    result_by_id = {item["result_observation_id"]: item for item in result_records}
    label_rows = report["out_of_inventory_observations"]
    blocked_label_statuses = {
        "conflict", "source_revision_requires_review", "draw_mismatch",
        "source_authority_unverified", "parse_error", "unsupported_label", "missing_official_label",
    }
    candidates_by_draw: dict[str, list[dict[str, Any]]] = {}
    excluded: dict[str, int] = {}

    def exclude(reason: str) -> None:
        excluded[reason] = excluded.get(reason, 0) + 1

    for result_row in report["out_of_inventory_draw_results"]:
        if result_row["draw_result_status"] != "pending_inventory" or not result_row["raw_evidence_verified"]:
            exclude(result_row["draw_result_status"])
            continue
        result_record = result_by_id.get(result_row["result_observation_id"])
        if not result_record:
            exclude("result_record_missing")
            continue
        source = result_record["source"]
        matching_labels = [
            item for item in label_rows
            if item["draw_id"] == result_row["draw_id"]
            and item.get("source_url") == source.get("final_url")
            and item.get("body_sha256") == source.get("body_sha256")
            and item.get("observation_status") == "official_label_pending_inventory"
            and item.get("reported_set_index") in (1, 2, 3)
        ]
        if len(matching_labels) != 1:
            exclude("matching_explicit_ball_set_label_missing_or_ambiguous")
            continue
        draw_labels = [item for item in label_rows if item["draw_id"] == result_row["draw_id"]]
        if any(item.get("observation_status") in blocked_label_statuses for item in draw_labels):
            exclude("ball_set_label_review_required")
            continue
        label = matching_labels[0]
        candidate_body = {
            "schema_version": "lottery.official-draw-result-candidate/v1",
            "draw_id": result_row["draw_id"],
            "draw_date": result_row["draw_date"],
            "front_numbers": result_row["front_numbers"],
            "back_numbers": result_row["back_numbers"],
            "ball_set_index": label["reported_set_index"],
            "draw_result_observation_id": result_record["result_observation_id"],
            "ball_set_observation_id": label["observation_id"],
            "source": {
                "authority_class": source["authority_class"],
                "final_url": source["final_url"],
                "retrieved_at_utc": source["retrieved_at_utc"],
                "body_sha256": source["body_sha256"],
                "raw_object_ref": source["raw_object_ref"],
                "manifest_object_ref": source["manifest_object_ref"],
            },
            "inventory_sha256": report["inventory_sha256"],
            "inventory_trust_status": report["inventory_trust_status"],
            "candidate_trust_status": "official_A2_provincial_candidate_pending_inventory_review",
            "canonical_mutation": False,
            "model_training": False,
            "holdout_access": False,
        }
        candidate_body["candidate_id"] = _canonical_hash(candidate_body)
        candidates_by_draw.setdefault(result_row["draw_id"], []).append(candidate_body)

    candidates: list[dict[str, Any]] = []
    for draw_id, rows in sorted(candidates_by_draw.items()):
        semantic_keys = {
            (
                row["draw_date"], tuple(row["front_numbers"]), tuple(row["back_numbers"]),
                row["ball_set_index"],
            )
            for row in rows
        }
        if len(semantic_keys) != 1:
            exclude("conflicting_candidate_versions")
            continue
        rows.sort(key=lambda row: row["source"]["retrieved_at_utc"])
        candidates.append(rows[-1])

    receipt = {
        "schema_version": "lottery.official-draw-result-candidate-receipt/v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "inventory_sha256": report["inventory_sha256"],
        "inventory_trust_status": report["inventory_trust_status"],
        "observation_ledger_sha256": report["observation_ledger_sha256"],
        "draw_result_ledger_sha256": report["draw_result_ledger_sha256"],
        "source_completeness_verified": report["source_completeness_verified"],
        "candidate_count": len(candidates),
        "candidate_ids": [item["candidate_id"] for item in candidates],
        "excluded_counts": excluded,
        "trust_status": "candidate_only",
        "canonical_mutation": False,
        "model_training": False,
        "holdout_access": False,
    }
    return candidates, receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--draw-inventory", type=Path, required=True)
    parser.add_argument("--observation-ledger", type=Path, required=True)
    parser.add_argument("--draw-result-ledger", type=Path, required=True)
    parser.add_argument("--archive-dir", type=Path, required=True)
    parser.add_argument("--output-jsonl", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--code-commit", default=os.environ.get("GITHUB_SHA", "local"))
    args = parser.parse_args()

    try:
        candidates, receipt = build_candidate_export(
            args.draw_inventory, args.observation_ledger, args.draw_result_ledger,
            args.archive_dir, code_commit=args.code_commit,
        )
        jsonl = "".join(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n" for item in candidates).encode("utf-8")
        receipt["candidate_file_sha256"] = hashlib.sha256(jsonl).hexdigest()
        protected = {
            args.draw_inventory.resolve(), args.observation_ledger.resolve(),
            args.draw_result_ledger.resolve(), (args.archive_dir / "receipt.json").resolve(),
        }
        _atomic_write(args.output_jsonl, jsonl, protected)
        _atomic_write(
            args.receipt,
            (json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8"),
            protected | {args.output_jsonl.resolve()},
        )
        print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
        return 0
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "failed_closed", "error": str(exc)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
