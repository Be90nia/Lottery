#!/usr/bin/env python3
"""Run the auditable Lottery MVP candidate-generation pipeline."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lottery.mvp import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
