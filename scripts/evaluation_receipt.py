#!/usr/bin/env python3
"""Build and verify immutable paired model-evaluation receipts."""
from __future__ import annotations
import argparse, json, os, tempfile
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from lottery.evaluation import EvaluationGateError, build_evaluation_receipt, verify_evaluation_receipt

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
                payload["score_rows"], candidate_model_id=args.candidate_model_id,
                champion_model_id=args.champion_model_id, dataset_sha256=args.dataset_sha256,
                code_commit=args.code_commit, protocol_version=args.protocol_version,
                scope=args.scope, min_targets=args.min_targets)
            if args.output.resolve() == args.scores.resolve():
                raise EvaluationGateError("receipt output must not overwrite the score input")
            args.output.parent.mkdir(parents=True, exist_ok=True)
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=args.output.name + ".", suffix=".tmp", dir=args.output.parent
            )
            temporary = Path(temporary_name)
            try:
                with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                    handle.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, args.output)
            except Exception:
                temporary.unlink(missing_ok=True)
                raise

        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, EvaluationGateError, ValueError) as exc:
        print(f"EVALUATION_RECEIPT_FAILED: {exc}", file=sys.stderr)
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
