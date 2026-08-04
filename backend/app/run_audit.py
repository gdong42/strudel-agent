from __future__ import annotations

import hashlib
import json
from time import time, time_ns
from uuid import uuid4

from .models import AgentAuditRecord, AgentFinalChange, AgentRun, AuditTextFingerprint, ChangeRecord, ChangeWarning
from .paths import audits_dir


AUDITS_DIR = audits_dir()
_MAX_EXPLANATION_BYTES = 4 * 1024
_MAX_WARNING_BYTES = 1024
_MAX_WARNINGS = 5


class AgentAuditLog:
    """Append safe lifecycle metadata without retaining private Run contents."""

    def record_started(self, run: AgentRun) -> None:
        self._append(
            self._run_record(
                run,
                event="run_started",
                occurred_at=run.created_at,
                status="running",
                intent=_fingerprint(run.intent),
            )
        )

    def record_state(self, run: AgentRun) -> None:
        if run.status == "needs_input" and run.pending_input:
            self._append(
                self._run_record(
                    run,
                    event="input_requested",
                    occurred_at=run.updated_at,
                    status=run.status,
                    question_id=run.pending_input.question_id,
                )
            )
            return
        if run.status == "completed" and run.final_change:
            final = _safe_final(run.final_change)
            self._append(
                self._run_record(
                    run,
                    event="run_completed",
                    occurred_at=run.updated_at,
                    status=run.status,
                    final_action=final.action,
                    final_explanation=final.explanation,
                    final_warnings=final.warnings,
                    truncated=final.truncated,
                )
            )
            return
        if run.status == "completed" and run.final_response:
            response, truncated = _bounded_text(run.final_response.content, _MAX_EXPLANATION_BYTES)
            self._append(
                self._run_record(
                    run,
                    event="run_completed",
                    occurred_at=run.updated_at,
                    status=run.status,
                    final_response=response,
                    truncated=truncated,
                )
            )
            return
        if run.status == "failed" and run.failure:
            self._append(
                self._run_record(
                    run,
                    event="run_failed",
                    occurred_at=run.updated_at,
                    status=run.status,
                    error_code=run.failure.code,
                )
            )
            return
        if run.status == "cancelled":
            self._append(
                self._run_record(
                    run,
                    event="run_cancelled",
                    occurred_at=run.updated_at,
                    status=run.status,
                )
            )

    def record_answer(self, run: AgentRun, question_id: str, answer: str) -> None:
        self._append(
            self._run_record(
                run,
                event="input_answered",
                occurred_at=run.updated_at,
                status=run.status,
                question_id=question_id,
                answer=_fingerprint(answer),
            )
        )

    def record_staged_change(self, run: AgentRun, change_id: str) -> None:
        if not run.final_change:
            return
        final = _safe_final(run.final_change)
        self._append(
            self._run_record(
                run,
                event="change_staged",
                occurred_at=_timestamp(),
                status=run.status,
                final_action=final.action,
                final_explanation=final.explanation,
                final_warnings=final.warnings,
                change_id=change_id,
                truncated=final.truncated,
            )
        )

    def record_change_undone(self, change: ChangeRecord) -> None:
        final = _safe_change_final(change)
        self._append(
            AgentAuditRecord(
                id=_record_id(),
                projectId=change.project_id,
                sessionId=change.session_id,
                occurredAt=change.undone_at or _timestamp(),
                event="change_undone",
                provider=change.provider,
                model=change.model,
                intent=_fingerprint(change.intent),
                finalAction=final.action,
                finalExplanation=final.explanation,
                finalWarnings=final.warnings,
                changeId=change.id,
                truncated=final.truncated,
            )
        )

    def _run_record(
        self,
        run: AgentRun,
        *,
        event: str,
        occurred_at: int,
        status: str,
        intent: AuditTextFingerprint | None = None,
        question_id: str | None = None,
        answer: AuditTextFingerprint | None = None,
        final_action: str | None = None,
        final_explanation: str | None = None,
        final_response: str | None = None,
        final_warnings: list[ChangeWarning] | None = None,
        change_id: str | None = None,
        error_code: str | None = None,
        truncated: bool = False,
    ) -> AgentAuditRecord:
        return AgentAuditRecord(
            id=_record_id(),
            projectId=run.project_id,
            sessionId=run.session_id,
            runId=run.id,
            occurredAt=occurred_at,
            event=event,
            status=status,
            provider=run.provider,
            model=run.model,
            usage=run.usage,
            intent=intent,
            questionId=question_id,
            answer=answer,
            finalAction=final_action,
            finalExplanation=final_explanation,
            finalResponse=final_response,
            finalWarnings=final_warnings or [],
            changeId=change_id,
            errorCode=error_code,
            truncated=truncated,
        )

    @staticmethod
    def _append(record: AgentAuditRecord) -> None:
        try:
            AUDITS_DIR.mkdir(parents=True, exist_ok=True)
            path = AUDITS_DIR / f"{time_ns():020d}-{record.id}.json"
            with path.open("x", encoding="utf-8") as output:
                json.dump(record.model_dump(by_alias=True), output, ensure_ascii=False, indent=2)
        except OSError:
            return


