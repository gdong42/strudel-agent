from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any


_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_VALIDATOR_SCRIPT = _REPOSITORY_ROOT / "scripts" / "validate_strudel.mjs"
_MAX_CODE_BYTES = 256_000
_MAX_OUTPUT_BYTES = 64_000
_VALIDATOR_TIMEOUT_SECONDS = 3
_ISSUE_CODES = {"javascript_syntax", "mini_notation_syntax", "invalid_final_expression"}


class StrudelValidatorUnavailable(RuntimeError):
    """The local static validator could not run or returned an invalid result."""


@dataclass(frozen=True)
class StrudelValidationIssue:
    code: str
    message: str
    line: int
    column: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "line": self.line,
            "column": self.column,
        }


def validate_strudel_code(code: str) -> list[dict[str, Any]]:
    if len(code.encode("utf-8")) > _MAX_CODE_BYTES:
        return [
            {
                "code": "candidate_too_large",
                "message": "Candidate code exceeds the static validation size limit.",
                "line": 1,
                "column": 1,
            }
        ]
    return [issue.to_dict() for issue in _validate_cached(code)]


@lru_cache(maxsize=128)
def _validate_cached(code: str) -> tuple[StrudelValidationIssue, ...]:
    try:
        completed = subprocess.run(
            ["node", str(_VALIDATOR_SCRIPT)],
            input=json.dumps({"code": code}, separators=(",", ":")),
            capture_output=True,
            text=True,
            timeout=_VALIDATOR_TIMEOUT_SECONDS,
            cwd=_REPOSITORY_ROOT,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise StrudelValidatorUnavailable("The local Strudel validator could not start.") from error

    output = completed.stdout.encode("utf-8")
    if completed.returncode != 0 or not output or len(output) > _MAX_OUTPUT_BYTES:
        raise StrudelValidatorUnavailable("The local Strudel validator did not complete successfully.")
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise StrudelValidatorUnavailable("The local Strudel validator returned malformed output.") from error
    issues = payload.get("issues") if isinstance(payload, dict) else None
    if not isinstance(issues, list):
        raise StrudelValidatorUnavailable("The local Strudel validator returned an invalid result.")
    try:
        return tuple(_parse_issue(issue) for issue in issues)
    except (KeyError, TypeError, ValueError) as error:
        raise StrudelValidatorUnavailable("The local Strudel validator returned an invalid issue.") from error


def _parse_issue(value: Any) -> StrudelValidationIssue:
    if not isinstance(value, dict):
        raise TypeError("Validation issues must be objects")
    code = value["code"]
    message = value["message"]
    line = value["line"]
    column = value["column"]
    if code not in _ISSUE_CODES:
        raise ValueError("Unknown validation issue code")
    if not isinstance(message, str) or not message or len(message) > 500:
        raise ValueError("Invalid validation issue message")
    if not isinstance(line, int) or isinstance(line, bool) or line < 1:
        raise ValueError("Invalid validation issue line")
    if not isinstance(column, int) or isinstance(column, bool) or column < 1:
        raise ValueError("Invalid validation issue column")
    return StrudelValidationIssue(code=code, message=message, line=line, column=column)
