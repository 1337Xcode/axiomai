"""
Centralized AXIOM System Configuration.

Edit this file to change models, temperature, token limits, embedding settings,
grading mode, and circuit-breaker behaviour without touching agent code.
"""
import os
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Runtime Mode
# ---------------------------------------------------------------------------
# AXIOM_MODE controls mock/fallback behaviour:
#   development  - in-memory fallbacks + mock accounts enabled
#   test         - pytest fixtures injected; no real API calls required
#   grading      - no mocks, no silent fallbacks; hard failures on missing deps
AXIOM_MODE: str = os.environ.get("AXIOM_MODE", "development")

# ---------------------------------------------------------------------------
# LLM Models
# ---------------------------------------------------------------------------
# gemini-3.5-flash  → released May 2026; high-capability agentic + reasoning
# gemini-3.1-flash-lite → released May 2026; fast, cost-efficient formatting
# Both are stable (non-preview) identifiers as of June 2026.
# gemini-2.5-flash and gemini-2.5-pro are deprecated and shut down 2026-06-17.
INTAKE_MODEL: str = os.environ.get("INTAKE_MODEL", "gemini-3.1-flash-lite")
FORMATTER_MODEL: str = os.environ.get("FORMATTER_MODEL", "gemini-3.1-flash-lite")
REASONING_MODEL: str = os.environ.get("REASONING_MODEL", "gemini-3.1-pro-preview")
REASONING_FALLBACK_MODEL: str = os.environ.get("REASONING_FALLBACK_MODEL", "gemini-3.5-flash")
RESEARCH_MODEL: str = os.environ.get("RESEARCH_MODEL", "gemini-3.1-flash-lite")

# Startup readiness check and fallback verification (skipped in test/mock — no live API)
if AXIOM_MODE not in ("test", "mock") and (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")):
    try:
        from google import genai
        api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        client = genai.Client(api_key=api_key)
        client.models.get(model=REASONING_MODEL)
        print(f"[STARTUP CHECK] Reasoning model '{REASONING_MODEL}' verified successfully.")
    except Exception as e:
        print(f"[STARTUP CHECK] Reasoning model '{REASONING_MODEL}' check failed: {e}. Falling back to '{REASONING_FALLBACK_MODEL}'.")
        REASONING_MODEL = REASONING_FALLBACK_MODEL
else:
    print(f"[STARTUP CHECK] Skipping live API check for Reasoning model. Using: '{REASONING_MODEL}' (mode: {AXIOM_MODE})")

# ---------------------------------------------------------------------------
# Embedding Model
# ---------------------------------------------------------------------------
# gemini-embedding-2 supports reduced output dimensions (e.g. 768).
# text-embedding-004 was shut down 2026-01-14. Do NOT use it.
EMBEDDING_MODEL: str = os.environ.get("EMBEDDING_MODEL", "gemini-embedding-2")
EMBEDDING_DIMENSIONS: int = int(os.environ.get("EMBEDDING_DIMENSIONS", "768"))

# ---------------------------------------------------------------------------
# LLM Generation Settings
# ---------------------------------------------------------------------------
# Temperature controls randomness. 0.0 = fully deterministic (for formatters).
# Increase for more creative reasoning agents if desired.
INTAKE_TEMPERATURE: float = float(os.environ.get("INTAKE_TEMPERATURE", "0.1"))
INTAKE_MAX_TOKENS: int = int(os.environ.get("INTAKE_MAX_TOKENS", "1024"))

REASONING_TEMPERATURE: float = float(os.environ.get("REASONING_TEMPERATURE", "0.3"))
REASONING_MAX_TOKENS: int = int(os.environ.get("REASONING_MAX_TOKENS", "2048"))

FORMATTER_TEMPERATURE: float = float(os.environ.get("FORMATTER_TEMPERATURE", "0.0"))
FORMATTER_MAX_TOKENS: int = int(os.environ.get("FORMATTER_MAX_TOKENS", "1024"))

RESEARCH_TEMPERATURE: float = float(os.environ.get("RESEARCH_TEMPERATURE", "0.1"))
RESEARCH_MAX_TOKENS: int = int(os.environ.get("RESEARCH_MAX_TOKENS", "1024"))

# ---------------------------------------------------------------------------
# Redis
# ---------------------------------------------------------------------------
REDIS_URL: str = os.environ.get("REDIS_URL", "redis://localhost:6379")
REDIS_MAX_CONNECTIONS: int = int(os.environ.get("REDIS_MAX_CONNECTIONS", "200"))
REDIS_SESSION_TTL: int = int(os.environ.get("REDIS_SESSION_TTL", "86400"))   # 24h
REDIS_MEMORY_TTL: int = int(os.environ.get("REDIS_MEMORY_TTL", "2592000"))  # 30d
REDIS_CACHE_TTL: int = int(os.environ.get("REDIS_CACHE_TTL", "3600"))        # 1h
REDIS_STREAM_MAXLEN: int = int(os.environ.get("REDIS_STREAM_MAXLEN", "10000"))

# ---------------------------------------------------------------------------
# Agent Ports
# ---------------------------------------------------------------------------
PORT_GATEWAY: int = int(os.environ.get("PORT_GATEWAY", "8080"))
PORT_PERSONAL: int = int(os.environ.get("PORT_PERSONAL", "8081"))
PORT_CS: int = int(os.environ.get("PORT_CS", "8082"))
PORT_RESEARCH: int = int(os.environ.get("PORT_RESEARCH", "8083"))

# ---------------------------------------------------------------------------
# Research / Orchestration
# ---------------------------------------------------------------------------
LINKUP_DEPTH: str = os.environ.get("LINKUP_DEPTH", "standard")
RESEARCH_PARALLEL_LIMIT: int = int(os.environ.get("RESEARCH_PARALLEL_LIMIT", "2"))
ORCHESTRATOR_TIMEOUT: float = float(os.environ.get("ORCHESTRATOR_TIMEOUT", "30.0"))
RESEARCH_SCOPED_DOMAINS: list[str] = os.environ.get("RESEARCH_SCOPED_DOMAINS", "").split(",") if os.environ.get("RESEARCH_SCOPED_DOMAINS") else []

# ---------------------------------------------------------------------------
# AG-UI / SSE
# ---------------------------------------------------------------------------
SSE_MAX_WAIT: float = float(os.environ.get("SSE_MAX_WAIT", "60.0"))
SSE_HEARTBEAT_INTERVAL: float = float(os.environ.get("SSE_HEARTBEAT_INTERVAL", "15.0"))

# ---------------------------------------------------------------------------
# Circuit Breaker
# ---------------------------------------------------------------------------
# In grading mode the long-running ban is disabled; we use a short rate-limit
# instead to avoid spoofable 30-minute bans based on caller-supplied agentId.
CIRCUIT_FAILURE_THRESHOLD: int = int(os.environ.get("CIRCUIT_FAILURE_THRESHOLD", "3"))
CIRCUIT_BAN_SECONDS: int = int(os.environ.get("CIRCUIT_BAN_SECONDS", "120"))  # 2 min, not 30
