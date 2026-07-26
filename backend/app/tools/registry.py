from __future__ import annotations

import difflib
import re
from collections.abc import Callable
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ..models import AgentFinalChange, RequestUserInput, ToolCall, ToolDefinition, ToolResult


class InspectDiffArguments(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    base_code: str = Field(alias="baseCode")
    candidate_code: str = Field(alias="candidateCode")


class ValidateCandidateArguments(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    candidate_code: str = Field(alias="candidateCode")


class FinalizeWarning(BaseModel):
    model_config = ConfigDict(extra="forbid")

    level: Literal["info", "warn", "risk"]
    message: str
    category: Literal["sample", "visual", "structure", "performance", "mini-notation"]


class FinalizeChangeArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    explanation: str
    action: Literal["apply", "noop"]
    warnings: list[FinalizeWarning]

    def to_final_change(self) -> AgentFinalChange:
        return AgentFinalChange(
            code=self.code,
            explanation=self.explanation,
            action=self.action,
            warnings=[warning.model_dump() for warning in self.warnings],
        )


ToolHandler = Callable[[ToolCall], ToolResult]

_SINGLE_QUOTED_PATTERN_CALL = re.compile(r"\b(?:s|sound|note|n)\(\s*'[^']*(?:[<>\[\]~*]|bd|sd|hh|cp)[^']*'\s*\)")
_DYNAMIC_EXECUTION = re.compile(r"\b(?:eval|Function)\s*\(")
_OPENING_DELIMITERS = {"(": ")", "[": "]", "{": "}"}
_CLOSING_DELIMITERS = {value: key for key, value in _OPENING_DELIMITERS.items()}
_WARNING_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "level": {"type": "string", "enum": ["info", "warn", "risk"]},
        "message": {"type": "string"},
        "category": {
            "type": "string",
            "enum": ["sample", "visual", "structure", "performance", "mini-notation"],
        },
    },
    "required": ["level", "message", "category"],
}
_QUESTION_OPTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "id": {"type": "string"},
        "label": {"type": "string"},
        "description": {"anyOf": [{"type": "string"}, {"type": "null"}]},
    },
    "required": ["id", "label", "description"],
}


