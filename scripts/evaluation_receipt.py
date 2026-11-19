#!/usr/bin/env python3
"""Build and verify immutable paired model-evaluation receipts."""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lottery.evaluation import (  # noqa: E402
    EvaluationGateError,
    build_evaluation_receipt,
    verify_evaluation_receipt,
)


def _write_new(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError as exc:
            raise EvaluationGateError(f"refusing to overwrite existing receipt: {path}") from exc
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    build = sub.add_parser("build")
    build.add_argument("scores", type=Path)
    build.add_argument("--candidate-model-id", required=True)
    build.add_argument("--champion-model-id", required=True)
    build.add_argument("--dataset-sha256", required=True)
    build.add_argument("--code-commit", required=True)
    build.add_argument("--protocol-version", required=True)
    build.add_argument("--scope", choices=("rolling_origin", "shadow"), default="rolling_origin")
    build.add_argument("--min-targets", type=int, default=200)
    build.add_argument("--output", type=Path, required=True)

    verify = sub.add_parser("verify")
    verify.add_argument("receipt", type=Path)
    args = parser.parse_args()

    try:
        if args.command == "verify":
            receipt = json.loads(args.receipt.read_text(encoding="utf-8"))
            verify_evaluation_receipt(receipt)
            result = {"valid": True, "receipt_sha256": receipt["receipt_sha256"]}
        else:
            payload = json.loads(args.scores.read_text(encoding="utf-8"))
            if not isinstance(payload, dict) or not isinstance(payload.get("score_rows"), list):
                raise EvaluationGateError("input must be an object with a score_rows array")
            result = build_evaluation_receipt(
                payload["score_rows"],
                candidate_model_id=args.candidate_model_id,
                champion_model_id=args.champion_model_id,
                dataset_sha256=args.dataset_sha256,
                code_commit=args.code_commit,
                protocol_version=args.protocol_version,
                scope=args.scope,
                min_targets=args.min_targets,
            )
            verify_evaluation_receipt(result)
            encoded = (json.dumps(result, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
            _write_new(args.output, encoded)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, EvaluationGateError, ValueError) as exc:
        print(f"EVALUATION_RECEIPT_FAILED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