def list_audit_records() -> list[AgentAuditRecord]:
    if not AUDITS_DIR.exists():
        return []
    records: list[AgentAuditRecord] = []
    for path in sorted(AUDITS_DIR.glob("*.json")):
        try:
            records.append(AgentAuditRecord.model_validate_json(path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
    return records


class _SafeFinal:
    def __init__(self, action: str, explanation: str, warnings: list[ChangeWarning], truncated: bool) -> None:
        self.action = action
        self.explanation = explanation
        self.warnings = warnings
        self.truncated = truncated


def _safe_final(final: AgentFinalChange) -> _SafeFinal:
    explanation, explanation_truncated = _bounded_text(final.explanation, _MAX_EXPLANATION_BYTES)
    warnings, warnings_truncated = _safe_warnings(final.warnings)
    return _SafeFinal(final.action, explanation, warnings, explanation_truncated or warnings_truncated)


def _safe_change_final(change: ChangeRecord) -> _SafeFinal:
    explanation, explanation_truncated = _bounded_text(change.explanation, _MAX_EXPLANATION_BYTES)
    warnings, warnings_truncated = _safe_warnings(change.warnings)
    return _SafeFinal(change.action, explanation, warnings, explanation_truncated or warnings_truncated)


def _safe_warnings(warnings: list[ChangeWarning]) -> tuple[list[ChangeWarning], bool]:
    safe_warnings: list[ChangeWarning] = []
    truncated = len(warnings) > _MAX_WARNINGS
    for warning in warnings[:_MAX_WARNINGS]:
        message, message_truncated = _bounded_text(warning.message, _MAX_WARNING_BYTES)
        safe_warnings.append(
            ChangeWarning(level=warning.level, category=warning.category, message=message)
        )
        truncated = truncated or message_truncated
    return safe_warnings, truncated


def _bounded_text(value: str, max_bytes: int) -> tuple[str, bool]:
    encoded = value.encode("utf-8")
    if len(encoded) <= max_bytes:
        return value, False
    marker = "\n[truncated]"
    prefix_limit = max(0, max_bytes - len(marker.encode("utf-8")))
    return encoded[:prefix_limit].decode("utf-8", errors="ignore") + marker, True


def _fingerprint(value: str) -> AuditTextFingerprint:
    encoded = value.encode("utf-8")
    return AuditTextFingerprint(sha256=hashlib.sha256(encoded).hexdigest(), byteCount=len(encoded))


def _record_id() -> str:
    return f"audit-{uuid4().hex}"


def _timestamp() -> int:
    return int(time() * 1000)
