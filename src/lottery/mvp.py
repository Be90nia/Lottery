"""One-command, auditable candidate-generation MVP runner."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from typing import Any

from .tickets import generate_ticket_candidates
from .validate import validate_records


def run_mvp(
    dataset_path: Path,
    output_path: Path,
    *,
    tickets_per_strategy: int = 5,
    seed: int = 20261119,
    alpha: float = 100.0,
    half_life: float = 100.0,
    code_commit: str | None = None,
) -> dict[str, Any]:
    """Validate one historical input and atomically publish a candidate batch receipt."""
    if dataset_path.resolve() == output_path.resolve():
        raise ValueError("output_path must not overwrite the input dataset")
    if output_path.exists():
        raise ValueError("output_path already exists; choose a new path to preserve prior run evidence")
    raw = dataset_path.read_bytes()
    try:
        lines = raw.decode("utf-8").splitlines()
        if not lines or any(not line.strip() for line in lines):
            raise ValueError("dataset must be non-empty JSONL without blank lines")
        rows = [json.loads(line) for line in lines]
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"dataset is not valid UTF-8 JSONL: {exc}") from exc
    validation = validate_records(rows)
    batch = generate_ticket_candidates(
        rows,
        tickets_per_strategy=tickets_per_strategy,
        seed=seed,
        alpha=alpha,
        half_life=half_life,
    )
    dataset_sha256 = hashlib.sha256(raw).hexdigest()
    commit = code_commit or os.environ.get("GITHUB_SHA")
    if commit is None:
        raise ValueError("code_commit is required; pass --code-commit or run in GitHub Actions")
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("code_commit must be a full 40-character lowercase Git SHA")

    batch["dataset"] = {
        "path": str(dataset_path),
        "sha256": dataset_sha256,
        "validation": validation,
        "trust_status": "not_authenticated_by_this_tool",
    }
    # Recompute the batch digest after attaching the exact byte-level input evidence.
    batch_bytes = json.dumps(
        batch, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    receipt = {
        "schema_version": 1,
        "status": "candidate_batch_generated",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "generation_run_id": batch["generation_run_id"],
        "code_commit": commit,
        "dataset_sha256": dataset_sha256,
        "batch_sha256": hashlib.sha256(batch_bytes).hexdigest(),
        "requested_tickets_per_strategy": tickets_per_strategy,
        "published_ticket_count": batch["total_tickets"],
        "data_trust_status": "not_authenticated_by_this_tool",
        "automatic_sync_status": "not_attempted",
        "model_training_status": "not_performed",
        "model_promotion_status": "not_performed",
    }
    document = {"schema_version": 1, "receipt": receipt, "batch": batch}
    rendered = json.dumps(document, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=output_path.name + ".", suffix=".tmp", dir=output_path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(rendered)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, output_path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return document


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("mvp-output.json"))
    parser.add_argument("--tickets-per-strategy", type=int, default=5)
    parser.add_argument("--seed", type=int, default=20261119)
    parser.add_argument("--alpha", type=float, default=100.0)
    parser.add_argument("--half-life", type=float, default=100.0)
    parser.add_argument("--code-commit")
    args = parser.parse_args()
    try:
        document = run_mvp(
            args.dataset, args.output,
            tickets_per_strategy=args.tickets_per_strategy,
            seed=args.seed, alpha=args.alpha, half_life=args.half_life,
            code_commit=args.code_commit,
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        print(f"MVP_RUN_FAILED: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(document["receipt"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
