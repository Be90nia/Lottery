#!/usr/bin/env python3
"""Fail closed on mutable GitHub Actions refs and excessive workflow permissions.

This check intentionally uses only the Python standard library.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

WORKFLOW_DIR = Path(".github/workflows")
FULL_SHA = re.compile(r"^[0-9a-f]{40}$")
ALLOWED_PERMISSION = re.compile(r"^(\s*)(contents|actions):\s*read\s*(?:#.*)?$")


def main() -> int:
    errors: list[str] = []
    files = sorted(WORKFLOW_DIR.glob("*.yml")) + sorted(WORKFLOW_DIR.glob("*.yaml"))
    if not files:
        errors.append(f"No workflow files found under {WORKFLOW_DIR}")

    for path in files:
        lines = path.read_text(encoding="utf-8").splitlines()
        for number, line in enumerate(lines, 1):
            uses = re.match(r"^\s*-?\s*uses:\s*([^\s#]+)", line)
            if uses:
                reference = uses.group(1)
                if "@" not in reference:
                    errors.append(f"{path}:{number}: action reference lacks @ref: {reference}")
                    continue
                _, ref = reference.rsplit("@", 1)
                if not FULL_SHA.fullmatch(ref):
                    errors.append(
                        f"{path}:{number}: action must use a full 40-character commit SHA: {reference}"
                    )

            permission = re.match(r"^(\s*)permissions:\s*(?:#.*)?$", line)
            if permission:
                indent = len(permission.group(1))
                found = False
                for child_number, child in enumerate(lines[number:], number + 1):
                    if not child.strip() or child.lstrip().startswith("#"):
                        continue
                    child_indent = len(child) - len(child.lstrip())
                    if child_indent <= indent:
                        break
                    found = True
                    permission_match = ALLOWED_PERMISSION.fullmatch(child)
                    if child_indent != indent + 2 or permission_match is None:
                        errors.append(
                            f"{path}:{child_number}: permission exceeds the read-only allowlist: {child.strip()}"
                        )
                    elif permission_match.group(2) == "actions" and not (
                        path.name == "subset-research.yml" and indent == 4
                    ):
                        errors.append(
                            f"{path}:{child_number}: actions: read is allowed only for the subset research job"
                        )
                if not found:
                    errors.append(f"{path}:{number}: empty permissions block")

        for number, line in enumerate(lines, 1):
            if re.match(r"^\s*-?\s*uses:\s*actions/checkout@", line):
                line_indent = len(line) - len(line.lstrip())
                step_indent = line_indent if line.lstrip().startswith("- uses:") else line_indent - 2
                step_lines: list[str] = []
                for candidate in lines[number:]:
                    candidate_indent = len(candidate) - len(candidate.lstrip())
                    if candidate.strip().startswith("- ") and candidate_indent <= step_indent:
                        break
                    step_lines.append(candidate)
                if not re.search(r"persist-credentials:\s*false", "\n".join(step_lines)):
                    errors.append(
                        f"{path}:{number}: checkout must set persist-credentials: false"
                    )

    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print(f"Workflow security policy passed for {len(files)} workflow file(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
