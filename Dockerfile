# syntax=docker/dockerfile:1.7
# Multi-stage build for the FastAPI API service.
# Stage 1 builds wheels (incl. dev/build toolchain); Stage 2 is a lean,
# non-root runtime with no compilers or dev dependencies.

# ----------------------------------------------------------------------------
# Builder: compile dependency wheels once, cache them for the runtime stage.
# ----------------------------------------------------------------------------
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Build deps for argon2-cffi, asyncpg, and any C extensions.
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

# Only project metadata is needed to resolve and pre-build dependency wheels.
COPY pyproject.toml ./
# Provide the package tree referenced by [tool.setuptools] so the project itself
# can be wheel-built; copy sources used by the build backend.
COPY src ./src

# Build wheels for all runtime dependencies (NOT the optional [dev] extras).
RUN pip wheel --wheel-dir /wheels .

# ----------------------------------------------------------------------------
# Frontend builder: compile the React dashboard to static assets (dist/).
# Served by FastAPI in the runtime stage so one service hosts API + dashboard.
# ----------------------------------------------------------------------------
FROM node:20-slim AS frontend
WORKDIR /frontend
# Install deps against the lockfile first (cached unless deps change).
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
# Build the SPA. No VITE_API_BASE -> the dashboard calls /api on its own origin
# (same Render service), so no CORS and no second URL.
COPY frontend/ ./
RUN npm run build

# ----------------------------------------------------------------------------
# Runtime: minimal image, non-root, only runtime deps installed from wheels.
# ----------------------------------------------------------------------------
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app/src:/app \
    APP_WORKERS=4 \
    APP_PORT=8000

# curl is required by the HEALTHCHECK probe.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 app

WORKDIR /app

# Install runtime dependencies from pre-built wheels (no network, no compilers).
COPY --from=builder /wheels /wheels
COPY pyproject.toml ./
COPY src ./src
COPY apps ./apps
COPY alembic ./alembic
COPY alembic.ini ./alembic.ini
# Compiled React dashboard — FastAPI serves it from /app/static (main.py).
COPY --from=frontend /frontend/dist ./static

# Install deps from local wheels, then the project itself (editable for the
# src-layout package). --no-index ensures we never reach out to PyPI at runtime.
# Install the project itself from the pre-built wheels; pip resolves ALL its
# declared dependencies from /wheels too (no hardcoded list to drift from
# pyproject.toml — the previous list still named passlib after the switch to
# argon2-cffi and omitted numpy/structlog/prometheus-client, which broke the
# build). --no-index guarantees we never reach PyPI.
RUN pip install --no-index --find-links=/wheels restaurant-platform \
    && rm -rf /wheels

# var/ holds uploads (menu images); make it writable by the app user.
RUN mkdir -p /app/var/uploads && chown -R app:app /app/var

USER app

EXPOSE 8000

# Liveness probe hits the FastAPI /health endpoint.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS "http://localhost:${APP_PORT}/health" || exit 1

# On boot: apply DB migrations, then serve. Best-effort migrate (|| echo) so a
# transient/misconfigured DB logs loudly but still starts the API and keeps
# /health green — the next deploy re-runs `alembic upgrade head` (idempotent).
#
# Port: bind the platform-assigned ${PORT} (Render/Heroku/Cloud Run inject it);
# fall back to ${APP_PORT} for local/docker-compose. Binding the wrong port is
# why Render logged "No open ports detected" and never cut the deploy over.
#
# Workers: honour ${WEB_CONCURRENCY} (Render sets =1 for the instance size); fall
# back to ${APP_WORKERS}. On the 512 MB free tier, 4 uvicorn workers each load the
# full app and OOM-thrash ("Child process died" loop), so the deploy never goes
# live — one worker fits the memory budget.
CMD sh -c 'alembic upgrade head || echo "[startup] alembic upgrade head FAILED — check APP_DATABASE_URL"; exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-$APP_PORT}" --workers "${WEB_CONCURRENCY:-$APP_WORKERS}"'
