"""Сборка сервисов веб-чата из переменных окружения.

Режимы (ASSISTANT_MODE):
- mock — ответы и источники из fixtures/rent_case.json, без API и базы;
- core — каталог A из базы знаний и AssistantService B;
- auto (по умолчанию) — core, если найдена база и задан ключ LLM, иначе mock.

Поиск и просмотр источников в режиме core используют один и тот же Corpus.
"""

from __future__ import annotations

import logging
import os
import sys
from contextlib import ExitStack
from dataclasses import dataclass, field
from pathlib import Path

from contracts import Corpus, RetrievalResult, SearchHit, SearchQuery
from web.chat import ChatController
from web.mock import DEFAULT_FIXTURE, Fixture, FixtureSourceRepository, MockAssistant

log = logging.getLogger("web.wiring")

KB_ARCHIVES = ("kb.zip", "knowledge-base.zip", "knowledge_base.zip")
KB_FOLDERS = ("kb", "knowledge_base", "knowledge-base")


def _env(name: str, default: str = "") -> str:
    value = os.getenv(name, "").strip()
    return value or default


@dataclass
class Settings:
    mode: str = "auto"
    data_dir: Path = Path("data")
    kb_path: Path | None = None
    fixture_path: Path = DEFAULT_FIXTURE
    mock_delay_ms: int = 300

    @classmethod
    def from_env(cls) -> "Settings":
        mode = _env("ASSISTANT_MODE", "auto").lower()
        if mode not in {"auto", "mock", "core"}:
            raise ValueError("ASSISTANT_MODE должен быть auto, mock или core")
        kb = _env("KB_PATH")
        try:
            delay = max(0, min(5000, int(_env("MOCK_DELAY_MS", "300"))))
        except ValueError:
            delay = 300
        return cls(
            mode=mode,
            data_dir=Path(_env("DATA_DIR", "data")),
            kb_path=Path(kb) if kb else None,
            fixture_path=Path(_env("FIXTURE_PATH")) if _env("FIXTURE_PATH") else DEFAULT_FIXTURE,
            mock_delay_ms=delay,
        )


@dataclass
class Runtime:
    controller: ChatController
    mode: str
    fragments: int
    resources: ExitStack = field(default_factory=ExitStack)

    def close(self) -> None:
        self.resources.close()


def find_knowledge_base(settings: Settings) -> Path | None:
    if settings.kb_path is not None:
        return settings.kb_path if settings.kb_path.exists() else None
    for name in KB_ARCHIVES + KB_FOLDERS:
        candidate = settings.data_dir / name
        if candidate.exists():
            return candidate
    return None


def has_llm_key() -> bool:
    return bool(_env("LLM_API_KEY") or _env("OPENAI_API_KEY"))


def load_corpus(kb: Path) -> Corpus:
    """ZIP читаем загрузчиком solution.py, папку — индексатором A: фрагменты совпадают."""
    from knowledge.indexer import CorpusIndexer

    if kb.is_dir():
        return CorpusIndexer().build(kb)
    from solution import load_documents

    return CorpusIndexer().build_documents(load_documents(kb))


def build_runtime(settings: Settings) -> Runtime:
    mode = settings.mode
    kb = find_knowledge_base(settings)
    if mode == "auto":
        mode = "core" if kb is not None and has_llm_key() else "mock"
        log.info("stage=startup ASSISTANT_MODE=auto -> %s", mode)
    if mode == "mock":
        return _build_mock(settings)
    if kb is None:
        raise FileNotFoundError(
            f"Режим core: не найдена база знаний в {settings.data_dir} "
            f"({', '.join(KB_ARCHIVES + KB_FOLDERS)}) или по KB_PATH"
        )
    return _build_core(kb)


def _build_mock(settings: Settings) -> Runtime:
    fixture = Fixture(settings.fixture_path)
    sources = FixtureSourceRepository(fixture)
    assistant = MockAssistant(fixture, delay_seconds=settings.mock_delay_ms / 1000)
    return Runtime(ChatController(assistant, sources), mode="mock", fragments=len(sources))


class WordSearch:
    """Резервный поиск по словам на том же Corpus, если embeddings недоступны."""

    def __init__(self, corpus: Corpus) -> None:
        self.corpus = corpus

    def search(self, query: SearchQuery) -> RetrievalResult:
        from solution import words

        query_words = words(query.text)
        ranked = sorted(
            self.corpus.fragments.values(),
            key=lambda f: len(query_words & words(f.title + " " + f.text)),
            reverse=True,
        )[: query.top_k]
        return RetrievalResult(hits=[SearchHit(fragment=f, applicability="unknown") for f in ranked])


def _build_core(kb: Path) -> Runtime:
    """Подключение ядра B. Если B добавит свою фабрику ядра, заменить тело здесь."""
    import httpx

    from assistant.model import DeepSeekClient
    from assistant.service import AssistantService
    from assistant.verifier import AnswerVerifier
    from knowledge.sources import SourceRepository
    from solution import create_search

    corpus = load_corpus(kb)
    if not corpus.fragments:
        raise ValueError(f"В базе знаний {kb} нет фрагментов")
    log.info("stage=startup kb=%s fragments=%d", kb.name, len(corpus.fragments))

    resources = ExitStack()
    client = resources.enter_context(httpx.Client(timeout=90.0))
    search = create_search(corpus, client)
    if search is None:
        print("Веб-чат: embeddings недоступны, поиск по словам.", file=sys.stderr)
        search = WordSearch(corpus)

    assistant = AssistantService(search, DeepSeekClient(), AnswerVerifier())
    sources = SourceRepository(corpus)
    return Runtime(
        ChatController(assistant, sources),
        mode="core",
        fragments=len(corpus.fragments),
        resources=resources,
    )
