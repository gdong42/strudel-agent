from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TRACK_PATH = ROOT / "tracks" / "main.strudel.js"


def read_track() -> str:
    return TRACK_PATH.read_text(encoding="utf-8")


def write_track(code: str) -> None:
    TRACK_PATH.parent.mkdir(parents=True, exist_ok=True)
    TRACK_PATH.write_text(code, encoding="utf-8")
