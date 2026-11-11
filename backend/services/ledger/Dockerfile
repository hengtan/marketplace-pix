FROM python:3.13-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:0.13.7 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /srv/backend/services/ledger
COPY backend/libs/marketplace_common /srv/backend/libs/marketplace_common
COPY backend/services/ledger/pyproject.toml backend/services/ledger/uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev --no-editable
COPY backend/services/ledger/src ./src
COPY backend/services/ledger/alembic ./alembic
COPY backend/services/ledger/alembic.ini ./
RUN uv sync --frozen --no-dev --no-editable

FROM python:3.13-slim
RUN useradd --create-home --uid 10001 app
WORKDIR /srv/backend/services/ledger
COPY --from=builder --chown=app:app /srv/backend/services/ledger /srv/backend/services/ledger
ENV PATH="/srv/backend/services/ledger/.venv/bin:$PATH" PYTHONUNBUFFERED=1
USER app
EXPOSE 8000
CMD ["uvicorn", "ledger.main:app", "--host", "0.0.0.0", "--port", "8000"]
