#!/usr/bin/env bash
# Enterprise API Copilot — install everything needed for local development.
#
#   ./setup.sh                  # Python (+debugpy), frontend, CLI, backend deps and .env
#   ./setup.sh --skip-backend   # skip the Maven dependency download (slowest step)
#
# Safe to re-run. Components whose toolchain is missing are skipped with a warning; only
# Python (via uv, or Python 3.12/3.13) is required. DEVELOPMENT ONLY: the generated .env
# holds random dev-only secrets and is git-ignored.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

SKIP_FRONTEND=0
SKIP_CLI=0
SKIP_BACKEND=0
for arg in "$@"; do
  case "$arg" in
    --skip-frontend) SKIP_FRONTEND=1 ;;
    --skip-cli) SKIP_CLI=1 ;;
    --skip-backend) SKIP_BACKEND=1 ;;
    -h | --help)
      sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *)
      echo "unknown option: $arg (see --help)" >&2
      exit 2
      ;;
  esac
done

step() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
ok() { printf '\033[32m  ✓ %s\033[0m\n' "$*"; }
warn() { printf '\033[33m  ! %s\033[0m\n' "$*"; }
die() {
  printf '\033[31m  ✗ %s\033[0m\n' "$*" >&2
  exit 1
}
have() { command -v "$1" >/dev/null 2>&1; }

# ─── Python AI service, sandbox, evals ───────────────────────────────────────
step "Python environment (.venv)"
if have uv; then
  # uv downloads a matching interpreter (requires-python >=3.12,<3.14) when none is installed.
  uv sync --extra dev
elif PY="$(command -v python3.13 || command -v python3.12)"; then
  warn "uv not found, falling back to $PY -m venv (install uv for faster installs)"
  [ -x .venv/bin/python ] || "$PY" -m venv .venv
  .venv/bin/python -m pip install --upgrade pip
  .venv/bin/python -m pip install -e ".[dev]"
else
  die "need uv (https://docs.astral.sh/uv/) or Python 3.12/3.13 on PATH"
fi
.venv/bin/python -c "import debugpy, ai, sandbox" || die "Python install is incomplete"
ok "$(.venv/bin/python --version) with debugpy $(.venv/bin/python -c 'import debugpy;print(debugpy.__version__)')"

# ─── Frontend ────────────────────────────────────────────────────────────────
step "Frontend (apps/frontend)"
if [ "$SKIP_FRONTEND" = 1 ]; then
  warn "skipped (--skip-frontend)"
elif have npm; then
  (cd apps/frontend && npm ci --no-audit --no-fund)
  ok "node $(node -v)"
else
  warn "npm not found, skipping (needs Node.js 22+)"
fi

# ─── CLI ─────────────────────────────────────────────────────────────────────
step "CLI (apps/cli)"
if [ "$SKIP_CLI" = 1 ]; then
  warn "skipped (--skip-cli)"
elif have go; then
  (cd apps/cli && go mod download && go build -o bin/copilot ./cmd/copilot)
  ok "built apps/cli/bin/copilot"
else
  warn "go not found, skipping (needs Go 1.22+)"
fi

# ─── Backend ─────────────────────────────────────────────────────────────────
step "Spring Boot backend (apps/backend)"
if [ "$SKIP_BACKEND" = 1 ]; then
  warn "skipped (--skip-backend)"
elif have mvn && have java; then
  # Pre-fetch dependencies so `./dev.sh --with-backend` starts without a long download.
  if (cd apps/backend && mvn -B -q dependency:go-offline); then
    ok "Maven dependencies downloaded"
  else
    warn "Maven dependency download failed; it will be retried on first run"
  fi
else
  warn "mvn/java not found, skipping (needs Java 21 and Maven 3.9+)"
fi
have docker || warn "docker not found: needed only for ./dev.sh --with-backend (PostgreSQL + Redis)"

# ─── .env ────────────────────────────────────────────────────────────────────
step "Local configuration (.env)"
if [ ! -f .env ]; then
  cp .env.example .env
  ok "created .env from .env.example"
fi

env_value() { sed -n "s/^$1=//p" .env | tail -n 1; }

# Fill KEY in .env only when it is present but blank, so existing values are never touched.
set_if_blank() {
  local key="$1" value="$2" tmp
  if grep -q "^$key=$" .env; then
    tmp="$(mktemp)"
    awk -v k="$key" -v v="$value" 'BEGIN { FS = OFS = "=" } $0 == k "=" { print k, v; next } { print }' .env >"$tmp"
    mv "$tmp" .env
    ok "generated dev-only $key"
  fi
}

random_secret() { .venv/bin/python -c 'import secrets;print(secrets.token_urlsafe(48))'; }

# Stable secrets keep approvals, CLI logins and sandbox credentials valid across restarts.
sandbox_secret="$(env_value SANDBOX_CLIENT_SECRET)"
[ -n "$sandbox_secret" ] || sandbox_secret="local-dev-$(random_secret)"
set_if_blank SANDBOX_CLIENT_SECRET "$sandbox_secret"
set_if_blank COPILOT_GATEWAY_SANDBOX_CLIENT_SECRET "$sandbox_secret"
set_if_blank COPILOT_APPROVAL_KEY "$(random_secret)"
set_if_blank COPILOT_PLATFORM_TOKEN_KEY "$(random_secret)"
set_if_blank COPILOT_SERVICE_TOKEN_KEY "$(random_secret)"
mkdir -p .copilot

step "Done"
cat <<'EOF'
  ./dev.sh                 start sandbox, platform API, agent API and web app
  ./dev.sh --debug         same, with debugpy listening (attach from VS Code: "Attach: all Python services")
  ./dev.sh --help          all options
EOF
