from __future__ import annotations

from ..models import GeneratedChange
from .base import ProviderRequest


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

    async def test_connection(self) -> None:
        return None
