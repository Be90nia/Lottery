"""Fail-closed, receipt-derived Lottery release readiness evaluation.

This module reports readiness only. It never enables collection, serving,
model promotion, Champion mutation, or access to the protected LOT-042 holdout.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

GATE_IDS = tuple(f"G{i}" for i in range(9))
GATE_NAMES = {
    "G0": "source_build_integrity",
    "G1": "canonical_data_source_evidence",
    "G2": "numerical_engine",
    "G3": "experimental_validity",
    "G4": "set_conditioned_population_validity",
    "G5": "champion_lifecycle_and_serving",
    "G6": "feedback_and_monitoring",
    "G7": "durable_storage_and_recovery",
    "G8": "security_and_operations",
}
OFFLINE_GATES = GATE_IDS[:4]
SHADOW_GATES = GATE_IDS[:8]
PRODUCTION_GATES = GATE_IDS
STATUSES = {"PASS", "FAIL", "BLOCKED", "UNKNOWN"}
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


class ReadinessError(ValueError):
    """Raised when a readiness input is malformed or cannot be verified."""


def _reject_constant(value: str):
    raise ReadinessError(f"non-finite JSON constant is forbidden: {value}")


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ReadinessError(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


def _read_json(path: Path) -> tuple[dict[str, Any], bytes]:
    try:
        raw = path.read_bytes()
        value = json.loads(
            raw.decode("utf-8"),
            parse_constant=_reject_constant,
            object_pairs_hook=_unique_object,
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReadinessError(f"cannot read JSON object {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ReadinessError(f"JSON root must be an object: {path}")
    return value, raw


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _hash_json(value: dict[str, Any]) -> str:
    try:
        raw = json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise ReadinessError(f"value is not canonicalizable JSON: {exc}") from exc
    return _sha256(raw)


def _require_mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ReadinessError(f"{name} must be an object")
    return value


def _require_sha(value: Any, name: str, *, nullable: bool = False) -> None:
    if nullable and value is None:
        return
    if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
        raise ReadinessError(f"{name} must be a lowercase 64-character SHA-256")


def _validate_manifest(manifest: dict[str, Any]) -> None:
    required = {
        "schema_version", "release_id", "source_commit", "protected_release_ref",
        "policy_version", "holdout_accessed", "workflow_action_pins", "runtime",
        "data", "model_artifacts", "experiments", "champion", "sampler",
        "feedback", "storage", "security", "activation",
    }
    missing = required.difference(manifest)
    if missing:
        raise ReadinessError(f"release manifest missing fields: {sorted(missing)}")
    if manifest["schema_version"] != "lottery.release-manifest/v1":
        raise ReadinessError("unsupported release manifest schema")
    if not isinstance(manifest["release_id"], str) or not manifest["release_id"]:
        raise ReadinessError("release_id must be a non-empty string")
    if not isinstance(manifest["source_commit"], str) or not GIT_SHA_RE.fullmatch(manifest["source_commit"]):
        raise ReadinessError("source_commit must be a full lowercase Git SHA")
    if not isinstance(manifest["protected_release_ref"], str) or not manifest["protected_release_ref"]:
        raise ReadinessError("protected_release_ref must be non-empty")
    pins = manifest["workflow_action_pins"]
    if not isinstance(pins, list):
        raise ReadinessError("workflow_action_pins must be an array")
    for index, pin in enumerate(pins):
        pin = _require_mapping(pin, f"workflow_action_pins[{index}]")
        if (not isinstance(pin.get("workflow"), str) or not pin["workflow"]
                or not isinstance(pin.get("action"), str) or not pin["action"]
                or not isinstance(pin.get("commit_sha"), str)
                or not GIT_SHA_RE.fullmatch(pin["commit_sha"])):
            raise ReadinessError(f"workflow_action_pins[{index}] is not pinned to a full commit SHA")

    for field in ("runtime", "data", "experiments", "champion", "sampler",
                  "feedback", "storage", "security", "activation"):
        _require_mapping(manifest[field], field)
    if not isinstance(manifest["model_artifacts"], list):
        raise ReadinessError("model_artifacts must be an array")

    runtime = manifest["runtime"]
    if not isinstance(runtime.get("python"), str) or not runtime["python"]:
        raise ReadinessError("runtime.python must be non-empty")
    _require_sha(runtime.get("dependency_lock_sha256"), "runtime.dependency_lock_sha256", nullable=True)

    data = manifest["data"]
    _require_sha(data.get("snapshot_sha256"), "data.snapshot_sha256", nullable=True)
    _require_sha(data.get("evidence_ledger_sha256"), "data.evidence_ledger_sha256", nullable=True)

    experiments = manifest["experiments"]
    _require_sha(experiments.get("registry_sha256"), "experiments.registry_sha256", nullable=True)
    _require_sha(experiments.get("evaluation_manifest_sha256"), "experiments.evaluation_manifest_sha256", nullable=True)

    feedback = manifest["feedback"]
    _require_sha(feedback.get("ledger_sha256"), "feedback.ledger_sha256", nullable=True)
    _require_sha(feedback.get("monitoring_policy_sha256"), "feedback.monitoring_policy_sha256", nullable=True)

    storage = manifest["storage"]
    _require_sha(storage.get("commit_receipt_sha256"), "storage.commit_receipt_sha256", nullable=True)
    _require_sha(storage.get("restore_drill_receipt_sha256"), "storage.restore_drill_receipt_sha256", nullable=True)

    security = manifest["security"]
    for field in ("sbom_sha256", "security_scan_sha256", "provenance_sha256", "rollback_drill_receipt_sha256"):
        _require_sha(security.get(field), f"security.{field}", nullable=True)

    activation = manifest["activation"]
    for field in ("scheduled_collection_enabled", "shadow_only",
                  "user_facing_serving_enabled", "automatic_promotion_enabled"):
        if type(activation.get(field)) is not bool:
            raise ReadinessError(f"activation.{field} must be boolean")


def _verify_evidence(evidence: Any, evidence_root: Path, gate_id: str) -> list[dict[str, str]]:
    if not isinstance(evidence, list):
        raise ReadinessError(f"{gate_id}.evidence must be an array")
    verified = []
    root = evidence_root.resolve()
    for index, item in enumerate(evidence):
        item = _require_mapping(item, f"{gate_id}.evidence[{index}]")
        relative = item.get("path")
        expected = item.get("sha256")
        if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
            raise ReadinessError(f"{gate_id}.evidence[{index}].path must be a relative path")
        _require_sha(expected, f"{gate_id}.evidence[{index}].sha256")
        candidate = (root / relative).resolve()
        if not candidate.is_relative_to(root):
            raise ReadinessError(f"{gate_id}.evidence path escapes evidence root: {relative}")
        if not candidate.is_file():
            raise ReadinessError(f"{gate_id}.evidence file is missing: {relative}")
        actual = _sha256(candidate.read_bytes())
        if actual != expected:
            raise ReadinessError(f"{gate_id}.evidence hash mismatch: {relative}")
        verified.append({"path": relative, "sha256": actual})
    return verified


def _validate_gates(gate_document: dict[str, Any], evidence_root: Path) -> tuple[dict[str, dict], list[dict]]:
    if gate_document.get("schema_version") != "lottery.release-gates/v1":
        raise ReadinessError("unsupported release gate-results schema")
    gates = gate_document.get("gates")
    if not isinstance(gates, list):
        raise ReadinessError("gate-results.gates must be an array")
    by_id: dict[str, dict] = {}
    all_evidence = []
    for index, gate in enumerate(gates):
        gate = _require_mapping(gate, f"gates[{index}]")
        gate_id = gate.get("gate_id")
        if gate_id not in GATE_IDS or gate_id in by_id:
            raise ReadinessError(f"invalid or duplicate gate_id: {gate_id!r}")
        status = gate.get("status")
        if status not in STATUSES:
            raise ReadinessError(f"{gate_id}.status must be one of {sorted(STATUSES)}")
        blockers = gate.get("blockers", [])
        if not isinstance(blockers, list) or any(not isinstance(x, str) or not x for x in blockers):
            raise ReadinessError(f"{gate_id}.blockers must be an array of non-empty strings")
        if status != "PASS" and not blockers:
            raise ReadinessError(f"{gate_id} must explain every non-PASS state with a blocker")
        if status == "PASS" and blockers:
            raise ReadinessError(f"{gate_id} cannot be PASS while blockers remain")
        verified = _verify_evidence(gate.get("evidence", []), evidence_root, gate_id)
        if status == "PASS" and not verified:
            raise ReadinessError(f"{gate_id} cannot PASS without at least one verified evidence file")
        fault_tests = gate.get("fault_tests", [])
        if not isinstance(fault_tests, list):
            raise ReadinessError(f"{gate_id}.fault_tests must be an array")
        for fault_index, fault in enumerate(fault_tests):
            fault = _require_mapping(fault, f"{gate_id}.fault_tests[{fault_index}]")
            if (not isinstance(fault.get("test_id"), str) or not fault["test_id"]
                    or not isinstance(fault.get("expected_state"), str)
                    or not isinstance(fault.get("observed_state"), str)
                    or type(fault.get("passed")) is not bool):
                raise ReadinessError(f"{gate_id}.fault_tests[{fault_index}] has an invalid receipt")
            if status == "PASS" and not fault["passed"]:
                raise ReadinessError(f"{gate_id} cannot PASS with a failed fault-injection receipt")
        by_id[gate_id] = {
            "gate_id": gate_id,
            "name": GATE_NAMES[gate_id],
            "status": status,
            "summary": gate.get("summary", ""),
            "blockers": list(blockers),
            "verified_evidence": verified,
            "fault_tests": fault_tests,
        }
        all_evidence.extend({"gate_id": gate_id, **item} for item in verified)
    missing = set(GATE_IDS).difference(by_id)
    if missing:
        raise ReadinessError(f"gate-results missing required gates: {sorted(missing)}")
    return by_id, all_evidence


def _validate_three_slots(manifest: dict[str, Any]) -> str | None:
    champion = manifest["champion"]
    generation = champion.get("registry_generation")
    slots = champion.get("slots")
    if not isinstance(generation, str) or not generation:
        return "Champion registry generation is missing"
    if not isinstance(slots, list) or len(slots) != 3:
        return "exactly three Champion slots are required; partial 3N service is forbidden"
    artifact_ids = []
    artifact_hashes = []
    for index, slot in enumerate(slots):
        if not isinstance(slot, dict):
            return f"Champion slot {index} is malformed"
        if slot.get("eligible") is not True or slot.get("registry_generation") != generation:
            return f"Champion slot {index} is ineligible or from a mixed registry generation"
        artifact_id = slot.get("artifact_id")
        digest = slot.get("artifact_sha256")
        if not isinstance(artifact_id, str) or not artifact_id:
            return f"Champion slot {index} has no artifact ID"
        if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
            return f"Champion slot {index} has no valid artifact SHA-256"
        artifact_ids.append(artifact_id)
        artifact_hashes.append(digest)
    if len(set(artifact_ids)) != 3 or len(set(artifact_hashes)) != 3:
        return "three slots must reference three distinct immutable artifacts"
    return None


def build_readiness_report(
    release_manifest_path: Path,
    gate_results_path: Path,
    evidence_root: Path,
) -> dict[str, Any]:
    manifest, manifest_raw = _read_json(release_manifest_path)
    gates_doc, gates_raw = _read_json(gate_results_path)
    _validate_manifest(manifest)
    gate_map, evidence = _validate_gates(gates_doc, evidence_root)
    blockers: list[str] = []
    statuses = {gate_id: gate_map[gate_id]["status"] for gate_id in GATE_IDS}

    if manifest.get("holdout_accessed") is not False:
        blockers.append("LOT-042 holdout access is recorded or not explicitly false; all readiness is denied.")

    slot_problem = _validate_three_slots(manifest)
    if statuses["G5"] == "PASS" and slot_problem:
        raise ReadinessError("G5 cannot PASS: " + slot_problem)

    activation = manifest["activation"]
    offline_safe = (
        activation["scheduled_collection_enabled"] is False
        and activation["user_facing_serving_enabled"] is False
        and activation["automatic_promotion_enabled"] is False
    )
    shadow_safe = (
        activation["shadow_only"] is True
        and activation["user_facing_serving_enabled"] is False
        and activation["automatic_promotion_enabled"] is False
    )

    if blockers:
        state = "NOT_READY"
    elif all(statuses[g] == "PASS" for g in OFFLINE_GATES) and offline_safe:
        state = "READY_FOR_OFFLINE_VALIDATION"
        if all(statuses[g] == "PASS" for g in SHADOW_GATES) and shadow_safe:
            state = "READY_FOR_SHADOW"
        if all(statuses[g] == "PASS" for g in PRODUCTION_GATES):
            # V1 deliberately has no production approval/signature verifier.
            # A boolean in a JSON receipt must never authorize production.
            state = "READY_FOR_SHADOW" if shadow_safe else "NOT_READY"
            if state == "NOT_READY":
                blockers.append("Production gates pass, but shadow-only activation boundary is not satisfied.")
    else:
        state = "NOT_READY"

    if state == "NOT_READY" and not blockers:
        for gate_id in GATE_IDS:
            if statuses[gate_id] != "PASS":
                blockers.append(
                    f"{gate_id} ({GATE_NAMES[gate_id]}) is {statuses[gate_id]}: "
                    + "; ".join(gate_map[gate_id]["blockers"])
                )
        if not offline_safe:
            blockers.append("Offline validation requires collection, serving, and automatic promotion disabled.")

    body = {
        "schema_version": "lottery.readiness-report/v1",
        "release_id": manifest["release_id"],
        "policy_version": manifest["policy_version"],
        "release_manifest_sha256": _sha256(manifest_raw),
        "gate_results_sha256": _sha256(gates_raw),
        "readiness_state": state,
        "gate_statuses": statuses,
        "gates": [gate_map[gate_id] for gate_id in GATE_IDS],
        "verified_evidence": evidence,
        "blocking_reasons": blockers,
        "holdout_accessed": manifest["holdout_accessed"],
        "production_approval": "not_implemented_fail_closed",
        "activation_performed": False,
        "serving_enabled_by_report": False,
        "automatic_promotion_enabled_by_report": False,
    }
    return {**body, "report_sha256": _hash_json(body)}


def write_readiness_report(report: dict[str, Any], output_path: Path) -> Path:
    content = (json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        if output_path.read_bytes() != content:
            raise ReadinessError(f"refusing to overwrite immutable readiness report: {output_path}")
        return output_path
    try:
        with output_path.open("xb") as stream:
            stream.write(content)
            stream.flush()
    except FileExistsError:
        if output_path.read_bytes() != content:
            raise ReadinessError(f"immutable readiness report conflicts: {output_path}")
    return output_path


def verify_readiness_report(
    report_path: Path,
    release_manifest_path: Path,
    gate_results_path: Path,
    evidence_root: Path,
) -> dict[str, Any]:
    supplied, _ = _read_json(report_path)
    expected = build_readiness_report(release_manifest_path, gate_results_path, evidence_root)
    if supplied != expected:
        raise ReadinessError("readiness report does not match current release manifest, gates, or evidence")
    return expected
