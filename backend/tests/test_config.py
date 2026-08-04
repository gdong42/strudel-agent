from __future__ import annotations

from pathlib import Path

from app.config import load_config
from app.paths import snapshots_dir, track_path


def test_repository_defaults_to_deepseek_v4_flash() -> None:
    config = load_config()

    assert config.agent.provider == "deepseek"
    assert config.agent.model == "deepseek-v4-flash"
    assert config.agent.runtime.max_turns == 8
    assert config.agent.runtime.max_elapsed_seconds == 900
    assert config.agent.runtime.max_total_tokens == 4_000_000
    assert config.agent.runtime.max_output_tokens_per_turn == 65_536
    assert config.agent.context_file == "agent-context.md"
    assert config.samples.registry_path == "samples"
    assert config.samples.library_path == "samples/library"


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
          "agent": {
            "contextFile": "set/context.md",
            "runtime": {
              "maxTurns": 3,
              "maxElapsedSeconds": 12,
              "maxTotalTokens": 900,
              "maxOutputTokensPerTurn": 256
            }
          },
          "snapshots": {
            "directory": "history",
            "maxCount": 3,
            "maxAgeHours": 2
          },
          "samples": {
            "registryPath": "audio",
            "libraryPath": "audio/library"
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
    assert config.agent.runtime.max_turns == 3
    assert config.agent.runtime.max_elapsed_seconds == 12
    assert config.agent.runtime.max_total_tokens == 900
    assert config.agent.runtime.max_output_tokens_per_turn == 256
    assert config.agent.context_file == "set/context.md"
    assert config.samples.registry_path == "audio"
    assert config.samples.library_path == "audio/library"
    assert track_path() == tmp_path / "tracks" / "live.strudel.js"
    assert snapshots_dir() == tmp_path / "history"


def test_load_config_accepts_an_unlimited_total_token_budget(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("STRUDEL_AGENT_ROOT", str(tmp_path))
    (tmp_path / "project.config.json").write_text(
        '{"agent":{"runtime":{"maxTotalTokens":null}}}',
        encoding="utf-8",
    )

    assert load_config().agent.runtime.max_total_tokens is None
