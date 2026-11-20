"""Fail-closed immutable model lifecycle and compare-and-swap Champion registry.

This module records lifecycle state only. Cryptographic approval verification is
an injected trust boundary; without a verifier, promotion, restoration, and
three-slot resolution are unavailable.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any, Callable
from uuid import uuid4

from .artifact import (
    ArtifactValidationError,
    canonicalize,
    create_artifact,
    parse_json_strict,
    verify_artifact,
)
from ..ledger_lock import ledger_lock

REGISTRY_SCHEMA = "lottery.champion-registry/v1"
EVALUATION_SCHEMA = "lottery.lifecycle-evaluation/v1"
SHADOW_SCHEMA = "lottery.lifecycle-shadow/v1"
APPROVAL_SCHEMA = "lottery.lifecycle-approval/v1"
POLICY_VERSION = "LOT-060-v1"
ZERO_HASH = "0" * 64
ZONES = ("front", "back")


class LifecycleError(RuntimeError):
    """Raised when lifecycle state or evidence is invalid."""


class StaleRegistryError(LifecycleError):
    """Raised when a compare-and-swap precondition no longer holds."""


ApprovalVerifier = Callable[[dict[str, Any], dict[str, Any]], bool]


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _is_sha(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(char in "0123456789abcdef" for char in value)
    )


def _atomic_write(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        if hasattr(os, "O_DIRECTORY"):
            directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def _write_once(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        if path.read_bytes() != raw:
            raise LifecycleError(f"immutable object collision at {path}")
        return
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    if hasattr(os, "O_DIRECTORY"):
        directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)


def _require_generation(value: Any) -> None:
    if type(value) is not int or value < 0:
        raise LifecycleError("expected_generation must be a non-negative integer")


def _slot_key(population_key: str, zone: str) -> str:
    if not isinstance(population_key, str) or not population_key or population_key.strip() != population_key:
        raise LifecycleError("population_key must be a non-empty canonical string")
    if zone not in ZONES:
        raise LifecycleError("zone must be 'front' or 'back'")
    return f"{population_key}|{zone}"


def _parse_regime_population_key(population_key: str) -> tuple[str, int]:
    match = re.fullmatch(
        r"([a-z0-9][a-z0-9._-]{0,63})\|reported_set_index=([123])",
        population_key,
    )
    if not match:
        raise LifecycleError(
            "verified set-conditioned population keys must be "
            "'<equipment_regime_id>|reported_set_index=<1|2|3>'"
        )
    return match.group(1), int(match.group(2))


def _new_slot(population_key: str, zone: str) -> dict[str, Any]:
    return {
        "population_key": population_key,
        "zone": zone,
        "champion_artifact_id": None,
        "champion_generation": None,
        "challenger_artifact_id": None,
        "shadow_artifact_id": None,
        "retired_artifact_ids": [],
        "rejected_artifact_ids": [],
        "validation": {},
        "shadow_validation": {},
        "approval": {},
        "suspended": False,
        "suspension_reason": None,
    }


def _validate_evaluation_receipt(receipt: dict[str, Any]) -> bool:
    required = {
        "schema_version", "artifact_id", "population_key", "zone",
        "evaluation_manifest_sha256", "target_list_sha256", "target_count",
        "training_population_sha256", "population_eligibility", "population_evidence_sha256", "full_coverage", "preregistered", "holdout_accessed", "numerical_pass",
        "calibration_pass", "stability_pass", "front_improved", "back_improved",
        "multiplicity_pass", "uniform_non_regression_pass", "decision", "reason_code",
    }
    if not isinstance(receipt, dict) or set(receipt) != required:
        raise LifecycleError("evaluation receipt fields do not match the closed LOT-060 schema")
    if receipt["schema_version"] != EVALUATION_SCHEMA:
        raise LifecycleError("unsupported lifecycle evaluation schema")
    for field in ("evaluation_manifest_sha256", "target_list_sha256", "training_population_sha256"):
        if not _is_sha(receipt[field]):
            raise LifecycleError(f"{field} must be a lowercase SHA-256")
    if receipt["population_eligibility"] not in (
        "verified_regime", "pooled_equipment_blind", "blocked_regime_unresolved"
    ):
        raise LifecycleError("population_eligibility is not a registered status")
    if receipt["population_eligibility"] == "verified_regime":
        _parse_regime_population_key(receipt["population_key"])
        if not _is_sha(receipt["population_evidence_sha256"]):
            raise LifecycleError("verified regime requires a population evidence SHA-256")
    elif receipt["population_evidence_sha256"] is not None:
        raise LifecycleError("non-regime population must not claim a regime evidence digest")
    if not isinstance(receipt["artifact_id"], str) or not receipt["artifact_id"].startswith("sha256:"):
        raise LifecycleError("evaluation receipt artifact_id is invalid")
    _slot_key(receipt["population_key"], receipt["zone"])
    if type(receipt["target_count"]) is not int or receipt["target_count"] < 1:
        raise LifecycleError("target_count must be a positive integer")
    for field in (
        "full_coverage", "preregistered", "holdout_accessed", "numerical_pass",
        "calibration_pass", "stability_pass", "front_improved", "back_improved",
        "multiplicity_pass", "uniform_non_regression_pass",
    ):
        if type(receipt[field]) is not bool:
            raise LifecycleError(f"{field} must be boolean")
    if receipt["decision"] not in ("PASS", "FAIL"):
        raise LifecycleError("evaluation decision must be PASS or FAIL")
    if not isinstance(receipt["reason_code"], str):
        raise LifecycleError("reason_code must be a string")
    return (
        receipt["decision"] == "PASS"
        and receipt["population_eligibility"] in ("verified_regime", "pooled_equipment_blind")
        and receipt["full_coverage"]
        and receipt["preregistered"]
        and not receipt["holdout_accessed"]
        and receipt["numerical_pass"]
        and receipt["calibration_pass"]
        and receipt["stability_pass"]
        and receipt["front_improved"]
        and receipt["back_improved"]
        and receipt["multiplicity_pass"]
        and receipt["uniform_non_regression_pass"]
    )


def _validate_shadow_receipt(
    receipt: dict[str, Any],
    *,
    artifact: dict[str, Any],
    artifact_id: str,
    population_key: str,
    zone: str,
    champion_artifact_id: str,
) -> bool:
    required = {
        "schema_version", "shadow_manifest_sha256", "artifact_id", "population_key",
        "zone", "champion_artifact_id", "target_list_sha256", "source_evidence_sha256",
        "first_target_draw_id", "last_target_draw_id", "target_count", "full_coverage",
        "targets_after_training_cutoff", "holdout_accessed", "champion_non_regression_pass",
        "uniform_non_regression_pass", "calibration_pass", "probability_integrity_pass",
        "stability_pass", "decision", "reason_code",
    }
    if not isinstance(receipt, dict) or set(receipt) != required:
        raise LifecycleError("shadow receipt fields do not match the closed LOT-060 schema")
    if receipt["schema_version"] != SHADOW_SCHEMA:
        raise LifecycleError("unsupported shadow receipt schema")
    for field in ("shadow_manifest_sha256", "target_list_sha256", "source_evidence_sha256"):
        if not _is_sha(receipt[field]):
            raise LifecycleError(f"shadow {field} must be a lowercase SHA-256")
    if (
        receipt["artifact_id"] != artifact_id
        or receipt["population_key"] != population_key
        or receipt["zone"] != zone
        or receipt["champion_artifact_id"] != champion_artifact_id
    ):
        raise LifecycleError("shadow receipt scope does not match challenger and current Champion")
    first_id = receipt["first_target_draw_id"]
    last_id = receipt["last_target_draw_id"]
    if (
        not isinstance(first_id, str) or not re.fullmatch(r"\d{5}", first_id)
        or not isinstance(last_id, str) or not re.fullmatch(r"\d{5}", last_id)
        or first_id > last_id
        or first_id <= artifact["training_cutoff_draw_id"]
    ):
        raise LifecycleError("shadow target window must be strictly after the candidate training cutoff")
    if type(receipt["target_count"]) is not int or receipt["target_count"] < 1:
        raise LifecycleError("shadow target_count must be a positive integer")
    for field in (
        "full_coverage", "targets_after_training_cutoff", "holdout_accessed",
        "champion_non_regression_pass", "uniform_non_regression_pass",
        "calibration_pass", "probability_integrity_pass", "stability_pass",
    ):
        if type(receipt[field]) is not bool:
            raise LifecycleError(f"shadow {field} must be boolean")
    if receipt["decision"] not in ("PASS", "FAIL") or not isinstance(receipt["reason_code"], str):
        raise LifecycleError("shadow decision or reason_code is invalid")
    return (
        receipt["decision"] == "PASS"
        and receipt["full_coverage"]
        and receipt["targets_after_training_cutoff"]
        and not receipt["holdout_accessed"]
        and receipt["champion_non_regression_pass"]
        and receipt["uniform_non_regression_pass"]
        and receipt["calibration_pass"]
        and receipt["probability_integrity_pass"]
        and receipt["stability_pass"]
    )


def _validate_approval(
    approval: dict[str, Any],
    *,
    action: str,
    artifact_id: str,
    population_key: str,
    zone: str,
    expected_champion_artifact_id: str | None,
    evaluation_manifest_sha256: str,
    evaluation_receipt_sha256: str,
    shadow_receipt_sha256: str | None,
) -> None:
    required = {
        "schema_version", "approval_id", "action", "artifact_id", "population_key",
        "zone", "expected_champion_artifact_id", "evaluation_manifest_sha256",
        "evaluation_receipt_sha256", "shadow_receipt_sha256", "policy_version", "issued_at_utc", "signer_id", "signature",
    }
    if not isinstance(approval, dict) or set(approval) != required:
        raise LifecycleError("approval receipt fields do not match the closed LOT-060 schema")
    if approval["schema_version"] != APPROVAL_SCHEMA or approval["policy_version"] != POLICY_VERSION:
        raise LifecycleError("unsupported approval schema or policy version")
    if (
        approval["action"] != action
        or approval["artifact_id"] != artifact_id
        or approval["population_key"] != population_key
        or approval["zone"] != zone
        or approval["expected_champion_artifact_id"] != expected_champion_artifact_id
        or approval["evaluation_manifest_sha256"] != evaluation_manifest_sha256
        or approval["evaluation_receipt_sha256"] != evaluation_receipt_sha256
        or approval["shadow_receipt_sha256"] != shadow_receipt_sha256
    ):
        raise LifecycleError("approval scope does not match the requested lifecycle transition")
    for field in ("approval_id", "issued_at_utc", "signer_id", "signature"):
        if not isinstance(approval[field], str) or not approval[field]:
            raise LifecycleError(f"approval {field} must be a non-empty string")
    if not _is_sha(evaluation_receipt_sha256):
        raise LifecycleError("approval evaluation_receipt_sha256 must be a lowercase SHA-256")
    if shadow_receipt_sha256 is not None and not _is_sha(shadow_receipt_sha256):
        raise LifecycleError("approval shadow_receipt_sha256 must be null or a lowercase SHA-256")
    if action == "restore" and shadow_receipt_sha256 is not None:
        raise LifecycleError("restore approval must not claim a prospective shadow receipt")
    if action == "promote" and expected_champion_artifact_id is not None and shadow_receipt_sha256 is None:
        raise LifecycleError("replacement Champion promotion requires a prospective shadow receipt")
    if approval["action"] not in ("promote", "restore"):
        raise LifecycleError("approval action must be promote or restore")
    try:
        issued_at = datetime.fromisoformat(approval["issued_at_utc"].replace("Z", "+00:00"))
    except ValueError as exc:
        raise LifecycleError("approval issued_at_utc must be ISO-8601") from exc
    if issued_at.tzinfo is None:
        raise LifecycleError("approval issued_at_utc must include a timezone")


class ChampionLifecycle:
    """Filesystem-backed immutable artifact store, event journal, and CAS registry."""

    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.objects = self.root / "objects"
        self.approvals = self.root / "approvals"
        self.evaluations = self.root / "evaluations"
        self.journals = self.root / "journals"
        self.registry_path = self.root / "registry.json"
        self.events_path = self.root / "events.jsonl"
        self.objects.mkdir(parents=True, exist_ok=True)
        self.approvals.mkdir(parents=True, exist_ok=True)
        self.evaluations.mkdir(parents=True, exist_ok=True)
        self.journals.mkdir(parents=True, exist_ok=True)
        with ledger_lock(self.registry_path):
            if not self.registry_path.exists():
                _atomic_write(self.registry_path, canonicalize({
                    "schema_version": REGISTRY_SCHEMA,
                    "generation": 0,
                    "slots": {},
                    "last_operation_id": None,
                }))
            self._recover_locked()

    def _read_registry(self) -> dict[str, Any]:
        try:
            registry = parse_json_strict(self.registry_path.read_bytes())
        except (OSError, ArtifactValidationError) as exc:
            raise LifecycleError(f"cannot read Champion registry: {exc}") from exc
        if (
            registry.get("schema_version") != REGISTRY_SCHEMA
            or type(registry.get("generation")) is not int
            or registry["generation"] < 0
            or not isinstance(registry.get("slots"), dict)
            or (registry.get("last_operation_id") is not None
                and (not isinstance(registry["last_operation_id"], str)
                     or not registry["last_operation_id"]))
        ):
            raise LifecycleError("Champion registry schema or generation is invalid")
        for key, slot in registry["slots"].items():
            if not isinstance(key, str) or not isinstance(slot, dict):
                raise LifecycleError("Champion registry slot entries must be objects with string keys")
            expected_key = _slot_key(slot.get("population_key"), slot.get("zone"))
            if key != expected_key:
                raise LifecycleError("Champion registry slot key does not match its population/zone")
            if (type(slot.get("suspended")) is not bool
                    or not isinstance(slot.get("retired_artifact_ids"), list)
                    or not isinstance(slot.get("rejected_artifact_ids"), list)
                    or not isinstance(slot.get("validation"), dict)
                    or not isinstance(slot.get("shadow_validation"), dict)
                    or not isinstance(slot.get("approval"), dict)
                    or (slot.get("suspension_reason") is not None
                        and not isinstance(slot["suspension_reason"], str))):
                raise LifecycleError("Champion registry slot state is malformed")
            if slot.get("champion_generation") is not None and type(slot["champion_generation"]) is not int:
                raise LifecycleError("Champion slot generation is malformed")
            for field in ("champion_artifact_id", "challenger_artifact_id", "shadow_artifact_id"):
                artifact_id = slot.get(field)
                if artifact_id is not None:
                    self._artifact_path(artifact_id)
            for artifact_id in slot["retired_artifact_ids"] + slot["rejected_artifact_ids"]:
                self._artifact_path(artifact_id)
            if any(not isinstance(v, dict) for v in slot["validation"].values()):
                raise LifecycleError("Champion validation references are malformed")
            for shadow_record in slot["shadow_validation"].values():
                if (not isinstance(shadow_record, dict)
                        or type(shadow_record.get("eligible")) is not bool
                        or not _is_sha(shadow_record.get("receipt_sha256"))):
                    raise LifecycleError("Champion shadow validation references are malformed")
            for approval_hash in slot["approval"].values():
                if not _is_sha(approval_hash):
                    raise LifecycleError("Champion approval hash is malformed")
        return registry

    def _read_events(self) -> list[dict[str, Any]]:
        if not self.events_path.exists():
            return []
        events: list[dict[str, Any]] = []
        previous = ZERO_HASH
        for line_number, line in enumerate(self.events_path.read_bytes().splitlines(), 1):
            try:
                event = parse_json_strict(line)
            except ArtifactValidationError as exc:
                raise LifecycleError(f"lifecycle event line {line_number} is invalid: {exc}") from exc
            event_hash = event.get("event_hash")
            body = {key: value for key, value in event.items() if key != "event_hash"}
            if event.get("prev_event_hash") != previous or event_hash != _sha(canonicalize(body)):
                raise LifecycleError(f"lifecycle event hash chain failed at line {line_number}")
            previous = event_hash
            events.append(event)
        return events

    def _append_event_locked(self, body: dict[str, Any]) -> None:
        events = self._read_events()
        if any(event.get("event_id") == body["event_id"] for event in events):
            return
        previous = events[-1]["event_hash"] if events else ZERO_HASH
        event_body = {**body, "prev_event_hash": previous}
        event = {**event_body, "event_hash": _sha(canonicalize(event_body))}
        self.events_path.parent.mkdir(parents=True, exist_ok=True)
        with self.events_path.open("ab") as handle:
            handle.write(canonicalize(event) + b"\n")
            handle.flush()
            os.fsync(handle.fileno())

    def _recover_locked(self) -> None:
        registry = self._read_registry()
        events = self._read_events()
        known_ids = {event.get("event_id") for event in events}
        for journal_path in sorted(self.journals.glob("*.json")):
            try:
                journal = parse_json_strict(journal_path.read_bytes())
            except (OSError, ArtifactValidationError) as exc:
                raise LifecycleError(f"cannot recover lifecycle journal {journal_path.name}: {exc}") from exc
            operation_id = journal.get("operation_id")
            if not isinstance(operation_id, str) or operation_id in known_ids:
                journal_path.unlink(missing_ok=True)
                continue
            event_body = journal["event"]
            if registry.get("last_operation_id") == operation_id:
                self._append_event_locked(event_body)
            elif registry["generation"] == journal["old_generation"]:
                aborted = {
                    **event_body,
                    "event_type": "operation_aborted",
                    "reason_code": "interrupted_before_registry_commit",
                }
                self._append_event_locked(aborted)
            else:
                raise LifecycleError("unresolved lifecycle journal conflicts with registry generation")
            journal_path.unlink(missing_ok=True)
            events = self._read_events()
            known_ids = {event.get("event_id") for event in events}

    def _commit_locked(
        self,
        registry: dict[str, Any],
        new_registry: dict[str, Any],
        *,
        event_type: str,
        population_key: str,
        zone: str,
        artifact_id: str | None,
        previous_artifact_id: str | None,
        actor: str,
        workflow_run_id: str | None,
        evidence_sha256: str | None,
        reason_code: str | None,
        event_details: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not isinstance(actor, str) or not actor:
            raise LifecycleError("lifecycle actor must be a non-empty string")
        if workflow_run_id is not None and (not isinstance(workflow_run_id, str) or not workflow_run_id):
            raise LifecycleError("workflow_run_id must be a non-empty string or null")
        operation_id = uuid4().hex
        new_registry["generation"] = registry["generation"] + 1
        new_registry["last_operation_id"] = operation_id
        event = {
            "event_id": operation_id,
            "event_type": event_type,
            "occurred_at_utc": datetime.now(timezone.utc).isoformat(),
            "actor": actor,
            "workflow_run_id": workflow_run_id,
            "population_key": population_key,
            "zone": zone,
            "artifact_id": artifact_id,
            "previous_artifact_id": previous_artifact_id,
            "policy_version": POLICY_VERSION,
            "evidence_sha256": evidence_sha256,
            "reason_code": reason_code,
            "registry_generation": new_registry["generation"],
        }
        if event_details:
            event.update(event_details)
        journal = {
            "operation_id": operation_id,
            "old_generation": registry["generation"],
            "new_registry": new_registry,
            "event": event,
        }
        _atomic_write(self.journals / f"{operation_id}.json", canonicalize(journal))
        _atomic_write(self.registry_path, canonicalize(new_registry))
        self._append_event_locked(event)
        (self.journals / f"{operation_id}.json").unlink(missing_ok=True)
        return new_registry

    def _artifact_path(self, artifact_id: str) -> Path:
        if not isinstance(artifact_id, str) or not artifact_id.startswith("sha256:") or not _is_sha(artifact_id[7:]):
            raise LifecycleError("artifact ID must be a lowercase sha256 content ID")
        return self.objects / f"{artifact_id[7:]}.json"

    def _load_artifact(self, artifact_id: str) -> dict[str, Any]:
        path = self._artifact_path(artifact_id)
        try:
            artifact = verify_artifact(path.read_bytes())
        except (OSError, ArtifactValidationError) as exc:
            raise LifecycleError(f"artifact {artifact_id} failed immutable verification: {exc}") from exc
        if artifact.get("artifact_id") != artifact_id:
            raise LifecycleError("artifact object path and content ID differ")
        return artifact

    def _load_evaluation_receipt(self, receipt_hash: str) -> dict[str, Any]:
        if not _is_sha(receipt_hash):
            raise LifecycleError("evaluation receipt hash is invalid")
        path = self.evaluations / f"{receipt_hash}.json"
        try:
            raw = path.read_bytes()
            receipt = parse_json_strict(raw)
        except (OSError, ArtifactValidationError) as exc:
            raise LifecycleError("immutable evaluation receipt is missing or invalid") from exc
        if _sha(raw) != receipt_hash or canonicalize(receipt) != raw:
            raise LifecycleError("evaluation receipt content hash or canonical bytes mismatch")
        _validate_evaluation_receipt(receipt)
        return receipt

    def _load_shadow_receipt(self, receipt_hash: str) -> dict[str, Any]:
        if not _is_sha(receipt_hash):
            raise LifecycleError("shadow receipt hash is invalid")
        path = self.evaluations / f"{receipt_hash}.json"
        try:
            raw = path.read_bytes()
            receipt = parse_json_strict(raw)
        except (OSError, ArtifactValidationError) as exc:
            raise LifecycleError("immutable shadow receipt is missing or invalid") from exc
        if _sha(raw) != receipt_hash or canonicalize(receipt) != raw:
            raise LifecycleError("shadow receipt content hash or canonical bytes mismatch")
        return receipt

    def snapshot(self) -> dict[str, Any]:
        with ledger_lock(self.registry_path):
            self._recover_locked()
            registry = self._read_registry()
            for slot in registry["slots"].values():
                for artifact_id in (
                    slot.get("champion_artifact_id"),
                    slot.get("challenger_artifact_id"),
                    slot.get("shadow_artifact_id"),
                    *slot.get("retired_artifact_ids", []),
                ):
                    if artifact_id is not None:
                        self._load_artifact(artifact_id)
                for artifact_id, validation in slot.get("validation", {}).items():
                    receipt = self._load_evaluation_receipt(validation["receipt_sha256"])
                    if (receipt.get("artifact_id") != artifact_id
                            or receipt.get("population_key") != slot["population_key"]
                            or receipt.get("zone") != slot["zone"]):
                        raise LifecycleError("evaluation receipt scope differs from registry slot")
                for artifact_id, shadow_validation in slot.get("shadow_validation", {}).items():
                    shadow_receipt = self._load_shadow_receipt(shadow_validation["receipt_sha256"])
                    if (shadow_receipt.get("artifact_id") != artifact_id
                            or shadow_receipt.get("population_key") != slot["population_key"]
                            or shadow_receipt.get("zone") != slot["zone"]):
                        raise LifecycleError("shadow receipt scope differs from registry slot")
                for approval_hash in slot.get("approval", {}).values():
                    if not _is_sha(approval_hash):
                        raise LifecycleError("immutable approval receipt reference is malformed")
                    approval_raw = (self.approvals / f"{approval_hash}.json").read_bytes()
                    if _sha(approval_raw) != approval_hash:
                        raise LifecycleError("immutable approval receipt hash mismatch")
            return registry

    def register_challenger(
        self,
        artifact_payload: dict[str, Any],
        *,
        population_key: str,
        zone: str,
        expected_generation: int,
        actor: str,
        workflow_run_id: str | None = None,
    ) -> dict[str, Any]:
        _require_generation(expected_generation)
        key = _slot_key(population_key, zone)
        try:
            raw, artifact_id = create_artifact(artifact_payload)
        except ArtifactValidationError as exc:
            raise LifecycleError(f"challenger artifact is invalid: {exc}") from exc
        artifact = verify_artifact(raw)
        if artifact["zone"] != zone:
            raise LifecycleError("challenger artifact zone does not match population slot")
        _write_once(self._artifact_path(artifact_id), raw)
        with ledger_lock(self.registry_path):
            self._recover_locked()
            registry = self._read_registry()
            if registry["generation"] != expected_generation:
                raise StaleRegistryError("registry generation changed before challenger registration")
            slots = dict(registry["slots"])
            slot = dict(slots.get(key, _new_slot(population_key, zone)))
            existing = slot.get("challenger_artifact_id")
            if existing == artifact_id or slot.get("shadow_artifact_id") == artifact_id:
                return registry
            if artifact_id in slot.get("rejected_artifact_ids", []):
                raise LifecycleError("a rejected immutable artifact cannot be re-registered")
            if artifact_id == slot.get("champion_artifact_id") or artifact_id in slot.get("retired_artifact_ids", []):
                raise LifecycleError("an existing Champion/retired artifact cannot be re-registered as challenger")
            if existing is not None or slot.get("shadow_artifact_id") is not None:
                raise LifecycleError("slot already has a challenger or shadow; resolve it before registering another")
            slot["challenger_artifact_id"] = artifact_id
            slots[key] = slot
            new_registry = {**registry, "slots": slots}
            return self._commit_locked(
                registry, new_registry, event_type="challenger_registered",
                population_key=population_key, zone=zone, artifact_id=artifact_id,
                previous_artifact_id=slot.get("champion_artifact_id"), actor=actor,
                workflow_run_id=workflow_run_id, evidence_sha256=artifact_id[7:],
                reason_code=None,
            )

    def validate_candidate(
        self,
        *,
        population_key: str,
        zone: str,
        artifact_id: str,
        receipt: dict[str, Any],
        expected_generation: int,
        actor: str,
        workflow_run_id: str | None = None,
    ) -> dict[str, Any]:
        _require_generation(expected_generation)
        key = _slot_key(population_key, zone)
        eligible = _validate_evaluation_receipt(receipt)
        if (
            receipt["population_key"] != population_key
            or receipt["zone"] != zone
            or receipt["artifact_id"] != artifact_id
        ):
            raise LifecycleError("evaluation receipt scope does not match challenger")
        artifact = self._load_artifact(artifact_id)
        if receipt["training_population_sha256"] != artifact["training_snapshot_sha256"]:
            raise LifecycleError("evaluation training population hash does not match immutable artifact")
        if receipt["population_eligibility"] == "verified_regime" and artifact["training_row_count"] < 300:
            raise LifecycleError("verified regime artifact requires at least 300 prior same-key training rows")
        receipt_raw = canonicalize(receipt)
        receipt_hash = _sha(receipt_raw)
        _write_once(self.evaluations / f"{receipt_hash}.json", receipt_raw)
        with ledger_lock(self.registry_path):
            self._recover_locked()
            registry = self._read_registry()
            if registry["generation"] != expected_generation:
                raise StaleRegistryError("registry generation changed before candidate validation")
            slots = dict(registry["slots"])
            if key not in slots or slots[key].get("challenger_artifact_id") != artifact_id:
                raise LifecycleError("artifact is not the current challenger for this slot")
            slot = dict(slots[key])
            validation = dict(slot.get("validation", {}))
            validation[artifact_id] = {
                "eligible": eligible,
                "receipt_sha256": receipt_hash,
                "evaluation_manifest_sha256": receipt["evaluation_manifest_sha256"],
                "target_list_sha256": receipt["target_list_sha256"],
                "target_count": receipt["target_count"],
            }
            slot["validation"] = validation
            slots[key] = slot
            new_registry = {**registry, "slots": slots}
            return self._commit_locked(
                registry, new_registry,
                event_type="candidate_validated" if eligible else "candidate_validation_failed",
                population_key=population_key, zone=zone, artifact_id=artifact_id,
                previous_artifact_id=slot.get("champion_artifact_id"), actor=actor,
                workflow_run_id=workflow_run_id, evidence_sha256=receipt_hash,
                reason_code=receipt["reason_code"] or ("all_gates_passed" if eligible else "evaluation_gate_failed"),
            )

    def _verified_approval(
        self,
        approval: dict[str, Any],
        *,
        approval_verifier: ApprovalVerifier | None,
        action: str,
        artifact_id: str,
        population_key: str,
        zone: str,
        expected_champion_artifact_id: str | None,
        evaluation_manifest_sha256: str,
        evaluation_receipt_sha256: str,
        shadow_receipt_sha256: str | None = None,
    ) -> tuple[bytes, str]:
        _validate_approval(
            approval, action=action, artifact_id=artifact_id,
            population_key=population_key, zone=zone,
            expected_champion_artifact_id=expected_champion_artifact_id,
            evaluation_manifest_sha256=evaluation_manifest_sha256,
            evaluation_receipt_sha256=evaluation_receipt_sha256,
            shadow_receipt_sha256=shadow_receipt_sha256,
        )
        if approval_verifier is None or approval_verifier(approval, {
            "action": action, "artifact_id": artifact_id,
            "population_key": population_key, "zone": zone,
            "expected_champion_artifact_id": expected_champion_artifact_id,
            "evaluation_manifest_sha256": evaluation_manifest_sha256,
            "evaluation_receipt_sha256": evaluation_receipt_sha256,
            "shadow_receipt_sha256": shadow_receipt_sha256,
            "policy_version": POLICY_VERSION,
        }) is not True:
            raise LifecycleError("protected cryptographic approval verifier is absent or rejected the receipt")
        raw = canonicalize(approval)
        digest = _sha(raw)
        _write_once(self.approvals / f"{digest}.json", raw)
        return raw, digest

    def mark_shadow(
        self, *, population_key: str, zone: str, artifact_id: str,
        shadow_receipt: dict[str, Any], expected_generation: int,
        actor: str, workflow_run_id: str | None = None,
    ) -> dict[str, Any]:
        """Record a prospective paired shadow evaluation; only a complete PASS enters shadow."""
        _require_generation(expected_generation)
        key = _slot_key(population_key, zone)
        with ledger_lock(self.registry_path):
            self._recover_locked()
            registry = self._read_registry()
            if registry["generation"] != expected_generation:
                raise StaleRegistryError("registry generation changed before shadow transition")
            slots = dict(registry["slots"])
            if key not in slots or slots[key].get("challenger_artifact_id") != artifact_id:
                raise LifecycleError("only the registered challenger can enter shadow")
            slot = dict(slots[key])
            champion_id = slot.get("champion_artifact_id")
            if champion_id is None or slot.get("suspended") is True:
                raise LifecycleError("prospective shadow evaluation requires an active Champion")
            if slot.get("shadow_artifact_id") is not None:
                raise LifecycleError("slot already contains a shadow artifact")
            validation = slot.get("validation", {}).get(artifact_id)
            if not validation or validation.get("eligible") is not True:
                raise LifecycleError("candidate cannot enter shadow before passing retrospective validation")
            artifact = self._load_artifact(artifact_id)
            eligible = _validate_shadow_receipt(
                shadow_receipt, artifact=artifact, artifact_id=artifact_id,
                population_key=population_key, zone=zone,
                champion_artifact_id=champion_id,
            )
            raw = canonicalize(shadow_receipt)
            shadow_hash = _sha(raw)
            _write_once(self.evaluations / f"{shadow_hash}.json", raw)
            shadow_validation = dict(slot.get("shadow_validation", {}))
            shadow_validation[artifact_id] = {
                "eligible": eligible,
                "receipt_sha256": shadow_hash,
                "shadow_manifest_sha256": shadow_receipt["shadow_manifest_sha256"],
                "target_list_sha256": shadow_receipt["target_list_sha256"],
                "target_count": shadow_receipt["target_count"],
                "champion_artifact_id": champion_id,
            }
            slot["shadow_validation"] = shadow_validation
            if eligible:
                slot["challenger_artifact_id"] = None
                slot["shadow_artifact_id"] = artifact_id
            slots[key] = slot
            new_registry = {**registry, "slots": slots}
            return self._commit_locked(
                registry, new_registry,
                event_type="candidate_entered_shadow" if eligible else "candidate_shadow_failed",
                population_key=population_key, zone=zone, artifact_id=artifact_id,
                previous_artifact_id=champion_id, actor=actor,
                workflow_run_id=workflow_run_id,
                evidence_sha256=shadow_hash,
                reason_code=shadow_receipt["reason_code"] or (
                    "prospective_shadow_gates_passed" if eligible else "prospective_shadow_gate_failed"
                ),
            )

    def promote_three_slot_generation(
        self,
        transitions: list[dict[str, Any]],
        *,
        expected_generation: int,
        approval_verifier: ApprovalVerifier | None,
        actor: str,
        workflow_run_id: str | None = None,
    ) -> dict[str, Any]:
        """Atomically publish all front/back Champions for reported indices 1, 2 and 3."""
        _require_generation(expected_generation)
        if not isinstance(transitions, list) or len(transitions) != 6:
            raise LifecycleError("atomic three-slot promotion requires exactly six zone transitions")
        if approval_verifier is None:
            raise LifecycleError("atomic three-slot promotion requires the protected approval verifier")
        current = self.snapshot()
        if current["generation"] != expected_generation:
            raise StaleRegistryError("registry generation changed before three-slot promotion")
        normalized: dict[str, dict[str, Any]] = {}
        population_keys: set[str] = set()
        evidence_hashes: set[str] = set()
        manifests: set[str] = set()
        target_lists: set[str] = set()
        target_counts: set[int] = set()
        shadow_manifests: set[str] = set()
        shadow_target_lists: set[str] = set()
        shadow_source_evidence: set[str] = set()
        shadow_target_counts: set[int] = set()
        training_by_population: dict[str, str] = {}
        artifact_ids_by_zone: dict[str, set[str]] = {"front": set(), "back": set()}
        verified: list[dict[str, Any]] = []

        for transition in transitions:
            required = {
                "population_key", "zone", "artifact_id",
                "expected_champion_artifact_id", "approval",
            }
            if not isinstance(transition, dict) or set(transition) != required:
                raise LifecycleError("three-slot transition fields do not match the closed schema")
            population_key = transition["population_key"]
            zone = transition["zone"]
            key = _slot_key(population_key, zone)
            if key in normalized:
                raise LifecycleError("three-slot promotion contains a duplicate population/zone")
            regime_id, _ = _parse_regime_population_key(population_key)
            population_keys.add(population_key)
            slot = current["slots"].get(key)
            artifact_id = transition["artifact_id"]
            expected_champion = transition["expected_champion_artifact_id"]
            if expected_champion is not None:
                self._artifact_path(expected_champion)
            if not slot or artifact_id not in (
                slot.get("challenger_artifact_id"), slot.get("shadow_artifact_id")
            ):
                raise LifecycleError("three-slot candidate is not registered as challenger or shadow")
            if slot.get("suspended") is True:
                raise LifecycleError("suspended slots require an approved restore before promotion")
            if slot.get("champion_artifact_id") != expected_champion:
                raise StaleRegistryError("three-slot expected Champion pointer does not match")
            validation = slot.get("validation", {}).get(artifact_id)
            if not validation or validation.get("eligible") is not True:
                raise LifecycleError("three-slot candidate has not passed preregistered validation")
            receipt = self._load_evaluation_receipt(validation["receipt_sha256"])
            if (
                receipt.get("artifact_id") != artifact_id
                or receipt.get("population_key") != population_key
                or receipt.get("zone") != zone
                or receipt.get("population_eligibility") != "verified_regime"
                or not _is_sha(receipt.get("population_evidence_sha256"))
            ):
                raise LifecycleError("three-slot candidate lacks verified regime evidence")
            artifact = self._load_artifact(artifact_id)
            if (
                artifact.get("zone") != zone
                or artifact.get("training_snapshot_sha256") != receipt["training_population_sha256"]
                or artifact.get("training_row_count", 0) < 300
            ):
                raise LifecycleError("three-slot candidate artifact has an invalid training population")
            evidence_hashes.add(receipt["population_evidence_sha256"])
            manifests.add(receipt["evaluation_manifest_sha256"])
            target_lists.add(receipt["target_list_sha256"])
            target_counts.add(receipt["target_count"])
            prior_training = training_by_population.setdefault(
                population_key, receipt["training_population_sha256"]
            )
            if prior_training != receipt["training_population_sha256"]:
                raise LifecycleError("front/back candidate artifacts use different training populations")
            if artifact_id in artifact_ids_by_zone[zone]:
                raise LifecycleError("three reported-index populations cannot reuse a zone artifact")
            artifact_ids_by_zone[zone].add(artifact_id)
            shadow_validation = slot.get("shadow_validation", {}).get(artifact_id)
            shadow_hash = None
            if expected_champion is not None:
                if (slot.get("shadow_artifact_id") != artifact_id or not shadow_validation
                        or shadow_validation.get("eligible") is not True):
                    raise LifecycleError("replacement three-slot candidate must pass prospective shadow evaluation")
                shadow_hash = shadow_validation["receipt_sha256"]
                shadow_receipt = self._load_shadow_receipt(shadow_hash)
                if not _validate_shadow_receipt(
                    shadow_receipt, artifact=artifact, artifact_id=artifact_id,
                    population_key=population_key, zone=zone,
                    champion_artifact_id=expected_champion,
                ):
                    raise LifecycleError("three-slot shadow receipt no longer passes its gates")
                shadow_manifests.add(shadow_receipt["shadow_manifest_sha256"])
                shadow_target_lists.add(shadow_receipt["target_list_sha256"])
                shadow_source_evidence.add(shadow_receipt["source_evidence_sha256"])
                shadow_target_counts.add(shadow_receipt["target_count"])
            _, approval_hash = self._verified_approval(
                transition["approval"], approval_verifier=approval_verifier,
                action="promote", artifact_id=artifact_id,
                population_key=population_key, zone=zone,
                expected_champion_artifact_id=expected_champion,
                evaluation_manifest_sha256=receipt["evaluation_manifest_sha256"],
                evaluation_receipt_sha256=validation["receipt_sha256"],
                shadow_receipt_sha256=shadow_hash,
            )
            normalized[key] = {
                "population_key": population_key,
                "zone": zone,
                "artifact_id": artifact_id,
                "expected_champion_artifact_id": expected_champion,
                "approval_sha256": approval_hash,
                "evaluation_receipt_sha256": validation["receipt_sha256"],
                "shadow_receipt_sha256": shadow_hash,
            }
            verified.append(normalized[key])

        parsed = [_parse_regime_population_key(key) for key in population_keys]
        if (
            len(population_keys) != 3
            or len({regime_id for regime_id, _ in parsed}) != 1
            or {index for _, index in parsed} != {1, 2, 3}
            or set(normalized) != {
                f"{population_key}|{zone}"
                for population_key in population_keys for zone in ZONES
            }
        ):
            raise LifecycleError("atomic promotion must cover indices 1/2/3 and both zones in one regime")
        if len(evidence_hashes) != 1 or len(manifests) != 1 or len(target_lists) != 1 or len(target_counts) != 1:
            raise LifecycleError("three-slot candidates must share one evidence, evaluation and target manifest")
        has_existing_champions = any(
            item["expected_champion_artifact_id"] is not None for item in normalized.values()
        )
        if has_existing_champions and (
            len(shadow_manifests) != 1 or len(shadow_target_lists) != 1
            or len(shadow_source_evidence) != 1 or len(shadow_target_counts) != 1
        ):
            raise LifecycleError("replacement three-slot candidates must share one complete shadow evaluation window")
        if len(set(training_by_population.values())) != 3:
            raise LifecycleError("three reported-index slots must use three distinct training populations")

        regime_id = parsed[0][0]
        with ledger_lock(self.registry_path):
            self._recover_locked()
            registry = self._read_registry()
            if registry["generation"] != expected_generation:
                raise StaleRegistryError("registry generation changed before atomic three-slot commit")
            slots = dict(registry["slots"])
            new_generation = registry["generation"] + 1
            for key, transition in normalized.items():
                slot = dict(slots[key])
                if (
                    transition["artifact_id"] not in (
                        slot.get("challenger_artifact_id"), slot.get("shadow_artifact_id")
                    )
                    or slot.get("champion_artifact_id") != transition["expected_champion_artifact_id"]
                ):
                    raise StaleRegistryError("a three-slot pointer changed before atomic commit")
                shadow_hash = transition["shadow_receipt_sha256"]
                if shadow_hash is not None:
                    current_shadow = slot.get("shadow_validation", {}).get(transition["artifact_id"])
                    if (slot.get("shadow_artifact_id") != transition["artifact_id"] or not current_shadow
                            or current_shadow.get("eligible") is not True
                            or current_shadow.get("receipt_sha256") != shadow_hash):
                        raise StaleRegistryError("a three-slot shadow receipt changed before atomic commit")
                retired = list(slot.get("retired_artifact_ids", []))
                old_champion = transition["expected_champion_artifact_id"]
                if old_champion is not None and old_champion not in retired:
                    retired.append(old_champion)
                slot["retired_artifact_ids"] = retired
                slot["champion_artifact_id"] = transition["artifact_id"]
                slot["champion_generation"] = new_generation
                slot["challenger_artifact_id"] = None
                slot["shadow_artifact_id"] = None
                slot["suspended"] = False
                slot["suspension_reason"] = None
                approvals = dict(slot.get("approval", {}))
                approvals[transition["artifact_id"]] = transition["approval_sha256"]
                slot["approval"] = approvals
                slots[key] = slot
            new_registry = {**registry, "slots": slots}
            event_transitions = [
                {
                    "population_key": item["population_key"],
                    "zone": item["zone"],
                    "artifact_id": item["artifact_id"],
                    "previous_artifact_id": item["expected_champion_artifact_id"],
                    "approval_sha256": item["approval_sha256"],
                    "evaluation_receipt_sha256": item["evaluation_receipt_sha256"],
                    "shadow_receipt_sha256": item["shadow_receipt_sha256"],
                }
                for item in verified
            ]
            return self._commit_locked(
                registry, new_registry, event_type="three_slot_generation_promoted",
                population_key=regime_id, zone="all", artifact_id=None,
                previous_artifact_id=None, actor=actor,
                workflow_run_id=workflow_run_id,
                evidence_sha256=_sha(canonicalize([item["approval_sha256"] for item in verified])),
                reason_code="atomic_three_slot_generation_passed",
                event_details={"transitions": event_transitions},
            )

    def promote_candidate(
        self,
        *,
        population_key: str,
        zone: str,
        artifact_id: str,
        expected_champion_artifact_id: str | None,
        expected_generation: int,
        approval: dict[str, Any],
        approval_verifier: ApprovalVerifier | None,
        actor: str,
        workflow_run_id: str | None = None,
    ) -> dict[str, Any]:
        _require_generation(expected_generation)
        key = _slot_key(population_key, zone)
        slot_snapshot = self.snapshot()["slots"].get(key)
        if slot_snapshot is None:
            raise LifecycleError("slot does not exist")
        validation = slot_snapshot.get("validation", {}).get(artifact_id)
        if (artifact_id not in (slot_snapshot.get("challenger_artifact_id"), slot_snapshot.get("shadow_artifact_id"))
                or not validation or validation.get("eligible") is not True):
            raise LifecycleError("challenger/shadow artifact has not passed every preregistered promotion gate")
        if slot_snapshot.get("champion_artifact_id") != expected_champion_artifact_id:
            raise StaleRegistryError("expected Champion artifact does not match current registry")
        evaluation = self._load_evaluation_receipt(validation["receipt_sha256"])
        if evaluation["population_eligibility"] == "verified_regime":
            raise LifecycleError("verified regime candidates must be promoted as one atomic three-slot generation")
        shadow_hash = None
        if expected_champion_artifact_id is not None:
            shadow_validation = slot_snapshot.get("shadow_validation", {}).get(artifact_id)
            if (slot_snapshot.get("shadow_artifact_id") != artifact_id or not shadow_validation
                    or shadow_validation.get("eligible") is not True):
                raise LifecycleError("replacement Champion requires a passing prospective shadow receipt")
            shadow_hash = shadow_validation["receipt_sha256"]
            shadow_receipt = self._load_shadow_receipt(shadow_hash)
            artifact = self._load_artifact(artifact_id)
            if not _validate_shadow_receipt(
                shadow_receipt, artifact=artifact, artifact_id=artifact_id,
                population_key=population_key, zone=zone,
                champion_artifact_id=expected_champion_artifact_id,
            ):
                raise LifecycleError("prospective shadow receipt no longer passes its gates")
        elif slot_snapshot.get("challenger_artifact_id") != artifact_id:
            raise LifecycleError("initial Champion must be promoted from challenger, not shadow")
        manifest_hash = validation["evaluation_manifest_sha256"]
        _, approval_hash = self._verified_approval(
            approval, approval_verifier=approval_verifier, action="promote",
            artifact_id=artifact_id, population_key=population_key, zone=zone,
            expected_champion_artifact_id=expected_champion_artifact_id,
            evaluation_manifest_sha256=manifest_hash,
            evaluation_receipt_sha256=validation["receipt_sha256"],
            shadow_receipt_sha256=shadow_hash,
        )
        with ledger_lock(self.registry_path):
            self._recover_locked()
            registry = self._read_registry()
            if registry["generation"] != expected_generation:
                raise StaleRegistryError("registry generation changed before promotion")
            slots = dict(registry["slots"])
            slot = dict(slots[key])
            if (artifact_id not in (slot.get("challenger_artifact_id"), slot.get("shadow_artifact_id"))
                    or slot.get("champion_artifact_id") != expected_champion_artifact_id):
                raise StaleRegistryError("Champion/challenger/shadow pointers changed before promotion")
            if slot.get("suspended") is True:
                raise LifecycleError("suspended slot cannot be promoted without an explicit revalidation")
            if shadow_hash is not None:
                current_shadow = slot.get("shadow_validation", {}).get(artifact_id)
                if (slot.get("shadow_artifact_id") != artifact_id or not current_shadow
                        or current_shadow.get("eligible") is not True
                        or current_shadow.get("receipt_sha256") != shadow_hash):
                    raise StaleRegistryError("prospective shadow receipt changed before promotion")
            retired = list(slot.get("retired_artifact_ids", []))
            if expected_champion_artifact_id is not None and expected_champion_artifact_id not in retired:
                retired.append(expected_champion_artifact_id)
            slot["retired_artifact_ids"] = retired
            slot["champion_artifact_id"] = artifact_id
            slot["champion_generation"] = registry["generation"] + 1
            slot["challenger_artifact_id"] = None
            slot["shadow_artifact_id"] = None
            slot["suspended"] = False
            slot["suspension_reason"] = None
            approvals = dict(slot.get("approval", {}))
            approvals[artifact_id] = approval_hash
            slot["approval"] = approvals
            slots[key] = slot
            new_registry = {**registry, "slots": slots}
            return self._commit_locked(
                registry, new_registry, event_type="promoted",
                population_key=population_key, zone=zone, artifact_id=artifact_id,
                previous_artifact_id=expected_champion_artifact_id, actor=actor,
                workflow_run_id=workflow_run_id, evidence_sha256=approval_hash,
                reason_code="preregistered_gates_and_protected_approval_passed",
            )

    def reject_challenger(
        self, *, population_key: str, zone: str, artifact_id: str,
        expected_generation: int, actor: str, reason_code: str,
        workflow_run_id: str | None = None,
    ) -> dict[str, Any]:
        _require_generation(expected_generation)
        key = _slot_key(population_key, zone)
        if not reason_code:
            raise LifecycleError("rejection requires a reason_code")
        with ledger_lock(self.registry_path):
            self._recover_locked()
            registry = self._read_registry()
            if registry["generation"] != expected_generation:
                raise StaleRegistryError("registry generation changed before rejection")
            slots = dict(registry["slots"])
            if key not in slots or artifact_id not in (slots[key].get("challenger_artifact_id"), slots[key].get("shadow_artifact_id")):
                raise LifecycleError("artifact is not the current challenger or shadow")
            slot = dict(slots[key])
            rejected = list(slot.get("rejected_artifact_ids", []))
            if artifact_id not in rejected:
                rejected.append(artifact_id)
            slot["rejected_artifact_ids"] = rejected
            slot["challenger_artifact_id"] = None
            slot["shadow_artifact_id"] = None
            slots[key] = slot
            new_registry = {**registry, "slots": slots}
            return self._commit_locked(
                registry, new_registry, event_type="challenger_rejected",
                population_key=population_key, zone=zone, artifact_id=artifact_id,
                previous_artifact_id=slot.get("champion_artifact_id"), actor=actor,
                workflow_run_id=workflow_run_id, evidence_sha256=None,
                reason_code=reason_code,
            )

    def suspend_slot(
        self, *, population_key: str, zone: str, expected_generation: int,
        actor: str, reason_code: str, workflow_run_id: str | None = None,
    ) -> dict[str, Any]:
        _require_generation(expected_generation)
        key = _slot_key(population_key, zone)
        if not reason_code:
            raise LifecycleError("suspension requires a reason_code")
        with ledger_lock(self.registry_path):
            self._recover_locked()
            registry = self._read_registry()
            if registry["generation"] != expected_generation:
                raise StaleRegistryError("registry generation changed before suspension")
            slots = dict(registry["slots"])
            if key not in slots:
                raise LifecycleError("cannot suspend an unknown slot")
            slot = dict(slots[key])
            slot["suspended"] = True
            slot["suspension_reason"] = reason_code
            slots[key] = slot
            new_registry = {**registry, "slots": slots}
            return self._commit_locked(
                registry, new_registry, event_type="slot_suspended",
                population_key=population_key, zone=zone,
                artifact_id=slot.get("champion_artifact_id"),
                previous_artifact_id=slot.get("champion_artifact_id"),
                actor=actor, workflow_run_id=workflow_run_id,
                evidence_sha256=None, reason_code=reason_code,
            )

    def restore_retired(
        self, *, population_key: str, zone: str, artifact_id: str,
        expected_champion_artifact_id: str | None, expected_generation: int,
        approval: dict[str, Any], approval_verifier: ApprovalVerifier | None,
        actor: str, workflow_run_id: str | None = None,
    ) -> dict[str, Any]:
        _require_generation(expected_generation)
        key = _slot_key(population_key, zone)
        registry_snapshot = self.snapshot()
        slot_snapshot = registry_snapshot["slots"].get(key)
        if slot_snapshot is None or artifact_id not in slot_snapshot.get("retired_artifact_ids", []):
            raise LifecycleError("restore target is not a retired artifact for this slot")
        validation = slot_snapshot.get("validation", {}).get(artifact_id)
        if not validation or validation.get("eligible") is not True:
            raise LifecycleError("retired artifact no longer has a passing validation receipt")
        artifact = self._load_artifact(artifact_id)
        retired_receipt = self._load_evaluation_receipt(validation["receipt_sha256"])
        if retired_receipt["population_eligibility"] == "verified_regime":
            raise LifecycleError("verified regime rollback must restore the complete three-slot generation atomically")
        if (retired_receipt.get("artifact_id") != artifact_id
                or retired_receipt.get("population_key") != population_key
                or retired_receipt.get("zone") != zone
                or retired_receipt.get("training_population_sha256") != artifact.get("training_snapshot_sha256")
                or artifact.get("zone") != zone):
            raise LifecycleError("retired artifact evidence/zone is incompatible with slot")
        if expected_champion_artifact_id is not None:
            current_artifact = self._load_artifact(expected_champion_artifact_id)
            for field in ("model_family", "zone", "population_size", "selection_size", "feature_schema_hash"):
                if artifact.get(field) != current_artifact.get(field):
                    raise LifecycleError("retired artifact is incompatible with current Champion schema")
        if slot_snapshot.get("champion_artifact_id") != expected_champion_artifact_id:
            raise StaleRegistryError("expected Champion artifact does not match current registry")
        _, approval_hash = self._verified_approval(
            approval, approval_verifier=approval_verifier, action="restore",
            artifact_id=artifact_id, population_key=population_key, zone=zone,
            expected_champion_artifact_id=expected_champion_artifact_id,
            evaluation_manifest_sha256=validation["evaluation_manifest_sha256"],
            evaluation_receipt_sha256=validation["receipt_sha256"],
            shadow_receipt_sha256=None,
        )
        with ledger_lock(self.registry_path):
            self._recover_locked()
            registry = self._read_registry()
            if registry["generation"] != expected_generation:
                raise StaleRegistryError("registry generation changed before restoration")
            slots = dict(registry["slots"])
            slot = dict(slots[key])
            if slot.get("champion_artifact_id") != expected_champion_artifact_id:
                raise StaleRegistryError("Champion pointer changed before restoration")
            retired = list(slot.get("retired_artifact_ids", []))
            retired.remove(artifact_id)
            if expected_champion_artifact_id is not None and expected_champion_artifact_id not in retired:
                retired.append(expected_champion_artifact_id)
            slot["retired_artifact_ids"] = retired
            slot["champion_artifact_id"] = artifact_id
            slot["champion_generation"] = registry["generation"] + 1
            slot["suspended"] = False
            slot["suspension_reason"] = None
            approvals = dict(slot.get("approval", {}))
            approvals[artifact_id] = approval_hash
            slot["approval"] = approvals
            slots[key] = slot
            new_registry = {**registry, "slots": slots}
            return self._commit_locked(
                registry, new_registry, event_type="champion_restored",
                population_key=population_key, zone=zone, artifact_id=artifact_id,
                previous_artifact_id=expected_champion_artifact_id, actor=actor,
                workflow_run_id=workflow_run_id, evidence_sha256=approval_hash,
                reason_code="compatible_retired_artifact_restored",
            )

    def restore_three_slot_generation(
        self,
        transitions: list[dict[str, Any]],
        *,
        expected_generation: int,
        approval_verifier: ApprovalVerifier | None,
        actor: str,
        workflow_run_id: str | None = None,
    ) -> dict[str, Any]:
        """Atomically restore six compatible retired artifacts as one Champion generation."""
        _require_generation(expected_generation)
        if not isinstance(transitions, list) or len(transitions) != 6:
            raise LifecycleError("atomic three-slot restoration requires exactly six zone transitions")
        if approval_verifier is None:
            raise LifecycleError("atomic three-slot restoration requires the protected approval verifier")
        current = self.snapshot()
        if current["generation"] != expected_generation:
            raise StaleRegistryError("registry generation changed before three-slot restoration")
        normalized: dict[str, dict[str, Any]] = {}
        population_keys: set[str] = set()
        evidence_hashes: set[str] = set()
        manifests: set[str] = set()
        target_lists: set[str] = set()
        target_counts: set[int] = set()
        training_by_population: dict[str, str] = {}
        artifact_ids_by_zone: dict[str, set[str]] = {"front": set(), "back": set()}

        for transition in transitions:
            required = {
                "population_key", "zone", "artifact_id",
                "expected_champion_artifact_id", "approval",
            }
            if not isinstance(transition, dict) or set(transition) != required:
                raise LifecycleError("three-slot restore fields do not match the closed schema")
            population_key = transition["population_key"]
            zone = transition["zone"]
            key = _slot_key(population_key, zone)
            if key in normalized:
                raise LifecycleError("three-slot restore contains a duplicate population/zone")
            regime_id, _ = _parse_regime_population_key(population_key)
            population_keys.add(population_key)
            slot = current["slots"].get(key)
            artifact_id = transition["artifact_id"]
            expected_champion = transition["expected_champion_artifact_id"]
            if not slot or artifact_id not in slot.get("retired_artifact_ids", []):
                raise LifecycleError("three-slot restore target is not a retired artifact for its slot")
            if slot.get("champion_artifact_id") != expected_champion:
                raise StaleRegistryError("three-slot restore expected Champion pointer does not match")
            validation = slot.get("validation", {}).get(artifact_id)
            if not validation or validation.get("eligible") is not True:
                raise LifecycleError("three-slot restore target lacks a passing immutable validation receipt")
            receipt = self._load_evaluation_receipt(validation["receipt_sha256"])
            if (
                receipt.get("artifact_id") != artifact_id
                or receipt.get("population_key") != population_key
                or receipt.get("zone") != zone
                or receipt.get("population_eligibility") != "verified_regime"
                or not _is_sha(receipt.get("population_evidence_sha256"))
            ):
                raise LifecycleError("three-slot restore target lacks verified regime evidence")
            artifact = self._load_artifact(artifact_id)
            current_artifact = self._load_artifact(expected_champion)
            for field in ("model_family", "zone", "population_size", "selection_size", "feature_schema_hash"):
                if artifact.get(field) != current_artifact.get(field):
                    raise LifecycleError("three-slot restore target is incompatible with current Champion schema")
            if (
                artifact.get("training_snapshot_sha256") != receipt["training_population_sha256"]
                or artifact.get("training_row_count", 0) < 300
            ):
                raise LifecycleError("three-slot restore target has an invalid training population")
            evidence_hashes.add(receipt["population_evidence_sha256"])
            manifests.add(receipt["evaluation_manifest_sha256"])
            target_lists.add(receipt["target_list_sha256"])
            target_counts.add(receipt["target_count"])
            prior_training = training_by_population.setdefault(
                population_key, receipt["training_population_sha256"]
            )
            if prior_training != receipt["training_population_sha256"]:
                raise LifecycleError("front/back restore targets use different training populations")
            if artifact_id in artifact_ids_by_zone[zone]:
                raise LifecycleError("three reported-index restore targets reuse a zone artifact")
            artifact_ids_by_zone[zone].add(artifact_id)
            _, approval_hash = self._verified_approval(
                transition["approval"], approval_verifier=approval_verifier,
                action="restore", artifact_id=artifact_id,
                population_key=population_key, zone=zone,
                expected_champion_artifact_id=expected_champion,
                evaluation_manifest_sha256=receipt["evaluation_manifest_sha256"],
                evaluation_receipt_sha256=validation["receipt_sha256"],
                shadow_receipt_sha256=None,
            )
            normalized[key] = {
                "population_key": population_key,
                "zone": zone,
                "artifact_id": artifact_id,
                "expected_champion_artifact_id": expected_champion,
                "approval_sha256": approval_hash,
                "evaluation_receipt_sha256": validation["receipt_sha256"],
            }

        parsed = [_parse_regime_population_key(key) for key in population_keys]
        if (
            len(population_keys) != 3
            or len({regime_id for regime_id, _ in parsed}) != 1
            or {index for _, index in parsed} != {1, 2, 3}
            or set(normalized) != {
                f"{population_key}|{zone}"
                for population_key in population_keys for zone in ZONES
            }
        ):
            raise LifecycleError("atomic restoration must cover indices 1/2/3 and both zones in one regime")
        if len(evidence_hashes) != 1 or len(manifests) != 1 or len(target_lists) != 1 or len(target_counts) != 1:
            raise LifecycleError("restored slots must share one evidence, evaluation and target manifest")
        if len(set(training_by_population.values())) != 3:
            raise LifecycleError("restored reported-index slots must use three distinct training populations")

        regime_id = parsed[0][0]
        with ledger_lock(self.registry_path):
            self._recover_locked()
            registry = self._read_registry()
            if registry["generation"] != expected_generation:
                raise StaleRegistryError("registry generation changed before atomic three-slot restore")
            slots = dict(registry["slots"])
            new_generation = registry["generation"] + 1
            for key, transition in normalized.items():
                slot = dict(slots[key])
                old_champion = transition["expected_champion_artifact_id"]
                artifact_id = transition["artifact_id"]
                if (
                    artifact_id not in slot.get("retired_artifact_ids", [])
                    or slot.get("champion_artifact_id") != old_champion
                ):
                    raise StaleRegistryError("three-slot retired/Champion pointer changed before restore")
                retired = list(slot["retired_artifact_ids"])
                retired.remove(artifact_id)
                if old_champion not in retired:
                    retired.append(old_champion)
                slot["retired_artifact_ids"] = retired
                slot["champion_artifact_id"] = artifact_id
                slot["champion_generation"] = new_generation
                slot["suspended"] = False
                slot["suspension_reason"] = None
                approvals = dict(slot.get("approval", {}))
                approvals[artifact_id] = transition["approval_sha256"]
                slot["approval"] = approvals
                slots[key] = slot
            new_registry = {**registry, "slots": slots}
            event_transitions = [
                {
                    "population_key": item["population_key"],
                    "zone": item["zone"],
                    "artifact_id": item["artifact_id"],
                    "previous_artifact_id": item["expected_champion_artifact_id"],
                    "approval_sha256": item["approval_sha256"],
                    "evaluation_receipt_sha256": item["evaluation_receipt_sha256"],
                }
                for item in normalized.values()
            ]
            return self._commit_locked(
                registry, new_registry, event_type="three_slot_generation_restored",
                population_key=regime_id, zone="all", artifact_id=None,
                previous_artifact_id=None, actor=actor,
                workflow_run_id=workflow_run_id,
                evidence_sha256=_sha(canonicalize([item["approval_sha256"] for item in normalized.values()])),
                reason_code="atomic_compatible_three_slot_generation_restored",
                event_details={"transitions": event_transitions},
            )

    def resolve_three_slot_generation(
        self,
        population_keys: list[str],
        *,
        approval_verifier: ApprovalVerifier | None,
    ) -> dict[str, Any]:
        if (
            not isinstance(population_keys, list)
            or len(population_keys) != 3
            or any(not isinstance(key, str) or not key for key in population_keys)
            or len(set(population_keys)) != 3
        ):
            raise LifecycleError("three-slot resolution requires exactly three distinct population keys")
        parsed_keys = [_parse_regime_population_key(key) for key in population_keys]
        if (len({regime_id for regime_id, _ in parsed_keys}) != 1
                or {index for _, index in parsed_keys} != {1, 2, 3}):
            raise LifecycleError("three-slot resolution requires reported indices 1/2/3 in one verified equipment regime")
        if approval_verifier is None:
            raise LifecycleError("three-slot resolution requires the protected approval verifier")
        registry = self.snapshot()
        resolved = []
        champion_generations: set[int] = set()
        evidence_by_population: dict[str, str] = {}
        training_by_population: dict[str, str] = {}
        artifacts_by_zone: dict[str, set[str]] = {"front": set(), "back": set()}
        for population_key in population_keys:
            for zone in ZONES:
                key = _slot_key(population_key, zone)
                slot = registry["slots"].get(key)
                if not slot or slot.get("suspended") is True:
                    raise LifecycleError("three-slot generation is incomplete or contains a suspended slot")
                artifact_id = slot.get("champion_artifact_id")
                champion_generation = slot.get("champion_generation")
                if type(champion_generation) is not int:
                    raise LifecycleError("three-slot Champion pointers were not published as one generation")
                champion_generations.add(champion_generation)
                approval_hash = slot.get("approval", {}).get(artifact_id)
                validation = slot.get("validation", {}).get(artifact_id)
                if not artifact_id or not approval_hash or not validation or validation.get("eligible") is not True:
                    raise LifecycleError("three-slot generation contains an unapproved or unvalidated artifact")
                artifact = self._load_artifact(artifact_id)
                receipt = self._load_evaluation_receipt(validation["receipt_sha256"])
                if (receipt.get("artifact_id") != artifact_id
                        or receipt.get("population_key") != population_key
                        or receipt.get("zone") != zone
                        or receipt.get("population_eligibility") != "verified_regime"
                        or not _is_sha(receipt.get("population_evidence_sha256"))):
                    raise LifecycleError("three-slot generation requires primary-verified regime evidence")
                evidence_hash = receipt["population_evidence_sha256"]
                previous_evidence_hash = evidence_by_population.setdefault(population_key, evidence_hash)
                if previous_evidence_hash != evidence_hash:
                    raise LifecycleError("front/back artifacts for a population key bind different evidence manifests")
                training_hash = receipt["training_population_sha256"]
                if training_hash != artifact.get("training_snapshot_sha256") or artifact.get("training_row_count", 0) < 300:
                    raise LifecycleError("three-slot artifact training population/cutoff is invalid")
                previous_training_hash = training_by_population.setdefault(population_key, training_hash)
                if previous_training_hash != training_hash:
                    raise LifecycleError("front/back artifacts for a population key use different training populations")
                if artifact_id in artifacts_by_zone[zone]:
                    raise LifecycleError("three population slots cannot reuse the same zone artifact")
                artifacts_by_zone[zone].add(artifact_id)
                if not _is_sha(approval_hash):
                    raise LifecycleError("Champion approval reference is malformed")
                approval_path = self.approvals / f"{approval_hash}.json"
                try:
                    approval = parse_json_strict(approval_path.read_bytes())
                except (OSError, ArtifactValidationError) as exc:
                    raise LifecycleError("Champion approval receipt is missing or invalid") from exc
                _validate_approval(
                    approval, action=approval.get("action"),
                    artifact_id=artifact_id, population_key=population_key,
                    zone=zone, expected_champion_artifact_id=approval.get("expected_champion_artifact_id"),
                    evaluation_manifest_sha256=validation["evaluation_manifest_sha256"],
                    evaluation_receipt_sha256=validation["receipt_sha256"],
                    shadow_receipt_sha256=approval.get("shadow_receipt_sha256"),
                )
                shadow_hash = approval.get("shadow_receipt_sha256")
                if shadow_hash is not None:
                    shadow_validation = slot.get("shadow_validation", {}).get(artifact_id)
                    if not shadow_validation or shadow_validation.get("receipt_sha256") != shadow_hash or shadow_validation.get("eligible") is not True:
                        raise LifecycleError("Champion shadow receipt reference is missing or ineligible")
                    shadow_receipt = self._load_shadow_receipt(shadow_hash)
                    if not _validate_shadow_receipt(
                        shadow_receipt, artifact=artifact, artifact_id=artifact_id,
                        population_key=population_key, zone=zone,
                        champion_artifact_id=approval.get("expected_champion_artifact_id"),
                    ):
                        raise LifecycleError("Champion shadow receipt failed verification at resolution")
                if approval_verifier(approval, {
                    "action": approval["action"], "artifact_id": artifact_id,
                    "population_key": population_key, "zone": zone,
                    "expected_champion_artifact_id": approval["expected_champion_artifact_id"],
                    "evaluation_manifest_sha256": validation["evaluation_manifest_sha256"],
                    "evaluation_receipt_sha256": validation["receipt_sha256"],
                    "shadow_receipt_sha256": shadow_hash,
                    "policy_version": POLICY_VERSION,
                }) is not True:
                    raise LifecycleError("Champion approval signature failed verification at resolution")
                resolved.append({
                    "population_key": population_key,
                    "zone": zone,
                    "artifact_id": artifact_id,
                    "artifact_sha256": artifact_id[7:],
                    "model_family": artifact["model_family"],
                    "training_cutoff_draw_id": artifact["training_cutoff_draw_id"],
                    "approval_sha256": approval_hash,
                })
        if len(set(training_by_population.values())) != 3:
            raise LifecycleError("three population slots must bind three distinct training populations")
        if len(champion_generations) != 1:
            raise LifecycleError("three-slot Champion pointers do not share one atomic generation")
        return {"registry_generation": registry["generation"], "champion_generation": next(iter(champion_generations)), "slots": resolved}
