#!/usr/bin/env python3
"""Build or operate a registry-bound LOT-063 prospective schedule.

Build requires a protected trust-adapter module with verify_target_manifest(value)
and verify_inventory(value) functions. No default/trivial verifier is supplied.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import importlib
import json
import os
from pathlib import Path
import sys

from lottery.prospective import ProspectiveLedger
from lottery.prospective_registry import (
    RegistryScheduleError,
    _load_canonical,
    assert_registry_unchanged,
    build_registry_schedule,
)
from lottery.prospective_schedule import load_schedule, run_schedule
from lottery.subset_model.artifact import canonicalize
from lottery.subset_model.lifecycle import ChampionLifecycle


def _write_once(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            if path.read_bytes() != raw:
                raise RegistryScheduleError("immutable schedule path already contains different bytes")
        if hasattr(os, "O_DIRECTORY"):
            directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
