from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.samples import SampleRegistryError, declared_samples, load_sample_registry, sample_registry_path


def test_missing_sample_registry_is_an_empty_unconfigured_catalog(tmp_path: Path) -> None:
    registry = load_sample_registry(root=tmp_path)

    assert registry.configured is False
    assert registry.registry.version == 1
    assert registry.registry.sounds == []


def test_sample_registry_loads_declared_sounds_in_stable_name_order(tmp_path: Path) -> None:
    path = sample_registry_path(root=tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "sounds": [
                    {"name": "HouseHat", "tags": ["drum", "hat"]},
                    {"name": "houseKick", "tags": ["drum", "kick"], "description": "Dry kick."},
                ],
            }
        ),
        encoding="utf-8",
    )

    registry = load_sample_registry(root=tmp_path)

    assert registry.configured is True
    assert [sound.name for sound in declared_samples(registry)] == ["HouseHat", "houseKick"]
    assert registry.registry.sounds[1].description == "Dry kick."


@pytest.mark.parametrize("registry_directory", ["../outside", "/tmp/outside"])
def test_sample_registry_path_is_confined_to_the_project_root(tmp_path: Path, registry_directory: str) -> None:
    with pytest.raises(SampleRegistryError, match="stay inside the project root"):
        sample_registry_path(registry_directory, root=tmp_path)


@pytest.mark.parametrize(
    "manifest",
    [
        {"version": 1, "sounds": [{"name": "bd"}, {"name": "BD"}]},
        {"version": 1, "sounds": [{"name": "bad name"}]},
        {"version": 1, "sounds": [{"name": "bd", "tags": ["drum", "DRUM"]}]},
    ],
)
def test_sample_registry_rejects_invalid_or_ambiguous_entries(tmp_path: Path, manifest: dict) -> None:
    path = sample_registry_path(root=tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(SampleRegistryError, match="Could not load"):
        load_sample_registry(root=tmp_path)


def test_sample_registry_rejects_a_directory_and_invalid_json(tmp_path: Path) -> None:
    path = sample_registry_path(root=tmp_path)
    path.mkdir(parents=True)

    with pytest.raises(SampleRegistryError, match="regular file"):
        load_sample_registry(root=tmp_path)

    path.rmdir()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("not json", encoding="utf-8")

    with pytest.raises(SampleRegistryError, match="Could not load"):
        load_sample_registry(root=tmp_path)
