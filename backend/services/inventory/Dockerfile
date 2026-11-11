FROM python:3.13-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:0.13.7 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /srv/backend/services/inventory
COPY backend/libs/marketplace_common /srv/backend/libs/marketplace_common
COPY backend/services/inventory/pyproject.toml backend/services/inventory/uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev --no-editable
COPY backend/services/inventory/src ./src
COPY backend/services/inventory/alembic ./alembic
COPY backend/services/inventory/alembic.ini ./
RUN uv sync --frozen --no-dev --no-editable

FROM python:3.13-slim
RUN useradd --create-home --uid 10001 app
WORKDIR /srv/backend/services/inventory
COPY --from=builder --chown=app:app /srv/backend/services/inventory /srv/backend/services/inventory
ENV PATH="/srv/backend/services/inventory/.venv/bin:$PATH" PYTHONUNBUFFERED=1
USER app
EXPOSE 8000
CMD ["uvicorn", "inventory.main:app", "--host", "0.0.0.0", "--port", "8000"]
