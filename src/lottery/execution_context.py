"""Validated GitHub Actions execution identity for immutable research provenance.

This captures a workflow invocation locator. It does not authenticate the
producer; a trusted GitHub metadata verifier remains a separate boundary.
"""
from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from typing import Any

from .subset_model.artifact import canonicalize


EXECUTION_SCHEMA = "lottery.github-actions-execution/v2"
_EXECUTION_FIELDS = {
    "schema", "repository", "repository_id", "workflow_id", "workflow_path", "workflow_ref",
    "run_id", "run_attempt", "job", "event_name", "ref", "sha", "actor", "run_url",
    "execution_id",
}


class ExecutionContextError(ValueError):
    """Raised when a GitHub Actions execution context is malformed or unexpected."""


def _execution_digest(context: Mapping[str, Any]) -> str:
    identity = {
        "schema": EXECUTION_SCHEMA,
        "repository_id": context["repository_id"],
        "workflow_id": context["workflow_id"],
        "workflow_path": context["workflow_path"],
        "run_id": context["run_id"],
        "run_attempt": context["run_attempt"],
    }
    return hashlib.sha256(canonicalize(identity)).hexdigest()


def validate_execution_context(
    context: dict[str, Any],
    *,
    expected_repository: str,
    expected_repository_id: str,
    expected_workflow_id: int,
    expected_workflow_path: str,
) -> dict[str, Any]:
    """Validate a closed execution envelope and return a shallow copy."""
    if not isinstance(context, dict) or set(context) != _EXECUTION_FIELDS:
        raise ExecutionContextError("execution context fields do not match the closed schema")
    if context["schema"] != EXECUTION_SCHEMA:
        raise ExecutionContextError("unsupported execution context schema")
    if context["repository"] != expected_repository:
        raise ExecutionContextError("execution repository does not match the allowlist")
    if str(context["repository_id"]) != str(expected_repository_id):
        raise ExecutionContextError("execution repository ID does not match the allowlist")
    if type(context["workflow_id"]) is not int or context["workflow_id"] != expected_workflow_id:
        raise ExecutionContextError("execution workflow ID does not match the allowlist")
    if context["workflow_path"] != expected_workflow_path:
        raise ExecutionContextError("execution workflow path does not match the allowlist")
    prefix = f'{expected_repository}/{expected_workflow_path}@'
    if not isinstance(context["workflow_ref"], str) or not context["workflow_ref"].startswith(prefix):
        raise ExecutionContextError("workflow_ref does not bind the allowed workflow path")
    workflow_ref_suffix = context["workflow_ref"][len(prefix):]
    if not workflow_ref_suffix:
        raise ExecutionContextError("workflow_ref is missing its ref")
    if workflow_ref_suffix != context["ref"]:
        raise ExecutionContextError("workflow_ref ref does not match execution ref")
    if type(context["run_id"]) is not int or context["run_id"] <= 0:
        raise ExecutionContextError("run_id must be a positive integer")
    if type(context["run_attempt"]) is not int or context["run_attempt"] <= 0:
        raise ExecutionContextError("run_attempt must be a positive integer")
    for field in ("job", "event_name", "ref", "actor"):
        if not isinstance(context[field], str) or not context[field].strip():
            raise ExecutionContextError(f"{field} must be a non-empty string")
    allowed_refs_by_event = {
        "push": {
            "refs/heads/feat/lot-055-preregistered-holm-inference",
            "refs/heads/feat/lot-063-prospective-score-ledger",
            "refs/heads/feat/lot-064-g3-runtime-binding-isolated",
        },
        "workflow_dispatch": {
            "refs/heads/feat/lot-064-g3-runtime-binding-isolated",
        },
    }
    if context["ref"] not in allowed_refs_by_event.get(context["event_name"], set()):
        raise ExecutionContextError("execution event/ref does not match the explicit workflow allowlist")
    if not isinstance(context["sha"], str) or re.fullmatch(r"[0-9a-f]{40}", context["sha"]) is None:
        raise ExecutionContextError("sha must be a lowercase 40-character commit SHA")
    expected_url = f"https://github.com/{expected_repository}/actions/runs/{context['run_id']}"
    if context["run_url"] != expected_url:
        raise ExecutionContextError("run_url does not match repository and run_id")
    if not isinstance(context["execution_id"], str) or context["execution_id"] != _execution_digest(context):
        raise ExecutionContextError("execution_id does not match the immutable invocation identity")
    return dict(context)


