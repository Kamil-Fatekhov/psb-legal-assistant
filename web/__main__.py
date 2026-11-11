"""Запуск веб-чата: python -m web

Переменные: HOST (по умолчанию 127.0.0.1), PORT (8000), LOG_LEVEL (info).
"""

import logging
import os

import uvicorn
from dotenv import load_dotenv


def main() -> None:
    load_dotenv(override=False)
    level = os.getenv("LOG_LEVEL", "info").lower()
    logging.basicConfig(
        level=level.upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    uvicorn.run(
        "web.app:create_app",
        factory=True,
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "8000")),
        log_level=level,
        access_log=False,
    )


if __name__ == "__main__":
    main()
