"""Append-only, hash-chained official provincial draw-result observations."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from typing import Any

from .ball_set_evidence import (
    BallSetEvidenceError, PARSER_VERSION, _allowed_url, _canonical_hash,
    parse_announcement,
)
from .ledger_lock import ledger_lock

DRAW_RESULT_SCHEMA = "lottery.official-draw-result/v1"
ZERO_HASH = "0" * 64
RESULT_STATUSES = {
    "inventory_matched", "pending_inventory", "draw_mismatch",
    "draw_result_mismatch", "missing_draw_result", "invalid_draw_result",
    "source_revision_same_semantics", "source_revision_requires_review",
    "conflict", "inventory_missing_after_match", "source_authority_unverified",
}


class DrawResultLedgerError(ValueError):
    """Raised when a draw-result evidence ledger is invalid."""


def read_draw_result_ledger(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records = []
    previous_hash = ZERO_HASH
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, 1):
            if not line.strip():
                raise DrawResultLedgerError(f"blank draw-result ledger line {line_no}")
            try:
                item = json.loads(line)
            except json.JSONDecodeError as exc:
                raise DrawResultLedgerError(f"invalid draw-result JSON at line {line_no}") from exc
            if not isinstance(item, dict) or item.get("schema_version") != DRAW_RESULT_SCHEMA:
                raise DrawResultLedgerError(f"unsupported draw-result record at line {line_no}")
            if item.get("prev_hash") != previous_hash:
                raise DrawResultLedgerError(f"draw-result hash chain broken at line {line_no}")
            event_hash = item.get("event_hash")
            event_body = {key: value for key, value in item.items() if key != "event_hash"}
            if not isinstance(event_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", event_hash):
                raise DrawResultLedgerError(f"invalid draw-result event hash at line {line_no}")
            if _canonical_hash(event_body) != event_hash:
                raise DrawResultLedgerError(f"draw-result event hash mismatch at line {line_no}")
            if (not isinstance(item.get("result_observation_id"), str)
                    or not re.fullmatch(r"[0-9a-f]{64}", item["result_observation_id"])
                    or not isinstance(item.get("draw_id"), str)
                    or not re.fullmatch(r"\d{5}", item["draw_id"])
                    or item.get("draw_result_status") not in RESULT_STATUSES):
                raise DrawResultLedgerError(f"invalid draw-result fields at line {line_no}")
            if item["draw_result_status"] in (
                "inventory_matched", "pending_inventory", "source_revision_same_semantics",
            ):
                if (not isinstance(item.get("front_numbers"), list)
                        or not isinstance(item.get("back_numbers"), list)
                        or len(item["front_numbers"]) != 5 or len(item["back_numbers"]) != 2):
                    raise DrawResultLedgerError(f"invalid draw-result number arrays at line {line_no}")
            source = item.get("source")
            if not isinstance(source, dict) or source.get("authority_class") != "A2":
                raise DrawResultLedgerError(f"invalid draw-result source authority at line {line_no}")
            for key in ("requested_url", "final_url"):
                if not isinstance(source.get(key), str):
                    raise DrawResultLedgerError(f"invalid draw-result source URL at line {line_no}")
                _allowed_url(source[key])
            if source.get("source_authority_class") != "A2":
                raise DrawResultLedgerError(f"invalid draw-result manifest authority at line {line_no}")
            for hop in source.get("redirect_chain", []):
                if not isinstance(hop, dict) or not isinstance(hop.get("url"), str):
                    raise DrawResultLedgerError(f"invalid draw-result redirect at line {line_no}")
                _allowed_url(hop["url"])
            if (not isinstance(source.get("body_sha256"), str)
                    or not re.fullmatch(r"[0-9a-f]{64}", source["body_sha256"])
                    or not source.get("raw_object_ref") or not source.get("manifest_object_ref")):
                raise DrawResultLedgerError(f"invalid draw-result raw evidence ref at line {line_no}")
            records.append(item)
            previous_hash = event_hash
    ids = [item["result_observation_id"] for item in records]
    if len(ids) != len(set(ids)):
        raise DrawResultLedgerError("duplicate draw-result observation IDs")
    return records


def append_draw_result(
    fetched: dict[str, Any], parsed: Any, manifest: dict[str, Any], *,
    inventory: dict[str, dict[str, Any]], inventory_sha256: str, ledger_path: Path,
) -> dict[str, Any]:
    source_url = fetched["final_url"]
    if not parsed.authority_footer_present:
        status = "source_authority_unverified"
    elif parsed.draw_result_status != "parsed":
        status = parsed.draw_result_status
    elif parsed.draw_id not in inventory:
        status = "pending_inventory"
    elif inventory[parsed.draw_id]["draw_date"] != parsed.draw_date:
        status = "draw_mismatch"
    elif (sorted(inventory[parsed.draw_id]["front_numbers"]) != list(parsed.front_numbers)
          or sorted(inventory[parsed.draw_id]["back_numbers"]) != list(parsed.back_numbers)):
        status = "draw_result_mismatch"
    else:
        status = "inventory_matched"
    crosswalk_status = status

    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    with ledger_lock(ledger_path):
        records = read_draw_result_ledger(ledger_path)
        previous = [
            item for item in records
            if item["draw_id"] == parsed.draw_id and item["source"]["final_url"] == source_url
        ]
        previous.sort(key=lambda item: item["source"]["retrieved_at_utc"])
        supersedes = previous[-1] if previous else None
        identity = {
            "draw_id": parsed.draw_id, "source_url": source_url,
            "body_sha256": manifest["body_sha256"], "parser_version": PARSER_VERSION,
        }
        result_id = _canonical_hash(identity)
        if supersedes and supersedes["source"]["body_sha256"] == manifest["body_sha256"]:
            return {"status": "duplicate_noop", "result_observation_id": supersedes["result_observation_id"]}
        if supersedes:
            same_result = (
                supersedes.get("draw_date") == parsed.draw_date
                and supersedes.get("front_numbers") == list(parsed.front_numbers or ())
                and supersedes.get("back_numbers") == list(parsed.back_numbers or ())
                and parsed.draw_result_status == "parsed"
                and parsed.authority_footer_present
                and status in ("inventory_matched", "pending_inventory")
                and supersedes.get("draw_result_status") not in (
                    "draw_result_mismatch", "draw_mismatch", "source_revision_requires_review", "conflict",
                )
            )
            status = "source_revision_same_semantics" if same_result else "source_revision_requires_review"
        else:
            other = [
                item for item in records if item["draw_id"] == parsed.draw_id
                and item.get("draw_result_status") in (
                    "inventory_matched", "pending_inventory", "source_revision_same_semantics",
                )
            ]
            if other and any(
                item.get("front_numbers") != list(parsed.front_numbers or ())
                or item.get("back_numbers") != list(parsed.back_numbers or ())
                for item in other
            ):
                status = "conflict"

        record = {
            "schema_version": DRAW_RESULT_SCHEMA,
            "result_observation_id": result_id,
            "draw_id": parsed.draw_id,
            "draw_date": parsed.draw_date,
            "front_numbers": list(parsed.front_numbers) if parsed.front_numbers is not None else None,
            "back_numbers": list(parsed.back_numbers) if parsed.back_numbers is not None else None,
            "draw_result_status": status,
            "source": {**manifest, "authority_class": "A2"},
            "parser": {
                "name": "dlt-official-draw-result",
                "version": PARSER_VERSION,
                "evidence_locator": {
                    "text_character_start": parsed.draw_result_evidence_start,
                    "text_character_end": parsed.draw_result_evidence_end,
                },
            },
            "inventory_crosswalk_at_capture": {
                "status": crosswalk_status,
                "inventory_sha256": inventory_sha256,
                "inventory_trust_status": "candidate_unverified",
            },
            "supersedes_result_observation_id": supersedes.get("result_observation_id") if supersedes else None,
        }
        record["prev_hash"] = records[-1]["event_hash"] if records else ZERO_HASH
        record["event_hash"] = _canonical_hash(record)
        with ledger_path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
            handle.flush()
            import os
            os.fsync(handle.fileno())
    return {"status": status, "result_observation_id": result_id}


def verify_draw_result_record(
    record: dict[str, Any], inventory_row: dict[str, Any] | None, archive_dir: Path,
) -> dict[str, Any]:
    source = record["source"]
    if record["draw_result_status"] in (
        "draw_result_mismatch", "draw_mismatch", "source_revision_requires_review",
        "conflict", "missing_draw_result", "invalid_draw_result", "source_authority_unverified",
    ):
        return {"status": record["draw_result_status"], "front_numbers": None, "back_numbers": None}
    if inventory_row is None and record.get("inventory_crosswalk_at_capture", {}).get("status") == "inventory_matched":
        return {"status": "inventory_missing_after_match", "front_numbers": None, "back_numbers": None}
    try:
        root = archive_dir.resolve()
        raw_path = (root / source["raw_object_ref"]).resolve()
        manifest_path = (root / source["manifest_object_ref"]).resolve()
        if not raw_path.is_relative_to(root) or not manifest_path.is_relative_to(root):
            raise DrawResultLedgerError("draw-result evidence path escapes archive")
        raw = raw_path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != source["body_sha256"] or len(raw) != source["body_byte_length"]:
            raise DrawResultLedgerError("draw-result raw object hash/length mismatch")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        expected_manifest = {
            key: value for key, value in source.items()
            if key not in ("authority_class", "manifest_object_ref")
        }
        if manifest != expected_manifest:
            raise DrawResultLedgerError("draw-result retrieval manifest mismatch")
        identity = {
            "draw_id": record["draw_id"], "source_url": source["final_url"],
            "body_sha256": source["body_sha256"], "parser_version": record.get("parser", {}).get("version"),
        }
        if _canonical_hash(identity) != record["result_observation_id"]:
            raise DrawResultLedgerError("draw-result observation identity mismatch")
        parsed = parse_announcement(raw, source["final_url"], source["content_type"])
    except (OSError, ValueError, BallSetEvidenceError, json.JSONDecodeError) as exc:
        return {"status": "raw_evidence_invalid", "front_numbers": None, "back_numbers": None}
    if not parsed.authority_footer_present:
        return {"status": "source_authority_unverified", "front_numbers": None, "back_numbers": None}
    if parsed.draw_id != record["draw_id"] or parsed.draw_date != record["draw_date"]:
        return {"status": "draw_mismatch", "front_numbers": None, "back_numbers": None}
    locator = record.get("parser", {}).get("evidence_locator", {})
    if (parsed.draw_result_status != "parsed"
            or list(parsed.front_numbers or ()) != record.get("front_numbers")
            or list(parsed.back_numbers or ()) != record.get("back_numbers")
            or locator.get("text_character_start") != parsed.draw_result_evidence_start
            or locator.get("text_character_end") != parsed.draw_result_evidence_end):
        return {"status": "invalid_draw_result", "front_numbers": None, "back_numbers": None}
    if inventory_row is None:
        return {
            "status": "pending_inventory",
            "front_numbers": list(parsed.front_numbers),
            "back_numbers": list(parsed.back_numbers),
        }
    if inventory_row["draw_date"] != parsed.draw_date:
        return {"status": "draw_mismatch", "front_numbers": None, "back_numbers": None}
    if (sorted(inventory_row["front_numbers"]) != list(parsed.front_numbers)
            or sorted(inventory_row["back_numbers"]) != list(parsed.back_numbers)):
        return {"status": "draw_result_mismatch", "front_numbers": None, "back_numbers": None}
    return {
        "status": "inventory_matched",
        "front_numbers": list(parsed.front_numbers),
        "back_numbers": list(parsed.back_numbers),
    }
