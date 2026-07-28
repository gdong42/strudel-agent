from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.evaluations import (
    EvaluationAssessment,
    EvaluationCheck,
    EvaluationRubricReview,
    EvaluationRunReport,
    EvaluationScenarioError,
    assess_final_result,
    create_human_review,
    evaluation_results_dir,
    execute_scenario,
    evaluations_root,
    list_evaluation_records,
    load_evaluation_scenarios,
    save_evaluation_record,
    scenario_fixture_path,
    summarize_evaluation_records,
)
from app.models import AgentFinalChange, AgentMessage, AgentRunUsage, ModelTurnResult, ToolCall
from tests.fakes import ScriptedAgentProvider


def make_report(scenario_id: str, run_id: str, *, passed: bool) -> EvaluationRunReport:
    assessment = EvaluationAssessment(
        scenarioId=scenario_id,
        status="completed",
        action="apply",
        syntaxValid=passed,
        checks=[EvaluationCheck(id="deterministic", passed=passed, detail="Deterministic check.")],
        passed=passed,
    )
    return EvaluationRunReport(
        scenarioId=scenario_id,
        runId=run_id,
        provider="scripted",
        model="scripted-model",
        status="completed",
        action="apply",
        editorUpdateApplied=False,
        usage=AgentRunUsage(turns=2, elapsedSeconds=1, totalTokens=120),
        tools=[],
        assessment=assessment,
        passed=passed,
    )


def make_review(scenario, *, result: str = "met", quality: int | None = 4, readiness: str = "ready", now: int = 100):
    return create_human_review(
        scenario,
        rubric=[EvaluationRubricReview(criterion=criterion, result=result) for criterion in scenario.expected.review],
        musical_quality=quality,
        performance_readiness=readiness,
        reviewed_at=now,
    )


def test_baseline_evaluation_scenarios_are_loadable_and_cover_core_capabilities() -> None:
    scenarios = load_evaluation_scenarios()
    by_id = {scenario.id: scenario for scenario in scenarios}

    assert set(by_id) == {
        "drums-only-groove",
        "four-on-the-floor-house",
        "brighten-pad-without-mud",
        "noop-existing-house-groove",
        "conflicting-tempo-request",
        "editor-update-reconciliation",
    }
    assert by_id["noop-existing-house-groove"].expected.action == "noop"
    assert by_id["conflicting-tempo-request"].expected.terminal_status == "needs_input"
    assert by_id["editor-update-reconciliation"].editor_update_fixture is not None

    root = evaluations_root()
    for scenario in scenarios:
        source = scenario_fixture_path(root, scenario.source_fixture).read_text(encoding="utf-8")
        for region in [*scenario.expected.must_change_regions, *scenario.expected.must_preserve_regions]:
            assert f"@eval-region:{region}:start" in source
            assert f"@eval-region:{region}:end" in source


def test_evaluation_loader_rejects_duplicate_ids_and_unsafe_fixture_paths(tmp_path: Path) -> None:
    scenarios_dir = tmp_path / "scenarios"
    fixtures_dir = tmp_path / "fixtures"
    scenarios_dir.mkdir()
    fixtures_dir.mkdir()
    (fixtures_dir / "base.strudel.js").write_text('s("bd")', encoding="utf-8")
    scenario = {
        "id": "duplicate",
        "title": "Duplicate",
        "description": "A test scenario.",
        "sourceFixture": "fixtures/base.strudel.js",
        "intent": "Do something.",
        "expected": {
            "terminalStatus": "completed",
            "action": "apply",
            "review": ["Check the result."],
        },
    }
    (scenarios_dir / "one.json").write_text(json.dumps(scenario), encoding="utf-8")
    (scenarios_dir / "two.json").write_text(json.dumps(scenario), encoding="utf-8")

    with pytest.raises(EvaluationScenarioError, match="Duplicate"):
        load_evaluation_scenarios(tmp_path)

    scenario["id"] = "unsafe"
    scenario["sourceFixture"] = "../outside.strudel.js"
    (scenarios_dir / "two.json").write_text(json.dumps(scenario), encoding="utf-8")

    with pytest.raises(EvaluationScenarioError, match="stay inside"):
        load_evaluation_scenarios(tmp_path)


def test_assessment_passes_a_scoped_final_change_and_uses_the_current_fixture() -> None:
    scenario = next(item for item in load_evaluation_scenarios() if item.id == "drums-only-groove")
    root = evaluations_root()
    source = scenario_fixture_path(root, scenario.source_fixture).read_text(encoding="utf-8")
    candidate = source.replace('s("~ hh ~ hh").gain(0.34)', 's("~ hh [~ hh] hh").gain(0.4)')

    assessment = assess_final_result(
        scenario,
        status="completed",
        final_change=AgentFinalChange(
            code=candidate,
            explanation="Added a syncopated hi-hat accent.",
            action="apply",
        ),
    )

    assert assessment.passed is True
    assert assessment.syntax_valid is True
    assert all(check.passed for check in assessment.checks)


