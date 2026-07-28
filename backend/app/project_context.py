from __future__ import annotations

from pathlib import Path

from .paths import project_root


MAX_PROJECT_CONTEXT_BYTES = 16 * 1024


class ProjectContextError(ValueError):
    """A configured project context cannot be safely supplied to an Agent Run."""


def load_project_context(context_file: str) -> str | None:
    """Read one bounded UTF-8 context snapshot from inside the project root."""

    configured_path = context_file.strip()
    if not configured_path:
        return None

    path = _resolve_context_path(configured_path)
    try:
        if not path.exists():
            return None
        if not path.is_file():
            raise ProjectContextError("Project context path must point to a regular file")
        with path.open("rb") as context_stream:
            content = context_stream.read(MAX_PROJECT_CONTEXT_BYTES + 1)
    except ProjectContextError:
        raise
    except OSError as error:
        raise ProjectContextError("Project context file could not be read") from error

    if len(content) > MAX_PROJECT_CONTEXT_BYTES:
        raise ProjectContextError(
            f"Project context file exceeds the {MAX_PROJECT_CONTEXT_BYTES // 1024} KiB limit"
        )
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ProjectContextError("Project context file must be valid UTF-8") from error
    return text if text.strip() else None


def _resolve_context_path(configured_path: str) -> Path:
    root = project_root().resolve()
    candidate = Path(configured_path)
    if candidate.is_absolute():
        raise ProjectContextError("Project context file must stay inside the project root")
    try:
        resolved = (root / candidate).resolve()
        resolved.relative_to(root)
    except (OSError, ValueError) as error:
        raise ProjectContextError("Project context file must stay inside the project root") from error
    return resolved
