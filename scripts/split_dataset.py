#!/usr/bin/env python3
"""Write deterministic chronological train/validation/test JSONL partitions."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lottery.split import split_chronologically  # noqa: E402
from lottery.validate import validate_jsonl  # noqa: E402


def _write_atomic(path: Path, content: str) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--train-fraction", type=float, default=0.70)
    parser.add_argument("--validation-fraction", type=float, default=0.15)
    args = parser.parse_args()

    try:
        validation = validate_jsonl(args.dataset)
        raw = args.dataset.read_bytes()
        rows = [json.loads(line) for line in raw.decode("utf-8").splitlines()]
        result = split_chronologically(
            rows,
            train_fraction=args.train_fraction,
            validation_fraction=args.validation_fraction,
        )
        args.output_dir.mkdir(parents=True, exist_ok=True)
        files = {}
        for name, partition in result["partitions"].items():
            path = args.output_dir / f"{name}.jsonl"
            content = "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in partition)
            _write_atomic(path, content)
            files[name] = {
                "file": path.name,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        manifest = {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "input": {
                "file": args.dataset.name,
                "sha256": hashlib.sha256(raw).hexdigest(),
                "validation": validation,
            },
            "split": result["metadata"],
            "files": files,
            "limitations": [
                "Static chronological partitions are for exploratory development and are not a substitute for rolling-origin evaluation.",
                "These partitions do not constitute the preregistered 500-draw prospective holdout.",
                "Same-date rows are kept together; actual row fractions may differ from requested fractions.",
            ],
        }
        manifest_path = args.output_dir / "split-manifest.json"
        _write_atomic(manifest_path, json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps(manifest, ensure_ascii=False, indent=2))
        return 0
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        print(f"CHRONOLOGICAL_SPLIT_FAILED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
