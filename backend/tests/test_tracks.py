from __future__ import annotations

from pathlib import Path

from app.tracks import read_track, write_track


def test_read_write_track_round_trip(project_paths: dict[str, Path]) -> None:
    write_track('s("bd hh")\n')

    assert read_track() == 's("bd hh")\n'
    assert project_paths["track_path"].read_text(encoding="utf-8") == 's("bd hh")\n'
