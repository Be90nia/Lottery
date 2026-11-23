#!/usr/bin/env python3
"""Collect and archive official per-draw ball-set announcements."""
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from lottery.ball_set_evidence import main  # noqa: E402
if __name__ == "__main__":
    raise SystemExit(main())
