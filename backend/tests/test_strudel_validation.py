from __future__ import annotations

import subprocess

import pytest

from app import strudel_validation
from app.strudel_validation import StrudelValidatorUnavailable, validate_strudel_code


def test_static_validator_accepts_complete_strudel_code() -> None:
    issues = validate_strudel_code(
        'setcpm(124 / 4)\nstack(s("bd*4"), note("<[c4,e4,g4] [d4,f4,a4]>"))'
    )

    assert issues == []


def test_static_validator_accepts_strudel_labeled_stack_syntax() -> None:
    issues = validate_strudel_code('$: s("bd*4")\n$: note("<[c4,e4,g4] [d4,f4,a4]>")')

    assert issues == []


def test_static_validator_reports_javascript_syntax_location() -> None:
    issues = validate_strudel_code('stack(\n  s("bd*4"),\n')

    assert len(issues) == 1
    assert issues[0]["code"] == "javascript_syntax"
    assert issues[0]["line"] == 3
    assert issues[0]["column"] == 1


def test_static_validator_reports_mini_notation_syntax_location() -> None:
    issues = validate_strudel_code('s("bd*4,")')

    assert len(issues) == 1
    assert issues[0]["code"] == "mini_notation_syntax"
    assert issues[0]["line"] == 1
    assert issues[0]["column"] == 9
    assert issues[0]["message"].startswith("[mini]")


def test_static_validator_requires_a_final_pattern_expression() -> None:
    issues = validate_strudel_code('const drums = s("bd*4")')

    assert issues == [
        {
            "code": "invalid_final_expression",
            "message": "The final top-level statement must be a Strudel pattern expression.",
            "line": 1,
            "column": 1,
        }
    ]


def test_static_validator_honors_the_transpiler_mini_off_boundary() -> None:
    issues = validate_strudel_code(
        '/* mini-off */\nconst url = "https://example.com/a,b";\n// mini-on\ns("bd*4")'
    )

    assert issues == []


def test_static_validator_never_executes_candidate_code() -> None:
    issues = validate_strudel_code('globalThis.process.exit(23)\ns("bd*4")')

    assert issues == []


def test_static_validator_bounds_candidate_size_before_starting_node() -> None:
    issues = validate_strudel_code(" " * 256_001)

    assert issues[0]["code"] == "candidate_too_large"


def test_static_validator_rejects_malformed_bridge_output(monkeypatch: pytest.MonkeyPatch) -> None:
    strudel_validation._validate_cached.cache_clear()
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, stdout="not-json", stderr=""),
    )

    with pytest.raises(StrudelValidatorUnavailable, match="malformed output"):
        validate_strudel_code('s("malformed_bridge_case")')


def test_static_validator_converts_process_timeout_to_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    strudel_validation._validate_cached.cache_clear()

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="node", timeout=3)

    monkeypatch.setattr(subprocess, "run", timeout)

    with pytest.raises(StrudelValidatorUnavailable, match="could not start"):
        validate_strudel_code('s("timeout_bridge_case")')
