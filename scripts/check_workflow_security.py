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



def validate_subset_research_gate(lines: list[str]) -> list[str]:
    """Keep provenance checks ahead of any registry mutation or full evaluation."""
    markers = {
        "verify": "- name: Verify append-only CP child registration source comment before any evaluation",
        "restore": "- name: Restore append-only registry and LOT-065 object history",
        "import": "- name: Append verified historical G3 execution to the persistent registry",
        "evaluate": "- name: Run full frozen 2,649-target exact-subset evaluation",
    }
    positions = {
        name: next((index for index, line in enumerate(lines) if marker in line), None)
        for name, marker in markers.items()
    }
    errors = []
    missing = [name for name, position in positions.items() if position is None]
    if missing:
        errors.append(
            "subset-research.yml is missing required CP provenance/evaluation step(s): "
            + ", ".join(missing)
        )
        return errors
    if not (
        positions["verify"] < positions["restore"] < positions["import"] < positions["evaluate"]
    ):
        errors.append(
            "CP source-comment verification must precede registry restore, historical import, and evaluation"
        )
    gate = "\n".join(lines[positions["verify"]:positions["restore"]])
    for required in (
        "--registration docs/LOT055_CP_CALIBRATION_REGISTRATION_2026-11-26.json",
        "--legacy-registration docs/G3_DIAGNOSTIC_REGISTRATION_2026-11-22.json",
        '--repository "$GITHUB_REPOSITORY"',
    ):
        if required not in gate:
            errors.append(f"CP provenance gate is missing required argument: {required}")
    workflow = "\n".join(lines)
    if "feat/lot055-cp-calibration-lineage" in workflow.split("workflow_dispatch:", 1)[0]:
        errors.append(
            "CP diagnostic branch must remain excluded from automatic full-evaluation push triggers"
        )
    return errors


def main() -> int:
    errors: list[str] = []
    files = sorted(WORKFLOW_DIR.glob("*.yml")) + sorted(WORKFLOW_DIR.glob("*.yaml"))
    if not files:
        errors.append(f"No workflow files found under {WORKFLOW_DIR}")

    for path in files:
        lines = path.read_text(encoding="utf-8").splitlines()
        if path.name == "subset-research.yml":
            errors.extend(validate_subset_research_gate(lines))
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
                        path.name in (
                            "subset-research.yml", "g3-historical-import.yml",
                            "g3-evidence-reconciliation.yml",
                        ) and indent == 4
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
