from __future__ import annotations

import difflib
import re
from collections.abc import Callable
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ..models import AgentFinalChange, RequestUserInput, ToolCall, ToolDefinition, ToolResult
from ..samples import LoadedSampleRegistry, SampleRegistryError, declared_samples, load_sample_registry
from ..strudel_docs import StrudelDocsError, StrudelKnowledgeBase, load_strudel_knowledge
from ..strudel_validation import StrudelValidatorUnavailable, validate_strudel_code


class InspectDiffArguments(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    base_code: str = Field(alias="baseCode")
    candidate_code: str = Field(alias="candidateCode")


class ValidateCandidateArguments(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    candidate_code: str = Field(alias="candidateCode")


class LookupSamplesArguments(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    query: str = ""
    tags: list[str] = Field(default_factory=list)
    limit: int = Field(default=20, ge=1, le=50)


class LookupStrudelDocsArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=300)
    topics: list[str] = Field(default_factory=list, max_length=8)
    symbols: list[str] = Field(default_factory=list, max_length=12)
    limit: int = Field(default=5, ge=1, le=8)


class InspectSampleUsageArguments(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    base_code: str = Field(alias="baseCode")
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
_DIRECT_SOUND_CALL = re.compile(
    r"(?<![\w.])(?:s|sound)\s*\(\s*(?:\"((?:\\.|[^\"\\])*)\"|'((?:\\.|[^'\\])*)')",
    re.DOTALL,
)
_SOUND_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_-]*")
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

    def __init__(
        self,
        *,
        sample_registry_loader: Callable[[], LoadedSampleRegistry] = load_sample_registry,
        strudel_knowledge_loader: Callable[[], StrudelKnowledgeBase] = load_strudel_knowledge,
        candidate_validator: Callable[[str], list[dict[str, Any]]] = validate_strudel_code,
    ) -> None:
        self._sample_registry_loader = sample_registry_loader
        self._strudel_knowledge_loader = strudel_knowledge_loader
        self._candidate_validator = candidate_validator
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
                description=(
                    "Statically validate candidate code with the pinned JavaScript and Strudel Mini Notation parsers, "
                    "plus runtime safety checks. This does not execute or play the candidate."
                ),
                inputSchema={
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {"candidateCode": {"type": "string"}},
                    "required": ["candidateCode"],
                },
            ),
            "lookup_strudel_docs": ToolDefinition(
                name="lookup_strudel_docs",
                description=(
                    "Search the pinned offline Strudel manual and function reference. "
                    "Use focused English terms and include exact API names in symbols when known."
                ),
                inputSchema={
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "query": {"type": "string", "minLength": 1, "maxLength": 300},
                        "topics": {
                            "type": "array",
                            "items": {"type": "string"},
                            "maxItems": 8,
                        },
                        "symbols": {
                            "type": "array",
                            "items": {"type": "string"},
                            "maxItems": 12,
                        },
                        "limit": {"type": "integer", "minimum": 1, "maximum": 8},
                    },
                    "required": ["query", "topics", "symbols", "limit"],
                },
            ),
            "lookup_samples": ToolDefinition(
                name="lookup_samples",
                description="List project-declared sound names from the optional local sample registry. Use an empty query and tag list to list the first matching names.",
                inputSchema={
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "query": {"type": "string"},
                        "tags": {"type": "array", "items": {"type": "string"}},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 50},
                    },
                    "required": ["query", "tags", "limit"],
                },
            ),
            "inspect_sample_usage": ToolDefinition(
                name="inspect_sample_usage",
                description="Compare direct s()/sound() names in base and candidate code against the project sample registry. It reports only newly introduced undeclared names.",
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
            "lookup_strudel_docs": self._lookup_strudel_docs,
            "lookup_samples": self._lookup_samples,
            "inspect_sample_usage": self._inspect_sample_usage,
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
        errors: list[dict[str, Any]] = []
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
        if code.strip():
            try:
                errors.extend(self._candidate_validator(code))
            except StrudelValidatorUnavailable:
                errors.append(
                    {
                        "code": "validator_unavailable",
                        "message": "The pinned local Strudel syntax validator could not run.",
                    }
                )
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

    def _lookup_samples(self, call: ToolCall) -> ToolResult:
        arguments = LookupSamplesArguments.model_validate(call.arguments)
        try:
            registry = self._sample_registry_loader()
        except SampleRegistryError:
            return self._sample_registry_error(call)
        if not registry.configured:
            return self._result(call, "ok", {"registryConfigured": False, "total": 0, "sounds": []})

        query = arguments.query.strip().casefold()
        requested_tags = {tag.strip().casefold() for tag in arguments.tags if tag.strip()}
        matches = [
            sound
            for sound in declared_samples(registry)
            if _sample_matches(sound.name, sound.tags, sound.description, query, requested_tags)
        ]
        return self._result(
            call,
            "ok",
            {
                "registryConfigured": True,
                "total": len(matches),
                "sounds": [
                    {"name": sound.name, "tags": sound.tags, "description": sound.description}
                    for sound in matches[: arguments.limit]
                ],
            },
        )

    def _lookup_strudel_docs(self, call: ToolCall) -> ToolResult:
        arguments = LookupStrudelDocsArguments.model_validate(call.arguments)
        try:
            knowledge = self._strudel_knowledge_loader()
        except StrudelDocsError:
            return self._result(
                call,
                "recoverable_error",
                {
                    "error": {
                        "code": "strudel_docs_unavailable",
                        "message": "The pinned local Strudel manual could not be read.",
                    }
                },
            )
        return self._result(
            call,
            "ok",
            knowledge.search(
                arguments.query,
                topics=arguments.topics,
                symbols=arguments.symbols,
                limit=arguments.limit,
            ),
        )

    def _inspect_sample_usage(self, call: ToolCall) -> ToolResult:
        arguments = InspectSampleUsageArguments.model_validate(call.arguments)
        try:
            registry = self._sample_registry_loader()
        except SampleRegistryError:
            return self._sample_registry_error(call)

        base_sounds = _direct_sound_names(arguments.base_code)
        candidate_sounds = _direct_sound_names(arguments.candidate_code)
        introduced_sounds = sorted(candidate_sounds - base_sounds, key=str.casefold)
        declared_names = {sound.name.casefold() for sound in declared_samples(registry)}
        declared_introduced = [sound for sound in introduced_sounds if sound.casefold() in declared_names]
        undeclared_introduced = [sound for sound in introduced_sounds if sound.casefold() not in declared_names]
        return self._result(
            call,
            "ok",
            {
                "registryConfigured": registry.configured,
                "baseSounds": sorted(base_sounds, key=str.casefold),
                "candidateSounds": sorted(candidate_sounds, key=str.casefold),
                "introducedSounds": introduced_sounds,
                "declaredIntroducedSounds": declared_introduced if registry.configured else [],
                "undeclaredIntroducedSounds": undeclared_introduced if registry.configured else [],
            },
        )

    def _finalize_change(self, call: ToolCall) -> ToolResult:
        arguments = FinalizeChangeArguments.model_validate(call.arguments)
        final_change = arguments.to_final_change()
        return self._result(call, "ok", {"finalChange": final_change.model_dump(by_alias=True)})

    def _request_user_input(self, call: ToolCall) -> ToolResult:
        request = RequestUserInput.model_validate(call.arguments)
        return self._result(call, "ok", {"request": request.model_dump(by_alias=True)})

    @classmethod
    def _sample_registry_error(cls, call: ToolCall) -> ToolResult:
        return cls._result(
            call,
            "recoverable_error",
            {
                "error": {
                    "code": "sample_registry_unavailable",
                    "message": "The local sample registry could not be read.",
                }
            },
        )

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


def _direct_sound_names(code: str) -> set[str]:
    values = [match.group(1) or match.group(2) for match in _DIRECT_SOUND_CALL.finditer(code)]
    return {name for value in values for name in _SOUND_NAME.findall(value)}


def _sample_matches(
    name: str,
    tags: list[str],
    description: str | None,
    query: str,
    requested_tags: set[str],
) -> bool:
    searchable = " ".join((name, *tags, description or "")).casefold()
    if query and query not in searchable:
        return False
    return requested_tags.issubset({tag.casefold() for tag in tags})
