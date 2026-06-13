#!/usr/bin/env bash
# ============================================================
# AXIOM A2A Banking Agents — Run & Score
# ============================================================
# This script:
#   1. Finds/starts Docker
#   2. Installs uv if missing
#   3. Builds & starts your two agents (Personal + CS) via docker-compose
#   4. Sets up the a2a-hack harness CLI
#   5. Runs a smoke test (1 task, instant feedback)
#   6. Runs the full training split (79 tasks, scored — this is your rank)
#
# Usage: chmod +x run.sh && ./run.sh
# ============================================================

# Don't use set -e — we handle errors per-step
set -uo pipefail

GREEN='\033[0;32m'; RED='\033[0;31m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
info()  { echo -e "${GREEN}[✓]${NC} $*"; }
warn()  { echo -e "${YELLOW}[!]${NC} $*"; }
fail()  { echo -e "${RED}[✗]${NC} $*"; }
die()   { echo -e "${RED}[✗]${NC} $*"; exit 1; }
step()  { echo -e "\n${BLUE}━━━ $* ━━━${NC}"; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ============================================================
step "1/6 — Docker"
# ============================================================

# Find docker binary
if ! command -v docker &>/dev/null; then
    for dp in "/Applications/Docker.app/Contents/Resources/bin" "$HOME/.docker/bin" "/usr/local/bin"; do
        [ -x "$dp/docker" ] && { export PATH="$dp:$PATH"; info "Found docker at $dp"; break; }
    done
fi

if ! command -v docker &>/dev/null; then
    if [ -d "/Applications/Docker.app" ]; then
        die "Docker Desktop is installed but CLI isn't in PATH.
  Fix option 1: Open Docker Desktop → Settings → General → enable CLI
  Fix option 2: sudo ln -sf /Applications/Docker.app/Contents/Resources/bin/docker /usr/local/bin/docker
  Then re-run this script."
    fi
    die "Docker not installed. Get it: https://docs.docker.com/desktop/install/mac-install/"
fi

# Ensure daemon is running
if ! docker info &>/dev/null 2>&1; then
    if [ -d "/Applications/Docker.app" ]; then
        warn "Docker daemon not running — launching Docker Desktop..."
        open -a Docker
        printf "  Waiting for Docker"
        for _ in $(seq 1 40); do
            docker info &>/dev/null 2>&1 && { printf "\n"; info "Docker daemon started."; break; }
            printf "."
            sleep 2
        done
        printf "\n"
        docker info &>/dev/null 2>&1 || die "Docker didn't start in 80s. Open Docker Desktop manually, wait for the whale icon to stop animating, then re-run."
    else
        die "Docker daemon not running and can't auto-start."
    fi
fi

# Pick compose command
if docker compose version &>/dev/null 2>&1; then DC="docker compose"
elif command -v docker-compose &>/dev/null; then DC="docker-compose"
else die "docker compose plugin missing. Update Docker Desktop."; fi

info "Docker ready ($DC)"

# ============================================================
step "2/6 — Python tooling (uv)"
# ============================================================

if ! command -v uv &>/dev/null; then
    for up in "$HOME/.cargo/bin" "$HOME/.local/bin" "$HOME/.uv/bin"; do
        [ -x "$up/uv" ] && { export PATH="$up:$PATH"; break; }
    done
fi

if ! command -v uv &>/dev/null; then
    info "Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh 2>/dev/null
    export PATH="$HOME/.cargo/bin:$HOME/.local/bin:$HOME/.uv/bin:$PATH"
    command -v uv &>/dev/null || die "uv install failed. Manual: https://docs.astral.sh/uv/getting-started/installation/"
fi

info "uv $(uv --version 2>/dev/null || echo 'installed')"

# ============================================================
step "3/6 — Environment"
# ============================================================

if [ ! -f "$SCRIPT_DIR/.env" ]; then
    if [ -f "$SCRIPT_DIR/env.local" ]; then
        cp "$SCRIPT_DIR/env.local" "$SCRIPT_DIR/.env"
        warn "Created .env from env.local."
        fail "You MUST set GOOGLE_API_KEY in .env before running."
        echo "  Edit: nano .env   (or open .env in any editor)"
        echo "  Then re-run: ./run.sh"
        exit 1
    fi
    die "No .env file found. Create one from env.local."
fi

# Load env vars
set -a; source "$SCRIPT_DIR/.env" 2>/dev/null || true; set +a

if [ -z "${GOOGLE_API_KEY:-}" ] || [ "$GOOGLE_API_KEY" = "your-google-api-key-here" ]; then
    die "GOOGLE_API_KEY is not set in .env. Add your Gemini API key and re-run."
fi

info "Config loaded (MODEL=${MODEL:-gemini-2.5-flash}, tokens=dev-*)"

# ============================================================
step "4/6 — Build & start agents"
# ============================================================

info "Building containers (personal-agent + cs-agent + redis)..."
if ! $DC build 2>&1 | tail -5; then
    fail "Docker build failed. Dumping full log:"
    $DC build
    die "Fix the build errors above and re-run."
fi
info "Build complete."

info "Starting containers..."
$DC down --remove-orphans &>/dev/null 2>&1 || true
$DC up -d || die "docker compose up failed."

info "Waiting for agents to initialize (CS Agent indexes 698 KB docs)..."
printf "  "
PA_UP=false; CS_UP=false
for _ in $(seq 1 60); do
    [ "$PA_UP" = false ] && curl -sf http://localhost:9001/.well-known/agent.json &>/dev/null && PA_UP=true
    [ "$CS_UP" = false ] && curl -sf http://localhost:9002/.well-known/agent.json &>/dev/null && CS_UP=true
    [ "$PA_UP" = true ] && [ "$CS_UP" = true ] && break
    printf "."
    sleep 2
done
printf "\n"

if [ "$PA_UP" = true ] && [ "$CS_UP" = true ]; then
    info "Personal Agent: http://localhost:9001 ✓"
    info "CS Agent:       http://localhost:9002 ✓"
elif [ "$PA_UP" = true ]; then
    info "Personal Agent: UP ✓"
    warn "CS Agent: still starting. Logs: $DC logs cs-agent"
    warn "Continuing — harness has 300s per-turn timeout."
else
    warn "Agents not responding yet. Logs: $DC logs"
    warn "Continuing anyway..."
fi

# ============================================================
step "5/6 — Harness CLI setup"
# ============================================================

HARNESS="$SCRIPT_DIR/harness"
[ -d "$HARNESS/src/a2a_hack" ] || die "harness/src/a2a_hack not found. Repo is incomplete."

cd "$HARNESS"

# Setup venv + install if needed
if [ ! -f ".venv/pyvenv.cfg" ]; then
    info "Creating harness virtualenv..."
    uv venv --python 3.12 2>/dev/null || uv venv || die "Failed to create venv. Need Python 3.12+."
fi

# Install package (includes tau2 from git)
if ! uv run python -c "import a2a_hack" &>/dev/null 2>&1; then
    info "Installing a2a-hack + tau2-bench (one-time, ~30s)..."
    if ! uv pip install -e "." 2>&1 | tail -5; then
        fail "Install failed. Full output:"
        uv pip install -e "."
        die "Harness install failed. Check errors above."
    fi
fi

# Final check
if ! uv run a2a-hack --help &>/dev/null 2>&1; then
    die "a2a-hack CLI broken after install. Debug: cd harness && uv run a2a-hack --help"
fi
info "a2a-hack CLI ready."

# ============================================================
step "6/6 — Score your agents"
# ============================================================

# Pass env vars the harness needs (it uses GOOGLE_API_KEY for the user sim LLM)
export GOOGLE_API_KEY="${GOOGLE_API_KEY}"

echo ""
echo "┌────────────────────────────────────────────┐"
echo "│  SMOKE TEST — 1 task, quick sanity check   │"
echo "└────────────────────────────────────────────┘"
echo ""

uv run a2a-hack smoke \
    --personal-url http://localhost:9001 \
    --cs-url http://localhost:9002 \
    2>&1
SMOKE=$?

echo ""
if [ $SMOKE -eq 0 ]; then
    info "Smoke test passed! Your agents are communicating correctly."
else
    warn "Smoke test exit code: $SMOKE (review output above)"
    warn "Common issues:"
    echo "  - 0 env tool calls = contextId not propagating (check session_id())"
    echo "  - 0 leg-2 messages = Personal Agent not calling CS Agent"
    echo "  - Reward 0.0 = tools called but wrong arguments"
fi

echo ""
echo "┌────────────────────────────────────────────┐"
echo "│  FULL RUN — all training tasks (scored)    │"
echo "│  This is what judges use. Takes 5-15 min.  │"
echo "└────────────────────────────────────────────┘"
echo ""

RESULTS="$SCRIPT_DIR/results/own-pair"
mkdir -p "$RESULTS"

uv run a2a-hack run \
    --personal-url http://localhost:9001 \
    --cs-url http://localhost:9002 \
    --tasks train \
    --save-to "$RESULTS" \
    --auto-resume \
    2>&1
SCORE_EXIT=$?

echo ""
echo "════════════════════════════════════════════════"
if [ $SCORE_EXIT -eq 0 ]; then
    info "ALL TASKS COMPLETE"
elif [ $SCORE_EXIT -eq 2 ]; then
    warn "Some tasks had infrastructure errors (will retry with --auto-resume)"
else
    warn "Run finished with exit code $SCORE_EXIT"
fi
echo "════════════════════════════════════════════════"
echo ""
info "Results: $RESULTS"
info "Browse:  cd harness && uv run tau2 view $RESULTS"
echo ""
echo "  Your own-pair mean reward = 50% of final competition score"
echo "  Final = 50% own-pair + 25% (your PA × held-out CS) + 25% (held-out PA × your CS)"
echo ""
info "Stop agents: cd $SCRIPT_DIR && $DC down"
