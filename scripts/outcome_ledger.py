#!/usr/bin/env python3
"""Record, verify, and score post-draw outcome ledger events."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lottery.outcomes import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
