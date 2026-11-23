"""Typed, offline readiness receipt verification for LOT-074.

This verifies receipt integrity and contract binding. It does not authenticate
who produced a receipt; SHA-256 is integrity, not source authenticity.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from lottery.subset_model.artifact import canonicalize

GATE_TYPES = {
    "G0": "source-build-integrity",
    "G1": "canonical-data-source-evidence",
    "G2": "numerical-engine",
    "G3": "experimental-validity",
    "G4": "population-regime-validity",
    "G5": "champion-lifecycle-serving",
    "G6": "feedback-monitoring",
    "G7": "durable-storage-recovery",
    "G8": "security-operations",
}
FAULTS = tuple(f"F{i:02d}" for i in range(1, 16))
GATE_REQUIRED_CHECKS = {
    "G0": ("source_commit", "workflow_action_pins", "dependency_lock", "runtime_toolchain", "sbom", "security_scan"),
    "G1": ("canonical_snapshot", "raw_source_bytes", "source_authority", "parser_lineage", "outcome_validation", "coverage"),
    "G2": ("full_support", "normalization", "exact_subset_probability", "conditional_poisson", "deterministic_sampler", "numerical_stability"),
    "G3": ("preregistration", "chronological_targets", "complete_denominator", "baseline_comparison", "multiplicity_control", "calibration"),
    "G4": ("row_level_labels", "regime_adjudication", "minimum_history", "same_target_comparison", "no_cross_regime_merge"),
    "G5": ("three_slot_registry", "single_registry_generation", "front_back_pairing", "immutable_artifacts", "sampler_cardinality", "no_fit_on_request"),
    "G6": ("frozen_forecast", "official_outcome_validation", "append_only_corrections", "statistical_unit", "monitoring_thresholds"),
    "G7": ("conditional_create", "readback_hash", "fencing_tokens", "immutable_registry", "independent_backup", "restore_drill", "measured_rpo_rto"),
    "G8": ("least_privilege", "secret_scan", "incident_response", "artifact_integrity", "rollback_drill", "operational_monitoring"),
}
SHA256 = re.compile(r"^[0-9a-f]{64}$")
GIT_SHA = re.compile(r"^[0-9a-f]{40}$")


class ReceiptVerificationError(ValueError):
    """A readiness receipt is malformed, mismatched, or unverifiable."""


def _strict_json(raw: bytes, label: str) -> dict[str, Any]:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise ReceiptVerificationError(f"{label}: duplicate JSON key {key}")
            result[key] = value
        return result

    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ReceiptVerificationError(f"{label}: invalid strict JSON") from exc
    if not isinstance(value, dict):
        raise ReceiptVerificationError(f"{label}: receipt must be an object")
    return value


def _safe_file(root: Path, reference: Any, label: str) -> tuple[bytes, str]:
    if not isinstance(reference, dict) or set(reference) != {"path", "sha256"}:
        raise ReceiptVerificationError(f"{label}: file reference shape invalid")
    path, expected = reference["path"], reference["sha256"]
    if (
        not isinstance(path, str) or not path or "\\" in path or ":" in path
        or not isinstance(expected, str) or not SHA256.fullmatch(expected)
    ):
        raise ReceiptVerificationError(f"{label}: invalid path or digest")
    relative = PurePosixPath(path)
    if relative.is_absolute() or relative.as_posix() != path or any(
        part in ("", ".", "..") for part in relative.parts
    ):
        raise ReceiptVerificationError(f"{label}: non-canonical or traversal path")
    candidate = root.joinpath(*relative.parts)
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ReceiptVerificationError(f"{label}: symlink forbidden")
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
        if not resolved.is_file():
            raise OSError("not a regular file")
        raw = resolved.read_bytes()
    except (OSError, ValueError) as exc:
        raise ReceiptVerificationError(f"{label}: file missing or outside evidence root") from exc
    actual = hashlib.sha256(raw).hexdigest()
    if actual != expected:
        raise ReceiptVerificationError(f"{label}: SHA-256 mismatch")
    return raw, actual


def _utc_timestamp(value: Any, label: str) -> None:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ReceiptVerificationError(f"{label}: timestamp must be UTC RFC3339 with Z")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ReceiptVerificationError(f"{label}: invalid timestamp") from exc
    if parsed.tzinfo != timezone.utc:
        raise ReceiptVerificationError(f"{label}: timestamp must be UTC")


def _verify_g2_evidence(check_id: str, raw: bytes) -> None:
    """Validate numerical-engine evidence values, not merely their file hashes."""
    report = _strict_json(raw, "G2 " + check_id)
    zones = {"front": (35, 5, 324632), "back": (12, 2, 66)}

    def finite_number(value: Any) -> bool:
        return type(value) in (int, float) and math.isfinite(value)

    def require(condition: bool, message: str) -> None:
        if not condition:
            raise ReceiptVerificationError("G2 " + check_id + ": " + message)

    if check_id in ("full_support", "normalization", "exact_subset_probability"):
        require(set(report) == {"schema", "zones"}, "report fields invalid")
        expected_schema = {
            "full_support": "lottery.g2-full-support/v1",
            "normalization": "lottery.g2-normalization/v1",
            "exact_subset_probability": "lottery.g2-exact-probability/v1",
        }[check_id]
        require(report["schema"] == expected_schema, "unsupported evidence schema")
        entries = report["zones"]
        require(isinstance(entries, list) and len(entries) == 2, "must contain front and back zones")
        indexed = {entry.get("zone"): entry for entry in entries if isinstance(entry, dict)}
        require(set(indexed) == set(zones), "front/back zone inventory mismatch")
        for zone, (m, k, support_count) in zones.items():
            entry = indexed[zone]
            if check_id == "full_support":
                require(
                    set(entry) == {"zone", "population_size", "selection_size", "expected_support_count", "enumerated_support_count"}
                    and entry["population_size"] == m and entry["selection_size"] == k
                    and entry["expected_support_count"] == support_count
                    and entry["enumerated_support_count"] == support_count,
                    f"{zone} support coverage is not exact",
                )
            else:
                expected_fields = (
                    {"zone", "probability_sum", "minimum_probability", "max_abs_error"}
                    if check_id == "normalization"
                    else {"zone", "enumerated_subset_count", "probability_sum", "minimum_probability", "max_abs_oracle_error"}
                )
                require(set(entry) == expected_fields, f"{zone} numerical fields invalid")
                count_field = "enumerated_subset_count"
                if check_id == "exact_subset_probability":
                    require(entry[count_field] == support_count, f"{zone} probability oracle did not cover full support")
                error_field = "max_abs_error" if check_id == "normalization" else "max_abs_oracle_error"
                require(
                    finite_number(entry["probability_sum"])
                    and abs(entry["probability_sum"] - 1.0) <= 1e-12
                    and finite_number(entry["minimum_probability"])
                    and entry["minimum_probability"] >= 0.0
                    and finite_number(entry[error_field])
                    and entry[error_field] <= 1e-12,
                    f"{zone} probabilities are not normalized/nonnegative within 1e-12",
                )
        return

    contracts = {
        "conditional_poisson": (
            {"schema", "algorithm", "oracle_cases", "max_abs_probability_error", "max_abs_marginal_error", "all_finite"},
            "lottery.g2-conditional-poisson/v1", "log_elementary_symmetric_dp",
        ),
        "deterministic_sampler": (
            {"schema", "algorithm", "seed", "samples_per_zone", "replay_identical", "invalid_sample_count"},
            "lottery.g2-deterministic-sampler/v1", "backward_dp",
        ),
        "numerical_stability": (
            {"schema", "stress_cases", "non_finite_count", "max_abs_normalization_error", "minimum_probability"},
            "lottery.g2-numerical-stability/v1", None,
        ),
    }
    fields, schema, algorithm = contracts[check_id]
    require(set(report) == fields and report["schema"] == schema, "report schema/fields invalid")
    if check_id == "conditional_poisson":
        require(
            report["algorithm"] == algorithm and type(report["oracle_cases"]) is int
            and report["oracle_cases"] >= 100
            and finite_number(report["max_abs_probability_error"])
            and report["max_abs_probability_error"] <= 1e-12
            and finite_number(report["max_abs_marginal_error"])
            and report["max_abs_marginal_error"] <= 1e-12
            and report["all_finite"] is True,
            "conditional-Poisson oracle checks failed",
        )
    elif check_id == "deterministic_sampler":
        require(
            report["algorithm"] == algorithm and type(report["seed"]) is int
            and report["seed"] >= 0
            and type(report["samples_per_zone"]) is int and report["samples_per_zone"] >= 1000
            and report["replay_identical"] is True
            and report["invalid_sample_count"] == 0,
            "deterministic sampler replay/support checks failed",
        )
    else:
        require(
            type(report["stress_cases"]) is int and report["stress_cases"] >= 100
            and report["non_finite_count"] == 0
            and finite_number(report["max_abs_normalization_error"])
            and report["max_abs_normalization_error"] <= 1e-10
            and finite_number(report["minimum_probability"])
            and report["minimum_probability"] >= 0.0,
            "numerical stability stress checks failed",
        )


def _checks_pass(checks: Any, label: str, root: Path) -> list[dict[str, str]]:
    required = GATE_REQUIRED_CHECKS[label]
    if not isinstance(checks, list):
        raise ReceiptVerificationError(f"{label}: checks must be an array")
    indexed: dict[str, dict[str, Any]] = {}
    for check in checks:
        if not isinstance(check, dict) or set(check) != {"check_id", "status", "evidence"}:
            raise ReceiptVerificationError(f"{label}: check shape invalid")
        check_id = check["check_id"]
        if not isinstance(check_id, str) or check_id in indexed:
            raise ReceiptVerificationError(f"{label}: check ID missing or duplicated")
        indexed[check_id] = check
    if set(indexed) != set(required):
        raise ReceiptVerificationError(f"{label}: required check inventory mismatch")
    verified: list[dict[str, str]] = []
    seen_paths: set[str] = set()
    for check_id in required:
        check = indexed[check_id]
        if check["status"] != "PASS":
            raise ReceiptVerificationError(f"{label}: check {check_id} did not pass")
        evidence_raw, digest = _safe_file(root, check["evidence"], label + " " + check_id)
        if label == "G2":
            _verify_g2_evidence(check_id, evidence_raw)
        path = check["evidence"]["path"]
        if path in seen_paths:
            raise ReceiptVerificationError(f"{label}: check evidence must be unique")
        seen_paths.add(path)
        verified.append({"path": path, "sha256": digest})
    return verified


def verify_gate_receipt(
    manifest: dict[str, Any], gate_result: dict[str, Any], evidence_root: str | Path,
) -> dict[str, Any]:
    """Verify one gate's typed receipt; gate status is derived, never caller-supplied."""
    if not isinstance(gate_result, dict):
        raise ReceiptVerificationError("gate result must be an object")
    gate_id = gate_result.get("gate_id")
    if not isinstance(gate_id, str) or gate_id not in GATE_TYPES or set(gate_result) != {"gate_id", "receipt"}:
        raise ReceiptVerificationError("gate result must contain only gate_id and receipt")
    root = Path(evidence_root).resolve(strict=True)
    raw, digest = _safe_file(root, gate_result["receipt"], gate_id)
    receipt = _strict_json(raw, gate_id)
    required = {
        "schema", "receipt_type", "gate_id", "release_id", "source_commit",
        "release_manifest_sha256", "result", "checks", "generated_at_utc",
    }
    if set(receipt) != required:
        raise ReceiptVerificationError(f"{gate_id}: gate receipt fields invalid")
    expected_manifest = "sha256:" + hashlib.sha256(canonicalize(manifest)).hexdigest()
    if (
        receipt["schema"] != "lottery.gate-receipt/v1"
        or receipt["receipt_type"] != GATE_TYPES[gate_id]
        or receipt["gate_id"] != gate_id
        or receipt["release_id"] != manifest.get("release_id")
        or receipt["source_commit"] != manifest.get("source_commit")
        or receipt["release_manifest_sha256"] != expected_manifest
        or receipt["result"] != "PASS"
    ):
        raise ReceiptVerificationError(f"{gate_id}: receipt does not bind this release and gate")
    if not GIT_SHA.fullmatch(str(receipt["source_commit"])):
        raise ReceiptVerificationError(f"{gate_id}: source commit must be full Git SHA")
    check_evidence = _checks_pass(receipt["checks"], gate_id, root)
    _utc_timestamp(receipt["generated_at_utc"], gate_id)
    return {
        "gate_id": gate_id, "receipt_sha256": digest, "status": "PASS",
        "check_evidence": check_evidence,
    }


