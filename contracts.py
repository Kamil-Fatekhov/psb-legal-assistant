"""Общие типы для поиска, ядра, веб-чата и сабмита."""

from dataclasses import dataclass, field
from datetime import date
from typing import Literal


AnswerStatus = Literal[
    "answered", "partial", "insufficient", "clarification_needed", "declined"
]
Applicability = Literal["applicable", "inapplicable", "unknown"]


@dataclass
class Message:
    role: Literal["user", "assistant"]
    text: str


@dataclass
class AskRequest:
    question: str
    history: list[Message] = field(default_factory=list)


@dataclass
class SearchQuery:
    text: str
    top_k: int = 8
    as_of: date | None = None
    event_kind: str | None = None
    event_date: date | None = None


@dataclass
class Fragment:
    fragment_id: str
    document_id: str
    title: str
    point: str
    text: str
    revision_id: str
    effective_from: date | None = None
    effective_to: date | None = None


@dataclass
class AmendmentRule:
    original_fragment_id: str
    replacement_fragment_id: str
    event_kind: str
    applies_after: date


@dataclass
class Corpus:
    fragments: dict[str, Fragment]
    amendment_rules: list[AmendmentRule] = field(default_factory=list)


@dataclass
class SearchHit:
    fragment: Fragment
    applicability: Applicability


@dataclass
class RetrievalResult:
    hits: list[SearchHit] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)


@dataclass
class SourceView:
    fragment: Fragment
    context_text: str


@dataclass
class Finding:
    text: str
    source_ids: list[str]


@dataclass
class Answer:
    status: AnswerStatus
    findings: list[Finding] = field(default_factory=list)
    note: str = ""
    missing: list[str] = field(default_factory=list)
    clarifying_question: str | None = None


class SourceNotFound(LookupError):
    """Идентификатор фрагмента отсутствует в каталоге."""


class DependencyUnavailable(RuntimeError):
    """Поиск или модель временно недоступны."""
