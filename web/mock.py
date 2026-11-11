"""Мок ядра и каталога для разработки веб-чата до готовности B.

Сценарии выбираются по словам в вопросе, чтобы вручную пройти каждый
статус Answer и сбой зависимости (см. README, раздел «Демо-режим»).
"""

from __future__ import annotations

import copy
import json
import re
import time
from datetime import date
from pathlib import Path

from contracts import (
    Answer,
    AskRequest,
    DependencyUnavailable,
    Finding,
    Fragment,
    SourceNotFound,
    SourceView,
)

DEFAULT_FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "rent_case.json"


def _norm(text: str) -> str:
    return text.lower().replace("ё", "е")


def _date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


class Fixture:
    def __init__(self, path: Path = DEFAULT_FIXTURE) -> None:
        raw = json.loads(path.read_text(encoding="utf-8"))
        self.raw = raw
        self.answer = Answer(
            status=raw["answer"]["status"],
            findings=[Finding(text=f["text"], source_ids=list(f["source_ids"])) for f in raw["answer"]["findings"]],
            note=raw["answer"].get("note", ""),
            missing=list(raw["answer"].get("missing", [])),
            clarifying_question=raw["answer"].get("clarifying_question"),
        )
        self.sources: dict[str, SourceView] = {}
        for item in raw["sources"]:
            fragment = Fragment(
                fragment_id=item["fragment_id"],
                document_id=item["document_id"],
                title=item["title"],
                point=item["point"],
                text=item["text"],
                revision_id=item["revision_id"],
                effective_from=_date(item.get("effective_from")),
                effective_to=_date(item.get("effective_to")),
            )
            self.sources[fragment.fragment_id] = SourceView(
                fragment=fragment, context_text=item.get("context_text") or fragment.text
            )


class FixtureSourceRepository:
    """Каталог источников из фикстуры. Тот же интерфейс, что у SourceRepository."""

    def __init__(self, fixture: Fixture) -> None:
        self._sources = fixture.sources

    def get_source(self, fragment_id: str) -> SourceView:
        view = self._sources.get(fragment_id)
        if view is None:
            raise SourceNotFound(fragment_id)
        return view

    def __len__(self) -> int:
        return len(self._sources)


class MockAssistant:
    """Детерминированные ответы для проверки интерфейса без LLM и поиска."""

    FAILURE = re.compile(r"#сбой|сбой зависимост")
    RENT = re.compile(r"северн\w* склад|аренд")
    OLD_REVISION = re.compile(r"редакци|20(1\d|20)\b")
    AMBIGUOUS = re.compile(r"альфа")
    COUNTERPARTY = re.compile(r"альфа[\s-]*трейд(инг)?")
    INJECTION = re.compile(r"игнорируй|системн\w* (промпт|промт|сообщени)|ignore (all|previous)")
    OFF_TOPIC = re.compile(r"погод|рецепт|анекдот|стих")

    def __init__(self, fixture: Fixture, delay_seconds: float = 0.0) -> None:
        self.fixture = fixture
        self.delay = delay_seconds

    def ask(self, request: AskRequest) -> Answer:
        if self.delay:
            time.sleep(self.delay)
        q = _norm(request.question)
        context = _norm(" ".join(m.text for m in request.history if m.role == "user"))

        if self.FAILURE.search(q):
            raise DependencyUnavailable("Демо: модель недоступна")
        if self.INJECTION.search(q):
            return Answer(
                status="declined",
                note="Я работаю только как юридический ассистент по базе документов и не меняю правила "
                     "работы по просьбе из сообщения. Задайте вопрос по документам — отвечу со ссылками.",
            )
        if self.OFF_TOPIC.search(q):
            return Answer(
                status="declined",
                note="Это вопрос вне моей компетенции. Я отвечаю на юридические вопросы по базе "
                     "нормативных документов и договоров банка.",
            )
        named = self.COUNTERPARTY.search(q)
        if named:
            # Ответ на уточнение: контрагент назван точно, повторно не переспрашиваем.
            name = "Альфа-Трейдинг" if named.group(1) else "Альфа-Трейд"
            return Answer(
                status="insufficient",
                note=f"Уточнение принято: договор с «{name}». В демонстрационной фикстуре текста "
                     f"этого договора нет, поэтому условия я не привожу. С подключённым ядром "
                     f"ответ будет построен по базе знаний.",
                missing=[f"Текст договора с «{name}» (в демо-режиме есть только договор аренды А-08/2024)"],
            )
        if self.AMBIGUOUS.search(q):
            return Answer(
                status="clarification_needed",
                note="В базе есть два похожих контрагента, и условия их договоров различаются.",
                clarifying_question="Уточните, о каком контрагенте речь: «Альфа-Трейд» или «Альфа-Трейдинг»?",
            )
        if self.RENT.search(q) or (self.RENT.search(context) and len(q) < 60):
            answer = copy.deepcopy(self.fixture.answer)
            if self.OLD_REVISION.search(q):
                answer.status = "partial"
                answer.findings = answer.findings[:1]
                answer.note = "Подтверждена только действующая редакция условий об арендной плате."
                answer.missing = [
                    "Редакция договора, действовавшая на указанную дату",
                    "Дополнительные соглашения об изменении арендной платы, если они были",
                ]
            return answer
        return Answer(
            status="insufficient",
            note="В базе не нашлось положений, которые отвечают на этот вопрос. "
                 "Делать вывод без подтверждающего источника я не буду.",
            missing=["Документ или положение, регулирующее предмет вопроса"],
        )
