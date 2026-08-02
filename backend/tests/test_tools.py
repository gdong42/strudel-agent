from __future__ import annotations

from app.models import ToolCall
from app.samples import DeclaredSample, LoadedSampleRegistry, SampleRegistry, SampleRegistryError
from app.strudel_docs import StrudelDocsError
from app.strudel_validation import StrudelValidatorUnavailable
from app.tools import ToolRegistry


def configured_sample_registry() -> LoadedSampleRegistry:
    return LoadedSampleRegistry(
        configured=True,
        registry=SampleRegistry(
            version=1,
            sounds=[
                DeclaredSample(name="house_kick", tags=["drum", "kick", "house"]),
                DeclaredSample(name="house_hat", tags=["drum", "hat", "house"]),
            ],
        ),
    )


def test_registry_exposes_strict_runtime_tool_schemas() -> None:
    definitions = ToolRegistry().definitions()

    assert [definition.name for definition in definitions] == [
        "inspect_diff",
        "validate_candidate",
        "lookup_strudel_docs",
        "lookup_samples",
        "inspect_sample_usage",
        "finalize_change",
        "request_user_input",
    ]
    assert all(definition.input_schema["additionalProperties"] is False for definition in definitions)
    assert definitions[5].input_schema["required"] == ["code", "explanation", "action", "warnings"]


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
        "javascript_syntax",
    }
    assert result.output["warnings"] == [{
        "level": "warn",
        "category": "mini-notation",
        "message": "Pattern-like mini-notation should use double quotes or backticks, not single quotes.",
    }]


def test_validate_candidate_uses_the_pinned_mini_notation_parser() -> None:
    result = ToolRegistry().execute(
        ToolCall(
            id="call-1",
            name="validate_candidate",
            arguments={"candidateCode": 's("bd*4,")'},
        )
    )

    assert result.status == "recoverable_error"
    assert result.output["valid"] is False
    assert result.output["errors"][0]["code"] == "mini_notation_syntax"
    assert result.output["errors"][0]["line"] == 1
    assert result.output["errors"][0]["column"] == 9


def test_validate_candidate_blocks_finalization_when_the_static_validator_is_unavailable() -> None:
    def unavailable_validator(_: str):
        raise StrudelValidatorUnavailable("missing node")

    result = ToolRegistry(candidate_validator=unavailable_validator).execute(
        ToolCall(
            id="call-1",
            name="validate_candidate",
            arguments={"candidateCode": 's("bd*4")'},
        )
    )

    assert result.status == "recoverable_error"
    assert result.output["valid"] is False
    assert result.output["errors"] == [
        {
            "code": "validator_unavailable",
            "message": "The pinned local Strudel syntax validator could not run.",
        }
    ]


def test_lookup_samples_filters_a_declared_local_registry() -> None:
    registry = ToolRegistry(sample_registry_loader=configured_sample_registry)

    result = registry.execute(
        ToolCall(
            id="call-1",
            name="lookup_samples",
            arguments={"query": "house", "tags": ["drum"], "limit": 1},
        )
    )

    assert result.status == "ok"
    assert result.output == {
        "registryConfigured": True,
        "total": 2,
        "sounds": [{"name": "house_hat", "tags": ["drum", "hat", "house"], "description": None}],
    }


def test_lookup_strudel_docs_returns_pinned_offline_reference_results() -> None:
    result = ToolRegistry().execute(
        ToolCall(
            id="docs-1",
            name="lookup_strudel_docs",
            arguments={
                "query": "combine patterns at the same time",
                "topics": ["patterns"],
                "symbols": ["stack"],
                "limit": 2,
            },
        )
    )

    assert result.status == "ok"
    assert result.output["manualVersion"] == "1.3.0"
    assert result.output["results"][0]["id"] == "reference:stack"
    assert "played at the same time" in result.output["results"][0]["content"]


def test_lookup_strudel_docs_reports_a_recoverable_local_package_failure() -> None:
    def unavailable_docs():
        raise StrudelDocsError("bad corpus")

    result = ToolRegistry(strudel_knowledge_loader=unavailable_docs).execute(
        ToolCall(
            id="docs-1",
            name="lookup_strudel_docs",
            arguments={"query": "scope", "topics": [], "symbols": [], "limit": 3},
        )
    )

    assert result.status == "recoverable_error"
    assert result.output["error"]["code"] == "strudel_docs_unavailable"


def test_inspect_sample_usage_reports_only_new_undeclared_direct_sound_names() -> None:
    registry = ToolRegistry(sample_registry_loader=configured_sample_registry)

    result = registry.execute(
        ToolCall(
            id="call-1",
            name="inspect_sample_usage",
            arguments={
                "baseCode": 'stack(s("house_kick"), note("c3").s("sine"))',
                "candidateCode": 'stack(s("house_kick [house_hat room_rim]"), note("c3").s("sine"))',
            },
        )
    )

    assert result.status == "ok"
    assert result.output == {
        "registryConfigured": True,
        "baseSounds": ["house_kick"],
        "candidateSounds": ["house_hat", "house_kick", "room_rim"],
        "introducedSounds": ["house_hat", "room_rim"],
        "declaredIntroducedSounds": ["house_hat"],
        "undeclaredIntroducedSounds": ["room_rim"],
    }


def test_inspect_sample_usage_remains_non_blocking_when_no_registry_is_configured() -> None:
    registry = ToolRegistry(
        sample_registry_loader=lambda: LoadedSampleRegistry(configured=False, registry=SampleRegistry(version=1))
    )

    result = registry.execute(
        ToolCall(
            id="call-1",
            name="inspect_sample_usage",
            arguments={"baseCode": 's("bd")', "candidateCode": 's("bd room_rim")'},
        )
    )

    assert result.status == "ok"
    assert result.output["registryConfigured"] is False
    assert result.output["introducedSounds"] == ["room_rim"]
    assert result.output["undeclaredIntroducedSounds"] == []


def test_sample_registry_failures_are_recoverable_tool_outcomes() -> None:
    def unavailable_registry() -> LoadedSampleRegistry:
        raise SampleRegistryError("bad registry")

    result = ToolRegistry(sample_registry_loader=unavailable_registry).execute(
        ToolCall(id="call-1", name="lookup_samples", arguments={"query": "", "tags": [], "limit": 20})
    )

    assert result.status == "recoverable_error"
    assert result.output["error"]["code"] == "sample_registry_unavailable"


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
