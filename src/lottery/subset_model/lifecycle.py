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


def _slot_key(population_key: str, zone: str) -> str:
    if not isinstance(population_key, str) or not population_key or population_key.strip() != population_key:
        raise LifecycleError("population_key must be a non-empty canonical string")
    if zone not in ZONES:
        raise LifecycleError("zone must be 'front' or 'back'")
    return f"{population_key}|{zone}"


def _new_slot(population_key: str, zone: str) -> dict[str, Any]:
    return {
        "population_key": population_key,
        "zone": zone,
        "champion_artifact_id": None,
        "challenger_artifact_id": None,
        "retired_artifact_ids": [],
        "rejected_artifact_ids": [],
        "validation": {},
        "approval": {},
        "suspended": False,
        "suspension_reason": None,
    }


def _validate_evaluation_receipt(receipt: dict[str, Any]) -> bool:
    required = {
        "schema_version", "artifact_id", "population_key", "zone",
        "evaluation_manifest_sha256", "target_list_sha256", "target_count",
        "full_coverage", "preregistered", "holdout_accessed", "numerical_pass",
        "calibration_pass", "stability_pass", "front_improved", "back_improved",
        "multiplicity_pass", "uniform_non_regression_pass", "decision", "reason_code",
    }
    if not isinstance(receipt, dict) or set(receipt) != required:
        raise LifecycleError("evaluation receipt fields do not match the closed LOT-060 schema")
    if receipt["schema_version"] != EVALUATION_SCHEMA:
        raise LifecycleError("unsupported lifecycle evaluation schema")
    for field in ("evaluation_manifest_sha256", "target_list_sha256"):
        if not _is_sha(receipt[field]):
            raise LifecycleError(f"{field} must be a lowercase SHA-256")
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
) -> None:
    required = {
        "schema_version", "approval_id", "action", "artifact_id", "population_key",
        "zone", "expected_champion_artifact_id", "evaluation_manifest_sha256",
        "evaluation_receipt_sha256", "policy_version", "issued_at_utc", "signer_id", "signature",
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
    ):
        raise LifecycleError("approval scope does not match the requested lifecycle transition")
    for field in ("approval_id", "issued_at_utc", "signer_id", "signature"):
        if not isinstance(approval[field], str) or not approval[field]:
            raise LifecycleError(f"approval {field} must be a non-empty string")
    if not _is_sha(evaluation_receipt_sha256):
        raise LifecycleError("approval evaluation_receipt_sha256 must be a lowercase SHA-256")
    if approval["action"] not in ("promote", "restore"):
        raise LifecycleError("approval action must be promote or restore")
    try:
        datetime.fromisoformat(approval["issued_at_utc"].replace("Z", "+00:00"))
    except ValueError as exc:
        raise LifecycleError("approval issued_at_utc must be ISO-8601") from exc


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
                    or not isinstance(slot.get("approval"), dict)
                    or (slot.get("suspension_reason") is not None
                        and not isinstance(slot["suspension_reason"], str))):
                raise LifecycleError("Champion registry slot state is malformed")
            for field in ("champion_artifact_id", "challenger_artifact_id"):
                artifact_id = slot.get(field)
                if artifact_id is not None:
                    self._artifact_path(artifact_id)
            for artifact_id in slot["retired_artifact_ids"] + slot["rejected_artifact_ids"]:
                self._artifact_path(artifact_id)
            if any(not isinstance(v, dict) for v in slot["validation"].values()):
                raise LifecycleError("Champion validation references are malformed")
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
    ) -> dict[str, Any]:
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

    def snapshot(self) -> dict[str, Any]:
        with ledger_lock(self.registry_path):
            self._recover_locked()
            registry = self._read_registry()
            for slot in registry["slots"].values():
                for artifact_id in (
                    slot.get("champion_artifact_id"),
                    slot.get("challenger_artifact_id"),
                    *slot.get("retired_artifact_ids", []),
                ):
                    if artifact_id is not None:
                        self._load_artifact(artifact_id)
                for validation in slot.get("validation", {}).values():
                    self._load_evaluation_receipt(validation["receipt_sha256"])
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
            if existing == artifact_id:
                return registry
            if artifact_id in slot.get("rejected_artifact_ids", []):
                raise LifecycleError("a rejected immutable artifact cannot be re-registered")
            if existing is not None:
                raise LifecycleError("slot already has a challenger; reject it before registering another")
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
        key = _slot_key(population_key, zone)
        eligible = _validate_evaluation_receipt(receipt)
        if (
            receipt["population_key"] != population_key
            or receipt["zone"] != zone
            or receipt["artifact_id"] != artifact_id
        ):
            raise LifecycleError("evaluation receipt scope does not match challenger")
        self._load_artifact(artifact_id)
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
    ) -> tuple[bytes, str]:
        _validate_approval(
            approval, action=action, artifact_id=artifact_id,
            population_key=population_key, zone=zone,
            expected_champion_artifact_id=expected_champion_artifact_id,
            evaluation_manifest_sha256=evaluation_manifest_sha256,
            evaluation_receipt_sha256=evaluation_receipt_sha256,
        )
        if approval_verifier is None or approval_verifier(approval, {
            "action": action, "artifact_id": artifact_id,
            "population_key": population_key, "zone": zone,
            "expected_champion_artifact_id": expected_champion_artifact_id,
            "evaluation_manifest_sha256": evaluation_manifest_sha256,
            "evaluation_receipt_sha256": evaluation_receipt_sha256,
            "policy_version": POLICY_VERSION,
        }) is not True:
            raise LifecycleError("protected cryptographic approval verifier is absent or rejected the receipt")
        raw = canonicalize(approval)
        digest = _sha(raw)
        _write_once(self.approvals / f"{digest}.json", raw)
        return raw, digest

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
        key = _slot_key(population_key, zone)
        slot_snapshot = self.snapshot()["slots"].get(key)
        if slot_snapshot is None:
            raise LifecycleError("slot does not exist")
        validation = slot_snapshot.get("validation", {}).get(artifact_id)
        if slot_snapshot.get("challenger_artifact_id") != artifact_id or not validation or validation.get("eligible") is not True:
            raise LifecycleError("challenger has not passed every preregistered promotion gate")
        if slot_snapshot.get("champion_artifact_id") != expected_champion_artifact_id:
            raise StaleRegistryError("expected Champion artifact does not match current registry")
        manifest_hash = validation["evaluation_manifest_sha256"]
        _, approval_hash = self._verified_approval(
            approval, approval_verifier=approval_verifier, action="promote",
            artifact_id=artifact_id, population_key=population_key, zone=zone,
            expected_champion_artifact_id=expected_champion_artifact_id,
            evaluation_manifest_sha256=manifest_hash,
            evaluation_receipt_sha256=validation["receipt_sha256"],
        )
        with ledger_lock(self.registry_path):
            self._recover_locked()
            registry = self._read_registry()
            if registry["generation"] != expected_generation:
                raise StaleRegistryError("registry generation changed before promotion")
            slots = dict(registry["slots"])
            slot = dict(slots[key])
            if slot.get("challenger_artifact_id") != artifact_id or slot.get("champion_artifact_id") != expected_champion_artifact_id:
                raise StaleRegistryError("Champion/challenger pointers changed before promotion")
            if slot.get("suspended") is True:
                raise LifecycleError("suspended slot cannot be promoted without an explicit revalidation")
            retired = list(slot.get("retired_artifact_ids", []))
            if expected_champion_artifact_id is not None and expected_champion_artifact_id not in retired:
                retired.append(expected_champion_artifact_id)
            slot["retired_artifact_ids"] = retired
            slot["champion_artifact_id"] = artifact_id
            slot["challenger_artifact_id"] = None
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
        key = _slot_key(population_key, zone)
        if not reason_code:
            raise LifecycleError("rejection requires a reason_code")
        with ledger_lock(self.registry_path):
            self._recover_locked()
            registry = self._read_registry()
            if registry["generation"] != expected_generation:
                raise StaleRegistryError("registry generation changed before rejection")
            slots = dict(registry["slots"])
            if key not in slots or slots[key].get("challenger_artifact_id") != artifact_id:
                raise LifecycleError("artifact is not the current challenger")
            slot = dict(slots[key])
            rejected = list(slot.get("rejected_artifact_ids", []))
            if artifact_id not in rejected:
                rejected.append(artifact_id)
            slot["rejected_artifact_ids"] = rejected
            slot["challenger_artifact_id"] = None
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
        key = _slot_key(population_key, zone)
        registry_snapshot = self.snapshot()
        slot_snapshot = registry_snapshot["slots"].get(key)
        if slot_snapshot is None or artifact_id not in slot_snapshot.get("retired_artifact_ids", []):
            raise LifecycleError("restore target is not a retired artifact for this slot")
        validation = slot_snapshot.get("validation", {}).get(artifact_id)
        if not validation or validation.get("eligible") is not True:
            raise LifecycleError("retired artifact no longer has a passing validation receipt")
        artifact = self._load_artifact(artifact_id)
        if artifact.get("zone") != zone:
            raise LifecycleError("retired artifact zone is incompatible with slot")
        if slot_snapshot.get("champion_artifact_id") != expected_champion_artifact_id:
            raise StaleRegistryError("expected Champion artifact does not match current registry")
        _, approval_hash = self._verified_approval(
            approval, approval_verifier=approval_verifier, action="restore",
            artifact_id=artifact_id, population_key=population_key, zone=zone,
            expected_champion_artifact_id=expected_champion_artifact_id,
            evaluation_manifest_sha256=validation["evaluation_manifest_sha256"],
            evaluation_receipt_sha256=validation["receipt_sha256"],
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
        if approval_verifier is None:
            raise LifecycleError("three-slot resolution requires the protected approval verifier")
        registry = self.snapshot()
        resolved = []
        for population_key in population_keys:
            for zone in ZONES:
                key = _slot_key(population_key, zone)
                slot = registry["slots"].get(key)
                if not slot or slot.get("suspended") is True:
                    raise LifecycleError("three-slot generation is incomplete or contains a suspended slot")
                artifact_id = slot.get("champion_artifact_id")
                approval_hash = slot.get("approval", {}).get(artifact_id)
                validation = slot.get("validation", {}).get(artifact_id)
                if not artifact_id or not approval_hash or not validation or validation.get("eligible") is not True:
                    raise LifecycleError("three-slot generation contains an unapproved or unvalidated artifact")
                artifact = self._load_artifact(artifact_id)
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
                )
                if approval_verifier(approval, {
                    "action": approval["action"], "artifact_id": artifact_id,
                    "population_key": population_key, "zone": zone,
                    "expected_champion_artifact_id": approval["expected_champion_artifact_id"],
                    "evaluation_manifest_sha256": validation["evaluation_manifest_sha256"],
                    "evaluation_receipt_sha256": validation["receipt_sha256"],
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
        return {"registry_generation": registry["generation"], "slots": resolved}
