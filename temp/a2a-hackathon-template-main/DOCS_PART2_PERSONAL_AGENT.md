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
