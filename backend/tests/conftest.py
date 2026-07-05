from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def project_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    track_path = tmp_path / "tracks" / "main.strudel.js"
    snapshots_dir = tmp_path / "snapshots"
    track_path.parent.mkdir(parents=True)
    track_path.write_text('s("bd")\n', encoding="utf-8")

    monkeypatch.setattr("app.tracks.TRACK_PATH", track_path)
    monkeypatch.setattr("app.snapshots.SNAPSHOTS_DIR", snapshots_dir)
    return {"track_path": track_path, "snapshots_dir": snapshots_dir}
