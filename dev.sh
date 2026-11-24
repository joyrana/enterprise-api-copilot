#!/usr/bin/env bash
# Enterprise API Copilot — run the services locally with prefixed, colour-coded logs.
#
#   ./dev.sh                         sandbox :8090, platform :8080, agent :8001, frontend :3000
#   ./dev.sh sandbox platform        only the named services
#   ./dev.sh --debug                 Python services run under debugpy (attach from VS Code)
#   ./dev.sh --debug --wait          ...and block until a debugger attaches
#   ./dev.sh --with-backend          serve the web app through the Spring Boot platform API
#                                    (:8081, JDWP :5005 with --debug) instead of the Python
#                                    reference facade: starts PostgreSQL (Docker, or a local
#                                    instance under .copilot/pg when Docker is not running),
#                                    sandbox, agent, Spring Boot and the frontend
#
# Services: sandbox platform agent frontend backend
# debugpy ports: sandbox 5678 · platform 5679 · agent 5680
# Ctrl-C stops everything; if one service exits, the others are stopped too.
# Run ./setup.sh first. DEVELOPMENT ONLY.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

ALL_SERVICES="sandbox platform agent frontend"
DEBUG=0
WAIT=0
WITH_BACKEND=0
SERVICES=""
for arg in "$@"; do
  case "$arg" in
    --debug) DEBUG=1 ;;
    --wait) WAIT=1 ;;
    --with-backend) WITH_BACKEND=1 ;;
    sandbox | platform | agent | frontend | backend) SERVICES="$SERVICES $arg" ;;
    -h | --help)
      sed -n '2,15p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *)
      echo "unknown argument: $arg (see --help)" >&2
      exit 2
      ;;
  esac
done
[ "$WAIT" = 0 ] || [ "$DEBUG" = 1 ] || {
  echo "--wait needs --debug" >&2
  exit 2
}
if [ -z "$SERVICES" ]; then
  SERVICES="$ALL_SERVICES"
  # Spring Boot replaces the Python platform facade in front of the agent service.
  [ "$WITH_BACKEND" = 0 ] || SERVICES="sandbox agent frontend backend"
fi
[ "$WITH_BACKEND" = 0 ] || case " $SERVICES " in *" backend "*) ;; *) SERVICES="$SERVICES backend" ;; esac

[ -x .venv/bin/python ] || {
  echo "no .venv found, run ./setup.sh first" >&2
  exit 1
}
[ -f .env ] || {
  echo "no .env found, run ./setup.sh first" >&2
  exit 1
}
set -a
# shellcheck disable=SC1091
. ./.env
set +a
export PYTHONUNBUFFERED=1
mkdir -p .copilot

PY="$ROOT/.venv/bin/python"
PIDS=""
NAMES=""

# Prefix every output line with the service name.
prefix() {
  local tag
  tag="$(printf '\033[%sm%-9s\033[0m|' "$2" "$1")"
  while IFS= read -r line; do printf '%s %s\n' "$tag" "$line"; done
}

# python_cmd DEBUG_PORT MODULE ARGS... — plain python, or python under debugpy with --debug.
python_cmd() {
  local port="$1"
  shift
  if [ "$DEBUG" = 1 ]; then
    local wait_flag=""
    [ "$WAIT" = 0 ] || wait_flag="--wait-for-client"
    # shellcheck disable=SC2086
    exec "$PY" -Xfrozen_modules=off -m debugpy --listen "127.0.0.1:$port" $wait_flag -m "$@"
  fi
  exec "$PY" -m "$@"
}

start() {
  local name="$1" colour="$2"
  shift 2
  ("$@" 2>&1 | prefix "$name" "$colour") &
  PIDS="$PIDS $!"
  NAMES="$NAMES $name"
}

