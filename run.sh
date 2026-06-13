#!/usr/bin/env bash
set -euo pipefail

# AXIOM A2A Banking Agents - Mac/Linux Run & Test Script
# Self-setup: installs missing deps, builds, runs, and scores.

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { echo -e "${GREEN}[AXIOM]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }

# --- Dependency checks ---
info "Checking dependencies..."

# Docker: check CLI first, if missing try to find Docker Desktop app and add to PATH
if ! command -v docker &>/dev/null; then
    # Docker Desktop on macOS installs CLI tools in these locations
    DOCKER_PATHS=(
        "/Applications/Docker.app/Contents/Resources/bin"
        "/usr/local/bin"
        "$HOME/.docker/bin"
    )
    FOUND_DOCKER=false
    for dp in "${DOCKER_PATHS[@]}"; do
        if [ -x "$dp/docker" ]; then
            export PATH="$dp:$PATH"
            FOUND_DOCKER=true
            info "Found docker at $dp — added to PATH"
            break
        fi
    done

    if [ "$FOUND_DOCKER" = false ]; then
        # Check if Docker.app exists but CLI symlinks are missing
        if [ -d "/Applications/Docker.app" ]; then
            warn "Docker Desktop is installed but CLI tools aren't linked."
            warn "Fix: Open Docker Desktop → Settings → General → enable 'Install Docker CLI in system PATH'"
            warn "Or run: sudo ln -sf /Applications/Docker.app/Contents/Resources/bin/docker /usr/local/bin/docker"
            error "Docker CLI not available. Fix the above and re-run."
        else
            error "Docker not found. Install Docker Desktop: https://docs.docker.com/desktop/install/mac-install/"
        fi
    fi
fi

if ! docker info &>/dev/null 2>&1; then
    # Try to start Docker Desktop
    if [ -d "/Applications/Docker.app" ]; then
        warn "Docker daemon not running. Starting Docker Desktop..."
        open -a Docker
        info "Waiting for Docker to start (up to 60s)..."
        for i in $(seq 1 30); do
            if docker info &>/dev/null 2>&1; then
                info "Docker is ready."
                break
            fi
            sleep 2
        done
        if ! docker info &>/dev/null 2>&1; then
            error "Docker failed to start within 60s. Open Docker Desktop manually and re-run."
        fi
    else
        error "Docker daemon not running and Docker Desktop not found."
    fi
fi

if ! command -v docker-compose &>/dev/null && ! docker compose version &>/dev/null 2>&1; then
    error "docker-compose not found. Install Docker Desktop (includes compose)."
fi

# Use 'docker compose' (v2) if available, else fallback to 'docker-compose'
if docker compose version &>/dev/null 2>&1; then
    DC="docker compose"
else
    DC="docker-compose"
fi

if ! command -v curl &>/dev/null; then
    error "curl not found. Install: brew install curl"
fi

# Check for uv (needed for harness)
if ! command -v uv &>/dev/null; then
    warn "uv not found. Installing..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.cargo/bin:$PATH"
    if ! command -v uv &>/dev/null; then
        error "Failed to install uv. Install manually: https://docs.astral.sh/uv/"
    fi
fi

info "All dependencies OK."

# --- Environment setup ---
if [ ! -f .env ]; then
    warn "No .env file. Copying env.local..."
    cp env.local .env
    echo ""
    warn "EDIT .env with your GOOGLE_API_KEY before continuing!"
    warn "Then re-run: ./run.sh"
    exit 1
fi

# Validate GOOGLE_API_KEY is set
source .env 2>/dev/null || true
if [ -z "${GOOGLE_API_KEY:-}" ] || [ "$GOOGLE_API_KEY" = "your-google-api-key-here" ]; then
    error "GOOGLE_API_KEY not set in .env. Add your API key and re-run."
fi

info "Environment configured."

# --- Build and start agents ---
info "Building agent containers..."
$DC build

info "Starting services (redis:6379, personal-agent:9001, cs-agent:9002)..."
$DC up -d

info "Waiting for CS Agent to index KB (may take 15-30s)..."
for i in $(seq 1 60); do
    if curl -sf http://localhost:9002/.well-known/agent.json &>/dev/null; then
        break
    fi
    sleep 2
done

# Health checks
echo ""
if curl -sf http://localhost:9001/.well-known/agent.json &>/dev/null; then
    info "Personal Agent: UP (http://localhost:9001)"
else
    warn "Personal Agent not responding. Check: $DC logs personal-agent"
fi

if curl -sf http://localhost:9002/.well-known/agent.json &>/dev/null; then
    info "CS Agent: UP (http://localhost:9002)"
else
    warn "CS Agent not responding. Check: $DC logs cs-agent"
fi

echo ""
info "Agents running. Starting harness smoke test..."

# --- Run harness smoke test ---
HARNESS_DIR="temp/a2a-hackathon-main"
if [ ! -d "$HARNESS_DIR" ]; then
    error "Harness not found at $HARNESS_DIR. Clone it first."
fi

cd "$HARNESS_DIR"

# Install harness deps if needed
if [ ! -d ".venv" ]; then
    info "Setting up harness virtual environment..."
    uv venv
    uv pip install -e . 2>/dev/null || uv pip install . 2>/dev/null || warn "Harness install failed — tau2 may need local checkout"
fi

info "Running smoke test (1 task, quick sanity check)..."
uv run a2a-hack smoke \
    --personal-url http://localhost:9001 \
    --cs-url http://localhost:9002 \
    || warn "Smoke test returned non-zero (check output above)"

echo ""
info "Smoke test done. Now running FULL scored evaluation (all training tasks)..."
echo ""

# Run the full training split — this is what judges score on
RESULTS_DIR="../../results/own-pair"
mkdir -p "$RESULTS_DIR"

info "Running all training tasks (this takes several minutes, uses Gemini API credits)..."
uv run a2a-hack run \
    --personal-url http://localhost:9001 \
    --cs-url http://localhost:9002 \
    --tasks train \
    --save-to "$RESULTS_DIR" \
    --auto-resume \
    || warn "Some tasks may have failed (check output above)"

echo ""
echo "============================================"
info "EVALUATION COMPLETE"
echo "============================================"
echo ""
info "Results saved to: results/own-pair/"
info "Browse results:   cd $HARNESS_DIR && uv run tau2 view $RESULTS_DIR"
echo ""
info "The mean reward printed above is your own-pair score (50% of final)."
info "Final competition score = 50% own-pair + 25% your-PA-x-held-out-CS + 25% held-out-PA-x-your-CS"
echo ""
info "To stop agents: cd ../.. && $DC down"
