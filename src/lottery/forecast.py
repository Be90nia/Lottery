"""Pre-draw probability forecast records for the prospective holdout.

The ledger is append-only by convention and hash-chained to expose accidental
edits, truncation, reordering, or duplicate target records. It is not a digital
signature and cannot prove who created a record.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import sys
from typing import Any

from .validate import validate_records
from .ledger_lock import LedgerLockError, ledger_lock
from .backtest import (
    DEFAULT_ALPHA,
    FRONT_SIZE,
    FRONT_PICK,
    BACK_SIZE,
    BACK_PICK,
    _probabilities,
    _validate_rows,
)

GENESIS_HASH = "0" * 64
CODE_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")


class ForecastLedgerError(ValueError):
    """Raised when a forecast cannot safely be added or verified."""


def _canonical_json(value: dict[str, Any]) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _event_hash(event_without_hash: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(event_without_hash)).hexdigest()


def _aware_timestamp(value: Any, field: str) -> datetime:
    if not isinstance(value, str):
        raise ForecastLedgerError(f"{field} must be an ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ForecastLedgerError(f"{field} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ForecastLedgerError(f"{field} must include a timezone")
    return parsed


def _validate_forecast_payload(event: dict[str, Any]) -> None:
    payload_keys = {
        "event_type", "generated_at", "target_draw_id", "target_draw_at",
        "training_dataset_sha256", "training_draw_count",
        "training_first_draw_id", "training_last_draw_id", "code_commit",
        "model_configuration", "models",
    }
    allowed_keys = payload_keys | {"sequence", "previous_event_hash"}
    if not isinstance(event, dict) or not payload_keys.issubset(event) or set(event) - allowed_keys:
        raise ForecastLedgerError("forecast event has an invalid or incomplete schema")
    if event.get("event_type") != "pre_draw_forecast":
        raise ForecastLedgerError("forecast event_type must be pre_draw_forecast")
    target = event.get("target_draw_id")
    if not isinstance(target, str) or not target.strip():
        raise ForecastLedgerError("target_draw_id must be a non-empty string")
    generated = _aware_timestamp(event.get("generated_at"), "generated_at")
    target_time = _aware_timestamp(event.get("target_draw_at"), "target_draw_at")
    if generated >= target_time:
        raise ForecastLedgerError("forecast must be generated strictly before target draw time")
    digest = event.get("training_dataset_sha256")
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ForecastLedgerError("training dataset SHA-256 must be 64 lowercase hex characters")
    commit = event.get("code_commit")
    if not isinstance(commit, str) or not CODE_COMMIT_RE.fullmatch(commit):
        raise ForecastLedgerError("code commit must be a full 40-character lowercase Git SHA")
    count = event.get("training_draw_count")
    if type(count) is not int or count < 1:
        raise ForecastLedgerError("training_draw_count must be a positive integer")
    for field in ("training_first_draw_id", "training_last_draw_id"):
        value = event.get(field)
        if not isinstance(value, str) or not value.strip():
            raise ForecastLedgerError(f"{field} must be a non-empty string")
    if event["training_first_draw_id"] > event["training_last_draw_id"]:
        raise ForecastLedgerError("training draw ID range is reversed")

    configuration = event.get("model_configuration")
    if not isinstance(configuration, dict) or set(configuration) != {
        "expanding_alpha", "ewma_half_life_draws"
    }:
        raise ForecastLedgerError("model_configuration schema is invalid")
    for field in ("expanding_alpha", "ewma_half_life_draws"):
        value = configuration[field]
        if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
            raise ForecastLedgerError(f"model_configuration {field} must be finite and positive")

    models = event.get("models")
    if not isinstance(models, dict) or set(models) != {"uniform", "expanding", "ewma"}:
        raise ForecastLedgerError("forecast models must be exactly uniform, expanding, and ewma")
    for model_name, zones in models.items():
        if not isinstance(zones, dict) or set(zones) != {
            "front_inclusion_probabilities", "back_inclusion_probabilities"
        }:
            raise ForecastLedgerError(f"{model_name} probability zones are invalid")
        for field, size, pick in (
            ("front_inclusion_probabilities", FRONT_SIZE, FRONT_PICK),
            ("back_inclusion_probabilities", BACK_SIZE, BACK_PICK),
        ):
            probabilities = zones[field]
            if (
                not isinstance(probabilities, list)
                or len(probabilities) != size
                or any(
                    type(value) not in (int, float)
                    or not math.isfinite(value)
                    or not 0.0 <= value <= 1.0
                    for value in probabilities
                )
                or abs(sum(probabilities) - pick) > 1e-8
            ):
                raise ForecastLedgerError(f"invalid {model_name} {field}")


def verify_ledger(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"events": 0, "last_event_hash": GENESIS_HASH}
    previous_hash = GENESIS_HASH
    target_ids: set[str] = set()
    count = 0
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            if not line.strip():
                raise ForecastLedgerError(f"line {line_no}: blank ledger lines are forbidden")
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ForecastLedgerError(f"line {line_no}: invalid JSON") from exc
            if not isinstance(event, dict):
                raise ForecastLedgerError(f"line {line_no}: event must be an object")
            supplied_hash = event.get("event_hash")
            body = {key: value for key, value in event.items() if key != "event_hash"}
            if type(body.get("sequence")) is not int or body.get("sequence") != count + 1:
                raise ForecastLedgerError(f"line {line_no}: sequence is not a contiguous integer")
            if body.get("previous_event_hash") != previous_hash:
                raise ForecastLedgerError(f"line {line_no}: previous hash does not match")
            if not isinstance(supplied_hash, str) or supplied_hash != _event_hash(body):
                raise ForecastLedgerError(f"line {line_no}: event hash mismatch")
            try:
                _validate_forecast_payload(body)
            except ForecastLedgerError as exc:
                raise ForecastLedgerError(f"line {line_no}: {exc}") from exc
            target_id = body.get("target_draw_id")
            if not isinstance(target_id, str) or not target_id:
                raise ForecastLedgerError(f"line {line_no}: missing target draw id")
            if target_id in target_ids:
                raise ForecastLedgerError(f"line {line_no}: duplicate target draw id {target_id}")
            target_ids.add(target_id)
            previous_hash = supplied_hash
            count += 1
    return {"events": count, "last_event_hash": previous_hash}


def create_forecast_event(
    rows: list[dict[str, Any]],
    *,
    target_draw_id: str,
    target_draw_at: str,
    training_sha256: str,
    code_commit: str,
    generated_at: datetime | None = None,
    alpha: float = DEFAULT_ALPHA,
    half_life: float = 100.0,
) -> dict[str, Any]:
    records = _validate_rows(rows)
    validate_records(records)
    if not isinstance(target_draw_id, str) or not target_draw_id.strip():
        raise ForecastLedgerError("target draw id must not be a non-empty string")
    if not isinstance(training_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", training_sha256):
        raise ForecastLedgerError("training dataset SHA-256 must be 64 lowercase hex characters")
    if not isinstance(code_commit, str) or not CODE_COMMIT_RE.fullmatch(code_commit):
        raise ForecastLedgerError("code commit must be a full 40-character lowercase Git SHA")
    if (
        type(alpha) not in (int, float) or not math.isfinite(alpha) or alpha <= 0
        or type(half_life) not in (int, float) or not math.isfinite(half_life) or half_life <= 0
    ):
        raise ForecastLedgerError("alpha and half-life must be finite positive numbers")

    target_time = _aware_timestamp(target_draw_at, "target draw timestamp")
    now = generated_at or datetime.now(timezone.utc)
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ForecastLedgerError("generated_at must include a timezone")
    if target_time <= now:
        raise ForecastLedgerError("target draw must be strictly in the future at forecast creation")
    latest_training_date = datetime.fromisoformat(records[-1]["draw_date"]).date()
    if target_time.date() <= latest_training_date:
        raise ForecastLedgerError("target draw date must be later than every training draw date")

    models: dict[str, Any] = {}
    for model in ("uniform", "expanding", "ewma"):
        models[model] = {
            "front_inclusion_probabilities": _probabilities(
                records, "front_numbers", FRONT_SIZE, FRONT_PICK,
                model=model, alpha=alpha, half_life=half_life,
            ),
            "back_inclusion_probabilities": _probabilities(
                records, "back_numbers", BACK_SIZE, BACK_PICK,
                model=model, alpha=alpha, half_life=half_life,
            ),
        }
    for model, zones in models.items():
        if abs(sum(zones["front_inclusion_probabilities"]) - FRONT_PICK) > 1e-9:
            raise ForecastLedgerError(f"{model} front probability mass is invalid")
        if abs(sum(zones["back_inclusion_probabilities"]) - BACK_PICK) > 1e-9:
            raise ForecastLedgerError(f"{model} back probability mass is invalid")

    return {
        "event_type": "pre_draw_forecast",
        "generated_at": now.astimezone(timezone.utc).isoformat(),
        "target_draw_id": target_draw_id,
        "target_draw_at": target_time.isoformat(),
        "training_dataset_sha256": training_sha256,
        "training_draw_count": len(records),
        "training_first_draw_id": records[0]["draw_id"],
        "training_last_draw_id": records[-1]["draw_id"],
        "code_commit": code_commit,
        "model_configuration": {"expanding_alpha": alpha, "ewma_half_life_draws": half_life},
        "models": models,
    }


def append_forecast(
    ledger_path: Path,
    event: dict[str, Any],
) -> dict[str, Any]:
    _validate_forecast_payload(event)
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    # Serialize the complete read/verify/deduplicate/append transaction.
    with ledger_lock(ledger_path):
        state = verify_ledger(ledger_path)
        if any(
            json.loads(line).get("target_draw_id") == event["target_draw_id"]
            for line in ledger_path.read_text(encoding="utf-8").splitlines()
        ) if ledger_path.exists() else False:
            raise ForecastLedgerError(f"forecast already exists for target {event['target_draw_id']}")
        body = {
            "sequence": state["events"] + 1,
            "previous_event_hash": state["last_event_hash"],
            **event,
        }
        record = {**body, "event_hash": _event_hash(body)}
        with ledger_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
            handle.flush()
            import os
            os.fsync(handle.fileno())
        return {"sequence": record["sequence"], "event_hash": record["event_hash"]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    create = subparsers.add_parser("create", help="record a pre-draw forecast")
    create.add_argument("dataset", type=Path)
    create.add_argument("--target-draw-id", required=True)
    create.add_argument("--target-draw-at", required=True, help="ISO-8601 timestamp including timezone")
    create.add_argument("--code-commit", required=True, help="full 40-character Git commit SHA")
    create.add_argument("--ledger", type=Path, default=Path("data/holdout/forecast-ledger.jsonl"))
    create.add_argument("--alpha", type=float, default=DEFAULT_ALPHA)
    create.add_argument("--half-life", type=float, default=100.0)
    verify = subparsers.add_parser("verify", help="verify the forecast ledger hash chain")
    verify.add_argument("ledger", type=Path)
    args = parser.parse_args()

    try:
        if args.command == "verify":
            result = verify_ledger(args.ledger)
        else:
            raw = args.dataset.read_bytes()
            rows = [json.loads(line) for line in raw.decode("utf-8").splitlines()]
            event = create_forecast_event(
                rows,
                target_draw_id=args.target_draw_id,
                target_draw_at=args.target_draw_at,
                training_sha256=hashlib.sha256(raw).hexdigest(),
                code_commit=args.code_commit,
                alpha=args.alpha,
                half_life=args.half_life,
            )
            result = append_forecast(args.ledger, event)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError, LedgerLockError) as exc:
        print(f"FORECAST_LEDGER_FAILED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
