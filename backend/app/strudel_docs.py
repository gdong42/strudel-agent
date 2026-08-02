from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any


_KNOWLEDGE_DIR = Path(__file__).resolve().parent / "knowledge" / "strudel"
_TOKEN = re.compile(r"[A-Za-z_][A-Za-z0-9_#.-]*|\d+(?:\.\d+)?")
_MAX_RESULT_CONTENT_CHARS = 3_500


class StrudelDocsError(RuntimeError):
    """The checked-in Strudel knowledge package is missing or invalid."""


@dataclass(frozen=True)
class _IndexedDocument:
    raw: dict[str, Any]
    title: str
    topic: str
    path: str
    names: frozenset[str]
    tags: frozenset[str]
    tokens: Counter[str]


class StrudelKnowledgeBase:
    def __init__(self, manifest: dict[str, Any], documents: list[dict[str, Any]]) -> None:
        self._manifest = manifest
        self._documents = [self._index_document(document) for document in documents]
        document_frequency: Counter[str] = Counter()
        for document in self._documents:
            document_frequency.update(document.tokens.keys())
        self._document_frequency = document_frequency

    @classmethod
    def load(cls, directory: Path = _KNOWLEDGE_DIR) -> "StrudelKnowledgeBase":
        try:
            manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
            corpus_bytes = (directory / "corpus.json").read_bytes()
            corpus = json.loads(corpus_bytes)
        except (OSError, json.JSONDecodeError) as error:
            raise StrudelDocsError("The local Strudel manual could not be read.") from error

        if manifest.get("schemaVersion") != 1 or corpus.get("schemaVersion") != 1:
            raise StrudelDocsError("The local Strudel manual uses an unsupported schema.")
        expected_hash = manifest.get("corpusSha256")
        if not isinstance(expected_hash, str) or hashlib.sha256(corpus_bytes).hexdigest() != expected_hash:
            raise StrudelDocsError("The local Strudel manual failed its integrity check.")
        documents = corpus.get("documents")
        if not isinstance(documents, list) or not documents:
            raise StrudelDocsError("The local Strudel manual contains no documents.")
        if not all(cls._valid_document(document) for document in documents):
            raise StrudelDocsError("The local Strudel manual contains an invalid document.")
        return cls(manifest, documents)

    def search(
        self,
        query: str,
        *,
        topics: list[str] | None = None,
        symbols: list[str] | None = None,
        limit: int = 5,
    ) -> dict[str, Any]:
        normalized_query = _normalize_phrase(query)
        query_tokens = _tokens(query)
        normalized_topics = {_normalize_phrase(topic) for topic in topics or [] if topic.strip()}
        normalized_symbols = {_normalize_symbol(symbol) for symbol in symbols or [] if symbol.strip()}
        ranked: list[tuple[float, int, str, _IndexedDocument]] = []
        for document in self._documents:
            score = self._score(
                document,
                normalized_query=normalized_query,
                query_tokens=query_tokens,
                topics=normalized_topics,
                symbols=normalized_symbols,
            )
            if score <= 0:
                continue
            kind_priority = 0 if document.raw["kind"] == "reference" else 1
            ranked.append((-score, kind_priority, document.raw["id"], document))
        ranked.sort(key=lambda item: item[:3])

        results = []
        for negative_score, _, _, document in ranked[:limit]:
            raw = document.raw
            results.append(
                {
                    "id": raw["id"],
                    "kind": raw["kind"],
                    "title": raw["title"],
                    "topic": raw["topic"],
                    "path": raw["path"],
                    "names": raw["names"],
                    "content": _bounded_content(raw["content"]),
                    "sourceUrl": raw["sourceUrl"],
                    "score": round(-negative_score, 3),
                }
            )
        return {
            "manualVersion": self._manifest["replVersion"],
            "referenceVersion": self._manifest["referenceVersion"],
            "total": len(ranked),
            "results": results,
        }

    def _score(
        self,
        document: _IndexedDocument,
        *,
        normalized_query: str,
        query_tokens: list[str],
        topics: set[str],
        symbols: set[str],
    ) -> float:
        score = 0.0
        title = document.title
        searchable_metadata = " ".join((document.topic, document.path, *document.tags))
        content = document.raw["content"].casefold()

        if normalized_query:
            if normalized_query == title or normalized_query in document.names:
                score += 140
            elif normalized_query in title:
                score += 70
            if normalized_query in searchable_metadata:
                score += 24
            if normalized_query in content:
                score += 12

        for symbol in symbols:
            if symbol in document.names:
                score += 180
            elif symbol == title:
                score += 140
            elif symbol in searchable_metadata:
                score += 35
            elif symbol in content:
                score += 12

        if topics:
            if document.topic in topics or topics.intersection(document.tags):
                score += 28
            elif any(topic in searchable_metadata for topic in topics):
                score += 12

        document_count = max(1, len(self._documents))
        for token in query_tokens:
            frequency = document.tokens.get(token, 0)
            if not frequency:
                continue
            document_frequency = self._document_frequency.get(token, 0)
            inverse_frequency = math.log(1 + (document_count + 1) / (document_frequency + 1))
            if token in document.names or token == title:
                weight = 22
            elif token in document.tags or token in document.topic or token in document.path:
                weight = 9
            else:
                weight = 2.5
            score += inverse_frequency * weight * min(3, frequency)
        return score

    @staticmethod
    def _index_document(document: dict[str, Any]) -> _IndexedDocument:
        title = document["title"].casefold()
        topic = document["topic"].casefold()
        path = document["path"].casefold()
        names = frozenset(_normalize_symbol(name) for name in document["names"])
        tags = frozenset(_normalize_phrase(tag) for tag in document["tags"])
        searchable = " ".join(
            (
                document["title"],
                document["topic"],
                document["path"],
                *document["names"],
                *document["tags"],
                document["content"],
            )
        )
        return _IndexedDocument(
            raw=document,
            title=title,
            topic=topic,
            path=path,
            names=names,
            tags=tags,
            tokens=Counter(_tokens(searchable)),
        )

    @staticmethod
    def _valid_document(document: Any) -> bool:
        if not isinstance(document, dict):
            return False
        scalar_fields = ("id", "kind", "title", "topic", "path", "content", "sourceUrl")
        if any(not isinstance(document.get(field), str) or not document[field] for field in scalar_fields):
            return False
        return (
            document["kind"] in {"tutorial", "reference"}
            and isinstance(document.get("names"), list)
            and all(isinstance(item, str) for item in document["names"])
            and isinstance(document.get("tags"), list)
            and all(isinstance(item, str) for item in document["tags"])
        )


@lru_cache(maxsize=1)
def load_strudel_knowledge() -> StrudelKnowledgeBase:
    return StrudelKnowledgeBase.load()


@lru_cache(maxsize=1)
def load_strudel_skill() -> str:
    try:
        skill = (_KNOWLEDGE_DIR / "skill.md").read_text(encoding="utf-8").strip()
    except OSError as error:
        raise StrudelDocsError("The local Strudel skill could not be read.") from error
    if not skill:
        raise StrudelDocsError("The local Strudel skill is empty.")
    return skill


def _tokens(value: str) -> list[str]:
    return [token.casefold() for token in _TOKEN.findall(value)]


def _normalize_phrase(value: str) -> str:
    return " ".join(value.casefold().split())


def _normalize_symbol(value: str) -> str:
    symbol = value.strip().casefold()
    if symbol.endswith("()"):
        symbol = symbol[:-2]
    return symbol.removeprefix(".")


def _bounded_content(content: str) -> str:
    if len(content) <= _MAX_RESULT_CONTENT_CHARS:
        return content
    return content[: _MAX_RESULT_CONTENT_CHARS - 20].rstrip() + "\n\n[section truncated]"
