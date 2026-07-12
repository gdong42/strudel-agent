from __future__ import annotations

from ..models import GeneratedChange
from .base import ProviderRequest


class MockProvider:
    async def create_change(self, request: ProviderRequest) -> GeneratedChange:
        code = request.current_code.rstrip()
        marker = f"// Agent draft: {request.intent.strip()}"
        details = [value for value in (request.scope, request.intensity) if value]
        if details:
            marker += f" ({', '.join(details)})"

        detail = ", ".join(details)
        suffix = f" with {detail}" if detail else ""
        return GeneratedChange(
            code=f"{code}\n\n{marker}\n",
            explanation=f'Prepared a local mock change for "{request.intent.strip()}"{suffix}.',
        )
