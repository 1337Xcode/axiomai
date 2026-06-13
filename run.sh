#!/usr/bin/env bash
# AXIOM A2A Banking Agents - Mac/Linux Run & Test Script
# Self-setup: finds Docker, installs uv, builds agents, runs harness scoring.

set -uo pipefail  # no -e: we handle errors ourselves

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { echo -e "${GREEN}[AXIOM]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
die()   { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# ============================================================
# 1. FIND DOCKER
# ============================================================
info "Checking Docker..."

if ! command -v docker &>/dev/null; then
    # Try common macOS Docker Desktop paths
    for dp in "/Applications/Docker.app/Contents/Resources/bin" "$HOME/.docker/bin" "/usr/local/bin"; do
        if [ -x "$dp/docker" ]; then
            export PATH="$dp:$PATH"
            info "Found docker at $dp"
            break
        fi
    done
fi

if ! command -v docker &>/dev/null; then
    if [ -d "/Applications/Docker.app" ]; then
        die "Docker Desktop installed but CLI not in PATH.\n  Fix: Open Docker Desktop → Settings → General → 'Install Docker CLI in system PATH'\n  Or: sudo ln -sf /Applications/Docker.app/Contents/Resources/bin/docker /usr/local/bin/docker"
    else
        die "Docker not found. Install: https://docs.docker.com/desktop/install/mac-install/"
    fi
fi

# Start Docker daemon if not running
if ! docker info &>/dev/null 2>&1; then
    if [ -d "/Applications/Docker.app" ]; then
        warn "Docker not running. Starting Docker Desktop..."
        open -a Docker
        echo -n "  Waiting"
        for i in $(seq 1 30); do
            if docker info &>/dev/null 2>&1; then echo ""; info "Docker ready."; break; fi
            echo -n "."
            sleep 2
        done
        echo ""
        docker info &>/dev/null 2>&1 || die "Docker failed to start. Open Docker Desktop manually."
    else
        die "Docker daemon not running."
    fi
fi

# Docker compose command
if docker compose version &>/dev/null 2>&1; then
    DC="docker compose"
elif command -v docker-compose &>/dev/null; then
    DC="docker-compose"
else
    die "docker compose not available. Update Docker Desktop."
fi

info "Docker OK. Using: $DC"

# ============================================================
# 2. FIND/INSTALL UV (Python package manager for harness)
# ============================================================
if ! command -v uv &>/dev/null; then
    # Check common install locations
    for up in "$HOME/.cargo/bin" "$HOME/.local/bin"; do
        if [ -x "$up/uv" ]; then
            export PATH="$up:$PATH"
            break
        fi
    done
fi

if ! command -v uv &>/dev/null; then
    info "Installing uv (Python package manager)..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.cargo/bin:$HOME/.local/bin:$PATH"
    command -v uv &>/dev/null || die "uv install failed. Install manually: https://docs.astral.sh/uv/"
fi

info "uv OK: $(uv --version)"

# ============================================================
# 3. ENVIRONMENT FILE
# ============================================================
if [ ! -f .env ]; then
    if [ -f env.local ]; then
        cp env.local .env
        warn "Created .env from env.local. Edit GOOGLE_API_KEY in .env, then re-run."
        exit 1
    else
        die "No .env or env.local found."
    fi
fi

# Source env and validate key
set -a; source .env 2>/dev/null || true; set +a
if [ -z "${GOOGLE_API_KEY:-}" ] || [ "$GOOGLE_API_KEY" = "your-google-api-key-here" ]; then
    die "GOOGLE_API_KEY not set in .env. Add your Gemini API key and re-run."
fi

info "Environment OK (GOOGLE_API_KEY set, MODEL=${MODEL:-gemini-2.5-flash})"

# ============================================================
# 4. BUILD & START AGENT CONTAINERS
# ============================================================
info "Building agent containers..."
$DC build || die "Docker build failed. Check Dockerfiles."

info "Starting services..."
$DC up -d || die "Failed to start containers."

info "Waiting for agents to be ready..."
echo -n "  "
READY=false
for i in $(seq 1 45); do
    PA=$(curl -sf -o /dev/null -w "%{http_code}" http://localhost:9001/.well-known/agent.json 2>/dev/null || echo "000")
    CS=$(curl -sf -o /dev/null -w "%{http_code}" http://localhost:9002/.well-known/agent.json 2>/dev/null || echo "000")
    if [ "$PA" = "200" ] && [ "$CS" = "200" ]; then
        READY=true
        echo ""
        break
    fi
    echo -n "."
    sleep 2
done

if [ "$READY" = true ]; then
    info "Both agents UP and serving."
else
    echo ""
    warn "Agents not fully ready after 90s. Checking individually..."
    [ "$PA" = "200" ] && info "  Personal Agent: UP" || warn "  Personal Agent: DOWN — check: $DC logs personal-agent"
    [ "$CS" = "200" ] && info "  CS Agent: UP" || warn "  CS Agent: DOWN (may still be indexing KB) — check: $DC logs cs-agent"
    warn "Continuing anyway — harness will retry on timeout..."
fi

# ============================================================
# 5. SETUP HARNESS CLI (a2a-hack)
# ============================================================
HARNESS_DIR="$SCRIPT_DIR/harness"
if [ ! -d "$HARNESS_DIR/src" ]; then
    die "Harness not found at $HARNESS_DIR. Something is wrong with the repo."
fi

cd "$HARNESS_DIR"

# Create venv and install if needed
if [ ! -d ".venv" ] || ! .venv/bin/python -c "import a2a_hack" &>/dev/null 2>&1; then
    info "Setting up harness environment (first run only, may take 1-2 min)..."
    rm -rf .venv
    uv venv --python 3.12 2>/dev/null || uv venv
    info "Installing harness + tau2-bench..."
    uv pip install -e "." 2>&1 | tail -3
fi

# Verify CLI works
if ! uv run a2a-hack --help &>/dev/null 2>&1; then
    warn "a2a-hack CLI failed. Trying reinstall..."
    uv pip install -e "." 2>&1 | tail -5
    uv run a2a-hack --help &>/dev/null 2>&1 || die "a2a-hack CLI broken. Run manually: cd harness && uv pip install -e . && uv run a2a-hack --help"
fi

info "Harness CLI ready."

# ============================================================
# 6. RUN SMOKE TEST (1 task — quick sanity check)
# ============================================================
echo ""
echo "============================================"
info "SMOKE TEST (1 task)"
echo "============================================"
echo ""

uv run a2a-hack smoke \
    --personal-url http://localhost:9001 \
    --cs-url http://localhost:9002
SMOKE_EXIT=$?

if [ $SMOKE_EXIT -eq 0 ]; then
    info "Smoke test PASSED."
else
    warn "Smoke test returned exit code $SMOKE_EXIT (see output above)."
fi

# ============================================================
# 7. RUN FULL SCORED EVALUATION (all training tasks)
# ============================================================
echo ""
echo "============================================"
info "FULL EVALUATION (training split — this is your score)"
echo "============================================"
echo ""

RESULTS_DIR="$SCRIPT_DIR/results/own-pair"
mkdir -p "$RESULTS_DIR"

uv run a2a-hack run \
    --personal-url http://localhost:9001 \
    --cs-url http://localhost:9002 \
    --tasks train \
    --save-to "$RESULTS_DIR" \
    --auto-resume
RUN_EXIT=$?

echo ""
echo "============================================"
if [ $RUN_EXIT -eq 0 ]; then
    info "EVALUATION COMPLETE — ALL TASKS PASSED"
else
    warn "EVALUATION COMPLETE — some tasks may have failed (exit $RUN_EXIT)"
fi
echo "============================================"
echo ""
info "Results saved to: results/own-pair/"
info "The mean reward above is your OWN-PAIR score (50% of final)."
info "Final = 50% own-pair + 25% your-PA×held-out-CS + 25% held-out-PA×your-CS"
echo ""
info "To browse results: cd harness && uv run tau2 view $RESULTS_DIR"
info "To stop agents: cd $SCRIPT_DIR && $DC down"
