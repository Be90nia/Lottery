#!/usr/bin/env python3
"""Build a reproducible official ball-set evidence coverage report."""
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from lottery.ball_set_coverage import main  # noqa: E402
if __name__ == "__main__":
    raise SystemExit(main())
