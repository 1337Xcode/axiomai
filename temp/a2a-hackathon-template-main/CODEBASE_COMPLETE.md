# Part 1: System Overview & Architecture

> **For AI Assistants**: This is part 1 of a 5-part comprehensive codebase documentation. Read all parts to understand the complete system.

## Table of Contents for Part 1
1. [What This System Does](#what-this-system-does)
2. [Complete File Inventory](#complete-file-inventory)
3. [System Architecture](#system-architecture)
4. [The contextId - Session Identity](#the-contextid---session-identity)
5. [Technology Stack](#technology-stack)

---

## What This System Does

This is a **two-agent banking simulation** for the A2A (Agent-to-Agent) Hackathon. It simulates **Rho-Bank** customer service scenarios where:

1. **A simulated user** (controlled by hackathon harness) wants to perform banking tasks
2. **personal-agent** (port 9001) acts as the user's assistant - performs user-side actions
3. **cs-agent** (port 9002) acts as bank customer service - performs bank-side actions
4. The agents **communicate via A2A protocol** to complete multi-sided tasks

### Example Scenarios
| Scenario | User Side | Bank Side |
|----------|-----------|-----------|
| Check balance | User asks | CS agent looks up (requires verification) |
| Submit referral | User calls `submit_referral()` | CS agent records referral |
| Open account | User provides info | CS agent verifies and opens |
| Dispute transaction | User initiates | CS agent investigates |

---

## Complete File Inventory

### Root Directory (5 files)
| File | Size | Purpose |
|------|------|---------|
| `.env.example` | 611 bytes | Environment variable template |
| `.gitignore` | 118 bytes | Excludes `.env`, `__pycache__/`, `kb/embeddings.json` |
| `README.md` | 9,097 bytes | Official hackathon documentation |
| `docker-compose.yml` | 1,161 bytes | Service orchestration (3 services) |
| `CODEBASE_EXPLANATION.md` | 16,026 bytes | Previous documentation |

### Personal Agent (`personal_agent/` - 6 files)
| File | Size | Purpose |
|------|------|---------|
| `Dockerfile` | 230 bytes | Python 3.12 slim container build |
| `agent.py` | 1,660 bytes | LlmAgent definition with system prompt |
| `cs_client_tool.py` | 2,354 bytes | A2A client to talk to CS agent |
| `env_toolset.py` | 3,515 bytes | Dynamic tool discovery from Environment API |
| `main.py` | 293 bytes | ASGI entry point using `to_a2a()` |
| `requirements.txt` | 81 bytes | 4 dependencies (ADK, A2A SDK, httpx, uvicorn) |

### Customer Service Agent (`cs_agent/` - 8 files)
| File | Size | Purpose |
|------|------|---------|
| `Dockerfile` | 233 bytes | Python 3.12 slim, copies kb/ folder |
| `agent.py` | 1,123 bytes | LlmAgent with policy.md + RAG guidance |
| `env_toolset.py` | 3,515 bytes | Dynamic tool discovery (bank-side tools) |
| `ingest.py` | 4,014 bytes | KB indexing at startup (readiness gate) |
| `main.py` | 490 bytes | Entry point with `build_index()` before serving |
| `precompute_embeddings.py` | 1,653 bytes | Generates embedding cache |
| `rag_tools.py` | 4,497 bytes | Redis search tools (BM25 + vector) |
| `requirements.txt` | 110 bytes | 6 dependencies (+redis, +google-genai) |

### Knowledge Base (`kb/` - 699 items)
| Path | Count | Type | Details |
|------|-------|------|---------|
| `kb/policy.md` | 1 | Markdown | 62 lines, master CS agent policy |
| `kb/documents/` | 698 | JSON | Banking procedure documents |
| `kb/embeddings.json` | 0 (gitignored) | JSON | Generated embedding cache |

**Document Filename Pattern:** `doc_{CATEGORY}_{SUBCATEGORY}_{NNN}.json`

Examples:
- `doc_bank_accounts_bank_accounts_(general)_001.json`
- `doc_business_checking_accounts_beige_001.json`
- `doc_credit_cards_credit_card_account_logistics_001.json`

---

## System Architecture

### Component Diagram

```
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                              EXTERNAL HACKATHON HARNESS                                  │
│                                                                                          │
│  • Simulates users with LLM personas                                                    │
│  • Provides tasks (train/test/feedback splits)                                          │
│  • Hosts Environment API at http://localhost:8090                                         │
│  • Tracks sessions via contextId                                                        │
│  • Validates agent responses                                                            │
│                                                                                          │
│  API:                                                                                   │
│  • GET  /sessions/{ctxId}/tools        → List OpenAI-style tool schemas               │
│  • POST /sessions/{ctxId}/tools/{name}   → Execute tool, return result                   │
└─────────────────────────────────────────────────────────────────────────────────────────┘
                                            │
                    ┌───────────────────────┴───────────────────────┐
                    │                                               │
                    ▼                                               ▼
┌──────────────────────────────────┐                  ┌──────────────────────────────────┐
│      PERSONAL-AGENT (Port 9001)  │                  │       CS-AGENT (Port 9002)     │
│                                    │    A2A Protocol  │                                  │
│  ┌────────────────────────────┐   │◄────────────────►│  ┌────────────────────────────┐   │
│  │ User's Banking Assistant   │   │   JSON-RPC      │  │ Bank Customer Service      │   │
│  ├────────────────────────────┤   │                 │  ├────────────────────────────┤   │
│  │ • User-side tools via API  │   │                 │  │ • Bank-side tools via API  │   │
│  │ • Contact CS when needed   │   │◄───────────────►│  │ • RAG KB search (Redis)    │   │
│  │ • Relay verification       │   │                 │  │ • Answer policy questions  │   │
│  │ • Perform user actions     │   │                 │  │ • Verify customers         │   │
│  └────────────────────────────┘   │                 │  └────────────────────────────┘   │
│                                    │                 │                                  │
│  Model: gemini-3.5-flash          │                 │  Model: gemini-3.5-flash          │
│  Tools:                            │                 │  Tools:                          │
│    - EnvApiToolset()              │                 │    - EnvApiToolset()             │
│    - ask_customer_service()       │                 │    - kb_search_bm25()            │
│                                    │                 │    - kb_search_vector()          │
└──────────────────────────────────┘                 └──────────────────────────────────┘
         │                                                       │
         │ Environment API (User Token)                            │ Environment API (Bank Token)
         │                                                       │
         └───────────────────────────┬─────────────────────────────┘
                                     │
                         ┌───────────┴───────────┐
                         ▼                       ▼
              ┌─────────────────┐    ┌─────────────────┐
              │     REDIS       │    │   (Port 6379)   │
              ├─────────────────┤    ├─────────────────┤
              │ • RediSearch    │    │ • FT.SEARCH     │
              │ • HNSW Vector   │    │ • BM25 Text     │
              │ • 698 KB docs   │    │ • doc:* keys    │
              │ • Index: kb_idx │    │ • COSINE sim    │
              └─────────────────┘    └─────────────────┘
```

### Services Overview

| Service | Port | Image/Build | Key Features |
|---------|------|-------------|--------------|
| personal-agent | 9001 | `personal_agent/Dockerfile` | User-side tools, contacts CS via A2A |
| cs-agent | 9002 | `cs_agent/Dockerfile` | Bank-side tools, Redis RAG, KB search |
| redis | 6379 | `redis:8` | RediSearch, HNSW vector index |

---

## The contextId - Session Identity

**CRITICAL CONCEPT**: The `contextId` is the single source of truth for session identity across ALL components.

### How contextId Flows

```
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                                    CONTEXTID FLOW                                        │
└─────────────────────────────────────────────────────────────────────────────────────────┘

Step 1: Harness Creates Session
────────────────────────────────
Harness → contextId = "ctx-abc-123"
        → Associates user persona
        → Prepares tool state for this session

Step 2: User → Personal-Agent
─────────────────────────────
A2A Request:
{
  "jsonrpc": "2.0",
  "method": "message/send",
  "params": {
    "message": {
      "message_id": "msg-001",
      "role": "user",
      "parts": [{"text": "Check my balance"}],
      "context_id": "ctx-abc-123"  ←─── THIS FIELD
    }
  }
}

Step 3: Personal-Agent Processing
──────────────────────────────────
1. ADK extracts context_id="ctx-abc-123"
2. Creates session with session.id="ctx-abc-123"
3. Tool calls use this ID:
   • GET /sessions/ctx-abc-123/tools
   • POST /sessions/ctx-abc-123/tools/{name}
4. When contacting CS:
   • Sends A2A message with SAME context_id="ctx-abc-123"

Step 4: CS-Agent Processing
───────────────────────────
1. Receives A2A with context_id="ctx-abc-123"
2. Uses same ID for bank tool calls:
   • GET /sessions/ctx-abc-123/tools
   • POST /sessions/ctx-abc-123/tools/{name}

Result: Both agents share session state via contextId!
```

### contextId Usage by Component

| Component | contextId Source | Usage |
|-----------|----------------|-------|
| Harness | Generated | Tracks session, routes tool calls |
| Personal-Agent | A2A message `context_id` field | `session_id(context)`, env API calls, CS A2A messages |
| CS-Agent | A2A message `context_id` field | `session_id(context)`, env API calls |
| Environment API | URL path `/sessions/{contextId}/...` | Session isolation, tool availability |

---

## Technology Stack

| Layer | Technology | Version | Purpose |
|-------|------------|---------|---------|
| **Language** | Python | 3.12 | Implementation language |
| **Agent Framework** | Google ADK | >=1.10 | Agent logic, tool integration |
| **Protocol** | A2A (Agent-to-Agent) | 0.3.4 | Inter-agent communication |
| **LLM** | Gemini | 3.5-flash | Language model (required) |
| **Embeddings** | Gemini | embedding-001 | Vector embeddings (768-dim) |
| **Vector DB** | Redis | 8.x | Full-text + vector search |
| **Search** | RediSearch | built-in | FT.SEARCH, HNSW index |
| **HTTP Client** | httpx | >=0.27 | Async API calls |
| **Server** | Uvicorn | >=0.34 | ASGI HTTP server |
| **Container** | Docker | - | Deployment |
| **Orchestration** | Docker Compose | - | Multi-service management |
| **Hosting** | Vertex AI | - | Model inference (via API key) |

### Python Dependencies (personal_agent)
```
google-adk[a2a]>=1.10          # ADK with A2A support
a2a-sdk[http-server]>=0.3.4,<0.4  # A2A protocol
httpx>=0.27                    # HTTP client
uvicorn>=0.34                  # ASGI server
```

### Python Dependencies (cs_agent)
```
google-adk[a2a]>=1.10          # ADK with A2A support
a2a-sdk[http-server]>=0.3.4,<0.4  # A2A protocol
httpx>=0.27                    # HTTP client
uvicorn>=0.34                  # ASGI server
redis>=5.0                     # Redis client
google-genai>=1.0              # Gemini client
```

---

## Next Parts

- **Part 2**: Personal Agent Deep Dive (`personal_agent/` files)
- **Part 3**: Customer Service Agent Deep Dive (`cs_agent/` files)
- **Part 4**: Knowledge Base Complete Analysis (`kb/` documents)
- **Part 5**: Environment API & A2A Protocol Specifications
# Part 2: Personal Agent Deep Dive

> **For AI Assistants**: This is part 2 of 5. See DOCS_PART1_OVERVIEW.md for system context.

## Table of Contents for Part 2
1. [Directory Structure](#directory-structure)
2. [main.py - ASGI Entry Point](#mainpy---asgi-entry-point)
3. [agent.py - Agent Definition](#agentpy---agent-definition)
4. [cs_client_tool.py - A2A Communication](#cs_client_toolpy---a2a-communication)
5. [env_toolset.py - Tool Discovery](#env_toolsetpy---tool-discovery)
6. [Dockerfile & Requirements](#dockerfile--requirements)

---

## Directory Structure

```
personal_agent/
├── Dockerfile              # Container build instructions
├── agent.py               # LlmAgent definition + system prompt (1,660 bytes)
├── cs_client_tool.py      # A2A client for CS communication (2,354 bytes)
├── env_toolset.py         # Dynamic tool discovery (3,515 bytes)
├── main.py                # ASGI entry point (293 bytes)
└── requirements.txt       # Python dependencies (81 bytes)
```

---

## main.py - ASGI Entry Point

### Full Source Code
```python
"""Serve the personal agent over A2A. Run: uvicorn main:app --host 0.0.0.0 --port 9001"""

import os

from google.adk.a2a.utils.agent_to_a2a import to_a2a

from agent import root_agent

app = to_a2a(root_agent, host=os.environ.get("HOST", "0.0.0.0"), port=int(os.environ.get("PORT", "9001"))
```

### Line-by-Line Analysis

| Line | Content | Purpose |
|------|---------|---------|
| 1 | Docstring with run command | Developer documentation |
| 3 | `import os` | Environment variable access |
| 5 | `from google.adk.a2a.utils.agent_to_a2a import to_a2a` | ADK's A2A wrapper |
| 7 | `from agent import root_agent` | Import agent definition |
| 9 | `app = to_a2a(...)` | Create ASGI application |

### to_a2a() Function Details

**Signature:** `to_a2a(agent, host="0.0.0.0", port=9001)`

**What it does:**
1. **Wraps ADK agent** with A2A protocol handlers
2. **Creates HTTP routes:**
   - `GET /` → Returns Agent Card (JSON metadata)
   - `POST /message/send` → Handles incoming A2A messages
3. **Manages sessions:** Maps A2A `context_id` to ADK session.id
4. **Handles responses:** Converts ADK outputs to A2A Task/Message format
5. **Supports streaming:** Non-streaming mode used in this template

**Agent Card Response (GET /):**
```json
{
  "name": "personal_agent",
  "description": "User's personal banking assistant",
  "url": "http://localhost:9001",
  "version": "1.0.0",
  "capabilities": {
    "streaming": false,
    "pushNotifications": false
  },
  "authentication": null
}
```

---

## agent.py - Agent Definition

### Full Source Code
```python
"""The user's personal banking assistant."""

import os

from google.adk.agents import LlmAgent

from cs_client_tool import ask_customer_service
from env_toolset import EnvApiToolset

MODEL = os.environ.get("MODEL", "gemini-3.5-flash")

INSTRUCTION = """\
You are the user's personal banking assistant for their Rho-Bank accounts.

- You act on the user's behalf. Your environment tools are the user's own
  banking actions (e.g. applying for cards, submitting referrals); use them
  when the user asks you to do something you have a tool for.
- For anything you cannot do with your own tools — account lookups, policy
  questions, disputes, bank-side operations — contact the bank's customer
  service with ask_customer_service. Relay the user's request and any details
  faithfully, and report the answer back to the user.
- Customer service will usually need to verify the user's identity. Ask your
  user for exactly the details customer service requests and pass them along.
- If customer service tells you that the *user* should perform an action and
  a matching tool appears in your tool list (or it names a tool you can reach
  via call_env_tool), perform it for the user after confirming with them.
- Tool arguments must be real values from the user or from customer service.
  Never fill in placeholders (e.g. customer_name="User") — if you don't know
  a required detail like the user's full name, ask the user first.
- Be concise, accurate, and never invent account details or policies.
"""

root_agent = LlmAgent(
    name="personal_agent",
    model=MODEL,
    instruction=INSTRUCTION,
    tools=[EnvApiToolset(), ask_customer_service],
)
```

### Imports Analysis (Lines 1-8)

| Import | Source | Purpose |
|--------|--------|---------|
| `os` | Standard library | Environment variables |
| `LlmAgent` | `google.adk.agents` | ADK agent class |
| `ask_customer_service` | `cs_client_tool` | Tool function for CS communication |
| `EnvApiToolset` | `env_toolset` | Dynamic toolset class |

### Model Configuration (Line 10)
```python
MODEL = os.environ.get("MODEL", "gemini-3.5-flash")
```
- Environment variable: `MODEL`
- Default: `gemini-3.5-flash`
- **Hackathon requirement**: Must be exactly `gemini-3.5-flash` for submissions

### System Instruction (Lines 12-31)

**Instruction Rules Table:**

| Rule # | Rule | Example Scenario |
|--------|------|------------------|
| 1 | Use user tools for user-side actions | "Apply for credit card" → Call `apply_for_card` tool |
| 2 | Contact CS for bank-side operations | "What's my balance?" → `ask_customer_service()` |
| 3 | Relay verification requests | CS asks for DOB → Ask user → Pass to CS |
| 4 | Execute instructed actions | CS says "user should call X" → Call X for user |
| 5 | Use real data only | Ask for actual name, not `customer_name="User"` |
| 6 | Be accurate, no hallucinations | Don't invent account numbers |

### Agent Instantiation (Lines 33-38)
```python
root_agent = LlmAgent(
    name="personal_agent",
    model=MODEL,
    instruction=INSTRUCTION,
    tools=[EnvApiToolset(), ask_customer_service],
)
```

**Parameters:**
| Parameter | Value | Type | Description |
|-----------|-------|------|-------------|
| `name` | `"personal_agent"` | str | Agent identifier in logs |
| `model` | `MODEL` | str | LLM model identifier |
| `instruction` | `INSTRUCTION` | str | System prompt |
| `tools` | List | [EnvApiToolset(), ask_customer_service] | Available tools |

**Tool Details:**
1. `EnvApiToolset()` - `BaseToolset` subclass, fetches user tools dynamically
2. `ask_customer_service` - `FunctionTool` for A2A communication with CS

---

## cs_client_tool.py - A2A Communication

### Full Source Code
```python
"""Tool that lets the personal agent talk to the bank's customer service
agent over A2A, propagating the current session's contextId so both agents
(and the env) share one conversation identity."""

import os
import uuid

import httpx
from a2a.client import ClientConfig, ClientFactory, minimal_agent_card
from a2a.types import Message, Part, Role, Task, TextPart
from google.adk.tools import ToolContext

from env_toolset import session_id

CS_AGENT_URL = os.environ["CS_AGENT_URL"]

_TIMEOUT_S = 300.0


def _text_of_message(message: Message) -> str:
    texts = []
    for part in message.parts or []:
        root = getattr(part, "root", part)
        if isinstance(root, TextPart) and root.text:
            texts.append(root.text)
    return "\n".join(texts)


def _text_of_task(task: Task) -> str:
    texts = []
    for artifact in task.artifacts or []:
        for part in artifact.parts or []:
            root = getattr(part, "root", part)
            if isinstance(root, TextPart) and root.text:
                texts.append(root.text)
    if task.status is not None and task.status.message is not None:
        text = _text_of_message(task.status.message)
        if text:
            texts.append(text)
    return "\n".join(texts)


async def ask_customer_service(message: str, tool_context: ToolContext) -> str:
    """Send a message to the bank's customer service agent and return its reply.

    The conversation with customer service persists for this whole session,
    so you can ask follow-up questions and they will remember the context.
    """
    outgoing = Message(
        message_id=uuid.uuid4().hex,
        role=Role.user,
        parts=[Part(root=TextPart(text=message))],
        context_id=session_id(tool_context),
    )
    async with httpx.AsyncClient(timeout=_TIMEOUT_S) as http_client:
        client = ClientFactory(
            ClientConfig(streaming=False, httpx_client=http_client)
        ).create(minimal_agent_card(CS_AGENT_URL, ["JSONRPC"]))
        reply = ""
        async for event in client.send_message(outgoing):
            if isinstance(event, Message):
                reply = _text_of_message(event) or reply
            elif isinstance(event, tuple) and isinstance(event[0], Task):
                reply = _text_of_task(event[0]) or reply
    return reply or "[no response from customer service]"
```

### Imports Analysis (Lines 6-14)

| Import | Module | Purpose |
|--------|--------|---------|
| `os` | stdlib | Environment access |
| `uuid` | stdlib | Unique message IDs |
| `httpx` | third-party | Async HTTP |
| `ClientConfig`, `ClientFactory`, `minimal_agent_card` | `a2a.client` | A2A client |
| `Message`, `Part`, `Role`, `Task`, `TextPart` | `a2a.types` | A2A types |
| `ToolContext` | `google.adk.tools` | ADK context |
| `session_id` | `env_toolset` | Extract session ID |

### Configuration (Lines 16-18)
```python
CS_AGENT_URL = os.environ["CS_AGENT_URL"]  # e.g., "http://host.docker.internal:8090/cs-agent"
_TIMEOUT_S = 300.0  # 5 minutes
```

### Helper: _text_of_message() (Lines 21-27)

**Purpose:** Extract text from A2A `Message` object.

**A2A Message Structure:**
```python
Message(
    message_id="msg-123",
    role=Role.user,  # or Role.agent
    parts=[
        Part(root=TextPart(text="Hello")),
        Part(root=TextPart(text="World"))
    ],
    context_id="ctx-abc"
)
```

**Processing:**
```python
for part in message.parts:           # Iterate parts
    root = getattr(part, "root", part) # Unwrap
    if isinstance(root, TextPart):      # Check type
        texts.append(root.text)         # Extract text
```

### Helper: _text_of_task() (Lines 30-41)

**Purpose:** Extract text from A2A `Task` object.

**A2A Task Structure:**
```python
Task(
    id="task-456",
    session_id="ctx-abc",
    status=TaskStatus(
        state=TaskState.completed,
        message=Message(...)  # Status message
    ),
    artifacts=[
        Artifact(parts=[Part(root=TextPart(text="Final answer"))])
    ]
)
```

**Processing:**
1. Extract text from `task.artifacts[]`
2. Extract text from `task.status.message`
3. Join all text parts

### Main Function: ask_customer_service() (Lines 44-66)

**Signature:**
```python
async def ask_customer_service(message: str, tool_context: ToolContext) -> str
```

**Parameters:**
| Parameter | Type | Source | Description |
|-----------|------|--------|-------------|
| `message` | `str` | LLM provides | Text to send to CS |
| `tool_context` | `ToolContext` | ADK injects | Contains session info |

**Returns:** `str` - CS agent's response text

**Execution Flow:**

```python
# Step 1: Build A2A Message
outgoing = Message(
    message_id=uuid.uuid4().hex,              # Random unique ID
    role=Role.user,                            # We are "user" to CS agent
    parts=[Part(root=TextPart(text=message))], # Wrap text
    context_id=session_id(tool_context),        # ← CRITICAL: Same contextId!
)

# Step 2: Create HTTP client (5 min timeout)
async with httpx.AsyncClient(timeout=_TIMEOUT_S) as http_client:

    # Step 3: Create A2A client
    client = ClientFactory(
        ClientConfig(streaming=False, httpx_client=http_client)
    ).create(minimal_agent_card(CS_AGENT_URL, ["JSONRPC"]))
    # minimal_agent_card creates agent descriptor from URL

    # Step 4: Send and collect response
    reply = ""
    async for event in client.send_message(outgoing):
        # Events can be Message or Task objects
        if isinstance(event, Message):
            reply = _text_of_message(event) or reply
        elif isinstance(event, tuple) and isinstance(event[0], Task):
            reply = _text_of_task(event[0]) or reply

# Step 5: Return response
return reply or "[no response from customer service]"
```

---

## env_toolset.py - Tool Discovery

### Full Source Code
```python
"""Dynamic ADK toolset over the harness env API.

Tools are fetched live for the current session (keyed by the incoming A2A
contextId), so tools granted mid-conversation appear automatically. A generic
call_env_tool fallback covers anything not yet in the fetched list."""

import json
import os
from typing import Any, Optional

import httpx
from google.adk.agents.readonly_context import ReadonlyContext
from google.adk.tools import BaseTool, FunctionTool, ToolContext
from google.adk.tools.base_toolset import BaseToolset
from google.genai import types

ENV_API_URL = os.environ["ENV_API_URL"].rstrip("/")
ENV_API_TOKEN = os.environ["ENV_API_TOKEN"]

_HEADERS = {"Authorization": f"Bearer {ENV_API_TOKEN}"}


def session_id(context: ReadonlyContext) -> str:
    """The env session id == the incoming A2A contextId (ADK keys its session
    on the contextId, so this is free)."""
    return context.session.id


async def _post_tool_call(sid: str, name: str, arguments: dict) -> dict:
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{ENV_API_URL}/sessions/{sid}/tools/{name}",
            json={"arguments": arguments},
            headers=_HEADERS,
        )
        if resp.status_code != 200:
            return {"error": True, "content": f"HTTP {resp.status_code}: {resp.text}"}
        return resp.json()


async def call_env_tool(
    tool_name: str, arguments_json: str, tool_context: ToolContext
) -> dict:
    """Call any environment tool by name.

    Use this for tools that are not in your tool list yet (for example a tool
    you were just granted). `arguments_json` is a JSON object string, e.g.
    '{"user_id": "abc123"}'.
    """
    try:
        arguments = json.loads(arguments_json or "{}")
    except json.JSONDecodeError as e:
        return {"error": True, "content": f"Invalid arguments JSON: {e}"}
    return await _post_tool_call(session_id(tool_context), tool_name, arguments)


class EnvApiTool(BaseTool):
    """One env tool, declared from its OpenAI-style schema."""

    def __init__(self, schema: dict):
        function = schema["function"]
        super().__init__(
            name=function["name"], description=function.get("description", "")
        )
        self._parameters = function.get("parameters")

    def _get_declaration(self) -> types.FunctionDeclaration:
        return types.FunctionDeclaration(
            name=self.name,
            description=self.description,
            parameters_json_schema=self._parameters,
        )

    async def run_async(self, *, args: dict[str, Any], tool_context: ToolContext) -> dict:
        return await _post_tool_call(session_id(tool_context), self.name, args)


class EnvApiToolset(BaseToolset):
    """Serves the env tools for the current session plus the generic fallback."""

    async def get_tools(self, readonly_context: Optional[ReadonlyContext] = None) -> list[BaseTool]:
        fallback: list[BaseTool] = [FunctionTool(call_env_tool)]
        if readonly_context is None:
            # No session yet (e.g. agent card construction).
            return fallback
        sid = session_id(readonly_context)
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{ENV_API_URL}/sessions/{sid}/tools", headers=_HEADERS
            )
        resp.raise_for_status()
        return [EnvApiTool(schema) for schema in resp.json()["tools"]] + fallback

    async def close(self) -> None:
        pass
```

### Constants (Lines 17-20)
```python
ENV_API_URL = os.environ["ENV_API_URL"].rstrip("/")  # e.g., "http://host.docker.internal:8090"
ENV_API_TOKEN = os.environ["ENV_API_TOKEN"]            # e.g., "dev-user-token"
_HEADERS = {"Authorization": f"Bearer {ENV_API_TOKEN}"}
```

### Function: session_id() (Lines 23-26)
```python
def session_id(context: ReadonlyContext) -> str:
    """The env session id == the incoming A2A contextId."""
    return context.session.id
```

**Critical:** This bridges ADK session.id with A2A contextId. ADK uses the incoming A2A `context_id` as the session ID, so `session_id(context)` returns the `contextId` for environment API calls.

### Function: _post_tool_call() (Lines 29-39)
```python
async def _post_tool_call(sid: str, name: str, arguments: dict) -> dict:
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{ENV_API_URL}/sessions/{sid}/tools/{name}",
            json={"arguments": arguments},
            headers=_HEADERS,
        )
        if resp.status_code != 200:
            return {"error": True, "content": f"HTTP {resp.status_code}: {resp.text}"}
        return resp.json()
```

**API Call:**
```
POST {ENV_API_URL}/sessions/{sid}/tools/{name}
Headers: Authorization: Bearer {ENV_API_TOKEN}
Body: {"arguments": {...}}
```

**Response Format:**
```json
{
  "content": "Tool result here",
  "error": false
}
```

### Function: call_env_tool() (Lines 42-55)
```python
async def call_env_tool(
    tool_name: str, arguments_json: str, tool_context: ToolContext
) -> dict:
    """Call any environment tool by name (fallback for tools not yet discovered)."""
    try:
        arguments = json.loads(arguments_json or "{}")
    except json.JSONDecodeError as e:
        return {"error": True, "content": f"Invalid arguments JSON: {e}"}
    return await _post_tool_call(session_id(tool_context), tool_name, arguments)
```

**Purpose:** Generic fallback tool. Can call ANY environment tool by name, even tools not in the discovered list.

**Parameters:**
| Parameter | Type | Example |
|-----------|------|---------|
| `tool_name` | str | `"submit_referral"` |
| `arguments_json` | str | `'{"account_type": "Blue Account"}'` |
| `tool_context` | ToolContext | ADK-injected context |

### Class: EnvApiTool (Lines 58-76)
```python
class EnvApiTool(BaseTool):
    """One env tool, declared from its OpenAI-style schema."""

    def __init__(self, schema: dict):
        function = schema["function"]
        super().__init__(
            name=function["name"], description=function.get("description", "")
        )
        self._parameters = function.get("parameters")

    def _get_declaration(self) -> types.FunctionDeclaration:
        return types.FunctionDeclaration(
            name=self.name,
            description=self.description,
            parameters_json_schema=self._parameters,
        )

    async def run_async(self, *, args: dict[str, Any], tool_context: ToolContext) -> dict:
        return await _post_tool_call(session_id(tool_context), self.name, args)
```

**Input Schema Format (from Environment API):**
```python
{
  "function": {
    "name": "tool_name",
    "description": "What this tool does",
    "parameters": {
      "type": "object",
      "properties": {...},
      "required": [...]
    }
  }
}
```

**ADK Declaration:** Converts to `types.FunctionDeclaration` for LLM function calling.

### Class: EnvApiToolset (Lines 79-96)
```python
class EnvApiToolset(BaseToolset):
    """Serves the env tools for the current session plus the generic fallback."""

    async def get_tools(self, readonly_context: Optional[ReadonlyContext] = None) -> list[BaseTool]:
        fallback: list[BaseTool] = [FunctionTool(call_env_tool)]
        if readonly_context is None:
            return fallback  # No session yet (agent card construction)
        sid = session_id(readonly_context)
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{ENV_API_URL}/sessions/{sid}/tools", headers=_HEADERS
            )
        resp.raise_for_status()
        return [EnvApiTool(schema) for schema in resp.json()["tools"]] + fallback

    async def close(self) -> None:
        pass
```

**Dynamic Discovery Flow:**

```
1. ADK calls get_tools(context)
        ↓
2. Extract session ID from context
        ↓
3. Fetch tools from Environment API:
   GET {ENV_API_URL}/sessions/{sid}/tools
   Headers: Authorization: Bearer {TOKEN}
        ↓
4. Parse response (OpenAI-style tool list)
        ↓
5. Convert each to EnvApiTool
        ↓
6. Return: [EnvApiTool1, EnvApiTool2, ..., call_env_tool]
```

---

## Dockerfile & Requirements

### Dockerfile
```dockerfile
FROM python:3.12-slim

WORKDIR /app
COPY personal_agent/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY personal_agent/ .

EXPOSE 9001
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "9001"]
```

**Steps:**
1. Base image: `python:3.12-slim`
2. Set workdir: `/app`
3. Copy and install requirements
4. Copy all agent files
5. Expose port 9001
6. Run uvicorn ASGI server

### requirements.txt
```
google-adk[a2a]>=1.10          # ADK framework with A2A extensions
a2a-sdk[http-server]>=0.3.4,<0.4  # A2A protocol SDK
httpx>=0.27                    # Async HTTP client
uvicorn>=0.34                  # ASGI server
```

---

## Next Part

- **Part 3**: Customer Service Agent Deep Dive (`cs_agent/` files, Redis, RAG)
# Part 3: Customer Service Agent Deep Dive

> **For AI Assistants**: Part 3 of 5. See Part 1 for system overview.

## Contents
1. [main.py - Readiness Gate](#mainpy---readiness-gate)
2. [agent.py - CS Agent Definition](#agentpy---cs-agent-definition)
3. [rag_tools.py - Redis Search](#rag_toolspy---redis-search)
4. [ingest.py - KB Indexing](#ingestpy---kb-indexing)
5. [precompute_embeddings.py](#precompute_embeddingspy)

---

## main.py - Readiness Gate

```python
"""Serve the CS agent over A2A."""
import os
from google.adk.a2a.utils.agent_to_a2a import to_a2a
from ingest import build_index

build_index()  # ← BLOCKS until KB is indexed

from agent import root_agent  # noqa: E402

app = to_a2a(root_agent, host=os.environ.get("HOST", "0.0.0.0"), port=int(os.environ.get("PORT", "9002"))
```

**Pattern:** `build_index()` runs BEFORE agent import. Agent card only served after KB is ready.

---

## agent.py - CS Agent Definition

```python
"""Rho-Bank customer service agent: policy + env tools + KB search (RAG)."""
import os
from pathlib import Path
from google.adk.agents import LlmAgent
from env_toolset import EnvApiToolset
from rag_tools import kb_search_bm25, kb_search_vector

MODEL = os.environ.get("MODEL", "gemini-3.5-flash")
POLICY_PATH = Path(os.environ.get("KB_POLICY_PATH", "/app/kb/policy.md"))

RAG_GUIDANCE = """
## Knowledge Base Access
You do NOT have the knowledge base inlined. Before answering policy questions
or performing scenario-specific procedures, search the knowledge base:
- kb_search_bm25(query): keyword search.
- kb_search_vector(query): semantic search for natural-language questions.
Search before you act; procedures, eligibility rules, internal tool names,
and scenario-specific guidance all live in the knowledge base.
"""

root_agent = LlmAgent(
    name="cs_agent",
    model=MODEL,
    instruction=POLICY_PATH.read_text() + RAG_GUIDANCE,
    tools=[EnvApiToolset(), kb_search_bm25, kb_search_vector],
)
```

**Key Points:**
- Loads `kb/policy.md` as base instruction
- Appends `RAG_GUIDANCE` reminding to search KB
- Tools: `EnvApiToolset()` (bank tools), `kb_search_bm25`, `kb_search_vector`

---

## rag_tools.py - Redis Search

### Constants
| Constant | Value |
|----------|-------|
| `REDIS_URL` | `redis://redis:6379/0` |
| `KB_INDEX` | `"kb_idx"` |
| `DOC_PREFIX` | `"doc:"` |
| `EMBEDDING_MODEL` | `"gemini-embedding-001"` |
| `EMBEDDING_DIM` | `768` |

### Key Functions

#### `kb_search_bm25(query, top_k=5)`
```python
def kb_search_bm25(query: str, top_k: int = 5) -> list[dict]:
    terms = re.findall(r"\w+", query.lower())
    if not terms:
        return []
    or_query = "|".join(dict.fromkeys(terms))  # OR-join terms
    reply = _client.execute_command(
        "FT.SEARCH", KB_INDEX, or_query,
        "LIMIT", "0", str(top_k),
        "RETURN", "2", "title", "content",
    )
    return _parse_search_reply(reply)
```

**Redis Command:** `FT.SEARCH kb_idx "term1|term2" LIMIT 0 5 RETURN 2 title content`

**Returns:** `[{"doc_id": "...", "title": "...", "content": "..."}, ...]`

#### `kb_search_vector(query, top_k=5)`
```python
def kb_search_vector(query: str, top_k: int = 5) -> list[dict]:
    vector = struct.pack(f"{EMBEDDING_DIM}f", *_embed([query])[0])
    reply = _client.execute_command(
        "FT.SEARCH", KB_INDEX, f"*=>[KNN {top_k} @embedding $vec AS score]",
        "PARAMS", "2", "vec", vector,
        "SORTBY", "score",
        "LIMIT", "0", str(top_k),
        "RETURN", "3", "title", "content", "score",
        "DIALECT", "2",
    )
    return _strip_score(_parse_search_reply(reply))
```

**Redis Command:** KNN vector search with HNSW index, COSINE similarity

---

## ingest.py - KB Indexing

### Process Flow
```
1. Connect to Redis
2. Load 698 documents from kb/documents/*.json
3. Drop existing index (if any)
4. Create new index:
   - TextField("title", weight=2.0)
   - TextField("content")
   - VectorField("embedding", "HNSW", {TYPE: "FLOAT32", DIM: 768, DISTANCE_METRIC: "COSINE"})
5. Load embedding cache (if exists)
6. Live-embed cache misses in batches of 25
7. Store all docs in Redis as HASH
```

### Key Code
```python
def build_index() -> None:
    client = redis.Redis.from_url(REDIS_URL, decode_responses=False)
    documents = load_documents()  # 698 docs
    
    # Drop old index
    try:
        client.ft(KB_INDEX).dropindex(delete_documents=True)
    except redis.ResponseError:
        pass
    
    # Create index
    client.ft(KB_INDEX).create_index(
        fields=[
            TextField("title", weight=2.0),
            TextField("content"),
            VectorField("embedding", "HNSW", {
                "TYPE": "FLOAT32", "DIM": 768, "DISTANCE_METRIC": "COSINE"
            }),
        ],
        definition=IndexDefinition(prefix=[DOC_PREFIX], index_type=IndexType.HASH),
    )
    
    # Load/embed documents
    cache = load_embedding_cache()
    embedding_bytes = [cache.get(d["id"]) for d in documents]
    misses = [i for i, b in enumerate(embedding_bytes) if b is None]
    
    # Live embed misses
    if misses:
        for start in range(0, len(misses), 25):
            idx = misses[start:start+25]
            vectors = _embed([f"{documents[i]['title']}\n{documents[i]['content']}" for i in idx])
            for i, vector in zip(idx, vectors):
                embedding_bytes[i] = struct.pack("768f", *vector)
    
    # Store in Redis
    pipe = client.pipeline(transaction=False)
    for doc, emb in zip(documents, embedding_bytes):
        mapping = {"title": doc["title"], "content": doc["content"]}
        if emb:
            mapping["embedding"] = emb
        pipe.hset(f"doc:{doc['id']}", mapping=mapping)
    pipe.execute()
```

---

## precompute_embeddings.py

```python
"""Precompute KB embedding cache (kb/embeddings.json)."""
import base64, json, os, struct, sys
from pathlib import Path
from ingest import load_documents
from rag_tools import EMBEDDING_DIM, _embed

KB_EMBEDDINGS_PATH = Path(os.environ.get("KB_EMBEDDINGS_PATH", "/app/kb/embeddings.json"))

def main() -> None:
    documents = load_documents()
    cache = {}
    for start in range(0, len(documents), 25):
        batch = documents[start:start+25]
        vectors = _embed([f"{d['title']}\n{d['content']}" for d in batch])
        for doc, vector in zip(batch, vectors):
            cache[doc["id"]] = base64.b64encode(struct.pack("768f", *vector)).decode()
    KB_EMBEDDINGS_PATH.write_text(json.dumps(cache))
```

**Purpose:** Generate embedding cache to avoid live embedding at startup (faster, cheaper).

**Usage:** `python cs_agent/precompute_embeddings.py`

**Output Format (embeddings.json):**
```json
{
  "doc_bank_accounts_001": "base64_encoded_float32_array...",
  "doc_bank_accounts_002": "..."
}
```

---

## Dockerfile & Requirements

### Dockerfile
```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY cs_agent/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY cs_agent/ .
COPY kb/ ./kb/          # ← Copies KB folder
EXPOSE 9002
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "9002"]
```

### requirements.txt
```
google-adk[a2a]>=1.10
a2a-sdk[http-server]>=0.3.4,<0.4
httpx>=0.27
uvicorn>=0.34
redis>=5.0
google-genai>=1.0
```

Extra deps vs personal_agent: `redis`, `google-genai`

---

## Next Part

- **Part 4**: Knowledge Base Analysis (`kb/` documents)
# Part 4: Knowledge Base Complete Analysis

> **For AI Assistants**: Part 4 of 5. This section covers the `kb/` folder in depth.

## Table of Contents
1. [KB Structure Overview](#kb-structure-overview)
2. [policy.md - Master Policy](#policymd---master-policy)
3. [documents/ - 698 KB Articles](#documents---698-kb-articles)
4. [Document Categories](#document-categories)
5. [Document Format & Schema](#document-format--schema)
6. [embeddings.json - Cache File](#embeddingsjson---cache-file)

---

## KB Structure Overview

```
kb/
├── policy.md              # Master CS agent policy (62 lines)
├── documents/             # 698 JSON articles
│   ├── doc_bank_accounts_bank_accounts_(general)_001.json
│   ├── doc_bank_accounts_bank_accounts_(general)_002.json
│   ├── ... (696 more files)
│   └── doc_credit_cards_credit_card_account_logistics_0xx.json
└── embeddings.json        # Generated cache (gitignored)
```

---

## policy.md - Master Policy

**Location:** `kb/policy.md`
**Size:** 62 lines (5,599 bytes)

**Full Contents:**
```markdown
# Rho-Bank Customer Service Policy

You are a helpful customer service agent for Rho-Bank.
Your goal is to help customers by searching the knowledge base and providing accurate information.

## Guidelines

1. Do not make up policies, information or actions that you can take on behalf of the user. All instructions will be found here or in the knowledge base. If you cannot find relevant information, let the user know. 
2. Do not ask for any documentation, receipts... from the customer unless it states very clearly in the knowledge base how to process it, and whether you're allowed to do so. 
3. Be polite and professional
4. If you need the current time, always use the get_current_time() tool. Do not make up or assume the current time. 
5. Generally, if the issue cannot be resolved or is outside your capabilities, ask the user whether they would like to be transferred to a human agent. If they do, invoke the appropriate transfer_to_human_agents tool. Do this only if you absolutely have to, and you are sure that there are no potential actions you can take as specified in the knowledge base, or in your policy. Do not transfer without asking the user first. This guidance may be overridden by specific scenario-based transfer guidance in the knowledge base. 
6. If an issue falls within your capabilities and the user still wants to be transferred to a human agent, kindly inform the user that you can help them, and try to help them first. If the user asks for a human agent 4 times, then you may invoke the transfer_to_human_agents tool. This guidance may be overridden by specific scenario-based transfer guidance in the knowledge base. 
7. Do not give intermediate responses to users while processing that would give away internal rho-bank information/policies. 



## Additional Instructions

### Discoverable Tools

#### Giving Discoverable Tools to Users
The knowledge base may contain instructions that indicate certain actions should be performed by the user themselves rather than by you. These are called "user discoverable tools." A user discoverable tool is a tool that you provide to the user so they can execute it on their own (e.g., through a customer portal or app).

**When to give user discoverable tools:**
-  Only give a tool when the user would like to perform an action, and the knowledge base explicitly has a tool that allows the user to perform this action (e.g., "to do X, have the user call tool_name(args)"). IMPORTANT: Do not unlock tools that you do not plan on giving to the user and actually using: this causes issues in database logging.
- You must search the knowledge base to find tools that you can give. Do not invent or guess user discoverable tools 
- Only use tool names and arguments discovered in the knowledge base

**How to give a tool:**
- Use the `give_discoverable_user_tool(discoverable_tool_name)` function
- Provide the exact tool name  as specified in the knowledge base
- Explain to the user what the tool does and how to use it, and what arguments to provide. Just explaining isn't enough, you must use the `give_discoverable_user_tool(discoverable_tool_name)` function.

#### Unlocking and Using Agent Discoverable Tools
The knowledge base may contain references to specialized internal tools that you can unlock and use. These are called "agent discoverable tools." Unlike regular tools which are always available, these tools must be explicitly unlocked after discovering them in the knowledge base.

**When to use agent discoverable tools:**
- Only unlock a tool when the knowledge base explicitly mentions it (e.g., "use tool_name to perform X"), and do not unlock tools you do not plan on using.
- You must search the knowledge base to find tools that you can unlock. Do not invent or guess tool names - only use tool names discovered in the knowledge base.

**How to use agent discoverable tools:**
1. First, unlock the tool using `unlock_discoverable_agent_tool(agent_tool_name)` with the exact tool name from the knowledge base: you must unlock the tool before using it to get information on the proper params. IMPORTANT: Do not unlock tools that you do not plan on actually using: this causes issues in database logging.
2. Then, call the tool using `call_discoverable_agent_tool(agent_tool_name, arguments)` with the required arguments
3. The unlock step is required before calling - you cannot call a tool that hasn't been unlocked

### Authenticating Users

Generally, for any scenario involving accessing customer information in internal databases, you must first verify their identify before proceeding. No need to verify more than once in a single conversation. You should ONLY verify a user's identity if you need to access or modify their customer information in internal databases on their behalf.

Here are some concrete examples:
* Looking up account balances, transaction history, referral history...
* Changing account settings (e.g., address, phone number, email)
* Closing an account
* Adding or removing authorized users
* Requesting information about specific transactions
* Discussing specific loan or credit details
* Filing a dispute on behalf of the user

To verify the identity of the user, call the appropriate read tools, and ensure that they are able to give correctly any 2 out of the following values: date of birth, email, phone number, address. Knowing full name or userID is not enough to verify. After verification, you must call the verification logging tool to properly log the information into the verification records. Do not leak any information about the user before they are verified.
```

### Policy Key Points

| Section | Key Rules |
|---------|-----------|
| **Guidelines** | Don't make up policies; don't ask for docs unless KB says so; be polite; use `get_current_time()` tool; transfer to human only when necessary (ask first, or after 4 requests) |
| **User Discoverable Tools** | Tools the USER should call (via their personal agent). Use `give_discoverable_user_tool(tool_name)` to grant. Must be from KB, not invented. |
| **Agent Discoverable Tools** | Tools the CS agent can unlock and use. Must call `unlock_discoverable_agent_tool(tool_name)` before `call_discoverable_agent_tool(tool_name, args)` |
| **Authentication** | Verify identity (2 of: DOB, email, phone, address) before accessing/modifying customer data. Log verification. |

### Tools Referenced in Policy

| Tool | Type | Purpose |
|------|------|---------|
| `get_current_time()` | Standard | Get current time (don't hallucinate) |
| `transfer_to_human_agents` | Standard | Escalate to human CS |
| `give_discoverable_user_tool(tool_name)` | User tools | Grant tool to user |
| `unlock_discoverable_agent_tool(tool_name)` | Agent tools | Unlock internal tool |
| `call_discoverable_agent_tool(tool_name, args)` | Agent tools | Call unlocked tool |

---

## documents/ - 698 KB Articles

### Filename Pattern
```
doc_{CATEGORY}_{SUBCATEGORY}_{NNN}.json
```

**Examples:**
- `doc_bank_accounts_bank_accounts_(general)_001.json`
- `doc_business_checking_accounts_beige_006.json`
- `doc_credit_cards_credit_card_account_logistics_004.json`

### Document Categories (from filename analysis)

| Category | Subcategories | Count (approx) |
|----------|--------------|----------------|
| `bank_accounts` | `bank_accounts_(general)` | ~50 |
| `business_checking_accounts` | `beige` | ~10 |
| `credit_cards` | `credit_card_account_logistics`, others | ~100+ |
| ... | ... | ... |
| **Total** | | **698** |

### Document Format & Schema

**Every document follows this exact structure:**
```json
{
  "id": "string",
  "title": "string",
  "content": "string (markdown)"
}
```

**Field Descriptions:**
| Field | Type | Description |
|-------|------|-------------|
| `id` | String | Unique identifier (matches filename without extension) |
| `title` | String | Human-readable title |
| `content` | String | Markdown-formatted content with procedures |

### Example Documents

#### Example 1: Opening Personal Checking
**File:** `doc_bank_accounts_bank_accounts_(general)_001.json`

```json
{
  "id": "doc_bank_accounts_bank_accounts_(general)_001",
  "title": "Internal: Opening Personal Checking Accounts",
  "content": "## Eligibility Requirements\n\nTo open a personal checking account, ensure all of the following are true:\n1. The customer is verified.\n2. The customer is at least 18 years old.\n3. The customer does not exceed 4 personal checking accounts.\n4. The customer has no checking accounts closed for cause in the past 6 months.\n\n## Opening Procedure\n\n1. Verify customer identity.\n2. Check eligibility requirements listed above.\n3. Confirm the customer's desired account_class selection.\n   - Personal checking account_class options must use the full official name ending with 'Account' (e.g., 'Blue Account', 'Green Account (checking)').\n4. Use open_bank_account_4821 to open the account."
}
```

**Key Information:**
- Eligibility: verified, 18+, <4 accounts, no recent closures
- Tool mentioned: `open_bank_account_4821`
- Account class format: full name ending with 'Account'

#### Example 2: Opening Personal Savings
**File:** `doc_bank_accounts_bank_accounts_(general)_002.json`

```json
{
  "id": "doc_bank_accounts_bank_accounts_(general)_002",
  "title": "Internal: Opening Personal Savings Accounts",
  "content": "## Scope and Focus\n\nProcedure for opening personal savings accounts. Eligibility requirements: 1) Customer must be verified, 2) Customer must already have at least one active Rho-Bank checking account, 3) Cannot have more than 5 personal savings accounts, 4) Must not have any accounts in collections or with negative balances, 5) Must have held their checking account for at least 14 days. Steps: 1) Verify customer identity, 2) Check eligibility requirements, 3) Confirm account selection with customer, 4) Use open_bank_account_4821 to open the account (note: account_class must use the full official name ending with 'Account', e.g., 'Silver Plus Account', 'Gold Account'), 5) Ask the customer if they would like you to transfer the opening deposit from their checking account now. If yes, use transfer_funds_between_bank_accounts_7291 to transfer the required amount. If no, inform them they have 30 days to fund the account (via internal transfer or external deposit) or the account will be closed.\n\n## Eligibility Requirements (Internal Checklist)\n\nConfirm all of the following before proceeding:\n- Customer identity is verified in our systems.\n- Customer has at least one active Rho-Bank checking account.\n- Customer currently holds fewer than 5 personal savings accounts.\n- Customer has no accounts in collections and no negative balances.\n- The customer's checking account tenure is at least 14 days.\n\nDo not proceed if any item above is not met.\n\n## Step-by-Step Procedure\n\n1) Verify identity\n- Authenticate the customer and confirm identity verification status on file.\n\n2) Check eligibility\n- Confirm an active checking account exists and meets the 14-day tenure requirement.\n- Count existing personal savings accounts; ensure the customer is below the 5 limit.\n- Review account status; there must be no collections activity and no negative balances."
}
```

**Key Information:**
- Requires existing checking account (14+ days old)
- Max 5 savings accounts
- Tools: `open_bank_account_4821`, `transfer_funds_between_bank_accounts_7291`
- 30-day funding deadline

#### Example 3: Business Checking (Beige Enterprise)
**File:** `doc_business_checking_accounts_beige_001.json`

```json
{
  "id": "doc_business_checking_accounts_beige_001",
  "title": "Implementing Beige: Enterprise Treasury Onboarding",
  "content": "## Onboarding timeline and responsibilities\n- Confirm executive sponsorship and authorized signers before initiating onboarding.\n- Prepare onboarding documentation, treasury policy, and internal approval matrix.\n- Identify primary funding sources for initial deposits and recurring cash flows.\n\n## Funding and balance setup\n- Maintain at least $250,000 to keep your enterprise-level treasury account in good standing.\n- The monthly maintenance fee is $200.00. This fee is waived when your average balance meets or exceeds $500,000.\n- If you anticipate balance variability during early implementation, align funding schedules to preserve eligibility for the fee waiver threshold.\n\n## Dedicated support structure\n- You are assigned 2 dedicated account managers who coordinate onboarding milestones, entitlements, and operational readiness.\n- Establish a recurring operating cadence with your account team for progress tracking and rapid issue resolution.\n\n## Overdraft settings during go-live\n- Overdrafts incur a fee of $0.00.\n- If you plan to stagger incoming funds across multiple institutions, configure conservative payment windows and internal approvals to avoid negative balances.\n\n## Operational readiness checklist\n- Set signer roles and entitlements consistent with your treasury policy.\n- Add internal approval rules for payments and administrative changes in line with your governance model.\n- Validate statement delivery preferences, reporting formats, and reconciliation identifiers prior to first close.\n- Confirm that funding sources are scheduled to achieve at least $250,000 and, if desired, the waiver threshold of $500,000.\n\n## Reference values for onboarding\n| Item | Value |\n| --- | --- |\n| Monthly maintenance fee | $200.00 |\n| Minimum balance requirement | $250,000 |\n| Fee waiver balance threshold | $500,000 |\n| Dedicated account managers | 2 |\n| Overdraft fee | $0.00 |"
}
```

**Key Information:**
- Beige = Enterprise treasury account
- Minimum balance: $250,000
- Monthly fee: $200 (waived at $500k+ average balance)
- 2 dedicated account managers

#### Example 4: Credit Card Closure
**File:** `doc_credit_cards_credit_card_account_logistics_001.json`

```json
{
  "id": "doc_credit_cards_credit_card_account_logistics_001",
  "title": "How can I close a credit card account?",
  "content": "## Eligibility Requirements for Account Closure\n\nTo close your Rho-Bank credit card account, you must meet all of the following:\n\n1. Zero balance required: Your account must have an outstanding balance of $0.00 dollars. Wait for any pending transactions to post, then pay the full statement balance.\n2. No pending disputes: Accounts with active or pending transaction disputes cannot be closed (pending disputes allowed: No). Request closure only after all disputes are fully resolved.\n3. Minimum account age: Your account must have been open for at least 60 days.\n4. No pending replacement cards: If a replacement card has been ordered and not yet received or activated, complete or cancel the replacement process before requesting closure.\n\n## Rewards and Annual Fee Policies\n\n- Unredeemed rewards: You have 45 days after submitting your closure request to redeem any remaining rewards. After this period, all unredeemed rewards are permanently forfeited.\n- Annual fee refund: If you close your account within 37 days of the annual fee posting, you are eligible for a full refund of that fee. After this window, no refund is provided.\n\n## Impact on Credit Score\n\nClosing a credit card may affect your credit score by reducing your total available credit and potentially impacting your credit utilization ratio. This impact can be more significant if the card has a high credit limit or is among your oldest accounts."
}
```

**Key Information:**
- Closure requirements: $0 balance, no disputes, 60+ days old, no pending cards
- Rewards: 45-day redemption window after closure request
- Annual fee refund: within 37 days of posting

### Common Document Patterns

**Most documents contain:**

| Section | Purpose |
|---------|---------|
| Eligibility Requirements | Prerequisites for the operation |
| Step-by-Step Procedure | Ordered list of actions |
| Tool References | Internal tool names (e.g., `open_bank_account_4821`) |
| Values/Thresholds | Dollar amounts, day counts, limits |
| Warnings | Things NOT to do |

---

## embeddings.json - Cache File

**Location:** `kb/embeddings.json` (gitignored)
**Format:** JSON mapping of doc_id → base64-encoded float32 array

**Example Structure:**
```json
{
  "doc_bank_accounts_bank_accounts_(general)_001": "AAAAAAAAAAAAAAAAAAAAAA...",
  "doc_bank_accounts_bank_accounts_(general)_002": "AAAAAAAAAAAAAAAAAAAAAA...",
  "doc_business_checking_accounts_beige_001": "AAAAAAAAAAAAAAAAAAAAAAAA..."
}
```

**Generation:** Via `precompute_embeddings.py`

**Encoding Process:**
```python
# 1. Embed text
vector = _embed(["{title}\n{content}"])[0]  # 768 floats

# 2. Pack to binary
binary = struct.pack("768f", *vector)  # 3072 bytes

# 3. Base64 encode
cached = base64.b64encode(binary).decode()
```

**Usage in ingest.py:**
```python
cache = load_embedding_cache()  # {doc_id: bytes}
embedding_bytes = [cache.get(doc["id"]) for doc in documents]
```

**Purpose:**
- Instant startup (no API calls during indexing)
- No per-restart embedding costs
- Deterministic, reproducible indexing

---

## Next Part

- **Part 5**: Environment API & A2A Protocol Specifications
# Part 5: Environment API & A2A Protocol Specifications

> **For AI Assistants**: Part 5 of 5. Complete API reference for Environment API and A2A protocol.

## Table of Contents
1. [Environment API Specification](#environment-api-specification)
2. [A2A Protocol Specification](#a2a-protocol-specification)
3. [Testing & Development Loop](#testing--development-loop)
4. [Docker & Deployment](#docker--deployment)
5. [Data Flow Examples](#data-flow-examples)

---

## Environment API Specification

**Base URL:** `http://host.docker.internal:8090` (from harness)

### Authentication
```
Authorization: Bearer {TOKEN}
```

| Agent | Token Env Var | Default |
|-------|---------------|---------|
| personal-agent | `PERSONAL_ENV_API_TOKEN` | `dev-user-token` |
| cs-agent | `CS_ENV_API_TOKEN` | `dev-agent-token` |

### Endpoint 1: List Tools

```
GET /sessions/{contextId}/tools
```

**Response Format:**
```json
{
  "tools": [
    {
      "function": {
        "name": "tool_name",
        "description": "What this tool does",
        "parameters": {
          "type": "object",
          "properties": {
            "param1": {"type": "string", "description": "..."},
            "param2": {"type": "integer", "description": "..."}
          },
          "required": ["param1"]
        }
      }
    }
  ]
}
```

**Personal Agent Tools (Examples):**
- `submit_referral` - Submit account referral
- `apply_for_credit_card` - Apply for credit card
- Various user-side actions

**CS Agent Tools (Examples):**
- `verify_customer` - Verify customer identity
- `open_bank_account_4821` - Open bank account
- `transfer_funds_between_bank_accounts_7291` - Transfer funds
- Various bank-side actions

### Endpoint 2: Execute Tool

```
POST /sessions/{contextId}/tools/{tool_name}
```

**Request Body:**
```json
{
  "arguments": {
    "param1": "value1",
    "param2": 123
  }
}
```

**Response Format:**
```json
{
  "content": "Tool result as string or JSON",
  "error": false
}
```

**Error Response:**
```json
{
  "content": "Error message",
  "error": true
}
```

### Tool Examples

#### Example: submit_referral
```bash
POST /sessions/ctx-123/tools/submit_referral
Authorization: Bearer dev-user-token
Content-Type: application/json

{
  "arguments": {
    "account_type": "Blue Account",
    "friend_name": "Dana",
    "friend_email": "dana@example.com"
  }
}
```

**Response:**
```json
{
  "content": "Referral submitted successfully. Reference: REF-2024-001",
  "error": false
}
```

#### Example: verify_customer
```bash
POST /sessions/ctx-123/tools/verify_customer
Authorization: Bearer dev-agent-token
Content-Type: application/json

{
  "arguments": {
    "date_of_birth": "1985-03-15",
    "email": "user@example.com"
  }
}
```

---

## A2A Protocol Specification

**Protocol:** JSON-RPC 2.0 over HTTP

### Agent Card (GET /)

**Request:**
```bash
GET http://localhost:9001/
```

**Response:**
```json
{
  "name": "personal_agent",
  "description": "User's personal banking assistant for Rho-Bank",
  "url": "http://localhost:9001",
  "version": "1.0.0",
  "capabilities": {
    "streaming": false,
    "pushNotifications": false
  },
  "authentication": null,
  "defaultInputModes": ["text"],
  "defaultOutputModes": ["text"],
  "skills": [
    {
      "id": "banking",
      "name": "Rho-Bank Banking Assistant"
    }
  ]
}
```

### Send Message (POST /message/send)

**Request:**
```bash
POST http://localhost:9001/message/send
Content-Type: application/json

{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "message/send",
  "params": {
    "message": {
      "message_id": "msg-001",
      "role": "user",
      "parts": [
        {
          "type": "text",
          "text": "Check my account balance"
        }
      ],
      "context_id": "ctx-abc-123",
      "parent_message_id": null
    },
    "session_id": "ctx-abc-123"
  }
}
```

**Message Part Types:**
| Type | Structure |
|------|-----------|
| `text` | `{"type": "text", "text": "content"}` |
| `file` | `{"type": "file", "file": {"bytes": "...", "mimeType": "...", "name": "..."}}` |
| `data` | `{"type": "data", "data": {...}}` |

**Response (Task):**
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "id": "task-001",
    "sessionId": "ctx-abc-123",
    "status": {
      "state": "completed",
      "message": {
        "role": "agent",
        "parts": [{"type": "text", "text": "Your balance is $5,000"}]
      }
    },
    "artifacts": [
      {
        "parts": [{"type": "text", "text": "Your balance is $5,000"}],
        "index": 0,
        "append": false
      }
    ],
    "history": [...]
  }
}
```

**Task States:**
| State | Meaning |
|-------|---------|
| `submitted` | Task received, not started |
| `working` | Agent is processing |
| `input-required` | Waiting for user input |
| `completed` | Task finished successfully |
| `canceled` | Task was canceled |
| `failed` | Task failed |

---

## Testing & Development Loop

### Prerequisites
1. Clone hackathon harness: `git clone https://github.com/a2anet/a2a-hackathon`
2. Set up `.env` with your `GOOGLE_API_KEY`
3. Run harness: `uv run a2a-hack --help`

### Local Development Commands

**1. Start Agents:**
```bash
docker compose up --build
```

Services start:
- personal-agent: http://localhost:9001
- cs-agent: http://localhost:9002
- redis: localhost:6379

**2. Smoke Test:**
```bash
export GOOGLE_API_KEY=your_key_here
cd /path/to/a2a-hackathon

uv run a2a-hack smoke \
    --personal-url http://localhost:9001 \
    --cs-url http://localhost:9002
```

**What smoke test does:**
- Runs one sample task
- Prints conversation flow (user↔personal, personal↔CS)
- Shows all environment tool calls
- Validates contextId propagation
- Reports success/failure

**3. Run Training Split:**
```bash
uv run a2a-hack run \
    --personal-url http://localhost:9001 \
    --cs-url http://localhost:9002 \
    --tasks train \
    --save-to results/dev \
    --auto-resume
```

**What this does:**
- Runs all `train` split tasks
- Saves results to `results/dev/`
- Can resume if interrupted

**4. View Results:**
```bash
uv run tau2 view results/dev
```

Shows:
- Task completion rate
- Rewards per task
- Conversation transcripts
- Tool call sequences

### Task Splits

| Split | Purpose | Count |
|-------|---------|-------|
| `train` | Development iteration | ~50 tasks |
| `test` | Generalization check | ~20 tasks |
| `feedback` | Submission feedback | 3 tasks |

**Rule:** Iterate on `train`, use `test` sparingly to check generalization.

---

## Docker & Deployment

### Build Process

```
repo-root/
├── personal_agent/
│   ├── Dockerfile
│   └── ...
├── cs_agent/
│   ├── Dockerfile
│   └── ...
├── kb/
│   ├── policy.md
│   └── documents/
└── docker-compose.yml
```

**Build Context:** Repository root (for `kb/` access)

**CS Agent Build:**
```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY cs_agent/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY cs_agent/ .
COPY kb/ ./kb/          # ← Critical: KB must be in image
EXPOSE 9002
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "9002"]
```

**Personal Agent Build:**
```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY personal_agent/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY personal_agent/ .
EXPOSE 9001
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "9001"]
```

### Environment Variables at Runtime

**Personal Agent:**
```
ENV_API_URL=http://host.docker.internal:8090
ENV_API_TOKEN=dev-user-token
CS_AGENT_URL=http://host.docker.internal:8090/cs-agent
MODEL=gemini-3.5-flash
GOOGLE_GENAI_USE_VERTEXAI=true
GOOGLE_API_KEY=...
```

**CS Agent:**
```
ENV_API_URL=http://host.docker.internal:8090
ENV_API_TOKEN=dev-agent-token
REDIS_URL=redis://redis:6379/0
MODEL=gemini-3.5-flash
GOOGLE_GENAI_USE_VERTEXAI=true
GOOGLE_API_KEY=...
```

---

## Data Flow Examples

### Example 1: Check Balance (Multi-Agent)

```
┌─────────┐    A2A     ┌─────────────────┐    A2A     ┌─────────────────┐
│  User   │───────────►│ personal-agent  │───────────►│    cs-agent     │
└─────────┘            └─────────────────┘            └─────────────────┘
                              │                               │
                              │ GET /sessions/ctx/tools       │ GET /sessions/ctx/tools
                              │ (user-side tools)             │ (bank-side tools)
                              │                               │
                              ▼                               ▼
                    ┌─────────────────┐             ┌─────────────────┐
                    │ Environment API │             │ Environment API │
                    │ (User token)    │             │ (Bank token)    │
                    └─────────────────┘             └─────────────────┘

Flow:
1. User: "What's my balance?"
2. personal-agent: No user tool for balance lookup
3. personal-agent → cs-agent (A2A): "What's the balance for this user?"
4. cs-agent: Needs bank-side lookup
5. cs-agent → Environment API: verify_customer() [if not verified]
6. cs-agent → Environment API: get_account_balance()
7. cs-agent → personal-agent (A2A): "Balance is $5,000"
8. personal-agent → User: "Your balance is $5,000"
```

### Example 2: Submit Referral (Discoverable Tool Pattern)

```
User → personal-agent: "Refer my friend Dana for a Blue Account"

personal-agent (internal):
1. Check user tools - no direct referral tool?
2. Contact cs-agent: "How do I submit a referral?"

cs-agent (internal):
1. Search KB: kb_search_bm25("submit referral")
2. KB says: "Have user call submit_referral(account_type, friend_name, ...)"
3. cs-agent → personal-agent: "Tell user to call submit_referral with these params"

personal-agent (internal):
1. Check user tools - now sees submit_referral!
2. Call submit_referral({account_type: "Blue Account", friend_name: "Dana", ...})
3. personal-agent → User: "Done! Referral submitted."
```

### Example 3: Account Opening (Verification Flow)

```
User → personal-agent: "Open a Blue Account"

personal-agent → cs-agent: "User wants to open Blue Account"

cs-agent (internal):
1. Search KB: kb_search_bm25("open Blue Account")
2. KB says: "Verify customer first (2 of: DOB, email, phone, address)"
3. cs-agent → personal-agent: "Need to verify identity. Provide DOB and email."

personal-agent → User: "I need to verify your identity. What's your date of birth and email?"

User → personal-agent: "1985-03-15, user@example.com"

personal-agent → cs-agent: "DOB: 1985-03-15, Email: user@example.com"

cs-agent (internal):
1. Call verify_customer({dob: "1985-03-15", email: "user@example.com"})
2. Verification successful
3. Call open_bank_account_4821({account_class: "Blue Account"})
4. cs-agent → personal-agent: "Account opened successfully!"

personal-agent → User: "Your Blue Account is now open!"
```

---

## Quick Reference: Key Values & Constants

### Ports
| Service | Port |
|---------|------|
| personal-agent | 9001 |
| cs-agent | 9002 |
| redis | 6379 |
| harness env API | 8090 |

### Redis
| Setting | Value |
|---------|-------|
| Index name | `kb_idx` |
| Key prefix | `doc:` |
| Embedding model | `gemini-embedding-001` |
| Embedding dim | 768 |
| Distance metric | COSINE |
| Batch size (embed) | 25 |

### Models
| Use | Model |
|-----|-------|
| Agent LLM | `gemini-3.5-flash` |
| Embeddings | `gemini-embedding-001` |

### Timeouts
| Operation | Timeout |
|-----------|---------|
| HTTP client (general) | 30s |
| CS agent A2A call | 300s (5 min) |
| Tool discovery | 10s |
| Tool execution | 30s |

---

## Complete File List Summary

| Category | File | Purpose |
|----------|------|---------|
| **Root** | `.env.example` | Environment template |
| | `docker-compose.yml` | Service orchestration |
| | `README.md` | Official docs |
| | `.gitignore` | Exclusions |
| **Personal Agent** | `Dockerfile` | Container build |
| | `main.py` | ASGI entry |
| | `agent.py` | Agent definition |
| | `cs_client_tool.py` | A2A to CS |
| | `env_toolset.py` | Tool discovery |
| | `requirements.txt` | Dependencies |
| **CS Agent** | `Dockerfile` | Container build |
| | `main.py` | Entry with gate |
| | `agent.py` | Agent definition |
| | `env_toolset.py` | Tool discovery |
| | `rag_tools.py` | Redis search |
| | `ingest.py` | KB indexing |
| | `precompute_embeddings.py` | Cache gen |
| | `requirements.txt` | Dependencies |
| **Knowledge Base** | `policy.md` | Master policy |
| | `documents/*.json` | 698 articles |
| | `embeddings.json` | Cache (generated) |

---

## End of Documentation

**All 5 Parts:**
- Part 1: System Overview & Architecture
- Part 2: Personal Agent Deep Dive
- Part 3: Customer Service Agent Deep Dive
- Part 4: Knowledge Base Analysis
- Part 5: Environment API & A2A Protocol
