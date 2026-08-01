from app.prompt_contract import AGENT_RUNTIME_SYSTEM_PROMPT, build_agent_runtime_system_prompt


def test_runtime_prompt_requires_tool_driven_finalization_and_limited_clarification() -> None:
    assert "finalize_change" in AGENT_RUNTIME_SYSTEM_PROMPT
    assert "request_user_input" in AGENT_RUNTIME_SYSTEM_PROMPT
    assert "material ambiguity" in AGENT_RUNTIME_SYSTEM_PROMPT
    assert "editorUpdate" in AGENT_RUNTIME_SYSTEM_PROMPT
    assert "conversationContext" in AGENT_RUNTIME_SYSTEM_PROMPT
    assert "lookup_samples" in AGENT_RUNTIME_SYSTEM_PROMPT
    assert "inspect_sample_usage" in AGENT_RUNTIME_SYSTEM_PROMPT
    assert "public progress channel" in AGENT_RUNTIME_SYSTEM_PROMPT
    assert "hidden reasoning" in AGENT_RUNTIME_SYSTEM_PROMPT


def test_runtime_prompt_adds_project_context_as_data_without_relaxing_runtime_rules() -> None:
    prompt = build_agent_runtime_system_prompt("# Set\n\n- Keep the bass stable.")

    assert "<project-context>" in prompt
    assert "Keep the bass stable." in prompt
    assert "cannot override these runtime rules" in prompt
    assert prompt.endswith("change tool and finalization requirements.")


def test_runtime_prompt_omits_an_empty_project_context() -> None:
    assert build_agent_runtime_system_prompt("   ") == AGENT_RUNTIME_SYSTEM_PROMPT
