from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def project_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    monkeypatch.setenv("STRUDEL_AGENT_ROOT", str(tmp_path))
    track_path = tmp_path / "tracks" / "main.strudel.js"
    snapshots_dir = tmp_path / "snapshots"
    changes_dir = tmp_path / "changes"
    audits_dir = tmp_path / "audits"
    track_path.parent.mkdir(parents=True)
    track_path.write_text('s("bd")\n', encoding="utf-8")

    monkeypatch.setattr("app.tracks.TRACK_PATH", track_path)
    monkeypatch.setattr("app.snapshots.SNAPSHOTS_DIR", snapshots_dir)
    monkeypatch.setattr("app.changes.CHANGES_DIR", changes_dir)
    monkeypatch.setattr("app.run_audit.AUDITS_DIR", audits_dir)
    return {
        "track_path": track_path,
        "snapshots_dir": snapshots_dir,
        "changes_dir": changes_dir,
        "audits_dir": audits_dir,
    }
