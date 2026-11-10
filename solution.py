"""Точка входа сабмита с поиском по фрагментам базы знаний."""

from __future__ import annotations

import csv
import io
import math
import os
import re
import sys
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from xml.etree import ElementTree as ET

import httpx
from dotenv import load_dotenv
from langchain_core.documents import Document

from contracts import Corpus, Fragment, SearchQuery
from knowledge.indexer import CorpusIndexer
from knowledge.search import SearchService

load_dotenv(override=False)


def env(name: str, default: str = "") -> str:
    value = os.getenv(name, "").strip()
    return default if not value or value == name else value


def env_int(name: str, default: int, low: int, high: int) -> int:
    try:
        return max(low, min(high, int(env(name))))
    except ValueError:
        return default


def env_float(name: str, default: float) -> float:
    try:
        return max(0.0, min(2.0, float(env(name))))
    except ValueError:
        return default


DATA_DIR = Path(env("DATA_DIR", "data"))
API_BASE = (env("LLM_BASE_URL") or env("BASE_URL") or env("OPENAI_BASE_URL")).rstrip("/")
LLM_KEY = env("LLM_API_KEY") or env("OPENAI_API_KEY")
EMBED_KEY = env("EMBEDDER_API_KEY") or LLM_KEY
RERANK_KEY = env("RERANKER_API_KEY") or LLM_KEY

LLM_MODEL = env("LLM_MODEL") or env("GEN_MODEL") or env("OPENAI_MODEL", "deepseek/deepseek-v4.1-flash")
EMB_MODEL = env("EMB_MODEL", "baai/bge-m3")
RERANKER_MODEL = env("RERANKER_MODEL")

TOP_K = env_int("TOP_K", 10 if RERANKER_MODEL else 5, 1, 20)
RERANKER_TOP_N = env_int("RERANKER_TOP_N", 5, 1, 20)
EMBED_BATCH_SIZE = env_int("EMBED_BATCH_SIZE", 32, 1, 128)
MAX_TOKENS = env_int("MAX_TOKENS", 1024, 128, 8192)
MAX_WORKERS = env_int("MAX_WORKERS", 2, 1, 8)
TEMPERATURE = env_float("TEMPERATURE", 0.0)
FALLBACK = "Не удалось получить ответ."
WORD_RE = re.compile(r"[0-9A-Za-zА-Яа-яЁё]{4,}")
API_ERRORS = (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError)


def words(text: str) -> set[str]:
    return set(WORD_RE.findall(text.lower().replace("ё", "е")))


def find_file(*names: str) -> Path:
    for root in (DATA_DIR, Path(__file__).resolve().parent / DATA_DIR, Path.cwd()):
        for name in names:
            path = root / name
            if path.is_file():
                return path
    raise FileNotFoundError(f"Не найден один из файлов: {', '.join(names)}")