def test_assessment_detects_a_preserved_region_that_changed() -> None:
    scenario = next(item for item in load_evaluation_scenarios() if item.id == "drums-only-groove")
    root = evaluations_root()
    source = scenario_fixture_path(root, scenario.source_fixture).read_text(encoding="utf-8")
    candidate = source.replace('s("~ hh ~ hh").gain(0.34)', 's("~ hh [~ hh] hh").gain(0.4)').replace(
        ".gain(0.48)", ".gain(0.7)"
    )

    assessment = assess_final_result(
        scenario,
        status="completed",
        final_change=AgentFinalChange(
            code=candidate,
            explanation="Changed drums and bass.",
            action="apply",
        ),
    )

    checks = {check.id: check for check in assessment.checks}
    assert assessment.passed is False
    assert checks["region:bass:preserved"].passed is False


def test_assessment_handles_noop_and_clarification_outcomes() -> None:
    scenarios = {item.id: item for item in load_evaluation_scenarios()}
    root = evaluations_root()
    noop = scenarios["noop-existing-house-groove"]
    source = scenario_fixture_path(root, noop.source_fixture).read_text(encoding="utf-8")

    noop_assessment = assess_final_result(
        noop,
        status="completed",
        final_change=AgentFinalChange(code=source, explanation="No change was needed.", action="noop"),
    )
    clarification_assessment = assess_final_result(
        scenarios["conflicting-tempo-request"],
        status="needs_input",
        final_change=None,
    )

    assert noop_assessment.passed is True
    assert clarification_assessment.passed is True
    assert clarification_assessment.syntax_valid is None


def test_assessment_records_validation_failure_without_including_candidate_code() -> None:
    scenario = next(item for item in load_evaluation_scenarios() if item.id == "drums-only-groove")
    candidate = 'eval("bad")'

    assessment = assess_final_result(
        scenario,
        status="completed",
        final_change=AgentFinalChange(code=candidate, explanation="Unsafe change.", action="apply"),
    )

    assert assessment.syntax_valid is False
    assert assessment.passed is False
    assert candidate not in assessment.model_dump_json()


def test_human_review_must_use_the_scenario_rubric_in_its_original_order() -> None:
    scenario = next(item for item in load_evaluation_scenarios() if item.id == "drums-only-groove")
    review = make_review(scenario, now=123)

    assert review.scenario_id == scenario.id
    assert review.reviewed_at == 123
    assert [item.criterion for item in review.rubric] == scenario.expected.review

    with pytest.raises(EvaluationScenarioError, match="exactly match"):
        create_human_review(
            scenario,
            rubric=[EvaluationRubricReview(criterion=scenario.expected.review[0], result="met")],
            musical_quality=4,
            performance_readiness="ready",
            reviewed_at=124,
        )


def test_reviewed_evaluation_records_are_safe_append_only_files(tmp_path: Path) -> None:
    scenario = next(item for item in load_evaluation_scenarios() if item.id == "drums-only-groove")
    private_candidate = 's("PRIVATE candidate code")'
    report = make_report(scenario.id, "run-1", passed=True)
    first = save_evaluation_record(
        scenario,
        report,
        make_review(scenario, now=101),
        root=tmp_path,
        now=101,
    )
    second = save_evaluation_record(
        scenario,
        make_report(scenario.id, "run-2", passed=False),
        make_review(scenario, result="partial", quality=3, readiness="needs_work", now=102),
        root=tmp_path,
        now=102,
    )

    results_dir = evaluation_results_dir(tmp_path)
    serialized = "\n".join(path.read_text(encoding="utf-8") for path in results_dir.glob("*.json"))

    assert [record.id for record in list_evaluation_records(tmp_path)] == [first.id, second.id]
    assert len(list(results_dir.glob("*.json"))) == 2
    assert private_candidate not in serialized
    assert "candidateCode" not in serialized
    assert "notes" not in serialized


def test_reviewed_evaluation_record_rejects_a_report_for_another_scenario(tmp_path: Path) -> None:
    scenarios = {item.id: item for item in load_evaluation_scenarios()}
    drums = scenarios["drums-only-groove"]
    house = scenarios["four-on-the-floor-house"]

    with pytest.raises(EvaluationScenarioError, match="supplied scenario"):
        save_evaluation_record(
            drums,
            make_report(house.id, "run-1", passed=True),
            make_review(drums),
            root=tmp_path,
            now=100,
        )


