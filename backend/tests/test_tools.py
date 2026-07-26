from __future__ import annotations

from app.models import ToolCall
from app.tools import ToolRegistry


def test_registry_exposes_strict_runtime_tool_schemas() -> None:
    definitions = ToolRegistry().definitions()

    assert [definition.name for definition in definitions] == [
        "inspect_diff",
        "validate_candidate",
        "finalize_change",
        "request_user_input",
    ]
    assert all(definition.input_schema["additionalProperties"] is False for definition in definitions)
    assert definitions[2].input_schema["required"] == ["code", "explanation", "action", "warnings"]


def test_inspect_diff_returns_deterministic_line_summary() -> None:
    result = ToolRegistry().execute(
        ToolCall(
            id="call-1",
            name="inspect_diff",
            arguments={"baseCode": 's("bd")', "candidateCode": 's("bd*4")\ns("hh")'},
        )
    )

    assert result.status == "ok"
    assert result.output["changed"] is True
    assert result.output["addedLines"] == 2
    assert result.output["removedLines"] == 1
    assert '+s("hh")' in result.output["unifiedDiff"]


def test_validate_candidate_returns_recoverable_errors_and_mini_notation_warning() -> None:
    result = ToolRegistry().execute(
        ToolCall(
            id="call-1",
            name="validate_candidate",
            arguments={"candidateCode": "eval('bad')\ns('bd hh')\n("},
        )
    )

    assert result.status == "recoverable_error"
    assert result.output["valid"] is False
    assert {error["code"] for error in result.output["errors"]} == {
        "dynamic_execution",
        "unbalanced_delimiters",
    }
    assert result.output["warnings"] == [{
        "level": "warn",
        "category": "mini-notation",
        "message": "Pattern-like mini-notation should use double quotes or backticks, not single quotes.",
    }]


def test_finalize_change_returns_normalized_internal_final_change() -> None:
    result = ToolRegistry().execute(
        ToolCall(
            id="call-1",
            name="finalize_change",
            arguments={
                "code": 's("bd*4")',
                "explanation": "Added a four-on-the-floor kick.",
                "action": "apply",
                "warnings": [],
            },
        )
    )

    assert result.status == "ok"
    assert result.output == {
        "finalChange": {
            "code": 's("bd*4")',
            "explanation": "Added a four-on-the-floor kick.",
            "action": "apply",
            "warnings": [],
            "ranges": None,
        }
    }


def test_request_user_input_keeps_reason_in_internal_tool_result() -> None:
    result = ToolRegistry().execute(
        ToolCall(
            id="call-1",
            name="request_user_input",
            arguments={
                "questionId": "tempo",
                "question": "Should the tempo stay at 124 BPM?",
                "options": [{"id": "keep", "label": "Keep 124 BPM"}],
                "reason": "The request conflicts with the current arrangement.",
            },
        )
    )

    assert result.status == "ok"
    assert result.output["request"]["reason"] == "The request conflicts with the current arrangement."


def test_invalid_or_unknown_tools_never_raise_from_the_registry() -> None:
    registry = ToolRegistry()

    invalid = registry.execute(ToolCall(id="call-1", name="finalize_change", arguments={"code": 's("bd")'}))
    invalid_warning = registry.execute(
        ToolCall(
            id="call-2",
            name="finalize_change",
            arguments={
                "code": 's("bd")',
                "explanation": "Added a kick.",
                "action": "apply",
                "warnings": [{"level": "warn", "message": "Check this.", "category": "sample", "extra": "no"}],
            },
        )
    )
    unknown = registry.execute(ToolCall(id="call-2", name="does_not_exist", arguments={}))

    assert invalid.status == "recoverable_error"
    assert invalid.output["error"]["code"] == "invalid_arguments"
    assert invalid_warning.status == "recoverable_error"
    assert unknown.status == "fatal_error"
    assert unknown.output["error"]["code"] == "unknown_tool"
