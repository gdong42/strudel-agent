from __future__ import annotations

import os
from pathlib import Path


DEFAULT_ROOT = Path(__file__).resolve().parents[2]


def project_root() -> Path:
    configured = os.environ.get("STRUDEL_AGENT_ROOT")
    if configured:
        return Path(configured).expanduser().resolve()
    return DEFAULT_ROOT


def track_path() -> Path:
    from .config import load_config

    return project_root() / load_config().track_file


def snapshots_dir() -> Path:
    from .config import load_config

    return project_root() / load_config().snapshots.directory


def changes_dir() -> Path:
    return project_root() / "changes"