def test_evaluation_summary_uses_only_the_latest_result_for_each_scenario(tmp_path: Path) -> None:
    scenarios = {item.id: item for item in load_evaluation_scenarios()}
    drums = scenarios["drums-only-groove"]
    house = scenarios["four-on-the-floor-house"]
    records = [
        save_evaluation_record(
            drums,
            make_report(drums.id, "run-1", passed=True),
            make_review(drums, quality=4, readiness="ready", now=100),
            root=tmp_path,
            now=100,
        ),
        save_evaluation_record(
            drums,
            make_report(drums.id, "run-2", passed=False),
            make_review(drums, result="partial", quality=3, readiness="needs_work", now=200),
            root=tmp_path,
            now=200,
        ),
        save_evaluation_record(
            house,
            make_report(house.id, "run-3", passed=True),
            make_review(house, result="not_met", quality=2, readiness="ready", now=150),
            root=tmp_path,
            now=150,
        ),
    ]

    summary = summarize_evaluation_records(records)

    assert summary.total_records == 3
    assert summary.scenario_count == 2
    assert summary.deterministic_passed == 1
    assert summary.human_reviewed == 2
    assert summary.rubric_partial == len(drums.expected.review)
    assert summary.rubric_not_met == len(house.expected.review)
    assert summary.rubric_met == 0
    assert summary.performance_ready == 1
    assert summary.average_musical_quality == 2.5


@pytest.mark.anyio
async def test_execute_scenario_records_safe_tool_and_loop_observations() -> None:
    scenario = next(item for item in load_evaluation_scenarios() if item.id == "drums-only-groove")
    root = evaluations_root()
    source = scenario_fixture_path(root, scenario.source_fixture).read_text(encoding="utf-8")
    candidate = source.replace('s("~ hh ~ hh").gain(0.34)', 's("~ hh [~ hh] hh").gain(0.4)')
    provider = ScriptedAgentProvider(
        [
            ModelTurnResult(
                assistantMessage=AgentMessage(
                    role="assistant",
                    toolCalls=[
                        ToolCall(
                            id="inspect-1",
                            name="inspect_diff",
                            arguments={"baseCode": source, "candidateCode": candidate},
                        )
                    ],
                )
            ),
            ModelTurnResult(
                assistantMessage=AgentMessage(
                    role="assistant",
                    toolCalls=[
                        ToolCall(
                            id="final-1",
                            name="finalize_change",
                            arguments={
                                "code": candidate,
                                "explanation": "Added a syncopated hi-hat accent.",
                                "action": "apply",
                                "warnings": [],
                            },
                        )
                    ],
                )
            ),
        ]
    )

    report = await execute_scenario(
        scenario,
        provider=provider,
        provider_name="scripted",
        model="scripted-model",
    )

    assert report.passed is True
    assert report.status == "completed"
    assert report.usage.turns == 2
    assert [(tool.name, tool.status) for tool in report.tools] == [
        ("inspect_diff", "ok"),
        ("finalize_change", "ok"),
    ]
    assert candidate not in report.model_dump_json()


@pytest.mark.anyio
async def test_execute_scenario_reconciles_against_its_editor_update_fixture() -> None:
    scenario = next(item for item in load_evaluation_scenarios() if item.id == "editor-update-reconciliation")
    root = evaluations_root()
    latest = scenario_fixture_path(root, scenario.editor_update_fixture or "").read_text(encoding="utf-8")
    candidate = latest.replace('s("~ hh ~ hh").gain(0.34)', 's("~ hh [~ hh] hh").gain(0.4)')
    provider = ScriptedAgentProvider(
        [
            ModelTurnResult(
                assistantMessage=AgentMessage(
                    role="assistant",
                    toolCalls=[
                        ToolCall(
                            id="final-1",
                            name="finalize_change",
                            arguments={
                                "code": candidate,
                                "explanation": "Added drum energy while preserving the bass edit.",
                                "action": "apply",
                                "warnings": [],
                            },
                        )
                    ],
                )
            )
        ]
    )

    report = await execute_scenario(
        scenario,
        provider=provider,
        provider_name="scripted",
        model="scripted-model",
    )

    assert report.passed is True
    assert report.editor_update_applied is True
    assert report.status == "completed"


@pytest.mark.anyio
async def test_execute_scenario_records_a_safe_clarification_outcome() -> None:
    scenario = next(item for item in load_evaluation_scenarios() if item.id == "conflicting-tempo-request")
    provider = ScriptedAgentProvider(
        [
            ModelTurnResult(
                assistantMessage=AgentMessage(
                    role="assistant",
                    toolCalls=[
                        ToolCall(
                            id="input-1",
                            name="request_user_input",
                            arguments={
                                "questionId": "tempo",
                                "question": "Should the tempo change or stay at 124 BPM?",
                                "options": [],
                                "reason": "PRIVATE tempo ambiguity analysis",
                            },
                        )
                    ],
                )
            )
        ]
    )

    report = await execute_scenario(
        scenario,
        provider=provider,
        provider_name="scripted",
        model="scripted-model",
    )

    assert report.passed is True
    assert report.status == "needs_input"
    assert [(tool.name, tool.status) for tool in report.tools] == [("request_user_input", "ok")]
    assert "PRIVATE tempo ambiguity analysis" not in report.model_dump_json()
