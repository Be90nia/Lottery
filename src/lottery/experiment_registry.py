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

from .execution_context import ExecutionContextError, validate_execution_context
from .ledger_lock import ledger_lock
from .subset_model.artifact import canonicalize, parse_json_strict, ArtifactValidationError
from .storage import FileSystemObjectStore, StorageError


EXPERIMENT_SCHEMA = "lottery.experiment-preregistration/v1"
EVENT_SCHEMA = "lottery.experiment-event/v1"
CONFIRMATORY_BOOTSTRAP_REPLICATES = 1000
CONFIRMATORY_BLOCK_LENGTH = 50
TERMINAL_STATUSES = {
    "succeeded", "completed_uncommitted", "fit_failed", "invalid_artifact", "runner_error", "timeout", "cancelled", "abandoned"
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


def _execution_binding_expectations(
    experiment_id: str, experiment: dict[str, Any], attempt: dict[str, Any],
    attempt_id: str, execution_id: str,
) -> dict[str, Any]:
    registration = experiment["registration"]
    spec = registration["spec"]
    expected = {
        "experiment_id": experiment_id,
        "spec_sha256": registration["spec_sha256"],
        "experiment_class": spec["experiment_class"],
        "approval_sha256": attempt.get("approval_sha256"),
        "approval_required": spec["experiment_class"] == "confirmatory",
        "trial_id": attempt["config_sha256"],
        "registry_attempt_id": attempt_id,
        "execution_id": execution_id,
        "execution_context": attempt["execution_context"],
    }
    config = next(
        item for item in spec["trial_plan"]
        if _sha(canonicalize(item)) == attempt["config_sha256"]
    )
    if (config.get("target_manifest_sha256") is not None
            and config.get("target_manifest_sha256") != spec.get("target_manifest_sha256")):
        raise ExperimentRegistryError("trial target manifest digest differs from experiment registration")
    expected["_expected_target_draw_ids"] = spec["target_draw_ids"]
    if isinstance(config.get("zones"), list) and isinstance(config.get("model_order"), list):
        expected["_expected_model_pairs"] = [
            (zone, model_name)
            for zone in config["zones"]
            for model_name in config["model_order"]
        ]
    if isinstance(config.get("target_manifest_sha256"), str):
        expected["_expected_target_manifest_sha256"] = config["target_manifest_sha256"]
    expected["approval_disposition"] = config.get(
        "approval_disposition",
        "not_required_exploratory" if spec["experiment_class"] == "exploratory"
        else "protected_approval",
    )
    for field in (
        "approval_disposition_reason", "legacy_parent_issue_url",
        "legacy_child_registration_comment_url",
        "legacy_child_registration_comment_sha256", "parent_lineage_disposition",
    ):
        if field in config:
            expected[field] = config[field]
    return expected


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
                    or event.get("schema") != EVENT_SCHEMA or canonicalize(event) != line
                    or event.get("prev_event_hash") != previous
                    or event.get("event_hash") != _sha(canonicalize(body))):
                raise ExperimentRegistryError(f"experiment event hash chain failed at line {line_number}")
            seen.add(event_id)
            previous = event["event_hash"]
            events.append(event)
        return events

    def _append_event_locked(self, body: dict[str, Any]) -> None:
        if not isinstance(body, dict) or body.get("schema") != EVENT_SCHEMA:
            raise ExperimentRegistryError("experiment event does not match the closed event schema")
        required_fields = {
            "experiment_registered": {
                "schema", "event_id", "event_type", "occurred_at_utc", "actor",
                "experiment_id", "approval_sha256",
            },
            "trial_started": {
                "schema", "event_id", "event_type", "occurred_at_utc", "actor",
                "experiment_id", "attempt_id", "config_sha256",
            },
            "artifacts_committed": {
                "schema", "event_id", "event_type", "occurred_at_utc", "actor",
                "experiment_id", "attempt_id", "execution_id", "storage_receipts_sha256",
                "result_sha256", "artifact_sha256", "output_files",
            },
            "trial_finished": {
                "schema", "event_id", "event_type", "occurred_at_utc", "actor",
                "experiment_id", "attempt_id", "terminal_status", "artifact_sha256",
                "result_sha256", "failure_code",
            },
        }
        optional_fields = {
            "experiment_registered": set(),
            "trial_started": {
                "execution_context", "approval_sha256", "source_metadata_sha256",
                "source_verification_receipt_sha256", "source_started_at_utc",
                "source_run_url", "imported",
            },
            "artifacts_committed": set(),
            "trial_finished": {
                "execution_id", "approval_sha256", "storage_receipts_sha256",
                "source_metadata_sha256", "source_verification_receipt_sha256",
                "source_started_at_utc", "source_completed_at_utc", "source_run_url",
                "source_artifact_id", "source_artifact_zip_sha256",
                "scientific_result_status", "confirmatory_eligible", "imported",
            },
        }
        event_type = body.get("event_type")
        required = required_fields.get(event_type)
        if required is None or not required <= set(body) or set(body) - required - optional_fields[event_type]:
            raise ExperimentRegistryError("experiment event fields do not match the closed event schema")
        if (not isinstance(body.get("event_id"), str) or not body["event_id"]
                or not isinstance(body.get("actor"), str) or not body["actor"]
                or not _is_sha(body.get("experiment_id"))):
            raise ExperimentRegistryError("experiment event identity fields are invalid")
        try:
            datetime.fromisoformat(body["occurred_at_utc"])
        except (TypeError, ValueError) as exc:
            raise ExperimentRegistryError("experiment event timestamp is invalid") from exc
        approval_hash = body.get("approval_sha256")
        if approval_hash is not None and not _is_sha(approval_hash):
            raise ExperimentRegistryError("experiment event approval digest is invalid")
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

    def _verify_historical_import_evidence(
        self, *, source_metadata_sha256: str, source_verification_receipt_sha256: str,
        execution_context: dict[str, Any], source_started_at_utc: str,
        source_completed_at_utc: str | None = None, source_artifact_id: int | None = None,
        source_artifact_zip_sha256: str | None = None,
        scientific_result_status: str | None = None,
        source_result_sha256: str | None = None, source_artifact_sha256: str | None = None,
    ) -> None:
        if not _is_sha(source_metadata_sha256) or not _is_sha(source_verification_receipt_sha256):
            raise ExperimentRegistryError("historical import evidence references malformed digests")
        try:
            source_metadata = _read_canonical(
                self.root / "historical-source-metadata" / f"{source_metadata_sha256}.json"
            )
            verification = _read_canonical(
                self.root / "github-actions-verification" / f"{source_verification_receipt_sha256}.json"
            )
        except ExperimentRegistryError as exc:
            raise ExperimentRegistryError("historical import source metadata or verification receipt is missing/invalid") from exc
        if (_sha(canonicalize(source_metadata)) != source_metadata_sha256
                or _sha(canonicalize(verification)) != source_verification_receipt_sha256
                or verification.get("schema") != "lottery.github-actions-verification/v1"
                or verification.get("verified") is not True
                or verification.get("source_metadata_sha256") != source_metadata_sha256
                or verification.get("artifact_zip_sha256") != source_metadata.get("source_artifact_zip_sha256")
                or verification.get("source_evidence_sha256") != source_metadata.get("source_evidence_sha256")
                or source_metadata.get("source_run_url") != execution_context.get("run_url")
                or source_metadata.get("source_started_at_utc") != source_started_at_utc
                or source_metadata.get("confirmatory_eligible") is not False):
            raise ExperimentRegistryError("historical import evidence does not resolve to the exact execution/source identity")
        if source_completed_at_utc is not None and (
            source_metadata.get("source_completed_at_utc") != source_completed_at_utc
            or source_metadata.get("source_artifact_id") != source_artifact_id
            or source_metadata.get("source_artifact_zip_sha256") != source_artifact_zip_sha256
            or source_metadata.get("scientific_result_status") != scientific_result_status
            or source_metadata.get("source_manifest_sha256") != source_result_sha256
            or source_metadata.get("source_model_artifacts_sha256") != source_artifact_sha256
        ):
            raise ExperimentRegistryError("historical import terminal event conflicts with its immutable source metadata")

    @staticmethod
    def _assert_execution_identity_unbound(
        snapshot: dict[str, Any], *, execution_id: str,
        experiment_id: str, attempt_id: str,
    ) -> None:
        for other_experiment_id, experiment in snapshot["experiments"].items():
            for other_attempt_id, attempt in experiment["attempts"].items():
                if (attempt.get("execution_id") == execution_id
                        and (other_experiment_id, other_attempt_id) != (experiment_id, attempt_id)):
                    raise ExperimentRegistryError(
                        "one GitHub Actions execution cannot be bound to multiple trial attempts"
                    )

    def _snapshot_unlocked(self) -> dict[str, Any]:
        events = self._read_events()
        experiments: dict[str, dict[str, Any]] = {}
        execution_ids: dict[str, tuple[str, str]] = {}
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
                approval_hash = experiments[experiment_id]["registration"].get("approval_sha256")
                if "approval_sha256" in event and event["approval_sha256"] != approval_hash:
                    raise ExperimentRegistryError("trial start approval receipt does not match registration")
                execution_context = event.get("execution_context")
                if execution_context is not None:
                    try:
                        validate_execution_context(
                            execution_context,
                            expected_repository=execution_context.get("repository"),
                            expected_repository_id=execution_context.get("repository_id"),
                            expected_workflow_id=execution_context.get("workflow_id"),
                            expected_workflow_path=execution_context.get("workflow_path"),
                        )
                    except (ExecutionContextError, AttributeError) as exc:
                        raise ExperimentRegistryError("trial execution context is invalid") from exc
                    execution_id = execution_context["execution_id"]
                    if execution_id in execution_ids:
                        raise ExperimentRegistryError(
                            "one GitHub Actions execution cannot be bound to multiple trial attempts"
                        )
                    execution_ids[execution_id] = (experiment_id, attempt_id)
                if event.get("imported") is True:
                    self._verify_historical_import_evidence(
                        source_metadata_sha256=event.get("source_metadata_sha256"),
                        source_verification_receipt_sha256=event.get("source_verification_receipt_sha256"),
                        execution_context=execution_context,
                        source_started_at_utc=event.get("source_started_at_utc"),
                    )
                attempts[attempt_id] = {
                    "attempt_id": attempt_id,
                    "config_sha256": event["config_sha256"],
                    "trial_id": event["config_sha256"],
                    "execution_context": execution_context,
                    "execution_id": execution_context.get("execution_id") if execution_context else None,
                    "approval_sha256": approval_hash,
                    "status": "running",
                    "started_at_utc": event["occurred_at_utc"],
                    "finished_at_utc": None,
                    "artifact_sha256": None,
                    "result_sha256": None,
                    "failure_code": None,
                    "source_metadata_sha256": event.get("source_metadata_sha256"),
                    "source_verification_receipt_sha256": event.get("source_verification_receipt_sha256"),
                    "source_started_at_utc": event.get("source_started_at_utc"),
                    "source_run_url": event.get("source_run_url"),
                    "imported": event.get("imported", False),
                    "artifacts_committed": None,
                }
            elif event.get("event_type") == "artifacts_committed":
                if experiment_id not in experiments:
                    raise ExperimentRegistryError("artifact commit references an unregistered experiment")
                attempt_id = event.get("attempt_id")
                attempt = experiments[experiment_id]["attempts"].get(attempt_id)
                if attempt is None or attempt["status"] != "running":
                    raise ExperimentRegistryError("artifact commit has no running execution attempt")
                if (attempt.get("execution_context") is None
                        or event.get("execution_id") != attempt.get("execution_id")):
                    raise ExperimentRegistryError("artifact commit execution identity does not match trial start")
                if attempt.get("artifacts_committed") is not None:
                    raise ExperimentRegistryError("execution attempt has more than one artifact commit event")
                if (not _is_sha(event.get("storage_receipts_sha256"))
                        or not _is_sha(event.get("result_sha256"))
                        or not _is_sha(event.get("artifact_sha256"))
                        or not isinstance(event.get("output_files"), list)
                        or not event["output_files"]
                        or any(not isinstance(name, str) or Path(name).name != name for name in event["output_files"])
                        or event["output_files"] != sorted(set(event["output_files"]))):
                    raise ExperimentRegistryError("artifact commit event identity or output list is invalid")
                self._verify_execution_storage_receipts(
                    execution_id=attempt["execution_id"],
                    expected_producer_commit=attempt["execution_context"]["sha"],
                    result_sha256=event["result_sha256"],
                    artifact_sha256=event["artifact_sha256"],
                    expected_receipts_sha256=event["storage_receipts_sha256"],
                    expected_binding=_execution_binding_expectations(
                        experiment_id, experiments[experiment_id], attempt, attempt_id,
                        attempt["execution_id"],
                    ),
                )
                bundle = _read_canonical(self.root / "storage-receipts" / f"{attempt['execution_id']}.json")
                if event["output_files"] != sorted(bundle):
                    raise ExperimentRegistryError("artifact commit event output coverage differs from LOT-065 receipt bundle")
                attempt["artifacts_committed"] = {
                    "event_id": event["event_id"],
                    "event_hash": event["event_hash"],
                    "execution_id": event["execution_id"],
                    "storage_receipts_sha256": event["storage_receipts_sha256"],
                    "result_sha256": event["result_sha256"],
                    "artifact_sha256": event["artifact_sha256"],
                    "output_files": event["output_files"],
                    "occurred_at_utc": event["occurred_at_utc"],
                }
            elif event.get("event_type") == "trial_finished":
                if experiment_id not in experiments:
                    raise ExperimentRegistryError("trial completion references an unregistered experiment")
                attempt_id = event.get("attempt_id")
                attempt = experiments[experiment_id]["attempts"].get(attempt_id)
                if attempt is None or attempt["status"] != "running":
                    raise ExperimentRegistryError("terminal trial event has no running attempt")
                if event.get("execution_id") != attempt.get("execution_id"):
                    raise ExperimentRegistryError("terminal event execution identity does not match trial start")
                if "approval_sha256" in event and event["approval_sha256"] != attempt.get("approval_sha256"):
                    raise ExperimentRegistryError("terminal event approval receipt does not match trial start")
                terminal_status = event.get("terminal_status")
                if terminal_status not in TERMINAL_STATUSES:
                    raise ExperimentRegistryError("terminal event status is outside the closed status set")
                if terminal_status == "completed_uncommitted":
                    if (event.get("imported") is not True
                            or not _is_sha(event.get("source_metadata_sha256"))
                            or not _is_sha(event.get("source_verification_receipt_sha256"))
                            or event.get("confirmatory_eligible") is not False
                            or event.get("storage_receipts_sha256") is not None
                            or not isinstance(event.get("source_completed_at_utc"), str)):
                        raise ExperimentRegistryError("completed_uncommitted terminal event lacks verified retrospective-import lineage")
                    self._verify_historical_import_evidence(
                        source_metadata_sha256=event["source_metadata_sha256"],
                        source_verification_receipt_sha256=event["source_verification_receipt_sha256"],
                        execution_context=attempt["execution_context"],
                        source_started_at_utc=event["source_started_at_utc"],
                        source_completed_at_utc=event["source_completed_at_utc"],
                        source_artifact_id=event["source_artifact_id"],
                        source_artifact_zip_sha256=event["source_artifact_zip_sha256"],
                        scientific_result_status=event["scientific_result_status"],
                        source_result_sha256=event["result_sha256"],
                        source_artifact_sha256=event["artifact_sha256"],
                    )
                if terminal_status == "succeeded" and attempt.get("execution_context") is not None:
                    committed = attempt.get("artifacts_committed")
                    legacy_first_producer = (
                        attempt.get("execution_context", {}).get("sha")
                        == "1bf59f4c23f8082eb9289d3ae8ae3603312ebe05"
                    )
                    if not legacy_first_producer and (
                            not isinstance(committed, dict)
                            or committed.get("execution_id") != attempt.get("execution_id")
                            or committed.get("storage_receipts_sha256") != event.get("storage_receipts_sha256")
                            or committed.get("result_sha256") != event.get("result_sha256")
                            or committed.get("artifact_sha256") != event.get("artifact_sha256")):
                        raise ExperimentRegistryError("execution-bound success requires a matching append-only artifact commit event")
                    storage_digest = event.get("storage_receipts_sha256")
                    if not _is_sha(storage_digest):
                        raise ExperimentRegistryError("execution-bound success event is missing LOT-065 receipt digest")
                    self._verify_execution_storage_receipts(
                        execution_id=attempt["execution_id"],
                        expected_producer_commit=attempt["execution_context"]["sha"],
                        result_sha256=event["result_sha256"],
                        artifact_sha256=event["artifact_sha256"],
                        expected_receipts_sha256=storage_digest,
                        expected_binding=_execution_binding_expectations(
                            experiment_id, experiments[experiment_id], attempt, attempt_id,
                            attempt["execution_id"],
                        ),
                    )
                attempt.update({
                    "status": event["terminal_status"],
                    "finished_at_utc": event["occurred_at_utc"],
                    "artifact_sha256": event["artifact_sha256"],
                    "result_sha256": event["result_sha256"],
                    "storage_receipts_sha256": event.get("storage_receipts_sha256"),
                    "failure_code": event["failure_code"],
                    "source_metadata_sha256": event.get("source_metadata_sha256"),
                    "source_verification_receipt_sha256": event.get("source_verification_receipt_sha256"),
                    "source_started_at_utc": event.get("source_started_at_utc"),
                    "source_completed_at_utc": event.get("source_completed_at_utc"),
                    "source_run_url": event.get("source_run_url"),
                    "source_artifact_id": event.get("source_artifact_id"),
                    "source_artifact_zip_sha256": event.get("source_artifact_zip_sha256"),
                    "scientific_result_status": event.get("scientific_result_status"),
                    "confirmatory_eligible": event.get("confirmatory_eligible"),
                    "imported": event.get("imported", False),
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
                    "schema": EVENT_SCHEMA,
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
        execution_context: dict[str, Any] | None = None,
        expected_repository: str | None = None,
        expected_repository_id: str | None = None,
        expected_workflow_id: int | None = None,
        expected_workflow_path: str | None = None,
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
        if execution_context is not None:
            if not all((expected_repository, expected_repository_id, expected_workflow_id, expected_workflow_path)):
                raise ExperimentRegistryError("execution context requires an explicit repository/workflow allowlist")
            try:
                execution_context = validate_execution_context(
                    execution_context,
                    expected_repository=expected_repository,
                    expected_repository_id=expected_repository_id,
                    expected_workflow_id=expected_workflow_id,
                    expected_workflow_path=expected_workflow_path,
                )
            except ExecutionContextError as exc:
                raise ExperimentRegistryError("trial execution context is invalid") from exc
        elif any((expected_repository, expected_repository_id, expected_workflow_id, expected_workflow_path)):
            raise ExperimentRegistryError("execution allowlist cannot be supplied without an execution context")
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
                if (existing["config_sha256"] == config_hash
                        and existing["execution_context"] == execution_context
                        and existing["status"] == "running"):
                    return existing
                raise ExperimentRegistryError("attempt_id already exists with a different or terminal state")
            if execution_context is not None:
                self._assert_execution_identity_unbound(
                    snapshot, execution_id=execution_context["execution_id"],
                    experiment_id=experiment_id, attempt_id=attempt_id,
                )
            event_id = _sha(f"{experiment_id}:{attempt_id}:start".encode("utf-8"))
            self._append_event_locked({
                "schema": EVENT_SCHEMA,
                "event_id": event_id,
                "event_type": "trial_started",
                "occurred_at_utc": datetime.now(timezone.utc).isoformat(),
                "actor": actor,
                "experiment_id": experiment_id,
                "attempt_id": attempt_id,
                "config_sha256": config_hash,
                "execution_context": execution_context,
                "approval_sha256": experiment["registration"].get("approval_sha256"),
            })
            return self._snapshot_unlocked()["experiments"][experiment_id]["attempts"][attempt_id]

    def import_completed_trial(
        self, *, experiment_id: str, attempt_id: str, config: dict[str, Any],
        actor: str, execution_context: dict[str, Any], source_metadata: dict[str, Any],
        metadata_verifier: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]],
        expected_repository: str, expected_repository_id: str,
        expected_workflow_id: int, expected_workflow_path: str,
    ) -> dict[str, Any]:
        """Append an honest retrospective import; source times never replace registry times."""
        if not _is_sha(experiment_id):
            raise ExperimentRegistryError("experiment_id is malformed")
        if not isinstance(attempt_id, str) or not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", attempt_id
        ):
            raise ValueError("attempt_id must be a canonical 1-128 character identifier")
        if not isinstance(actor, str) or not actor:
            raise ValueError("actor must be a non-empty string")
        if not callable(metadata_verifier):
            raise ExperimentRegistryError("historical import requires a trusted GitHub metadata verifier")
        try:
            context = validate_execution_context(
                execution_context,
                expected_repository=expected_repository,
                expected_repository_id=expected_repository_id,
                expected_workflow_id=expected_workflow_id,
                expected_workflow_path=expected_workflow_path,
            )
        except ExecutionContextError as exc:
            raise ExperimentRegistryError("historical execution context is invalid") from exc
        required_source = {
            "source_run_url", "source_started_at_utc", "source_completed_at_utc",
            "source_artifact_id", "source_artifact_zip_sha256", "source_manifest_sha256",
            "source_model_artifacts_sha256", "source_evidence_sha256", "scientific_result_status", "confirmatory_eligible",
        }
        if not isinstance(source_metadata, dict) or set(source_metadata) != required_source:
            raise ExperimentRegistryError("historical source metadata fields do not match the closed import schema")
        if (source_metadata["source_run_url"] != context["run_url"]
                or source_metadata["confirmatory_eligible"] is not False
                or not isinstance(source_metadata["source_artifact_id"], int)
                or source_metadata["source_artifact_id"] <= 0
                or not isinstance(source_metadata["scientific_result_status"], str)
                or not source_metadata["scientific_result_status"]):
            raise ExperimentRegistryError("historical source metadata conflicts with the execution identity or exploratory boundary")
        for field in ("source_artifact_zip_sha256", "source_manifest_sha256", "source_model_artifacts_sha256", "source_evidence_sha256"):
            if not _is_sha(source_metadata[field]):
                raise ExperimentRegistryError(f"{field} must be a lowercase SHA-256")
        parsed_times = []
        for field in ("source_started_at_utc", "source_completed_at_utc"):
            try:
                value = datetime.fromisoformat(source_metadata[field].replace("Z", "+00:00"))
            except (AttributeError, TypeError, ValueError) as exc:
                raise ExperimentRegistryError(f"{field} is not an ISO-8601 timestamp") from exc
            if value.tzinfo is None or value.utcoffset() is None:
                raise ExperimentRegistryError(f"{field} must be timezone-aware")
            parsed_times.append(value)
        if parsed_times[0] >= parsed_times[1]:
            raise ExperimentRegistryError("historical source start must precede source completion")
        source_metadata_sha256 = _sha(canonicalize(source_metadata))
        verification = metadata_verifier(source_metadata, context)
        verification_fields = {
            "schema", "verifier_id", "verified", "source_metadata_sha256",
            "artifact_zip_sha256", "source_evidence_sha256", "verified_at_utc",
        }
        if (not isinstance(verification, dict) or set(verification) != verification_fields
                or verification.get("schema") != "lottery.github-actions-verification/v1"
                or verification.get("verified") is not True
                or verification.get("source_metadata_sha256") != source_metadata_sha256
                or verification.get("artifact_zip_sha256") != source_metadata["source_artifact_zip_sha256"]
                or verification.get("source_evidence_sha256") != source_metadata["source_evidence_sha256"]
                or not isinstance(verification.get("verifier_id"), str)
                or not verification["verifier_id"]):
            raise ExperimentRegistryError("trusted GitHub metadata verifier did not attest the exact historical source")
        try:
            verified_at = datetime.fromisoformat(verification["verified_at_utc"].replace("Z", "+00:00"))
        except (AttributeError, TypeError, ValueError) as exc:
            raise ExperimentRegistryError("GitHub verification receipt timestamp is invalid") from exc
        if verified_at.tzinfo is None or verified_at.utcoffset() is None:
            raise ExperimentRegistryError("GitHub verification receipt timestamp must be timezone-aware")
        verification_receipt_sha256 = _sha(canonicalize(verification))
        config_sha256 = _sha(canonicalize(config))
        with ledger_lock(self.events_path):
            snapshot = self._snapshot_unlocked()
            experiment = snapshot["experiments"].get(experiment_id)
            if experiment is None:
                raise ExperimentRegistryError("historical import requires a content-addressed registration")
            spec = experiment["registration"]["spec"]
            if spec["experiment_class"] != "exploratory" or spec["outcomes_observed"] is not True:
                raise ExperimentRegistryError("post-outcome historical imports must remain exploratory")
            if config_sha256 not in {_sha(canonicalize(item)) for item in spec["trial_plan"]}:
                raise ExperimentRegistryError("historical import config was not in the immutable trial plan")
            existing = experiment["attempts"].get(attempt_id)
            if existing is None:
                self._assert_execution_identity_unbound(
                    snapshot, execution_id=context["execution_id"],
                    experiment_id=experiment_id, attempt_id=attempt_id,
                )
            resume_partial_import = False
            if existing is not None:
                same_source = (
                    existing.get("imported") is True
                    and existing.get("source_metadata_sha256") == source_metadata_sha256
                    and existing.get("execution_id") == context["execution_id"]
                    and existing.get("config_sha256") == config_sha256
                )
                if not same_source:
                    raise ExperimentRegistryError("historical attempt ID already exists with conflicting evidence")
                verification_receipt_sha256 = existing["source_verification_receipt_sha256"]
                if existing.get("status") == "completed_uncommitted":
                    return existing
                if existing.get("status") != "running":
                    raise ExperimentRegistryError("historical attempt is in a non-recoverable terminal state")
                resume_partial_import = True
            else:
                _write_once(
                    self.root / "historical-source-metadata" / f"{source_metadata_sha256}.json",
                    canonicalize(source_metadata),
                )
                _write_once(
                    self.root / "github-actions-verification" / f"{verification_receipt_sha256}.json",
                    canonicalize(verification),
                )
            approval_sha256 = experiment["registration"].get("approval_sha256")
            if approval_sha256 is not None:
                raise ExperimentRegistryError("exploratory historical import must not fabricate an approval receipt")
            start_event_id = _sha(f"{experiment_id}:{attempt_id}:import-start".encode("utf-8"))
            finish_event_id = _sha(f"{experiment_id}:{attempt_id}:import-finish".encode("utf-8"))
            recorded_at = datetime.now(timezone.utc).isoformat()
            common = {
                "source_metadata_sha256": source_metadata_sha256,
                "source_verification_receipt_sha256": verification_receipt_sha256,
                "source_started_at_utc": source_metadata["source_started_at_utc"],
                "source_run_url": source_metadata["source_run_url"],
                "imported": True,
            }
            if not resume_partial_import:
                self._append_event_locked({
                    "schema": EVENT_SCHEMA,
                    "event_id": start_event_id,
                    "event_type": "trial_started",
                    "occurred_at_utc": recorded_at,
                    "actor": actor,
                    "experiment_id": experiment_id,
                    "attempt_id": attempt_id,
                    "config_sha256": config_sha256,
                    "execution_context": context,
                    "approval_sha256": None,
                    **common,
                })
            self._append_event_locked({
                "schema": EVENT_SCHEMA,
                "event_id": finish_event_id,
                "event_type": "trial_finished",
                "occurred_at_utc": datetime.now(timezone.utc).isoformat(),
                "actor": actor,
                "experiment_id": experiment_id,
                "attempt_id": attempt_id,
                "terminal_status": "completed_uncommitted",
                "artifact_sha256": source_metadata["source_model_artifacts_sha256"],
                "result_sha256": source_metadata["source_manifest_sha256"],
                "failure_code": None,
                "execution_id": context["execution_id"],
                "approval_sha256": None,
                "storage_receipts_sha256": None,
                "source_metadata_sha256": source_metadata_sha256,
                "source_verification_receipt_sha256": verification_receipt_sha256,
                "source_started_at_utc": source_metadata["source_started_at_utc"],
                "source_completed_at_utc": source_metadata["source_completed_at_utc"],
                "source_run_url": source_metadata["source_run_url"],
                "source_artifact_id": source_metadata["source_artifact_id"],
                "source_artifact_zip_sha256": source_metadata["source_artifact_zip_sha256"],
                "scientific_result_status": source_metadata["scientific_result_status"],
                "confirmatory_eligible": False,
                "imported": True,
            })
            return self._snapshot_unlocked()["experiments"][experiment_id]["attempts"][attempt_id]

    def _verify_execution_storage_receipts(
        self, *, execution_id: str, expected_producer_commit: str,
        result_sha256: str, artifact_sha256: str, expected_receipts_sha256: str,
        expected_binding: dict[str, Any],
    ) -> None:
        """Resolve every LOT-065 receipt to committed bytes before terminal success."""
        bundle_path = self.root / "storage-receipts" / f"{execution_id}.json"
        try:
            bundle_raw = bundle_path.read_bytes()
            bundle = parse_json_strict(bundle_raw)
        except (OSError, ArtifactValidationError) as exc:
            raise ExperimentRegistryError("execution-bound success requires a LOT-065 storage receipts bundle") from exc
        if (not isinstance(bundle, dict) or canonicalize(bundle) != bundle_raw
                or _sha(bundle_raw) != expected_receipts_sha256):
            raise ExperimentRegistryError("LOT-065 storage receipts bundle digest or canonical form is invalid")
        required_outputs = {
            "run_manifest.json", "subset-model-rolling-origin.json",
            "target-score-ledger.jsonl", "model-artifacts.jsonl",
            "model-artifact-provenance.jsonl",
        }
        if not required_outputs.issubset(bundle):
            raise ExperimentRegistryError(
                "LOT-065 storage receipts omit the manifest, target-score ledger, "
                "model-artifact ledger or artifact-provenance sidecar"
            )
        store = FileSystemObjectStore(self.root.parent / "experiment-storage")
        resolved: dict[str, bytes] = {}
        required_entry_fields = {
            "operation_id", "content_sha256", "byte_length", "stage_manifest_sha256",
            "validation_receipt_sha256", "commit_receipt_sha256",
            "publication_receipt_sha256", "pointer_name", "read_back_verified",
        }
        for filename, entry in bundle.items():
            if (not isinstance(filename, str) or Path(filename).name != filename
                    or not isinstance(entry, dict) or set(entry) != required_entry_fields
                    or entry.get("read_back_verified") is not True):
                raise ExperimentRegistryError("LOT-065 receipt entry does not match the closed output schema")
            operation_id = entry["operation_id"]
            try:
                stage_path = store._operation_path(operation_id)
                validation_path = store._validation_path(operation_id)
                commit_path = store._commit_path(operation_id)
                stage_raw = stage_path.read_bytes()
                validation_raw = validation_path.read_bytes()
                commit_raw = commit_path.read_bytes()
                stage = parse_json_strict(stage_raw)
                validation = parse_json_strict(validation_raw)
                commit = parse_json_strict(commit_raw)
                pointer = store.read_pointer(entry["pointer_name"])
                object_raw = store._verify_bytes(
                    store._object_path(entry["content_sha256"]),
                    entry["content_sha256"], entry["byte_length"],
                )
                publication_path = store.publications / f"{entry['pointer_name']}.{operation_id}.json"
                publication_raw = publication_path.read_bytes()
                publication = parse_json_strict(publication_raw)
            except (OSError, ArtifactValidationError, StorageError, KeyError, TypeError, ValueError) as exc:
                raise ExperimentRegistryError(f"LOT-065 committed object or receipt is missing/invalid: {filename}") from exc
            if (canonicalize(stage) != stage_raw or canonicalize(validation) != validation_raw
                    or canonicalize(commit) != commit_raw or canonicalize(publication) != publication_raw):
                raise ExperimentRegistryError(f"LOT-065 receipts are not canonical: {filename}")
            if (_sha(stage_raw) != entry["stage_manifest_sha256"]
                    or _sha(validation_raw) != entry["validation_receipt_sha256"]
                    or _sha(commit_raw) != entry["commit_receipt_sha256"]
                    or _sha(publication_raw) != entry["publication_receipt_sha256"]):
                raise ExperimentRegistryError(f"LOT-065 receipt digest mismatch: {filename}")
            expected_publication = {
                "schema": "lottery.storage-publication/v1",
                "pointer_name": entry["pointer_name"],
                "generation": pointer["generation"],
                "object_sha256": entry["content_sha256"],
                "operation_id": operation_id,
                "previous_object_sha256": pointer.get("previous_object_sha256"),
            }
            checks = {
                "stage_operation_id": stage.get("operation_id") == operation_id,
                "stage_content_sha256": stage.get("content_sha256") == entry["content_sha256"],
                "stage_byte_length": stage.get("byte_length") == entry["byte_length"],
                "stage_producer_commit": stage.get("producer_commit") == expected_producer_commit,
                # The first isolated G3 run predates operation-level execution IDs.
                # Keep this one exact producer commit readable; all later runs must
                # bind each LOT-065 stage to the concrete execution attempt.
                "stage_execution_id": (
                    stage.get("execution_id") == execution_id
                    or (
                        stage.get("execution_id") is None
                        and expected_producer_commit == "1bf59f4c23f8082eb9289d3ae8ae3603312ebe05"
                    )
                ),
                "stage_schema_version": stage.get("schema_version") == "lottery.g3-run-output/v1",
                "validation_operation_id": validation.get("operation_id") == operation_id,
                "validation_content_sha256": validation.get("content_sha256") == entry["content_sha256"],
                "validation_passed": validation.get("validated") is True,
                "validation_mode": validation.get("validation_mode") == "semantic",
                "validation_validator_id": validation.get("validator_id") == "lottery.g3-json-object-or-jsonl/v1",
                "commit_operation_id": commit.get("operation_id") == operation_id,
                "commit_content_sha256": commit.get("content_sha256") == entry["content_sha256"],
                "commit_byte_length": commit.get("byte_length") == entry["byte_length"],
                "commit_flag": commit.get("committed") is True,
                "commit_stage_receipt": commit.get("stage_manifest_sha256") == _sha(stage_raw),
                "commit_validation_receipt": commit.get("validation_receipt_sha256") == _sha(validation_raw),
                "commit_object_key": commit.get("object_key") == str(store._object_path(entry["content_sha256"]).relative_to(store.root)),
                "pointer_operation_id": pointer.get("last_operation_id") == operation_id,
                "pointer_content_sha256": pointer.get("object_sha256") == entry["content_sha256"],
                "publication_receipt": publication == expected_publication,
            }
            mismatches = [name for name, passed in checks.items() if not passed]
            if mismatches:
                raise ExperimentRegistryError(
                    f"LOT-065 stage/validation/commit/read-back chain mismatch: {filename}: {mismatches}"
                )
            resolved[filename] = object_raw

        manifest_raw = resolved["run_manifest.json"]
        if _sha(manifest_raw) != result_sha256:
            raise ExperimentRegistryError("LOT-065 run manifest bytes do not match the terminal result digest")
        try:
            manifest = parse_json_strict(manifest_raw)
        except ArtifactValidationError as exc:
            raise ExperimentRegistryError("LOT-065 stored run manifest is invalid JSON") from exc
        if canonicalize(manifest) + b"\n" != manifest_raw:
            raise ExperimentRegistryError("LOT-065 stored run manifest is not canonical JSON")
        manifest_body = dict(manifest)
        manifest_self_digest = manifest_body.pop("manifest_sha256", None)
        if manifest_self_digest != "sha256:" + _sha(canonicalize(manifest_body)):
            raise ExperimentRegistryError("LOT-065 run manifest self-digest is invalid")
        manifest_binding = manifest.get("experiment_binding")
        required_binding_fields = {
            "schema", "experiment_id", "spec_sha256", "approval_sha256",
            "approval_required", "approval_disposition", "approval_disposition_reason",
            "legacy_parent_issue_url", "legacy_child_registration_comment_url",
            "legacy_child_registration_comment_sha256", "parent_lineage_disposition",
            "experiment_class", "trial_id", "registry_attempt_id", "execution_id",
            "execution_context",
        }
        if (not isinstance(manifest_binding, dict)
                or set(manifest_binding) != required_binding_fields
                or manifest_binding.get("schema") != "lottery.experiment-run-binding/v1"
                or manifest.get("experiment_id") != expected_binding["experiment_id"]
                or manifest.get("experiment_class") != expected_binding["experiment_class"]):
            raise ExperimentRegistryError("LOT-065 run manifest is missing its closed registry experiment binding")
        for field, expected_value in expected_binding.items():
            if field.startswith("_"):
                continue
            if manifest_binding.get(field) != expected_value:
                raise ExperimentRegistryError(
                    f"LOT-065 run manifest binding mismatch: {field}"
                )
        if (expected_binding["experiment_class"] == "exploratory"
                and manifest.get("confirmatory_eligible") is not False):
            raise ExperimentRegistryError(
                "exploratory execution manifest cannot claim confirmatory eligibility"
            )
        def read_canonical_jsonl(filename: str) -> list[dict[str, Any]]:
            raw = resolved[filename]
            if raw and not raw.endswith(b"\n"):
                raise ExperimentRegistryError(f"LOT-065 JSONL output lacks its final newline: {filename}")
            records = []
            for line in raw.splitlines():
                if not line:
                    raise ExperimentRegistryError(f"LOT-065 JSONL output contains a blank record: {filename}")
                try:
                    value = parse_json_strict(line)
                except ArtifactValidationError as exc:
                    raise ExperimentRegistryError(f"LOT-065 JSONL output contains invalid JSON: {filename}") from exc
                if not isinstance(value, dict) or canonicalize(value) != line:
                    raise ExperimentRegistryError(f"LOT-065 JSONL record is not canonical: {filename}")
                records.append(value)
            return records

        target_records = read_canonical_jsonl("target-score-ledger.jsonl")
        artifact_records = read_canonical_jsonl("model-artifacts.jsonl")
        provenance_records = read_canonical_jsonl("model-artifact-provenance.jsonl")
        target_manifest = manifest.get("target_manifest")
        models = manifest.get("models")
        target_count = target_manifest.get("target_count_per_zone") if isinstance(target_manifest, dict) else None
        if (type(target_count) is not int or target_count < 1
                or not isinstance(models, list) or not models):
            raise ExperimentRegistryError("LOT-065 manifest omits its frozen target denominator or model family")
        model_pairs = []
        for model in models:
            if (not isinstance(model, dict)
                    or not isinstance(model.get("zone"), str)
                    or not isinstance(model.get("model_name"), str)
                    or not model["zone"] or not model["model_name"]):
                raise ExperimentRegistryError("LOT-065 manifest model family contains an invalid zone/model entry")
            pair = (model["zone"], model["model_name"])
            if pair in model_pairs:
                raise ExperimentRegistryError("LOT-065 manifest model family contains duplicate zone/model entries")
            model_pairs.append(pair)
        expected_model_pairs = expected_binding.get("_expected_model_pairs")
        if (expected_model_pairs is not None and set(model_pairs) != set(expected_model_pairs)):
            raise ExperimentRegistryError("LOT-065 manifest model × zone family differs from preregistered trial plan")
        expected_target_ids = expected_binding.get("_expected_target_draw_ids")
        if (not isinstance(expected_target_ids, list) or not expected_target_ids
                or len(set(expected_target_ids)) != len(expected_target_ids)
                or target_count != len(expected_target_ids)):
            raise ExperimentRegistryError("LOT-065 manifest target denominator differs from preregistered target IDs")
        expected_target_count = target_count * len(model_pairs)
        if (manifest.get("expected_target_record_count") != expected_target_count
                or manifest.get("actual_target_record_count") != expected_target_count
                or len(target_records) != expected_target_count):
            raise ExperimentRegistryError("LOT-065 target-score ledger does not cover the complete expected denominator")
        if (manifest.get("model_artifact_count") != len(artifact_records)
                or manifest.get("model_artifact_provenance_count") != len(provenance_records)
                or len(provenance_records) != len(artifact_records)):
            raise ExperimentRegistryError("LOT-065 model artifact/provenance counts differ from manifest declarations")

        artifact_ids = set()
        for record in artifact_records:
            artifact_id = record.get("artifact_id")
            if (not isinstance(artifact_id, str)
                    or re.fullmatch(r"sha256:[0-9a-f]{64}", artifact_id) is None
                    or artifact_id in artifact_ids):
                raise ExperimentRegistryError("LOT-065 model artifact IDs are malformed or duplicated")
            artifact_ids.add(artifact_id)

        target_ids_by_pair: dict[tuple[str, str], set[str]] = {pair: set() for pair in model_pairs}
        observed_status_counts: dict[str, int] = {}
        for row in target_records:
            pair = (row.get("zone"), row.get("model_name"))
            target_id = row.get("target_draw_id")
            if pair not in target_ids_by_pair or not isinstance(target_id, str) or not target_id:
                raise ExperimentRegistryError("LOT-065 target ledger contains an undeclared model or target")
            if target_id in target_ids_by_pair[pair]:
                raise ExperimentRegistryError("LOT-065 target ledger contains a duplicate model/target row")
            target_ids_by_pair[pair].add(target_id)
            record_body = dict(row)
            record_digest = record_body.pop("record_sha256", None)
            if record_digest != "sha256:" + _sha(canonicalize(record_body)):
                raise ExperimentRegistryError("LOT-065 target ledger record hash is invalid")
            for field, expected_value in expected_binding.items():
                if field.startswith("_"):
                    continue
                if field in row and row.get(field) != expected_value:
                    raise ExperimentRegistryError(f"LOT-065 target ledger binding mismatch: {field}")
            for field in (
                "experiment_id", "trial_id", "registry_attempt_id", "execution_id",
                "approval_sha256", "approval_required", "approval_disposition",
            ):
                if row.get(field) != expected_binding[field]:
                    raise ExperimentRegistryError(f"LOT-065 target ledger is missing or mismatches binding field: {field}")
            if (row.get("training_dates_strictly_before_target") is not True
                    or not isinstance(row.get("training_last_draw_id"), str)
                    or row["training_last_draw_id"] >= target_id
                    or type(row.get("training_row_count")) is not int
                    or row["training_row_count"] < 1):
                raise ExperimentRegistryError("LOT-065 target ledger has an invalid chronological training cutoff")
            status = row.get("terminal_status")
            allowed_target_statuses = {
                "scored", "fit_failed", "artifact_invalid",
                "probability_invalid", "runner_error",
            }
            if status not in allowed_target_statuses:
                raise ExperimentRegistryError("LOT-065 target ledger row has an unknown terminal status")
            observed_status_counts[status] = observed_status_counts.get(status, 0) + 1
            if status == "scored" and row.get("artifact_id") is None:
                raise ExperimentRegistryError("LOT-065 scored target row has no model artifact reference")
            for field in ("artifact_id", "diagnostic_ref"):
                reference = row.get(field)
                if reference is not None and reference not in artifact_ids:
                    raise ExperimentRegistryError(f"LOT-065 target ledger references an absent model artifact: {field}")
        target_sets = list(target_ids_by_pair.values())
        expected_target_set = set(expected_target_ids)
        if (any(values != expected_target_set for values in target_sets)):
            raise ExperimentRegistryError("LOT-065 target ledger does not exactly cover the preregistered target IDs")
        ordered_target_ids = sorted(expected_target_ids)
        if (target_manifest.get("first_target_draw_id") != ordered_target_ids[0]
                or target_manifest.get("last_target_draw_id") != ordered_target_ids[-1]):
            raise ExperimentRegistryError("LOT-065 target manifest bounds differ from preregistered target IDs")
        expected_target_manifest_sha256 = expected_binding.get("_expected_target_manifest_sha256")
        if expected_target_manifest_sha256 is not None:
            target_dates: dict[str, str] = {}
            for row in target_records:
                target_id = row["target_draw_id"]
                target_date = row.get("target_draw_date")
                if not isinstance(target_date, str):
                    raise ExperimentRegistryError("LOT-065 target ledger omits target draw dates")
                if target_id in target_dates and target_dates[target_id] != target_date:
                    raise ExperimentRegistryError("LOT-065 target ledger has inconsistent dates for a target ID")
                target_dates[target_id] = target_date
            target_list = [
                {"target_draw_id": target_id, "target_draw_date": target_dates[target_id]}
                for target_id in ordered_target_ids
            ]
            observed_target_manifest_sha256 = _sha(canonicalize({"targets": target_list}))
            if (observed_target_manifest_sha256 != expected_target_manifest_sha256
                    or target_manifest.get("target_list_sha256") != expected_target_manifest_sha256):
                raise ExperimentRegistryError("LOT-065 target manifest digest differs from preregistered target manifest")
        declared_status_counts = manifest.get("terminal_status_counts")
        if (not isinstance(declared_status_counts, dict)
                or any(key not in allowed_target_statuses or type(value) is not int or value < 0
                       for key, value in declared_status_counts.items())
                or {key: value for key, value in declared_status_counts.items() if value}
                != observed_status_counts
                or sum(declared_status_counts.values()) != expected_target_count):
            raise ExperimentRegistryError("LOT-065 target ledger terminal counts differ from manifest")
        expected_scientific_status = (
            "complete" if set(observed_status_counts) == {"scored"}
            else "complete_with_explicit_failures"
        )
        if manifest.get("status") != expected_scientific_status:
            raise ExperimentRegistryError("LOT-065 scientific status does not match target ledger terminal outcomes")

        provenance_ids = set()
        for row in provenance_records:
            artifact_id = row.get("artifact_id")
            if artifact_id not in artifact_ids or artifact_id in provenance_ids:
                raise ExperimentRegistryError("LOT-065 artifact provenance references an absent or duplicate artifact")
            provenance_ids.add(artifact_id)
            provenance_expectations = {
                "experiment_id": expected_binding["experiment_id"],
                "trial_id": expected_binding["trial_id"],
                "attempt_id": expected_binding["registry_attempt_id"],
                "execution_id": expected_binding["execution_id"],
                "approval_sha256": expected_binding["approval_sha256"],
                "approval_required": expected_binding["approval_required"],
                "approval_disposition": expected_binding["approval_disposition"],
                "experiment_class": expected_binding["experiment_class"],
                "evaluation_run_id": manifest.get("run_id"),
            }
            for field in (
                "legacy_parent_issue_url", "legacy_child_registration_comment_url",
                "legacy_child_registration_comment_sha256", "parent_lineage_disposition",
            ):
                if field in expected_binding:
                    provenance_expectations[field] = expected_binding[field]
            if any(row.get(field) != value for field, value in provenance_expectations.items()):
                raise ExperimentRegistryError("LOT-065 artifact provenance does not match registry execution binding")
        if provenance_ids != artifact_ids:
            raise ExperimentRegistryError("LOT-065 artifact provenance does not cover the exact model artifact set")
        declared = manifest.get("output_files") if isinstance(manifest, dict) else None
        expected_output_schemas = {
            "subset-model-rolling-origin.json": "lottery.g3-summary-report/v1",
            "target-score-ledger.jsonl": "lottery.target-score-ledger/v1",
            "model-artifacts.jsonl": "lottery.subset-probability-model/v1",
            "model-artifact-provenance.jsonl": "lottery.model-artifact-provenance/v1",
        }
        if (not isinstance(declared, dict)
                or set(declared) != set(expected_output_schemas)
                or set(bundle) != set(declared) | {"run_manifest.json"}):
            raise ExperimentRegistryError("LOT-065 receipt bundle does not cover the exact manifest output set")
        legacy_first_g3_run = (
            expected_producer_commit == "1bf59f4c23f8082eb9289d3ae8ae3603312ebe05"
        )
        for filename, declaration in declared.items():
            raw = resolved.get(filename)
            legacy_declaration = (
                legacy_first_g3_run
                and isinstance(declaration, dict)
                and set(declaration) == {"sha256", "bytes"}
            )
            current_declaration = (
                isinstance(declaration, dict)
                and set(declaration) == {"schema_version", "sha256", "bytes"}
                and declaration.get("schema_version") == expected_output_schemas[filename]
            )
            if (raw is None or not (legacy_declaration or current_declaration)
                    or declaration.get("sha256") != _sha(raw)
                    or declaration.get("bytes") != len(raw)):
                raise ExperimentRegistryError(
                    f"LOT-065 stored output schema/digest/length does not match manifest declaration: {filename}"
                )
        if _sha(resolved["model-artifacts.jsonl"]) != artifact_sha256:
            raise ExperimentRegistryError("LOT-065 model artifact bytes do not match the terminal artifact digest")

    def record_artifacts_committed(
        self, *, experiment_id: str, attempt_id: str, execution_id: str,
        result_sha256: str, artifact_sha256: str, storage_receipts_sha256: str,
        actor: str,
    ) -> dict[str, Any]:
        """Append a verifiable LOT-065 artifact-commit event before terminal success."""
        if not all(_is_sha(value) for value in (
            execution_id, result_sha256, artifact_sha256, storage_receipts_sha256,
        )):
            raise ExperimentRegistryError("artifact commit event requires canonical SHA-256 identities")
        if not isinstance(actor, str) or not actor:
            raise ValueError("actor must be a non-empty string")
        with ledger_lock(self.events_path):
            snapshot = self._snapshot_unlocked()
            experiment = snapshot["experiments"].get(experiment_id)
            attempt = experiment["attempts"].get(attempt_id) if experiment else None
            if attempt is None or attempt.get("status") not in {"running", "succeeded"}:
                raise ExperimentRegistryError("artifact commit requires a running or already committed registered execution")
            if attempt.get("execution_id") != execution_id or attempt.get("execution_context") is None:
                raise ExperimentRegistryError("artifact commit execution identity does not match the registered attempt")
            self._verify_execution_storage_receipts(
                execution_id=execution_id,
                expected_producer_commit=attempt["execution_context"]["sha"],
                result_sha256=result_sha256,
                artifact_sha256=artifact_sha256,
                expected_receipts_sha256=storage_receipts_sha256,
                expected_binding=_execution_binding_expectations(
                    experiment_id, experiment, attempt, attempt_id, execution_id,
                ),
            )
            bundle = _read_canonical(self.root / "storage-receipts" / f"{execution_id}.json")
            output_files = sorted(bundle)
            existing = attempt.get("artifacts_committed")
            if existing is not None:
                expected_existing = {
                    "execution_id": execution_id,
                    "storage_receipts_sha256": storage_receipts_sha256,
                    "result_sha256": result_sha256,
                    "artifact_sha256": artifact_sha256,
                    "output_files": output_files,
                }
                if all(existing.get(key) == value for key, value in expected_existing.items()):
                    return existing
                raise ExperimentRegistryError("artifact commit event cannot be overwritten")
            if attempt.get("status") != "running":
                raise ExperimentRegistryError("terminal execution cannot receive a new artifact commit event")
            event_id = _sha(
                f"{experiment_id}:{attempt_id}:artifacts-committed:{storage_receipts_sha256}".encode("utf-8")
            )
            self._append_event_locked({
                "schema": EVENT_SCHEMA,
                "event_id": event_id,
                "event_type": "artifacts_committed",
                "occurred_at_utc": datetime.now(timezone.utc).isoformat(),
                "actor": actor,
                "experiment_id": experiment_id,
                "attempt_id": attempt_id,
                "execution_id": execution_id,
                "storage_receipts_sha256": storage_receipts_sha256,
                "result_sha256": result_sha256,
                "artifact_sha256": artifact_sha256,
                "output_files": output_files,
            })
            return self._snapshot_unlocked()["experiments"][experiment_id]["attempts"][attempt_id]["artifacts_committed"]

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
        execution_id: str | None = None,
        storage_receipts_sha256: str | None = None,
    ) -> dict[str, Any]:
        if terminal_status not in TERMINAL_STATUSES or terminal_status == "completed_uncommitted":
            raise ExperimentRegistryError("trial terminal_status is not in the closed status set; completed_uncommitted is reserved for verified historical imports")
        if not isinstance(actor, str) or not actor:
            raise ValueError("actor must be a non-empty string")
        if artifact_sha256 is not None and not _is_sha(artifact_sha256):
            raise ExperimentRegistryError("artifact_sha256 must be null or a lowercase SHA-256")
        if result_sha256 is not None and not _is_sha(result_sha256):
            raise ExperimentRegistryError("result_sha256 must be null or a lowercase SHA-256")
        if storage_receipts_sha256 is not None and not _is_sha(storage_receipts_sha256):
            raise ExperimentRegistryError("storage_receipts_sha256 must be null or a lowercase SHA-256")
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
            if attempt.get("execution_id") != execution_id:
                raise ExperimentRegistryError("terminal execution identity does not match trial start")
            if attempt.get("execution_context") is not None and terminal_status == "succeeded":
                if artifact_sha256 is None:
                    raise ExperimentRegistryError("execution-bound successful trial requires an artifact digest")
                if storage_receipts_sha256 is None:
                    raise ExperimentRegistryError("execution-bound successful trial requires verified LOT-065 storage receipts")
                self._verify_execution_storage_receipts(
                    execution_id=execution_id,
                    expected_producer_commit=attempt["execution_context"]["sha"],
                    result_sha256=result_sha256,
                    artifact_sha256=artifact_sha256,
                    expected_receipts_sha256=storage_receipts_sha256,
                    expected_binding=_execution_binding_expectations(
                        experiment_id, experiment, attempt, attempt_id, execution_id,
                    ),
                )
                committed = attempt.get("artifacts_committed")
                legacy_first_producer = (
                    attempt.get("execution_context", {}).get("sha")
                    == "1bf59f4c23f8082eb9289d3ae8ae3603312ebe05"
                )
                if not legacy_first_producer and (
                        not isinstance(committed, dict)
                        or committed.get("execution_id") != execution_id
                        or committed.get("storage_receipts_sha256") != storage_receipts_sha256
                        or committed.get("result_sha256") != result_sha256
                        or committed.get("artifact_sha256") != artifact_sha256):
                    raise ExperimentRegistryError("execution-bound success requires a matching append-only artifact commit event")
            if attempt["status"] != "running":
                same = (
                    attempt["status"] == terminal_status
                    and attempt["artifact_sha256"] == artifact_sha256
                    and attempt["result_sha256"] == result_sha256
                    and attempt["failure_code"] == failure_code
                    and attempt.get("execution_id") == execution_id
                    and attempt.get("storage_receipts_sha256") == storage_receipts_sha256
                )
                if same:
                    return attempt
                raise ExperimentRegistryError("terminal trial attempt cannot be overwritten")
            event_id = _sha(f"{experiment_id}:{attempt_id}:finish".encode("utf-8"))
            self._append_event_locked({
                "schema": EVENT_SCHEMA,
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
                "execution_id": execution_id,
                "approval_sha256": attempt.get("approval_sha256"),
                "storage_receipts_sha256": storage_receipts_sha256,
            })
            return self._snapshot_unlocked()["experiments"][experiment_id]["attempts"][attempt_id]
