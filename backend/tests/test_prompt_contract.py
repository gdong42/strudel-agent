from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from app.models import ReconciliationContext
from app.prompt_contract import AGENT_RUNTIME_SYSTEM_PROMPT, PromptContractOutput, SYSTEM_PROMPT, build_prompt_input


def test_prompt_contract_requires_complete_structured_output() -> None:
    output = PromptContractOutput.model_validate({
        "code": 's("bd*4")',
        "explanation": "Added a steady kick.",
        "action": "apply",
        "warnings": [{
            "level": "warn",
            "message": "This uses a visual function.",
            "category": "visual",
        }],
    })

    assert output.warnings[0].category == "visual"

    with pytest.raises(ValidationError):
        PromptContractOutput.model_validate({
            "code": 's("bd")',
            "explanation": "Missing action and warnings.",
        })


def test_prompt_contract_rejects_unknown_output_fields() -> None:
    with pytest.raises(ValidationError):
        PromptContractOutput.model_validate({
            "code": 's("bd")',
            "explanation": "Extra field.",
            "action": "apply",
            "warnings": [],
            "unexpected": True,
        })


def test_prompt_input_preserves_reconciliation_context() -> None:
    payload = json.loads(build_prompt_input(
        intent="keep the hats",
        current_code='s("hh")',
        reconciliation=ReconciliationContext(
            baseCode='s("bd")',
            previousAgentCode='s("bd*4")',
            userEditDiff='+ s("hh")',
            attempt=1,
        ),
    ))

    assert payload == {
        "user_intent": "keep the hats",
        "current_strudel_code": 's("hh")',
        "reconciliation": {
            "base_strudel_code": 's("bd")',
            "previous_agent_code": 's("bd*4")',
            "user_edit_diff": '+ s("hh")',
            "attempt": 1,
        },
    }
    assert "byte-for-byte unchanged" in SYSTEM_PROMPT


def test_runtime_prompt_requires_tool_driven_finalization_and_limited_clarification() -> None:
    assert "finalize_change" in AGENT_RUNTIME_SYSTEM_PROMPT
    assert "request_user_input" in AGENT_RUNTIME_SYSTEM_PROMPT
    assert "material ambiguity" in AGENT_RUNTIME_SYSTEM_PROMPT
    assert "editorUpdate" in AGENT_RUNTIME_SYSTEM_PROMPT
