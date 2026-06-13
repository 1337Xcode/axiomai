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
