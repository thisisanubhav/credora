FROM python:3.12.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/app/.venv/bin:$PATH
WORKDIR /app

RUN pip install --no-cache-dir uv==0.12.3
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project --no-cache
COPY apps ./apps
COPY services ./services

USER 10001:10001
CMD ["uvicorn", "apps.discovery_api.main:app", "--host", "0.0.0.0", "--port", "8001", "--no-access-log"]
