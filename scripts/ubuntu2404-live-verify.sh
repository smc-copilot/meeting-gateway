#!/usr/bin/env bash
# Ubuntu 24.04 read-only verification for the Meeting gateway.
# Default: check the host, compose file and a running API. It does not start containers.
#   --up      build and start deploy/compose.yaml (requires a private .env)
#   --offline run the synthetic pytest suite with uv
#   --live    require MEETING_LIVE=1 plus gateway URL and token; unreachable is a failure
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

UP=0
OFFLINE=0
LIVE=0
for arg in "$@"; do
  case "$arg" in
    --up) UP=1 ;;
    --offline) OFFLINE=1 ;;
    --live) LIVE=1 ;;
    *) echo "Unknown argument: $arg" >&2; echo "Usage: $0 [--up] [--offline] [--live]" >&2; exit 2 ;;
  esac
done

pass() { printf 'PASS %s\n' "$1"; }
skip() { printf 'SKIP %s\n' "$1"; }
fail() { printf 'FAIL %s\n' "$1" >&2; exit 1; }

if [[ ! -r /etc/os-release ]]; then
  fail "os-release-missing"
fi
# shellcheck disable=SC1091
source /etc/os-release
if [[ "${ID:-}" != "ubuntu" || "${VERSION_ID:-}" != "24.04" ]]; then
  fail "expected-ubuntu-24.04-got-${ID:-unknown}-${VERSION_ID:-unknown}"
fi
pass "ubuntu-24.04"

command -v docker >/dev/null || fail "docker-missing"
docker compose version >/dev/null || fail "docker-compose-missing"
pass "docker-compose"

if [[ "$OFFLINE" -eq 1 ]]; then
  command -v uv >/dev/null || fail "uv-missing"
  uv sync --frozen --group dev
  uv run python -m app.cli check
  uv run pytest tests/integration tests/acceptance tests/unit tests/live -q
  pass "offline-tests"
fi

if [[ ! -f .env ]]; then
  if [[ "$UP" -eq 1 || "$LIVE" -eq 1 ]]; then
    fail "env-file-missing"
  fi
  skip "compose-config-no-env"
else
  docker compose --env-file .env -f deploy/compose.yaml config --quiet
  pass "compose-config"
fi

if [[ "$UP" -eq 1 ]]; then
  docker compose --env-file .env -f deploy/compose.yaml up -d --build
  pass "compose-up"
fi

if [[ -f .env ]] && docker compose --env-file .env -f deploy/compose.yaml ps --status running --services 2>/dev/null | grep -qx api; then
  curl --silent --show-error --fail --max-time 5 http://127.0.0.1:4522/health/live >/dev/null
  pass "health-live"
  ready="$(curl --silent --show-error --fail --max-time 5 http://127.0.0.1:4522/health/ready)"
  python3 -c 'import json,sys; body=json.loads(sys.argv[1]);
raise SystemExit(0 if body.get("database") is True else 1)' "$ready"
  pass "health-ready-database"
  python3 -c 'import json,sys; body=json.loads(sys.argv[1]);
raise SystemExit(0 if body.get("backend") is True else 1)' "$ready" \
    && pass "health-ready-backend" || fail "backend-not-ready"
  if docker compose --env-file .env -f deploy/compose.yaml ps --status running --services | grep -qx worker; then
    pass "worker-running"
  else
    fail "worker-not-running"
  fi
else
  if [[ "$UP" -eq 1 || "$LIVE" -eq 1 ]]; then
    fail "api-not-running"
  fi
  skip "api-not-running"
fi

if [[ "$LIVE" -eq 1 ]]; then
  export MEETING_LIVE=1
  if [[ -z "${MEETING_BASE_URL:-}" || -z "${MEETING_ACCESS_TOKEN:-}" ]]; then
    fail "live-environment-missing"
  fi
  python3 scripts/tencent_live_smoke.py
  pass "readonly-smoke"
else
  skip "readonly-smoke-not-requested"
fi

printf 'DONE verification finished without printing secrets\n'