def execution_context_from_env(
    env: Mapping[str, str],
    *,
    checked_out_sha: str,
    expected_repository: str,
    expected_repository_id: str,
    expected_workflow_id: int,
    expected_workflow_path: str,
) -> dict[str, Any]:
    """Build and validate an execution envelope from the real Actions environment."""
    required = (
        "GITHUB_REPOSITORY", "GITHUB_REPOSITORY_ID", "LOTTERY_WORKFLOW_ID", "GITHUB_WORKFLOW_REF",
        "GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT", "GITHUB_JOB", "GITHUB_EVENT_NAME",
        "GITHUB_REF", "GITHUB_SHA", "GITHUB_ACTOR",
    )
    missing = [key for key in required if not env.get(key)]
    if missing:
        raise ExecutionContextError("missing GitHub Actions context: " + ", ".join(missing))
    if env["GITHUB_REPOSITORY"] != expected_repository:
        raise ExecutionContextError("repository GITHUB_REPOSITORY does not match the allowlist")
    if str(env["GITHUB_REPOSITORY_ID"]) != str(expected_repository_id):
        raise ExecutionContextError("GITHUB_REPOSITORY_ID does not match the allowlist")
    if env["GITHUB_SHA"] != checked_out_sha:
        raise ExecutionContextError("checked-out HEAD does not match GITHUB_SHA")
    if not isinstance(checked_out_sha, str) or re.fullmatch(r"[0-9a-f]{40}", checked_out_sha) is None:
        raise ExecutionContextError("checked_out_sha must be a lowercase 40-character commit SHA")
    try:
        workflow_id = int(env["LOTTERY_WORKFLOW_ID"])
        run_id = int(env["GITHUB_RUN_ID"])
        run_attempt = int(env["GITHUB_RUN_ATTEMPT"])
    except (TypeError, ValueError) as exc:
        raise ExecutionContextError("LOTTERY_WORKFLOW_ID, GITHUB_RUN_ID and GITHUB_RUN_ATTEMPT must be integers") from exc
    prefix = f'{expected_repository}/'
    workflow_ref = env["GITHUB_WORKFLOW_REF"]
    if not workflow_ref.startswith(prefix) or "@" not in workflow_ref:
        raise ExecutionContextError("GITHUB_WORKFLOW_REF is malformed or belongs to another repository")
    workflow_path, _ = workflow_ref[len(prefix):].rsplit("@", 1)
    context = {
        "schema": EXECUTION_SCHEMA,
        "repository": env["GITHUB_REPOSITORY"],
        "repository_id": str(env["GITHUB_REPOSITORY_ID"]),
        "workflow_id": workflow_id,
        "workflow_path": workflow_path,
        "workflow_ref": workflow_ref,
        "run_id": run_id,
        "run_attempt": run_attempt,
        "job": env["GITHUB_JOB"],
        "event_name": env["GITHUB_EVENT_NAME"],
        "ref": env["GITHUB_REF"],
        "sha": checked_out_sha,
        "actor": env["GITHUB_ACTOR"],
        "run_url": f"https://github.com/{expected_repository}/actions/runs/{run_id}",
    }
    context["execution_id"] = _execution_digest(context)
    return validate_execution_context(
        context,
        expected_repository=expected_repository,
        expected_repository_id=expected_repository_id,
        expected_workflow_id=expected_workflow_id,
        expected_workflow_path=expected_workflow_path,
    )
