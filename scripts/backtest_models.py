#!/usr/bin/env python3
"""Run the rolling-origin benchmark for uniform and historical-frequency models."""
from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lottery.backtest import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
