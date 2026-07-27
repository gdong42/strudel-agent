from __future__ import annotations

import json
import time
from typing import Any
from uuid import uuid4

from .config import AgentRuntimeConfig
from .models import (
    AgentMessage,
    AgentRun,
    AgentRunBudget,
    AgentRunUsage,
    EditorVersion,
    LOCAL_PROJECT_ID,
    LOCAL_SESSION_ID,
    ModelTurnRequest,
    ModelTurnResult,
    ToolResult,
)
from .prompt_contract import AGENT_RUNTIME_SYSTEM_PROMPT
from .providers.base import AgentProvider
from .tools import ToolRegistry


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
    remaining_token_budget = max(run.budget.max_total_tokens - run.usage.total_tokens, 0)
    result = await provider.next_turn(
        ModelTurnRequest(
            messages=[message.model_copy(deep=True) for message in run.messages],
            tools=tools.definitions(),
            model=run.model,
            remainingTokenBudget=remaining_token_budget,
        )
    )
    updated = append_model_turn(run, result, now=now)
    if not result.assistant_message.tool_calls:
        return updated
    tool_results = [tools.execute(call) for call in result.assistant_message.tool_calls]
    return append_tool_results(updated, tool_results, now=now)


def _rebuild_run(run: AgentRun, *, now: int | None, **updates: Any) -> AgentRun:
    timestamp = _timestamp(now)
    if timestamp < run.updated_at:
        raise AgentRuntimeTransitionError("Agent Run timestamp cannot move backwards")
    payload = run.model_dump(by_alias=True)
    payload.update(updates)
    payload["updatedAt"] = timestamp
    return AgentRun.model_validate(payload)


def _require_running(run: AgentRun) -> None:
    if run.status != "running":
        raise AgentRuntimeTransitionError("Only running Agent Runs may receive model or tool results")


def _timestamp(now: int | None) -> int:
    return int(time.time() * 1000) if now is None else now
