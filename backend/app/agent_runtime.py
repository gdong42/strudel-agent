from __future__ import annotations

import asyncio
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
from .prompt_contract import build_agent_runtime_system_prompt
from .providers.base import AgentProvider, ModelCommentaryCallback, ProviderError
from .tools import ToolRegistry


_TERMINAL_TOOL_NAMES = frozenset({"finalize_change", "request_user_input"})
_CANCELLED_MODEL_TURN = object()


class AgentRuntimeTransitionError(RuntimeError):
    pass


class AgentRunCancellation:
    """Cooperative cancellation signal owned by one active Agent Run task."""

    def __init__(self) -> None:
        self._event = asyncio.Event()

    @property
    def is_cancelled(self) -> bool:
        return self._event.is_set()

    def cancel(self) -> None:
        self._event.set()

    async def wait(self) -> None:
        await self._event.wait()


def build_run_budget(config: AgentRuntimeConfig) -> AgentRunBudget:
    return AgentRunBudget(
        maxTurns=config.max_turns,
        maxElapsedSeconds=config.max_elapsed_seconds,
        maxTotalTokens=config.max_total_tokens,
        maxOutputTokensPerTurn=config.max_output_tokens_per_turn,
    )


def create_agent_run(
    *,
    intent: str,
    editor_version: EditorVersion,
    apply_mode: str,
    budget: AgentRunBudget,
    provider: str,
    model: str,
    project_context: str | None = None,
    conversation_context: list[dict[str, object]] | None = None,
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

    initial_input: dict[str, object] = {
        "intent": normalized_intent,
        "editorVersion": editor_version.model_dump(by_alias=True),
    }
    if conversation_context:
        initial_input["conversationContext"] = conversation_context

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
        activeStartedAt=timestamp,
        budget=budget,
        provider=provider,
        model=model,
        messages=[
            AgentMessage(role="system", content=build_agent_runtime_system_prompt(project_context)),
            AgentMessage(
                role="user",
                content=json.dumps(
                    initial_input,
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
        inputTokens=run.usage.input_tokens + result.usage.input_tokens,
        outputTokens=run.usage.output_tokens + result.usage.output_tokens,
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


def cancel_agent_run(run: AgentRun, *, now: int | None = None) -> AgentRun:
    if run.status not in {"running", "needs_input"}:
        raise AgentRuntimeTransitionError("Only active Agent Runs may be cancelled")
    return _rebuild_run(run, now=now, status="cancelled", pendingInput=None)


def discard_unstaged_completed_agent_run(run: AgentRun, *, now: int | None = None) -> AgentRun:
    if run.status != "completed" or not run.final_change or run.staged_change_id:
        raise AgentRuntimeTransitionError("Only unstaged completed Agent Runs may be cancelled")
    return _rebuild_run(run, now=now, status="cancelled", finalChange=None)


def resume_agent_run(
    run: AgentRun,
    *,
    question_id: str,
    answer: str,
    now: int | None = None,
) -> AgentRun:
    if run.status != "needs_input" or not run.pending_input:
        raise AgentRuntimeTransitionError("Only paused Agent Runs may receive user input")
    normalized_question_id = question_id.strip()
    normalized_answer = answer.strip()
    if not normalized_question_id or not normalized_answer:
        raise AgentRuntimeTransitionError("Agent Run input requires a question and answer")
    if run.pending_input.question_id != normalized_question_id:
        raise AgentRuntimeTransitionError("Agent Run input does not match the pending question")
    return _rebuild_run(
        run,
        now=now,
        status="running",
        pendingInput=None,
        messages=[
            *run.messages,
            AgentMessage(
                role="user",
                content=json.dumps(
                    {
                        "userInput": {"questionId": normalized_question_id, "answer": normalized_answer},
                        "editorVersion": run.editor_version.model_dump(by_alias=True),
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            ),
        ],
    )


def update_agent_run_editor_version(
    run: AgentRun,
    *,
    base_hash: str,
    editor_version: EditorVersion,
    now: int | None = None,
) -> AgentRun:
    if run.status not in {"running", "needs_input"}:
        raise AgentRuntimeTransitionError("Only active Agent Runs may receive editor updates")
    if not base_hash.strip() or not editor_version.code.strip():
        raise AgentRuntimeTransitionError("Agent Run editor updates require non-empty code and hashes")
    if run.editor_version.hash != base_hash:
        raise AgentRuntimeTransitionError("Agent Run editor update is stale")
    if editor_version.hash == run.editor_version.hash:
        if editor_version.code != run.editor_version.code:
            raise AgentRuntimeTransitionError("Agent Run editor update reuses a hash for different code")
        return run.model_copy(deep=True)
    return _rebuild_run(
        run,
        now=now,
        editorVersion=editor_version,
        messages=[
            *run.messages,
            AgentMessage(
                role="user",
                content=json.dumps(
                    {
                        "editorUpdate": {
                            "baseHash": base_hash,
                            "editorVersion": editor_version.model_dump(by_alias=True),
                        }
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            ),
        ],
    )


def reopen_completed_agent_run(
    run: AgentRun,
    *,
    base_hash: str,
    editor_version: EditorVersion,
    now: int | None = None,
) -> AgentRun:
    if run.status != "completed" or not run.final_change:
        raise AgentRuntimeTransitionError("Only completed Agent Runs may be reopened after a stale final")
    if run.staged_change_id:
        raise AgentRuntimeTransitionError("A persisted Agent Run change cannot be reopened")
    if not base_hash.strip() or not editor_version.code.strip():
        raise AgentRuntimeTransitionError("Agent Run editor updates require non-empty code and hashes")
    if run.editor_version.hash != base_hash:
        raise AgentRuntimeTransitionError("Agent Run editor update is stale")
    if editor_version.hash == run.editor_version.hash:
        if editor_version.code != run.editor_version.code:
            raise AgentRuntimeTransitionError("Agent Run editor update reuses a hash for different code")
        raise AgentRuntimeTransitionError("Completed Agent Run editor update must contain a newer version")
    return _rebuild_run(
        run,
        now=now,
        status="running",
        editorVersion=editor_version,
        finalChange=None,
        messages=[
            *run.messages,
            AgentMessage(
                role="user",
                content=json.dumps(
                    {
                        "editorUpdate": {
                            "baseHash": base_hash,
                            "editorVersion": editor_version.model_dump(by_alias=True),
                        }
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            ),
        ],
    )


def fail_agent_run(run: AgentRun, failure: AgentRunFailure, *, now: int | None = None) -> AgentRun:
    _require_running(run)
    return _rebuild_run(run, now=now, status="failed", failure=failure)


async def execute_model_turn(
    run: AgentRun,
    provider: AgentProvider,
    tools: ToolRegistry,
    *,
    now: int | None = None,
    cancellation: AgentRunCancellation | None = None,
    on_commentary: ModelCommentaryCallback | None = None,
) -> AgentRun:
    """Run one provider turn and append its ordered tool observations privately."""

    _require_running(run)
    if cancellation and cancellation.is_cancelled:
        return cancel_agent_run(run, now=now)
    if not run.model:
        raise AgentRuntimeTransitionError("Running Agent Runs require a model")
    started_at = _timestamp(now)
    if failed_run := _budget_failure_before_turn(run, now=started_at):
        return failed_run
    max_output_tokens = run.budget.max_output_tokens_per_turn
    if run.budget.max_total_tokens is not None:
        remaining_total_tokens = max(run.budget.max_total_tokens - run.usage.total_tokens, 0)
        max_output_tokens = min(max_output_tokens, remaining_total_tokens)
    request = ModelTurnRequest(
        messages=[message.model_copy(deep=True) for message in run.messages],
        tools=tools.definitions(),
        model=run.model,
        maxOutputTokens=max_output_tokens,
    )
    try:
        remaining_active_seconds = _remaining_active_seconds(run, started_at)
        async with asyncio.timeout(remaining_active_seconds):
            result = await _await_provider_turn(provider, request, cancellation, on_commentary)
    except TimeoutError:
        return _fail_run(
            run,
            code="budget_exhausted",
            message="The agent run exceeded its active time limit.",
            retryable=False,
            now=_timestamp(now),
        )
    except ProviderError as error:
        if cancellation and cancellation.is_cancelled:
            return cancel_agent_run(run, now=_timestamp(now))
        return _fail_run(
            run,
            code="provider_error",
            message="The model provider could not complete this run.",
            retryable=error.retryable,
            now=_timestamp(now),
        )
    except Exception:
        if cancellation and cancellation.is_cancelled:
            return cancel_agent_run(run, now=_timestamp(now))
        return _fail_run(
            run,
            code="internal_error",
            message="The agent run could not complete.",
            retryable=False,
            now=_timestamp(now),
        )

    completed_at = _timestamp(now)
    if result is _CANCELLED_MODEL_TURN or (cancellation and cancellation.is_cancelled):
        return cancel_agent_run(run, now=completed_at)
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


async def _await_provider_turn(
    provider: AgentProvider,
    request: ModelTurnRequest,
    cancellation: AgentRunCancellation | None,
    on_commentary: ModelCommentaryCallback | None,
) -> ModelTurnResult | object:
    provider_turn = _next_provider_turn(provider, request, on_commentary)
    if cancellation is None:
        return await provider_turn

    provider_task = asyncio.create_task(provider_turn)
    cancellation_task = asyncio.create_task(cancellation.wait())
    try:
        await asyncio.wait({provider_task, cancellation_task}, return_when=asyncio.FIRST_COMPLETED)
        if cancellation.is_cancelled:
            return _CANCELLED_MODEL_TURN
        return provider_task.result()
    finally:
        if not provider_task.done():
            provider_task.cancel()
        if not cancellation_task.done():
            cancellation_task.cancel()
        await asyncio.gather(provider_task, cancellation_task, return_exceptions=True)


async def _next_provider_turn(
    provider: AgentProvider,
    request: ModelTurnRequest,
    on_commentary: ModelCommentaryCallback | None,
) -> ModelTurnResult:
    streaming_turn = getattr(provider, "next_turn_stream", None)
    if on_commentary is not None and callable(streaming_turn):
        return await streaming_turn(request, on_commentary)
    return await provider.next_turn(request)


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
    if _active_elapsed_milliseconds(run, now) >= run.budget.max_elapsed_seconds * 1000:
        return _fail_run(
            run,
            code="budget_exhausted",
            message="The agent run exceeded its active time limit.",
            retryable=False,
            now=now,
        )
    if run.budget.max_total_tokens is not None and run.usage.total_tokens >= run.budget.max_total_tokens:
        return _fail_run(
            run,
            code="budget_exhausted",
            message="The agent run exhausted its token budget.",
            retryable=False,
            now=now,
        )
    return None


def _budget_failure_after_turn(run: AgentRun, *, now: int) -> AgentRun | None:
    if _active_elapsed_milliseconds(run, now) >= run.budget.max_elapsed_seconds * 1000:
        return _fail_run(
            run,
            code="budget_exhausted",
            message="The agent run exceeded its active time limit.",
            retryable=False,
            now=now,
        )
    if run.budget.max_total_tokens is not None and run.usage.total_tokens > run.budget.max_total_tokens:
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
    return fail_agent_run(
        run,
        AgentRunFailure(code=code, message=message, retryable=retryable),
        now=now,
    )


def _rebuild_run(run: AgentRun, *, now: int | None, **updates: Any) -> AgentRun:
    timestamp = _timestamp(now)
    if timestamp < run.updated_at:
        raise AgentRuntimeTransitionError("Agent Run timestamp cannot move backwards")
    payload = run.model_dump(by_alias=True)
    payload.update(updates)
    active_elapsed_milliseconds = _active_elapsed_milliseconds(run, timestamp)
    payload["activeElapsedMilliseconds"] = active_elapsed_milliseconds
    payload["activeStartedAt"] = timestamp if payload["status"] == "running" else None
    usage = AgentRunUsage.model_validate(payload["usage"])
    payload["usage"] = usage.model_copy(
        update={"elapsed_seconds": active_elapsed_milliseconds // 1000}
    ).model_dump(by_alias=True)
    payload["updatedAt"] = timestamp
    return AgentRun.model_validate(payload)


def _require_running(run: AgentRun) -> None:
    if run.status != "running":
        raise AgentRuntimeTransitionError("Only running Agent Runs may receive model or tool results")


def _timestamp(now: int | None) -> int:
    return int(time.time() * 1000) if now is None else now


def _active_elapsed_milliseconds(run: AgentRun, timestamp: int) -> int:
    if run.status != "running":
        return run.active_elapsed_milliseconds
    started_at = run.active_started_at if run.active_started_at is not None else run.updated_at
    return run.active_elapsed_milliseconds + max(0, timestamp - started_at)


def _remaining_active_seconds(run: AgentRun, timestamp: int) -> float:
    remaining_milliseconds = (
        run.budget.max_elapsed_seconds * 1000 - _active_elapsed_milliseconds(run, timestamp)
    )
    return max(remaining_milliseconds / 1000, 0)
