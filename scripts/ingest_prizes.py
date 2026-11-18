#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Lossless extraction of Sporttery prizeLevelList objects.

This command does not normalize prize labels or calculate payouts. It preserves
the complete source object and adds immutable snapshot provenance plus a stable
occurrence/content fingerprint.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_manifest(path: Path) -> dict[str, Any]:
    obj = json.loads(path.read_text(encoding="utf-8"))
    required = (
        "source", "url", "retrieved_at", "http_status",
        "content_type", "sha256", "raw_file", "parser_version",
    )
    missing = [k for k in required if k not in obj]
    if missing:
        raise ValueError(f"{path.name}: missing manifest fields: {missing}")
    return obj


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw-dir", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--report", type=Path, required=True)
    args = ap.parse_args()

    raw_dir = args.raw_dir
    raw_files = sorted(
        p for p in raw_dir.glob("page-*.json")
        if not p.name.endswith(".manifest.json")
    )
    if not raw_files:
        raise SystemExit("no page JSON files found")

    records: list[dict[str, Any]] = []
    report: dict[str, Any] = {
        "schema": "sporttery-prizes-raw/v1",
        "raw_dir": str(raw_dir),
        "input_pages": 0,
        "draw_count": 0,
        "prize_count": 0,
        "missing_prize_list": [],
        "empty_prize_list": [],
        "invalid_prize_entries": [],
        "duplicate_content_fingerprints": {},
    }
    seen_draws: set[str] = set()
    fp_occurrences: dict[str, list[str]] = {}

    for raw_path in raw_files:
        manifest_path = raw_path.with_name(raw_path.name.removesuffix(".json") + ".manifest.json")
        if not manifest_path.exists():
            raise SystemExit(f"missing sidecar: {manifest_path.name}")
        manifest = load_manifest(manifest_path)
        raw = raw_path.read_bytes()
        digest = sha256_bytes(raw)
        if digest != manifest["sha256"]:
            raise SystemExit(f"SHA-256 mismatch: {raw_path.name}")
        if manifest["raw_file"] != raw_path.name:
            raise SystemExit(f"manifest raw_file mismatch: {manifest_path.name}")
        if manifest["http_status"] != 200:
            raise SystemExit(f"non-200 snapshot: {raw_path.name}")

        payload = json.loads(raw.decode("utf-8-sig"))
        value = payload.get("value")
        if not isinstance(value, dict) or not isinstance(value.get("list"), list):
            raise SystemExit(f"invalid value.list: {raw_path.name}")

        report["input_pages"] += 1
        for draw_index, draw in enumerate(value["list"]):
            if not isinstance(draw, dict):
                raise SystemExit(f"non-object draw at {raw_path.name}:{draw_index}")

            draw_id = str(draw.get("lotteryDrawNum", "")).strip()
            if not draw_id:
                raise SystemExit(f"missing draw ID at {raw_path.name}:{draw_index}")
            if draw_id in seen_draws:
                raise SystemExit(f"duplicate draw ID: {draw_id}")
            seen_draws.add(draw_id)
            report["draw_count"] += 1

            if "prizeLevelList" not in draw:
                report["missing_prize_list"].append(draw_id)
                continue
            prize_list = draw["prizeLevelList"]
            if not isinstance(prize_list, list):
                raise SystemExit(f"prizeLevelList is not a list: {draw_id}")
            if not prize_list:
                report["empty_prize_list"].append(draw_id)
                continue

            for prize_index, prize in enumerate(prize_list):
                if not isinstance(prize, dict):
                    report["invalid_prize_entries"].append(
                        {"draw_id": draw_id, "prize_index": prize_index}
                    )
                    raise SystemExit(f"non-object prize entry: {draw_id}:{prize_index}")

                fp = sha256_bytes(canonical_json(prize))
                occurrence = f"{digest}:{draw_id}:{draw_index}:{prize_index}"
                row_id = sha256_bytes(occurrence.encode("utf-8"))
                fp_occurrences.setdefault(fp, []).append(occurrence)

                records.append({
                    "record_schema": "sporttery-prize-raw/v1",
                    "draw_id": draw_id,
                    "draw_date": str(draw.get("lotteryDrawTime", "")).strip(),
                    "source": {
                        "source_name": manifest["source"],
                        "source_url": manifest["url"],
                        "retrieved_at": manifest["retrieved_at"],
                        "http_status": manifest["http_status"],
                        "content_type": manifest["content_type"],
                        "snapshot_sha256": digest,
                        "raw_file": raw_path.name,
                        "parser_version": manifest["parser_version"],
                    },
                    "source_position": {
                        "draw_index": draw_index,
                        "prize_index": prize_index,
                    },
                    "raw_prize": prize,
                    "raw_prize_sha256": fp,
                    "row_id": row_id,
                })

    report["prize_count"] = len(records)
    report["duplicate_content_fingerprints"] = {
        fp: occ for fp, occ in fp_occurrences.items() if len(occ) > 1
    }
    if report["missing_prize_list"] or report["empty_prize_list"] or report["invalid_prize_entries"]:
        raise SystemExit(
            "prize coverage validation failed; see report fields for gaps"
        )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="\n") as fh:
        for row in records:
            fh.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"pages={report['input_pages']} draws={report['draw_count']} prizes={report['prize_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
