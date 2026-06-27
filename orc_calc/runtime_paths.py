from __future__ import annotations

import sys
from pathlib import Path


def application_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def runtime_dir() -> Path:
    path = application_root() / "runtime"
    path.mkdir(parents=True, exist_ok=True)
    return path


def logs_dir() -> Path:
    path = application_root() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path
