"""Immutable pre-registration and trial-history registry for model research.

The registry records all attempts, including failures. Confirmatory
registrations require a protected approval verifier; post-result changes must
be registered as exploratory child experiments.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import re
import tempfile
from typing import Any, Callable
from uuid import uuid4

from .ledger_lock import ledger_lock
from .subset_model.artifact import canonicalize, parse_json_strict, ArtifactValidationError


EXPERIMENT_SCHEMA = "lottery.experiment-preregistration/v1"
EVENT_SCHEMA = "lottery.experiment-event/v1"
CONFIRMATORY_BOOTSTRAP_REPLICATES = 1000
CONFIRMATORY_BLOCK_LENGTH = 50
TERMINAL_STATUSES = {
    "succeeded", "fit_failed", "invalid_artifact", "runner_error", "timeout", "abandoned"
}
POPULATION_CLAIMS = {
    "pooled", "same_artifact_distinct_fit", "distinct_population", "distributionally_distinct"
}


class ExperimentRegistryError(RuntimeError):
    """Raised when experiment registration or trial lineage is invalid."""


class ExperimentApprovalError(ExperimentRegistryError):
    """Raised when a confirmatory registration lacks protected approval."""


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _is_sha(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _write_once(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            if path.read_bytes() != raw:
                raise ExperimentRegistryError(f"immutable experiment object collision at {path}")
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


def _read_canonical(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
        value = parse_json_strict(raw)
    except (OSError, ArtifactValidationError) as exc:
        raise ExperimentRegistryError(f"immutable experiment record is missing or invalid: {path}") from exc
    if not isinstance(value, dict) or canonicalize(value) != raw:
        raise ExperimentRegistryError(f"experiment record is not canonical JSON: {path}")
    return value


def _validate_spec(spec: dict[str, Any]) -> None:
    required = {
        "schema", "experiment_name", "experiment_class", "parent_experiment_id",
        "hypothesis", "model_family", "population_key", "zone",
        "training_snapshot_sha256", "training_cutoff_draw_id",
        "target_draw_ids", "target_manifest_sha256", "source_evidence_sha256",
        "feature_schema_sha256", "trial_plan", "primary_metric",
        "multiplicity_family", "bootstrap_replicates", "block_length",
        "seed_commitment_sha256", "holdout_accessed", "outcomes_observed",
        "population_claim", "population_evidence_sha256",
    }
    if not isinstance(spec, dict) or set(spec) != required:
        raise ExperimentRegistryError("experiment specification fields do not match the closed preregistration schema")
    if spec["schema"] != EXPERIMENT_SCHEMA:
        raise ExperimentRegistryError("unsupported experiment preregistration schema")
    for field in ("experiment_name", "hypothesis", "model_family", "population_key", "primary_metric"):
        if not isinstance(spec[field], str) or not spec[field].strip():
            raise ExperimentRegistryError(f"{field} must be a non-empty string")
    if spec["experiment_class"] not in ("confirmatory", "exploratory"):
        raise ExperimentRegistryError("experiment_class must be confirmatory or exploratory")
    if spec["zone"] not in ("front", "back", "joint"):
        raise ExperimentRegistryError("zone must be front, back or joint")
    for field in (
        "training_snapshot_sha256", "target_manifest_sha256",
        "source_evidence_sha256", "feature_schema_sha256", "seed_commitment_sha256",
    ):
        if not _is_sha(spec[field]):
            raise ExperimentRegistryError(f"{field} must be a lowercase SHA-256")
    cutoff = spec["training_cutoff_draw_id"]
    if not isinstance(cutoff, str) or re.fullmatch(r"\d{5}", cutoff) is None:
        raise ExperimentRegistryError("training_cutoff_draw_id must be a five-digit draw ID")
    targets = spec["target_draw_ids"]
    if (not isinstance(targets, list) or not targets
            or any(not isinstance(x, str) or re.fullmatch(r"\d{5}", x) is None for x in targets)
            or targets != sorted(set(targets)) or any(x <= cutoff for x in targets)):
        raise ExperimentRegistryError("target IDs must be unique, ascending, and strictly after the training cutoff")
    if spec["holdout_accessed"] is not False:
        raise ExperimentRegistryError("LOT-042 holdout access is prohibited")
    if type(spec["outcomes_observed"]) is not bool:
        raise ExperimentRegistryError("outcomes_observed must be boolean")
    if spec["experiment_class"] == "confirmatory" and spec["outcomes_observed"]:
        raise ExperimentRegistryError("an experiment registered after outcomes were observed must be exploratory")
    if type(spec["bootstrap_replicates"]) is not int or type(spec["block_length"]) is not int:
        raise ExperimentRegistryError("bootstrap_replicates and block_length must be integers")
    if spec["experiment_class"] == "confirmatory" and (
        spec["bootstrap_replicates"] != CONFIRMATORY_BOOTSTRAP_REPLICATES
        or spec["block_length"] != CONFIRMATORY_BLOCK_LENGTH
    ):
        raise ExperimentRegistryError("confirmatory experiments must pin the preregistered 1000 × 50 bootstrap")
    family = spec["multiplicity_family"]
    if (not isinstance(family, list) or any(not isinstance(x, str) or not x for x in family)
            or len(family) != len(set(family))):
        raise ExperimentRegistryError("multiplicity_family must be a unique list of named hypotheses")
    if spec["experiment_class"] == "confirmatory" and not family:
        raise ExperimentRegistryError("confirmatory experiment requires a fixed multiplicity family")
    plan = spec["trial_plan"]
    if not isinstance(plan, list) or not plan or any(not isinstance(x, dict) for x in plan):
        raise ExperimentRegistryError("trial_plan must contain every predeclared trial configuration")
    config_hashes = [_sha(canonicalize(config)) for config in plan]
    if len(config_hashes) != len(set(config_hashes)):
        raise ExperimentRegistryError("trial_plan contains duplicate configurations")
    if spec["population_claim"] not in POPULATION_CLAIMS:
        raise ExperimentRegistryError("population_claim is not an allowed evidence classification")
    evidence = spec["population_evidence_sha256"]
    if spec["population_claim"] in ("distinct_population", "distributionally_distinct") and not _is_sha(evidence):
        raise ExperimentRegistryError("distinct population claims require an evidence manifest digest")
    if evidence is not None and not _is_sha(evidence):
        raise ExperimentRegistryError("population_evidence_sha256 must be null or a lowercase SHA-256")
    parent = spec["parent_experiment_id"]
    if parent is not None and not _is_sha(parent):
        raise ExperimentRegistryError("parent_experiment_id must be null or a content-addressed experiment ID")


class ExperimentRegistry:
    """Append-only experiment and trial registry with immutable preregistrations."""

    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.registrations = self.root / "registrations"
        self.approvals = self.root / "approvals"
        self.events_path = self.root / "events.jsonl"

    def _registration_path(self, experiment_id: str) -> Path:
        if not _is_sha(experiment_id):
            raise ExperimentRegistryError("experiment_id must be a lowercase SHA-256")
        return self.registrations / f"{experiment_id}.json"

    def _approval_path(self, approval_sha256: str) -> Path:
        if not _is_sha(approval_sha256):
            raise ExperimentRegistryError("approval digest is malformed")
        return self.approvals / f"{approval_sha256}.json"

    def _read_events(self) -> list[dict[str, Any]]:
        if not self.events_path.exists():
            return []
        events: list[dict[str, Any]] = []
        previous = "0" * 64
        seen: set[str] = set()
        for line_number, line in enumerate(self.events_path.read_bytes().splitlines(), 1):
            try:
                event = parse_json_strict(line)
            except ArtifactValidationError as exc:
                raise ExperimentRegistryError(f"experiment event line {line_number} is invalid") from exc
            event_id = event.get("event_id")
            body = {key: value for key, value in event.items() if key != "event_hash"}
            if (not isinstance(event_id, str) or not event_id or event_id in seen
                    or event.get("prev_event_hash") != previous
                    or event.get("event_hash") != _sha(canonicalize(body))):
                raise ExperimentRegistryError(f"experiment event hash chain failed at line {line_number}")
            seen.add(event_id)
            previous = event["event_hash"]
            events.append(event)
        return events

    def _append_event_locked(self, body: dict[str, Any]) -> None:
        events = self._read_events()
        event_id = body["event_id"]
        existing = next((x for x in events if x["event_id"] == event_id), None)
        if existing is not None:
            existing_body = {k: v for k, v in existing.items() if k not in ("event_hash", "prev_event_hash")}
            if canonicalize(existing_body) != canonicalize(body):
                raise ExperimentRegistryError("event_id collision has different immutable content")
            return
        previous = events[-1]["event_hash"] if events else "0" * 64
        event_body = {**body, "prev_event_hash": previous}
        event = {**event_body, "event_hash": _sha(canonicalize(event_body))}
        self.events_path.parent.mkdir(parents=True, exist_ok=True)
        with self.events_path.open("ab") as handle:
            handle.write(canonicalize(event) + b"\n")
            handle.flush()
            os.fsync(handle.fileno())

    def _snapshot_unlocked(self) -> dict[str, Any]:
        events = self._read_events()
        experiments: dict[str, dict[str, Any]] = {}
        for event in events:
            experiment_id = event.get("experiment_id")
            if event.get("event_type") == "experiment_registered":
                if experiment_id in experiments:
                    raise ExperimentRegistryError("duplicate experiment registration event")
                registration = _read_canonical(self._registration_path(experiment_id))
                spec = registration.get("spec")
                if (registration.get("experiment_id") != experiment_id
                        or registration.get("spec_sha256") != experiment_id
                        or not isinstance(spec, dict)
                        or _sha(canonicalize(spec)) != experiment_id):
                    raise ExperimentRegistryError("experiment registration content hash mismatch")
                if registration.get("schema") != "lottery.experiment-registration/v1":
                    raise ExperimentRegistryError("unsupported experiment registration record")
                approval_hash = registration.get("approval_sha256")
                if registration["spec"]["experiment_class"] == "confirmatory" and not _is_sha(approval_hash):
                    raise ExperimentRegistryError("confirmatory experiment lacks its immutable approval receipt")
                if approval_hash is not None:
                    approval_path = self._approval_path(approval_hash)
                    approval_raw = approval_path.read_bytes()
                    approval = _read_canonical(approval_path)
                    if (_sha(approval_raw) != approval_hash
                            or approval.get("experiment_id") != experiment_id
                            or approval.get("spec_sha256") != experiment_id):
                        raise ExperimentRegistryError("experiment approval receipt is missing or mismatched")
                experiments[experiment_id] = {"registration": registration, "attempts": {}}
            elif event.get("event_type") == "trial_started":
                if experiment_id not in experiments:
                    raise ExperimentRegistryError("trial references an unregistered experiment")
                attempt_id = event.get("attempt_id")
                attempts = experiments[experiment_id]["attempts"]
                if attempt_id in attempts:
                    raise ExperimentRegistryError("duplicate trial attempt ID")
                spec = experiments[experiment_id]["registration"]["spec"]
                allowed = {_sha(canonicalize(x)) for x in spec["trial_plan"]}
                if event.get("config_sha256") not in allowed:
                    raise ExperimentRegistryError("trial config was not preregistered")
                attempts[attempt_id] = {
                    "attempt_id": attempt_id,
                    "config_sha256": event["config_sha256"],
                    "status": "running",
                    "started_at_utc": event["occurred_at_utc"],
                    "finished_at_utc": None,
                    "artifact_sha256": None,
                    "result_sha256": None,
                    "failure_code": None,
                }
            elif event.get("event_type") == "trial_finished":
                if experiment_id not in experiments:
                    raise ExperimentRegistryError("trial completion references an unregistered experiment")
                attempt_id = event.get("attempt_id")
                attempt = experiments[experiment_id]["attempts"].get(attempt_id)
                if attempt is None or attempt["status"] != "running":
                    raise ExperimentRegistryError("terminal trial event has no running attempt")
                attempt.update({
                    "status": event["terminal_status"],
                    "finished_at_utc": event["occurred_at_utc"],
                    "artifact_sha256": event["artifact_sha256"],
                    "result_sha256": event["result_sha256"],
                    "failure_code": event["failure_code"],
                })
            else:
                raise ExperimentRegistryError("unknown experiment event type")
        return {"experiments": experiments, "event_count": len(events)}

    def snapshot(self) -> dict[str, Any]:
        with ledger_lock(self.events_path):
            return self._snapshot_unlocked()

    def register_experiment(
        self,
        spec: dict[str, Any],
        *,
        actor: str,
        approval: dict[str, Any] | None = None,
        approval_verifier: Callable[[dict[str, Any], dict[str, Any]], bool] | None = None,
    ) -> dict[str, Any]:
        _validate_spec(spec)
        if not isinstance(actor, str) or not actor:
            raise ValueError("actor must be a non-empty string")
        spec_raw = canonicalize(spec)
        experiment_id = _sha(spec_raw)
        approval_hash = None
        with ledger_lock(self.events_path):
            snapshot = self._snapshot_unlocked()
            existing = snapshot["experiments"].get(experiment_id)
            if existing is not None:
                registration = existing["registration"]
                return {
                    "experiment_id": experiment_id,
                    "spec_sha256": experiment_id,
                    "approval_sha256": registration.get("approval_sha256"),
                }
            parent_id = spec["parent_experiment_id"]
            if parent_id is not None:
                parent = snapshot["experiments"].get(parent_id)
                if parent is None:
                    raise ExperimentRegistryError("parent experiment is not registered")
                parent_has_results = any(
                    attempt["status"] != "running"
                    for attempt in parent["attempts"].values()
                ) or parent["registration"]["spec"]["outcomes_observed"]
                if parent_has_results and spec["experiment_class"] != "exploratory":
                    raise ExperimentRegistryError("post-result child experiments must be exploratory")
            if spec["experiment_class"] == "confirmatory":
                if approval is None or approval_verifier is None:
                    raise ExperimentApprovalError("confirmatory registration requires a protected approval verifier")
                expected = {
                    "experiment_id": experiment_id,
                    "spec_sha256": experiment_id,
                    "policy": "LOT-064-confirmatory-v1",
                }
                if approval_verifier(approval, expected) is not True:
                    raise ExperimentApprovalError("protected preregistration approval was absent or rejected")
                if (approval.get("experiment_id") != experiment_id
                        or approval.get("spec_sha256") != experiment_id):
                    raise ExperimentApprovalError("approval does not bind the exact preregistration digest")
                approval_raw = canonicalize(approval)
                approval_hash = _sha(approval_raw)
                _write_once(self._approval_path(approval_hash), approval_raw)
            path = self._registration_path(experiment_id)
            registration = {
                "schema": "lottery.experiment-registration/v1",
                "experiment_id": experiment_id,
                "spec_sha256": experiment_id,
                "spec": spec,
                "approval_sha256": approval_hash,
            }
            _write_once(path, canonicalize(registration))
            if experiment_id not in snapshot["experiments"]:
                self._append_event_locked({
                    "event_id": f"register:{experiment_id}",
                    "event_type": "experiment_registered",
                    "occurred_at_utc": datetime.now(timezone.utc).isoformat(),
                    "actor": actor,
                    "experiment_id": experiment_id,
                    "approval_sha256": approval_hash,
                })
            return {"experiment_id": experiment_id, "spec_sha256": experiment_id, "approval_sha256": approval_hash}

    def start_trial(
        self,
        *,
        experiment_id: str,
        attempt_id: str,
        config: dict[str, Any],
        actor: str,
    ) -> dict[str, Any]:
        if not _is_sha(experiment_id):
            raise ExperimentRegistryError("experiment_id is malformed")
        if not isinstance(attempt_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", attempt_id):
            raise ValueError("attempt_id must be a canonical 1-128 character identifier")
        if not isinstance(config, dict):
            raise TypeError("trial config must be an object")
        if not isinstance(actor, str) or not actor:
            raise ValueError("actor must be a non-empty string")
        config_hash = _sha(canonicalize(config))
        with ledger_lock(self.events_path):
            snapshot = self._snapshot_unlocked()
            experiment = snapshot["experiments"].get(experiment_id)
            if experiment is None:
                raise ExperimentRegistryError("experiment must be preregistered before a trial starts")
            spec = experiment["registration"]["spec"]
            allowed = {_sha(canonicalize(x)) for x in spec["trial_plan"]}
            if config_hash not in allowed:
                raise ExperimentRegistryError("trial configuration was not included in the immutable preregistration")
            if attempt_id in experiment["attempts"]:
                existing = experiment["attempts"][attempt_id]
                if existing["config_sha256"] == config_hash and existing["status"] == "running":
                    return existing
                raise ExperimentRegistryError("attempt_id already exists with a different or terminal state")
            event_id = _sha(f"{experiment_id}:{attempt_id}:start".encode("utf-8"))
            self._append_event_locked({
                "event_id": event_id,
                "event_type": "trial_started",
                "occurred_at_utc": datetime.now(timezone.utc).isoformat(),
                "actor": actor,
                "experiment_id": experiment_id,
                "attempt_id": attempt_id,
                "config_sha256": config_hash,
            })
            return self._snapshot_unlocked()["experiments"][experiment_id]["attempts"][attempt_id]

    def finish_trial(
        self,
        *,
        experiment_id: str,
        attempt_id: str,
        terminal_status: str,
        actor: str,
        artifact_sha256: str | None = None,
        result_sha256: str | None = None,
        failure_code: str | None = None,
    ) -> dict[str, Any]:
        if terminal_status not in TERMINAL_STATUSES:
            raise ExperimentRegistryError("trial terminal_status is not in the closed status set")
        if not isinstance(actor, str) or not actor:
            raise ValueError("actor must be a non-empty string")
        if artifact_sha256 is not None and not _is_sha(artifact_sha256):
            raise ExperimentRegistryError("artifact_sha256 must be null or a lowercase SHA-256")
        if result_sha256 is not None and not _is_sha(result_sha256):
            raise ExperimentRegistryError("result_sha256 must be null or a lowercase SHA-256")
        if terminal_status == "succeeded":
            if result_sha256 is None:
                raise ExperimentRegistryError("successful trial requires a result digest")
        elif not isinstance(failure_code, str) or not failure_code:
            raise ExperimentRegistryError("failed trial must retain a stable failure_code")
        with ledger_lock(self.events_path):
            snapshot = self._snapshot_unlocked()
            experiment = snapshot["experiments"].get(experiment_id)
            if experiment is None:
                raise ExperimentRegistryError("experiment is not registered")
            attempt = experiment["attempts"].get(attempt_id)
            if attempt is None:
                raise ExperimentRegistryError("trial attempt was never started")
            if attempt["status"] != "running":
                same = (
                    attempt["status"] == terminal_status
                    and attempt["artifact_sha256"] == artifact_sha256
                    and attempt["result_sha256"] == result_sha256
                    and attempt["failure_code"] == failure_code
                )
                if same:
                    return attempt
                raise ExperimentRegistryError("terminal trial attempt cannot be overwritten")
            event_id = _sha(f"{experiment_id}:{attempt_id}:finish".encode("utf-8"))
            self._append_event_locked({
                "event_id": event_id,
                "event_type": "trial_finished",
                "occurred_at_utc": datetime.now(timezone.utc).isoformat(),
                "actor": actor,
                "experiment_id": experiment_id,
                "attempt_id": attempt_id,
                "terminal_status": terminal_status,
                "artifact_sha256": artifact_sha256,
                "result_sha256": result_sha256,
                "failure_code": failure_code,
            })
            return self._snapshot_unlocked()["experiments"][experiment_id]["attempts"][attempt_id]
