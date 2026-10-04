"""Run provenance required by the benchmark protocol (ADR-0008)."""

from __future__ import annotations

import hashlib
import os
import platform
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DATASETS = Path(__file__).resolve().parent / "datasets"


def _git(*args: str) -> str | None:
    try:
        out = subprocess.run(
            ["git", *args], cwd=ROOT, capture_output=True, text=True, check=True, timeout=10
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip()


def dataset_info(version: str) -> dict[str, Any]:
    folder = DATASETS / version
    files = {}
    combined = hashlib.sha256()
    for path in sorted(folder.glob("*.jsonl")):
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        combined.update(f"{path.name}:{digest}".encode())
        files[path.name] = {
            "sha256": digest,
            "examples": sum(1 for line in path.read_text().splitlines() if line.strip()),
        }
    return {"version": version, "sha256": combined.hexdigest(), "files": files}


def collect(
    *, dataset_version: str, config: dict[str, Any], seeds: dict[str, int]
) -> dict[str, Any]:
    porcelain = _git("status", "--porcelain")
    return {
        "run_at": datetime.now(UTC).isoformat(),
        "git": {
            "commit": _git("rev-parse", "HEAD"),
            "dirty": bool(porcelain) if porcelain is not None else None,
        },
        "dataset": dataset_info(dataset_version),
        "config": config,
        "seeds": seeds,
        "environment": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "machine": platform.machine(),
            "cpu_count": os.cpu_count(),
        },
    }
