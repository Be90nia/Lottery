"""Fail-closed LOT-067 release-readiness evaluator (offline only)."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from lottery.subset_model.artifact import canonicalize

GATES = tuple(f"G{i}" for i in range(9))
FAULTS = tuple(f"F{i:02d}" for i in range(1, 16))
OFFLINE_GATES = ("G0", "G1", "G2", "G3")
OFFLINE_FAULTS = ("F01", "F03", "F04", "F05")
STATUSES = {"PASS", "FAIL", "BLOCKED", "UNKNOWN"}
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")


class ReadinessError(ValueError):
    """Invalid manifest or evidence; evaluation must stop rather than guess."""


def _pairs_no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ReadinessError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def load_json(path: str | Path) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=_pairs_no_duplicates)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ReadinessError(f"cannot read strict JSON input: {path}") from exc


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _safe_evidence(root: Path, item: Any) -> tuple[bool, str]:
    if not isinstance(item, dict):
        return False, "evidence_entry_not_object"
    rel = item.get("path")
    expected = item.get("sha256")
    if not isinstance(rel, str) or not rel or Path(rel).is_absolute():
        return False, "evidence_path_not_relative"
    if not isinstance(expected, str) or not _SHA256.fullmatch(expected):
        return False, "evidence_sha256_invalid"
    relative = Path(rel)
    if any(part in ("", ".", "..") for part in relative.parts):
        return False, "evidence_path_traversal"
    candidate = root / relative
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            return False, "evidence_symlink_forbidden"
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
        if not resolved.is_file():
            return False, "evidence_not_regular_file"
        actual = _digest(resolved.read_bytes())
    except (OSError, ValueError):
        return False, "evidence_missing_or_outside_root"
    if actual != expected:
        return False, "evidence_sha256_mismatch"
    return True, "verified"


def _validate_manifest(manifest: Any) -> list[str]:
    if not isinstance(manifest, dict) or manifest.get("schema") != "lottery.release-manifest/v1":
        raise ReadinessError("release manifest schema must be lottery.release-manifest/v1")
    for field in ("release_id", "release_ref", "source_commit"):
        if not isinstance(manifest.get(field), str) or not manifest[field]:
            raise ReadinessError(f"manifest {field} must be non-empty")
    if not _GIT_SHA.fullmatch(manifest["source_commit"]):
        raise ReadinessError("source_commit must be a full lowercase Git SHA")
    if manifest["release_ref"] != manifest["source_commit"]:
        raise ReadinessError("release_ref must pin the exact source_commit; mutable refs are forbidden")
    for field in ("workflow_policy_sha256", "dependency_lock_sha256", "snapshot_sha256"):
        if not isinstance(manifest.get(field), str) or not _SHA256.fullmatch(manifest[field]):
            raise ReadinessError(f"manifest {field} must be a lowercase SHA-256")
    if type(manifest.get("lot042_accessed")) is not bool:
        raise ReadinessError("lot042_accessed must be an explicit boolean")
    return []


def _index_records(records: Any, required: tuple[str, ...], label: str) -> dict[str, dict[str, Any]]:
    if not isinstance(records, list):
        raise ReadinessError(f"{label} must be a JSON array")
    indexed: dict[str, dict[str, Any]] = {}
    for record in records:
        if not isinstance(record, dict):
            raise ReadinessError(f"{label} entries must be objects")
        key = record.get("gate_id" if label == "gate_results" else "fault_id")
        if key not in required:
            raise ReadinessError(f"unknown {label} identifier: {key}")
        if key in indexed:
            raise ReadinessError(f"duplicate {label} identifier: {key}")
        indexed[key] = record
    return indexed


def evaluate_readiness(
    manifest: dict[str, Any],
    gate_results: list[dict[str, Any]],
    fault_results: list[dict[str, Any]],
    evidence_root: str | Path,
) -> dict[str, Any]:
    """Verify evidence and derive a readiness state; never emits production-ready."""
    _validate_manifest(manifest)
    root = Path(evidence_root).resolve(strict=True)
    if not root.is_dir():
        raise ReadinessError("evidence_root must be a directory")

    gate_index = _index_records(gate_results, GATES, "gate_results")
    fault_index = _index_records(fault_results, FAULTS, "fault_results")
    verified_evidence: list[dict[str, str]] = []
    blockers: list[str] = []
    gate_states: dict[str, str] = {}

    for gate_id in GATES:
        record = gate_index.get(gate_id)
        if record is None:
            gate_states[gate_id] = "UNKNOWN"
            blockers.append(f"{gate_id}:missing_gate_result")
            continue
        declared = record.get("status")
        if declared not in STATUSES:
            raise ReadinessError(f"{gate_id}: invalid gate status")
        evidence = record.get("evidence", [])
        if not isinstance(evidence, list):
            raise ReadinessError(f"{gate_id}: evidence must be an array")
        valid = True
        for entry in evidence:
            ok, reason = _safe_evidence(root, entry)
            if ok:
                verified_evidence.append({"owner": gate_id, "path": entry["path"], "sha256": entry["sha256"]})
            else:
                valid = False
                blockers.append(f"{gate_id}:{reason}")
        state = declared
        if declared == "PASS" and (not evidence or not valid):
            state = "FAIL"
            if not evidence:
                blockers.append(f"{gate_id}:pass_without_evidence")
        gate_states[gate_id] = state
        if state != "PASS":
            blockers.append(f"{gate_id}:{state.lower()}")

    fault_states: dict[str, str] = {}
    for fault_id in FAULTS:
        record = fault_index.get(fault_id)
        if record is None:
            fault_states[fault_id] = "UNKNOWN"
            continue
        declared = record.get("status")
        if declared not in STATUSES:
            raise ReadinessError(f"{fault_id}: invalid fault status")
        ok, reason = _safe_evidence(root, record.get("evidence"))
        passed = (
            declared == "PASS"
            and record.get("injected") is True
            and isinstance(record.get("expected_state"), str)
            and record.get("expected_state") == record.get("observed_state")
            and ok
        )
        if passed:
            fault_states[fault_id] = "PASS"
            verified_evidence.append({
                "owner": fault_id,
                "path": record["evidence"]["path"],
                "sha256": record["evidence"]["sha256"],
            })
        else:
            fault_states[fault_id] = "FAIL" if declared == "PASS" else declared
            if declared == "PASS":
                blockers.append(f"{fault_id}:{reason if not ok else 'fault_expectation_mismatch'}")

    if manifest["lot042_accessed"] is not False:
        blockers.append("LOT-042:protected_holdout_accessed_or_not_isolated")

    offline_ok = (
        manifest["lot042_accessed"] is False
        and all(gate_states.get(g) == "PASS" for g in OFFLINE_GATES)
        and all(fault_states.get(f) == "PASS" for f in OFFLINE_FAULTS)
    )
    shadow_ok = (
        offline_ok
        and all(gate_states.get(g) == "PASS" for g in GATES)
        and all(fault_states.get(f) == "PASS" for f in FAULTS)
    )
    if shadow_ok:
        readiness = "READY_FOR_SHADOW"
    elif offline_ok:
        readiness = "READY_FOR_OFFLINE_VALIDATION"
    else:
        readiness = "NOT_READY"

    return {
        "schema": "lottery.readiness-report/v1",
        "release_id": manifest["release_id"],
        "source_commit": manifest["source_commit"],
        "release_manifest_sha256": "sha256:" + _digest(canonicalize(manifest)),
        "gate_results_sha256": "sha256:" + _digest(canonicalize(gate_results)),
        "fault_results_sha256": "sha256:" + _digest(canonicalize(fault_results)),
        "readiness": readiness,
        "production_ready": False,
        "production_blocker": "v1 has no protected cryptographic production-approval verifier",
        "gate_states": gate_states,
        "fault_states": fault_states,
        "verified_evidence_count": len(verified_evidence),
        "verified_evidence": verified_evidence,
        "blockers": sorted(set(blockers)),
        "lot042_accessed": manifest["lot042_accessed"],
    }


def write_readiness_report(report: dict[str, Any], output: str | Path) -> None:
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = canonicalize(report) + b"\n"
    temporary = path.with_name(f".{path.name}.tmp")
    if path.exists():
        raise ReadinessError("readiness report output already exists; immutable no-clobber required")
    with temporary.open("xb") as handle:
        handle.write(raw)
        handle.flush()
        import os
        os.fsync(handle.fileno())
    try:
        os.link(temporary, path)
    except FileExistsError as exc:
        raise ReadinessError("readiness report output collision") from exc
    finally:
        temporary.unlink(missing_ok=True)
