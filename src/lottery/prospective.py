"""Immutable prospective forecast, official outcome and exact-score ledger."""
from __future__ import annotations

from datetime import date, datetime, timezone
import hashlib
import json
import math
from math import comb, log
import os
from pathlib import Path
import re
import tempfile
from typing import Any, Callable
from uuid import uuid4

from .ledger_lock import ledger_lock
from .subset_model.artifact import canonicalize, parse_json_strict, ArtifactValidationError


LEDGER_SCHEMA = "lottery.prospective-ledger/v1"
FORECAST_SCHEMA = "lottery.prospective-forecast/v1"
OUTCOME_SCHEMA = "lottery.prospective-outcome/v1"
SCORE_SCHEMA = "lottery.prospective-score/v1"
GENESIS_HASH = "0" * 64
AUTHORITIES = {"official_validated", "official_unverified", "third_party", "blocked", "conflict", "invalid"}


class ProspectiveLedgerError(RuntimeError):
    """Raised when prospective evidence or score lineage is invalid."""


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _is_sha(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _timestamp(value: str, field: str) -> datetime:
    if not isinstance(value, str):
        raise ProspectiveLedgerError(f"{field} must be an ISO-8601 string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ProspectiveLedgerError(f"{field} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ProspectiveLedgerError(f"{field} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _validate_subset(numbers: Any, zone: str) -> list[int]:
    size, maximum = (5, 35) if zone == "front" else (2, 12)
    if (not isinstance(numbers, list) or len(numbers) != size
            or any(type(value) is not int or not 1 <= value <= maximum for value in numbers)
            or numbers != sorted(set(numbers))):
        raise ProspectiveLedgerError(f"{zone} outcome must be {size} unique ascending integers in 1..{maximum}")
    return list(numbers)


def _write_once(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            if path.read_bytes() != raw:
                raise ProspectiveLedgerError("immutable prospective record collision")
        if hasattr(os, "O_DIRECTORY"):
            directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


class ProspectiveLedger:
    """One artifact × target × zone forecast unit, versioned outcomes and score revisions."""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def _read_events(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        events = []
        previous = GENESIS_HASH
        seen = set()
        for line_number, line in enumerate(self.path.read_bytes().splitlines(), 1):
            try:
                event = parse_json_strict(line)
            except ArtifactValidationError as exc:
                raise ProspectiveLedgerError(f"event line {line_number} is invalid JSON") from exc
            if not isinstance(event, dict):
                raise ProspectiveLedgerError(f"event line {line_number} must be an object")
            body = {key: value for key, value in event.items() if key != "event_hash"}
            event_id = event.get("event_id")
            if (not isinstance(event_id, str) or not event_id or event_id in seen
                    or event.get("schema") != LEDGER_SCHEMA
                    or canonicalize(event) != line
                    or event.get("previous_event_hash") != previous
                    or event.get("event_hash") != _sha(canonicalize(body))):
                raise ProspectiveLedgerError(f"prospective ledger hash chain failed at line {line_number}")
            seen.add(event_id)
            previous = event["event_hash"]
            events.append(event)
        return events

    def _append_locked(self, event_id: str, event_type: str, record: dict[str, Any]) -> None:
        events = self._read_events()
        existing = next((event for event in events if event["event_id"] == event_id), None)
        if existing is not None:
            if existing.get("record") != record or existing.get("event_type") != event_type:
                raise ProspectiveLedgerError("prospective event id collision has different content")
            return
        previous = events[-1]["event_hash"] if events else GENESIS_HASH
        body = {
            "schema": LEDGER_SCHEMA,
            "event_id": event_id,
            "event_type": event_type,
            "occurred_at_utc": datetime.now(timezone.utc).isoformat(),
            "previous_event_hash": previous,
            "record": record,
        }
        event = {**body, "event_hash": _sha(canonicalize(body))}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("ab") as handle:
            handle.write(canonicalize(event) + b"\n")
            handle.flush()
            os.fsync(handle.fileno())

    def _snapshot_unlocked(self) -> dict[str, Any]:
        forecasts: dict[str, dict[str, Any]] = {}
        forecast_keys: dict[tuple[str, str, str, str, str, str, str, int], str] = {}
        outcomes: dict[str, dict[str, Any]] = {}
        latest_outcome: dict[str, str] = {}
        superseded: set[str] = set()
        scores: dict[str, dict[str, Any]] = {}
        score_keys: dict[tuple[str, str, str], str] = {}
        score_failures: dict[str, dict[str, Any]] = {}
        score_failure_keys: dict[tuple[str, str, str, str], str] = {}
        for event in self._read_events():
            record = event.get("record")
            if not isinstance(record, dict):
                raise ProspectiveLedgerError("prospective event record must be an object")
            if event["event_type"] in ("forecast_issued", "forecast_missing"):
                if record.get("schema") != FORECAST_SCHEMA or _sha(canonicalize({
                    key: value for key, value in record.items() if key != "forecast_id"
                })) != record.get("forecast_id"):
                    raise ProspectiveLedgerError("forecast record content hash mismatch")
                expected_status = "missing_at_cutoff" if event["event_type"] == "forecast_missing" else None
                if (expected_status is not None and record.get("status") != expected_status
                        or expected_status is None and record.get("status") not in ("eligible", "ineligible")):
                    raise ProspectiveLedgerError("forecast event type and terminal status disagree")
                forecast_id = record["forecast_id"]
                key = (
                    record["front_artifact_sha256"], record["back_artifact_sha256"],
                    record["target_draw_id"], record["zone"],
                    record["population_key"], record["forecast_policy_version"],
                    record["active_registry_snapshot_id"], record["registry_generation"],
                )
                if forecast_id in forecasts or key in forecast_keys:
                    raise ProspectiveLedgerError("duplicate artifact × target × zone forecast")
                forecasts[forecast_id] = record
                forecast_keys[key] = forecast_id
            elif event["event_type"] == "outcome_observed":
                if record.get("schema") != OUTCOME_SCHEMA or _sha(canonicalize({
                    key: value for key, value in record.items() if key != "outcome_id"
                })) != record.get("outcome_id"):
                    raise ProspectiveLedgerError("outcome record content hash mismatch")
                outcome_id = record["outcome_id"]
                draw_id = record["draw_id"]
                if outcome_id in outcomes:
                    raise ProspectiveLedgerError("duplicate outcome ID")
                previous_id = record.get("supersedes_outcome_id")
                current_id = latest_outcome.get(draw_id)
                if previous_id != current_id:
                    if previous_id is not None or current_id is not None:
                        raise ProspectiveLedgerError("outcome correction does not supersede the current version")
                if previous_id is not None:
                    superseded.add(previous_id)
                outcomes[outcome_id] = record
                latest_outcome[draw_id] = outcome_id
            elif event["event_type"] == "score_recorded":
                if record.get("schema") != SCORE_SCHEMA or _sha(canonicalize({
                    key: value for key, value in record.items() if key != "score_id"
                })) != record.get("score_id"):
                    raise ProspectiveLedgerError("score record content hash mismatch")
                score_id = record["score_id"]
                key = (record["forecast_id"], record["outcome_id"], record["scorer_version"])
                if score_id in scores or key in score_keys:
                    raise ProspectiveLedgerError("duplicate forecast/outcome/scorer score")
                if record["forecast_id"] not in forecasts or record["outcome_id"] not in outcomes:
                    raise ProspectiveLedgerError("score references missing forecast or outcome")
                scores[score_id] = record
                score_keys[key] = score_id
            elif event["event_type"] == "score_failed":
                if record.get("schema") != SCORE_SCHEMA or record.get("status") != "score_failed" or _sha(canonicalize({
                    key: value for key, value in record.items() if key != "score_failure_id"
                })) != record.get("score_failure_id"):
                    raise ProspectiveLedgerError("score failure record content hash mismatch")
                failure_id = record["score_failure_id"]
                key = (
                    record["forecast_id"], record["outcome_id"],
                    record["scorer_version"], record["attempt_id"],
                )
                if failure_id in score_failures or key in score_failure_keys:
                    raise ProspectiveLedgerError("duplicate score failure attempt")
                if record["forecast_id"] not in forecasts or record["outcome_id"] not in outcomes:
                    raise ProspectiveLedgerError("score failure references missing forecast or outcome")
                score_failures[failure_id] = record
                score_failure_keys[key] = failure_id
            else:
                raise ProspectiveLedgerError("unknown prospective ledger event type")
        return {
            "forecasts": forecasts,
            "forecast_keys": forecast_keys,
            "outcomes": outcomes,
            "latest_outcome_by_draw": latest_outcome,
            "superseded_outcome_ids": superseded,
            "scores": scores,
            "score_keys": score_keys,
            "score_failures": score_failures,
            "score_failure_keys": score_failure_keys,
            "event_count": len(self._read_events()),
        }

    def snapshot(self) -> dict[str, Any]:
        with ledger_lock(self.path):
            return self._snapshot_unlocked()

    def issue_forecast(
        self,
        *,
        target_draw_id: str,
        target_draw_at_utc: str,
        target_cutoff_utc: str,
        target_cutoff_timezone_source: str,
        issued_at_utc: str,
        artifact_sha256: str,
        distribution_sha256: str,
        front_artifact_sha256: str,
        back_artifact_sha256: str,
        front_distribution_sha256: str,
        back_distribution_sha256: str,
        active_registry_snapshot_id: str,
        lifecycle_state: str,
        model_spec_sha256: str,
        zone: str,
        population_key: str,
        training_snapshot_sha256: str,
        training_first_draw_id: str,
        training_last_draw_id: str,
        training_row_count: int,
        training_last_draw_date: str,
        registry_generation: int,
        forecast_policy_version: str,
        scoring_policy_version: str,
        model_family: str,
        code_commit: str,
        runtime: str,
        source_evidence_manifest_sha256: str | None = None,
    ) -> dict[str, Any]:
        if not isinstance(target_draw_id, str) or re.fullmatch(r"\d{5}", target_draw_id) is None:
            raise ProspectiveLedgerError("target_draw_id must be a five-digit ID")
        if (not isinstance(training_first_draw_id, str)
                or re.fullmatch(r"\d{5}", training_first_draw_id) is None
                or not isinstance(training_last_draw_id, str)
                or re.fullmatch(r"\d{5}", training_last_draw_id) is None
                or training_first_draw_id > training_last_draw_id):
            raise ProspectiveLedgerError("training draw range must use ordered five-digit IDs")
        if type(training_row_count) is not int or training_row_count < 1:
            raise ProspectiveLedgerError("training_row_count must be a positive integer")
        if zone not in ("front", "back"):
            raise ProspectiveLedgerError("forecast zone must be front or back")
        for field, value in (
            ("artifact_sha256", artifact_sha256),
            ("distribution_sha256", distribution_sha256),
            ("front_artifact_sha256", front_artifact_sha256),
            ("back_artifact_sha256", back_artifact_sha256),
            ("front_distribution_sha256", front_distribution_sha256),
            ("back_distribution_sha256", back_distribution_sha256),
            ("active_registry_snapshot_id", active_registry_snapshot_id),
            ("model_spec_sha256", model_spec_sha256),
            ("training_snapshot_sha256", training_snapshot_sha256),
        ):
            if not _is_sha(value):
                raise ProspectiveLedgerError(f"{field} must be a lowercase SHA-256")
        if source_evidence_manifest_sha256 is not None and not _is_sha(source_evidence_manifest_sha256):
            raise ProspectiveLedgerError("source_evidence_manifest_sha256 must be null or a lowercase SHA-256")
        selected_artifact = front_artifact_sha256 if zone == "front" else back_artifact_sha256
        selected_distribution = front_distribution_sha256 if zone == "front" else back_distribution_sha256
        if artifact_sha256 != selected_artifact or distribution_sha256 != selected_distribution:
            raise ProspectiveLedgerError("zone artifact/distribution hashes must match the bound front/back pair")
        if type(registry_generation) is not int or registry_generation < 0:
            raise ProspectiveLedgerError("registry_generation must be a non-negative integer")
        for field, value in (
            ("population_key", population_key), ("forecast_policy_version", forecast_policy_version),
            ("scoring_policy_version", scoring_policy_version),
            ("target_cutoff_timezone_source", target_cutoff_timezone_source),
            ("model_family", model_family), ("code_commit", code_commit), ("runtime", runtime),
        ):
            if not isinstance(value, str) or not value:
                raise ProspectiveLedgerError(f"{field} must be a non-empty string")
        if re.fullmatch(r"[0-9a-f]{40}", code_commit) is None:
            raise ProspectiveLedgerError("code_commit must be a full lowercase Git SHA")
        draw_at = _timestamp(target_draw_at_utc, "target_draw_at_utc")
        cutoff = _timestamp(target_cutoff_utc, "target_cutoff_utc")
        issued = _timestamp(issued_at_utc, "issued_at_utc")
        if draw_at <= cutoff:
            raise ProspectiveLedgerError("target draw time must be strictly after its forecast cutoff")
        if lifecycle_state not in ("champion", "shadow", "challenger", "retired", "suspended"):
            raise ProspectiveLedgerError("lifecycle_state is not a registered state")
        if population_key not in ("pooled", "pooled-equipment-blind") and source_evidence_manifest_sha256 is None:
            raise ProspectiveLedgerError("set-conditioned forecast requires a source evidence manifest digest")
        try:
            training_date = date.fromisoformat(training_last_draw_date)
        except (TypeError, ValueError) as exc:
            raise ProspectiveLedgerError("training_last_draw_date must be YYYY-MM-DD") from exc
        reasons = []
        if lifecycle_state not in ("champion", "shadow"):
            reasons.append("lifecycle_not_active")
        if issued >= cutoff:
            reasons.append("forecast_after_cutoff")
        if training_last_draw_id >= target_draw_id:
            reasons.append("training_draw_not_before_target")
        if training_date >= cutoff.date():
            reasons.append("training_date_not_before_target_cutoff")
        if training_row_count < 300:
            reasons.append("insufficient_training_history")
        record = {
            "schema": FORECAST_SCHEMA,
            "target_draw_id": target_draw_id,
            "target_draw_at_utc": draw_at.isoformat(),
            "target_cutoff_utc": cutoff.isoformat(),
            "target_cutoff_timezone_source": target_cutoff_timezone_source,
            "issued_at_utc": issued.isoformat(),
            "artifact_sha256": artifact_sha256,
            "distribution_sha256": distribution_sha256,
            "front_artifact_sha256": front_artifact_sha256,
            "back_artifact_sha256": back_artifact_sha256,
            "front_distribution_sha256": front_distribution_sha256,
            "back_distribution_sha256": back_distribution_sha256,
            "active_registry_snapshot_id": active_registry_snapshot_id,
            "lifecycle_state": lifecycle_state,
            "model_spec_sha256": model_spec_sha256,
            "zone": zone,
            "population_key": population_key,
            "training_snapshot_sha256": training_snapshot_sha256,
            "training_first_draw_id": training_first_draw_id,
            "training_last_draw_id": training_last_draw_id,
            "training_row_count": training_row_count,
            "training_last_draw_date": training_date.isoformat(),
            "registry_generation": registry_generation,
            "forecast_policy_version": forecast_policy_version,
            "scoring_policy_version": scoring_policy_version,
            "model_family": model_family,
            "code_commit": code_commit,
            "runtime": runtime,
            "source_evidence_manifest_sha256": source_evidence_manifest_sha256,
            "status": "eligible" if not reasons else "ineligible",
            "reason_codes": reasons,
        }
        record["forecast_id"] = _sha(canonicalize(record))
        key = (
            front_artifact_sha256, back_artifact_sha256, target_draw_id,
            zone, population_key, forecast_policy_version,
            active_registry_snapshot_id, registry_generation,
        )
        with ledger_lock(self.path):
            snapshot = self._snapshot_unlocked()
            existing_id = snapshot["forecast_keys"].get(key)
            if existing_id is not None:
                if existing_id == record["forecast_id"]:
                    return snapshot["forecasts"][existing_id]
                raise ProspectiveLedgerError("forecast key already has an immutable record")
            self._append_locked(f"forecast:{record['forecast_id']}", "forecast_issued", record)
            return record

    def record_missing_forecast(
        self,
        *,
        target_draw_id: str,
        target_draw_at_utc: str,
        target_cutoff_utc: str,
        target_cutoff_timezone_source: str,
        expected_at_utc: str,
        checked_at_utc: str,
        zone: str,
        population_key: str,
        front_artifact_sha256: str,
        back_artifact_sha256: str,
        active_registry_snapshot_id: str,
        lifecycle_state: str,
        model_spec_sha256: str,
        training_snapshot_sha256: str,
        training_first_draw_id: str,
        training_last_draw_id: str,
        training_row_count: int,
        training_last_draw_date: str,
        registry_generation: int,
        forecast_policy_version: str,
        scoring_policy_version: str,
        model_family: str,
        code_commit: str,
        runtime: str,
        source_evidence_manifest_sha256: str | None = None,
    ) -> dict[str, Any]:
        """Finalize an expected forecast as missing once its cutoff has passed."""
        if not isinstance(target_draw_id, str) or re.fullmatch(r"\d{5}", target_draw_id) is None:
            raise ProspectiveLedgerError("target_draw_id must be a five-digit ID")
        if zone not in ("front", "back"):
            raise ProspectiveLedgerError("zone must be front or back")
        draw_at = _timestamp(target_draw_at_utc, "target_draw_at_utc")
        cutoff = _timestamp(target_cutoff_utc, "target_cutoff_utc")
        expected_at = _timestamp(expected_at_utc, "expected_at_utc")
        checked_at = _timestamp(checked_at_utc, "checked_at_utc")
        if draw_at <= cutoff or expected_at >= cutoff or checked_at < cutoff:
            raise ProspectiveLedgerError("missing forecast must be expected before and finalized at/after cutoff")
        if lifecycle_state not in ("champion", "shadow"):
            raise ProspectiveLedgerError("only active Champion/shadow slots may have expected forecasts")
        if type(registry_generation) is not int or registry_generation < 0:
            raise ProspectiveLedgerError("registry_generation must be a non-negative integer")
        for field, value in (
            ("front_artifact_sha256", front_artifact_sha256),
            ("back_artifact_sha256", back_artifact_sha256),
            ("active_registry_snapshot_id", active_registry_snapshot_id),
            ("model_spec_sha256", model_spec_sha256),
            ("training_snapshot_sha256", training_snapshot_sha256),
        ):
            if not _is_sha(value):
                raise ProspectiveLedgerError(f"{field} must be a lowercase SHA-256")
        if source_evidence_manifest_sha256 is not None and not _is_sha(source_evidence_manifest_sha256):
            raise ProspectiveLedgerError("source_evidence_manifest_sha256 must be null or a lowercase SHA-256")
        if population_key not in ("pooled", "pooled-equipment-blind") and source_evidence_manifest_sha256 is None:
            raise ProspectiveLedgerError("set-conditioned forecast requires a source evidence manifest digest")
        if (not isinstance(training_first_draw_id, str)
                or re.fullmatch(r"\d{5}", training_first_draw_id) is None
                or not isinstance(training_last_draw_id, str)
                or re.fullmatch(r"\d{5}", training_last_draw_id) is None
                or training_first_draw_id > training_last_draw_id):
            raise ProspectiveLedgerError("training draw range must use ordered five-digit IDs")
        if type(training_row_count) is not int or training_row_count < 300:
            raise ProspectiveLedgerError("missing forecast expectation requires at least 300 training rows")
        if training_last_draw_id >= target_draw_id:
            raise ProspectiveLedgerError("training_last_draw_id must be strictly before target_draw_id")
        training_date = date.fromisoformat(training_last_draw_date)
        if training_date >= cutoff.date():
            raise ProspectiveLedgerError("training date must be strictly before target cutoff")
        for field, value in (
            ("target_cutoff_timezone_source", target_cutoff_timezone_source),
            ("population_key", population_key),
            ("forecast_policy_version", forecast_policy_version),
            ("scoring_policy_version", scoring_policy_version),
            ("model_family", model_family),
            ("code_commit", code_commit),
            ("runtime", runtime),
        ):
            if not isinstance(value, str) or not value:
                raise ProspectiveLedgerError(f"{field} must be a non-empty string")
        selected_artifact = front_artifact_sha256 if zone == "front" else back_artifact_sha256
        record = {
            "schema": FORECAST_SCHEMA,
            "target_draw_id": target_draw_id,
            "target_draw_at_utc": draw_at.isoformat(),
            "target_cutoff_utc": cutoff.isoformat(),
            "target_cutoff_timezone_source": target_cutoff_timezone_source,
            "expected_at_utc": expected_at.isoformat(),
            "checked_at_utc": checked_at.isoformat(),
            "issued_at_utc": None,
            "artifact_sha256": selected_artifact,
            "distribution_sha256": None,
            "front_artifact_sha256": front_artifact_sha256,
            "back_artifact_sha256": back_artifact_sha256,
            "front_distribution_sha256": None,
            "back_distribution_sha256": None,
            "active_registry_snapshot_id": active_registry_snapshot_id,
            "lifecycle_state": lifecycle_state,
            "model_spec_sha256": model_spec_sha256,
            "zone": zone,
            "population_key": population_key,
            "training_snapshot_sha256": training_snapshot_sha256,
            "training_first_draw_id": training_first_draw_id,
            "training_last_draw_id": training_last_draw_id,
            "training_row_count": training_row_count,
            "training_last_draw_date": training_date.isoformat(),
            "registry_generation": registry_generation,
            "forecast_policy_version": forecast_policy_version,
            "scoring_policy_version": scoring_policy_version,
            "model_family": model_family,
            "code_commit": code_commit,
            "runtime": runtime,
            "source_evidence_manifest_sha256": source_evidence_manifest_sha256,
            "status": "missing_at_cutoff",
            "reason_codes": ["forecast_missing_at_cutoff"],
        }
        record["forecast_id"] = _sha(canonicalize(record))
        key = (
            front_artifact_sha256, back_artifact_sha256, target_draw_id,
            zone, population_key, forecast_policy_version,
            active_registry_snapshot_id, registry_generation,
        )
        with self._lock():
            snapshot = self._snapshot_unlocked()
            existing = snapshot["forecast_keys"].get(key)
            if existing is not None:
                if existing == record["forecast_id"]:
                    return snapshot["forecasts"][existing]
                raise ProspectiveLedgerError("duplicate artifact × target × zone forecast")
            event_id = _sha(f"forecast-missing:{record['forecast_id']}".encode("utf-8"))
            self._append_locked(event_id, "forecast_missing", record)
        return record

    def record_outcome(
        self,
        *,
        draw_id: str,
        observed_at_utc: str,
        authority: str,
        source_evidence_sha256: str,
        source_object_ref: str,
        requested_url: str,
        final_url: str,
        retrieved_at_utc: str,
        evidence_locator: str,
        parser_version: str,
        front_numbers: list[int] | None,
        back_numbers: list[int] | None,
        evidence_verifier: Callable[[dict[str, Any], dict[str, Any]], bool] | None = None,
        supersedes_outcome_id: str | None = None,
        reason_code: str | None = None,
        conflict_group: str | None = None,
    ) -> dict[str, Any]:
        if not isinstance(draw_id, str) or re.fullmatch(r"\d{5}", draw_id) is None:
            raise ProspectiveLedgerError("draw_id must be a five-digit ID")
        observed = _timestamp(observed_at_utc, "observed_at_utc")
        if authority not in AUTHORITIES:
            raise ProspectiveLedgerError("unknown outcome authority class")
        if not _is_sha(source_evidence_sha256):
            raise ProspectiveLedgerError("source_evidence_sha256 must be a lowercase SHA-256")
        for field, value in (
            ("source_object_ref", source_object_ref),
            ("requested_url", requested_url),
            ("final_url", final_url),
            ("evidence_locator", evidence_locator),
            ("parser_version", parser_version),
        ):
            if not isinstance(value, str) or not value:
                raise ProspectiveLedgerError(f"{field} must be a non-empty string")
        from urllib.parse import urlsplit
        for field, value in (("requested_url", requested_url), ("final_url", final_url)):
            parsed_url = urlsplit(value)
            if (parsed_url.scheme != "https" or not parsed_url.netloc
                    or parsed_url.username is not None or parsed_url.password is not None
                    or parsed_url.fragment):
                raise ProspectiveLedgerError(f"{field} must be an absolute HTTPS URL without credentials/fragments")
        retrieved = _timestamp(retrieved_at_utc, "retrieved_at_utc")
        if retrieved > observed:
            raise ProspectiveLedgerError("evidence retrieval cannot occur after the outcome observation")
        if conflict_group is not None and (not isinstance(conflict_group, str) or not conflict_group):
            raise ProspectiveLedgerError("conflict_group must be null or a non-empty string")
        if authority == "official_validated" and requested_url != final_url:
            raise ProspectiveLedgerError("official validated evidence cannot use a redirected final URL")
        if authority == "conflict" and conflict_group is None:
            raise ProspectiveLedgerError("conflicting outcome requires a conflict_group")
        front = _validate_subset(front_numbers, "front") if front_numbers is not None else None
        back = _validate_subset(back_numbers, "back") if back_numbers is not None else None
        if authority == "official_validated":
            if front is None or back is None or evidence_verifier is None:
                raise ProspectiveLedgerError("official validated outcome requires both legal subsets and protected evidence verifier")
            expected = {
                "draw_id": draw_id,
                "source_evidence_sha256": source_evidence_sha256,
                "source_object_ref": source_object_ref,
                "requested_url": requested_url,
                "final_url": final_url,
                "retrieved_at_utc": retrieved.isoformat(),
                "evidence_locator": evidence_locator,
                "parser_version": parser_version,
                "authority": authority,
            }
            candidate = {
                **expected,
                "front_numbers": front,
                "back_numbers": back,
                "conflict_group": conflict_group,
            }
            if evidence_verifier(candidate, expected) is not True:
                raise ProspectiveLedgerError("official outcome evidence verifier rejected the observation")
            if reason_code is not None:
                raise ProspectiveLedgerError("official validated outcome cannot carry a failure reason")
        elif not isinstance(reason_code, str) or not reason_code:
            raise ProspectiveLedgerError("non-authoritative outcome must retain a stable reason_code")

        with ledger_lock(self.path):
            snapshot = self._snapshot_unlocked()
            record = {
                "schema": OUTCOME_SCHEMA,
                "draw_id": draw_id,
                "observed_at_utc": observed.isoformat(),
                "authority": authority,
                "source_evidence_sha256": source_evidence_sha256,
                "source_object_ref": source_object_ref,
                "requested_url": requested_url,
                "final_url": final_url,
                "retrieved_at_utc": retrieved.isoformat(),
                "evidence_locator": evidence_locator,
                "parser_version": parser_version,
                "front_numbers": front,
                "back_numbers": back,
                "supersedes_outcome_id": supersedes_outcome_id,
                "reason_code": reason_code,
                "conflict_group": conflict_group,
            }
            record["outcome_id"] = _sha(canonicalize(record))
            existing = snapshot["outcomes"].get(record["outcome_id"])
            if existing is not None:
                return existing
            current_id = snapshot["latest_outcome_by_draw"].get(draw_id)
            if supersedes_outcome_id != current_id:
                if supersedes_outcome_id is not None or current_id is not None:
                    raise ProspectiveLedgerError("correction must explicitly supersede the current outcome version")
            if supersedes_outcome_id is not None:
                previous = snapshot["outcomes"].get(supersedes_outcome_id)
                if previous is None or previous["draw_id"] != draw_id:
                    raise ProspectiveLedgerError("superseded outcome must belong to the same draw")
                if observed < _timestamp(previous["observed_at_utc"], "previous observed_at_utc"):
                    raise ProspectiveLedgerError("outcome correction timestamp cannot move backwards")
            self._append_locked(f"outcome:{record['outcome_id']}", "outcome_observed", record)
            return record

    def score_forecast(
        self,
        *,
        forecast_id: str,
        outcome_id: str,
        scorer_version: str,
        log_probability: Callable[[dict[str, Any], list[int]], dict[str, Any]],
        attempt_id: str | None = None,
    ) -> dict[str, Any]:
        if not _is_sha(forecast_id) or not _is_sha(outcome_id):
            raise ProspectiveLedgerError("forecast_id and outcome_id must be lowercase SHA-256 values")
        if not isinstance(scorer_version, str) or not scorer_version:
            raise ProspectiveLedgerError("scorer_version must be a non-empty string")
        if attempt_id is not None and (
            not isinstance(attempt_id, str)
            or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", attempt_id) is None
        ):
            raise ProspectiveLedgerError("score attempt_id is malformed")
        if not callable(log_probability):
            raise ProspectiveLedgerError("exact artifact log-probability scorer is required")
        with ledger_lock(self.path):
            snapshot = self._snapshot_unlocked()
            forecast = snapshot["forecasts"].get(forecast_id)
            if forecast is None:
                raise ProspectiveLedgerError("forecast record is missing")
            if forecast["status"] != "eligible":
                raise ProspectiveLedgerError("ineligible forecast cannot be scored")
            outcome = snapshot["outcomes"].get(outcome_id)
            if outcome is None:
                raise ProspectiveLedgerError("outcome record is missing")
            if outcome["authority"] != "official_validated":
                raise ProspectiveLedgerError("only authoritative validated outcomes can be scored")
            if snapshot["latest_outcome_by_draw"].get(outcome["draw_id"]) != outcome_id:
                raise ProspectiveLedgerError("superseded outcome cannot receive a new score")
            if forecast["target_draw_id"] != outcome["draw_id"]:
                raise ProspectiveLedgerError("forecast and outcome target draw IDs differ")
            if _timestamp(outcome["observed_at_utc"], "observed_at_utc") < _timestamp(
                forecast["target_draw_at_utc"], "target_draw_at_utc"
            ):
                raise ProspectiveLedgerError("outcome observation predates the scheduled target draw")
            actual = outcome["front_numbers"] if forecast["zone"] == "front" else outcome["back_numbers"]
            if actual is None:
                raise ProspectiveLedgerError("validated outcome is missing the forecast zone subset")
            def record_failure(failure_code: str) -> None:
                current_attempt_id = attempt_id or uuid4().hex
                if (not isinstance(current_attempt_id, str)
                        or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", current_attempt_id) is None):
                    raise ProspectiveLedgerError("score failure attempt_id is malformed")
                failure = {
                    "schema": SCORE_SCHEMA,
                    "status": "score_failed",
                    "forecast_id": forecast_id,
                    "outcome_id": outcome_id,
                    "target_draw_id": forecast["target_draw_id"],
                    "artifact_sha256": forecast["artifact_sha256"],
                    "zone": forecast["zone"],
                    "population_key": forecast["population_key"],
                    "scorer_version": scorer_version,
                    "attempt_id": current_attempt_id,
                    "failure_code": failure_code,
                }
                failure["score_failure_id"] = _sha(canonicalize(failure))
                event_id = _sha(
                    f"{forecast_id}:{outcome_id}:{scorer_version}:{current_attempt_id}:failed".encode("utf-8")
                )
                self._append_locked(event_id, "score_failed", failure)

            try:
                evaluation = log_probability(forecast, actual)
            except Exception as exc:
                record_failure("artifact_probability_evaluation_failed")
                raise ProspectiveLedgerError("artifact probability evaluation failed") from exc
            if (not isinstance(evaluation, dict)
                    or set(evaluation) != {"artifact_sha256", "normalization_verified", "log_probability"}
                    or evaluation.get("artifact_sha256") != forecast["artifact_sha256"]
                    or evaluation.get("normalization_verified") is not True):
                record_failure("artifact_normalization_or_identity_unverified")
                raise ProspectiveLedgerError("exact-set evaluator must verify the bound artifact and full-support normalization")
            raw_logp = evaluation["log_probability"]
            try:
                if isinstance(raw_logp, bool):
                    raise TypeError("boolean is not a probability score")
                logp = float(raw_logp)
            except (TypeError, ValueError, OverflowError):
                record_failure("invalid_log_probability")
                raise ProspectiveLedgerError("exact-set log probability is invalid")
            if not math.isfinite(logp) or logp >= 0.0:
                record_failure("invalid_log_probability")
                raise ProspectiveLedgerError("exact-set log probability must be finite and strictly negative")
            population, selection = (35, 5) if forecast["zone"] == "front" else (12, 2)
            nll = -logp
            uniform_nll = log(comb(population, selection))
            base = {
                "schema": SCORE_SCHEMA,
                "forecast_id": forecast_id,
                "outcome_id": outcome_id,
                "target_draw_id": forecast["target_draw_id"],
                "artifact_sha256": forecast["artifact_sha256"],
                "zone": forecast["zone"],
                "population_key": forecast["population_key"],
                "scorer_version": scorer_version,
                "log_probability": logp,
                "negative_log_score": nll,
                "uniform_negative_log_score": uniform_nll,
                "candidate_minus_uniform_nll": nll - uniform_nll,
            }
            base["score_id"] = _sha(canonicalize(base))
            key = (forecast_id, outcome_id, scorer_version)
            existing_id = snapshot["score_keys"].get(key)
            if existing_id is not None:
                existing = snapshot["scores"][existing_id]
                if existing["score_id"] == base["score_id"]:
                    return existing
                raise ProspectiveLedgerError("score key already has a different immutable result")
            self._append_locked(f"score:{base['score_id']}", "score_recorded", base)
            return base

    def coverage_report(self) -> dict[str, Any]:
        snapshot = self.snapshot()
        forecasts = list(snapshot["forecasts"].values())
        outcomes = list(snapshot["outcomes"].values())
        scores = list(snapshot["scores"].values())
        latest_outcomes = set(snapshot["latest_outcome_by_draw"].values())
        scored_forecasts = {
            score["forecast_id"] for score in scores if score["outcome_id"] in latest_outcomes
        }
        eligible = [record for record in forecasts if record["status"] == "eligible"]
        outcome_pending = 0
        outcome_invalid = 0
        score_pending = 0
        for record in eligible:
            outcome_id = snapshot["latest_outcome_by_draw"].get(record["target_draw_id"])
            if outcome_id is None:
                outcome_pending += 1
            elif snapshot["outcomes"][outcome_id]["authority"] != "official_validated":
                outcome_invalid += 1
            elif record["forecast_id"] not in scored_forecasts:
                score_pending += 1
        return {
            "expected_forecast_records": len(forecasts),
            "eligible": len(eligible),
            "ineligible": len(forecasts) - len(eligible),
            "forecast_missing_at_cutoff": sum(
                record["status"] == "missing_at_cutoff" for record in forecasts
            ),
            "outcome_versions": len(outcomes),
            "latest_outcomes": len(latest_outcomes),
            "outcome_authority_counts": {
                authority: sum(snapshot["outcomes"][outcome_id]["authority"] == authority for outcome_id in latest_outcomes)
                for authority in sorted(AUTHORITIES)
            },
            "official_validated_latest_outcomes": sum(
                snapshot["outcomes"][outcome_id]["authority"] == "official_validated"
                for outcome_id in latest_outcomes
            ),
            "scored_current_forecasts": len(scored_forecasts),
            "outcome_pending": outcome_pending,
            "outcome_invalid": outcome_invalid,
            "score_pending": score_pending,
            "eligible_pending": outcome_pending + outcome_invalid + score_pending,
            "score_revisions": len(scores),
            "score_failed_attempts": len(snapshot["score_failures"]),
            "event_count": snapshot["event_count"],
        }