def verify_fault_receipt(
    manifest: dict[str, Any], fault_result: dict[str, Any], evidence_root: str | Path,
) -> dict[str, str]:
    """Verify a fault-specific recovery receipt, including no partial output."""
    if not isinstance(fault_result, dict):
        raise ReceiptVerificationError("fault result must be an object")
    fault_id = fault_result.get("fault_id")
    if not isinstance(fault_id, str) or fault_id not in FAULTS or set(fault_result) != {"fault_id", "receipt"}:
        raise ReceiptVerificationError("fault result must contain only fault_id and receipt")
    root = Path(evidence_root).resolve(strict=True)
    raw, digest = _safe_file(root, fault_result["receipt"], fault_id)
    receipt = _strict_json(raw, fault_id)
    required = {
        "schema", "fault_id", "release_id", "source_commit",
        "release_manifest_sha256", "injection_method", "expected_state",
        "observed_state", "recovery_action", "output_publication",
        "runner_commit", "evidence", "generated_at_utc",
    }
    if set(receipt) != required:
        raise ReceiptVerificationError(f"{fault_id}: fault receipt fields invalid")
    expected_manifest = "sha256:" + hashlib.sha256(canonicalize(manifest)).hexdigest()
    if (
        receipt["schema"] != "lottery.fault-receipt/v1"
        or receipt["fault_id"] != fault_id
        or receipt["release_id"] != manifest.get("release_id")
        or receipt["source_commit"] != manifest.get("source_commit")
        or receipt["release_manifest_sha256"] != expected_manifest
        or not isinstance(receipt["injection_method"], str) or not receipt["injection_method"].strip()
        or not isinstance(receipt["expected_state"], str) or not receipt["expected_state"].strip()
        or receipt["observed_state"] != receipt["expected_state"]
        or not isinstance(receipt["recovery_action"], str) or not receipt["recovery_action"].strip()
        or receipt["output_publication"] != "none"
        or not isinstance(receipt["runner_commit"], str)
        or not GIT_SHA.fullmatch(receipt["runner_commit"])
    ):
        raise ReceiptVerificationError(f"{fault_id}: fault receipt contract mismatch")
    _utc_timestamp(receipt["generated_at_utc"], fault_id)
    evidence_raw, evidence_digest = _safe_file(root, receipt["evidence"], fault_id + " evidence")
    if not evidence_raw:
        raise ReceiptVerificationError(f"{fault_id}: fault evidence must not be empty")
    return {
        "fault_id": fault_id, "receipt_sha256": digest,
        "evidence_sha256": evidence_digest, "status": "PASS",
    }


