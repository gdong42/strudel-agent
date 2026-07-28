from __future__ import annotations

import json

from ..models import AgentMessage, GeneratedChange, ModelTurnRequest, ModelTurnResult, ModelUsage, ToolCall
from .base import ProviderError, ProviderRequest


class MockProvider:
    async def create_change(self, request: ProviderRequest) -> GeneratedChange:
        code = request.current_code.rstrip()
        marker = f"// Agent draft: {request.intent.strip()}"
        if request.reconciliation and marker in code:
            return GeneratedChange(
                code=request.current_code,
                explanation="Your latest edit already includes the requested mock change.",
                action="noop",
            )
        return GeneratedChange(
            code=f"{code}\n\n{marker}\n",
            explanation=f'Prepared a local mock change for "{request.intent.strip()}".',
        )

    async def next_turn(self, request: ModelTurnRequest) -> ModelTurnResult:
        if request.remaining_token_budget == 0:
            raise ProviderError("Mock model turn has no remaining token budget")
        intent, code = self._runtime_input(request)
        marker = f"// Agent draft: {intent}"
        action = "noop" if marker in code else "apply"
        final_code = code if action == "noop" else f"{code.rstrip()}\n\n{marker}\n"
        return ModelTurnResult(
            assistantMessage=AgentMessage(
                role="assistant",
                toolCalls=[
                    ToolCall(
                        id="mock-final",
                        name="finalize_change",
                        arguments={
                            "code": final_code,
                            "explanation": f'Prepared a local mock change for "{intent}".',
                            "action": action,
                            "warnings": [],
                        },
                    )
                ],
            ),
            usage=ModelUsage(),
        )

    async def test_connection(self) -> None:
        return None

    @staticmethod
    def _runtime_input(request: ModelTurnRequest) -> tuple[str, str]:
        intent: str | None = None
        code: str | None = None
        for message in request.messages:
            if message.role != "user":
                continue
            try:
                payload = json.loads(message.content)
            except json.JSONDecodeError:
                continue
            if not isinstance(payload, dict):
                continue
            candidate_intent = payload.get("intent")
            editor_version = payload.get("editorVersion")
            if isinstance(candidate_intent, str):
                intent = candidate_intent
            if isinstance(editor_version, dict) and isinstance(editor_version.get("code"), str):
                code = editor_version["code"]
            editor_update = payload.get("editorUpdate")
            if not isinstance(editor_update, dict):
                continue
            updated_version = editor_update.get("editorVersion")
            if isinstance(updated_version, dict) and isinstance(updated_version.get("code"), str):
                code = updated_version["code"]
        if isinstance(intent, str) and isinstance(code, str):
            return intent, code
        raise ProviderError("Mock model turn is missing the initial Agent Run input")