def load_questions(path: Path) -> list[tuple[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames or not {"id", "question"}.issubset(reader.fieldnames):
            raise ValueError("В questions.csv нужны колонки id и question")
        rows = [(str(r["id"]).strip(), str(r["question"]).strip()) for r in reader]
    if not rows or any(not qid for qid, _ in rows):
        raise ValueError("В questions.csv отсутствуют вопросы или id")
    return rows


def read_docx(raw: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(raw)) as doc:
        xml = doc.read("word/document.xml")
    root = ET.fromstring(xml)
    ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    return "\n".join(
        "".join(x.text or "" for x in paragraph.iter(ns + "t"))
        for paragraph in root.iter(ns + "p")
    )


def load_documents(path: Path) -> list[Document]:
    documents = []
    with zipfile.ZipFile(path) as archive:
        for name in sorted(archive.namelist()):
            if name.endswith("/") or name.startswith("__MACOSX/"):
                continue
            suffix = Path(name).suffix.lower()
            if suffix not in {".txt", ".md", ".docx"}:
                continue
            raw = archive.read(name)
            try:
                text = read_docx(raw) if suffix == ".docx" else raw.decode("utf-8-sig")
            except (UnicodeDecodeError, KeyError, ValueError, zipfile.BadZipFile, ET.ParseError):
                print(f"Пропущен нечитаемый документ: {name}", file=sys.stderr)
                continue
            if text.strip():
                text = text.replace("\r\n", "\n").replace("\r", "\n")
                documents.append(Document(page_content=text, metadata={"source": name}))
    if not documents:
        raise ValueError("В архиве базы знаний нет читаемых документов")
    return documents


def post(client: httpx.Client, path: str, key: str, payload: dict) -> dict:
    if not key:
        raise ValueError("На платформе отсутствует API-ключ")
    response = client.post(
        API_BASE + path,
        headers={"Authorization": "Bearer " + key},
        json=payload,
    )
    response.raise_for_status()
    return response.json()


def embeddings(client: httpx.Client, texts: list[str]) -> list[list[float]]:
    result = post(client, "/embeddings", EMBED_KEY, {
        "model": EMB_MODEL,
        "input": texts,
        "encoding_format": "float",
    })
    vectors: list[list[float] | None] = [None] * len(texts)
    for position, item in enumerate(result["data"]):
        index = int(item.get("index", position))
        if not 0 <= index < len(texts) or vectors[index] is not None:
            raise ValueError("Некорректный индекс embedding")
        vector = [float(value) for value in item["embedding"]]
        if not vector or not all(map(math.isfinite, vector)):
            raise ValueError("API вернул некорректный вектор")
        norm = math.hypot(*vector) or 1.0
        vectors[index] = [value / norm for value in vector]
    if any(v is None for v in vectors):
        raise ValueError("Получены не все embeddings")
    return [vector for vector in vectors if vector is not None]


class ApiEmbedder:
    def __init__(self, client: httpx.Client) -> None:
        self.client = client

    def embed_query(self, text: str) -> list[float]:
        return embeddings(self.client, [text])[0]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        vectors = []
        for start in range(0, len(texts), EMBED_BATCH_SIZE):
            vectors.extend(embeddings(self.client, texts[start:start + EMBED_BATCH_SIZE]))
        return vectors


def rerank(client: httpx.Client, question: str, candidates: list[Fragment]) -> list[int]:
    result = post(client, "/rerank", RERANK_KEY, {
        "model": RERANKER_MODEL,
        "query": question,
        "documents": [fragment.text for fragment in candidates],
        "top_n": min(RERANKER_TOP_N, len(candidates)),
    })
    items = result.get("results", result.get("data", []))
    indices = [int(item["index"]) for item in items]
    return [i for i in dict.fromkeys(indices) if 0 <= i < len(candidates)][:RERANKER_TOP_N]


def describe_api_error(error: Exception) -> str:
    if isinstance(error, httpx.HTTPStatusError):
        return f"{error.request.url.path}: HTTP {error.response.status_code}"
    return type(error).__name__


def create_search(corpus: Corpus, client: httpx.Client) -> SearchService | None:
    fragment_ids = list(corpus.fragments)
    embedder = ApiEmbedder(client)
    try:
        vectors = embedder.embed_documents([corpus.fragments[key].text for key in fragment_ids])
        return SearchService(corpus, fragment_ids, vectors, embedder)
    except API_ERRORS as exc:
        print(f"Индекс недоступен ({describe_api_error(exc)}). Поиск по словам.", file=sys.stderr)
        return None


def select_by_words(question: str, corpus: Corpus) -> list[Fragment]:
    query_words = words(question)
    return sorted(
        corpus.fragments.values(),
        key=lambda fragment: len(query_words & words(fragment.title + " " + fragment.text)),
        reverse=True,
    )[:TOP_K]


def select_fragments(
    client: httpx.Client, question: str, corpus: Corpus, search: SearchService | None
) -> list[Fragment]:
    if search is None:
        candidates = select_by_words(question, corpus)
    else:
        try:
            result = search.search(SearchQuery(text=question, top_k=TOP_K))
            candidates = [hit.fragment for hit in result.hits]
        except API_ERRORS as exc:
            print(f"Векторный поиск недоступен ({describe_api_error(exc)}). Поиск по словам.", file=sys.stderr)
            candidates = select_by_words(question, corpus)

    if RERANKER_MODEL and candidates:
        try:
            indices = rerank(client, question, candidates)
            if indices:
                return [candidates[i] for i in indices]
        except API_ERRORS as exc:
            print(f"Реранкер недоступен ({describe_api_error(exc)}). Сохраняю порядок поиска.", file=sys.stderr)
    return candidates


def generate(client: httpx.Client, question: str, fragments: list[Fragment]) -> str:
    context = "\n\n".join(
        f"Документ: {fragment.title}\nID: {fragment.fragment_id}\n{fragment.text}"
        for fragment in fragments
    )
    payload = {
        "model": LLM_MODEL,
        "messages": [
            {"role": "system",
             "content": "Ответь на последний вопрос пользователя по приложенным фрагментам. "
                        "Для каждого юридически значимого вывода укажи документ и номер пункта, если он есть в тексте. "
                        "Если данных не хватает, сообщи, каких именно. Не выдумывай основания."},
            {"role": "user", "content": "Фрагменты:\n" + context + "\n\nВопрос:\n" + question},
        ],
        "temperature": TEMPERATURE,
        "max_tokens": MAX_TOKENS,
    }
    for attempt in range(2):
        try:
            result = post(client, "/chat/completions", LLM_KEY, payload)
            content = result["choices"][0]["message"].get("content", "")
            if isinstance(content, str) and content.strip():
                return " ".join(content.split())
            raise ValueError("Модель вернула пустой ответ")
        except API_ERRORS as exc:
            print(f"LLM attempt {attempt + 1}: {describe_api_error(exc)}", file=sys.stderr)
            if attempt == 0:
                time.sleep(1)
    return FALLBACK


def main() -> None:
    if not API_BASE or not LLM_KEY:
        raise ValueError("Нужны LLM_BASE_URL и LLM_API_KEY (или их аналоги)")
    questions = load_questions(find_file("questions.csv"))
    documents = load_documents(find_file("kb.zip", "knowledge-base.zip", "knowledge_base.zip"))
    corpus = CorpusIndexer().build_documents(documents)
    if not corpus.fragments:
        raise ValueError("В базе знаний нет фрагментов")
    print(
        f"Вопросы: {len(questions)}; документы: {len(documents)}; "
        f"фрагменты: {len(corpus.fragments)}; TOP_K={TOP_K}",
        flush=True,
    )

    answers = [FALLBACK] * len(questions)
    with httpx.Client(timeout=90.0) as client:
        search = create_search(corpus, client)

        def work(position: int, question: str) -> tuple[int, str]:
            try:
                selected = select_fragments(client, question, corpus, search)
                return position, generate(client, question, selected)
            except Exception as exc:
                print(f"Ошибка вопроса {position}: {describe_api_error(exc)}", file=sys.stderr)
                return position, FALLBACK

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            futures = [pool.submit(work, i, question) for i, (_, question) in enumerate(questions)]
            for finished, future in enumerate(as_completed(futures), 1):
                index, answer = future.result()
                answers[index] = answer
                if finished % 10 == 0 or finished == len(questions):
                    print(f"Обработано {finished}/{len(questions)}", flush=True)

    with open("submission.csv", "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, quoting=csv.QUOTE_ALL, lineterminator="\n")
        writer.writerow(["id", "answer"])
        for i, (qid, _) in enumerate(questions):
            writer.writerow([qid, answers[i]])
    print(f"Создан submission.csv: {len(questions)} ответов", flush=True)


if __name__ == "__main__":
    main()
