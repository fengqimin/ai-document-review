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
# Stage 2: Python runtime (FastAPI + review pipeline + built UI)
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Runtime deps (PyMuPDF ships manylinux wheels; no system libs needed).
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

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
