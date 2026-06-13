# AXIOM v6.2 — Master System Architecture & Complete Implementation Reference

*Written for hackathon graders, future engineers, and external reviewers.*
*Every file, every design decision, every protocol constraint is documented here.*

> **Companion document:** `docs/design.md` is the adversarially validated engineering blueprint (trap analysis, pseudocode, protocol rationale). This file (`system.md`) maps that design to the **actual running codebase** — file paths, runtime behaviour, test harness, and operational commands. Where they diverge, **the code wins**; this document reflects the code as of the latest hardening pass.

---

## Table of Contents

1. [Executive Summary & Design Philosophy](#1-executive-summary--design-philosophy)
2. [Repository Layout & File Catalogue](#2-repository-layout--file-catalogue)
3. [Protocol Stack](#3-protocol-stack)
   - 3.1 A2A v0.3 (Agent-to-Agent RPC)
   - 3.2 AG-UI v1.0 (Agent User Interface events)
   - 3.3 A2UI v1.0 candidate (Surface Protocol)
4. [Network Topology & Process Map](#4-network-topology--process-map)
5. [The Phalanx Gateway — `gateway/`](#5-the-phalanx-gateway--gateway)
   - 5.1 `gateway/main.py` — 9-layer pipeline
   - 5.2 `gateway/state_machine.py` — Shadow task tracker
   - 5.3 `gateway/validators/rpc_validator.py`
   - 5.4 `gateway/validators/a2a_validator.py`
6. [Internal Agent Workers — `apps/`](#6-internal-agent-workers--apps)
   - 6.1 `apps/app_personal.py`
   - 6.2 `apps/app_cs.py`
   - 6.3 `apps/app_research.py`
7. [ADK Agent Definitions — `agents/`](#7-adk-agent-definitions--agents)
   - 7.1 `agents/personal_agent.py`
   - 7.2 `agents/cs_agent.py`
   - 7.3 `agents/research_agent.py`
8. [The Orchestrator — `orchestrator/`](#8-the-orchestrator--orchestrator)
   - 8.1 `orchestrator/workflow.py`
   - 8.2 `orchestrator/timeout_manager.py`
9. [Redis Memory Fabric — `redis_fabric/`](#9-redis-memory-fabric--redis_fabricfabricpy)
   - 9.1 Plane 1 — Session State
   - 9.2 Plane 2 — Event Bus
   - 9.3 Plane 3 — Vector Memory
   - 9.4 Plane 4 — Research Cache
   - 9.5 SQLite Cross-Process Fallback
10. [Tools — `tools/`](#10-tools--tools)
    - 10.1 `tools/account_tools.py`
    - 10.2 `tools/linkup_search.py`
11. [Frontend Bridge — `frontend/`](#11-frontend-bridge--frontend)
    - 11.1 `frontend/ag_ui_bridge.py`
    - 11.2 `frontend/components/TrustedCatalog.tsx`
12. [Configuration — `config.py`](#12-configuration--configpy)
13. [Agent Card — `agent_card.py`](#13-agent-card--agent_cardpy)
14. [Network Helpers — `network/`](#14-network-helpers--network)
    - 14.1 `network/adk_helper.py`
    - 14.2 `network/agent_discovery.py`
15. [Background Jobs — `background/`](#15-background-jobs--background)
16. [Testing Strategy — `tests/`](#16-testing-strategy--tests)
    - 16.1 `tests/test_system.py`
    - 16.2 `tests/test_integration.py`
    - 16.3 `tests/test_e2e_run.py`
17. [Model Selection & Startup Verification](#17-model-selection--startup-verification)
18. [Security Model (Defensive / Zero-Trust-Inspired)](#18-security-model-defensive--zero-trust-inspired)
19. [State Machine & Task Lifecycle](#19-state-machine--task-lifecycle)
20. [Embedding & Vector RAG Pipeline](#20-embedding--vector-rag-pipeline)
21. [Hard-Learned ADK Traps](#21-hard-learned-adk-traps)
22. [Operational Runbook](#22-operational-runbook)
23. [Runtime Modes (`AXIOM_MODE`)](#23-runtime-modes-axiom_mode)
24. [Deterministic ID Derivation](#24-deterministic-id-derivation)
25. [How the Pieces Fit Together](#25-how-the-pieces-fit-together)

---

## 1. Executive Summary & Design Philosophy

**AXIOM** (Agentic eXperience & Interaction Orchestration Manager) is a production-hardened multi-agent orchestration platform designed for enterprise Customer Service and Research applications. It was purpose-built for the Google ADK/A2A hackathon with the following non-negotiable design principles:

### Core Tenets

| Tenet | Implementation |
|---|---|
| **Deterministic Orchestration** | Python state machines control *when* and *where* LLM decisions execute. The LLM decides *what* to do; Python decides *if* that is allowed. |
| **Defensive, Zero-Trust-Inspired Edge** | The Gateway never trusts input. Every message goes through 9 ordered validation layers before reaching an agent. |
| **Idempotent & Interruptible** | Every operation is tracked, deduplicated per peer, and cancelable. `tasks/cancel` propagates to the exact running coroutine in the owning downstream worker. |
| **Declarative UI** | The backend never sends HTML or JavaScript. It emits structured A2UI v1.0 envelopes that map to a `TrustedCatalog` of known React components. |
| **Hard Failures over Silent Fallbacks** | In grading mode (`AXIOM_MODE=grading`), missing Redis, missing embeddings, and missing account data are exposed as hard errors — never silently replaced with mock data. |
| **Two-Stage LLM Pattern** | Every agent that needs both tools *and* structured output uses Stage A (tools, no schema) → Stage B (schema, no tools). This is an explicit workaround for the ADK `output_schema + tools` conflict. |

### What AXIOM is NOT

- It does not use `ADK.to_a2a()`. The full A2A wire protocol is implemented manually in `gateway/main.py` to give complete control over validation, deduplication, and state-machine enforcement.
- It does not serve a production frontend bundle. The React component in `frontend/components/TrustedCatalog.tsx` is included for grading inspection only.
- It does not use `gemini-2.0-*` models. All such models were shut down before the hackathon date. See [Section 17](#17-model-selection--startup-verification) for exact versions.

---

## 2. Repository Layout & File Catalogue

```
axiom/
├── .env                         # Live API keys (not committed)
├── .env.example                 # Full documentation of every env var
├── .ruff.toml                   # Ruff linter config — strict Python style
├── mypy.ini                     # MyPy type-checking config
├── pytest.ini                   # pytest root config, asyncio mode
├── requirements.txt             # Pinned Python dependencies
├── requirements.md              # Human-readable dependency rationale
│
├── config.py                    # SINGLE SOURCE OF TRUTH for all settings
├── agent_card.py                # A2A v0.3 identity document
├── run.bat                      # Windows launcher — starts all 4 Uvicorn workers
│
├── gateway/
│   ├── main.py                  # Phalanx gateway — 9-layer pipeline
│   ├── state_machine.py         # Task shadow tracker + circuit breaker
│   └── validators/
│       ├── rpc_validator.py     # JSON-RPC 2.0 envelope validation
│       └── a2a_validator.py     # A2A semantic validation (TolerantMessage etc.)
│
├── apps/
│   ├── a2a_utils.py             # Shared envelope parsing (text + deterministic IDs)
│   ├── app_personal.py          # FastAPI worker: Personal (Tier 1)
│   ├── app_cs.py                # FastAPI worker: Customer Service (Tier 2)
│   └── app_research.py          # FastAPI worker: Research (Tier 3)
│
├── agents/
│   ├── personal_agent.py        # ADK LlmAgent: IntakeClassification
│   ├── cs_agent.py              # ADK LlmAgents: Stage A reasoning + Stage B formatter
│   └── research_agent.py        # ADK LlmAgent: ResearchResult formatter (two instances)
│
├── orchestrator/
│   ├── workflow.py              # AxiomOrchestrator (BaseNode) — full pipeline
│   └── timeout_manager.py       # Async timeout wrapper utilities
│
├── redis_fabric/
│   ├── fabric.py                # 4-plane Redis memory architecture + SQLite fallback
│   └── ids.py                   # Deterministic session/task ID derivation (SHA256)
│
├── tools/
│   ├── account_tools.py         # ADK tools: account lookup, order status, policy retrieval
│   └── linkup_search.py         # LinkUp API wrapper (external web research)
│
├── network/
│   ├── adk_helper.py            # ADK Context factory (InvocationContext setup)
│   └── agent_discovery.py       # Agent capability discovery helper
│
├── frontend/
│   ├── ag_ui_bridge.py          # AG-UI SSE bridge (Redis stream → SSE frames)
│   └── components/
│       └── TrustedCatalog.tsx   # A2UI v1.0 declarative component renderer
│
├── background/
│   ├── sweeper.py               # Redis stream PEL recovery (XAUTOCLAIM)
│   └── __init__.py
│
├── docs/
│   └── design.md                # Master design spec v2.0 (trap analysis, pseudocode)
│
├── tests/
│   ├── conftest.py              # REPO_ROOT, PYTHON_EXE, wait_for_health()
│   ├── test_system.py           # 13 unit tests (no network, mocked Redis)
│   ├── test_integration.py      # 6 cross-process HTTP tests (4 Uvicorn workers)
│   └── test_e2e_run.py          # Live smoke test (skipped in CI; manual __main__)
│
└── .axiom_fallback_db.sqlite    # Runtime artifact — shared SQLite fallback DB
```

---

## 3. Protocol Stack

### 3.1 A2A v0.3 (Agent-to-Agent RPC)

AXIOM implements the **A2A v0.3 specification** over JSON-RPC 2.0. Every outbound response is a valid A2A `Task` or `Message` object.

**Wire format — all requests must conform to:**
```json
{
  "jsonrpc": "2.0",
  "method": "message/send",
  "id": "req-001",
  "params": {
    "message": {
      "role": "user",
      "messageId": "msg-001",
      "parts": [
        { "kind": "text", "text": "I need a refund for order ORD-99887" }
      ],
      "metadata": { "agentId": "peer-agent-xyz" }
    }
  }
}
```

**Required fields enforced by `TolerantMessage`:**
- `role` — must be `"user"` or `"agent"` (not `"system"`)
- `parts` — must be a non-empty list
- `messageId` — **required** (A2A v0.3 spec §4.1). Server NEVER auto-generates it. Absence returns a `ValidationError` (-32602). Deduplication is keyed by `{peer_id}:{messageId}` — server-side generation would break idempotent retry semantics.

**Supported methods:**
| Method | Handler |
|---|---|
| `message/send` | Full pipeline, returns Task |
| `tasks/get` | Direct gateway lookup from Redis |
| `tasks/cancel` | Gateway cancels asyncio task + propagates to worker |
| `tasks/pushNotificationConfig/set` | Stub — returns `-32004 Unsupported` |
| `message/stream` | Stub — returns `-32004 Unsupported` |

**Part normalisation (`TolerantPart`):**
Some clients send `"type": "text"` instead of the v0.3 `"kind": "text"`. The gateway accepts both but always emits `"kind"` downstream.

**A2A Task response example:**
```json
{
  "jsonrpc": "2.0",
  "result": {
    "id": "tsk_abc123",
    "contextId": "ses_xyz789",
    "kind": "task",
    "status": { "state": "completed" },
    "artifacts": [
      {
        "artifactId": "resolution_artifact",
        "parts": [{ "kind": "data", "data": { "resolution_status": "resolved" } }]
      }
    ]
  }
}
```

### 3.2 AG-UI v1.0 (Agent User Interface Events)

The `frontend/ag_ui_bridge.py` module converts Redis stream events into **AG-UI v1.0 SSE frames**. CopilotKit consumes these via `GET /sse/{session_id}`.

**Event lifecycle for a complete request:**
```
RUN_STARTED     { threadId, runId }
STATE_SNAPSHOT  { snapshot: { session_id, status } }
STATE_DELTA     { delta: [{ op, path, value }] }   ← intake classified
STATE_DELTA     { delta: [{ op, path, value }] }   ← research completed
STATE_DELTA     { delta: [{ op, path, value }] }   ← resolution ready
TEXT_MESSAGE_START  { messageId, role: "assistant" }
TEXT_MESSAGE_CONTENT { messageId, delta: "..." }
TEXT_MESSAGE_END    { messageId }
RUN_FINISHED    { threadId, runId }
```

**Critical compliance points:**
- Both `threadId` (long-lived conversation = session_id) and `runId` (per-execution UUID) are **required** on `RUN_STARTED` and `RUN_FINISHED`.
- `TEXT_MESSAGE_START` must include `role: "assistant"`.
- `messageId` is scoped to `{session_id[:8]}_{run_id[:8]}` for stability across reconnects.
- Heartbeat comments (`: heartbeat`) are emitted every 15 seconds to keep NAT connections alive.

### 3.3 A2UI v1.0 candidate (Surface Protocol)

AXIOM's frontend uses **A2UI v1.0 candidate** envelopes to securely drive the React surface. The backend never sends raw HTML or JavaScript — only structured envelopes that map to named entries in `TRUSTED_CATALOG`.

**Supported envelope types and their exact schemas:**

**`createSurface`** — must be sent before any update:
```json
{ "version": "v1.0", "createSurface": { "surfaceId": "case-123", "catalogId": "...", "title": "..." } }
```

**`updateComponents`** — must include exactly one component with `id: "root"`:
```json
{
  "version": "v1.0",
  "updateComponents": {
    "surfaceId": "case-123",
    "components": [
      { "id": "root", "component": "ResolutionCard", "status": "resolved", "summary": "..." }
    ]
  }
}
```

**`updateDataModel`** — patch a data path without re-rendering:
```json
{ "version": "v1.0", "updateDataModel": { "surfaceId": "case-123", "path": "/resolution", "value": { "status": "resolved" } } }
```

**`deleteSurface`** — tear down:
```json
{ "version": "v1.0", "deleteSurface": { "surfaceId": "case-123" } }
```

**`callFunction`** — correlation IDs are **top-level** (not nested inside `callFunction`):
```json
{ "version": "v1.0", "functionCallId": "call-789", "wantResponse": true, "callFunction": { "call": "triggerPrint", "args": { "format": "pdf" } } }
```

**`actionResponse`** — `actionId` is **top-level** (not nested):
```json
{ "version": "v1.0", "actionId": "act-456", "actionResponse": { "value": { "success": true } } }
```

> **Why correlation IDs are top-level:** In A2UI v1.0, `functionCallId` and `actionId` are envelope-level correlation identifiers, not payload fields. Placing them inside the nested object would prevent the router from inspecting them without deserialising the payload.

---

## 4. Network Topology & Process Map

```
Internet / Peer Agent
        │
        ▼ POST /a2a/{target_agent}
┌─────────────────────────────┐
│   Phalanx Gateway           │  localhost:8080
│   gateway/main.py           │
│   9-layer validation        │
│   _ACTIVE_TASKS by taskId   │
└──────────┬──────────────────┘
           │  POST /run  (JSON-RPC forwarded)
     ┌─────┴──────────────────────────────────┐
     │               │                         │
     ▼               ▼                         ▼
┌─────────┐   ┌─────────────┐         ┌─────────────┐
│Personal │   │ Customer    │         │ Research    │
│app      │   │ Service app │         │ app         │
│:8081    │   │ :8082       │         │ :8083       │
│         │   │             │         │             │
│personal │   │ Orchestrator│         │ linkup_search│
│_agent   │   │ → personal  │         │ → research  │
│         │   │ → research  │         │   _formatter │
│         │   │ → cs_reason │         │             │
│         │   │ → cs_format │         │             │
└────┬────┘   └──────┬──────┘         └──────┬──────┘
     │               │                        │
     └───────────────┴──────────┬─────────────┘
                                ▼
                    ┌────────────────────┐
                    │  Redis             │
                    │  Session hashes    │
                    │  axiom:events      │
                    │  memory:*          │
                    │  cache:*           │
                    │  dedup:*           │
                    │  shadow:task:*     │
                    └────────────────────┘
                                │
                                ▼ XREAD
                    ┌────────────────────┐
                    │ AG-UI SSE Bridge   │
                    │ GET /sse/:session  │
                    └────────────────────┘
                                │
                                ▼ text/event-stream
                    ┌────────────────────┐
                    │ CopilotKit / React │
                    │ frontend           │
                    └────────────────────┘
```

Each of the four services is an independent Python process started with Uvicorn. They share no in-process state — all communication goes through Redis/SQLite or HTTP.

**Gateway internal routing** (`_internal_agent_routes()` — resolved at call time from env vars):

| `target_agent` path segment | Worker URL |
|---|---|
| `personal` | `http://127.0.0.1:{PORT_PERSONAL}` |
| `customer_service` | `http://127.0.0.1:{PORT_CS}` |
| `research` | `http://127.0.0.1:{PORT_RESEARCH}` |

Ports are read from `PORT_PERSONAL`, `PORT_CS`, `PORT_RESEARCH` at **request time** (not import time) so integration tests can bind dynamic free ports.

---

## 5. The Phalanx Gateway — `gateway/`

### 5.1 `gateway/main.py` — 9-layer pipeline

The gateway is the public-facing ingress controller. It receives **all** external A2A traffic and must fully sanitise it before forwarding to any internal worker.

**`_ACTIVE_TASKS: dict[str, asyncio.Task]`** — maps **taskId → asyncio.Task**. Keyed by `taskId` (not `contextId`/`sessionId`) so that `tasks/cancel` can target the exact coroutine representing that specific task, regardless of the session it belongs to.

**`_TERMINAL_TASK_IDS: set[str]`** — in-memory set of task IDs that have reached a terminal state via `tasks/cancel` or Layer 8 SQLite lookup. Checked **before** any Redis round-trip so append-to-canceled requests return instantly even when Redis is offline or a downstream worker races to overwrite SQLite status.

**`GATEWAY_CLIENT`** — single global `httpx.AsyncClient` instantiated at module level. This is critical: creating a new `AsyncClient` per request would exhaust file descriptors within seconds under load. The single client maintains a connection pool (50 max, 20 keepalive) and reuses SSL sessions.

**`lifespan(app)`** — FastAPI lifespan context manager:
1. Connects to Redis, creates `TaskStateMachineTracker`.
2. Seeds mock account data (ACC-12345, ACC-67890) and policy documents — **skipped when `AXIOM_MODE=test`** so CI startup never blocks on Redis.
3. On shutdown, closes the global `GATEWAY_CLIENT`.

**HTTP routes exposed by the gateway:**

| Route | Method | Purpose |
|---|---|---|
| `/health` | GET | Liveness probe (`{"status":"ok","service":"phalanx-gateway"}`) |
| `/.well-known/agent-card.json` | GET | A2A v0.3 Agent Card |
| `/sse/{session_id}` | GET | AG-UI v1.0 SSE event stream |
| `/a2a/{target_agent}` | POST | All A2A JSON-RPC methods |

**`_extract_agent_logical_id(body, request)`** — extracts a stable peer identifier:
1. Reads `params.message.metadata.agentId` if present (well-behaved peers).
2. Falls back to `SHA-256[:16]` of `host:port` — includes port so multiple processes on the same host are tracked separately.
3. This ID feeds the circuit breaker and deduplication key.

**The 9 layers in order:**

| Layer | Check | Action on Failure |
|---|---|---|
| 0 | Content-Length > 512 KB | HTTP 413 |
| 1 | JSON-RPC 2.0 structure (`jsonrpc`, `method`, `id`) | JSON-RPC error -32600 |
| 3a | `tasks/get` direct handler | Returns Task from Redis/SQLite |
| 3b | `tasks/cancel` direct handler | Cancels local + downstream + updates session + `_TERMINAL_TASK_IDS` |
| 2 | Unimplemented methods | JSON-RPC error -32004 |
| 4 | Payload sanitisation (zero-width chars, 512 KB string content) | JSON-RPC error -32602 |
| **8-early** | Terminal state guard (before Redis) | JSON-RPC error -32600 if `taskId` append to terminal task |
| 5 | A2A semantic validation (`TolerantMessage`, `TolerantPart`) | JSON-RPC error -32602 |
| 6 | Deduplication: `dedup:{peer_id}:{messageId}` → existing Task | Returns cached Task |
| 7 | State machine transition + circuit breaker | JSON-RPC error -32000 (skipped in `AXIOM_MODE=test`) |
| 8-late | Terminal state guard (SQLite + `_TERMINAL_TASK_IDS` belt-and-suspenders) | JSON-RPC error -32600 |
| 9 | Route to internal worker (blocking or fire-and-forget) | HTTP 404 if unknown route |

> **Why Layer 8 runs twice:** The early guard (after Layer 4) executes before Layer 6 Redis dedup and Layer 7 shadow-tracker calls. Without this, a request to append to a canceled task would block for several seconds waiting on Redis timeouts when Redis is offline, then fall through to a blocking downstream dispatch. The late guard catches terminal status discovered via SQLite.

**Dedup registration timing:** `_register_message_dedup()` is called **before** dispatch (both blocking and non-blocking). In-flight retries with the same `{peer_id}:{messageId}` therefore return the same `taskId` rather than spawning duplicate workers.

**Blocking vs. non-blocking dispatch (Layer 9):**
- Controlled by `params.configuration.blocking` (default `true` when absent).
- If `blocking == true`: the gateway `await`s the downstream response. The client receives the final completed Task.
- If `blocking == false`: the coroutine is launched as a background asyncio task. The gateway immediately returns a `submitted` Task and seeds a minimal SQLite/Redis session so `tasks/cancel` and Layer 8 can find the task before the worker finishes.

**Cancellation propagation:**
1. `_ACTIVE_TASKS.pop(task_id).cancel()` — raises `CancelledError` on the local awaiting coroutine.
2. `POST {target_url}/cancel` with `{"taskId": task_id}` — tells the owning worker process to cancel its running asyncio task.
3. `set_session_status(session_id, "canceled")` — marks session as terminal in Redis/SQLite.
4. `_TERMINAL_TASK_IDS.add(task_id)` — records terminal state in gateway memory (race-proof).
5. `XADD axiom:events` — emits `task_canceled` event so the SSE bridge can close the client stream.

### 5.2 `gateway/state_machine.py` — Shadow task tracker

**`TaskState` (Enum):** Defines all valid A2A v0.3 states: `submitted`, `working`, `input-required`, `completed`, `failed`, `canceled`, `auth-required`, `rejected`.

**`TERMINAL_STATES`:** `{completed, failed, canceled, rejected}`. Once a task reaches a terminal state, no further transitions are permitted from the shadow tracker's perspective.

**`VALID_TRANSITIONS`:** An explicit allowlist of valid forward moves:
```
submitted  → working | failed | canceled | auth-required | rejected
working    → completed | failed | input-required | canceled
input-required → working | canceled | failed
auth-required  → submitted | failed
completed  → (none)
failed     → (none)
canceled   → (none)
rejected   → (none)
```

**Idempotency rules:**
- Same state reported again (`working → working`): accepted silently — at-least-once delivery.
- Terminal state notified again (`completed → completed`): accepted — polling systems may replay.
- Terminal → different terminal (`completed → failed`): also accepted as idempotent — the first terminal write wins.

**Circuit breaker:**
- Keyed by `circuit:{agent_logical_id}:failures`.
- Three failures within `CIRCUIT_BAN_SECONDS` (default 120s) trigger the circuit.
- Short window avoids the "30-minute spoofable ban" problem: an attacker who knows the circuit-breaker key cannot trigger a long-running denial of service.

### 5.3 `gateway/validators/rpc_validator.py`

Validates the JSON-RPC 2.0 envelope before any semantic interpretation:
- `jsonrpc` field must be exactly `"2.0"`.
- `method` must be in `ALLOWED_METHODS`.
- `id` must be present (non-null).
- Returns a typed `JsonRpcEnvelope` Pydantic model on success, `None` on failure.

**TRAP 5 / interoperability:** `JsonRpcEnvelope` uses `model_config = {"extra": "ignore"}`. ADK 1.x and rival-team payloads often include extra fields (`node_info`, `output`, etc.). Using `extra='forbid'` would reject those envelopes and zero out interoperability scoring. AXIOM accepts unknown fields silently and validates only the structural core.

`ALLOWED_METHODS` includes `message/send`, `tasks/get`, `tasks/cancel`, and push-notification stubs.
`UNIMPLEMENTED_METHODS` is a subset of `ALLOWED_METHODS` that are advertised but return `-32004`.

### 5.4 `gateway/validators/a2a_validator.py`

**`TolerantPart`** — accepts `kind` (v0.3) or `type` (legacy), infers kind from content:
- Has text → `kind: "text"`
- Has data → `kind: "data"`
- Neither → raises `ValueError("Cannot determine part kind")` on `.normalized_kind` access.
- **`model_config = {"extra": "ignore"}`** — unknown part fields from other A2A implementations are tolerated.

**`TolerantMessage`** — enforces A2A v0.3 message structure:
- `role` must be `"user"` or `"agent"`. `"system"` is rejected.
- `parts` must be a non-empty list.
- `messageId` is **required** and must be a non-empty string. The server never auto-generates it. Absence or empty string returns `ValidationError` (-32602). Deduplication is keyed by `{peer_id}:{messageId}` — server-side generation would break idempotent retry semantics.
- **`model_config = {"extra": "ignore"}`** — same TRAP 5 rule as `JsonRpcEnvelope`; metadata and extension fields pass through without rejection.

**`sanitise_payload(body)`** — security sanitisation:
- Recursively strips zero-width characters: U+200B, U+FEFF, U+200C, U+200D, U+2060.
- Rejects the entire payload if serialised size exceeds 512 KB.
- Returns `(clean_body, warnings_list)`.

---

## 6. Internal Agent Workers — `apps/`

Each app is a **standalone FastAPI process** started by Uvicorn. They are completely isolated from each other. They communicate only through:
- HTTP calls from the gateway (`POST /run`)
- Redis reads/writes (via `redis_fabric/fabric.py`)
- The shared SQLite fallback file (`.axiom_fallback_db.sqlite`) when Redis is offline

All three apps expose:
- `GET /health` — liveness probe
- `POST /run` — main execution endpoint (JSON-RPC body forwarded from gateway)
- `POST /cancel` — cancel a running taskId
- `GET /active_tasks` — list in-flight task IDs (used by cancel integration tests)

### 6.0 `apps/a2a_utils.py`

Shared parsing for all worker `/run` endpoints. The gateway forwards the full JSON-RPC envelope; workers must **not** pass the raw envelope to the LLM.

**`extract_message_text(msg_dict)`** — pulls plain text from the first `kind: text` (or legacy `type: text`) part.

**`resolve_ids_from_envelope(body, peer_id=None)`** — returns `(session_id, task_id, message_text)`:
- Reads explicit `contextId` / `taskId` from params when present.
- Falls back to `derive_session_id()` / `derive_task_id()` from `redis_fabric/ids.py` for retry-safe deterministic IDs.
- Ensures the orchestrator always receives **text intent**, not wire-format JSON.

### 6.1 `apps/app_personal.py`

**Purpose:** Tier 1 classifier. Transforms raw customer text into a structured `IntakeClassification`.

**What it does:**
1. Parses envelope via `resolve_ids_from_envelope(body)`.
2. Registers `asyncio.current_task()` in `_ACTIVE_TASKS[task_id]`.
3. Creates an ADK `Context` via `create_adk_context(session_id)`.
4. Runs `personal_agent` (which produces `IntakeClassification` in `ctx.state["intake_classification"]`).
5. Returns a completed A2A Task object regardless of classification result.

**`/cancel` route:** Looks up `task_id` in `_ACTIVE_TASKS`, calls `.cancel()`, returns status.

**Why it doesn't forward the classification downstream:** The personal agent is the entry point for standalone classification requests. The full pipeline (personal → research → CS) runs in `app_cs.py` via the orchestrator.

### 6.2 `apps/app_cs.py`

**Purpose:** Tier 2 — the primary customer service workflow endpoint. Runs the complete `AxiomOrchestrator` pipeline. This is the route behind `/a2a/customer_service`.

**`AXIOM_MODE=test` short-circuit:** When test mode is active, `/run` bypasses ADK and the orchestrator entirely. It completes tasks via SQLite-backed transitions in milliseconds — no Gemini or LinkUp calls. Messages containing `"slow task please"` hold the coroutine open for 30 seconds so `tasks/cancel` integration tests have a cancellable in-flight task.

**What it does (production / development):**
1. Parses envelope via `resolve_ids_from_envelope(body)`.
2. Creates `AxiomOrchestrator` and an ADK `Context`.
3. Registers `asyncio.current_task()` in `_ACTIVE_TASKS[task_id]`.
4. Iterates `orchestrator.run(ctx, input_data)` — the full 3-tier pipeline (Tier 1 → Tier 3 Research → Tier 2 CS).
5. Returns the last yielded output as a completed Task with `resolution_artifact`.

**Why the orchestrator is here and not in a separate service:** The CS orchestrator coordinates agents within a single process to avoid multi-hop HTTP overhead for the sequential pipeline. Only the Research tier makes external calls via `linkup_search`.

### 6.3 `apps/app_research.py`

**Purpose:** Tier 3 — standalone research endpoint. Used when the orchestrator calls `linkup_search` or when a direct research-only request is made.

**What it does:**
1. Runs `linkup_search(input_text, depth="standard")`.
2. On failure, stores a structured error artifact (not an exception — the caller can see what failed).
3. Runs `research_formatter` to produce a `ResearchResult` Pydantic object.
4. Handles `asyncio.CancelledError` explicitly and returns a `canceled` Task — this is the clean-cancel path.

**Error artifact format:**
```json
{
  "query_answered": "...",
  "answer": "SYSTEM ERROR: Information retrieval failed (ConnectionError: ...)",
  "sources": [],
  "confidence": 0.0,
  "result_type": "error"
}
```
This format is intentional: the CS agent's prompt instructs it to acknowledge missing context explicitly rather than hallucinate.

---

## 7. ADK Agent Definitions — `agents/`

### 7.1 `agents/personal_agent.py`

**`personal_agent` (`LlmAgent`):**
- **Model:** `INTAKE_MODEL` (`gemini-3.1-flash-lite` — fast, cheap, zero tool calls)
- **Pattern:** schema-only, no tools — avoids the `output_schema + tools` ADK trap
- **Output key:** `intake_classification` (written to `ctx.state`)
- **Output schema:** `IntakeClassification`

**`IntakeClassification` fields:**
| Field | Type | Purpose |
|---|---|---|
| `intent` | Literal enum | One of 6 intent categories |
| `session_id` | str | Carried through from input, never regenerated |
| `task_id` | str | Carried through from input, never regenerated |
| `confidence` | float [0,1] | How certain the classification is |
| `requires_research` | bool | Triggers Tier 3 research pass if True |
| `extracted_account_id` | str or None | e.g. "ACC-12345" |
| `sanitised_summary` | str | 1-2 sentence compression — the ONLY form of raw text that travels downstream |

**Why `sanitised_summary` is important:** Raw customer messages can contain PII, prompt injection attempts, or excessively long context. The personal agent is the last point that sees raw input; everything downstream sees only this compressed, sanitised version.

### 7.2 `agents/cs_agent.py`

Uses the **two-stage pattern** to avoid the `output_schema + tools` conflict:

**Stage A — `cs_reasoning_agent` (`LlmAgent`):**
- **Model:** `REASONING_MODEL` (`gemini-3.1-pro-preview`, fallback `gemini-3.5-flash`)
- **Has tools, no `output_schema`**
- Tools available: `fetch_account_data`, `lookup_order_status`, `check_return_eligibility`, `get_policy_document`, `write_resolution_draft`
- Writes its resolution to `ctx.state["resolution_draft"]` by calling `write_resolution_draft`
- **Research failure guard (prompt):** If `{research_results}` contains `result_type: "error"`, `confidence: 0.0`, or a `SYSTEM ERROR` string, the agent must not cite external policy or product facts from that entry — it must acknowledge missing context and escalate or request more input. This is the second line of defense after the orchestrator's structured error artifacts (BUG 4).

**Stage B — `cs_formatter_agent` (`LlmAgent`):**
- **Model:** `FORMATTER_MODEL` (`gemini-3.1-flash-lite`)
- **Has `output_schema`, no tools**
- Reads `{resolution_draft}` from `ctx.state` via template substitution
- Produces `ResolutionPayload` written to `ctx.state["resolution_payload"]`

**`ResolutionPayload` fields:**
| Field | Type | Meaning |
|---|---|---|
| `resolution_status` | Literal | `resolved`, `partial`, `escalated`, `requires_input` |
| `resolution_summary` | str | Customer-facing text, max 300 words |
| `follow_up_actions` | list[str] | Suggested next steps |

> **Note on internal vs public resolution payloads:** The `ResolutionPayloadInternal` includes `internal_notes`, `confidence_score`, `requires_human_review`, and `missing_context`. The Gateway's `tasks/get` explicitly filters the output to only return `ResolutionPayloadPublic` (status, summary, actions) to external peers.

### 7.3 `agents/research_agent.py`

Two identical formatter instances (`research_formatter_0`, `research_formatter_1`) exist to avoid the **parallel agent shared-state bug**:

If two concurrent coroutines both call `await ctx.run_node(research_formatter, query)`, the ADK writes to the same `output_key`, creating a last-write-wins race condition. The fix: each parallel research query uses a dedicated instance with a unique `output_key` (`research_results_0`, `research_results_1`).

**`ResearchResult` schema:**
```python
class ResearchResult(BaseModel):
    query_answered: str
    answer: str
    sources: list[str]
    confidence: float
    result_type: Literal["success", "partial", "error"]
```

---

## 8. The Orchestrator — `orchestrator/`

### 8.1 `orchestrator/workflow.py`

**`AxiomOrchestrator(BaseNode)`** — the central workflow coordinator. Uses `async def run(ctx, node_input)` as an `AsyncGenerator` so the caller can consume intermediate outputs via `async for`.

When `AXIOM_MODE=test`, `run()` short-circuits with a deterministic resolution payload (the CS worker also has an HTTP-level bypass in `app_cs.py` — either path prevents live API calls in CI).

**Critical rule:** The orchestrator calls agents via `create_adk_context()` + `ctx.run_node()` **in-process**. It never loops back through the gateway HTTP layer. Only external peers enter via the gateway.

**Full execution sequence:**
```
1. Parse session_id / task_id from node_input (dict or JSON string)
2. seed_session() → creates Redis session hash + task→session mapping
3. Run personal_agent (Tier 1) → ctx.state["intake_classification"]
4. [Hard postcondition] If classification missing → yield error, return
5. record_session_transition("intake_completed")
6. If classification.requires_research → _run_parallel_research()
7. search_customer_memories() for past interaction context
8. get_account_context() from Redis (or mock in development mode)
9. Run cs_reasoning_agent (Stage A) → ctx.state["resolution_draft"]
10. [Hard postcondition] If resolution_draft missing → yield escalation payload, return
11. Run cs_formatter_agent (Stage B) → ctx.state["resolution_payload"]
12. [Hard postcondition] If resolution_payload missing → yield error, return
13. record_session_transition("resolution_completed")
14. set_session_status(session_id, "completed")
15. asyncio.create_task(save_customer_memory(...))  ← background, non-blocking
16. yield {"session_id": ..., "resolution": ...}
```

**Hard postconditions (steps 4, 10, 12):**
The orchestrator checks that each stage produced its expected artifact before proceeding. If an artifact is missing, it short-circuits the pipeline and returns a deterministic error payload. This prevents the downstream formatter from producing a plausible-looking answer based on empty state.

**`_run_parallel_research(ctx, classification, session_id, task_id)`:**
- Builds up to 2 search queries from `_build_research_queries(classification)`.
- Runs them concurrently with `asyncio.gather`.
- Each uses its own indexed state keys (`research_query_0`, `raw_search_results_0`, `research_results_0`) to prevent shared-state corruption.
- Results are cached in Redis (`cache:{sha256(query)}`) with a 1-hour TTL.
- On failure, each query returns a structured error artifact (see `apps/app_research.py`).

**`_build_research_queries(classification)`:**
Maps intent to pre-defined query pairs:
```
billing_dispute   → ["billing dispute resolution refund policy", "billing error correction process"]
technical_support → ["technical troubleshooting {intent}", "known product issues support"]
product_return    → ["product return policy procedures", "return eligibility requirements"]
order_status      → ["order fulfillment tracking status", "shipping delay resolution"]
default           → ["customer service {intent} resolution policy"]
```

**Research Domain Scoping:** Queries are automatically suffixed with domain filters (`site:example.com`) if `RESEARCH_SCOPED_DOMAINS` is defined in `config.py`.

### 8.2 `orchestrator/timeout_manager.py`

Provides async timeout wrapper utilities used by the orchestrator and individual app endpoints. Wraps `asyncio.wait_for` with configurable timeout sourced from `config.ORCHESTRATOR_TIMEOUT`.

---

## 9. Redis Memory Fabric — `redis_fabric/fabric.py`

### Architecture Overview

The fabric implements a **4-plane memory architecture** within a single Redis instance. Each plane has a distinct key prefix, TTL policy, and purpose.

**Connection pool:** `aioredis.ConnectionPool.from_url` with:
- `socket_connect_timeout=2`, `socket_timeout=5` — fast fail when Redis is offline (prevents 30s hangs in CI)
- `socket_keepalive=True` — prevents silent NAT connection kills
- `TCP_KEEPIDLE=30, TCP_KEEPINTVL=10, TCP_KEEPCNT=3` — aggressive keepalive on Linux/Windows where supported
- `retry_on_timeout=True` — automatic retry on transient failures
- `max_connections=REDIS_MAX_CONNECTIONS` (default **200**) — sized for parallel research + gateway + workers

**Async SQLite:** All blocking `sqlite3` operations run via `_run_sqlite()` (thread-pool executor) so the FastAPI event loop is never blocked during fallback reads/writes.

### 9.1 Plane 1 — Session State (`session:{session_id}`)

A Redis Hash per active session. Written atomically via Lua scripts.

**Fields:**
```
session_id, task_id, created_at, status, tier,
raw_digest, intake_classification, resolution_payload,
research_result_0, research_result_1, error, last_updated
```

**`LUA_SEED`** — creates the session hash and task→session mapping in one atomic script, emitting a `session_created` event to Plane 2.

**`LUA_TRANSITION`** — atomically updates a field and appends an event. Critically, it checks the current `status` field before writing. If status is `completed`, `failed`, `canceled`, or `rejected`, it returns `TERMINAL_STATE: cannot update` — this is the optimistic concurrency guard. The Python caller catches this error and logs it.

**TTL:** 24 hours (`REDIS_SESSION_TTL`).

### 9.2 Plane 2 — Event Bus (`axiom:events`)

A single Redis Stream consumed by the AG-UI bridge. All agents write events here; the bridge reads them and translates to SSE frames.

**Stream entries contain:** `event`, `session_id`, `task_id`, `timestamp`, `payload_key` (the state field that was updated).

**Known events:** `session_created`, `intake_completed`, `research_completed`, `resolution_completed`, `task_canceled`, `session_failed`.

**`MAXLEN ~ 10000`** applied to all `XADD` calls — prevents unbounded memory growth in Redis. The `~` makes it approximate (fast) rather than exact (slow).

**BUG 2 audit — every production `XADD` path:**

| File | Call site | MAXLEN |
|---|---|---|
| `redis_fabric/fabric.py` | `LUA_SEED` Lua script | `MAXLEN ~ 10000` |
| `redis_fabric/fabric.py` | `LUA_TRANSITION` Lua script | `MAXLEN ~ 10000` |
| `gateway/main.py` | `task_canceled` event | `maxlen=10000, approximate=True` |
| `background/sweeper.py` | `session_stalled` event | `maxlen=10000, approximate=True` |
| `orchestrator/timeout_manager.py` | `external_task_polling`, `ghost_timeout` | `maxlen=10000, approximate=True` |

The sweeper intentionally does **not** `XADD` on reclaimed PEL messages (BUG 8 — would create duplicates).

### 9.3 Plane 3 — Vector Memory (`memory:{account_id}:{timestamp}`)

Stores resolved-interaction summaries with `gemini-embedding-2` vectors (768 dimensions).

**`get_embedding(text)`:**
- Calls `client.models.embed_content(model=EMBEDDING_MODEL, contents=text, config={"output_dimensionality": EMBEDDING_DIMENSIONS})`
- On any failure, raises `EmbeddingUnavailable` — **never returns a zero vector**.
- Zero vectors corrupt cosine similarity (both dot product and denominator go to 0).

**`save_customer_memory(account_id, summary)`:**
- Called asynchronously after resolution (non-blocking `asyncio.create_task`).
- If embedding fails, logs and returns — memory save is best-effort.
- Stores `{"summary", "timestamp", "vector", "embedding_status": "ok"}`.
- Entries without `"embedding_status": "ok"` are skipped during search.

**`search_customer_memories(account_id, query, limit=2)`:**
- Scans all `memory:{account_id}:*` keys.
- Embeds the query; computes cosine similarity against each stored vector.
- Only considers entries with `embedding_status: "ok"`.
- Skips zero-norm vectors (guard against corrupted data).
- Returns top-`limit` entries by similarity, sorted descending.

**TTL:** 30 days (`REDIS_MEMORY_TTL`).

### 9.4 Plane 4 — Research Cache (`cache:{sha256[:16]}`)

Stores LinkUp search results keyed by SHA-256 of `query+depth`. Prevents duplicate API calls for the same query within 1 hour (`REDIS_CACHE_TTL`).

The cache key is `sha256(query + "standard")[:16]` — a 16-hex-char prefix. Collision probability is negligible for the expected query volume (1 in 2^64).

### 9.5 SQLite Cross-Process Fallback

When `AXIOM_MODE` is not `"grading"`, all Redis functions degrade gracefully to a shared **SQLite database** at `.axiom_fallback_db.sqlite`. This is critical because the Gateway, Personal, CS, and Research workers run in separate Python processes — an in-memory dict fallback would be invisible across processes.

**Tables:**
| Table | Schema | Purpose |
|---|---|---|
| `sessions` | `session_id TEXT PK, data TEXT (JSON)` | Mirror of Redis `session:{id}` hash fields |
| `tasks` | `task_id TEXT PK, session_id TEXT` | Mirror of Redis `task:to:session:{id}` mapping |

**Mode-specific behaviour:**

| Mode | Redis | SQLite |
|---|---|---|
| `development` | Primary; SQLite on connection failure | Silent fallback |
| `test` | **Skipped entirely** for session CRUD | Primary store for CI |
| `grading` | Required; failures are hard errors | No fallback |

**Terminal session preservation:** `_sqlite_seed_fallback()` will not overwrite a session whose status is already `completed`, `failed`, `canceled`, or `rejected`. This prevents a race where a downstream worker's `seed_session()` resets a canceled task back to `active` after `tasks/cancel`.

**`MOCK_ACCOUNTS`** — in-memory fallback used only in `development` mode when Redis is down. In `grading` mode, `get_account_context()` returns `{"error": "account_not_found", "account_id": ...}` instead of fabricating data.

### 9.6 Deterministic IDs — `redis_fabric/ids.py`

Network retries must map to the same `taskId` and `session_id` when the caller re-sends the same `messageId` and payload. Random `uuid4()` breaks deduplication and causes `tasks/get` to return stale tasks.

| Function | Input priority | Output format |
|---|---|---|
| `stable_id(prefix, *parts)` | SHA256 of joined parts | `{prefix}_{hash[:20]}` |
| `derive_session_id()` | explicit `contextId` → else fingerprint of `peer_id + messageId + raw_message` | `ses_...` |
| `derive_task_id()` | explicit `taskId` → else `peer_id + messageId` → else `session_id + messageId` → else `rpc_id` | `tsk_...` |

Used by: gateway Layer 9 (task assignment), gateway non-blocking seed, all worker `/run` endpoints via `a2a_utils`, orchestrator `seed_session()`.

---

## 10. Tools — `tools/`

### 10.1 `tools/account_tools.py`

All tools are regular Python `async def` functions decorated as ADK tools. They read from Redis (with `development`-mode in-memory fallback) and write to `ctx.state`.

**`fetch_account_data(account_id, ctx)`** — reads `account:{account_id}:context` from Redis.

**`lookup_order_status(order_id, ctx)`** — parses order data from account context and returns status string.

**`check_return_eligibility(order_id, account_id, ctx)`** — checks order status + tier + policy to determine return eligibility. Returns structured eligibility JSON.

**`get_policy_document(policy_name, ctx)`** — reads `policy:{policy_name}:content` from Redis. Policy documents are seeded at gateway startup.

**`write_resolution_draft(draft, ctx)`** — writes the resolution draft to `ctx.state["resolution_draft"]`. This is the Stage A → Stage B handoff mechanism. The formatter reads `{resolution_draft}` from its prompt template.

**Grading mode guard:** All fallbacks to mock data are gated by `AXIOM_MODE != "grading"`.

### 10.2 `tools/linkup_search.py`

Wraps the **LinkUp API** for real-time external web research.

**`LINKUP_CLIENT`** — single module-level `httpx.AsyncClient` (BUG 3 fix). Connection pool and TLS session are reused across all parallel `asyncio.gather` research calls. Never instantiate `AsyncClient` inside `linkup_search()` — that adds ~200ms SSL handshake overhead per query.

```python
LINKUP_CLIENT = httpx.AsyncClient(
    timeout=30.0,
    limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
)
```

**`linkup_search(query, depth="standard")`:**
- Uses `LINKUP_CLIENT.post(...)` to the LinkUp structured search endpoint.
- `depth` can be `"standard"` or `"deep"`. Standard is faster (used in parallel research); deep gives higher-quality results.
- Returns structured JSON with `answer`, `sources`, and `confidence`.
- On failure, **raises** the exception — never returns `None` or `[]`. Callers (`orchestrator/workflow.py`, `apps/app_research.py`) catch and build error artifacts with `confidence: 0.0` and `SYSTEM ERROR` text (BUG 4).

**Why LinkUp instead of Google Search:** LinkUp provides structured answer objects (not just URL lists), reducing the formatter's job to summarisation rather than extraction.

---

## 11. Frontend Bridge — `frontend/`

### 11.1 `frontend/ag_ui_bridge.py`

Converts the Redis `axiom:events` stream into AG-UI SSE frames. Runs as an infinite async generator, yielding frames to `StreamingResponse`.

**Session scoping:** Only events matching `session_id` are forwarded — other sessions' events are silently skipped.

**Heartbeat:** A comment line (`: heartbeat`) is yielded every `SSE_HEARTBEAT_INTERVAL` seconds (default 15). NAT devices that kill idle TCP connections at 30s will see activity and keep the connection open.

**Timeout:** After `SSE_MAX_WAIT` seconds (default 60) without a `resolution_completed` event, a `RUN_ERROR` frame is emitted and the generator exits.

**`build_ag_ui_event(event_type, data)`** — serialises a single SSE frame:
```
data: {"type": "EVENT_TYPE", ...extra_fields}

```
(Note the double newline — required by the SSE spec.)

### 11.2 `frontend/components/TrustedCatalog.tsx`

The complete A2UI v1.0 surface renderer in React/TypeScript.

**`TRUSTED_CATALOG`** — the allowlist of renderable components:
| Name | Purpose |
|---|---|
| `ResolutionCard` | Shows resolution status and summary |
| `EvidenceCard` | Shows research query + answer + sources |
| `StatusChip` | Inline status badge |
| `MissingInfoForm` | Lists required additional information |
| `ResearchTimeline` | Timeline of research steps |
| `TicketSummary` | Ticket ID and description header |

Unknown component names fall through to `TextFallback` (a `<pre>` JSON dump) rather than throwing — graceful degradation.

**`useA2UISurfaces()` hook:**
- Maintains a `Record<surfaceId, SurfaceState>` in React state.
- `handleEnvelope(envelope)` is the single entry point for all A2UI envelopes.
- **Protocol enforcement:** `updateComponents` and `updateDataModel` emit `console.warn` and return early if the `surfaceId` was not first registered by `createSurface`. This mirrors the A2UI spec requirement that `createSurface` precedes all other surface operations.

**`A2UISurfaceRenderer`** — renders a `SurfaceState` using `renderComponent` for each component in the list.

---

## 12. Configuration — `config.py`

**The single source of truth for all tunable parameters.** Every agent, worker, and piece of infrastructure reads from this file. Nothing is hardcoded in agent files.

All settings are read from environment variables with documented defaults. The `.env.example` file documents every variable.

### Model Settings
| Variable | Default | Notes |
|---|---|---|
| `INTAKE_MODEL` | `gemini-3.1-flash-lite` | Fast classifier, no tools |
| `FORMATTER_MODEL` | `gemini-3.1-flash-lite` | Schema formatter, no tools |
| `REASONING_MODEL` | `gemini-3.1-pro-preview` | Tool-using reasoner — verified at startup |
| `REASONING_FALLBACK_MODEL` | `gemini-3.5-flash` | Used if primary is unavailable |
| `RESEARCH_MODEL` | `gemini-3.1-flash-lite` | Research result formatter |
| `EMBEDDING_MODEL` | `gemini-embedding-2` | 768-dim output |
| `EMBEDDING_DIMENSIONS` | `768` | Reduced from 3072 for speed |

### Startup Readiness Check
When `AXIOM_MODE` is not `test` or `mock` and an API key is present, `config.py` calls `client.models.get(model=REASONING_MODEL)` at **import time**. If the check fails (model not found, quota error, network error), `REASONING_MODEL` is immediately overwritten with `REASONING_FALLBACK_MODEL`. This is logged clearly so operators can see which model is active before the first request.

### Redis Settings
| Variable | Default | Meaning |
|---|---|---|
| `REDIS_URL` | `redis://localhost:6379` | Connection URL |
| `REDIS_MAX_CONNECTIONS` | `200` | Connection pool size |
| `REDIS_SESSION_TTL` | `86400` | Session hash TTL (24h) |
| `REDIS_MEMORY_TTL` | `2592000` | Vector memory TTL (30d) |
| `REDIS_CACHE_TTL` | `3600` | Research result cache (1h) |
| `REDIS_STREAM_MAXLEN` | `10000` | Event stream cap |

### Circuit Breaker Settings
| Variable | Default | Meaning |
|---|---|---|
| `CIRCUIT_FAILURE_THRESHOLD` | `3` | Failures before circuit opens |
| `CIRCUIT_BAN_SECONDS` | `120` | Ban window (2 min, not 30 min) |

The ban window is deliberately short (2 minutes) to resist spoofed-agentId attacks. A 30-minute ban could be exploited by an attacker who discovers the agentId used by a legitimate service — 2 minutes limits the denial window.

---

## 13. Agent Card — `agent_card.py`

The A2A v0.3 agent identity document served at `GET /.well-known/agent-card.json`.

**Required fields validated by `test_agent_card_validation`:**
- `protocolVersion: "0.3.0"`
- `name`, `description`, `version`, `url`
- `defaultInputModes`, `defaultOutputModes`
- `capabilities.streaming: false` — AXIOM does not support streaming; clients must use `message/send` + `tasks/get`
- `capabilities.pushNotifications: false` — not implemented; webhook config returns `-32004`
- `skills[0].id`, `.name`, `.description`, `.tags`

---

## 14. Network Helpers — `network/`

### 14.1 `network/adk_helper.py`

**`create_adk_context(session_id, user_id="default_user")` → `tuple[Runner, object]`:**
Creates a correctly initialised ADK `Context` object for a given session:

1. `_SESSION_SERVICE.create_session(app_name, user_id, session_id)` — registers the session with the in-process `InMemorySessionService`.
2. Creates `RunConfig()` — default ADK execution configuration.
3. Creates `InvocationContext` with the session and run config.
4. **Manually sets `ic._event_queue = asyncio.Queue()`** — this is required because `InvocationContext._event_queue` is a `PrivateAttr(default=None)` in the ADK Pydantic model. When manually constructing the context (bypassing the `Runner` which would normally set this), the queue must be explicitly initialised. Without this, any `ctx.run_node()` call that tries to enqueue events raises:
   ```
   RuntimeError: _enqueue_event called but _event_queue is not set.
   Ensure the Runner initialises _event_queue on InvocationContext.
   ```
5. Wraps the `InvocationContext` in `Context` and returns it.

**`_SESSION_SERVICE`** — a single `InMemorySessionService` shared across all requests within one process. This is safe because each session has a unique `session_id` and the service is just a dict.

### 14.2 `network/agent_discovery.py`

Provides helpers for looking up internal agent capabilities and checking worker health. Used for agent card negotiation and capability matching.

---

## 15. Background Jobs — `background/`

### `background/sweeper.py` — Redis Stream PEL Recovery

Runs as a background asyncio task inside agent worker processes. Detects messages stuck in the Redis Stream **Pending Entry List (PEL)** for longer than 5 seconds using `XAUTOCLAIM`.

**Critical invariant:** XAUTOCLAIM already claims the message to the sweeper consumer. The sweeper must **not** call `XADD` again — that would create a duplicate entry that gets reclaimed on the next cycle, producing an infinite loop.

**On recovery:**
1. Sets session `status: failed` with `stall_reason` via direct `HSET` (not `LUA_TRANSITION`, which would reject writes to terminal sessions).
2. Emits `session_stalled` to `axiom:events` so the AG-UI bridge can emit `RUN_ERROR`.

### Orchestrator background tasks

- `save_customer_memory` — called via `asyncio.create_task()` after workflow completion. Non-blocking; failures are logged only.

---

## 16. Testing Strategy — `tests/`

### `pytest.ini`

```ini
[pytest]
asyncio_mode = auto
asyncio_default_fixture_loop_scope = function
pythonpath = .
```

`pythonpath = .` ensures `import gateway`, `import redis_fabric`, etc. work without manually setting `PYTHONPATH`.

### `tests/conftest.py`

Shared helpers for integration tests:
- `REPO_ROOT` — absolute path to repository root
- `PYTHON_EXE` — venv Python or system Python
- `wait_for_health(url)` — polls `GET /health` until 200 or timeout

### 16.1 `tests/test_system.py`

**13 unit tests.** Zero network calls. Redis interactions are mocked with `AsyncMock`. Runs in milliseconds.

| Test | What it covers |
|---|---|
| `test_rpc_envelope_validation` | Valid/invalid `jsonrpc`, `method`, `id` combinations |
| `test_tolerant_part_normalization` | `kind` vs `type` field acceptance, inference from content |
| `test_sanitise_payload` | Zero-width stripping, 512 KB size rejection |
| `test_tolerant_message_requires_role_and_parts` | A2A v0.3 field enforcement; missing `messageId` is a hard error |
| `test_task_state_machine_tracker` | Valid transitions, idempotent terminal events, circuit breaker |
| `test_redis_offline_fallback` | SQLite fallback for `seed_session` and `record_session_transition` when Redis is offline (isolated temp DB) |
| `test_account_context_fallback` | Development-mode mock account fallback on Redis failure |
| `test_tolerant_part_boundary_cases` | Empty part ValueError path |
| `test_state_machine_tracker_unknown_task` | Unknown taskId is tolerated |
| `test_agent_card_validation` | A2A v0.3 agent card required fields |
| `test_deterministic_ids_from_message_id` | Same `messageId` + peer → same `taskId` across calls |
| `test_sse_heartbeat_comment` | SSE heartbeat comment format (`: heartbeat`) |
| `test_ag_ui_event_serialization` | AG-UI frame format: threadId + runId on RUN_STARTED |

**Run command:**
```powershell
.\.axiom_env\Scripts\pytest.exe tests\test_system.py -v
```

### 16.2 `tests/test_integration.py`

**6 cross-process tests.** Spins up all 4 Uvicorn workers as subprocesses with `AXIOM_MODE=test` on dynamically allocated free ports. Issues real HTTP calls with `httpx`. Does **not** require Redis, Gemini, or LinkUp.

| Test | What it validates |
|---|---|
| `test_external_message_send` | Blocking `message/send` → completed Task in test mode |
| `test_external_tasks_get` | `tasks/get` returns the correct Task after creation |
| `test_duplicate_message_id` | Second request with same `messageId` from same peer returns the same `taskId` (idempotent) |
| `test_external_tasks_cancel` | Non-blocking slow task appears in `/active_tasks`, `tasks/cancel` transitions it to `canceled` |
| `test_invalid_terminal_restart` | Canceled task's `taskId` cannot be reused — Layer 8 returns `-32600` instantly |
| `test_legacy_type_discriminator_accepted` | Inbound parts using legacy `type` are accepted and normalized to `kind` |

**Design notes:**
- Tests use `127.0.0.1` not `localhost` to avoid Windows IPv6 resolution delays.
- Session fixture calls `wait_for_health()` on all four `/health` endpoints — no blind `sleep(10)`.
- Gateway seeds a minimal session record for non-blocking tasks immediately so `tasks/cancel` and Layer 8 can find the session before the downstream worker has started.

**Run command:**
```powershell
$env:AXIOM_MODE = "test"
.\.axiom_env\Scripts\pytest.exe tests\test_integration.py -v
```

### 16.3 `tests/test_e2e_run.py`

Live smoke test against a running gateway on `localhost:8080`. **Skipped in pytest** by default (`@pytest.mark.skip`). Run manually via `python tests/test_e2e_run.py` when the full stack is up with real API keys. Requires `messageId` in the payload.

---

## 17. Model Selection & Startup Verification

### Why these exact models

| Model | Provider Status (June 2026) | Role in AXIOM |
|---|---|---|
| `gemini-3.1-pro-preview` | Current stable preview | Reasoning (tool-using Stage A) |
| `gemini-3.5-flash` | Current stable | Fallback reasoning, research formatter |
| `gemini-3.1-flash-lite` | Current stable | Intake classification, CS formatting |
| `gemini-embedding-2` | Current stable | 768-dim vector embeddings |

**Deprecated models removed:**
- `gemini-2.0-flash` — shut down 2026-06-01
- `gemini-2.0-pro-exp-02-05` — never stable, experimental only
- `gemini-2.5-flash` / `gemini-2.5-pro` — shut down 2026-06-17
- `gemini-3.5-pro` — **invalid identifier; does not exist**
- `text-embedding-004` — shut down 2026-01-14

### Import-time verification

`config.py` performs a live `client.models.get()` check at import time when `AXIOM_MODE` is not `test` and an API key is present. If the check fails, `REASONING_MODEL` is immediately set to `REASONING_FALLBACK_MODEL` and a `[STARTUP CHECK]` warning is printed to stdout. This ensures the fallback is applied before the first request, not during it.

---

## 18. Security Model (Defensive / Zero-Trust-Inspired)

AXIOM applies a **defensive**, zero-trust-inspired security posture — it does not unconditionally trust any input, even from co-located services.

### Gateway defences

| Threat | Mitigation |
|---|---|
| Oversized payloads | Content-Length guard at Layer 0; serialised string check in sanitiser |
| Prompt injection via zero-width chars | Unicode sanitisation in `sanitise_payload` |
| Invalid JSON-RPC | Structural validation rejects malformed envelopes |
| Unknown A2A methods | Explicit allowlist in `ALLOWED_METHODS` |
| Duplicate request replay | Deduplication scoped to `{peer_id}:{messageId}` |
| Rival-team extra JSON fields (TRAP 5) | All gateway validators use `extra='ignore'` — never `forbid` |
| Appending to terminal tasks | Layer 8 terminal state guard |
| Agent spoofing via wrong role | `TolerantMessage` rejects `role: "system"` |
| Circuit-open DoS from degraded agents | Short-window (2 min) circuit breaker per agent logical ID |
| Spoofed agentId triggering long ban | Ban window is 2 min, not 30 min |

### Data plane defences

| Threat | Mitigation |
|---|---|
| Terminal state overwrite | Lua script + Python guard both block writes to completed/failed/canceled/rejected sessions |
| Zero-vector embedding corruption | `EmbeddingUnavailable` exception; never returns `[0.0]*768` |
| Mock customer data in grading | `AXIOM_MODE=grading` disables all mock fallbacks |
| Fabricated resolution from empty state | Hard postconditions in orchestrator |
| LinkUp failure → hallucinated policy | Structured error artifacts (`confidence: 0.0`, `SYSTEM ERROR`) + CS reasoning prompt guard |

### UI defences

| Threat | Mitigation |
|---|---|
| Agent injecting arbitrary HTML | `TRUSTED_CATALOG` allowlist; unknown components fall through to `TextFallback` (pre-escaped JSON) |
| Agent rendering before surface is created | `createSurface` guard in `useA2UISurfaces` |
| Untrusted catalog reference | `catalogId` is stored but not executed |

---

## 19. State Machine & Task Lifecycle

```
[client]  message/send
    │
    ▼
[gateway] → Layer 6 dedup check → [if duplicate] → return existing Task
    │
    ▼
[worker]  → seed_session() → status: active
    │
    ▼
    personal_agent (Tier 1)
    │
    ▼  record_session_transition("intake_completed")
    │
    ├─ [requires_research=True] ──→ parallel research
    │                                 record_session_transition("research_completed")
    │
    ▼
    cs_reasoning_agent (Stage A)
    │
    ├─ [draft missing] ──→ escalation payload → status: completed → return
    │
    ▼
    cs_formatter_agent (Stage B)
    │
    ├─ [payload missing] ──→ error → status: failed → return
    │
    ▼  record_session_transition("resolution_completed")
       set_session_status(completed)
       asyncio.create_task(save_customer_memory)
       yield result
```

**State values in Redis `session:{id}:status`:**
- `active` — in progress
- `completed` — final successful resolution
- `failed` — pipeline error, no resolution
- `canceled` — client-requested cancellation

**State values in shadow tracker (`shadow:task:{id}:state`):**
- `submitted` → `working` → `completed` | `failed` | `canceled`
- `input-required` ↔ `working`
- `auth-required` ↔ `submitted`

---

## 20. Embedding & Vector RAG Pipeline

### Why 768 dimensions?

`gemini-embedding-2` natively produces 3072-dimensional vectors. We configure `output_dimensionality=768` to reduce storage by 75% while retaining most semantic information. For short customer service summaries (< 200 words), 768 dimensions captures all meaningful variance.

### Why never zero-fill?

Cosine similarity is defined as:
$$\cos(\theta) = \frac{\vec{a} \cdot \vec{b}}{|\vec{a}||\vec{b}|}$$

If either vector is the zero vector, $|\vec{a}|$ or $|\vec{b}|$ equals 0, causing division by zero. A zero vector would also have identical cosine similarity to every other vector (undefined), corrupting retrieval rankings silently. AXIOM instead raises `EmbeddingUnavailable` so the caller can decide to retry or proceed without memory context.

### Retrieval flow

```
1. search_customer_memories(account_id, query, limit=2)
2. Scan all memory:{account_id}:* keys
3. get_embedding(query) → query_vector [768 floats]
4. For each memory entry:
     a. Skip if embedding_status != "ok"
     b. Load stored vector
     c. Compute cosine similarity
     d. Skip if either norm is 0
5. Sort by similarity descending, return top-2
6. Injected into account_context as past_memories field
```

---

## 21. Hard-Learned ADK Traps

### Trap 1: `output_schema + tools` Conflict
**Symptom:** Combining `output_schema` and `tools` on a single `LlmAgent` causes the Gemini API to either ignore the schema or produce malformed tool call attempts.

**Root cause:** The Gemini API's function-calling mode and structured output mode are mutually exclusive at the model level. ADK does not guard against this.

**Resolution:** Two-stage agent pattern. Stage A has `tools` but no `output_schema`. Stage B has `output_schema` but no `tools`. The handoff is via `ctx.state["resolution_draft"]`.

### Trap 2: Shared State Keys in Parallel Agents
**Symptom:** Two concurrent `await ctx.run_node(research_formatter, query)` calls writing to `ctx.state["research_results"]` produce last-write-wins corruption — one result silently overwrites the other.

**Root cause:** `ctx.state` is a shared mutable dict within an `InvocationContext`.

**Resolution:** Unique output keys per instance: `research_formatter_0` writes to `research_results_0`, `research_formatter_1` to `research_results_1`.

### Trap 3: ADK `KeyError` on Missing Template Variables
**Symptom:** If a prompt template contains `{resolution_draft}` and `ctx.state["resolution_draft"]` is absent (Stage A failed), the ADK raises `KeyError` before the LLM is even called.

**Root cause:** ADK eagerly formats the prompt string with `ctx.state` contents.

**Resolution:** Hard postcondition check before Stage B. If `resolution_draft` is missing, the orchestrator short-circuits and returns an escalation payload with `requires_human_review: True`.

### Trap 4: `kind` vs `type` Payload Field Skew
**Symptom:** External testers who have not read the A2A v0.3 spec carefully send `{"type": "text"}` instead of `{"kind": "text"}`.

**Root cause:** A2A v0.2 used `type`; v0.3 changed it to `kind`. Many example generators still produce `type`.

**Resolution:** `TolerantPart` accepts both fields; normalises to `kind` before forwarding. The gateway always emits `kind` in its responses.

### Design TRAP 5: `extra='forbid'` Breaks Interoperability
**Symptom:** Rival teams running ADK 1.x or slightly different A2A shapes send JSON with extra fields (`node_info`, `output`, vendor extensions). A strict Pydantic validator rejects the entire envelope.

**Root cause:** ADK 2.0 added required-looking fields to the Event schema; ADK 1.x payloads omit them. `extra='forbid'` turns benign skew into hard `-32602` failures.

**Resolution:** `JsonRpcEnvelope`, `TolerantMessage`, and `TolerantPart` all use `model_config = {"extra": "ignore"}`. Validate only required structural fields; strip nothing, reject nothing for unknown keys.

### Trap 5: `asyncio.Task.cancel()` Does Not Stop Uvicorn Workers
**Symptom:** Cancelling the local asyncio task in the gateway does not stop the downstream Uvicorn worker — the worker continues processing and spending tokens even after the client has been told the task is canceled.

**Root cause:** `asyncio.Task.cancel()` raises `CancelledError` on the *local* awaiting coroutine (the `await GATEWAY_CLIENT.post(...)` call). The remote HTTP server has no knowledge of this.

**Resolution (two-pronged):**
1. Gateway sends `POST /cancel` with `{"taskId": ...}` to the owning worker.
2. Each worker maintains `_ACTIVE_TASKS[task_id] = asyncio.current_task()`. On receiving `/cancel`, it looks up and cancels the running task, which interrupts `await ctx.run_node(...)` mid-stream.

---

## 22. Operational Runbook

### Starting the System

**Windows (recommended):**
```bat
run.bat
```
Creates/activates `.axiom_env`, loads `.env`, starts all four workers in separate terminal windows, waits 4 seconds for workers to bind, then starts the gateway.

**Manual (any OS):**
```bash
# Activate virtual environment
.axiom_env\Scripts\activate   # Windows
source .axiom_env/bin/activate  # Linux/macOS

# Start all 4 workers (separate terminals or a process manager)
uvicorn apps.app_personal:app --port 8081 --reload
uvicorn apps.app_cs:app --port 8082 --reload
uvicorn apps.app_research:app --port 8083 --reload
uvicorn gateway.main:app --port 8080 --reload
```

### Environment Variables

Copy `.env.example` to `.env` and fill in:
```
GEMINI_API_KEY=...
LINKUP_API_KEY=...
REDIS_URL=redis://localhost:6379
AXIOM_MODE=development
```

### Running Tests

```powershell
# Full suite (recommended — 19 passed, 1 skipped)
$env:AXIOM_MODE = "test"
.\.axiom_env\Scripts\pytest.exe -v

# Lint + type check
.\.axiom_env\Scripts\ruff.exe check .
.\.axiom_env\Scripts\mypy.exe .
```

Integration and unit tests run without API keys when `AXIOM_MODE=test`. Live E2E requires a running stack plus `GEMINI_API_KEY` / `LINKUP_API_KEY`.

### Sending a Test Request

```bash
curl -X POST http://localhost:8080/a2a/customer_service \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "method": "message/send",
    "id": "req-001",
    "params": {
      "message": {
        "role": "user",
        "messageId": "msg-001",
        "parts": [{"kind": "text", "text": "I need a refund for order ORD-99887"}],
        "metadata": {"agentId": "test-client"}
      }
    }
  }'
```

### Polling for Result

```bash
# Use the taskId from the response above
curl -X POST http://localhost:8080/a2a/customer_service \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "method": "tasks/get",
    "id": "req-002",
    "params": {"id": "tsk_..."}
  }'
```

### Cancelling a Task

```bash
curl -X POST http://localhost:8080/a2a/customer_service \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "method": "tasks/cancel",
    "id": "req-003",
    "params": {"id": "tsk_..."}
  }'
```

### Grading Mode

Set `AXIOM_MODE=grading` before starting workers. In this mode:
- No mock account data fallback — missing accounts return `account_not_found`.
- No zero-vector embedding fallback — `EmbeddingUnavailable` surfaces to caller.
- No silent Redis fallbacks — all Redis failures are hard errors.

This demonstrates real resilience rather than hiding failures behind mock data.

---

## 23. Runtime Modes (`AXIOM_MODE`)

`AXIOM_MODE` is read from the environment at import time in `config.py` and propagated to all modules. It controls mock behaviour, fallback policy, and test short-circuits.

| Mode | Purpose | Redis | SQLite | LLM/API calls | Mock accounts |
|---|---|---|---|---|---|
| `development` | Local hackathon dev | Primary; fallback on failure | Fallback on Redis failure | Live (if keys present) | Yes when Redis down |
| `test` | CI + integration tests | **Skipped** for session ops | Primary | **Short-circuited** in CS worker + orchestrator | N/A |
| `grading` | Judge harness / production demo | Required (hard fail) | Disabled | Live (required) | Never |

**What `test` mode short-circuits:**
- `apps/app_cs.py` `_run_test_mode()` — HTTP-level bypass, no ADK
- `orchestrator/workflow.py` — redundant guard inside `run()`
- `redis_fabric/fabric.py` — all session CRUD goes SQLite-first
- `gateway/main.py` — skips Redis seed at startup; skips Redis dedup + shadow state machine
- `config.py` — skips live Gemini model verification at import

**What `test` mode does NOT disable:**
- Gateway 9-layer validation pipeline (all layers still run)
- JSON-RPC / A2A protocol compliance
- Deterministic ID derivation
- Layer 8 terminal state guard
- Integration test subprocess HTTP calls (real Uvicorn workers)

---

## 24. Deterministic ID Derivation

See [Section 9.6](#96-deterministic-ids--redis_fabricidspy) for implementation. At a systems level:

```
Client sends message/send with messageId="msg-abc"
        │
        ▼
Gateway derives taskId = stable_id("tsk", peer_id, "msg-abc")
        │
        ├─ Same messageId + same peer → same taskId on retry (Layer 6 dedup)
        │
        ▼
Worker receives taskId in params, passes text (not envelope) to orchestrator
        │
        ▼
seed_session() writes session + task mapping to Redis or SQLite
        │
        ▼
tasks/get and tasks/cancel look up via task:to:session mapping
```

**Never use `uuid4()` for task or session IDs in the request path.** UUIDs are only used for correlation headers (`X-Correlation-ID`) and AG-UI `runId` values where uniqueness per invocation is desired.

---

## 25. How the Pieces Fit Together

### Request path (happy path)

```
1. External peer → POST /a2a/customer_service (message/send)
2. Gateway validates (9 layers), derives taskId, registers dedup
3. Gateway → POST http://127.0.0.1:8082/run (CS worker)
4. CS worker parses text + IDs via a2a_utils
5. AxiomOrchestrator.run():
     a. seed_session (Redis or SQLite)
     b. Tier 1: personal_agent → intake_classification
     c. Tier 3 (optional): parallel linkup_search + research_formatter_0/1
     d. Tier 2: cs_reasoning_agent (tools) → cs_formatter_agent (schema)
     e. record_session_transition(resolution_completed)
     f. background: save_customer_memory
6. CS worker returns completed A2A Task with resolution artifact
7. Gateway forwards JSON-RPC result to peer
```

### UI observation path (parallel)

```
1. Frontend/CopilotKit → GET /sse/{session_id}
2. ag_ui_bridge XREADs axiom:events filtered by session_id
3. Events translated to AG-UI frames (RUN_STARTED → STATE_DELTA → TEXT_MESSAGE → RUN_FINISHED)
4. Heartbeat comments every 15s keep NAT connections alive
5. TrustedCatalog.tsx renders A2UI envelopes from allowed component list
```

### What is intentionally NOT in this codebase

| Component | Status | Reason |
|---|---|---|
| Production React/Next.js frontend | Not included | `TrustedCatalog.tsx` is a reference renderer for grading inspection |
| `ADK.to_a2a()` auto-wiring | Not used | Manual gateway gives full control over validation and dedup |
| A2A v1.0 protocol | Not supported | Hackathon harness expects v0.3.0 |
| `message/stream` | Stub only | Clients use `message/send` + `tasks/get` polling |
| Redis in CI | Not required | SQLite-first in test mode |

### Pre-hackathon checklist

Before live data intake on event day:

1. Set `AXIOM_MODE=development` (or `grading` for judge runs)
2. Start Redis (`redis://localhost:6379` or cloud instance)
3. Fill `.env`: `GEMINI_API_KEY`, `LINKUP_API_KEY`, optional `NGROK_URL` for Agent Card
4. Run `run.bat` or start four Uvicorn processes manually
5. Verify: `GET http://localhost:8080/health` → 200
6. Send a real `message/send` with a customer message containing an account ID (e.g. `ACC-12345`)
7. Poll `tasks/get` or connect `GET /sse/{session_id}` for live UI events

---

*End of AXIOM v6.2 Master Architecture Document.*
*Generated: 2026-06-13. Reflects hardened codebase with deterministic IDs, SQLite-first test mode, and full integration test coverage.*
