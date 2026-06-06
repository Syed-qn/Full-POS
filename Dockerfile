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

# Build deps for argon2 (passlib[argon2]), asyncpg, and any C extensions.
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

# Install deps from local wheels, then the project itself (editable for the
# src-layout package). --no-index ensures we never reach out to PyPI at runtime.
RUN pip install --no-index --find-links=/wheels \
        fastapi "uvicorn[standard]" pydantic pydantic-settings \
        "sqlalchemy[asyncio]" asyncpg alembic "celery[redis]" redis \
        "passlib[argon2]" pyjwt anthropic python-multipart \
    && pip install --no-deps -e . \
    && rm -rf /wheels

# var/ holds uploads (menu images); make it writable by the app user.
RUN mkdir -p /app/var/uploads && chown -R app:app /app/var

USER app

EXPOSE 8000

# Liveness probe hits the FastAPI /health endpoint.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS "http://localhost:${APP_PORT}/health" || exit 1

# Worker count is configurable via APP_WORKERS (set in compose / env).
# Shell form so ${APP_WORKERS}/${APP_PORT} expand at container start.
CMD uvicorn app.main:app --host 0.0.0.0 --port "${APP_PORT}" --workers "${APP_WORKERS}"