V2_SCALAR_REFS = (
    "workflow_policy", "dependency_lock", "readiness_policy", "canonical_snapshot",
    "source_evidence_ledger", "runtime_toolchain", "sbom", "security_scan",
    "experiment_registration", "champion_registry_snapshot", "sampler_rng",
    "storage_commit_receipts", "backup_generation", "independent_restore_receipt",
)


def verify_release_manifest_v2(
    manifest: dict[str, Any], evidence_root: str | Path,
) -> dict[str, Any]:
    """Verify every immutable release-tuple reference against its actual bytes."""
    if not isinstance(manifest, dict) or set(manifest) != {
        "schema", "release_id", "release_ref", "source_commit", "lot042_accessed", "evidence",
    }:
        raise ReceiptVerificationError("v2 release manifest has missing or unknown fields")
    if manifest["schema"] != "lottery.release-manifest/v2":
        raise ReceiptVerificationError("unsupported v2 release manifest schema")
    if (
        not isinstance(manifest["release_id"], str) or not manifest["release_id"]
        or not isinstance(manifest["source_commit"], str)
        or not GIT_SHA.fullmatch(manifest["source_commit"])
        or manifest["release_ref"] != manifest["source_commit"]
        or type(manifest["lot042_accessed"]) is not bool
    ):
        raise ReceiptVerificationError("v2 release identity, immutable ref or LOT-042 flag invalid")
    evidence = manifest["evidence"]
    required = set(V2_SCALAR_REFS) | {"evaluation_manifests", "model_artifacts"}
    if not isinstance(evidence, dict) or set(evidence) != required:
        raise ReceiptVerificationError("v2 release evidence inventory has missing or unknown refs")
    root = Path(evidence_root).resolve(strict=True)
    references: list[tuple[str, Any]] = [(key, evidence[key]) for key in V2_SCALAR_REFS]
    for collection in ("evaluation_manifests", "model_artifacts"):
        values = evidence[collection]
        if not isinstance(values, list) or not values:
            raise ReceiptVerificationError(f"v2 {collection} must be a non-empty array")
        references.extend((f"{collection}[{i}]", item) for i, item in enumerate(values))
    verified: list[dict[str, str]] = []
    seen_paths: set[str] = set()
    for label, reference in references:
        _, digest = _safe_file(root, reference, "manifest " + label)
        path = reference["path"]
        if path in seen_paths:
            raise ReceiptVerificationError("v2 manifest evidence paths must be unique")
        seen_paths.add(path)
        verified.append({"name": label, "path": path, "sha256": digest})
    return {
        "release_manifest_sha256": "sha256:" + hashlib.sha256(canonicalize(manifest)).hexdigest(),
        "verified_evidence": verified,
    }


