# syntax=docker/dockerfile:1

# ---------------------------------------------------------------------------
# Stage 1: build the React UI (Fluent UI + vite)
# vite writes to ../api/www relative to /build -> /api/www
# ---------------------------------------------------------------------------
FROM node:22-alpine AS ui-builder

WORKDIR /build
COPY app/ui/package.json app/ui/package-lock.json* ./
RUN npm install --no-audit --no-fund

COPY app/ui/ ./
RUN npm run build && cp -r /api/www /out-www

# ---------------------------------------------------------------------------
# Stage 2: Python 3.14 runtime (uv-managed) + FastAPI + review pipeline + UI
# ---------------------------------------------------------------------------
FROM python:3.14-slim AS runtime

COPY --from=ghcr.io/astral-sh/uv:0.13.8 /uv /uvx /bin/

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# Dependencies first (cached layer): lockfile-driven, no resolver drift.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# Application code: API + shared models + review pipeline.
COPY common/ ./common/
COPY flows/__init__.py ./flows/__init__.py
COPY flows/ai_doc_review/ ./flows/ai_doc_review/
COPY app/api/ ./app/api/

# Built UI from stage 1.
COPY --from=ui-builder /out-www ./app/api/www

# Non-root runtime; ./data is volume-mounted by docker-compose.
RUN useradd --create-home --uid 10001 reviewer \
    && mkdir -p /app/data \
    && chown -R reviewer:reviewer /app
USER reviewer

WORKDIR /app/app/api
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/api/health',timeout=4)" || exit 1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
