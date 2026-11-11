FROM python:3.13-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:0.13.7 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /srv/backend/gateway
COPY backend/libs/marketplace_common /srv/backend/libs/marketplace_common
COPY backend/gateway/pyproject.toml backend/gateway/uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev --no-editable
COPY backend/gateway/src ./src
RUN uv sync --frozen --no-dev --no-editable

FROM python:3.13-slim
RUN useradd --create-home --uid 10001 app
WORKDIR /srv/backend/gateway
COPY --from=builder --chown=app:app /srv/backend/gateway /srv/backend/gateway
ENV PATH="/srv/backend/gateway/.venv/bin:$PATH" PYTHONUNBUFFERED=1
USER app
EXPOSE 8000
CMD ["uvicorn", "gateway.main:app", "--host", "0.0.0.0", "--port", "8000"]
