# A2A Hackathon Harness - Comprehensive Codebase Documentation

> **Purpose**: Complete documentation for AI systems without codebase access.

## Table of Contents

1. [System Overview](#system-overview)
2. [Architecture](#architecture)
3. [Project Structure](#project-structure)
4. [Core Files](#core-files)
5. [Environment API](#environment-api)
6. [Data Contents](#data-contents)
7. [Tests](#tests)
8. [Configuration](#configuration)
9. [API Reference](#api-reference)

---

## System Overview

**A2A Hackathon Harness** evaluates agent pairs (Personal + CS) in banking scenarios using the A2A Protocol on tau2-bench.

### Key Concepts

| Term | Definition |
|------|------------|
| **A2A** | Agent-to-Agent protocol |
| **Leg 1** | User Simulator ↔ Personal Agent |
| **Leg 2** | Personal Agent ↔ CS Agent (via gateway) |
| **contextId** | UUID tying all session components together |
| **Environment API** | HTTP API for banking tools |

### Scoring Model: 50/25/25
- 50%: Own pair (Personal × CS)
- 25%: Personal × Held-out CS
- 25%: Held-out Personal × CS

---

## Architecture

```
User Simulator → Bridge (A2A) → Personal Agent → Gateway → CS Agent
                                   ↓                ↓
                              [Tool Calls]   [Tool Calls]
                                   ↓                ↓
                              Environment API Server
                              (Session Manager + Banking DB)
```

**Data Flow**:
1. UUID generated as `contextId`
2. User sim generates message → Bridge converts to A2A → Personal agent
3. Personal agent calls tools via API (recorded with contextId)
4. Personal agent forwards to CS via gateway (recorded as Leg 2)
5. CS agent calls tools via API (recorded with contextId)
6. Session closed, trajectory merged, evaluated

---

## Project Structure

```
a2a-hackathon-main/
├── src/a2a_hack/                    # Main source code
│   ├── __init__.py                  # Package init, registers domain on import
│   ├── cli.py                       # CLI entry point (run, score, smoke commands)
│   ├── domain.py                    # Domain registration & task loading
│   ├── runner.py                    # Simulation orchestration & batch processing
│   ├── bridge.py                    # A2A bridge agent (tau2 ↔ A2A protocol)
│   ├── merge.py                     # Trajectory merging (conversation + tool calls)
│   ├── scoring.py                   # 50/25/25 scoring calculation
│   ├── env_api/                     # Environment API server
│   │   ├── __init__.py              # (empty)
│   │   ├── sessions.py              # Session management & recording
│   │   └── server.py                # FastAPI endpoints (tools + gateway)
│   └── data/                        # Task definitions
│       ├── banking_hackathon_splits.json   # Train/test/feedback splits
│       └── tasks/                   # 79 JSON task files (task_001.json, etc.)
├── tests/                           # Test suite
│   ├── conftest.py                  # Test fixtures (echo agents, servers)
│   ├── test_batch_and_scoring.py    # M3: Batch loop & scoring tests
│   ├── test_golden_replay.py        # M0: Env API & golden action tests
│   └── test_m1_contextid.py         # M1: ContextId propagation tests
├── pyproject.toml                   # Python package configuration
├── Dockerfile                       # Container build instructions
└── README.md                        # User-facing documentation
```

## File-by-File Documentation

### Core Module: `src/a2a_hack/__init__.py`

**Purpose**: Package initialization that auto-registers the `banking_hackathon` domain with tau2 on import.

**Low-Level Details**:
- Imports `register()` from `domain.py` and calls it immediately
- This ensures tau2 knows about the custom domain before any other code runs
- Idempotent: safe to import multiple times

---

### Core Module: `src/a2a_hack/cli.py`

**Purpose**: Command-line interface using [Typer](https://typer.tiangolo.com/). Three main commands: `run`, `score`, `smoke`.

**Commands**:

| Command | Purpose |
|---------|---------|
| `run` | Batch execution of tasks against agent pair with resume/checkpointing |
| `score` | Combine three pairing runs (50/25/25 weighting) into final score |
| `smoke` | Single-task test run with detailed output for debugging |

**Low-Level Details**:
- `DEFAULT_USER_LLM = "vertex_ai/gemini-3.5-flash"` - Simulated user LLM
- Uses `ENV_API_USER_TOKEN` and `ENV_API_AGENT_TOKEN` env vars for auth
- Supports `--auto-resume` to continue from checkpoints
- Non-zero exit code (2) on infrastructure errors for retry logic
- Vertex AI express endpoint routing when `GOOGLE_API_KEY` is set

---

### Core Module: `src/a2a_hack/domain.py`

**Purpose**: Domain registration and task management for the `banking_hackathon` domain.

**Key Functions**:

| Function | Purpose |
|----------|---------|
| `get_hack_db()` | Load transactional DB with `A2A_HACK_DB` override support |
| `get_hack_environment()` | Create environment with `no_knowledge` retrieval variant |
| `get_hack_task_splits()` | Load train/test/feedback splits from JSON |
| `get_hack_tasks()` | Load tasks with `A2A_HACK_TASKS_DIR` override support |
| `build_user_sim()` | Create user simulator with hackathon-specific addendum |
| `register()` | Register domain and tasks with tau2 registry |

**Low-Level Details**:
- `DOMAIN_NAME = "banking_hackathon"` - Unique domain identifier
- `USER_SIM_ADDENDUM` - Instructs simulated user they're talking to a personal assistant, not directly to the bank
- `A2A_HACK_DB` env var allows private marking repo to use perturbed data
- `A2A_HACK_TASKS_DIR` env var allows task override without code changes
- Uses tau2's `banking_knowledge` domain as base with custom overrides

---

### Core Module: `src/a2a_hack/runner.py`

**Purpose**: Simulation orchestration and batch processing with checkpoint/resume support.

**Key Functions**:

| Function | Purpose |
|----------|---------|
| `start_env_api()` | Start FastAPI server in background thread |
| `run_one()` | Execute single simulation with full lifecycle |
| `build_info()` | Create run metadata for checkpoint fingerprinting |
| `run_batch()` | Execute multiple tasks with concurrency, retries, resume |

**Low-Level Details**:
- **UUID as contextId**: `sid = uuid.uuid4().hex` ties everything together
- **Session lifecycle**: `manager.create_session()` → orchestrator runs → `manager.close()`
- **Concurrency**: ThreadPoolExecutor with `DEFAULT_CONCURRENCY = 2` (limited due to API quotas)
- **Timeouts**: `DEFAULT_TASK_TIMEOUT_S = 600.0` (whole task), per-turn timeout in bridge
- **Retry logic**: `run_with_retry()` from tau2 with `DEFAULT_OUTER_RETRIES = 2`
- **Merging**: `simulation.messages = merge_trajectory(...)` happens before evaluation
- **Storage**: tau2's directory format, browsable with `tau2 view`

**Constants**:
```python
DEFAULT_MAX_STEPS = 60          # Max conversation turns
DEFAULT_MAX_ERRORS = 10        # Max tool/infra errors before termination
DEFAULT_CONCURRENCY = 2        # Parallel simulations
DEFAULT_OUTER_RETRIES = 2      # Retries per simulation
DEFAULT_TASK_TIMEOUT_S = 600.0 # 10 minute wall-clock timeout
```

---

### Core Module: `src/a2a_hack/bridge.py`

**Purpose**: A2A protocol bridge between tau2's orchestrator and team's personal agent.

**Class**: `A2ABridgeAgent(HalfDuplexParticipant)`

**Role in System**:
- Acts as tau2's "agent" participant
- Forwards user messages to personal agent over A2A protocol
- Stateless: session keyed entirely by A2A `contextId`

**Low-Level Details**:
- `DEFAULT_TURN_TIMEOUT_S = 300.0` - Per-turn budget (one personal turn may include CS sub-loop)
- `EMPTY_REPLY_PLACEHOLDER = "[no response]"` - Silences empty A2A replies (orchestrator validation)
- Uses `a2a-sdk` client: `ClientFactory` + `minimal_agent_card()`
- Async `_send()` wrapped in `asyncio.run()` for sync bridge interface
- Never emits tool calls directly - all tools go through env API

**A2A Message Flow**:
```python
A2AMessage(
    message_id=uuid.uuid4().hex,
    role=Role.user,
    parts=[Part(root=TextPart(text=text))],
    context_id=self.context_id,  # The session key
)
```

---

### Core Module: `src/a2a_hack/merge.py`

**Purpose**: Merge orchestrator conversation with out-of-band tool call recordings into single trajectory.

**Function**: `merge_trajectory(conversation, records)`

**Algorithm**:
1. Build `[carrier_message, tool_message]` pairs for each recorded call
2. Interleave conversation messages and pairs by timestamp
3. Rewrite timestamps to be strictly monotonic
4. Renumber `turn_idx` sequentially

**Low-Level Details**:
- Carrier messages: `UserMessage` for user-scope calls, `AssistantMessage` for agent-scope
- `tool_call.requestor` preserved from recorded scope mapping
- Result is byte-identical replayable by tau2's evaluator
- Timestamps rewritten as: `base + timedelta(seconds=i)` for stability

---

### Core Module: `src/a2a_hack/scoring.py`

**Purpose**: Calculate final hackathon score from three pairing runs.

**Scoring Formula**:
```
final = 0.5 * a + 0.25 * b + 0.25 * c

where:
  a = team personal × team CS (own pair)
  b = team personal × held-out CS
  c = held-out personal × team CS
```

**Functions**:

| Function | Purpose |
|----------|---------|
| `load_pairing_rewards()` | Load per-task rewards, grid, and completed set |
| `combine_per_pairing()` | Weighted score over chosen task set |
| `score_pairings()` | Main entry: combines three dirs into final score |

**Low-Level Details**:
- `PAIRING_WEIGHTS = {"a": 0.5, "b": 0.25, "c": 0.25}`
- Missing/INFRASTRUCTURE_ERROR tasks count as reward 0
- `per_task` table allows cross-team marking over common completed sets
- Reports both mean over union grid and per-pairing completed sets

---

### Env API: `src/a2a_hack/env_api/sessions.py`

**Purpose**: Session management, tool execution, and recording for environment API.

**Classes**:

| Class | Purpose |
|-------|---------|
| `RecordedCall` | One executed tool call with result (Pydantic model) |
| `RecordedChat` | One personal↔CS gateway message (Pydantic model) |
| `Session` | Live state for one simulation (env + records + lock) |
| `SessionManager` | Factory and registry for sessions, token mapping |

**Error Classes** (with HTTP status codes):
- `UnknownSessionError` → 404
- `UnknownToolError` → 404
- `SessionClosedError` → 409

**Low-Level Details**:
- **Scope mapping**: `user` token → user tools, `agent` token → all agent tools
- **Threading**: Each session has `threading.Lock()` for concurrent safety
- **Sequencing**: `_seq` counter for deterministic ordering across mixed operations
- **Tool execution**: `env.get_response(tool_call)` records result atomically
- **Chat recording**: Best-effort, non-blocking but shares lock for global ordering

**Token-to-Scope**:
```python
def scope_for_token(self, token: str) -> Optional[Scope]:
    if token == self.user_token: return "user"
    if token == self.agent_token: return "agent"
    return None
```

---

### Env API: `src/a2a_hack/env_api/server.py`

**Purpose**: FastAPI application with two endpoint groups: tools API and CS gateway.

**Endpoints**:

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/sessions/{cid}/tools` | List tools for caller's scope |
| POST | `/sessions/{cid}/tools/{name}` | Execute tool, record it |
| GET | `/cs-agent/.well-known/...` | Proxy agent card (URL rewritten) |
| POST | `/cs-agent` | Gateway to real CS agent (records messages) |

**Low-Level Details**:
- **Auth**: Bearer token → scope via `SessionManager`
- **Streaming**: `message/stream` handled with byte passthrough + best-effort capture
- **Recording**: Extracts `contextId` from JSON-RPC params, records both directions
- **Text extraction**: Handles both `kind` and legacy `type` fields, Message and Task results
- **URL rewriting**: Gateway overwrites agent card URL so clients keep using gateway

**Gateway Flow**:
```
Personal Agent → POST /cs-agent (A2A JSON-RPC)
                    ↓
            _record_request_message()  # Record outgoing
                    ↓
            Forward to CS_URL (real CS agent)
                    ↓
            _record_reply()  # Record response
                    ↓
            Return to Personal Agent
```

---

### Test Suite

#### `tests/conftest.py`

**Purpose**: Shared test utilities and fixtures.

**Utilities**:
- `free_port()` - Get available TCP port
- `start_server(app, port)` - Start uvicorn in background thread
- `text_event()`, `incoming_text()` - ADK event helpers
- `SimpleEchoAgent` - Minimal ADK agent that echoes input + session id

---

#### `tests/test_golden_replay.py`

**Purpose**: M0 milestone - verify golden actions through HTTP API reproduce exact rewards.

**Tests**:
- `test_golden_replay_reward_one()` - Golden actions → reward 1.0
- `test_skipped_action_reward_zero()` - Missing actions → reward 0.0
- `test_tool_listing_by_scope()` - User vs agent tool visibility
- `test_auth_and_scope_errors()` - 401/404 on bad tokens/scopes
- `test_closed_session_409()` - 409 on closed session

**Mechanism**: Creates session, applies initial state, executes golden actions via API, merges with canned conversation, evaluates.

---

#### `tests/test_m1_contextid.py`

**Purpose**: M1 milestone - verify contextId propagates end-to-end and gateway records leg 2.

**Tests**:
- `test_contextid_end_to_end()` - Full flow: bridge → personal → gateway → CS

**Agents**:
- `CsEchoAgent` - Echoes ADK session id (should match A2A contextId)
- `PersonalEchoAgent` - Echoes session id and relays to CS via gateway

**Verifies**:
1. Both personal and CS see same contextId as their session id
2. Gateway recorded both directions in `chat_records`

---

#### `tests/test_batch_and_scoring.py`

**Purpose**: M3 milestone - batch checkpoint/resume and scoring math.

**Tests**:
- `test_batch_checkpoint_and_resume()` - Resume doesn't re-run completed tasks
- `test_score_pairings_math()` - 50/25/25 math with INFRA handling

**Fixtures**:
- `ScriptedUser` - Deterministic user for reproducible tests
- `personal_echo` - Module-scoped echo agent via ADK's `to_a2a()`

---

## Task Format

Tasks are stored in `src/a2a_hack/data/tasks/task_*.json`.

**Structure**:
```json
{
  "id": "task_001",
  "description": {
    "purpose": "...",
    "relevant_policies": "...",
    "notes": "..."
  },
  "user_scenario": {
    "persona": "...",
    "instructions": "..."
  },
  "initial_state": {
    "initialization_data": {...},
    "initialization_actions": [...],
    "message_history": null
  },
  "evaluation_criteria": {
    "actions": [
      {
        "name": "log_verification",
        "arguments": {...},
        "requestor": "assistant",
        "action_id": "001_0"
      }
    ],
    "reward_basis": ["DB"]
  },
  "user_tools": [],
  "required_documents": ["doc_..."]
}
```

**Task Splits** (79 total tasks):
- `train`: 63 tasks - Main training set
- `test`: 20 tasks - Held-out test set
- `feedback`: 3 tasks (task_006, task_009, task_053) - Quick smoke tests

## Dependencies

**Core** (from `pyproject.toml`):
- `tau2[knowledge]` - Banking knowledge domain + evaluator
- `a2a-sdk>=0.3.4` - A2A protocol implementation
- `fastapi>=0.115.11` - Env API server
- `uvicorn>=0.34.0` - ASGI server
- `httpx>=0.24.0` - HTTP client
- `typer>=0.12.5` - CLI framework
- `loguru>=0.7.3` - Logging
- `pydantic>=2.0.0` - Data validation

**Dev**:
- `a2a-sdk[http-server]` - A2A server support
- `google-adk[a2a]>=1.10` - Google ADK for tests
- `pytest>=8.3.5` - Testing

## Data Flow Summary

```
1. CLI parses args, resolves tasks
2. SessionManager created with bearer tokens
3. Env API server started (FastAPI in thread)
4. For each task:
   a. Create Session (UUID = contextId)
   b. Build UserSimulator + A2ABridgeAgent + Orchestrator
   c. Run simulation:
      - User sim generates message
      - Bridge sends to personal agent (A2A)
      - Personal agent may call tools (via HTTP API, recorded)
      - Personal agent may call CS (via gateway, recorded)
      - CS agent may call tools (via HTTP API, recorded)
   d. Merge trajectory (conversation + tool records)
   e. Evaluate with tau2 evaluator
   f. Save results
5. Batch complete: output mean reward, exit non-zero if INFRA errors
```

## Security Model

- **Bearer tokens**: Per-job static tokens (not rotated)
- **User scope**: Limited to `task.user_tools` (subset)
- **Agent scope**: All environment tools
- **Session isolation**: Sessions keyed by UUID, closed after simulation
- **No persistence**: Session data only in memory, written to results on completion

---

# Appendix: Comprehensive Data Reference

## Data Folder Complete Contents

### `src/a2a_hack/data/banking_hackathon_splits.json`

**Complete Task Distribution**:
```json
{
  "train": [
    "task_002", "task_003", "task_005", "task_006", "task_008", "task_009",
    "task_010", "task_011", "task_012", "task_013", "task_016", "task_018",
    "task_020", "task_022", "task_023", "task_024", "task_025", "task_027",
    "task_028", "task_029", "task_031", "task_032", "task_033", "task_034",
    "task_035", "task_036", "task_037", "task_038", "task_039", "task_041",
    "task_042", "task_044", "task_045", "task_046", "task_048", "task_050",
    "task_051", "task_052", "task_053", "task_054", "task_055", "task_056",
    "task_057", "task_058", "task_061", "task_062", "task_063", "task_064",
    "task_066", "task_067", "task_068", "task_069", "task_071", "task_072",
    "task_073", "task_074", "task_075", "task_076", "task_077", "task_078",
    "task_079"
  ],
  "test": [
    "task_001", "task_004", "task_007", "task_014", "task_015", "task_017",
    "task_019", "task_021", "task_026", "task_030", "task_040", "task_043",
    "task_047", "task_049", "task_059", "task_060", "task_065", "task_070"
  ],
  "feedback": [
    "task_006", "task_009", "task_053"
  ]
}
```

**Split Details**:
| Split | Count | Description |
|-------|-------|-------------|
| `train` | 63 | Primary training set |
| `test` | 20 | Held-out evaluation set |
| `feedback` | 3 | Quick smoke-test subset (also in train) |
| **Total** | **79** | All unique tasks |

### Task Files Complete Inventory (79 files)

| File | Size | Split | File | Size | Split | File | Size | Split |
|------|------|-------|------|------|-------|------|------|-------|
| task_001.json | 6,573 B | test | task_028.json | 17,934 B | train | task_055.json | 16,107 B | train |
| task_002.json | 4,843 B | train | task_029.json | 8,885 B | train | task_056.json | 7,129 B | train |
| task_003.json | 10,090 B | train | task_030.json | 17,523 B | test | task_057.json | 4,023 B | train |
| task_004.json | 7,946 B | test | task_031.json | 33,873 B | train | task_058.json | 33,770 B | train |
| task_005.json | 21,212 B | train | task_032.json | 3,751 B | train | task_059.json | 11,954 B | test |
| task_006.json | 2,539 B | train/feedback | task_033.json | 10,598 B | train | task_060.json | 5,840 B | test |
| task_007.json | 11,926 B | test | task_034.json | 12,442 B | train | task_061.json | 13,722 B | train |
| task_008.json | 10,870 B | train | task_035.json | 5,205 B | train | task_062.json | 5,030 B | train |
| task_009.json | 1,971 B | train/feedback | task_036.json | 16,428 B | train | task_063.json | 22,813 B | train |
| task_010.json | 12,853 B | train | task_037.json | 22,781 B | train | task_064.json | 3,105 B | train |
| task_011.json | 7,141 B | train | task_038.json | 13,423 B | train | task_065.json | 8,636 B | test |
| task_012.json | 8,081 B | train | task_039.json | 10,257 B | train | task_066.json | 4,199 B | train |
| task_013.json | 7,196 B | train | task_040.json | 10,095 B | test | task_067.json | 17,010 B | train |
| task_014.json | 8,499 B | test | task_041.json | 13,881 B | train | task_068.json | 6,636 B | train |
| task_015.json | 7,260 B | test | task_042.json | 3,410 B | train | task_069.json | 13,805 B | train |
| task_016.json | 22,559 B | train | task_043.json | 9,561 B | test | task_070.json | 10,957 B | test |
| task_017.json | 12,486 B | test | task_044.json | 3,349 B | train | task_071.json | 17,155 B | train |
| task_018.json | 6,562 B | train | task_045.json | 6,555 B | train | task_072.json | 26,010 B | train |
| task_019.json | 3,896 B | test | task_046.json | 4,988 B | train | task_073.json | 11,011 B | train |
| task_020.json | 35,275 B | train | task_047.json | 2,411 B | test | task_074.json | 3,207 B | train |
| task_021.json | 2,761 B | test | task_048.json | 10,297 B | train | task_075.json | 3,350 B | train |
| task_022.json | 9,154 B | train | task_049.json | 23,161 B | test | task_076.json | 11,839 B | train |
| task_023.json | 5,431 B | train | task_050.json | 9,288 B | train | task_077.json | 6,195 B | train |
| task_024.json | 2,829 B | train | task_051.json | 24,301 B | train | task_078.json | 22,982 B | train |
| task_025.json | 5,750 B | train | task_052.json | 5,561 B | train | task_079.json | 11,667 B | train |
| task_026.json | 5,166 B | test | task_053.json | 8,301 B | train/feedback | | | |
| task_027.json | 9,706 B | train | task_054.json | 8,874 B | train | **Total** | ~750 KB | |

**Largest Files**: task_020.json (35,275 B), task_031.json (33,873 B), task_058.json (33,770 B)

---

## Task JSON Schema - Complete Specification

### Root Object Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | `string` | ✅ | Unique task identifier (format: "task_NNN") |
| `description` | `object` | ✅ | Task metadata and scenario notes |
| `user_scenario` | `object` | ✅ | Instructions for user simulator LLM |
| `initial_state` | `object \| null` | ✅ | Database state to load before simulation |
| `evaluation_criteria` | `object` | ✅ | Success criteria and golden actions |
| `annotations` | `object \| null` | ✅ | Additional metadata (always null in current tasks) |
| `user_tools` | `string[]` | ✅ | Tools available to user-scope agents |
| `required_documents` | `string[]` | ✅ | Document IDs for RAG retrieval |

### `description` Object Fields

| Field | Type | Description |
|-------|------|-------------|
| `purpose` | `string` | High-level task description (often "Task: task_XXX") |
| `relevant_policies` | `string \| null` | Policy text extracted from documents |
| `notes` | `string \| null` | Detailed scenario notes, calculations, evaluator traps |

**Example** (task_001.json - ATM fee checking):
```json
{
  "purpose": "Task: task_075",
  "relevant_policies": null,
  "notes": "PERSONAL CHECKING ACCOUNT RECOMMENDATION WITH ATM FEE CALCULATION: User Marco Vitiello is planning a 3-month international trip... THE KEY INSIGHT: When using a foreign ATM that is not in Rho-Bank's network, BOTH the out-of-network ATM fee AND the foreign ATM withdrawal fee apply... GREEN FEE-FREE ACCOUNT: $0 out-of-network + $0 foreign = $0 TOTAL (OPTIMAL)..."
}
```

### `user_scenario` Object Fields

| Field | Type | Description |
|-------|------|-------------|
| `persona` | `string \| null` | Character description for user sim |
| `instructions` | `string` | Complete LLM prompt with behavior guidelines |

**Example** (task_006.json - Credit card application):
```json
{
  "persona": null,
  "instructions": "You are playing the role of a customer contacting a customer service representative agent. Your character is a management consultant named Sarah Bosch who earns $100,000 annually. You travel frequently for work, but your company provides a corporate travel card that covers all your work-related travel expenses...\n\nYou're looking for a credit card to use for your everyday purchases. You want the card that gives you the highest cash back available in the company profile...\n\nAfter you receive enough information to make a decision, immediately apply for a credit card on your own, and there is no need to respond to the agent..."
}
```

**Common Instructions Patterns**:
- **Character**: Name, age, occupation, location, income
- **Situation**: Current problem or goal
- **Verification Info**: Name, phone, email, DOB, address
- **Behavior Guidelines**: How to respond to agent questions
- **Tool Access**: What tools user can invoke
- **Conversation Flow**: Step-by-step interaction guide
- **Closing**: When/how to end conversation (often includes `###STOP###` marker)

### `initial_state` Object Fields

| Field | Type | Description |
|-------|------|-------------|
| `initialization_data` | `object \| null` | Complete database state under `agent_data` key |
| `initialization_actions` | `array \| null` | Actions to execute after data load |
| `message_history` | `array \| null` | Pre-existing conversation messages |

**`initialization_data.agent_data` Structure**:

```json
{
  "agent_data": {
    "users": {
      "data": {
        "{user_id}": {
          "name": "string",
          "user_id": "string",
          "address": "string",
          "email": "string",
          "phone_number": "string",
          "date_of_birth": "MM/DD/YYYY"
        }
      }
    },
    "accounts": {
      "data": {
        "{account_id}": {
          "account_id": "string",
          "user_id": "string",
          "class": "checking | savings | credit",
          "level": "string (account type name)",
          "date_opened": "MM/DD/YYYY",
          "status": "OPEN | CLOSED | FROZEN",
          "current_holdings": "string (decimal amount)"
        }
      }
    },
    "debit_cards": {
      "data": {
        "{card_id}": {
          "card_id": "string",
          "account_id": "string",
          "user_id": "string",
          "cardholder_name": "string (UPPERCASE)",
          "last_4_digits": "string (4 digits)",
          "cvv": "string (3 digits)",
          "status": "ACTIVE | INACTIVE | BLOCKED | EXPIRED",
          "issue_date": "MM/DD/YYYY",
          "expiration_date": "MM/DD/YYYY",
          "issue_reason": "new_account | replacement | theft | fraud"
        }
      }
    },
    "credit_cards": { "data": { ... } },
    "payments": { "data": { ... } },
    "referrals": { "data": { ... } },
    "applications": { "data": { ... } },
    "user_profiles": { "data": { ... } },
    "fraud_disputes": { "data": { ... } }
  }
}
```

**Example** (task_020.json - Fraud dispute with data):
```json
{
  "initialization_data": {
    "agent_data": {
      "users": {
        "data": {
          "tm92c4d7e8": {
            "name": "Taylor Morrison",
            "user_id": "tm92c4d7e8",
            "address": "7845 Maple Street, Denver, CO 80202",
            "email": "taylor.morrison@outlook.com",
            "phone_number": "720-555-0348",
            "date_of_birth": "08/15/1990"
          }
        }
      },
      "accounts": {
        "data": {
          "chk_tm92c4d7e8_blue": {
            "account_id": "chk_tm92c4d7e8_blue",
            "user_id": "tm92c4d7e8",
            "class": "checking",
            "level": "Blue Account",
            "date_opened": "03/15/2023",
            "status": "OPEN",
            "current_holdings": "8500.00"
          }
        }
      },
      "debit_cards": {
        "data": {
          "dbc_tm92c4d7e8_blue": {
            "card_id": "dbc_tm92c4d7e8_blue",
            "account_id": "chk_tm92c4d7e8_blue",
            "user_id": "tm92c4d7e8",
            "cardholder_name": "TAYLOR MORRISON",
            "last_4_digits": "4927",
            "cvv": "583",
            "status": "ACTIVE",
            "issue_date": "03/20/2023",
            "expiration_date": "03/31/2027",
            "issue_reason": "new_account"
          }
        }
      }
    }
  },
  "initialization_actions": null,
  "message_history": null
}
```

### `evaluation_criteria` Object Fields

| Field | Type | Description |
|-------|------|-------------|
| `actions` | `Action[]` | Golden actions required for full reward |
| `communicate_info` | `array` | Information items to communicate (usually empty) |
| `reward_basis` | `string[]` | Reward calculation method (see below) |
| `nl_assertions` | `array \| null` | Natural language assertions to check |

**`Action` Object Fields**:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | `string` | ✅ | Tool name to invoke |
| `arguments` | `object` | ✅ | Tool parameters (exact match required) |
| `requestor` | `"user" \| "assistant"` | ✅ | Who should invoke the tool |
| `action_id` | `string` | ✅ | Unique ID format: `{taskId}_{sequence}` |
| `compare_args` | `string[]` | Optional | For partial matching (ACTION reward basis) |

**Example Actions** (task_001.json):
```json
{
  "actions": [
    {
      "name": "log_verification",
      "arguments": {
        "name": "Marco Vitiello",
        "user_id": "mv93f8a7b2",
        "address": "2847 South Lamar Boulevard, Austin, TX 78704",
        "email": "marco.vitiello@gmail.com",
        "phone_number": "512-555-0847",
        "date_of_birth": "08/22/1993",
        "time_verified": "2025-11-14 03:40:00 EST"
      },
      "requestor": "assistant",
      "action_id": "075_0"
    },
    {
      "name": "unlock_discoverable_agent_tool",
      "arguments": {
        "agent_tool_name": "open_bank_account_4821"
      },
      "requestor": "assistant",
      "action_id": "075_1"
    },
    {
      "name": "call_discoverable_agent_tool",
      "arguments": {
        "agent_tool_name": "open_bank_account_4821",
        "arguments": "{\"user_id\": \"mv93f8a7b2\", \"account_type\": \"checking\", \"account_class\": \"Green Fee-Free Account\"}"
      },
      "requestor": "assistant",
      "action_id": "075_2"
    }
  ],
  "reward_basis": ["DB"]
}
```

**Example with `compare_args`** (task_009.json):
```json
{
  "actions": [
    {
      "name": "transfer_to_human_agents",
      "arguments": {
        "reason": "account_ownership_dispute",
        "summary": ""
      },
      "compare_args": ["reason"],
      "requestor": "assistant",
      "action_id": "004_0"
    }
  ],
  "reward_basis": ["ACTION"]
}
```

**Reward Basis Values**:
| Value | Description |
|-------|-------------|
| `"DB"` | Full reward only if database state matches expected after all golden actions |
| `"ACTION"` | Partial reward based on action execution; uses `compare_args` for partial matching |

### `user_tools` Array

Tools available to user-scope agents (bearer token = user_token). Empty array means user cannot directly invoke tools.

**Examples from tasks**:
| Task | `user_tools` | Purpose |
|------|--------------|---------|
| task_006.json | `["apply_for_credit_card"]` | User can apply for credit cards |
| task_009.json | `["apply_for_credit_card"]` | (Note: mismatch with task purpose) |
| task_020.json | `["request_human_agent_transfer"]` | User can request human transfer |
| task_001.json | `[]` | User has no tools; must ask agent |
| Most tasks | `[]` | Default - user asks agent to perform actions |

### `required_documents` Array

Document IDs for RAG retrieval. Pattern: `doc_{category}_{document_name}_{number}`

**Common Document Categories**:
| Pattern | Description |
|---------|-------------|
| `doc_bank_accounts_*` | General banking account info |
| `doc_checking_accounts_*` | Checking account types (Green Fee-Free, Purple, Blue, etc.) |
| `doc_credit_cards_*` | Credit card products (Gold Rewards, Silver, Platinum, etc.) |
| `doc_debit_cards_*` | Debit card policies and procedures |
| `doc_fraud_protection_*` | Fraud protection and dispute policies |
| `doc_referral_program_*` | Customer referral bonus policies |
| `doc_human_agent_transfer_*` | Transfer policies and rules |

**Example** (task_001.json - Checking account comparison):
```json
[
  "doc_bank_accounts_bank_accounts_(general)_001",
  "doc_checking_accounts_green_fee-free_account_001",
  "doc_checking_accounts_green_fee-free_account_003",
  "doc_checking_accounts_green_fee-free_account_005",
  "doc_checking_accounts_purple_account_001",
  "doc_checking_accounts_purple_account_004",
  "doc_checking_accounts_purple_account_012",
  "doc_checking_accounts_bluest_account_001",
  "doc_checking_accounts_bluest_account_003",
  "doc_checking_accounts_bluest_account_007",
  "doc_checking_accounts_bluest_account_010",
  "doc_checking_accounts_light_blue_account_001",
  "doc_checking_accounts_light_blue_account_004",
  "doc_checking_accounts_light_blue_account_006",
  "doc_checking_accounts_evergreen_account_001",
  "doc_checking_accounts_evergreen_account_008",
  "doc_checking_accounts_gold_years_account_001",
  "doc_checking_accounts_light_green_account_001",
  "doc_checking_accounts_light_green_account_013",
  "doc_checking_accounts_dark_green_account_001",
  "doc_checking_accounts_dark_green_account_002",
  "doc_checking_accounts_blue_account_001",
  "doc_checking_accounts_blue_account_012",
  "doc_checking_accounts_green_account_(checking)_001",
  "doc_checking_accounts_green_account_(checking)_012"
]
```

---

## Complete Task Examples

### Example 1: task_006.json (Credit Card Application - 2,539 B)

```json
{
  "id": "task_006",
  "description": {
    "purpose": "Task: task_001",
    "relevant_policies": null,
    "notes": null
  },
  "user_scenario": {
    "persona": null,
    "instructions": "You are playing the role of a customer contacting a customer service representative agent. Your character is a management consultant named Sarah Bosch who earns $100,000 annually. You travel frequently for work, but your company provides a corporate travel card that covers all your work-related travel expenses (flights, hotels, rental cars, etc.). \n\nYou're looking for a credit card to use for your everyday purchases. You want the card that gives you the highest cash back available in the company profile. You will not accept a credit card that has any annual fees unless it is the ONLY option available. \n\nIf you find out that there are no credit cards that fit your needs, you are happy to immediately take your business elsewhere and end the conversation. \n\nYou have access to a tool that allow you to apply for credit cards by specifying the card type. You're seeking advice on which personal credit card would be the best fit for your situation and spending patterns. \n\nYou receive a Rho-Bank+ subscription for free through your company. ONLY MENTION THIS if you are asked about this. \n\nAfter you receive enough information to make a decision, immediately apply for a credit card on your own, and there is no need to respond to the agent, or ask for instructions on how to apply. \n\nYou are currently on the line with a customer support agent. Only provide additional details about your situation when the agent asks for them. Don't dump all your information at once. Never respond as a customer service representative/assistant. You are playing the role of the customer."
  },
  "initial_state": null,
  "evaluation_criteria": {
    "actions": [
      {
        "name": "apply_for_credit_card",
        "arguments": {
          "card_type": "Gold Rewards Card",
          "customer_name": "Sarah Bosch",
          "annual_income": 100000,
          "rho_bank_subscription": true
        },
        "requestor": "user",
        "action_id": "001_0"
      }
    ],
    "communicate_info": [],
    "reward_basis": ["DB"]
  },
  "annotations": null,
  "user_tools": ["apply_for_credit_card"],
  "required_documents": [
    "doc_credit_cards_gold_rewards_card_001",
    "doc_credit_cards_silver_rewards_card_001",
    "doc_credit_cards_bronze_rewards_card_001",
    "doc_credit_cards_platinum_rewards_card_001"
  ]
}
```

### Example 2: task_009.json (Email Change with Transfer - 1,971 B)

```json
{
  "id": "task_009",
  "description": {
    "purpose": "Task: task_004",
    "relevant_policies": null,
    "notes": null
  },
  "user_scenario": {
    "persona": null,
    "instructions": "You are playing the role of a customer contacting a customer service representative agent. Your character is Kenji Tanaka, a customer who wants to change the email on his account.\n\nYour email is kenji.tanaka@gmail.com. You are absolutely certain of this.\nYour phone number is 206-555-0293.\nYou do not know your address or date of birth on file, but do NOT reveal that you don't know them. Just deflect or say you don't have that information on hand right now.\n\nHere are your behavior guidelines:\n\n- Start by saying you want to change the email on your account because you recently changed it.\n- When asked for verification information, provide your name (Kenji Tanaka), your email (kenji.tanaka@gmail.com), and your phone number (206-555-0293).\n- If the agent helps you change your email, thank them and end the conversation.\n- If the agent asks for your address or date of birth, deflect - you don't have that info handy right now.\n- If the situation remains unresolved after 5 exchanges, demand to be transferred to a human agent.\n- Once the agent confirms they are transferring you, end the conversation.\n\nYou are now on the line with a customer support agent."
  },
  "initial_state": null,
  "evaluation_criteria": {
    "actions": [
      {
        "name": "transfer_to_human_agents",
        "arguments": {
          "reason": "account_ownership_dispute",
          "summary": ""
        },
        "compare_args": ["reason"],
        "requestor": "assistant",
        "action_id": "004_0"
      }
    ],
    "communicate_info": [],
    "reward_basis": ["ACTION"]
  },
  "annotations": null,
  "user_tools": ["apply_for_credit_card"],
  "required_documents": [
    "doc_bank_accounts_bank_accounts_(general)_042"
  ]
}
```

### Example 3: task_001.json (ATM Fee Checking - 6,573 B)

Complex task with multiple golden actions and many required documents for account comparison.

```json
{
  "id": "task_001",
  "description": {
    "purpose": "Task: task_075",
    "relevant_policies": null,
    "notes": "PERSONAL CHECKING ACCOUNT RECOMMENDATION WITH ATM FEE CALCULATION: User Marco Vitiello is planning a 3-month international trip... THE KEY INSIGHT: When using a foreign ATM that is not in Rho-Bank's network, BOTH the out-of-network ATM fee AND the foreign ATM withdrawal fee apply..."
  },
  "user_scenario": {
    "persona": null,
    "instructions": "**Your character:** You are Marco Vitiello, a 31-year-old freelance photographer from Austin, TX...\n\n**Your situation:** You're planning a 3-month photography assignment across Southeast Asia...\n\n**Verification info:**\n- Name: Marco Vitiello | Phone: 512-555-0847 | Email: marco.vitiello@gmail.com\n- DOB: 08/22/1993 | Address: 2847 South Lamar Boulevard, Austin, TX 78704"
  },
  "initial_state": {
    "initialization_data": null,
    "initialization_actions": null,
    "message_history": null
  },
  "evaluation_criteria": {
    "actions": [
      {
        "name": "log_verification",
        "arguments": {
          "name": "Marco Vitiello",
          "user_id": "mv93f8a7b2",
          "address": "2847 South Lamar Boulevard, Austin, TX 78704",
          "email": "marco.vitiello@gmail.com",
          "phone_number": "512-555-0847",
          "date_of_birth": "08/22/1993",
          "time_verified": "2025-11-14 03:40:00 EST"
        },
        "requestor": "assistant",
        "action_id": "075_0"
      },
      {
        "name": "unlock_discoverable_agent_tool",
        "arguments": {
          "agent_tool_name": "open_bank_account_4821"
        },
        "requestor": "assistant",
        "action_id": "075_1"
      },
      {
        "name": "call_discoverable_agent_tool",
        "arguments": {
          "agent_tool_name": "open_bank_account_4821",
          "arguments": "{\"user_id\": \"mv93f8a7b2\", \"account_type\": \"checking\", \"account_class\": \"Green Fee-Free Account\"}"
        },
        "requestor": "assistant",
        "action_id": "075_2"
      }
    ],
    "reward_basis": ["DB"]
  },
  "annotations": null,
  "user_tools": [],
  "required_documents": [
    "doc_bank_accounts_bank_accounts_(general)_001",
    "doc_checking_accounts_green_fee-free_account_001",
    "doc_checking_accounts_green_fee-free_account_003",
    ...
  ]
}
```

---

## Test Suite Deep Dive

### Test Structure

| Test File | Lines | Purpose | Key Tests |
|-----------|-------|---------|-----------|
| `conftest.py` | 53 | Shared fixtures | `free_port()`, `start_server()`, `SimpleEchoAgent` |
| `test_golden_replay.py` | 210 | M0: Golden replay | 5 tests for env API, auth, replay |
| `test_m1_contextid.py` | 125 | M1: ContextId | End-to-end contextId propagation |
| `test_batch_and_scoring.py` | 155 | M3: Batch/scoring | Checkpoint/resume, scoring math |

### `conftest.py` Details

**`free_port()`**: 
```python
def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
```

**`start_server(app, port)`**: Starts uvicorn in daemon thread, polls 150×0.1s for `server.started`

**`SimpleEchoAgent(BaseAgent)`**:
- Async generator echoing `f"echo sid={ctx.session.id}: {incoming_text(ctx)}"`
- Used for testing A2A connectivity without LLM

### `test_golden_replay.py` - M0 Verification

**Fixture `task`**: Selects referral task by matching golden action names

**`test_golden_replay_reward_one`**:
1. Create session with `ctx-m0` contextId
2. Apply task initial state via `session.env.set_state()`
3. Execute all golden actions from `task.evaluation_criteria.actions`
4. Each action: POST `/sessions/{id}/tools/{name}` with correct bearer token
5. Assert all responses are HTTP 200 with `error: false`
6. Merge with canned conversation from `_canned_conversation()`
7. Call `evaluate_simulation()` with `EvaluationType.ALL`
8. Assert `reward_info.reward == 1.0`

**`test_skipped_action_reward_zero`**:
- Same setup but only executes first golden action
- Skips remaining actions
- Asserts `reward_info.reward == 0.0`

**`test_tool_listing_by_scope`**:
- User token → GET tools → assert only `task.user_tools` visible
- Agent token → GET tools → assert all agent tools visible

**`test_auth_and_scope_errors`**:
- Invalid token → 401
- User token calling agent-only tool → 404, not recorded
- Agent token calling user-only tool → 404, not recorded
- Unknown session → 404

**`test_closed_session_409`**:
- `manager.close(session.id)`
- POST to tools → 409 with `SessionClosedError`

### `test_m1_contextid.py` - M1 Verification

**Test Agents**:

**`CsEchoAgent`**:
```python
async def _run_async_impl(self, ctx):
    yield text_event(self, ctx, f"cs sid={ctx.session.id}")
```

**`PersonalEchoAgent`**:
- Echoes ADK session ID
- Calls CS via gateway URL with same `contextId`
- Relays: `f"personal sid={ctx.session.id} | {cs_reply}"`

**`test_contextid_end_to_end(stack)`**:
1. Setup: Env API + Personal Echo + CS Echo (3 servers on free ports)
2. Create session: `manager.create_session("m1-ctx-1", task)`
3. Bridge sends: `UserMessage(content="hello agents")`
4. Verify response contains `personal sid=m1-ctx-1`
5. Verify response contains `cs sid=m1-ctx-1`
6. Verify `session.chat_records` contains both directions
7. Verify personal record has `relay:hello agents`
8. Verify CS record has `cs sid=m1-ctx-1`

### `test_batch_and_scoring.py` - M3 Verification

**`ScriptedUser` Class**:
```python
class ScriptedUser:
    def __init__(self, script: list[str]):
        self.script = script
    def generate_next_message(self, message, state):
        text = self.script[min(state["i"], len(self.script) - 1)]
        state["i"] += 1
        return UserMessage(role="user", content=text), state
```

**`test_batch_checkpoint_and_resume`**:
1. Monkeypatch `build_user_sim` → returns `ScriptedUser(["hi", "ok bye ###STOP###"])`
2. Run 3 tasks → checkpoint saved
3. Run 5 tasks (same save_to, auto_resume=True)
4. Verify only 2 new simulations ran
5. Verify all 5 have `termination_reason == USER_STOP`
6. Verify `reward_info.reward == 0.0` (echo agents don't use tools)

**`test_score_pairings_math`**:
- Creates 3 pairing dirs with synthetic results
- a: task_001=1.0, task_002=0.5
- b: task_001=None (INFRA), task_002=1.0
- c: task_001=1.0 (task_002 missing)
- Expected: a=0.75, b=0.5, c=0.5, final=0.625

---

## Configuration Files

### `pyproject.toml`

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "a2a-hack"
version = "0.1.0"
description = "A2A hackathon harness on tau2-bench banking_knowledge"
requires-python = ">=3.12,<3.14"
dependencies = [
    "tau2[knowledge]",        # Banking domain
    "a2a-sdk>=0.3.4,<0.4",    # A2A protocol
    "fastapi>=0.115.11",      # API server
    "uvicorn>=0.34.0",        # ASGI server
    "httpx>=0.24.0",          # HTTP client
    "typer>=0.12.5",          # CLI framework
    "loguru>=0.7.3",          # Logging
    "pydantic>=2.0.0",        # Data validation
]

[project.scripts]
a2a-hack = "a2a_hack.cli:app"

[dependency-groups]
dev = [
    "a2a-sdk[http-server]>=0.3.4,<0.4",
    "google-adk[a2a]>=1.10",   # For tests
    "pytest>=8.3.5",
]

[tool.uv.sources]
tau2 = { path = "../tau2-bench", editable = true }

[tool.hatch.build.targets.wheel]
packages = ["src/a2a_hack"]
```

### `Dockerfile`

```dockerfile
FROM python:3.12-slim
RUN pip install --no-cache-dir uv

COPY --from=tau2 . /tau2-bench

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src

# Update path to use baked-in tau2
RUN sed -i 's#path = "../tau2-bench"#path = "/tau2-bench"#' pyproject.toml \
    && uv venv && uv pip install . /tau2-bench

ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8090
CMD ["a2a-hack", "--help"]
```

**Build Command**:
```bash
docker build --build-context tau2=../tau2-bench -t a2a-hackathon-harness .
```

---

## API Reference

### Environment API Endpoints

#### Authentication
All tool endpoints require Bearer token:
```
Authorization: Bearer <token>
```

Tokens map to scopes:
- `user_token` → "user" scope (limited to `task.user_tools`)
- `agent_token` → "agent" scope (all tools)

#### GET `/sessions/{contextId}/tools`

List available tools for the caller's scope.

**Request**:
```bash
curl -H "Authorization: Bearer user-token" \
  http://localhost:8090/sessions/abc123/tools
```

**Response** (200 OK):
```json
{
  "tools": [
    {
      "type": "function",
      "function": {
        "name": "get_account_balance",
        "description": "...",
        "parameters": {...}
      }
    }
  ]
}
```

**Errors**:
- 401: Invalid token
- 404: Unknown session

#### POST `/sessions/{contextId}/tools/{toolName}`

Execute a tool and record the call.

**Request**:
```bash
curl -X POST \
  -H "Authorization: Bearer agent-token" \
  -H "Content-Type: application/json" \
  -d '{"arguments": {"user_id": "u123"}}' \
  http://localhost:8090/sessions/abc123/tools/get_account_balance
```

**Response** (200 OK):
```json
{
  "content": "{\"balance\": 1000.00}",
  "error": false
}
```

**Response** (error):
```json
{
  "content": "Account not found",
  "error": true
}
```

**Errors**:
- 401: Invalid token
- 404: Unknown session or tool not in scope
- 409: Session closed

#### GET `/cs-agent/.well-known/agent-card.json`

Proxy CS agent card with URL rewritten to gateway.

**No authentication required.**

#### POST `/cs-agent`

Gateway to real CS agent. Records messages.

**No authentication required** (internal use only).

**Request**: A2A JSON-RPC message
```json
{
  "jsonrpc": "2.0",
  "id": "msg-1",
  "method": "message/send",
  "params": {
    "message": {
      "messageId": "m-1",
      "role": "user",
      "parts": [{"kind": "text", "text": "Hello"}],
      "contextId": "abc123"
    }
  }
}
```

**Response**: A2A JSON-RPC result

---

## Data Models (Pydantic)

### `RecordedCall`
```python
class RecordedCall(BaseModel):
    seq: int                    # Sequence within session
    timestamp: str              # ISO format
    scope: Scope                # "user" | "agent"
    tool_call: ToolCall         # {id, name, arguments, requestor}
    tool_message: ToolMessage    # {content, error, timestamp}
```

### `RecordedChat`
```python
class RecordedChat(BaseModel):
    seq: int
    timestamp: str
    role: Literal["personal", "cs"]
    content: str
    raw: Optional[dict]         # Original A2A message
```

### `Session`
```python
class Session(BaseModel):
    id: str                     # contextId
    task: Task
    env: Environment            # tau2 Environment instance
    records: list[RecordedCall]
    chat_records: list[RecordedChat]
    closed: bool
```

---

## Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `A2A_HACK_DB` | tau2 default | Override transactional DB path |
| `A2A_HACK_TASKS_DIR` | `src/a2a_hack/data/tasks` | Override task directory |
| `ENV_API_USER_TOKEN` | `dev-user-token` | User scope bearer token |
| `ENV_API_AGENT_TOKEN` | `dev-agent-token` | Agent scope bearer token |
| `GOOGLE_API_KEY` | None | Route user LLM through Vertex AI express |

---

## Command Examples

### Smoke Test
```bash
uv run a2a-hack smoke \
  --personal-url http://localhost:9001 \
  --cs-url http://localhost:9002 \
  --task-id task_006
```

### Batch Run
```bash
uv run a2a-hack run \
  --personal-url http://localhost:9001 \
  --cs-url http://localhost:9002 \
  --tasks train \
  --save-to results/dev \
  --auto-resume \
  --concurrency 2
```

### Scoring
```bash
uv run a2a-hack score \
  --a results/own-pair \
  --b results/personal-x-heldout \
  --c results/heldout-x-cs \
  --out scores.json
```

### View Results
```bash
uv run tau2 view results/dev
```
