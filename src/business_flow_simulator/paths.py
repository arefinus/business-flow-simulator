"""Locate repository-level resources (configs, schemas) from an editable install or a
checkout. Nothing here touches user directories."""
from __future__ import annotations

import os
from pathlib import Path

ENV_ROOT = "BFS_REPO_ROOT"


def repo_root() -> Path:
    env = os.environ.get(ENV_ROOT)
    if env:
        return Path(env).resolve()
    here = Path(__file__).resolve()
    candidate = here.parents[2]
    if (candidate / "configs").is_dir():
        return candidate
    cwd = Path.cwd()
    if (cwd / "configs").is_dir():
        return cwd
    raise FileNotFoundError(
        "cannot locate the repository root (a directory containing configs/). "
        f"Run from the repository root or set {ENV_ROOT}."
    )


def configs_dir() -> Path:
    return repo_root() / "configs"


def scenarios_dir() -> Path:
    return configs_dir() / "scenarios"


def schemas_dir() -> Path:
    return repo_root() / "schemas"


def fixtures_dir() -> Path:
    return repo_root() / "examples" / "fixtures" / "v1"


def output_dir() -> Path:
    return repo_root() / "examples" / "output"
