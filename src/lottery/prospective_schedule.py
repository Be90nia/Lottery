"""Pre-register and cutoff-finalize a frozen prospective forecast schedule.

This is an idempotent command runner for an external trusted scheduler. It does
not discover Champion state, load models, issue forecasts, or authorize serving.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import tempfile
from typing import Any, Callable

from lottery.subset_model.artifact import canonicalize
from .prospective import ProspectiveLedger, ProspectiveLedgerError

SCHEDULE_SCHEMA = "lottery.prospective-schedule/v1"
REQUIRED_FIELDS = {
    "target_draw_id", "target_draw_at_utc", "target_cutoff_utc",
    "target_cutoff_timezone_source", "expected_at_utc", "zone",
    "population_key", "front_artifact_sha256", "back_artifact_sha256",
    "active_registry_snapshot_id", "lifecycle_state", "model_spec_sha256",
    "training_snapshot_sha256", "training_first_draw_id", "training_last_draw_id",
    "training_row_count", "training_last_draw_date", "registry_generation",
    "forecast_policy_version", "scoring_policy_version", "model_family",
    "code_commit", "runtime",
}
OPTIONAL_FIELDS = {"source_evidence_manifest_sha256"}


class ScheduleError(ValueError):
    """Invalid immutable schedule or failed schedule execution."""


def _aware(value: Any, field: str) -> datetime:
    if not isinstance(value, str):
        raise ScheduleError(f"{field} must be an ISO-8601 timestamp")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ScheduleError(f"{field} must be an ISO-8601 timestamp") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise ScheduleError(f"{field} must include a timezone")
    return result.astimezone(timezone.utc)


def _schedule_digest(schedule: dict[str, Any]) -> str:
    body = {key: value for key, value in schedule.items() if key != "schedule_id"}
    return "sha256:" + hashlib.sha256(canonicalize(body)).hexdigest()


def validate_schedule(schedule: Any) -> list[dict[str, Any]]:
    if not isinstance(schedule, dict) or schedule.get("schema") != SCHEDULE_SCHEMA:
        raise ScheduleError(f"schedule schema must be {SCHEDULE_SCHEMA}")
    if schedule.get("schedule_id") != _schedule_digest(schedule):
        raise ScheduleError("schedule_id does not match canonical schedule content")
    _aware(schedule.get("generated_at_utc"), "generated_at_utc")
    records = schedule.get("expected_forecasts")
    if not isinstance(records, list) or not records:
        raise ScheduleError("expected_forecasts must be a non-empty array")
    seen = set()
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            raise ScheduleError(f"schedule record {index} must be an object")
        keys = set(record)
        if not REQUIRED_FIELDS <= keys or keys - REQUIRED_FIELDS - OPTIONAL_FIELDS:
            raise ScheduleError(f"schedule record {index} has missing or unknown fields")
        key = (
            record["front_artifact_sha256"], record["back_artifact_sha256"],
            record["target_draw_id"], record["zone"], record["population_key"],
            record["forecast_policy_version"], record["active_registry_snapshot_id"],
            record["registry_generation"],
        )
        if key in seen:
            raise ScheduleError(f"duplicate expected forecast slot at record {index}")
        seen.add(key)
        cutoff = _aware(record["target_cutoff_utc"], "target_cutoff_utc")
        expected_at = _aware(record["expected_at_utc"], "expected_at_utc")
        draw_at = _aware(record["target_draw_at_utc"], "target_draw_at_utc")
        generated = _aware(schedule["generated_at_utc"], "generated_at_utc")
        if not expected_at < cutoff < draw_at:
            raise ScheduleError(f"record {index} must order expectation < cutoff < draw")
        if generated >= cutoff:
            raise ScheduleError(f"schedule was generated at/after record {index} cutoff")
    return records


def run_schedule(
    schedule: dict[str, Any],
    ledger: ProspectiveLedger,
    *,
    mode: str,
    clock: Callable[[], datetime] | None = None,
) -> dict[str, Any]:
    """Run register or finalize mode; retries are idempotent and failures retained."""
    if mode not in ("register", "finalize"):
        raise ScheduleError("mode must be register or finalize")
    records = validate_schedule(schedule)
    now_fn = clock or (lambda: datetime.now(timezone.utc))
    if mode == "register":
        # Preflight every record against the same ledger contract before any
        # durable write. Real writes remain individually idempotent if a cutoff
        # is crossed or the process stops partway through the batch.
        with tempfile.TemporaryDirectory(prefix="lottery-schedule-preflight-") as directory:
            probe = ProspectiveLedger(Path(directory) / "preflight.jsonl", clock=now_fn)
            for record in records:
                probe.register_expected_forecast(**record)

    snapshot = ledger.snapshot()
    completed = []
    skipped = []
    failures = []
    for record in records:
        key = (
            record["front_artifact_sha256"], record["back_artifact_sha256"],
            record["target_draw_id"], record["zone"], record["population_key"],
            record["forecast_policy_version"], record["active_registry_snapshot_id"],
            record["registry_generation"],
        )
        try:
            if mode == "register":
                value = ledger.register_expected_forecast(**record)
                completed.append(value["expected_forecast_id"])
            else:
                if key in snapshot["forecast_keys"]:
                    skipped.append(record["target_draw_id"] + ":" + record["zone"])
                    continue
                now = now_fn()
                if now.tzinfo is None or now.utcoffset() is None:
                    raise ScheduleError("scheduler clock must return timezone-aware datetime")
                value = ledger.record_missing_forecast(
                    **{key: item for key, item in record.items() if key != "expected_at_utc"},
                    expected_at_utc=record["expected_at_utc"],
                    checked_at_utc=now.astimezone(timezone.utc).isoformat(),
                )
                completed.append(value["forecast_id"])
        except (ProspectiveLedgerError, ScheduleError, ValueError) as exc:
            failures.append({
                "target_draw_id": record["target_draw_id"],
                "zone": record["zone"],
                "reason": str(exc),
            })
    return {
        "schema": "lottery.prospective-schedule-receipt/v1",
        "schedule_id": schedule["schedule_id"],
        "mode": mode,
        "status": "complete" if not failures else "partial_or_failed",
        "expected_count": len(records),
        "completed_count": len(completed),
        "skipped_count": len(skipped),
        "failure_count": len(failures),
        "completed_ids": completed,
        "skipped_slots": skipped,
        "failures": failures,
        "ledger_event_count": ledger.snapshot()["event_count"],
    }


def load_schedule(path: str | Path) -> dict[str, Any]:
    def no_duplicates(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ScheduleError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=no_duplicates)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ScheduleError("cannot read prospective schedule JSON") from exc
    validate_schedule(value)
    return value
