from __future__ import annotations

import json

from ..models import AgentMessage, ModelTurnRequest, ModelTurnResult, ModelUsage, ToolCall
from .base import ModelCommentaryCallback, ProviderError


class MockProvider:
    async def next_turn(self, request: ModelTurnRequest) -> ModelTurnResult:
        if request.max_output_tokens == 0:
            raise ProviderError("Mock model turn has no output token budget")
        intent, code = self._runtime_input(request)
        marker = f"// Agent draft: {intent}"
        action = "noop" if marker in code else "apply"
        base_code = code.rstrip() or 's("bd*4")'
        final_code = code if action == "noop" else f"{base_code}\n\n{marker}\n"
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

    async def next_turn_stream(
        self,
        request: ModelTurnRequest,
        on_commentary: ModelCommentaryCallback,
    ) -> ModelTurnResult:
        await on_commentary("Preparing a local mock change.")
        return await self.next_turn(request)

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
