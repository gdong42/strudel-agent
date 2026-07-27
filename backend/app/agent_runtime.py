from __future__ import annotations

import json
import time
from typing import Any
from uuid import uuid4

from .config import AgentRuntimeConfig
from .models import (
    AgentFinalChange,
    AgentMessage,
    AgentRun,
    AgentRunBudget,
    AgentRunFailure,
    AgentRunUsage,
    EditorVersion,
    LOCAL_PROJECT_ID,
    LOCAL_SESSION_ID,
    ModelTurnRequest,
    ModelTurnResult,
    RequestUserInput,
    ToolCall,
    ToolResult,
)
from .prompt_contract import AGENT_RUNTIME_SYSTEM_PROMPT
from .providers.base import AgentProvider, ProviderError
from .tools import ToolRegistry


_TERMINAL_TOOL_NAMES = frozenset({"finalize_change", "request_user_input"})


class AgentRuntimeTransitionError(RuntimeError):
    pass


def build_run_budget(config: AgentRuntimeConfig) -> AgentRunBudget:
    return AgentRunBudget(
        maxTurns=config.max_turns,
        maxElapsedSeconds=config.max_elapsed_seconds,
        maxTotalTokens=config.max_total_tokens,
    )


def create_agent_run(
    *,
    intent: str,
    editor_version: EditorVersion,
    apply_mode: str,
    budget: AgentRunBudget,
    provider: str,
    model: str,
    now: int | None = None,
    run_id: str | None = None,
) -> AgentRun:
    normalized_intent = intent.strip()
    if not normalized_intent:
        raise AgentRuntimeTransitionError("Agent Run intent cannot be empty")
    if apply_mode not in {"manual", "auto"}:
        raise AgentRuntimeTransitionError("Agent Run apply mode is invalid")
    if not provider.strip() or not model.strip():
        raise AgentRuntimeTransitionError("Agent Run provider and model are required")

    timestamp = _timestamp(now)
    return AgentRun(
        id=run_id or f"run-{uuid4().hex}",
        projectId=LOCAL_PROJECT_ID,
        sessionId=LOCAL_SESSION_ID,
        status="running",
        intent=normalized_intent,
        applyMode=apply_mode,
        editorVersion=editor_version,
        createdAt=timestamp,
        updatedAt=timestamp,
        budget=budget,
        provider=provider,
        model=model,
        messages=[
            AgentMessage(role="system", content=AGENT_RUNTIME_SYSTEM_PROMPT),
            AgentMessage(
                role="user",
                content=json.dumps(
                    {
                        "intent": normalized_intent,
                        "editorVersion": editor_version.model_dump(by_alias=True),
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            ),
        ],
    )


def append_model_turn(run: AgentRun, result: ModelTurnResult, *, now: int | None = None) -> AgentRun:
    _require_running(run)
    usage = AgentRunUsage(
        turns=run.usage.turns + 1,
        elapsedSeconds=run.usage.elapsed_seconds,
        totalTokens=run.usage.total_tokens + result.usage.total_tokens,
    )
    return _rebuild_run(
        run,
        now=now,
        messages=[*run.messages, result.assistant_message.model_copy(deep=True)],
        usage=usage,
    )


def append_tool_results(run: AgentRun, results: list[ToolResult], *, now: int | None = None) -> AgentRun:
    _require_running(run)
    tool_messages = [
        AgentMessage(
            role="tool",
            toolCallId=result.call_id,
            content=json.dumps(
                {
                    "name": result.name,
                    "status": result.status,
                    "output": result.output,
                },
                ensure_ascii=False,
                separators=(",", ":"),
            ),
        )
        for result in results
    ]
    return _rebuild_run(
        run,
        now=now,
        messages=[*run.messages, *tool_messages],
        toolResults=[*run.tool_results, *(result.model_copy(deep=True) for result in results)],
    )


async def execute_model_turn(
    run: AgentRun,
    provider: AgentProvider,
    tools: ToolRegistry,
    *,
    now: int | None = None,
) -> AgentRun:
    """Run one provider turn and append its ordered tool observations privately."""

    _require_running(run)
    if not run.model:
        raise AgentRuntimeTransitionError("Running Agent Runs require a model")
    started_at = _timestamp(now)
    if failed_run := _budget_failure_before_turn(run, now=started_at):
        return failed_run
    remaining_token_budget = max(run.budget.max_total_tokens - run.usage.total_tokens, 0)
    try:
        result = await provider.next_turn(
            ModelTurnRequest(
                messages=[message.model_copy(deep=True) for message in run.messages],
                tools=tools.definitions(),
                model=run.model,
                remainingTokenBudget=remaining_token_budget,
            )
        )
    except ProviderError as error:
        return _fail_run(
            run,
            code="provider_error",
            message="The model provider could not complete this run.",
            retryable=error.retryable,
            now=_timestamp(now),
        )
    except Exception:
        return _fail_run(
            run,
            code="internal_error",
            message="The agent run could not complete.",
            retryable=False,
            now=_timestamp(now),
        )

    completed_at = _timestamp(now)
    if not isinstance(result, ModelTurnResult):
        return _fail_run(
            run,
            code="provider_error",
            message="The model provider could not complete this run.",
            retryable=False,
            now=completed_at,
        )
    updated = append_model_turn(run, result, now=completed_at)
    if failed_run := _budget_failure_after_turn(updated, now=completed_at):
        return failed_run
    tool_calls = result.assistant_message.tool_calls
    if not tool_calls:
        return _append_runtime_feedback(
            updated,
            "The previous response did not request a tool. Continue by calling an available tool.",
            now=now,
        )
    terminal_calls = [call for call in tool_calls if call.name in _TERMINAL_TOOL_NAMES]
    if terminal_calls:
        if len(tool_calls) != 1 or len(terminal_calls) != 1:
            return append_tool_results(updated, _terminal_conflict_results(tool_calls), now=now)
        return _handle_terminal_tool(updated, terminal_calls[0], tools, now=now)
    tool_results = [tools.execute(call) for call in tool_calls]
    return append_tool_results(updated, tool_results, now=now)


def _handle_terminal_tool(run: AgentRun, call: ToolCall, tools: ToolRegistry, *, now: int | None) -> AgentRun:
    result = tools.execute(call)
    if result.status != "ok":
        return append_tool_results(run, [result], now=now)
    if call.name == "finalize_change":
        return _finalize_run(run, call, result, tools, now=now)
    return _pause_for_input(run, call, result, now=now)


def _finalize_run(
    run: AgentRun,
    call: ToolCall,
    result: ToolResult,
    tools: ToolRegistry,
    *,
    now: int | None,
) -> AgentRun:
    try:
        final_change = AgentFinalChange.model_validate(result.output["finalChange"])
    except (KeyError, TypeError, ValueError):
        return append_tool_results(run, [_protocol_error_result(call, "invalid_final_change")], now=now)

    if final_change.action == "noop" and final_change.code != run.editor_version.code:
        return append_tool_results(run, [_finalization_rejection(call, "noop_changed_code")], now=now)

    validation = tools.execute(
        ToolCall(
            id=call.id,
            name="validate_candidate",
            arguments={"candidateCode": final_change.code},
        )
    )
    if validation.status != "ok" or validation.output.get("valid") is not True:
        return append_tool_results(run, [_finalization_rejection(call, "candidate_validation_failed", validation)], now=now)

    with_result = append_tool_results(run, [result], now=now)
    return _rebuild_run(with_result, now=now, status="completed", finalChange=final_change)


def _pause_for_input(run: AgentRun, call: ToolCall, result: ToolResult, *, now: int | None) -> AgentRun:
    try:
        request = RequestUserInput.model_validate(result.output["request"])
    except (KeyError, TypeError, ValueError):
        return append_tool_results(run, [_protocol_error_result(call, "invalid_input_request")], now=now)
    with_result = append_tool_results(run, [result], now=now)
    return _rebuild_run(with_result, now=now, status="needs_input", pendingInput=request)


def _append_runtime_feedback(run: AgentRun, message: str, *, now: int | None) -> AgentRun:
    return _rebuild_run(
        run,
        now=now,
        messages=[
            *run.messages,
            AgentMessage(role="user", content=json.dumps({"runtimeFeedback": message}, separators=(",", ":"))),
        ],
    )


def _terminal_conflict_results(calls: list[ToolCall]) -> list[ToolResult]:
    return [_protocol_error_result(call, "terminal_tool_conflict") for call in calls]


def _protocol_error_result(call: ToolCall, code: str) -> ToolResult:
    return ToolResult(
        callId=call.id,
        name=call.name,
        status="recoverable_error",
        output={"error": {"code": code, "message": "The terminal tool protocol was not satisfied."}},
    )


def _finalization_rejection(call: ToolCall, code: str, validation: ToolResult | None = None) -> ToolResult:
    output: dict[str, Any] = {
        "error": {
            "code": code,
            "message": "The proposed final change did not pass deterministic finalization.",
        }
    }
    if validation:
        output["validation"] = validation.output
    return ToolResult(callId=call.id, name=call.name, status="recoverable_error", output=output)


def _budget_failure_before_turn(run: AgentRun, *, now: int) -> AgentRun | None:
    if run.usage.turns >= run.budget.max_turns:
        return _fail_run(
            run,
            code="budget_exhausted",
            message="The agent run reached its turn limit.",
            retryable=False,
            now=now,
        )
    if _elapsed_seconds(run, now) >= run.budget.max_elapsed_seconds:
        return _fail_run(
            run,
            code="budget_exhausted",
            message="The agent run exceeded its time limit.",
            retryable=False,
            now=now,
        )
    if run.usage.total_tokens >= run.budget.max_total_tokens:
        return _fail_run(
            run,
            code="budget_exhausted",
            message="The agent run exhausted its token budget.",
            retryable=False,
            now=now,
        )
    return None


def _budget_failure_after_turn(run: AgentRun, *, now: int) -> AgentRun | None:
    if _elapsed_seconds(run, now) >= run.budget.max_elapsed_seconds:
        return _fail_run(
            run,
            code="budget_exhausted",
            message="The agent run exceeded its time limit.",
            retryable=False,
            now=now,
        )
    if run.usage.total_tokens > run.budget.max_total_tokens:
        return _fail_run(
            run,
            code="budget_exhausted",
            message="The agent run exhausted its token budget.",
            retryable=False,
            now=now,
        )
    return None


def _fail_run(
    run: AgentRun,
    *,
    code: str,
    message: str,
    retryable: bool,
    now: int,
) -> AgentRun:
    return _rebuild_run(
        run,
        now=now,
        status="failed",
        failure=AgentRunFailure(code=code, message=message, retryable=retryable),
    )


def _rebuild_run(run: AgentRun, *, now: int | None, **updates: Any) -> AgentRun:
    timestamp = _timestamp(now)
    if timestamp < run.updated_at:
        raise AgentRuntimeTransitionError("Agent Run timestamp cannot move backwards")
    payload = run.model_dump(by_alias=True)
    payload.update(updates)
    usage = AgentRunUsage.model_validate(payload["usage"])
    payload["usage"] = usage.model_copy(
        update={"elapsed_seconds": _elapsed_seconds(run, timestamp)}
    ).model_dump(by_alias=True)
    payload["updatedAt"] = timestamp
    return AgentRun.model_validate(payload)


def _require_running(run: AgentRun) -> None:
    if run.status != "running":
        raise AgentRuntimeTransitionError("Only running Agent Runs may receive model or tool results")


def _timestamp(now: int | None) -> int:
    return int(time.time() * 1000) if now is None else now


def _elapsed_seconds(run: AgentRun, timestamp: int) -> int:
    return max(0, (timestamp - run.created_at) // 1000)
