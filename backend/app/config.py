from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field

from .paths import project_root


CONFIG_FILENAME = "project.config.json"


class SnapshotConfig(BaseModel):
    max_count: int = Field(default=50, alias="maxCount")
    max_age_hours: int = Field(default=24, alias="maxAgeHours")
    directory: str = "snapshots"


class AgentRuntimeConfig(BaseModel):
    max_turns: int = Field(default=8, alias="maxTurns", ge=1)
    max_elapsed_seconds: int = Field(default=900, alias="maxElapsedSeconds", ge=1)
    max_total_tokens: int | None = Field(default=4_000_000, alias="maxTotalTokens", ge=1)
    max_output_tokens_per_turn: int = Field(default=65_536, alias="maxOutputTokensPerTurn", ge=1)


class AgentConfig(BaseModel):
    provider: str = "mock"
    model: str | None = None
    context_file: str = Field(default="agent-context.md", alias="contextFile")
    runtime: AgentRuntimeConfig = Field(default_factory=AgentRuntimeConfig)


class SampleConfig(BaseModel):
    registry_path: str = Field(default="samples", alias="registryPath")
    library_path: str = Field(default="samples/library", alias="libraryPath")


class ServerConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8787


class ProjectConfig(BaseModel):
    track_file: str = Field(default="tracks/main.strudel.js", alias="trackFile")
    snapshots: SnapshotConfig = Field(default_factory=SnapshotConfig)
    agent: AgentConfig = Field(default_factory=AgentConfig)
    samples: SampleConfig = Field(default_factory=SampleConfig)
    server: ServerConfig = Field(default_factory=ServerConfig)


def load_config() -> ProjectConfig:
    path = config_path()
    if not path.exists():
        return ProjectConfig()

    return ProjectConfig.model_validate(json.loads(path.read_text(encoding="utf-8")))


def config_path() -> Path:
    return project_root() / CONFIG_FILENAME
