#!/usr/bin/env python3
"""Verify exact GitHub comment-body digests pinned by G3/CP registrations."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def _github_json(url: str, token: str) -> dict:
    request = Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "Lottery-registration-provenance-check",
        },
    )
    try:
        with urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"unable to retrieve registered GitHub comment: {type(exc).__name__}") from exc
    if not isinstance(payload, dict):
        raise ValueError("GitHub comment API returned a non-object payload")
    return payload


def _verify_comment(
    *,
    repository: str,
    issue_number: int,
    comment_url: str,
    comment_id: int,
    digest_expected: str,
    token: str,
    fetch_json,
) -> str:
    expected_url = f"https://github.com/{repository}/issues/{issue_number}#issuecomment-{comment_id}"
    if comment_url != expected_url:
        raise ValueError("registered GitHub comment URL or issue lineage is mismatched")
    payload = fetch_json(
        f"https://api.github.com/repos/{repository}/issues/comments/{comment_id}",
        token,
    )
    if payload.get("id") != comment_id:
        raise ValueError("GitHub returned a different issue comment ID")
    if payload.get("issue_url") != (
        f"https://api.github.com/repos/{repository}/issues/{issue_number}"
    ):
        raise ValueError("GitHub comment belongs to a different issue")
    if payload.get("html_url") != expected_url:
        raise ValueError("GitHub comment canonical URL does not match the registration")
    if (not isinstance(payload.get("user"), dict)
            or payload["user"].get("login") != repository.split("/", 1)[0]):
        raise ValueError("GitHub comment author does not match the repository owner")
    body = payload.get("body")
    if not isinstance(body, str):
        raise ValueError("GitHub comment body is missing or not text")
    actual = hashlib.sha256(body.encode("utf-8")).hexdigest()
    if actual != digest_expected:
        raise ValueError(
            "registered GitHub comment body SHA-256 mismatch: "
            f"registered={digest_expected} actual={actual}"
        )
    return actual


def verify_registration_comment(
    registration: dict,
    repository: str,
    *,
    token: str,
    fetch_json=_github_json,
) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("repository must be owner/name")
    comment_id = registration.get("child_registration_comment_id")
    digest = registration.get("child_registration_comment_sha256")
    if not isinstance(comment_id, int) or isinstance(comment_id, bool) or comment_id <= 0:
        raise ValueError("child registration comment ID is missing or malformed")
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError("child registration comment SHA-256 is missing or malformed")
    if registration.get("governance_issue_url") != f"https://github.com/{repository}/issues/27":
        raise ValueError("CP governance issue URL is mismatched")
    if registration.get("parent_issue_url") != f"https://github.com/{repository}/issues/18":
        raise ValueError("CP parent LOT-055 protocol issue URL is mismatched")
    return _verify_comment(
        repository=repository,
        issue_number=27,
        comment_url=registration.get("child_registration_comment_url"),
        comment_id=comment_id,
        digest_expected=digest,
        token=token,
        fetch_json=fetch_json,
    )


def verify_legacy_registration_comment(
    registration: dict,
    repository: str,
    *,
    token: str,
    fetch_json=_github_json,
) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("repository must be owner/name")
    digest = registration.get("legacy_child_registration_comment_sha256")
    comment_url = registration.get("legacy_child_registration_comment_url")
    match = re.fullmatch(
        rf"https://github\.com/{re.escape(repository)}/issues/27#issuecomment-(\d+)",
        comment_url if isinstance(comment_url, str) else "",
    )
    if not match:
        raise ValueError("legacy child registration comment URL is missing or malformed")
    if registration.get("legacy_parent_issue_url") != f"https://github.com/{repository}/issues/18":
        raise ValueError("legacy LOT-055 parent issue URL is mismatched")
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError("legacy child registration comment SHA-256 is missing or malformed")
    return _verify_comment(
        repository=repository,
        issue_number=27,
        comment_url=comment_url,
        comment_id=int(match.group(1)),
        digest_expected=digest,
        token=token,
        fetch_json=fetch_json,
    )



def verify_solver_parameter_comment(
    registration: dict,
    repository: str,
    *,
    digest_expected: str,
    token: str,
    fetch_json=_github_json,
) -> str:
    """Verify the immutable Issue #27 comment that fixes Strong-Wolfe parameters."""
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("repository must be owner/name")
    comment_id = registration.get("solver_parameter_comment_id")
    comment_url = registration.get("solver_parameter_comment_url")
    if comment_id != 7184937843:
        raise ValueError("solver parameter comment ID is missing or not the registered clarification")
    registered_digest = registration.get("solver_parameter_comment_sha256")
    if (not isinstance(registered_digest, str)
            or not re.fullmatch(r"[0-9a-f]{64}", registered_digest)):
        raise ValueError("registration must pin solver_parameter_comment_sha256")
    if not isinstance(digest_expected, str) or not re.fullmatch(r"[0-9a-f]{64}", digest_expected):
        raise ValueError("solver parameter comment SHA-256 is missing or malformed")
    if registered_digest != digest_expected:
        raise ValueError("workflow solver-parameter digest differs from immutable registration")
    return _verify_comment(
        repository=repository,
        issue_number=27,
        comment_url=comment_url,
        comment_id=comment_id,
        digest_expected=digest_expected,
        token=token,
        fetch_json=fetch_json,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registration", type=Path, required=True)
    parser.add_argument("--legacy-registration", type=Path, required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--solver-parameter-comment-sha256", required=True)
    args = parser.parse_args()
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        raise SystemExit("GITHUB_TOKEN or GH_TOKEN is required for source-comment verification")
    try:
        registration = json.loads(args.registration.read_text(encoding="utf-8"))
        legacy_registration = json.loads(args.legacy_registration.read_text(encoding="utf-8"))
        cp_digest = verify_registration_comment(registration, args.repository, token=token)
        legacy_digest = verify_legacy_registration_comment(
            legacy_registration, args.repository, token=token,
        )
        solver_digest = verify_solver_parameter_comment(
            registration, args.repository,
            digest_expected=args.solver_parameter_comment_sha256, token=token,
        )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"Registration provenance verification failed: {exc}", file=sys.stderr)
        return 1
    print(
        "Verified CP and legacy G3 source comments: "
        f"cp_sha256={cp_digest} legacy_sha256={legacy_digest} "
        f"solver_parameters_sha256={solver_digest}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
