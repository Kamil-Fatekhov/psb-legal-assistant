"""HTTP-схемы веб-чата и преобразование в общие типы из contracts.py.

Pydantic отвечает только за границу HTTP: проверку входа (422) и форму
ответа. Внутри приложения используются dataclass-типы из contracts.py,
поэтому ядро B и поиск A не зависят от веб-слоя.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from contracts import Answer, AskRequest, Fragment, Message, SourceView

MAX_QUESTION_CHARS = 4000
MAX_MESSAGE_CHARS = 20000
MAX_HISTORY_MESSAGES = 40


class MessageIn(BaseModel):
    model_config = ConfigDict(extra="ignore")

    role: Literal["user", "assistant"]
    text: str = Field(max_length=MAX_MESSAGE_CHARS)


class ChatRequestIn(BaseModel):
    """Тело POST /api/chat. Совпадает с AskRequest."""

    model_config = ConfigDict(extra="ignore")

    question: str = Field(max_length=MAX_QUESTION_CHARS)
    history: list[MessageIn] = Field(default_factory=list, max_length=MAX_HISTORY_MESSAGES)

    @field_validator("question")
    @classmethod
    def question_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Вопрос не должен быть пустым")
        return value

    def to_contract(self) -> AskRequest:
        return AskRequest(
            question=self.question,
            history=[Message(role=m.role, text=m.text) for m in self.history],
        )


class FindingOut(BaseModel):
    text: str
    source_ids: list[str]


class SourceRefOut(BaseModel):
    """Краткое описание источника для ссылки в чате."""

    fragment_id: str
    found: bool
    document_id: str | None = None
    title: str | None = None
    point: str | None = None
    revision_id: str | None = None
    effective_from: date | None = None
    effective_to: date | None = None


class ChatResponseOut(BaseModel):
    """Answer из contracts.py плюс справочник источников для ссылок."""

    status: str
    findings: list[FindingOut]
    note: str
    missing: list[str]
    clarifying_question: str | None
    sources: list[SourceRefOut]
    request_id: str


class FragmentOut(BaseModel):
    fragment_id: str
    document_id: str
    title: str
    point: str
    text: str
    revision_id: str
    effective_from: date | None
    effective_to: date | None


class SourceOut(FragmentOut):
    """Тело GET /api/sources/{fragment_id}: Fragment + context_text."""

    context_text: str


class ErrorBody(BaseModel):
    code: str
    message: str


class ErrorOut(BaseModel):
    error: ErrorBody
    request_id: str


def fragment_out(fragment: Fragment) -> dict:
    return {
        "fragment_id": fragment.fragment_id,
        "document_id": fragment.document_id,
        "title": fragment.title,
        "point": fragment.point,
        "text": fragment.text,
        "revision_id": fragment.revision_id,
        "effective_from": fragment.effective_from,
        "effective_to": fragment.effective_to,
    }


def source_out(view: SourceView) -> SourceOut:
    return SourceOut(**fragment_out(view.fragment), context_text=view.context_text)


def chat_response_out(
    answer: Answer, sources: list[SourceRefOut], request_id: str
) -> ChatResponseOut:
    return ChatResponseOut(
        status=answer.status,
        findings=[FindingOut(text=f.text, source_ids=list(f.source_ids)) for f in answer.findings],
        note=answer.note,
        missing=list(answer.missing),
        clarifying_question=answer.clarifying_question,
        sources=sources,
        request_id=request_id,
    )
