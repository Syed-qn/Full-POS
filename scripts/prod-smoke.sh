#!/usr/bin/env bash
# prod-smoke.sh — boot the production compose stack, assert the API is healthy
# and the WhatsApp webhook handshake works, then tear everything down.
#
# This validates the deployment artifacts end-to-end (it DOES build images).
# Overridable env:
#   COMPOSE_FILE   compose file (default docker-compose.prod.yml)
#   API_PORT       host port the API publishes (default 8000)
#   POSTGRES_PASSWORD  db password (default smoke-test-pw)
#   WAIT_SECONDS   max seconds to wait for api health (default 180)
set -euo pipefail

cd "$(dirname "$0")/.."

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
API_PORT="${API_PORT:-8000}"
WAIT_SECONDS="${WAIT_SECONDS:-180}"
VERIFY_TOKEN="smoke-verify-token"
CHALLENGE="smoke-challenge-$RANDOM"

export POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-smoke-test-pw}"
export API_PORT

COMPOSE=(docker compose -f "$COMPOSE_FILE")

# A throwaway .env so env_file resolves and the webhook verify token is known.
ENV_CREATED=0
cleanup() {
  echo "--- tearing down ---"
  "${COMPOSE[@]}" down -v --remove-orphans || true
  if [[ "$ENV_CREATED" == "1" ]]; then rm -f .env; fi
}
trap cleanup EXIT

if [[ ! -f .env ]]; then
  echo "--- writing temporary .env for smoke run ---"
  cp .env.example .env
  # Force a known verify token + cloud-style provider expectations for the test.
  {
    echo "APP_ENV=prod"
    echo "APP_WA_VERIFY_TOKEN=${VERIFY_TOKEN}"
  } >> .env
  ENV_CREATED=1
else
  # Use whatever token the existing .env defines.
  VERIFY_TOKEN="$(grep -E '^APP_WA_VERIFY_TOKEN=' .env | head -1 | cut -d= -f2-)"
  VERIFY_TOKEN="${VERIFY_TOKEN:-dev-verify-token}"
fi

echo "--- config validation ---"
"${COMPOSE[@]}" config >/dev/null
echo "compose config OK"

echo "--- building + starting stack ---"
"${COMPOSE[@]}" up -d --build

echo "--- waiting for api to become healthy (up to ${WAIT_SECONDS}s) ---"
deadline=$(( $(date +%s) + WAIT_SECONDS ))
healthy=0
until [[ $(date +%s) -ge $deadline ]]; do
  status="$("${COMPOSE[@]}" ps api --format '{{.Health}}' 2>/dev/null || true)"
  if [[ "$status" == "healthy" ]]; then healthy=1; break; fi
  # Surface migrate failures early.
  mstate="$("${COMPOSE[@]}" ps -a migrate --format '{{.State}} {{.ExitCode}}' 2>/dev/null || true)"
  if [[ "$mstate" == exited\ [1-9]* ]]; then
    echo "ERROR: migrate failed ($mstate)"; "${COMPOSE[@]}" logs migrate; exit 1
  fi
  sleep 3
done

if [[ "$healthy" != "1" ]]; then
  echo "ERROR: api did not become healthy in ${WAIT_SECONDS}s"
  "${COMPOSE[@]}" ps
  "${COMPOSE[@]}" logs api
  exit 1
fi
echo "api is healthy"

echo "--- GET /health ---"
health_body="$(curl -fsS "http://localhost:${API_PORT}/health")"
echo "response: ${health_body}"
echo "${health_body}" | grep -q '"status":"ok"' || { echo "ERROR: /health not ok"; exit 1; }

echo "--- webhook GET handshake ---"
hs="$(curl -fsS "http://localhost:${API_PORT}/webhooks/whatsapp?hub.mode=subscribe&hub.verify_token=${VERIFY_TOKEN}&hub.challenge=${CHALLENGE}")"
echo "challenge echoed: ${hs}"
[[ "$hs" == "$CHALLENGE" ]] || { echo "ERROR: handshake did not echo challenge"; exit 1; }

echo "--- webhook handshake rejects bad token (expect 403) ---"
code="$(curl -s -o /dev/null -w '%{http_code}' "http://localhost:${API_PORT}/webhooks/whatsapp?hub.mode=subscribe&hub.verify_token=WRONG&hub.challenge=x")"
[[ "$code" == "403" ]] || { echo "ERROR: bad token returned ${code}, expected 403"; exit 1; }
echo "bad token correctly rejected (403)"

echo ""
echo "SMOKE TEST PASSED"
