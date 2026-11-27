#!/usr/bin/env python3
"""Verify that a CP child registration pins the exact immutable GitHub comment body."""

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
    digest_expected = registration.get("child_registration_comment_sha256")
    comment_url = registration.get("child_registration_comment_url")
    issue_url = registration.get("governance_issue_url")
    if not isinstance(comment_id, int) or isinstance(comment_id, bool) or comment_id <= 0:
        raise ValueError("child registration comment ID is missing or malformed")
    if not isinstance(digest_expected, str) or not re.fullmatch(r"[0-9a-f]{64}", digest_expected):
        raise ValueError("child registration comment SHA-256 is missing or malformed")
    expected_comment_url = f"https://github.com/{repository}/issues/27#issuecomment-{comment_id}"
    expected_issue_url = f"https://github.com/{repository}/issues/27"
    if comment_url != expected_comment_url or issue_url != expected_issue_url:
        raise ValueError("child registration comment URL or governance issue URL is mismatched")

    payload = fetch_json(
        f"https://api.github.com/repos/{repository}/issues/comments/{comment_id}",
        token,
    )
    if payload.get("id") != comment_id:
        raise ValueError("GitHub returned a different issue comment ID")
    if payload.get("issue_url") != f"https://api.github.com/repos/{repository}/issues/27":
        raise ValueError("GitHub comment belongs to a different issue")
    if payload.get("html_url") != expected_comment_url:
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
            "child registration comment body SHA-256 mismatch: "
            f"registered={digest_expected} actual={actual}"
        )
    return actual


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registration", type=Path, required=True)
    parser.add_argument("--repository", required=True)
    args = parser.parse_args()
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        raise SystemExit("GITHUB_TOKEN or GH_TOKEN is required for source-comment verification")
    try:
        registration = json.loads(args.registration.read_text(encoding="utf-8"))
        digest = verify_registration_comment(registration, args.repository, token=token)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"CP registration provenance verification failed: {exc}", file=sys.stderr)
        return 1
    print(f"Verified CP child registration comment {registration['child_registration_comment_id']}: sha256={digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
