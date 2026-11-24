"""Read-only reconciliation of LOT-064 execution events against GitHub Actions."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

from lottery.experiment_registry import ExperimentRegistry
from lottery.subset_model.artifact import canonicalize

API = "https://api.github.com"


def _api_json(url: str, token: str) -> dict[str, Any]:
    request = Request(url, headers={
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
    })
    with urlopen(request, timeout=60) as response:
        value = json.loads(response.read())
    if not isinstance(value, dict):
        raise ValueError(f"GitHub API returned a non-object response: {url}")
    return value


def _paged_items(url: str, key: str, token: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    page = 1
    while True:
        payload = _api_json(f"{url}{'&' if '?' in url else '?'}per_page=100&page={page}", token)
        batch = payload.get(key, [])
        if not isinstance(batch, list):
            raise ValueError(f"GitHub API {key} field is not a list")
        items.extend(item for item in batch if isinstance(item, dict))
        total = payload.get("total_count")
        if len(batch) < 100 or (isinstance(total, int) and len(items) >= total):
            return items
        page += 1


def _finding(code: str, severity: str, **details: Any) -> dict[str, Any]:
    return {"code": code, "severity": severity, **details}


def _normalise_workflow_path(value: Any) -> Any:
    # GitHub's workflow-run API may append "@<ref>" to the workflow path.
    return value.split("@", 1)[0] if isinstance(value, str) else value


def reconcile(
    *, registry_root: Path, token: str, repository: str,
    repository_id: str, workflow_id: int, workflow_path: str,
) -> dict[str, Any]:
    """Compare the append-only local registry with authoritative Actions metadata."""
    registry = ExperimentRegistry(registry_root)
    snapshot = registry.snapshot()
    attempts_by_run: dict[int, list[dict[str, Any]]] = {}
    attempts_by_execution: dict[str, list[dict[str, Any]]] = {}
    for experiment_id, experiment in snapshot["experiments"].items():
        experiment_class = experiment["registration"]["spec"]["experiment_class"]
        for attempt in experiment["attempts"].values():
            context = attempt.get("execution_context")
            if not isinstance(context, dict) or type(context.get("run_id")) is not int:
                continue
            binding = {
                "experiment_id": experiment_id,
                "experiment_class": experiment_class,
                "attempt": attempt,
            }
            attempts_by_run.setdefault(context["run_id"], []).append(binding)
            execution_id = context.get("execution_id")
            if isinstance(execution_id, str):
                attempts_by_execution.setdefault(execution_id, []).append(binding)

    findings: list[dict[str, Any]] = []
    checked_runs: set[int] = set()
    for run_id, bindings in sorted(attempts_by_run.items()):
        checked_runs.add(run_id)
        by_attempt: dict[int, list[dict[str, Any]]] = {}
        for binding in bindings:
            number = binding["attempt"]["execution_context"].get("run_attempt")
            if type(number) is int:
                by_attempt.setdefault(number, []).append(binding)

        for number, attempt_bindings in sorted(by_attempt.items()):
            # The run-level endpoint returns the latest rerun. Compare each
            # immutable registry attempt with the matching Actions attempt.
            run = _api_json(
                f"{API}/repos/{repository}/actions/runs/{run_id}/attempts/{number}",
                token,
            )
            context = attempt_bindings[0]["attempt"]["execution_context"]
            expected = {
                "id": run_id,
                "run_attempt": number,
                "workflow_id": workflow_id,
                "path": workflow_path,
                "head_sha": context.get("sha"),
                "event": context.get("event_name"),
                "ref": context.get("ref"),
            }
            actual = {key: run.get(key) for key in expected}
            actual["path"] = _normalise_workflow_path(actual.get("path"))
            if str(run.get("repository", {}).get("id")) != repository_id:
                findings.append(_finding(
                    "repository_identity_mismatch", "error", run_id=run_id,
                    run_attempt=number, expected_repository_id=repository_id,
                    actual_repository_id=str(run.get("repository", {}).get("id")),
                ))
            mismatches = {
                key: {"expected": value, "actual": actual.get(key)}
                for key, value in expected.items() if actual.get(key) != value
            }
            if mismatches:
                findings.append(_finding(
                    "workflow_metadata_mismatch", "error", run_id=run_id,
                    run_attempt=number, mismatches=mismatches,
                ))

            for binding in attempt_bindings:
                attempt = binding["attempt"]
                status = attempt["status"]
                if status == "running" and run.get("status") == "completed":
                    findings.append(_finding(
                        "workflow_terminal_registry_running", "error",
                        run_id=run_id, run_attempt=number,
                        attempt_id=attempt["attempt_id"],
                        workflow_conclusion=run.get("conclusion"),
                    ))
                elif status != "running" and run.get("status") != "completed":
                    findings.append(_finding(
                        "registry_terminal_before_workflow_terminal", "error",
                        run_id=run_id, run_attempt=number,
                        attempt_id=attempt["attempt_id"],
                        registry_status=status, workflow_status=run.get("status"),
                    ))
                elif status in ("succeeded", "completed_uncommitted") and (
                    run.get("status") != "completed" or run.get("conclusion") != "success"
                ):
                    findings.append(_finding(
                        "registry_success_without_successful_workflow", "error",
                        run_id=run_id, run_attempt=number,
                        attempt_id=attempt["attempt_id"],
                        registry_status=status, workflow_status=run.get("status"),
                        workflow_conclusion=run.get("conclusion"),
                    ))

                source_artifact_id = attempt.get("source_artifact_id")
                if source_artifact_id is not None:
                    artifacts = _paged_items(
                        f"{API}/repos/{repository}/actions/runs/{run_id}/artifacts",
                        "artifacts", token,
                    )
                    matches = [item for item in artifacts if item.get("id") == source_artifact_id]
                    if len(matches) != 1:
                        findings.append(_finding(
                            "imported_source_artifact_missing_or_ambiguous", "error",
                            run_id=run_id, run_attempt=number,
                            attempt_id=attempt["attempt_id"],
                            source_artifact_id=source_artifact_id,
                        ))
                    else:
                        artifact = matches[0]
                        expected_digest = attempt.get("source_artifact_zip_sha256")
                        actual_digest = str(artifact.get("digest", "")).removeprefix("sha256:")
                        if (artifact.get("expired") is True
                                or actual_digest != expected_digest
                                or artifact.get("workflow_run", {}).get("id") != run_id
                                or str(artifact.get("workflow_run", {}).get("repository_id")) != repository_id
                                or artifact.get("workflow_run", {}).get("head_sha") != context.get("sha")):
                            findings.append(_finding(
                                "imported_source_artifact_mismatch", "error",
                                run_id=run_id, run_attempt=number,
                                attempt_id=attempt["attempt_id"],
                                source_artifact_id=source_artifact_id,
                                expired=artifact.get("expired"),
                                expected_digest=expected_digest,
                                actual_digest=actual_digest,
                            ))
                if status == "completed_uncommitted":
                    findings.append(_finding(
                        "historical_execution_not_durably_committed", "warning",
                        run_id=run_id, run_attempt=number,
                        attempt_id=attempt["attempt_id"],
                        experiment_id=binding["experiment_id"],
                    ))

    runs_url = f"{API}/repos/{repository}/actions/workflows/{workflow_id}/runs"
    workflow_runs = _paged_items(runs_url, "workflow_runs", token)
    for run in workflow_runs:
        run_id = run.get("id")
        if type(run_id) is not int or run_id in checked_runs:
            continue
        if _normalise_workflow_path(run.get("path")) not in (None, workflow_path):
            continue
        findings.append(_finding(
            "workflow_run_without_registry_binding", "warning",
            run_id=run_id, run_attempt=run.get("run_attempt"),
            status=run.get("status"), conclusion=run.get("conclusion"),
            head_sha=run.get("head_sha"), html_url=run.get("html_url"),
        ))

    # Detect a crash after LOT-065 commits but before the registry terminal event.
    # Verification is read-only: no event or storage object is repaired here.
    receipt_root = registry_root / "storage-receipts"
    if receipt_root.exists():
        for receipt_path in sorted(receipt_root.glob("*.json")):
            execution_id = receipt_path.stem
            bindings = attempts_by_execution.get(execution_id, [])
            if len(bindings) != 1:
                findings.append(_finding(
                    "storage_bundle_without_unique_registry_attempt", "error",
                    execution_id=execution_id, matching_attempt_count=len(bindings),
                ))
                continue
            binding = bindings[0]
            attempt = binding["attempt"]
            try:
                bundle_raw = receipt_path.read_bytes()
                bundle = json.loads(bundle_raw)
                if not isinstance(bundle, dict) or canonicalize(bundle) != bundle_raw:
                    raise ValueError("receipt bundle is not canonical JSON")
                manifest_entry = bundle["run_manifest.json"]
                artifact_entry = bundle["model-artifacts.jsonl"]
                registry._verify_execution_storage_receipts(
                    execution_id=execution_id,
                    expected_producer_commit=attempt["execution_context"]["sha"],
                    result_sha256=manifest_entry["content_sha256"],
                    artifact_sha256=artifact_entry["content_sha256"],
                    expected_receipts_sha256=hashlib.sha256(bundle_raw).hexdigest(),
                )
            except Exception as exc:
                findings.append(_finding(
                    "storage_bundle_invalid", "error",
                    execution_id=execution_id, attempt_id=attempt["attempt_id"],
                    reason=f"{type(exc).__name__}: {exc}",
                ))
                continue
            if attempt["status"] != "succeeded":
                findings.append(_finding(
                    "storage_bundle_valid_but_terminal_missing", "error",
                    execution_id=execution_id, run_id=attempt["execution_context"]["run_id"],
                    attempt_id=attempt["attempt_id"], registry_status=attempt["status"],
                    experiment_id=binding["experiment_id"],
                ))

    findings.sort(key=lambda item: (
        item.get("run_id", 0), item["code"], item.get("attempt_id", "")
    ))
    return {
        "schema": "lottery.experiment-execution-reconciliation/v1",
        "mode": "read_only",
        "repository": repository,
        "repository_id": repository_id,
        "workflow_id": workflow_id,
        "workflow_path": workflow_path,
        "registry_event_count": snapshot["event_count"],
        "registered_execution_attempt_count": sum(len(items) for items in attempts_by_run.values()),
        "workflow_run_count_scanned": len(workflow_runs),
        "finding_count": len(findings),
        "findings": findings,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry-root", type=Path, required=True)
    parser.add_argument("--repository", default="Be90nia/Lottery")
    parser.add_argument("--repository-id", default="1461523125")
    parser.add_argument("--workflow-id", type=int, default=423307604)
    parser.add_argument("--workflow-path", default=".github/workflows/subset-research.yml")
    parser.add_argument("--token-env", default="GITHUB_TOKEN")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    token = os.environ.get(args.token_env) or os.environ.get("GH_TOKEN")
    if not token:
        raise SystemExit("GITHUB_TOKEN (Actions: read) is required for read-only reconciliation")
    report = reconcile(
        registry_root=args.registry_root, token=token,
        repository=args.repository, repository_id=args.repository_id,
        workflow_id=args.workflow_id, workflow_path=args.workflow_path,
    )
    raw = json.dumps(report, sort_keys=True, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(raw, encoding="utf-8")
    print(raw, end="")
    return 1 if any(item["severity"] == "error" for item in report["findings"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
