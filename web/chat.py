"""Контроллер веб-чата: мост между HTTP и общим ядром.

Контроллер не хранит состояние диалога. История приходит в каждом запросе,
как и при автоматической проверке на платформе.
"""

from __future__ import annotations

import logging
from typing import Protocol

from contracts import Answer, AskRequest, SourceNotFound, SourceView
from web.schemas import SourceRefOut

log = logging.getLogger("web.chat")

ANSWER_STATUSES = {"answered", "partial", "insufficient", "clarification_needed", "declined"}
STATUSES_WITH_FINDINGS = {"answered", "partial"}


class AssistantPort(Protocol):
    """То, что веб ждёт от ядра B (AssistantService или мок)."""

    def ask(self, request: AskRequest) -> Answer: ...


class SourcePort(Protocol):
    """То, что веб ждёт от каталога A (SourceRepository)."""

    def get_source(self, fragment_id: str) -> SourceView: ...


class CoreNotReady(RuntimeError):
    """Ядро ещё не реализовано (заглушка B выбрасывает NotImplementedError)."""


class ContractViolation(RuntimeError):
    """Ядро вернуло Answer, который нельзя показывать юристу."""


class ChatController:
    def __init__(self, assistant: AssistantPort, sources: SourcePort) -> None:
        self.assistant = assistant
        self.sources = sources

    def post_message(self, request: AskRequest) -> Answer:
        """POST /api/chat. DependencyUnavailable пробрасывается наверх как есть."""
        try:
            answer = self.assistant.ask(request)
        except NotImplementedError as exc:
            raise CoreNotReady("AssistantService.ask ещё не реализован") from exc
        self._check_answer(answer)
        return answer

    def get_source(self, fragment_id: str) -> SourceView:
        """GET /api/sources/{fragment_id}. Для неизвестного ID — SourceNotFound."""
        return self.sources.get_source(fragment_id)

    def describe_sources(self, answer: Answer) -> list[SourceRefOut]:
        """Справочник источников ответа в порядке первого упоминания.

        Ссылка на ID вне каталога не скрывается: она помечается found=False,
        чтобы ошибку стыковки было видно в интерфейсе и логах.
        """
        refs: list[SourceRefOut] = []
        seen: set[str] = set()
        for finding in answer.findings:
            for fragment_id in finding.source_ids:
                if fragment_id in seen:
                    continue
                seen.add(fragment_id)
                try:
                    fragment = self.sources.get_source(fragment_id).fragment
                except SourceNotFound:
                    log.warning("stage=describe_sources error=SourceNotFound id=%r", fragment_id)
                    refs.append(SourceRefOut(fragment_id=fragment_id, found=False))
                    continue
                refs.append(
                    SourceRefOut(
                        fragment_id=fragment_id,
                        found=True,
                        document_id=fragment.document_id,
                        title=fragment.title,
                        point=fragment.point,
                        revision_id=fragment.revision_id,
                        effective_from=fragment.effective_from,
                        effective_to=fragment.effective_to,
                    )
                )
        return refs

    @staticmethod
    def _check_answer(answer: Answer) -> None:
        """Минимальные гарантии контракта Answer перед показом пользователю.

        Глубокую проверку выводов делает AnswerVerifier (B). Здесь веб
        только не даёт показать юридический вывод без ссылки на источник.
        """
        if answer.status not in ANSWER_STATUSES:
            raise ContractViolation(f"Неизвестный статус ответа: {answer.status!r}")
        if answer.status in STATUSES_WITH_FINDINGS:
            if not answer.findings:
                raise ContractViolation(f"Статус {answer.status} требует хотя бы один вывод")
            for finding in answer.findings:
                if not finding.source_ids:
                    raise ContractViolation("Вывод без ссылок на источники")
        elif answer.findings:
            log.warning("stage=check_answer warning=findings_ignored status=%s", answer.status)
            answer.findings = []
        if answer.status == "clarification_needed" and not (answer.clarifying_question or "").strip():
            raise ContractViolation("Статус clarification_needed без уточняющего вопроса")
