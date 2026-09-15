#!/usr/bin/env bash
# Start API Maintainer: verify prerequisites, then serve the local web UI.
#
#   ./start.sh                 check everything, then start the server
#   ./start.sh --check         run the checks and exit (no server)
#   ./start.sh --no-build      skip the frontend build, serve the existing bundle
#   ./start.sh --rebuild-image force a rebuild of the execution image
#   ./start.sh --port 8001     serve on a different port
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$ROOT/backend/.venv"
IMAGE="api-maintainer-python:local"
PORT="${PORT:-8000}"
CHECK_ONLY=0
BUILD_FRONTEND=1
REBUILD_IMAGE=0

while [ $# -gt 0 ]; do
  case "$1" in
    --check)         CHECK_ONLY=1 ;;
    --no-build)      BUILD_FRONTEND=0 ;;
    --rebuild-image) REBUILD_IMAGE=1 ;;
    --port)          PORT="${2:?--port needs a value}"; shift ;;
    -h|--help)       sed -n '2,/^$/p' "${BASH_SOURCE[0]}" | grep '^#' | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Unknown option: $1 (try --help)" >&2; exit 2 ;;
  esac
  shift
done

if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
  R=$'\033[31m'; G=$'\033[32m'; Y=$'\033[33m'; B=$'\033[1m'; N=$'\033[0m'
else
  R=""; G=""; Y=""; B=""; N=""
fi
ok()   { printf '  %s✓%s %s\n' "$G" "$N" "$1"; }
warn() { printf '  %s!%s %s\n' "$Y" "$N" "$1"; }
die()  { printf '  %s✗%s %s\n' "$R" "$N" "$1" >&2; [ $# -gt 1 ] && printf '    %s\n' "$2" >&2; exit 1; }
step() { printf '\n%s%s%s\n' "$B" "$1" "$N"; }

step "API Maintainer"
printf '  %s\n' "$ROOT"

# ---------------------------------------------------------------- python env
step "1. Backend environment"
[ -x "$VENV/bin/python" ] || die "Python virtualenv missing at backend/.venv" \
  "Run: uv sync --project backend --frozen"
[ -x "$VENV/bin/api-maintainer" ] || die "api-maintainer entry point missing" \
  "Run: uv sync --project backend --frozen"
ok "virtualenv present ($("$VENV/bin/python" --version 2>&1))"

# ------------------------------------------------------------------- docker
step "2. Docker"
command -v docker >/dev/null 2>&1 || die "docker CLI not found on PATH"
if ! docker info >/dev/null 2>&1; then
  if [ "$(uname -s)" = "Darwin" ] && [ -d "/Applications/Docker.app" ]; then
    warn "daemon not responding; starting Docker Desktop"
    open -a Docker
    for _ in $(seq 1 60); do
      docker info >/dev/null 2>&1 && break
      printf '.'; sleep 2
    done
    printf '\n'
  fi
  docker info >/dev/null 2>&1 || die "Docker daemon is not reachable" \
    "Start Docker Desktop manually, then re-run this script."
fi
ok "daemon reachable (server $(docker info --format '{{.ServerVersion}}' 2>/dev/null))"

# The execution image. Re-confirm before rebuilding: a momentary daemon stall
# exits nonzero exactly like a genuinely absent image.
if [ "$REBUILD_IMAGE" -eq 1 ]; then
  warn "rebuilding $IMAGE on request"
  docker build -t "$IMAGE" "$ROOT/docker"
elif docker image inspect "$IMAGE" >/dev/null 2>&1 || docker image inspect "$IMAGE" >/dev/null 2>&1; then
  ok "execution image present ($(docker images "$IMAGE" --format '{{.ID}}'))"
else
  warn "execution image missing; building it now"
  docker build -t "$IMAGE" "$ROOT/docker"
  docker image inspect "$IMAGE" >/dev/null 2>&1 || die "image build did not produce $IMAGE"
  ok "execution image built"
fi

# ----------------------------------------------------------------- frontend
step "3. Web UI bundle"
DIST="$ROOT/frontend/dist"
if [ "$BUILD_FRONTEND" -eq 0 ]; then
  [ -f "$DIST/index.html" ] || die "--no-build given but no bundle exists at frontend/dist"
  ok "using existing bundle (build skipped)"
elif ! command -v node >/dev/null 2>&1; then
  warn "node not found on PATH, so the bundle cannot be rebuilt"
  warn "fix with: brew link --overwrite node || brew reinstall node"
  [ -f "$DIST/index.html" ] || die "no existing bundle at frontend/dist either" \
    "Restore node, then run: npm --prefix frontend run build"
  warn "serving the existing bundle; recent UI changes will NOT be included"
else
  [ -d "$ROOT/frontend/node_modules" ] || { warn "installing frontend dependencies"; npm --prefix "$ROOT/frontend" ci; }
  npm --prefix "$ROOT/frontend" run build >/dev/null
  ok "bundle built ($(node --version))"
fi

# ---------------------------------------------------------------- model cfg
step "4. Model configuration"
if [ -f "$ROOT/.env" ]; then
  ok ".env present (loaded by the CLI, server and workers)"
else
  warn ".env not found; copy .env.example and add OPENROUTER_API_KEY"
fi

# ------------------------------------------------------- stop old instances
step "5. Existing instances"
# Only one migration may hold the lease, so never leave a second server running.
PIDS="$(pgrep -f 'api_maintainer' 2>/dev/null || true)"
if [ -n "$PIDS" ]; then
  warn "stopping running api_maintainer processes: $(echo "$PIDS" | tr '\n' ' ')"
  # shellcheck disable=SC2086
  kill $PIDS 2>/dev/null || true
  sleep 2
  PIDS="$(pgrep -f 'api_maintainer' 2>/dev/null || true)"
  # shellcheck disable=SC2086
  [ -n "$PIDS" ] && { kill -9 $PIDS 2>/dev/null || true; sleep 1; }
  ok "stopped"
else
  ok "none running"
fi
STRAY="$(docker ps -aq --filter 'label=api-maintainer.run' 2>/dev/null || true)"
if [ -n "$STRAY" ]; then
  # shellcheck disable=SC2086
  docker rm -f $STRAY >/dev/null 2>&1 || true
  ok "removed leftover run containers"
fi

# -------------------------------------------------------------------- ready
step "6. Prerequisite check"
if "$VENV/bin/api-maintainer" doctor; then
  ok "ready"
else
  warn "doctor reports not ready (see above)"
  warn "if it says image:false while 'docker images $IMAGE' shows it, just re-run — the check flaps"
fi

if [ "$CHECK_ONLY" -eq 1 ]; then
  step "Checks complete (--check): server not started."
  exit 0
fi

step "Starting server on http://127.0.0.1:$PORT"
printf '  Stop with Ctrl+C. Hard-reload the browser (Cmd+Shift+R) after a UI rebuild.\n\n'
cd "$ROOT"
exec "$VENV/bin/uvicorn" api_maintainer.api:app --host 127.0.0.1 --port "$PORT"
