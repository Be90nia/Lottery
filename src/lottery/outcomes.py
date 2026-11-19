"""Post-draw outcome ledger and offline scoring for pre-draw forecasts.

Outcome records live in a separate hash chain. They never mutate the forecast
ledger. Provenance metadata is checked for consistency, not cryptographically
authenticated; archive the exact source snapshot and its hash independently.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import sys
from typing import Any
from urllib.parse import parse_qs, urlparse

from .backtest import _scores, FRONT_SIZE, FRONT_PICK, BACK_SIZE, BACK_PICK
from .ledger_lock import LedgerLockError, ledger_lock
from .forecast import (
    GENESIS_HASH,
    ForecastLedgerError,
    _event_hash,
    verify_ledger,
)

class OutcomeLedgerError(ValueError):
    """Raised when an outcome cannot safely be recorded or scored."""


_OUTCOME_EVENT_KEYS = {
    "event_type", "recorded_at", "target_draw_id", "forecast_event_hash",
    "published_at", "captured_at", "source_url", "source_http_status",
    "source_snapshot_sha256", "front_numbers", "back_numbers",
}


def _aware(value: str, field: str) -> datetime:
    if not isinstance(value, str):
        raise OutcomeLedgerError(f"{field} must be an ISO-8601 timestamp string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise OutcomeLedgerError(f"{field} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise OutcomeLedgerError(f"{field} must include a timezone")
    return parsed


def _read_events(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    events = []
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, 1):
            if not line.strip():
                raise OutcomeLedgerError(f"line {line_no}: blank lines are forbidden")
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                raise OutcomeLedgerError(f"line {line_no}: invalid JSON") from exc
            if not isinstance(event, dict):
                raise OutcomeLedgerError(f"line {line_no}: event must be an object")
            events.append(event)
    return events


def _validate_outcome_payload(event: dict[str, Any]) -> None:
    if not isinstance(event, dict) or set(event) != _OUTCOME_EVENT_KEYS:
        raise OutcomeLedgerError("outcome event has an invalid schema")
    if event.get("event_type") != "post_draw_outcome":
        raise OutcomeLedgerError("outcome event_type must be post_draw_outcome")
    target = event.get("target_draw_id")
    if not isinstance(target, str) or not target.strip() or target != target.strip():
        raise OutcomeLedgerError("outcome target_draw_id must be a non-empty trimmed string")
    forecast_hash = event.get("forecast_event_hash")
    if (not isinstance(forecast_hash, str) or len(forecast_hash) != 64
            or any(c not in "0123456789abcdef" for c in forecast_hash)):
        raise OutcomeLedgerError("forecast_event_hash must be a SHA-256 hex digest")
    publication = _aware(event.get("published_at", ""), "published_at")
    capture = _aware(event.get("captured_at", ""), "captured_at")
    recorded = _aware(event.get("recorded_at", ""), "recorded_at")
    if capture < publication:
        raise OutcomeLedgerError("capture timestamp precedes publication timestamp")
    if recorded < capture:
        raise OutcomeLedgerError("recorded_at precedes capture timestamp")
    source_url = event.get("source_url")
    if not isinstance(source_url, str):
        raise OutcomeLedgerError("source URL must be a string")
    parsed = urlparse(source_url)
    query = parse_qs(parsed.query)
    if (parsed.scheme != "https" or parsed.hostname != "webapi.sporttery.cn"
            or parsed.path != "/gateway/lottery/getHistoryPageListV1.qry"
            or query.get("gameNo") != ["85"]):
        raise OutcomeLedgerError("source URL must be the official Sporttery history endpoint for gameNo=85")
    if type(event.get("source_http_status")) is not int or event.get("source_http_status") != 200:
        raise OutcomeLedgerError("source HTTP status must be integer 200")
    digest = event.get("source_snapshot_sha256")
    if (not isinstance(digest, str) or len(digest) != 64
            or any(c not in "0123456789abcdef" for c in digest)):
        raise OutcomeLedgerError("source snapshot SHA-256 must be 64 lowercase hex characters")
    _validate_numbers(event.get("front_numbers"), FRONT_SIZE, FRONT_PICK, "front_numbers")
    _validate_numbers(event.get("back_numbers"), BACK_SIZE, BACK_PICK, "back_numbers")
    if event["front_numbers"] != sorted(event["front_numbers"]) or event["back_numbers"] != sorted(event["back_numbers"]):
        raise OutcomeLedgerError("outcome number arrays must be in canonical ascending order")


def _verify_chain(path: Path, event_type: str) -> dict[str, Any]:
    previous = GENESIS_HASH
    targets: set[str] = set()
    count = 0
    for line_no, event in enumerate(_read_events(path), 1):
        body = {k: v for k, v in event.items() if k != "event_hash"}
        supplied = event.get("event_hash")
        if body.get("event_type") != event_type:
            raise OutcomeLedgerError(f"line {line_no}: unexpected event type")
        if event_type == "post_draw_outcome":
            payload = {
                key: value for key, value in body.items()
                if key not in ("sequence", "previous_event_hash")
            }
            _validate_outcome_payload(payload)
        if body.get("sequence") != count + 1:
            raise OutcomeLedgerError(f"line {line_no}: sequence is not contiguous")
        if body.get("previous_event_hash") != previous:
            raise OutcomeLedgerError(f"line {line_no}: previous hash does not match")
        if not isinstance(supplied, str) or supplied != _event_hash(body):
            raise OutcomeLedgerError(f"line {line_no}: event hash mismatch")
        target = body.get("target_draw_id")
        if not isinstance(target, str) or not target or target in targets:
            raise OutcomeLedgerError(f"line {line_no}: missing or duplicate target draw id")
        targets.add(target)
        previous, count = supplied, count + 1
    return {"events": count, "last_event_hash": previous}


def _validate_forecast_link(event: dict[str, Any], forecasts: dict[str, dict[str, Any]]) -> None:
    forecast = forecasts.get(event["target_draw_id"])
    if forecast is None:
        raise OutcomeLedgerError(
            f"no pre-draw forecast exists for target {event['target_draw_id']}"
        )
    if forecast.get("event_hash") != event.get("forecast_event_hash"):
        raise OutcomeLedgerError(
            f"outcome {event['target_draw_id']} does not link to its forecast event"
        )
    if _aware(event["published_at"], "published_at") < _aware(
        forecast["target_draw_at"], "forecast target_draw_at"
    ):
        raise OutcomeLedgerError(
            f"outcome {event['target_draw_id']} was published before its target draw time"
        )


def verify_outcome_ledger(path: Path, forecast_path: Path | None = None) -> dict[str, Any]:
    state = _verify_chain(path, "post_draw_outcome")
    if forecast_path is not None:
        forecasts = _forecast_events(forecast_path)
        for event in _read_events(path):
            payload = {
                key: value for key, value in event.items()
                if key not in ("sequence", "previous_event_hash", "event_hash")
            }
            _validate_forecast_link(payload, forecasts)
    return state


def _validate_numbers(values: list[int], size: int, pick: int, field: str) -> None:
    if (not isinstance(values, list) or len(values) != pick
            or any(type(n) is not int or not 1 <= n <= size for n in values)
            or len(set(values)) != pick):
        raise OutcomeLedgerError(f"{field} must contain {pick} distinct integers in 1..{size}")


def _forecast_events(path: Path) -> dict[str, dict[str, Any]]:
    try:
        verify_ledger(path)
    except ForecastLedgerError as exc:
        raise OutcomeLedgerError(f"forecast ledger is invalid: {exc}") from exc
    events = _read_events(path)
    result = {}
    for line_no, event in enumerate(events, 1):
        if event.get("event_type") != "pre_draw_forecast":
            raise OutcomeLedgerError(f"forecast line {line_no}: unexpected event type")
        target = event.get("target_draw_id")
        models = event.get("models")
        if not isinstance(target, str) or not target or target in result:
            raise OutcomeLedgerError(f"forecast line {line_no}: invalid or duplicate target")
        if not isinstance(models, dict) or set(models) != {"uniform", "expanding", "ewma"}:
            raise OutcomeLedgerError(f"forecast line {line_no}: model set is invalid")
        for model, zones in models.items():
            if not isinstance(zones, dict):
                raise OutcomeLedgerError(f"forecast line {line_no}: {model} zones are invalid")
            for zone, size, pick in (("front_inclusion_probabilities", FRONT_SIZE, FRONT_PICK),
                                     ("back_inclusion_probabilities", BACK_SIZE, BACK_PICK)):
                probs = zones.get(zone)
                if (not isinstance(probs, list) or len(probs) != size
                        or any(type(p) not in (int, float) or not math.isfinite(p) or not 0 <= p <= 1
                               for p in probs)
                        or abs(sum(probs) - pick) > 1e-8):
                    raise OutcomeLedgerError(f"forecast line {line_no}: invalid {model} {zone}")
        result[target] = event
    return result


def create_outcome_event(
    forecast_path: Path, *, target_draw_id: str, published_at: str,
    captured_at: str, source_url: str, source_sha256: str, http_status: int,
    front_numbers: list[int], back_numbers: list[int],
    recorded_at: datetime | None = None,
) -> dict[str, Any]:
    forecasts = _forecast_events(forecast_path)
    forecast = forecasts.get(target_draw_id)
    if forecast is None:
        raise OutcomeLedgerError(f"no pre-draw forecast exists for target {target_draw_id}")
    publication = _aware(published_at, "published_at")
    capture = _aware(captured_at, "captured_at")
    if recorded_at is not None and not isinstance(recorded_at, datetime):
        raise OutcomeLedgerError("recorded_at must be a timezone-aware datetime")
    recorded = recorded_at or datetime.now(timezone.utc)
    if recorded.tzinfo is None or recorded.utcoffset() is None:
        raise OutcomeLedgerError("recorded_at must include a timezone")
    target_time = _aware(forecast["target_draw_at"], "forecast target_draw_at")
    if publication < target_time:
        raise OutcomeLedgerError("publication timestamp precedes target draw time")
    if capture < publication:
        raise OutcomeLedgerError("capture timestamp precedes publication timestamp")
    if recorded < capture:
        raise OutcomeLedgerError("recorded_at precedes capture timestamp")
    if not isinstance(source_url, str):
        raise OutcomeLedgerError("source URL must be a string")
    parsed = urlparse(source_url)
    query = parse_qs(parsed.query)
    if (parsed.scheme != "https" or parsed.hostname != "webapi.sporttery.cn"
            or parsed.path != "/gateway/lottery/getHistoryPageListV1.qry"
            or query.get("gameNo") != ["85"]):
        raise OutcomeLedgerError("source URL must be the official Sporttery history endpoint for gameNo=85")
    if type(http_status) is not int or http_status != 200:
        raise OutcomeLedgerError("source HTTP status must be integer 200")
    if not isinstance(source_sha256, str) or len(source_sha256) != 64 or any(
        c not in "0123456789abcdef" for c in source_sha256
    ):
        raise OutcomeLedgerError("source snapshot SHA-256 must be 64 lowercase hex characters")
    _validate_numbers(front_numbers, FRONT_SIZE, FRONT_PICK, "front_numbers")
    _validate_numbers(back_numbers, BACK_SIZE, BACK_PICK, "back_numbers")
    return {
        "event_type": "post_draw_outcome",
        "recorded_at": recorded.astimezone(timezone.utc).isoformat(),
        "target_draw_id": target_draw_id,
        "forecast_event_hash": forecast["event_hash"],
        "published_at": publication.isoformat(),
        "captured_at": capture.isoformat(),
        "source_url": source_url,
        "source_http_status": http_status,
        "source_snapshot_sha256": source_sha256,
        "front_numbers": sorted(front_numbers),
        "back_numbers": sorted(back_numbers),
    }



def create_outcome_event_from_snapshot(
    forecast_path: Path, *, target_draw_id: str, published_at: str,
    captured_at: str, source_url: str, snapshot_path: Path,
    http_status: int, recorded_at: datetime | None = None,
) -> dict[str, Any]:
    """Build an outcome only when the exact official response contains that draw."""
    if http_status != 200:
        raise OutcomeLedgerError("source HTTP status must be 200")
    parsed = urlparse(source_url)
    query = parse_qs(parsed.query)
    if (parsed.scheme != "https" or parsed.hostname != "webapi.sporttery.cn"
            or parsed.path != "/gateway/lottery/getHistoryPageListV1.qry"
            or query.get("gameNo") != ["85"]):
        raise OutcomeLedgerError("source URL must be the official Sporttery history endpoint for gameNo=85")
    raw = snapshot_path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    try:
        from .ingest import IngestionError, _parse_page
        rows = _parse_page(raw, 1, f"sha256:{digest}")
    except (IngestionError, ValueError) as exc:
        raise OutcomeLedgerError(f"official source snapshot failed parsing: {exc}") from exc
    matches = [row for row in rows if row.draw_id == target_draw_id]
    if len(matches) != 1:
        raise OutcomeLedgerError(
            f"snapshot must contain exactly one record for target {target_draw_id}; found {len(matches)}"
        )
    observed = matches[0]
    return create_outcome_event(
        forecast_path, target_draw_id=target_draw_id,
        published_at=published_at, captured_at=captured_at,
        source_url=source_url, source_sha256=digest, http_status=http_status,
        front_numbers=observed.front_numbers, back_numbers=observed.back_numbers,
        recorded_at=recorded_at,
    )

def append_outcome(
    path: Path, event: dict[str, Any], forecast_path: Path
) -> dict[str, Any]:
    _validate_outcome_payload(event)
    forecasts = _forecast_events(forecast_path)
    _validate_forecast_link(event, forecasts)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Lock before reading the chain: sequence, previous hash, duplicate check,
    # and append must be one cross-process transaction.
    with ledger_lock(path):
        state = verify_outcome_ledger(path, forecast_path)
        existing = {item.get("target_draw_id") for item in _read_events(path)}
        if event["target_draw_id"] in existing:
            raise OutcomeLedgerError(f"outcome already exists for target {event['target_draw_id']}")
        body = {"sequence": state["events"] + 1,
                "previous_event_hash": state["last_event_hash"], **event}
        record = {**body, "event_hash": _event_hash(body)}
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
            handle.flush()
            import os
            os.fsync(handle.fileno())
        return {"sequence": record["sequence"], "event_hash": record["event_hash"]}


def score_ledgers(forecast_path: Path, outcome_path: Path) -> dict[str, Any]:
    forecasts = _forecast_events(forecast_path)
    verify_outcome_ledger(outcome_path, forecast_path)
    outcomes = _read_events(outcome_path)
    scores = []
    for outcome in outcomes:
        target = outcome["target_draw_id"]
        forecast = forecasts.get(target)
        if forecast is None or forecast.get("event_hash") != outcome.get("forecast_event_hash"):
            raise OutcomeLedgerError(f"outcome {target} does not link to its forecast event")
        if _aware(outcome["published_at"], "published_at") < _aware(
            forecast["target_draw_at"], "forecast target_draw_at"
        ):
            raise OutcomeLedgerError(f"outcome {target} was published before its target draw time")
        zones = {}
        for model, probabilities in forecast["models"].items():
            front = _scores(probabilities["front_inclusion_probabilities"], outcome["front_numbers"])
            back = _scores(probabilities["back_inclusion_probabilities"], outcome["back_numbers"])
            zones[model] = {
                "front": {"brier_per_number": front[0], "log_loss_per_number": front[1], "top5_hits": front[2]},
                "back": {"brier_per_number": back[0], "log_loss_per_number": back[1], "top2_hits": back[2]},
            }
        scores.append({"target_draw_id": target, "forecast_event_hash": forecast["event_hash"],
                       "outcome_event_hash": outcome["event_hash"], "models": zones})
    return {
        "status": "per-draw descriptive scores only; no interim model ranking or holdout conclusion",
        "scored_draws": len(scores),
        "scores": scores,
    }


def _numbers(value: str) -> list[int]:
    try:
        return [int(part) for part in value.split(",")]
    except ValueError as exc:
        raise argparse.ArgumentTypeError("numbers must be comma-separated integers") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    record = sub.add_parser("record", help="record a published outcome against a pre-draw forecast")
    record.add_argument("--forecasts", type=Path, required=True)
    record.add_argument("--outcomes", type=Path, default=Path("data/holdout/outcome-ledger.jsonl"))
    record.add_argument("--target-draw-id", required=True)
    record.add_argument("--published-at", required=True)
    record.add_argument("--captured-at", required=True)
    record.add_argument("--source-url", required=True)
    record.add_argument("--snapshot", type=Path, required=True, help="exact raw response snapshot bytes")
    record.add_argument("--http-status", type=int, required=True)
    record.add_argument("--front", type=_numbers, required=True)
    record.add_argument("--back", type=_numbers, required=True)
    verify = sub.add_parser("verify", help="verify outcome ledger hash chain and optional forecast links")
    verify.add_argument("outcomes", type=Path)
    verify.add_argument("--forecasts", type=Path)
    score = sub.add_parser("score", help="score linked forecast/outcome ledgers offline")
    score.add_argument("--forecasts", type=Path, required=True)
    score.add_argument("--outcomes", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "verify":
            result = verify_outcome_ledger(args.outcomes, args.forecasts)
        elif args.command == "score":
            result = score_ledgers(args.forecasts, args.outcomes)
        else:
            raw = args.snapshot.read_bytes()
            event = create_outcome_event_from_snapshot(
                args.forecasts, target_draw_id=args.target_draw_id,
                published_at=args.published_at, captured_at=args.captured_at,
                source_url=args.source_url, snapshot_path=args.snapshot,
                http_status=args.http_status,
            )
            if sorted(args.front) != event["front_numbers"] or sorted(args.back) != event["back_numbers"]:
                raise OutcomeLedgerError("CLI numbers do not match the selected result in the raw source snapshot")
            result = append_outcome(args.outcomes, event, args.forecasts)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError, LedgerLockError) as exc:
        print(f"OUTCOME_LEDGER_FAILED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
