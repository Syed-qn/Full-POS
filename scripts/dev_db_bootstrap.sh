#!/usr/bin/env bash
set -euo pipefail
# Bring local dev + test DBs to head. Idempotent.
docker compose up -d db redis
# Wait for db health
until docker compose exec -T db pg_isready -U app >/dev/null 2>&1; do sleep 1; done
# Ensure test DB exists (ignore error if present)
docker compose exec -T db psql -U app -d restaurant -c "CREATE DATABASE restaurant_test;" 2>/dev/null || true
.venv/bin/alembic upgrade head
echo "dev_db_bootstrap: restaurant @ head"