def verify_receipt_set(
    manifest: dict[str, Any],
    gate_results: list[dict[str, Any]],
    fault_results: list[dict[str, Any]],
    evidence_root: str | Path,
) -> dict[str, Any]:
    """Verify complete, non-reused typed receipt inventory and derive readiness."""
    if not isinstance(manifest, dict):
        raise ReceiptVerificationError("release manifest must be an object")
    manifest_evidence: list[dict[str, str]] = []
    if manifest.get("schema") == "lottery.release-manifest/v2":
        manifest_evidence = verify_release_manifest_v2(manifest, evidence_root)["verified_evidence"]
    elif manifest.get("schema") == "lottery.release-manifest/v1":
        if (
            not isinstance(manifest.get("release_id"), str) or not manifest["release_id"]
            or not isinstance(manifest.get("source_commit"), str)
            or not GIT_SHA.fullmatch(manifest["source_commit"])
            or manifest.get("release_ref") != manifest.get("source_commit")
        ):
            raise ReceiptVerificationError("manifest release identity/ref is invalid or mutable")
        for field in ("workflow_policy_sha256", "dependency_lock_sha256", "readiness_policy_sha256", "snapshot_sha256"):
            if not isinstance(manifest.get(field), str) or not SHA256.fullmatch(manifest[field]):
                raise ReceiptVerificationError(f"manifest {field} must be a lowercase SHA-256")
        if type(manifest.get("lot042_accessed")) is not bool:
            raise ReceiptVerificationError("manifest LOT-042 isolation must be explicit")
    else:
        raise ReceiptVerificationError("unsupported release manifest schema")
    if not isinstance(gate_results, list) or not isinstance(fault_results, list):
        raise ReceiptVerificationError("gate and fault receipt inventories must be arrays")
    if any(not isinstance(item, dict) or not isinstance(item.get("gate_id"), str) for item in gate_results):
        raise ReceiptVerificationError("gate receipt inventory contains a malformed entry")
    if any(not isinstance(item, dict) or not isinstance(item.get("fault_id"), str) for item in fault_results):
        raise ReceiptVerificationError("fault receipt inventory contains a malformed entry")
    gates = {item["gate_id"]: item for item in gate_results}
    faults = {item["fault_id"]: item for item in fault_results}
    if len(gates) != len(gate_results) or set(gates) != set(GATE_TYPES):
        raise ReceiptVerificationError("gate receipt inventory must contain each G0-G8 exactly once")
    if len(faults) != len(fault_results) or set(faults) != set(FAULTS):
        raise ReceiptVerificationError("fault receipt inventory must contain each F01-F15 exactly once")
    verified_gates = [
        verify_gate_receipt(manifest, gates[key], evidence_root) for key in GATE_TYPES
    ]
    verified_faults = [
        verify_fault_receipt(manifest, faults[key], evidence_root) for key in FAULTS
    ]
    identities = [item["receipt_sha256"] for item in verified_gates + verified_faults]
    paths = [gates[key]["receipt"]["path"] for key in GATE_TYPES]
    paths += [faults[key]["receipt"]["path"] for key in FAULTS]
    evidence_records = [
        entry
        for gate in verified_gates for entry in gate["check_evidence"]
    ]
    evidence_records += manifest_evidence
    for key in FAULTS:
        fault_raw, _ = _safe_file(
            Path(evidence_root).resolve(strict=True), faults[key]["receipt"], key
        )
        fault_receipt = _strict_json(fault_raw, key)
        evidence_records.append({
            "path": fault_receipt["evidence"]["path"],
            "sha256": fault_receipt["evidence"]["sha256"],
        })
    evidence_paths = [entry["path"] for entry in evidence_records]
    evidence_digests = [entry["sha256"] for entry in evidence_records]
    if (
        len(set(identities)) != len(identities)
        or len(set(paths)) != len(paths)
        or len(set(evidence_paths)) != len(evidence_paths)
        or len(set(evidence_digests)) != len(evidence_digests)
        or set(evidence_paths) & set(paths)
    ):
        raise ReceiptVerificationError("receipt and evidence files/digests must be unique per gate and fault")
    return {
        "schema": "lottery.readiness-receipt-verification/v1",
        "release_id": manifest["release_id"],
        "release_manifest_sha256": "sha256:" + hashlib.sha256(canonicalize(manifest)).hexdigest(),
        "readiness": "NOT_READY",
        "receipt_completeness": (
            "COMPLETE" if manifest["lot042_accessed"] is False else "BLOCKED_LOT042"
        ),
        "shadow_authorized": False,
        "production_ready": False,
        "release_manifest_evidence": manifest_evidence,
        "gate_receipts": verified_gates,
        "fault_receipts": verified_faults,
        "lot042_accessed": manifest["lot042_accessed"],
        "authenticity_note": "SHA-256 verifies integrity only; receipt producer authenticity and official-source authority are not established by this offline verifier.",
    }

