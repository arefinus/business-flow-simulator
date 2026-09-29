"""Run manifest (schema_version 1) written by every smoke, demo and run."""
from __future__ import annotations

import platform
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import yaml

from business_flow_simulator import PROJECT_ID
from business_flow_simulator.outputs import canonical_json, sha256_bytes

MANIFEST_SCHEMA_VERSION = 1


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run_id(mode: str, started_at: str) -> str:
    return started_at.replace(":", "").replace("-", "") + "-" + mode


def configuration_hash(*parts: Mapping[str, Any]) -> str:
    return sha256_bytes(canonical_json(list(parts)).encode("utf-8"))


def build_manifest(*, mode: str, status: str, started_at: str, finished_at: str, seed: int,
                   config_hash: str, data_hash: str, sample_counts: Mapping[str, int],
                   metrics_file: str | None, predictions_file: str | None = None,
                   source_id: str = "synthetic-fixture-v1") -> dict[str, Any]:
    if mode not in ("smoke", "demo", "experiment"):
        raise ValueError(f"mode must be smoke, demo or experiment, got {mode!r}")
    if status not in ("completed", "failed"):
        raise ValueError(f"status must be completed or failed, got {status!r}")
    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "project_id": PROJECT_ID,
        "run_id": run_id(mode, started_at),
        "status": status,
        "mode": mode,
        "evidence_status": "demo",
        "git_commit": None,
        "data": {
            "source_id": source_id,
            "version": "v1",
            "split_manifest_hash": data_hash,
            "sample_counts": dict(sample_counts),
        },
        "configuration_hash": config_hash,
        "seed": int(seed),
        "environment": {"python": platform.python_version(), "device": "cpu"},
        "metrics_file": metrics_file,
        "predictions_file": predictions_file,
        "started_at": started_at,
        "finished_at": finished_at,
    }


def write_manifest(manifest: Mapping[str, Any], path: str | Path) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8", newline="\n") as fh:
        yaml.safe_dump(dict(manifest), fh, sort_keys=False)
    return p
