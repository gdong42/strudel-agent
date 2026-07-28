from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .config import load_config
from .paths import project_root


REGISTRY_FILENAME = "registry.json"


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


class LoadedSampleRegistry(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    configured: bool
    registry: SampleRegistry


class SampleListResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    configured: bool
    samples: list[DeclaredSample]


def sample_registry_path(registry_directory: str | None = None, *, root: Path | None = None) -> Path:
    project = (root or project_root()).resolve()
    configured_directory = registry_directory if registry_directory is not None else load_config().samples.registry_path
    directory = Path(configured_directory)
    if directory.is_absolute():
        raise SampleRegistryError("Sample registry must stay inside the project root")
    try:
        registry = (project / directory / REGISTRY_FILENAME).resolve()
        registry.relative_to(project)
    except (OSError, ValueError) as error:
        raise SampleRegistryError("Sample registry must stay inside the project root") from error
    return registry


def load_sample_registry(
    registry_directory: str | None = None,
    *,
    root: Path | None = None,
) -> LoadedSampleRegistry:
    path = sample_registry_path(registry_directory, root=root)
    if not path.exists():
        return LoadedSampleRegistry(configured=False, registry=SampleRegistry(version=1))
    if not path.is_file():
        raise SampleRegistryError("Sample registry must be a regular file")
    try:
        registry = SampleRegistry.model_validate(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError) as error:
        raise SampleRegistryError(f"Could not load sample registry {path.name}") from error
    return LoadedSampleRegistry(configured=True, registry=registry)


def declared_samples(registry: LoadedSampleRegistry) -> list[DeclaredSample]:
    return sorted(registry.registry.sounds, key=lambda sound: sound.name.casefold())
