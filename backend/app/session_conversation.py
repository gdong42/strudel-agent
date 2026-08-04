from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from .models import AgentRun


DEFAULT_MAX_RECORDS = 12
DEFAULT_MAX_BYTES = 16 * 1024
_MAX_FIELD_BYTES = 1024
_MAX_CLARIFICATIONS = 4
_MAX_WARNINGS = 3
_TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled"})


@dataclass
class _Clarification:
    question_id: str
    question: str
    answer: str | None = None


@dataclass
class _ConversationRecord:
    run_id: str
    created_at: int
    updated_at: int
    intent: str
    status: str = "running"
    clarifications: list[_Clarification] = field(default_factory=list)
    final_action: str | None = None
    final_explanation: str | None = None
    final_response: str | None = None
    final_warnings: list[dict[str, str]] = field(default_factory=list)
    change_id: str | None = None
    error_code: str | None = None
    truncated: bool = False


class SessionConversation:
    """Keep a bounded, safe-to-replay summary of one local backend session."""

    def __init__(
        self,
        *,
        max_records: int = DEFAULT_MAX_RECORDS,
        max_bytes: int = DEFAULT_MAX_BYTES,
    ) -> None:
        if max_records < 1 or max_bytes < 256:
            raise ValueError("Session conversation limits must be positive")
        self._max_records = max_records
        self._max_bytes = max_bytes
        self._field_bytes = min(_MAX_FIELD_BYTES, max(64, max_bytes // 8))
        self._records: dict[str, _ConversationRecord] = {}

    def record_started(self, run: AgentRun) -> None:
        record = _ConversationRecord(
            run_id=run.id,
            created_at=run.created_at,
            updated_at=run.updated_at,
            intent=self._bounded_text(run.intent),
            status=run.status,
        )
        record.truncated = record.intent != run.intent
        self._records[run.id] = record
        self._trim()

    def record_state(self, run: AgentRun) -> None:
        record = self._records.get(run.id)
        if not record:
            return

        record.status = run.status
        record.updated_at = run.updated_at
        if run.status == "running":
            record.final_action = None
            record.final_explanation = None
            record.final_response = None
            record.final_warnings = []
            record.change_id = None
            record.error_code = None
        elif run.status == "needs_input" and run.pending_input:
            self._record_question(record, run.pending_input.question_id, run.pending_input.question)
        elif run.status == "completed" and run.final_change:
            action = run.final_change.action
            explanation = self._bounded_text(run.final_change.explanation)
            warnings = [self._warning_payload(warning) for warning in run.final_change.warnings[:_MAX_WARNINGS]]
            record.final_action = action
            record.final_explanation = explanation
            record.final_warnings = warnings
            record.change_id = run.staged_change_id
            record.error_code = None
            if (
                explanation != run.final_change.explanation
                or len(warnings) != len(run.final_change.warnings)
                or any(warning["message"] != source.message for warning, source in zip(warnings, run.final_change.warnings))
            ):
                record.truncated = True
        elif run.status == "completed" and run.final_response:
            response = self._bounded_text(run.final_response.content)
            record.final_action = None
            record.final_explanation = None
            record.final_response = response
            record.final_warnings = []
            record.change_id = None
            record.error_code = None
            if response != run.final_response.content:
                record.truncated = True
        elif run.status == "failed" and run.failure:
            record.final_action = None
            record.final_explanation = None
            record.final_response = None
            record.final_warnings = []
            record.change_id = None
            record.error_code = run.failure.code
        elif run.status == "cancelled":
            record.final_action = None
            record.final_explanation = None
            record.final_response = None
            record.final_warnings = []
            record.change_id = None
            record.error_code = None
        self._trim()

    def record_answer(self, run_id: str, question_id: str, answer: str) -> None:
        record = self._records.get(run_id)
        if not record:
            return
        for clarification in reversed(record.clarifications):
            if clarification.question_id != question_id:
                continue
            clarification.answer = self._bounded_text(answer)
            if clarification.answer != answer:
                record.truncated = True
            self._trim()
            return

    def record_staged_change(self, run_id: str, change_id: str) -> None:
        record = self._records.get(run_id)
        if not record:
            return
        record.change_id = change_id
        self._trim()

    def clear(self) -> None:
        self._records.clear()

    def model_context(self) -> list[dict[str, object]]:
        """Return oldest-to-newest completed or paused records under the byte budget."""

        self._trim()
        selected: list[dict[str, object]] = []
        total_bytes = 2
        for record in reversed(list(self._records.values())):
            if record.status == "running":
                continue
            payload = self._model_payload(record)
            payload_bytes = len(_serialize(payload))
            separator_bytes = 1 if selected else 0
            if total_bytes + separator_bytes + payload_bytes > self._max_bytes:
                continue
            selected.append(payload)
            total_bytes += separator_bytes + payload_bytes
        selected.reverse()
        return selected

    def _record_question(self, record: _ConversationRecord, question_id: str, question: str) -> None:
        for clarification in record.clarifications:
            if clarification.question_id == question_id:
                return
        if len(record.clarifications) >= _MAX_CLARIFICATIONS:
            record.truncated = True
            return
        bounded_question = self._bounded_text(question)
        record.clarifications.append(_Clarification(question_id=question_id, question=bounded_question))
        if bounded_question != question:
            record.truncated = True

    def _warning_payload(self, warning: Any) -> dict[str, str]:
        message = self._bounded_text(warning.message)
        return {
            "level": warning.level,
            "category": warning.category,
            "message": message,
        }

    def _model_payload(self, record: _ConversationRecord) -> dict[str, object]:
        payload: dict[str, object] = {
            "runId": record.run_id,
            "createdAt": record.created_at,
            "intent": record.intent,
            "clarifications": [
                {
                    "question": clarification.question,
                    **({"answer": clarification.answer} if clarification.answer else {}),
                }
                for clarification in record.clarifications
            ],
            "outcome": {"status": record.status},
        }
        outcome = payload["outcome"]
        assert isinstance(outcome, dict)
        if record.final_action:
            outcome["action"] = record.final_action
        if record.final_explanation:
            outcome["explanation"] = record.final_explanation
        if record.final_response:
            outcome["response"] = record.final_response
        if record.final_warnings:
            outcome["warnings"] = record.final_warnings
        if record.change_id:
            outcome["changeId"] = record.change_id
        if record.error_code:
            outcome["errorCode"] = record.error_code
        if record.truncated:
            payload["truncated"] = True
        return payload

    def _bounded_text(self, value: str) -> str:
        encoded = value.encode("utf-8")
        if len(encoded) <= self._field_bytes:
            return value
        marker = "\n[truncated]"
        prefix_limit = max(0, self._field_bytes - len(marker.encode("utf-8")))
        return encoded[:prefix_limit].decode("utf-8", errors="ignore") + marker

    def _trim(self) -> None:
        while len(self._records) > self._max_records or len(_serialize(self._ledger_payloads())) > self._max_bytes:
            run_id = self._oldest_evictable_run_id()
            if run_id is None:
                return
            self._records.pop(run_id, None)

    def _oldest_evictable_run_id(self) -> str | None:
        for run_id, record in self._records.items():
            if record.status in _TERMINAL_STATUSES:
                return run_id
        return next(iter(self._records), None)

    def _ledger_payloads(self) -> list[dict[str, object]]:
        return [self._model_payload(record) for record in self._records.values()]


def _serialize(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
