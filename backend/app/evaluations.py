from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from time import time, time_ns
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .agent_runs import AgentRunManager
from .agent_runtime import build_run_budget
from .config import AgentRuntimeConfig
from .models import (
    AgentFinalChange,
    AgentRunBudget,
    AgentRunStatus,
    AgentRunUsage,
    EditorVersion,
    ToolCall,
    ToolResult,
)
from .paths import project_root
from .providers.base import AgentProvider
from .tools import ToolRegistry


class EvaluationScenarioError(ValueError):
    pass


class EvaluationExpectation(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    terminal_status: Literal["completed", "needs_input"] = Field(alias="terminalStatus")
    action: Literal["apply", "noop"] | None = None
    must_change_regions: list[str] = Field(default_factory=list, alias="mustChangeRegions")
    must_preserve_regions: list[str] = Field(default_factory=list, alias="mustPreserveRegions")
    review: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_terminal_expectation(self) -> "EvaluationExpectation":
        if self.terminal_status == "completed" and self.action is None:
            raise ValueError("Completed evaluation scenarios require an expected action")
        if self.terminal_status == "needs_input" and self.action is not None:
            raise ValueError("Clarification scenarios cannot expect a final action")
        if set(self.must_change_regions) & set(self.must_preserve_regions):
            raise ValueError("A region cannot be both changed and preserved")
        return self


class EvaluationScenario(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    description: str = Field(min_length=1)
    source_fixture: str = Field(alias="sourceFixture", min_length=1)
    project_context_fixture: str | None = Field(default=None, alias="projectContextFixture")
    editor_update_fixture: str | None = Field(default=None, alias="editorUpdateFixture")
    intent: str = Field(min_length=1)
    expected: EvaluationExpectation


class EvaluationCheck(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    id: str = Field(min_length=1)
    passed: bool
    detail: str = Field(min_length=1)


class EvaluationAssessment(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    scenario_id: str = Field(alias="scenarioId")
    status: AgentRunStatus
    action: Literal["apply", "noop"] | None = None
    syntax_valid: bool | None = Field(default=None, alias="syntaxValid")
    validation_errors: list[str] = Field(default_factory=list, alias="validationErrors")
    validation_warnings: list[str] = Field(default_factory=list, alias="validationWarnings")
    checks: list[EvaluationCheck]
    passed: bool


class EvaluationToolObservation(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    name: str = Field(min_length=1)
    status: Literal["ok", "recoverable_error", "fatal_error"]
    error_code: str | None = Field(default=None, alias="errorCode")


class EvaluationRunReport(BaseModel):
    """Safe execution report for one scenario; candidate code stays in the Run only."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    scenario_id: str = Field(alias="scenarioId")
    run_id: str = Field(alias="runId")
    provider: str
    model: str
    status: AgentRunStatus
    action: Literal["apply", "noop"] | None = None
    editor_update_applied: bool = Field(alias="editorUpdateApplied")
    usage: AgentRunUsage
    tools: list[EvaluationToolObservation]
    assessment: EvaluationAssessment
    passed: bool

    @model_validator(mode="after")
    def validate_assessment_scenario(self) -> "EvaluationRunReport":
        if self.assessment.scenario_id != self.scenario_id:
            raise ValueError("Evaluation assessment must belong to the reported scenario")
        return self


HumanReviewResult = Literal["met", "partial", "not_met", "not_applicable"]
PerformanceReadiness = Literal["ready", "needs_work", "not_applicable"]


class EvaluationRubricReview(BaseModel):
    """One human judgment against a version-controlled scenario rubric item."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    criterion: str = Field(min_length=1)
    result: HumanReviewResult


class HumanMusicalReview(BaseModel):
    """Structured human feedback; intentionally no free-text or candidate-code field."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    scenario_id: str = Field(alias="scenarioId", min_length=1)
    reviewed_at: int = Field(alias="reviewedAt", ge=0)
    rubric: list[EvaluationRubricReview] = Field(min_length=1)
    musical_quality: int | None = Field(default=None, alias="musicalQuality", ge=1, le=5)
    performance_readiness: PerformanceReadiness = Field(alias="performanceReadiness")

    @model_validator(mode="after")
    def validate_unique_rubric_criteria(self) -> "HumanMusicalReview":
        criteria = [item.criterion for item in self.rubric]
        if len(set(criteria)) != len(criteria):
            raise ValueError("Human review rubric criteria must be unique")
        return self


class EvaluationRecord(BaseModel):
    """Append-only, code-free evaluation result with its human musical review."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    id: str = Field(min_length=1)
    created_at: int = Field(alias="createdAt", ge=0)
    report: EvaluationRunReport
    review: HumanMusicalReview

    @model_validator(mode="after")
    def validate_scenario_match(self) -> "EvaluationRecord":
        if self.report.scenario_id != self.review.scenario_id:
            raise ValueError("Evaluation report and human review must belong to the same scenario")
        return self


class EvaluationSummary(BaseModel):
    """Latest-result coverage summary; historical records remain available separately."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    total_records: int = Field(alias="totalRecords", ge=0)
    scenario_count: int = Field(alias="scenarioCount", ge=0)
    deterministic_passed: int = Field(alias="deterministicPassed", ge=0)
    human_reviewed: int = Field(alias="humanReviewed", ge=0)
    rubric_met: int = Field(alias="rubricMet", ge=0)
    rubric_partial: int = Field(alias="rubricPartial", ge=0)
    rubric_not_met: int = Field(alias="rubricNotMet", ge=0)
    rubric_not_applicable: int = Field(alias="rubricNotApplicable", ge=0)
    performance_ready: int = Field(alias="performanceReady", ge=0)
    average_musical_quality: float | None = Field(default=None, alias="averageMusicalQuality", ge=1, le=5)


def evaluations_root() -> Path:
    return project_root() / "evals"


def evaluation_results_dir(root: Path | None = None) -> Path:
    return (root or evaluations_root()).resolve() / "results"


def load_evaluation_scenarios(root: Path | None = None) -> list[EvaluationScenario]:
    root = (root or evaluations_root()).resolve()
    scenarios_dir = root / "scenarios"
    if not scenarios_dir.exists():
        raise EvaluationScenarioError("Evaluation scenarios directory is missing")

    scenarios: list[EvaluationScenario] = []
    identifiers: set[str] = set()
    for path in sorted(scenarios_dir.glob("*.json")):
        try:
            scenario = EvaluationScenario.model_validate(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError) as error:
            raise EvaluationScenarioError(f"Could not load evaluation scenario {path.name}") from error
        if scenario.id in identifiers:
            raise EvaluationScenarioError(f"Duplicate evaluation scenario ID: {scenario.id}")
        identifiers.add(scenario.id)
        _validate_fixture(root, scenario.source_fixture, path.name)
        if scenario.project_context_fixture:
            _validate_fixture(root, scenario.project_context_fixture, path.name)
        if scenario.editor_update_fixture:
            _validate_fixture(root, scenario.editor_update_fixture, path.name)
        scenarios.append(scenario)
    if not scenarios:
        raise EvaluationScenarioError("No evaluation scenarios were found")
    return scenarios


def scenario_fixture_path(scenario_root: Path, fixture: str) -> Path:
    candidate = Path(fixture)
    if candidate.is_absolute():
        raise EvaluationScenarioError("Evaluation fixtures must stay inside the evaluation root")
    try:
        resolved = (scenario_root.resolve() / candidate).resolve()
        resolved.relative_to(scenario_root.resolve())
    except (OSError, ValueError) as error:
        raise EvaluationScenarioError("Evaluation fixtures must stay inside the evaluation root") from error
    return resolved


def assess_final_result(
    scenario: EvaluationScenario,
    *,
    status: AgentRunStatus,
    final_change: AgentFinalChange | None,
    scenario_root: Path | None = None,
    tools: ToolRegistry | None = None,
) -> EvaluationAssessment:
    """Assess a public Run outcome without retaining candidate code in the report."""

    root = (scenario_root or evaluations_root()).resolve()
    base_code = _scenario_base_code(root, scenario)
    checks = [
        _check(
            "terminal_status",
            status == scenario.expected.terminal_status,
            f"Expected {scenario.expected.terminal_status}; received {status}.",
        )
    ]
    action = final_change.action if final_change else None
    if scenario.expected.action is not None:
        checks.append(
            _check(
                "final_action",
                action == scenario.expected.action,
                f"Expected {scenario.expected.action}; received {action or 'no final action'}.",
            )
        )

    if status != "completed" or not final_change:
        checks.append(
            _check(
                "final_change_shape",
                final_change is None if status != "completed" else final_change is not None,
                "No final change is available before a completed Run."
                if status != "completed"
                else "A completed Run must include a final change.",
            )
        )
        return _assessment(scenario, status, action, None, [], [], checks)

    validation = (tools or ToolRegistry()).execute(
        ToolCall(
            id=f"evaluation-{scenario.id}",
            name="validate_candidate",
            arguments={"candidateCode": final_change.code},
        )
    )
    validation_output = validation.output
    validation_errors = _validation_messages(validation_output.get("errors"))
    validation_warnings = _validation_messages(validation_output.get("warnings"))
    syntax_valid = validation.status == "ok" and validation_output.get("valid") is True
    checks.append(
        _check(
            "candidate_validation",
            syntax_valid,
            "Candidate passed the current non-performing validation gate."
            if syntax_valid
            else "Candidate failed the current non-performing validation gate.",
        )
    )

    base_regions = _extract_regions(base_code)
    final_regions = _extract_regions(final_change.code)
    for region in scenario.expected.must_change_regions:
        checks.append(_region_check(region, "changed", base_regions, final_regions))
    for region in scenario.expected.must_preserve_regions:
        checks.append(_region_check(region, "preserved", base_regions, final_regions))
    if scenario.expected.action == "noop":
        checks.append(
            _check(
                "noop_code_identity",
                final_change.code == base_code,
                "No-op code matches the latest evaluation fixture byte-for-byte."
                if final_change.code == base_code
                else "No-op code differs from the latest evaluation fixture.",
            )
        )
    return _assessment(scenario, status, action, syntax_valid, validation_errors, validation_warnings, checks)


async def execute_scenario(
    scenario: EvaluationScenario,
    *,
    provider: AgentProvider,
    provider_name: str,
    model: str,
    scenario_root: Path | None = None,
    budget: AgentRunBudget | None = None,
    tools: ToolRegistry | None = None,
) -> EvaluationRunReport:
    """Run one scenario in isolation and return only safe final/loop observations."""

    root = (scenario_root or evaluations_root()).resolve()
    source_code = _scenario_source_code(root, scenario)
    initial_editor = _editor_version(source_code)
    project_context = _scenario_project_context(root, scenario)
    registry = tools or ToolRegistry()
    manager = AgentRunManager(tools=registry)
    editor_update_applied = False
    try:
        started = await manager.start(
            intent=scenario.intent,
            editor_version=initial_editor,
            apply_mode="manual",
            budget=budget or build_run_budget(AgentRuntimeConfig()),
            provider_name=provider_name,
            model=model,
            provider=provider,
            project_context=project_context,
        )
        if scenario.editor_update_fixture:
            latest_editor = _editor_version(_read_fixture(root, scenario.editor_update_fixture))
            updated = await manager.update_editor(
                started.id,
                base_hash=initial_editor.hash,
                editor_version=latest_editor,
            )
            if not updated:
                raise EvaluationScenarioError("Scenario Agent Run disappeared before its editor update")
            editor_update_applied = updated.editor_version.hash == latest_editor.hash

        completed = await manager.wait(started.id)
        if not completed:
            raise EvaluationScenarioError("Scenario Agent Run disappeared before completion")
        assessment = assess_final_result(
            scenario,
            status=completed.status,
            final_change=completed.final_change,
            scenario_root=root,
            tools=registry,
        )
        return EvaluationRunReport(
            scenarioId=scenario.id,
            runId=completed.id,
            provider=completed.provider or provider_name,
            model=completed.model or model,
            status=completed.status,
            action=completed.final_change.action if completed.final_change else None,
            editorUpdateApplied=editor_update_applied,
            usage=completed.usage,
            tools=[_tool_observation(result) for result in completed.tool_results],
            assessment=assessment,
            passed=assessment.passed,
        )
    finally:
        await manager.close()


def create_human_review(
    scenario: EvaluationScenario,
    *,
    rubric: list[EvaluationRubricReview],
    performance_readiness: PerformanceReadiness,
    musical_quality: int | None = None,
    reviewed_at: int | None = None,
) -> HumanMusicalReview:
    """Create human feedback that can only reference this scenario's fixed rubric."""

    review = HumanMusicalReview(
        scenarioId=scenario.id,
        reviewedAt=_timestamp() if reviewed_at is None else reviewed_at,
        rubric=rubric,
        musicalQuality=musical_quality,
        performanceReadiness=performance_readiness,
    )
    _validate_human_review(scenario, review)
    return review


def save_evaluation_record(
    scenario: EvaluationScenario,
    report: EvaluationRunReport,
    review: HumanMusicalReview,
    *,
    root: Path | None = None,
    now: int | None = None,
) -> EvaluationRecord:
    """Append a reviewed report without persisting source, candidate, or provider credentials."""

    _validate_report_scenario(scenario, report)
    _validate_human_review(scenario, review)
    record = EvaluationRecord(
        id=_evaluation_record_id(),
        createdAt=_timestamp() if now is None else now,
        report=report,
        review=review,
    )
    results_dir = evaluation_results_dir(root)
    try:
        results_dir.mkdir(parents=True, exist_ok=True)
        path = results_dir / f"{time_ns():020d}-{record.id}.json"
        with path.open("x", encoding="utf-8") as output:
            json.dump(record.model_dump(by_alias=True), output, ensure_ascii=False, indent=2)
    except OSError as error:
        raise EvaluationScenarioError("Could not persist the evaluation record") from error
    return record


def list_evaluation_records(root: Path | None = None) -> list[EvaluationRecord]:
    results_dir = evaluation_results_dir(root)
    if not results_dir.exists():
        return []
    records: list[EvaluationRecord] = []
    for path in sorted(results_dir.glob("*.json")):
        try:
            records.append(EvaluationRecord.model_validate_json(path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
    return records


def summarize_evaluation_records(records: list[EvaluationRecord]) -> EvaluationSummary:
    """Summarize the latest reviewed result per scenario without hiding history."""

    latest_by_scenario: dict[str, EvaluationRecord] = {}
    for record in records:
        previous = latest_by_scenario.get(record.report.scenario_id)
        if previous is None or record.created_at >= previous.created_at:
            latest_by_scenario[record.report.scenario_id] = record

    latest_records = list(latest_by_scenario.values())
    rubric_results = [item.result for record in latest_records for item in record.review.rubric]
    quality_scores = [
        record.review.musical_quality
        for record in latest_records
        if record.review.musical_quality is not None
    ]
    return EvaluationSummary(
        totalRecords=len(records),
        scenarioCount=len(latest_records),
        deterministicPassed=sum(record.report.passed for record in latest_records),
        humanReviewed=len(latest_records),
        rubricMet=rubric_results.count("met"),
        rubricPartial=rubric_results.count("partial"),
        rubricNotMet=rubric_results.count("not_met"),
        rubricNotApplicable=rubric_results.count("not_applicable"),
        performanceReady=sum(record.review.performance_readiness == "ready" for record in latest_records),
        averageMusicalQuality=(sum(quality_scores) / len(quality_scores) if quality_scores else None),
    )


def _validate_report_scenario(scenario: EvaluationScenario, report: EvaluationRunReport) -> None:
    if report.scenario_id != scenario.id:
        raise EvaluationScenarioError("Evaluation report must belong to the supplied scenario")


def _validate_human_review(scenario: EvaluationScenario, review: HumanMusicalReview) -> None:
    if review.scenario_id != scenario.id:
        raise EvaluationScenarioError("Human review must belong to the supplied scenario")
    expected_rubric = scenario.expected.review
    actual_rubric = [item.criterion for item in review.rubric]
    if actual_rubric != expected_rubric:
        raise EvaluationScenarioError("Human review rubric must exactly match the scenario rubric")


def _validate_fixture(root: Path, fixture: str, scenario_name: str) -> None:
    path = scenario_fixture_path(root, fixture)
    if not path.is_file():
        raise EvaluationScenarioError(f"Scenario {scenario_name} references a missing fixture: {fixture}")


def _scenario_base_code(root: Path, scenario: EvaluationScenario) -> str:
    fixture = scenario.editor_update_fixture or scenario.source_fixture
    return _read_fixture(root, fixture)


def _scenario_source_code(root: Path, scenario: EvaluationScenario) -> str:
    return _read_fixture(root, scenario.source_fixture)


def _scenario_project_context(root: Path, scenario: EvaluationScenario) -> str | None:
    if not scenario.project_context_fixture:
        return None
    return _read_fixture(root, scenario.project_context_fixture)


def _read_fixture(root: Path, fixture: str) -> str:
    try:
        return scenario_fixture_path(root, fixture).read_text(encoding="utf-8")
    except OSError as error:
        raise EvaluationScenarioError(f"Could not read evaluation fixture: {fixture}") from error


def _assessment(
    scenario: EvaluationScenario,
    status: AgentRunStatus,
    action: Literal["apply", "noop"] | None,
    syntax_valid: bool | None,
    validation_errors: list[str],
    validation_warnings: list[str],
    checks: list[EvaluationCheck],
) -> EvaluationAssessment:
    return EvaluationAssessment(
        scenarioId=scenario.id,
        status=status,
        action=action,
        syntaxValid=syntax_valid,
        validationErrors=validation_errors,
        validationWarnings=validation_warnings,
        checks=checks,
        passed=all(check.passed for check in checks),
    )


def _check(identifier: str, passed: bool, detail: str) -> EvaluationCheck:
    return EvaluationCheck(id=identifier, passed=passed, detail=detail)


def _region_check(
    region: str,
    expectation: Literal["changed", "preserved"],
    base_regions: dict[str, str],
    final_regions: dict[str, str],
) -> EvaluationCheck:
    base = base_regions.get(region)
    final = final_regions.get(region)
    identifier = f"region:{region}:{expectation}"
    if base is None or final is None:
        return _check(identifier, False, f"Region {region} is missing from the source or final code.")
    passed = base != final if expectation == "changed" else base == final
    return _check(
        identifier,
        passed,
        f"Region {region} was expected to be {expectation}.",
    )


_REGION_PATTERN = re.compile(
    r"/\*\s*@eval-region:([A-Za-z0-9_-]+):start\s*\*/(?P<body>.*?)/\*\s*@eval-region:\1:end\s*\*/",
    re.DOTALL,
)


def _extract_regions(code: str) -> dict[str, str]:
    return {match.group(1): match.group("body") for match in _REGION_PATTERN.finditer(code)}


def _validation_messages(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    messages: list[str] = []
    for item in value:
        if isinstance(item, dict) and isinstance(item.get("message"), str):
            messages.append(item["message"])
    return messages


def _editor_version(code: str) -> EditorVersion:
    return EditorVersion(code=code, hash=hashlib.sha256(code.encode("utf-8")).hexdigest())


def _tool_observation(result: ToolResult) -> EvaluationToolObservation:
    error_code: str | None = None
    error = result.output.get("error")
    if isinstance(error, dict) and isinstance(error.get("code"), str):
        error_code = error["code"]
    return EvaluationToolObservation(name=result.name, status=result.status, errorCode=error_code)


def _evaluation_record_id() -> str:
    return f"evaluation-{uuid4().hex}"


def _timestamp() -> int:
    return int(time() * 1000)
