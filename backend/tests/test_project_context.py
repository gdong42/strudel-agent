from __future__ import annotations

from pathlib import Path

import pytest

from app.project_context import MAX_PROJECT_CONTEXT_BYTES, ProjectContextError, load_project_context


def test_load_project_context_returns_none_when_the_optional_file_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("STRUDEL_AGENT_ROOT", str(tmp_path))

    assert load_project_context("agent-context.md") is None


def test_load_project_context_reads_a_utf8_markdown_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("STRUDEL_AGENT_ROOT", str(tmp_path))
    context = "# Set\n\n- Keep the bass stable.\n"
    (tmp_path / "agent-context.md").write_text(context, encoding="utf-8")

    assert load_project_context("agent-context.md") == context


@pytest.mark.parametrize("context_file", ["../outside.md", "/tmp/outside.md"])
def test_load_project_context_rejects_paths_outside_the_project_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, context_file: str
) -> None:
    monkeypatch.setenv("STRUDEL_AGENT_ROOT", str(tmp_path))

    with pytest.raises(ProjectContextError, match="stay inside the project root"):
        load_project_context(context_file)


def test_load_project_context_rejects_non_regular_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STRUDEL_AGENT_ROOT", str(tmp_path))
    (tmp_path / "context").mkdir()

    with pytest.raises(ProjectContextError, match="regular file"):
        load_project_context("context")


def test_load_project_context_rejects_oversized_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STRUDEL_AGENT_ROOT", str(tmp_path))
    (tmp_path / "agent-context.md").write_bytes(b"x" * (MAX_PROJECT_CONTEXT_BYTES + 1))

    with pytest.raises(ProjectContextError, match="16 KiB"):
        load_project_context("agent-context.md")


def test_load_project_context_rejects_invalid_utf8(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STRUDEL_AGENT_ROOT", str(tmp_path))
    (tmp_path / "agent-context.md").write_bytes(b"\xff\xfe")

    with pytest.raises(ProjectContextError, match="valid UTF-8"):
        load_project_context("agent-context.md")
