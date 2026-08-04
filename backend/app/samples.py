from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .config import load_config
from .paths import project_root


REGISTRY_FILENAME = "registry.json"
SAMPLE_MAP_PATH = "/sample-library/strudel.json"
SAMPLE_FILE_BASE = "/sample-library/files/"
SUPPORTED_AUDIO_EXTENSIONS = frozenset({".aif", ".aiff", ".flac", ".m4a", ".mp3", ".ogg", ".wav"})
_SOUND_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


class SampleRegistryError(ValueError):
    pass


class DeclaredSample(BaseModel):
    """A sound name the project has deliberately made available to its REPL."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    name: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
    tags: list[str] = Field(default_factory=list)
    description: str | None = Field(default=None, max_length=240)

    @model_validator(mode="after")
    def validate_tags(self) -> "DeclaredSample":
        normalized = [tag.casefold() for tag in self.tags]
        if any(not tag.strip() for tag in self.tags):
            raise ValueError("Sample tags cannot be empty")
        if len(set(normalized)) != len(normalized):
            raise ValueError("Sample tags must be unique")
        return self


class SampleRegistry(BaseModel):
    """Versioned manifest of names, not a claim that audio is currently loaded."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    version: int = Field(ge=1, le=1)
    sounds: list[DeclaredSample] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_unique_sound_names(self) -> "SampleRegistry":
        names = [sound.name.casefold() for sound in self.sounds]
        if len(set(names)) != len(names):
            raise ValueError("Sample names must be unique without regard to case")
        return self


