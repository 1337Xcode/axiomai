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