class ToolRegistry:
    """Deterministic runtime tools. Their results remain internal to an Agent Run."""

    def __init__(self) -> None:
        self._definitions = {
            "inspect_diff": ToolDefinition(
                name="inspect_diff",
                description="Return a deterministic line diff between base and candidate Strudel code.",
                inputSchema={
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "baseCode": {"type": "string"},
                        "candidateCode": {"type": "string"},
                    },
                    "required": ["baseCode", "candidateCode"],
                },
            ),
            "validate_candidate": ToolDefinition(
                name="validate_candidate",
                description="Check candidate Strudel code for empty content, dynamic execution, delimiter balance, and mini-notation warnings.",
                inputSchema={
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {"candidateCode": {"type": "string"}},
                    "required": ["candidateCode"],
                },
            ),
            "finalize_change": ToolDefinition(
                name="finalize_change",
                description="Request deterministic finalization of a complete Strudel code replacement.",
                inputSchema={
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "code": {"type": "string"},
                        "explanation": {"type": "string"},
                        "action": {"type": "string", "enum": ["apply", "noop"]},
                        "warnings": {"type": "array", "items": _WARNING_SCHEMA},
                    },
                    "required": ["code", "explanation", "action", "warnings"],
                },
            ),
            "request_user_input": ToolDefinition(
                name="request_user_input",
                description="Pause only to ask the performer one material clarification or creative decision.",
                inputSchema={
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "questionId": {"type": "string"},
                        "question": {"type": "string"},
                        "options": {"type": "array", "items": _QUESTION_OPTION_SCHEMA},
                        "reason": {"type": "string"},
                    },
                    "required": ["questionId", "question", "options", "reason"],
                },
            ),
        }
        self._handlers: dict[str, ToolHandler] = {
            "inspect_diff": self._inspect_diff,
            "validate_candidate": self._validate_candidate,
            "finalize_change": self._finalize_change,
            "request_user_input": self._request_user_input,
        }

    def definitions(self) -> list[ToolDefinition]:
        return [definition.model_copy(deep=True) for definition in self._definitions.values()]

    def execute(self, call: ToolCall) -> ToolResult:
        handler = self._handlers.get(call.name)
        if not handler:
            return self._result(
                call,
                "fatal_error",
                {"error": {"code": "unknown_tool", "message": "The requested tool is not registered."}},
            )
        try:
            return handler(call)
        except ValidationError:
            return self._result(
                call,
                "recoverable_error",
                {"error": {"code": "invalid_arguments", "message": "Tool arguments do not match the required schema."}},
            )
        except Exception:
            return self._result(
                call,
                "fatal_error",
                {"error": {"code": "tool_execution_failed", "message": "The tool could not complete."}},
            )

    def _inspect_diff(self, call: ToolCall) -> ToolResult:
        arguments = InspectDiffArguments.model_validate(call.arguments)
        diff_lines = list(
            difflib.unified_diff(
                arguments.base_code.splitlines(),
                arguments.candidate_code.splitlines(),
                fromfile="base",
                tofile="candidate",
                lineterm="",
            )
        )
        added_lines = sum(1 for line in diff_lines if line.startswith("+") and not line.startswith("+++"))
        removed_lines = sum(1 for line in diff_lines if line.startswith("-") and not line.startswith("---"))
        return self._result(
            call,
            "ok",
            {
                "changed": arguments.base_code != arguments.candidate_code,
                "addedLines": added_lines,
                "removedLines": removed_lines,
                "unifiedDiff": "\n".join(diff_lines),
            },
        )

    def _validate_candidate(self, call: ToolCall) -> ToolResult:
        arguments = ValidateCandidateArguments.model_validate(call.arguments)
        code = arguments.candidate_code
        errors: list[dict[str, str]] = []
        warnings: list[dict[str, str]] = []
        if not code.strip():
            errors.append({"code": "empty_code", "message": "Candidate code is empty."})

        executable_code = _strip_literals_and_comments(code)
        if _DYNAMIC_EXECUTION.search(executable_code):
            errors.append(
                {
                    "code": "dynamic_execution",
                    "message": "Candidate code uses eval() or Function(), which is not allowed.",
                }
            )
        delimiter_error = _delimiter_error(executable_code)
        if delimiter_error:
            errors.append({"code": "unbalanced_delimiters", "message": delimiter_error})
        if _SINGLE_QUOTED_PATTERN_CALL.search(code):
            warnings.append(
                {
                    "level": "warn",
                    "category": "mini-notation",
                    "message": "Pattern-like mini-notation should use double quotes or backticks, not single quotes.",
                }
            )
        return self._result(
            call,
            "ok" if not errors else "recoverable_error",
            {"valid": not errors, "errors": errors, "warnings": warnings},
        )

    def _finalize_change(self, call: ToolCall) -> ToolResult:
        arguments = FinalizeChangeArguments.model_validate(call.arguments)
        final_change = arguments.to_final_change()
        return self._result(call, "ok", {"finalChange": final_change.model_dump(by_alias=True)})

    def _request_user_input(self, call: ToolCall) -> ToolResult:
        request = RequestUserInput.model_validate(call.arguments)
        return self._result(call, "ok", {"request": request.model_dump(by_alias=True)})

    @staticmethod
    def _result(
        call: ToolCall,
        status: Literal["ok", "recoverable_error", "fatal_error"],
        output: dict[str, Any],
    ) -> ToolResult:
        return ToolResult(callId=call.id, name=call.name, status=status, output=output)


def _strip_literals_and_comments(code: str) -> str:
    result: list[str] = []
    index = 0
    length = len(code)
    while index < length:
        current = code[index]
        following = code[index + 1] if index + 1 < length else ""
        if current == "/" and following == "/":
            result.extend(" " for _ in range(2))
            index += 2
            while index < length and code[index] not in "\r\n":
                result.append(" ")
                index += 1
            continue
        if current == "/" and following == "*":
            result.extend(" " for _ in range(2))
            index += 2
            while index < length:
                if code[index] == "*" and index + 1 < length and code[index + 1] == "/":
                    result.extend(" " for _ in range(2))
                    index += 2
                    break
                result.append("\n" if code[index] == "\n" else " ")
                index += 1
            continue
        if current in {'"', "'", "`"}:
            quote = current
            result.append(" ")
            index += 1
            while index < length:
                character = code[index]
                if character == "\\":
                    result.append(" ")
                    index += 1
                    if index < length:
                        result.append("\n" if code[index] == "\n" else " ")
                        index += 1
                    continue
                result.append("\n" if character == "\n" else " ")
                index += 1
                if character == quote:
                    break
            continue
        result.append(current)
        index += 1
    return "".join(result)


def _delimiter_error(code: str) -> str | None:
    stack: list[tuple[str, int]] = []
    for index, character in enumerate(code):
        if character in _OPENING_DELIMITERS:
            stack.append((character, index))
        elif character in _CLOSING_DELIMITERS:
            if not stack or stack[-1][0] != _CLOSING_DELIMITERS[character]:
                return f"Unexpected '{character}' at character {index}."
            stack.pop()
    if stack:
        character, index = stack[-1]
        return f"Unclosed '{character}' at character {index}."
    return None
