# Веб-чат юридического ассистента: API + интерфейс в одном процессе.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt \
 && useradd --create-home --uid 10001 app

COPY contracts.py solution.py ./
COPY knowledge ./knowledge
COPY assistant ./assistant
COPY web ./web
COPY fixtures ./fixtures

USER app

ENV HOST=0.0.0.0 \
    PORT=8000 \
    DATA_DIR=/app/data

EXPOSE 8000

# Сборка индекса при старте в режиме core может занять пару минут.
HEALTHCHECK --interval=15s --timeout=5s --start-period=180s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4)"

CMD ["python", "-m", "web"]