run_sandbox() { python_cmd 5678 sandbox --port 8090; }
run_platform() { python_cmd 5679 ai.api platform --port 8080; }
run_agent() {
  # Platform and agent share COPILOT_STATE_DB; migrating it concurrently fails with
  # "database is locked", so let the platform finish start-up first.
  case " $SERVICES " in
    *" platform "*)
      echo "waiting for platform to be healthy (shared state DB)"
      until curl -sf -o /dev/null http://127.0.0.1:8080/api/v1/health; do sleep 1; done
      ;;
  esac
  python_cmd 5680 ai.api agent --port 8001
}
run_frontend() {
  cd apps/frontend
  [ -d node_modules ] || npm ci --no-audit --no-fund
  # The Vite dev server proxies /api to the platform API (8080 reference facade, 8081 Spring).
  case " $SERVICES " in
    *" backend "*) export VITE_API_PROXY="http://localhost:8081" ;;
  esac
  exec npm run dev
}
# PostgreSQL for the Spring backend: the Compose service when Docker is running, otherwise a
# throwaway local instance (initdb/pg_ctl from PATH or Homebrew) kept under .copilot/pg.
start_postgres() {
  PGUSER_="${POSTGRES_USER:-api_copilot}"
  PGDB_="${POSTGRES_DB:-api_copilot}"
  if command -v docker >/dev/null && docker info >/dev/null 2>&1; then
    docker compose -f docker/docker-compose.yml up -d --wait postgres
    export POSTGRES_HOST=localhost POSTGRES_PORT=5432
    export POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-dev-only-postgres-password}"
    return
  fi
  local bin
  for bin in "$(dirname "$(command -v initdb 2>/dev/null || true)")" /opt/homebrew/opt/postgresql@18/bin /opt/homebrew/opt/postgresql@17/bin; do
    [ -x "$bin/initdb" ] && break
    bin=""
  done
  [ -n "$bin" ] || {
    echo "the backend needs PostgreSQL: start Docker, or install PostgreSQL (initdb/pg_ctl)" >&2
    exit 1
  }
  local dir="$ROOT/.copilot/pg" port=55432
  [ -d "$dir/data" ] || {
    mkdir -p "$dir"
    "$bin/initdb" -D "$dir/data" -A trust -U "$PGUSER_" -E UTF8 >/dev/null
  }
  "$bin/pg_ctl" -D "$dir/data" status >/dev/null 2>&1 ||
    "$bin/pg_ctl" -D "$dir/data" -w -l "$dir/pg.log" \
      -o "-p $port -k $dir -c listen_addresses=127.0.0.1" start >/dev/null
  "$bin/psql" -h 127.0.0.1 -p "$port" -U "$PGUSER_" -d postgres -tc \
    "SELECT 1 FROM pg_database WHERE datname='$PGDB_'" | grep -q 1 ||
    "$bin/createdb" -h 127.0.0.1 -p "$port" -U "$PGUSER_" "$PGDB_"
  export POSTGRES_HOST=127.0.0.1 POSTGRES_PORT="$port" POSTGRES_PASSWORD=""
}

run_backend() {
  start_postgres
  local jvm_args=""
  [ "$DEBUG" = 0 ] || jvm_args="-agentlib:jdwp=transport=dt_socket,server=y,suspend=n,address=127.0.0.1:5005"
  cd apps/backend
  # Same keys as the Python services (.env): the agent verifies the platform's service tokens
  # and approval tokens with them.
  : "${COPILOT_PLATFORM_TOKEN_KEY:=$(head -c 48 /dev/urandom | base64 | tr -d '\n=+/')}"
  : "${COPILOT_SERVICE_TOKEN_KEY:?COPILOT_SERVICE_TOKEN_KEY must be set in .env (shared with the agent)}"
  : "${COPILOT_APPROVAL_KEY:?COPILOT_APPROVAL_KEY must be set in .env (shared with the agent)}"
  export COPILOT_PLATFORM_TOKEN_KEY COPILOT_SERVICE_TOKEN_KEY COPILOT_APPROVAL_KEY
  BACKEND_PORT=8081 COPILOT_AGENT_URL=http://127.0.0.1:8001 SPRING_PROFILES_ACTIVE=local \
    exec mvn -B spring-boot:run -Dspring-boot.run.jvmArguments="$jvm_args"
}

cleanup() {
  trap - INT TERM EXIT
  printf '\n\033[1mStopping services...\033[0m\n'
  # Everything started here shares this script's process group.
  kill 0 2>/dev/null || true
}
trap cleanup INT TERM EXIT

colour=31
for svc in $SERVICES; do
  colour=$((colour + 1))
  [ "$colour" -le 36 ] || colour=32
  start "$svc" "$colour" "run_$svc"
done

printf '\033[1mStarted:%s\033[0m\n' "$NAMES"
for svc in $SERVICES; do
  case "$svc" in
    sandbox) echo "  sandbox    http://127.0.0.1:8090$([ "$DEBUG" = 0 ] || echo '   debugpy 5678')" ;;
    platform) echo "  platform   http://127.0.0.1:8080$([ "$DEBUG" = 0 ] || echo '   debugpy 5679')" ;;
    agent) echo "  agent      http://127.0.0.1:8001$([ "$DEBUG" = 0 ] || echo '   debugpy 5680')" ;;
    frontend) echo "  frontend   http://localhost:3000" ;;
    backend) echo "  backend    http://127.0.0.1:8081$([ "$DEBUG" = 0 ] || echo '   JDWP 5005')" ;;
  esac
done
[ "$WAIT" = 0 ] || echo "  waiting for a debugger to attach before the Python services start"

# bash 3.2 (macOS) has no `wait -n`, so poll: stop everything when any service exits.
while sleep 1; do
  i=0
  for pid in $PIDS; do
    i=$((i + 1))
    if ! kill -0 "$pid" 2>/dev/null; then
      name="$(echo "$NAMES" | awk -v n="$i" '{ print $n }')"
      printf '\033[31m%s exited\033[0m\n' "$name"
      exit 1
    fi
  done
done
