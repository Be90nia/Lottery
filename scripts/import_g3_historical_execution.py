"""Verify and append-only import the already completed G3 Actions run.

This command does not rerun the evaluator. It fetches authoritative GitHub
Actions metadata, downloads the original workflow artifact, verifies its
transport digest and internal content hashes, then records source timestamps
separately from registry-import timestamps. The imported attempt remains
completed_uncommitted until LOT-065 durable receipts exist.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import io
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen
import zipfile

from lottery.execution_context import _execution_digest, validate_execution_context
from lottery.experiment_registry import ExperimentRegistry
from lottery.subset_model.artifact import canonicalize, verify_artifact
from scripts import run_subset_rolling_origin as runner


API = "https://api.github.com"
REPOSITORY = "Be90nia/Lottery"
REPOSITORY_ID = "1461523125"
WORKFLOW_PATH = ".github/workflows/subset-research.yml"


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _api_json(url: str, token: str) -> dict:
    request = Request(url, headers={
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
    })
    with urlopen(request, timeout=60) as response:
        return json.loads(response.read())


def _download_artifact(url: str, token: str) -> bytes:
    request = Request(url, headers={
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
    })
    opener = build_opener(_NoRedirect)
    try:
        with opener.open(request, timeout=120) as response:
            return response.read()
    except HTTPError as exc:
        if exc.code not in (301, 302, 303, 307, 308):
            raise
        location = exc.headers.get("Location")
        if not location:
            raise ValueError("GitHub artifact download redirect omitted Location")
        # The bearer token is deliberately not forwarded to the blob host.
        with urlopen(location, timeout=120) as response:
            return response.read()


def _digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _verify_archive(evidence: dict, archive_raw: bytes) -> tuple[dict, bytes, bytes]:
    artifact = evidence["artifact"]
    if len(archive_raw) != artifact["size_in_bytes"]:
        raise ValueError("downloaded historical artifact byte length differs from GitHub metadata")
    expected_zip_digest = artifact["digest"].removeprefix("sha256:")
    if _digest(archive_raw) != expected_zip_digest:
        raise ValueError("downloaded historical artifact ZIP digest differs from GitHub metadata")

    with zipfile.ZipFile(io.BytesIO(archive_raw)) as archive:
        members = {}
        for name in archive.namelist():
            if name.endswith("/"):
                continue
            basename = Path(name).name
            if basename in members:
                raise ValueError(f"historical artifact contains duplicate basename: {basename}")
            members[basename] = archive.read(name)

    required = {"run_manifest.json", "target-score-ledger.jsonl", "model-artifacts.jsonl"}
    if not required <= set(members):
        raise ValueError("historical artifact is missing one or more required result files")
    manifest_raw = members["run_manifest.json"]
    manifest_file_evidence = evidence["artifact_contents"]["run_manifest_file"]
    if (_digest(manifest_raw) != manifest_file_evidence["sha256"]
            or len(manifest_raw) != manifest_file_evidence["byte_length"]):
        raise ValueError("historical run manifest file bytes differ from pinned evidence")
    ledger_raw = members["target-score-ledger.jsonl"]
    artifacts_raw = members["model-artifacts.jsonl"]
    content = evidence["artifact_contents"]
    if _digest(ledger_raw) != content["target_score_ledger"]["sha256"]:
        raise ValueError("historical target-score ledger digest mismatch")
    if len(ledger_raw) != content["target_score_ledger"]["byte_length"]:
        raise ValueError("historical target-score ledger byte length mismatch")
    if _digest(artifacts_raw) != content["model_artifacts"]["sha256"]:
        raise ValueError("historical model-artifact ledger digest mismatch")
    if len(artifacts_raw) != content["model_artifacts"]["byte_length"]:
        raise ValueError("historical model-artifact ledger byte length mismatch")

    manifest = json.loads(manifest_raw)
    manifest_body = dict(manifest)
    manifest_self_digest = manifest_body.pop("manifest_sha256", None)
    if manifest_self_digest != "sha256:" + _digest(canonicalize(manifest_body)):
        raise ValueError("historical run manifest self-digest mismatch")
    if manifest_self_digest.removeprefix("sha256:") != content["run_manifest_sha256"]:
        raise ValueError("historical run manifest digest differs from pinned evidence")
    scientific = evidence["scientific_result"]
    target_manifest = manifest.get("target_manifest", {})
    if (manifest.get("status") != scientific["status"]
            or manifest.get("confirmatory_eligible") is not False
            or manifest.get("snapshot", {}).get("sha256") != scientific["snapshot_sha256"]
            or manifest.get("expected_target_record_count") != evidence["artifact_contents"]["target_score_ledger"]["record_count"]
            or manifest.get("actual_target_record_count") != evidence["artifact_contents"]["target_score_ledger"]["record_count"]
            or manifest.get("model_artifact_count") != evidence["artifact_contents"]["model_artifacts"]["record_count"]
            or manifest.get("terminal_status_counts") != scientific["terminal_counts"]
            or target_manifest.get("first_target_draw_id") != scientific["first_target_draw_id"]
            or target_manifest.get("last_target_draw_id") != scientific["last_target_draw_id"]
            or target_manifest.get("target_count_per_zone") != scientific["target_count_per_zone"]):
        raise ValueError("historical run manifest scientific status, snapshot or target denominators differ from evidence")
    declared_outputs = manifest.get("output_files", {})
    if set(declared_outputs) != {"target-score-ledger.jsonl", "model-artifacts.jsonl"}:
        raise ValueError("historical manifest output set differs from the pinned legacy run schema")
    for filename, raw in (
        ("target-score-ledger.jsonl", ledger_raw),
        ("model-artifacts.jsonl", artifacts_raw),
    ):
        declaration = declared_outputs.get(filename)
        if (not isinstance(declaration, dict)
                or declaration.get("sha256") != _digest(raw)
                or declaration.get("bytes") != len(raw)):
            raise ValueError(f"historical manifest output declaration mismatch: {filename}")

    ledger_lines = [line for line in ledger_raw.splitlines() if line]
    artifact_lines = [line for line in artifacts_raw.splitlines() if line]
    if len(ledger_lines) != content["target_score_ledger"]["record_count"]:
        raise ValueError("historical score-ledger record count mismatch")
    if len(artifact_lines) != content["model_artifacts"]["record_count"]:
        raise ValueError("historical model-artifact record count mismatch")

    artifact_ids = set()
    for line in artifact_lines:
        artifact = verify_artifact(line)
        artifact_ids.add(artifact["artifact_id"])
    expected_models = {item["model_name"] for item in manifest.get("models", [])}
    expected_zones = {item["zone"] for item in manifest.get("models", [])}
    if not expected_models or not expected_zones:
        raise ValueError("historical manifest omitted its fixed model/zone family")
    zone_targets = Counter()
    target_model_counts = Counter()
    terminal_counts = Counter()
    seen_rows = set()
    for line in ledger_lines:
        row = json.loads(line)
        record_hash = row.pop("record_sha256", None)
        if record_hash not in (_digest(canonicalize(row)), "sha256:" + _digest(canonicalize(row))):
            raise ValueError("historical score-ledger record hash mismatch")
        zone = row.get("zone")
        target_id = row.get("target_draw_id")
        model_name = row.get("model_name")
        key = (zone, target_id, model_name)
        if key in seen_rows or zone not in expected_zones or model_name not in expected_models:
            raise ValueError("historical score ledger contains duplicate or undeclared model/target rows")
        seen_rows.add(key)
        zone_targets[(zone, target_id)] += 1
        target_model_counts[(zone, target_id)] += 1
        terminal_counts[row["terminal_status"]] += 1
        if (row.get("training_dates_strictly_before_target") is not True
                or not isinstance(row.get("training_last_draw_id"), str)
                or row["training_last_draw_id"] >= target_id
                or type(row.get("training_row_count")) is not int
                or row["training_row_count"] <= 0):
            raise ValueError("historical score ledger contains a non-chronological training cutoff")
        for key_name in ("artifact_id", "diagnostic_ref"):
            artifact_id = row.get(key_name)
            if artifact_id is not None and artifact_id not in artifact_ids:
                raise ValueError(f"historical score ledger {key_name} references an absent model artifact")
    target_count = manifest["target_manifest"]["target_count_per_zone"]
    manifest_terminal_counts = manifest["terminal_status_counts"]
    observed_terminal_counts = {
        status: terminal_counts.get(status, 0) for status in manifest_terminal_counts
    }
    if (set(zone for zone, _ in zone_targets) != expected_zones
            or any(sum(1 for z, _ in zone_targets if z == zone) != target_count for zone in expected_zones)
            or any(count != len(expected_models) for count in target_model_counts.values())
            or sum(terminal_counts.values()) != len(ledger_lines)
            or set(terminal_counts) - set(manifest_terminal_counts)
            or observed_terminal_counts != manifest_terminal_counts):
        raise ValueError("historical score ledger model/zone denominators or terminal counts mismatch")

    return manifest, ledger_raw, artifacts_raw


def _verify_github_sources(evidence: dict, token: str) -> tuple[dict, dict]:
    run_id = evidence["run"]["id"]
    run = _api_json(f"{API}/repos/{REPOSITORY}/actions/runs/{run_id}", token)
    job_payload = _api_json(f"{API}/repos/{REPOSITORY}/actions/runs/{run_id}/jobs?per_page=100", token)
    artifact_payload = _api_json(f"{API}/repos/{REPOSITORY}/actions/runs/{run_id}/artifacts?per_page=100", token)

    expected_run = evidence["run"]
    checks = {
        "id": expected_run["id"],
        "run_attempt": expected_run["run_attempt"],
        "run_number": expected_run["run_number"],
        "workflow_id": expected_run["workflow_id"],
        "name": expected_run["workflow_name"],
        "path": expected_run["workflow_path"],
        "head_branch": expected_run["head_branch"],
        "head_sha": expected_run["head_sha"],
        "event": expected_run["event"],
        "status": expected_run["status"],
        "conclusion": expected_run["conclusion"],
        "run_started_at": expected_run["run_started_at_utc"],
        "html_url": expected_run["run_url"],
    }
    for key, value in checks.items():
        actual = run.get(key)
        # GitHub's workflow-run API may append "@<ref>" to the workflow path.
        if key == "path" and isinstance(actual, str):
            actual = actual.split("@", 1)[0]
        if actual != value:
            raise ValueError(f"live GitHub Actions run metadata mismatch: {key}")
    if str(run.get("repository", {}).get("id")) != REPOSITORY_ID:
        raise ValueError("historical run repository ID differs from the allowlist")
    if run.get("actor", {}).get("login") != expected_run["actor"]:
        raise ValueError("historical run actor differs from the pinned evidence")

    expected_job = evidence["job"]
    jobs = [item for item in job_payload.get("jobs", []) if item.get("id") == expected_job["id"]]
    if len(jobs) != 1:
        raise ValueError("live GitHub Actions API did not return exactly one expected historical job")
    job = jobs[0]
    for key, value in {
        "name": expected_job["name"],
        "status": expected_job["status"],
        "conclusion": expected_job["conclusion"],
        "started_at": expected_job["started_at_utc"],
        "completed_at": expected_job["completed_at_utc"],
        "run_attempt": expected_run["run_attempt"],
        "head_sha": expected_run["head_sha"],
    }.items():
        if job.get(key) != value:
            raise ValueError(f"live GitHub Actions job metadata mismatch: {key}")
    evaluator_steps = [
        step for step in job.get("steps", [])
        if step.get("name") == "Run full frozen 2,649-target exact-subset evaluation"
    ]
    if len(evaluator_steps) != 1:
        raise ValueError("historical job is missing its unique full rolling-origin evaluator step")
    evaluator_step = evaluator_steps[0]
    if (evaluator_step.get("started_at") != expected_job["evaluator_step_started_at_utc"]
            or evaluator_step.get("completed_at") != expected_job["evaluator_step_completed_at_utc"]
            or evaluator_step.get("conclusion") != "success"):
        raise ValueError("historical evaluator step timestamps or conclusion differ from pinned evidence")

    expected_artifact = evidence["artifact"]
    artifacts = [item for item in artifact_payload.get("artifacts", []) if item.get("id") == expected_artifact["id"]]
    if len(artifacts) != 1:
        raise ValueError("live GitHub Actions API did not return exactly one expected artifact")
    artifact = artifacts[0]
    for key, value in {
        "name": expected_artifact["name"],
        "size_in_bytes": expected_artifact["size_in_bytes"],
        "digest": expected_artifact["digest"],
        "created_at": expected_artifact["created_at_utc"],
        "expires_at": expected_artifact["expires_at_utc"],
    }.items():
        if artifact.get(key) != value:
            raise ValueError(f"live GitHub artifact metadata mismatch: {key}")
    if (artifact.get("workflow_run", {}).get("id") != run_id
            or str(artifact.get("workflow_run", {}).get("repository_id")) != REPOSITORY_ID
            or artifact.get("workflow_run", {}).get("head_sha") != expected_run["head_sha"]
            or artifact.get("expired") is True):
        raise ValueError("historical artifact is expired or belongs to a different run/repository/commit")
    return run, artifact


def import_historical_execution(
    *, evidence_path: Path, snapshot_path: Path, registration_path: Path,
    registry_root: Path, token: str,
) -> dict:
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    if evidence.get("schema") != "lottery.github-actions-historical-run-evidence/v1":
        raise ValueError("unsupported historical execution evidence schema")
    run, artifact = _verify_github_sources(evidence, token)
    archive_raw = _download_artifact(artifact["archive_download_url"], token)
    manifest, ledger_raw, artifacts_raw = _verify_archive(evidence, archive_raw)

    rows, snapshot_digest = runner._load_and_validate(snapshot_path)
    spec, config = runner._build_g3_registry_spec(rows, snapshot_digest, registration_path)
    registry = ExperimentRegistry(registry_root)
    registration = registry.register_experiment(spec, actor="github-actions-historical-import")

    expected_run = evidence["run"]
    context = {
        "schema": "lottery.github-actions-execution/v2",
        "repository": REPOSITORY,
        "repository_id": REPOSITORY_ID,
        "workflow_id": expected_run["workflow_id"],
        "workflow_path": WORKFLOW_PATH,
        "workflow_ref": f"{REPOSITORY}/{WORKFLOW_PATH}@{expected_run['ref']}",
        "run_id": expected_run["id"],
        "run_attempt": expected_run["run_attempt"],
        "job": evidence["job"]["name"],
        "event_name": expected_run["event"],
        "ref": expected_run["ref"],
        "sha": expected_run["head_sha"],
        "actor": expected_run["actor"],
        "run_url": expected_run["run_url"],
    }
    context["execution_id"] = _execution_digest(context)
    context = validate_execution_context(
        context, expected_repository=REPOSITORY,
        expected_repository_id=REPOSITORY_ID,
        expected_workflow_id=expected_run["workflow_id"],
        expected_workflow_path=WORKFLOW_PATH,
    )
    if context["execution_id"] != expected_run["execution_id"]:
        raise ValueError("historical execution ID differs from the pinned evidence")

    source_metadata = {
        "source_run_url": expected_run["run_url"],
        "source_started_at_utc": evidence["job"]["evaluator_step_started_at_utc"],
        "source_completed_at_utc": evidence["job"]["evaluator_step_completed_at_utc"],
        "source_artifact_id": artifact["id"],
        "source_artifact_zip_sha256": _digest(archive_raw),
        "source_manifest_sha256": _digest(archive_manifest_raw := _read_manifest_bytes(evidence_path, archive_raw)),
        "source_model_artifacts_sha256": _digest(artifacts_raw),
        "source_evidence_sha256": _digest(evidence_path.read_bytes()),
        "scientific_result_status": manifest["status"],
        "confirmatory_eligible": False,
    }
    source_metadata_sha256 = _digest(canonicalize(source_metadata))
    verification = {
        "schema": "lottery.github-actions-verification/v1",
        "verifier_id": "lottery.github-actions-rest-and-artifact/v1",
        "verified": True,
        "source_metadata_sha256": source_metadata_sha256,
        "artifact_zip_sha256": _digest(archive_raw),
        "source_evidence_sha256": source_metadata["source_evidence_sha256"],
        "verified_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    attempt_id = f"imported-actions-{expected_run['id']}-attempt-{expected_run['run_attempt']}"
    attempt = registry.import_completed_trial(
        experiment_id=registration["experiment_id"],
        attempt_id=attempt_id,
        config=config,
        actor="github-actions-historical-import",
        execution_context=context,
        source_metadata=source_metadata,
        metadata_verifier=lambda _metadata, _context: verification,
        expected_repository=REPOSITORY,
        expected_repository_id=REPOSITORY_ID,
        expected_workflow_id=expected_run["workflow_id"],
        expected_workflow_path=WORKFLOW_PATH,
    )
    receipt = {
        "schema": "lottery.g3-historical-import-receipt/v1",
        "experiment_id": registration["experiment_id"],
        "spec_sha256": registration["spec_sha256"],
        "trial_id": attempt["trial_id"],
        "attempt_id": attempt_id,
        "execution_id": context["execution_id"],
        "source_metadata_sha256": source_metadata_sha256,
        "source_verification_receipt_sha256": _digest(canonicalize(verification)),
        "source_run_url": source_metadata["source_run_url"],
        "source_started_at_utc": source_metadata["source_started_at_utc"],
        "source_completed_at_utc": source_metadata["source_completed_at_utc"],
        "registry_recorded_started_at_utc": attempt["started_at_utc"],
        "registry_recorded_finished_at_utc": attempt["finished_at_utc"],
        "execution_status": "completed",
        "durable_storage_status": "not_committed",
        "scientific_result_status": manifest["status"],
        "confirmatory_eligible": False,
        "artifact_zip_sha256": source_metadata["source_artifact_zip_sha256"],
        "run_manifest_file_sha256": source_metadata["source_manifest_sha256"],
        "model_artifacts_sha256": source_metadata["source_model_artifacts_sha256"],
        "terminal_status": attempt["status"],
    }
    receipt_path = registry.root / "historical-import-receipt.json"
    runner._write_once_bytes(receipt_path, canonicalize(receipt) + b"\n")
    return receipt


def _read_manifest_bytes(evidence_path: Path, archive_raw: bytes) -> bytes:
    with zipfile.ZipFile(io.BytesIO(archive_raw)) as archive:
        matches = [name for name in archive.namelist() if Path(name).name == "run_manifest.json"]
        if len(matches) != 1:
            raise ValueError("historical artifact must contain exactly one run_manifest.json")
        return archive.read(matches[0])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--registration", type=Path, required=True)
    parser.add_argument("--registry-root", type=Path, required=True)
    parser.add_argument("--token-env", default="GITHUB_TOKEN")
    args = parser.parse_args()
    token = os.environ.get(args.token_env) or os.environ.get("GH_TOKEN")
    if not token:
        raise SystemExit("GITHUB_TOKEN (Actions: read) is required for live historical-source verification")
    receipt = import_historical_execution(
        evidence_path=args.evidence,
        snapshot_path=args.snapshot,
        registration_path=args.registration,
        registry_root=args.registry_root,
        token=token,
    )
    print("G3_HISTORICAL_IMPORT=" + json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
