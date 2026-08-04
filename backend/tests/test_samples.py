from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.samples import (
    SampleRegistryError,
    declared_samples,
    load_sample_library,
    load_sample_registry,
    resolve_sample_file,
    sample_library_path,
    sample_map,
    sample_registry_path,
)


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


def test_sample_library_builds_a_stable_map_from_folders_and_root_files(tmp_path: Path) -> None:
    library = sample_library_path(root=tmp_path)
    (library / "kick").mkdir(parents=True)
    (library / "kick" / "02 punch.wav").write_bytes(b"punch")
    (library / "kick" / "01 deep.WAV").write_bytes(b"deep")
    (library / "vocal.wav").write_bytes(b"vocal")
    (library / "ignore.txt").write_text("not audio", encoding="utf-8")

    loaded = load_sample_library(root=tmp_path)

    assert loaded.configured is True
    assert loaded.file_count == 3
    assert loaded.sounds == {
        "kick": ("kick/01 deep.WAV", "kick/02 punch.wav"),
        "vocal": ("vocal.wav",),
    }
    assert sample_map(loaded) == {
        "_base": "/sample-library/files/",
        "kick": ["kick/01 deep.WAV", "kick/02 punch.wav"],
        "vocal": ["vocal.wav"],
    }
    assert loaded.info().map_url is not None


def test_sample_library_ignores_empty_directories_with_unsupported_names(tmp_path: Path) -> None:
    library = sample_library_path(root=tmp_path)
    (library / "field recordings").mkdir(parents=True)
    (library / "field recordings" / "notes.txt").write_text("not audio", encoding="utf-8")

    loaded = load_sample_library(root=tmp_path)

    assert loaded.sounds == {}


def test_sample_library_supports_m4a_variants(tmp_path: Path) -> None:
    library = sample_library_path(root=tmp_path)
    (library / "voice").mkdir(parents=True)
    (library / "voice" / "00_hello.m4a").write_bytes(b"audio")

    loaded = load_sample_library(root=tmp_path)

    assert loaded.sounds == {"voice": ("voice/00_hello.m4a",)}
    assert resolve_sample_file("voice/00_hello.m4a", loaded).read_bytes() == b"audio"


def test_sample_library_names_are_merged_into_the_agent_catalog(tmp_path: Path) -> None:
    library = sample_library_path(root=tmp_path)
    (library / "house_kick").mkdir(parents=True)
    (library / "house_kick" / "dry.wav").write_bytes(b"dry")
    registry = sample_registry_path(root=tmp_path)
    registry.parent.mkdir(parents=True, exist_ok=True)
    registry.write_text(
        json.dumps(
            {
                "version": 1,
                "sounds": [
                    {"name": "HOUSE_KICK", "tags": ["drum", "kick"], "description": "Main kick."},
                    {"name": "external_hat", "tags": ["hat"]},
                ],
            }
        ),
        encoding="utf-8",
    )

    loaded = load_sample_registry(root=tmp_path)

    assert [(sound.name, sound.tags, sound.description) for sound in declared_samples(loaded)] == [
        ("external_hat", ["hat"], None),
        ("house_kick", ["drum", "kick"], "Main kick."),
    ]


def test_sample_library_rejects_invalid_names_symlinks_and_unmapped_files(tmp_path: Path) -> None:
    library = sample_library_path(root=tmp_path)
    (library / "bad name").mkdir(parents=True)
    (library / "bad name" / "sound.wav").write_bytes(b"bad")

    with pytest.raises(SampleRegistryError, match="invalid sound name"):
        load_sample_library(root=tmp_path)

    (library / "bad name" / "sound.wav").unlink()
    (library / "bad name").rmdir()
    (library / "kick").mkdir()
    (library / "kick" / "one.wav").write_bytes(b"one")
    (library / "secret.txt").write_text("secret", encoding="utf-8")
    loaded = load_sample_library(root=tmp_path)

    assert resolve_sample_file("kick/one.wav", loaded) == library / "kick" / "one.wav"
    with pytest.raises(SampleRegistryError, match="outside"):
        resolve_sample_file("../secret.txt", loaded)
    with pytest.raises(SampleRegistryError, match="unavailable"):
        resolve_sample_file("secret.txt", loaded)


def test_sample_library_rejects_symbolic_links(tmp_path: Path) -> None:
    library = sample_library_path(root=tmp_path)
    library.mkdir(parents=True)
    outside = tmp_path / "outside.wav"
    outside.write_bytes(b"outside")
    (library / "linked.wav").symlink_to(outside)

    with pytest.raises(SampleRegistryError, match="symbolic links"):
        load_sample_library(root=tmp_path)
