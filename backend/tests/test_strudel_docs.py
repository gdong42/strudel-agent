from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from app.strudel_docs import StrudelDocsError, StrudelKnowledgeBase, load_strudel_knowledge, load_strudel_skill


KNOWLEDGE_DIR = Path(__file__).resolve().parents[1] / "app" / "knowledge" / "strudel"


def test_checked_in_knowledge_package_matches_the_pinned_runtime() -> None:
    manifest = json.loads((KNOWLEDGE_DIR / "manifest.json").read_text(encoding="utf-8"))
    knowledge = load_strudel_knowledge()

    assert manifest["replVersion"] == "1.3.0"
    assert manifest["referenceVersion"] == "1.2.2"
    assert manifest["documentCounts"] == {"reference": 508, "tutorial": 436}
    assert knowledge.search("stack", symbols=["stack"], limit=1)["results"][0]["id"] == "reference:stack"


def test_search_prioritizes_exact_symbols_and_keeps_examples() -> None:
    result = load_strudel_knowledge().search(
        "oscilloscope visual scope",
        topics=["visuals"],
        symbols=["_scope"],
        limit=3,
    )

    assert result["manualVersion"] == "1.3.0"
    assert result["total"] > 3
    assert result["results"][0]["id"] == "tutorial:learn/visual-feedback#visual-feedback-scope"
    assert 's("sawtooth")._scope()' in result["results"][0]["content"]
    assert all(len(item["content"]) <= 3_500 for item in result["results"])


def test_search_finds_tutorial_explanations_for_mini_notation() -> None:
    result = load_strudel_knowledge().search(
        "parallel polyphony chords mini notation",
        topics=["mini-notation"],
        limit=2,
    )

    first = result["results"][0]
    assert first["id"] == "tutorial:learn/mini-notation#mini-notation-parallel-polyphony"
    assert "Using commas, we can play chords" in first["content"]
    assert 'note("<[g3,b3,e4]' in first["content"]


def test_knowledge_loader_rejects_a_tampered_corpus(tmp_path: Path) -> None:
    destination = tmp_path / "strudel"
    shutil.copytree(KNOWLEDGE_DIR, destination)
    corpus_path = destination / "corpus.json"
    corpus_path.write_text(corpus_path.read_text(encoding="utf-8") + " ", encoding="utf-8")

    with pytest.raises(StrudelDocsError, match="integrity"):
        StrudelKnowledgeBase.load(destination)


def test_strudel_skill_contains_runtime_specific_guidance() -> None:
    skill = load_strudel_skill()

    assert "@strudel/repl` 1.3.0" in skill
    assert "lookup_strudel_docs" in skill
    assert ".play()" in skill
