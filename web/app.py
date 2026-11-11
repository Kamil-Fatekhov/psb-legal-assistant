"""HTTP-сервер веб-чата.

POST /api/chat                 AskRequest -> Answer (+ справочник источников)
GET  /api/sources/{fragment_id} Fragment + context_text, неизвестный ID -> 404
GET  /api/health               режим и размер каталога
GET  /                         интерфейс чата (web/static)

Коды ошибок: 404 — нет источника, 422 — неверный запрос,
503 — сбой зависимости или ядро не подключено, 502 — ядро нарушило контракт.

Запуск: uvicorn web.app:create_app --factory --port 8000
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Callable
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from contracts import DependencyUnavailable, SourceNotFound
from web.chat import ContractViolation, CoreNotReady
from web.schemas import ChatRequestIn, ChatResponseOut, ErrorOut, SourceOut, chat_response_out, source_out
from web.wiring import Runtime, Settings, build_runtime

log = logging.getLogger("web.app")
STATIC_DIR = Path(__file__).resolve().parent / "static"

SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
        "connect-src 'self'; font-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
}


def _error(status: int, code: str, message: str, request: Request) -> JSONResponse:
    body = ErrorOut(error={"code": code, "message": message}, request_id=request.state.request_id)
    return JSONResponse(status_code=status, content=body.model_dump())


def create_app(runtime_factory: Callable[[], Runtime] | None = None) -> FastAPI:
    """Фабрика приложения. В тестах передаётся своя сборка сервисов."""
    if runtime_factory is None:
        runtime_factory = lambda: build_runtime(Settings.from_env())  # noqa: E731

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        runtime = runtime_factory()
        app.state.runtime = runtime
        log.info("stage=startup mode=%s fragments=%d", runtime.mode, runtime.fragments)
        try:
            yield
        finally:
            runtime.close()

    app = FastAPI(
        title="ПСБ · Юридический ассистент",
        version="1.0.0",
        lifespan=lifespan,
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID", "")[:64] or uuid.uuid4().hex[:12]
        request.state.request_id = request_id
        started = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = (time.perf_counter() - started) * 1000
        response.headers["X-Request-ID"] = request_id
        for name, value in SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        if request.url.path.startswith("/api/"):
            # В лог не пишем текст вопроса и заголовки: только ID, стадию и время.
            log.info(
                "request_id=%s stage=%s status=%d ms=%.0f",
                request_id, request.url.path.split("/")[2], response.status_code, elapsed_ms,
            )
        return response

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, exc: RequestValidationError):
        problems = []
        for err in exc.errors():
            where = ".".join(str(p) for p in err.get("loc", ()) if p != "body")
            problems.append(f"{where}: {err.get('msg', '')}" if where else err.get("msg", ""))
        return _error(422, "invalid_request", "; ".join(problems) or "Неверный запрос", request)

    @app.exception_handler(SourceNotFound)
    async def source_not_found(request: Request, exc: SourceNotFound):
        return _error(404, "source_not_found", "Фрагмент с таким ID не найден в каталоге", request)

    @app.exception_handler(DependencyUnavailable)
    async def dependency_unavailable(request: Request, exc: DependencyUnavailable):
        log.warning("request_id=%s stage=chat error=DependencyUnavailable", request.state.request_id)
        return _error(503, "dependency_unavailable",
                      "Поиск или языковая модель сейчас недоступны. Повторите запрос позже.", request)

    @app.exception_handler(CoreNotReady)
    async def core_not_ready(request: Request, exc: CoreNotReady):
        return _error(503, "core_not_ready", "Ядро ассистента ещё не подключено.", request)

    @app.exception_handler(ContractViolation)
    async def contract_violation(request: Request, exc: ContractViolation):
        log.error("request_id=%s stage=chat error=ContractViolation detail=%s", request.state.request_id, exc)
        return _error(502, "invalid_core_answer",
                      "Ассистент сформировал ответ без проверяемых ссылок, поэтому он не показан.", request)

    @app.exception_handler(Exception)
    async def unexpected(request: Request, exc: Exception):
        log.exception("request_id=%s stage=unexpected error=%s", request.state.request_id, type(exc).__name__)
        return _error(500, "internal_error", "Внутренняя ошибка сервера.", request)

    errors = {
        404: {"model": ErrorOut}, 422: {"model": ErrorOut},
        502: {"model": ErrorOut}, 503: {"model": ErrorOut},
    }

    @app.get("/api/health")
    def health(request: Request) -> dict:
        runtime: Runtime = request.app.state.runtime
        return {"status": "ok", "mode": runtime.mode, "fragments": runtime.fragments}

    # Синхронные обработчики FastAPI выполняет в пуле потоков: долгий вызов
    # модели не блокирует остальные запросы.
    @app.post("/api/chat", response_model=ChatResponseOut, responses=errors)
    def chat(body: ChatRequestIn, request: Request) -> ChatResponseOut:
        controller = request.app.state.runtime.controller
        answer = controller.post_message(body.to_contract())
        return chat_response_out(answer, controller.describe_sources(answer), request.state.request_id)

    @app.get("/api/sources/{fragment_id:path}", response_model=SourceOut, responses=errors)
    def get_source(fragment_id: str, request: Request) -> SourceOut:
        return source_out(request.app.state.runtime.controller.get_source(fragment_id))

    @app.api_route("/api/{rest:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
                   include_in_schema=False)
    def api_not_found(rest: str, request: Request):
        return _error(404, "not_found", "Неизвестный адрес API", request)

    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
    return app
