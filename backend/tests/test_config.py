from __future__ import annotations

from pathlib import Path

from app.config import load_config
from app.paths import snapshots_dir, track_path


def test_repository_defaults_to_deepseek_v4_pro() -> None:
    config = load_config()

    assert config.agent.provider == "deepseek"
    assert config.agent.model == "deepseek-v4-pro"


def test_load_config_defaults_when_file_missing(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("STRUDEL_AGENT_ROOT", str(tmp_path))

    config = load_config()

    assert config.track_file == "tracks/main.strudel.js"
    assert config.snapshots.max_count == 50
    assert config.snapshots.max_age_hours == 24
    assert track_path() == tmp_path / "tracks" / "main.strudel.js"
    assert snapshots_dir() == tmp_path / "snapshots"


def test_load_config_reads_project_config(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("STRUDEL_AGENT_ROOT", str(tmp_path))
    (tmp_path / "project.config.json").write_text(
        """
        {
          "trackFile": "tracks/live.strudel.js",
          "snapshots": {
            "directory": "history",
            "maxCount": 3,
            "maxAgeHours": 2
          }
        }
        """,
        encoding="utf-8",
    )

    config = load_config()

    assert config.track_file == "tracks/live.strudel.js"
    assert config.snapshots.directory == "history"
    assert config.snapshots.max_count == 3
    assert config.snapshots.max_age_hours == 2
    assert track_path() == tmp_path / "tracks" / "live.strudel.js"
    assert snapshots_dir() == tmp_path / "history"