class SampleLibraryInfo(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    configured: bool
    sound_count: int = Field(alias="soundCount", ge=0)
    file_count: int = Field(alias="fileCount", ge=0)
    map_url: str | None = Field(default=None, alias="mapUrl")


class LoadedSampleRegistry(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    configured: bool
    registry: SampleRegistry
    library: SampleLibraryInfo


class SampleListResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    configured: bool
    samples: list[DeclaredSample]
    library: SampleLibraryInfo


@dataclass(frozen=True)
class LoadedSampleLibrary:
    configured: bool
    root: Path
    sounds: dict[str, tuple[str, ...]]
    fingerprint: str

    @property
    def file_count(self) -> int:
        return sum(len(files) for files in self.sounds.values())

    def info(self) -> SampleLibraryInfo:
        return SampleLibraryInfo(
            configured=self.configured,
            soundCount=len(self.sounds),
            fileCount=self.file_count,
            mapUrl=f"{SAMPLE_MAP_PATH}?v={self.fingerprint[:12]}" if self.sounds else None,
        )


def sample_registry_path(registry_directory: str | None = None, *, root: Path | None = None) -> Path:
    configured_directory = registry_directory if registry_directory is not None else load_config().samples.registry_path
    directory = _project_directory(configured_directory, "Sample registry", root=root)
    return directory / REGISTRY_FILENAME


def sample_library_path(library_directory: str | None = None, *, root: Path | None = None) -> Path:
    configured_directory = library_directory if library_directory is not None else load_config().samples.library_path
    return _project_directory(configured_directory, "Sample library", root=root)


def load_sample_registry(
    registry_directory: str | None = None,
    *,
    library_directory: str | None = None,
    root: Path | None = None,
) -> LoadedSampleRegistry:
    path = sample_registry_path(registry_directory, root=root)
    registry_configured = path.exists()
    if registry_configured:
        if path.is_symlink() or not path.is_file():
            raise SampleRegistryError("Sample registry must be a regular file")
        try:
            registry = SampleRegistry.model_validate(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError) as error:
            raise SampleRegistryError(f"Could not load sample registry {path.name}") from error
    else:
        registry = SampleRegistry(version=1)

    library = load_sample_library(library_directory, root=root)
    metadata = {sound.name.casefold(): sound for sound in registry.sounds}
    merged: list[DeclaredSample] = []
    library_names: set[str] = set()
    for name, files in library.sounds.items():
        library_names.add(name.casefold())
        declared = metadata.get(name.casefold())
        merged.append(
            DeclaredSample(
                name=name,
                tags=declared.tags if declared else [],
                description=declared.description if declared else _local_sample_description(len(files)),
            )
        )
    merged.extend(sound for sound in registry.sounds if sound.name.casefold() not in library_names)
    return LoadedSampleRegistry(
        configured=registry_configured or library.configured,
        registry=SampleRegistry(version=1, sounds=merged),
        library=library.info(),
    )


def declared_samples(registry: LoadedSampleRegistry) -> list[DeclaredSample]:
    return sorted(registry.registry.sounds, key=lambda sound: sound.name.casefold())


def load_sample_library(
    library_directory: str | None = None,
    *,
    root: Path | None = None,
) -> LoadedSampleLibrary:
    library = sample_library_path(library_directory, root=root)
    if not library.exists():
        return LoadedSampleLibrary(configured=False, root=library, sounds={}, fingerprint=_fingerprint({}))
    if library.is_symlink() or not library.is_dir():
        raise SampleRegistryError("Sample library must be a regular directory")

    sounds: dict[str, list[str]] = {}
    canonical_names: dict[str, str] = {}
    try:
        for entry in sorted(library.iterdir(), key=lambda item: item.name.casefold()):
            if entry.name.startswith("."):
                continue
            if entry.is_symlink():
                raise SampleRegistryError("Sample library cannot contain symbolic links")
            if entry.is_file() and _is_supported_audio(entry):
                _add_library_file(sounds, canonical_names, entry.stem, entry.relative_to(library))
                continue
            if not entry.is_dir():
                continue
            audio_files = [
                audio
                for audio in sorted(entry.rglob("*"), key=lambda item: item.as_posix().casefold())
                if audio.is_file() and _is_supported_audio(audio)
            ]
            if audio_files:
                _validate_sound_name(entry.name)
            for audio in audio_files:
                if audio.is_symlink():
                    raise SampleRegistryError("Sample library cannot contain symbolic links")
                _add_library_file(sounds, canonical_names, entry.name, audio.relative_to(library))
    except OSError as error:
        raise SampleRegistryError("Could not scan sample library") from error

    frozen = {name: tuple(files) for name, files in sorted(sounds.items(), key=lambda item: item[0].casefold())}
    try:
        fingerprint = _fingerprint(frozen, root=library)
    except OSError as error:
        raise SampleRegistryError("Could not scan sample library") from error
    return LoadedSampleLibrary(configured=True, root=library, sounds=frozen, fingerprint=fingerprint)


def sample_map(library: LoadedSampleLibrary) -> dict[str, str | list[str]]:
    return {"_base": SAMPLE_FILE_BASE, **{name: list(files) for name, files in library.sounds.items()}}


def resolve_sample_file(sample_path: str, library: LoadedSampleLibrary) -> Path:
    relative = Path(sample_path)
    if relative.is_absolute() or ".." in relative.parts:
        raise SampleRegistryError("Sample file is outside the configured library")
    try:
        candidate = (library.root / relative).resolve(strict=True)
        candidate.relative_to(library.root)
    except (OSError, ValueError) as error:
        raise SampleRegistryError("Sample file is unavailable") from error
    mapped = {path for files in library.sounds.values() for path in files}
    if candidate.is_symlink() or relative.as_posix() not in mapped or not candidate.is_file():
        raise SampleRegistryError("Sample file is unavailable")
    return candidate


def _project_directory(configured_directory: str, label: str, *, root: Path | None) -> Path:
    project = (root or project_root()).resolve()
    directory = Path(configured_directory)
    if directory.is_absolute():
        raise SampleRegistryError(f"{label} must stay inside the project root")
    unresolved = project / directory
    try:
        current = project
        for part in directory.parts:
            current /= part
            if current.is_symlink():
                raise SampleRegistryError(f"{label} must stay inside the project root without symbolic links")
        resolved = unresolved.resolve()
        resolved.relative_to(project)
    except OSError as error:
        raise SampleRegistryError(f"{label} must stay inside the project root") from error
    except ValueError as error:
        raise SampleRegistryError(f"{label} must stay inside the project root") from error
    return resolved


def _add_library_file(
    sounds: dict[str, list[str]],
    canonical_names: dict[str, str],
    sound_name: str,
    relative: Path,
) -> None:
    _validate_sound_name(sound_name)
    folded = sound_name.casefold()
    existing = canonical_names.get(folded)
    if existing is not None and existing != sound_name:
        raise SampleRegistryError("Sample library sound names must be unique without regard to case")
    canonical_names[folded] = sound_name
    sounds.setdefault(sound_name, []).append(relative.as_posix())


def _validate_sound_name(value: str) -> None:
    if not _SOUND_NAME.fullmatch(value):
        raise SampleRegistryError("Sample library contains an invalid sound name")


def _is_supported_audio(path: Path) -> bool:
    return path.suffix.casefold() in SUPPORTED_AUDIO_EXTENSIONS


def _fingerprint(sounds: dict[str, tuple[str, ...]], *, root: Path | None = None) -> str:
    digest = hashlib.sha256()
    for name, files in sorted(sounds.items(), key=lambda item: item[0].casefold()):
        digest.update(name.encode("utf-8"))
        for relative in files:
            digest.update(relative.encode("utf-8"))
            if root is not None:
                stat = (root / relative).stat()
                digest.update(f"{stat.st_size}:{stat.st_mtime_ns}".encode("ascii"))
    return digest.hexdigest()


def _local_sample_description(count: int) -> str:
    unit = "file" if count == 1 else "files"
    return f"{count} local sample {unit}."
