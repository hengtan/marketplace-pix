FROM python:3.13-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:0.13.7 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /srv/backend/services/assistant
COPY backend/libs/marketplace_common /srv/backend/libs/marketplace_common
COPY backend/services/assistant/pyproject.toml backend/services/assistant/uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev --no-editable
COPY backend/services/assistant/src ./src
COPY backend/services/assistant/alembic ./alembic
COPY backend/services/assistant/alembic.ini ./
COPY backend/services/assistant/evals ./evals
RUN uv sync --frozen --no-dev --no-editable

FROM python:3.13-slim
RUN useradd --create-home --uid 10001 app
WORKDIR /srv/backend/services/assistant
COPY --from=builder --chown=app:app /srv/backend/services/assistant /srv/backend/services/assistant
ENV PATH="/srv/backend/services/assistant/.venv/bin:$PATH" PYTHONUNBUFFERED=1
USER app
EXPOSE 8000
CMD ["uvicorn", "assistant.main:app", "--host", "0.0.0.0", "--port", "8000"]
