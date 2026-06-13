# A2A Hackathon Template - Codebase Explanation

## System Overview

This is a **two-agent banking simulation system** built for the A2A (Agent-to-Agent) Hackathon. It demonstrates how AI agents can communicate with each other using the A2A protocol to handle customer service scenarios.

### High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              HARNESS/ENVIRONMENT                              │
│  (External simulation environment - provides tasks, user simulation, tools)     │
│                         Runs on port 8090 (host)                            │
└─────────────────────────────────────────────────────────────────────────────┘
                                       │
           ┌───────────────────────────┼───────────────────────────┐
           │                           │                           │
           ▼                           ▼                           ▼
┌─────────────────────┐    ┌─────────────────────┐    ┌─────────────────────┐
│   personal-agent    │◄──►│     cs-agent        │    │       redis         │
│     (port 9001)     │    │     (port 9002)     │    │     (port 6379)     │
│                     │    │                     │    │                     │
│ • User-facing       │    │ • Bank-facing       │    │ • Vector DB         │
│ • User tools        │    │ • Bank tools        │    │ • Full-text index   │
│ • Calls CS agent    │    │ • RAG search        │    │ • KB storage        │
└─────────────────────┘    └─────────────────────┘    └─────────────────────┘
```

### Communication Flow

```
User (simulated) ──A2A──► personal-agent ──A2A──► cs-agent ──API──► Environment
                              │                         │
                              │                         ├──► Redis (KB search)
                              │                         │
                              └──► User tools            └──► Bank tools
```

---

## File-by-File Breakdown

### Root Configuration Files

#### `.env.example`
Template for environment variables:
- `ENV_API_URL`: Harness environment API endpoint
- `CS_AGENT_URL`: URL for the customer service agent
- `PERSONAL_ENV_API_TOKEN` / `CS_ENV_API_TOKEN`: Authentication tokens
- `MODEL`: LLM model (defaults to `gemini-3.5-flash`)
- `GOOGLE_GENAI_USE_VERTEXAI`: Whether to use Vertex AI
- `GOOGLE_API_KEY`: Google API key for model access

#### `docker-compose.yml`
Defines three services:
1. **personal-agent**: Port 9001, user-side agent
2. **cs-agent**: Port 9002, bank-side agent, depends on Redis
3. **redis**: Port 6379, vector database for knowledge base

#### `.gitignore`
Excludes `.env`, `__pycache__/`, and `kb/embeddings.json` (generated cache).

#### `README.md`
Comprehensive documentation for hackathon participants covering:
- Architecture explanation
- Rules and constraints
- Dev loop commands
- Submission guidelines

---

## Personal Agent (`personal_agent/`)

### Purpose
The **user's personal banking assistant** that:
- Receives user requests via A2A protocol
- Has access to user-side banking tools (apply for cards, submit referrals)
- Can contact the bank's customer service on the user's behalf
- Runs on port 9001

### Files

#### `main.py`
Entry point that serves the agent over A2A using ADK's `to_a2a()` wrapper.

```python
app = to_a2a(root_agent, host="0.0.0.0", port=9001)
```

#### `agent.py`
Defines the `LlmAgent` with:
- **Name**: `personal_agent`
- **Model**: `gemini-3.5-flash`
- **Instruction**: System prompt explaining the agent's role
- **Tools**: `EnvApiToolset()` + `ask_customer_service`

Key behaviors in prompt:
- Act on user's behalf with user tools
- Contact customer service for bank-side operations
- Relay verification requests between user and CS
- Never invent account details or policies

#### `env_toolset.py`
Dynamic toolset that fetches user tools from the environment API:

**Classes/Functions:**
- `session_id(context)`: Extracts session ID from A2A contextId
- `call_env_tool()`: Generic fallback for tools not yet in the fetched list
- `EnvApiTool`: Wrapper for individual environment tools
- `EnvApiToolset`: Main class that fetches tools live per session

**API Calls:**
- `GET {ENV_API_URL}/sessions/{contextId}/tools` - Lists available tools
- `POST {ENV_API_URL}/sessions/{contextId}/tools/{name}` - Executes tool

#### `cs_client_tool.py`
Tool for communicating with the CS agent over A2A:

**Function:** `ask_customer_service(message, tool_context)`
- Sends message to CS agent via A2A protocol
- Propagates `contextId` so both agents share session identity
- Returns CS agent's text response

**Key points:**
- Uses `a2a.client.ClientFactory` to create A2A client
- Handles both `Message` and `Task` responses
- 5-minute timeout for CS agent responses

#### `Dockerfile`
Python 3.12 slim image, installs requirements, exposes port 9001, runs uvicorn.

#### `requirements.txt`
```
google-adk[a2a]>=1.10      # ADK framework with A2A support
a2a-sdk[http-server]>=0.3.4 # A2A protocol SDK
httpx>=0.27                 # HTTP client
uvicorn>=0.34               # ASGI server
```

---

## Customer Service Agent (`cs_agent/`)

### Purpose
The **bank's customer service agent** that:
- Receives requests from the personal agent via A2A
- Has access to bank-side tools (account lookups, policy enforcement)
- Answers policy questions by searching the knowledge base (Redis RAG)
- Runs on port 9002

### Files

#### `main.py`
Entry point with readiness gate:

```python
build_index()  # Build KB index before serving
from agent import root_agent  # Import after index is ready
app = to_a2a(root_agent, host="0.0.0.0", port=9002)
```

Agent card is only served once the knowledge base index is built.

#### `agent.py`
Defines the `LlmAgent` with:
- **Name**: `cs_agent`
- **Model**: `gemini-3.5-flash`
- **Instruction**: `policy.md` content + RAG guidance
- **Tools**: `EnvApiToolset()` + `kb_search_bm25` + `kb_search_vector`

The instruction dynamically loads from `kb/policy.md` at startup.

#### `env_toolset.py`
Identical to `personal_agent/env_toolset.py` but uses `CS_ENV_API_TOKEN` and fetches bank-side tools instead of user tools.

#### `rag_tools.py`
Knowledge base search tools backed by Redis RediSearch:

**Constants:**
- `REDIS_URL`: Redis connection string
- `KB_INDEX`: "kb_idx" - name of the search index
- `DOC_PREFIX`: "doc:" - key prefix for documents
- `EMBEDDING_MODEL`: "gemini-embedding-001"
- `EMBEDDING_DIM`: 768

**Functions:**

1. **`kb_search_bm25(query, top_k=5)`**
   - Full-text BM25 keyword search
   - OR-semantics (terms joined with `|`)
   - Returns: list of `{doc_id, title, content}`

2. **`kb_search_vector(query, top_k=5)`**
   - Semantic vector search using HNSW
   - Embeds query with `gemini-embedding-001`
   - Returns: list of `{doc_id, title, content}`
   - Falls back to error message if embeddings unavailable

**Helper functions:**
- `_embed(texts)`: Batch embed texts using Google GenAI
- `_parse_search_reply()`: Normalizes Redis FT.SEARCH response format
- `_decode()`: Handles bytes/strings from Redis

#### `ingest.py`
Builds the Redis knowledge base index at startup:

**Process:**
1. Load documents from `kb/documents/*.json`
2. Load pre-baked embeddings from `kb/embeddings.json` (if exists)
3. Live-embed any missing documents (batch size 25)
4. Create RediSearch index with:
   - `title` (TextField, weight 2.0)
   - `content` (TextField)
   - `embedding` (VectorField, HNSW, COSINE metric)
5. Store documents in Redis

**Embedding strategy:**
- Pre-baked cache first (fast startup)
- Live embedding for cache misses
- BM25-only fallback if embedding fails

#### `precompute_embeddings.py`
Standalone script to precompute embeddings:

**Purpose:** Generate `kb/embeddings.json` cache file

```bash
python precompute_embeddings.py
```

This avoids per-restart embedding costs and enables instant startup.

#### `Dockerfile`
Python 3.12 slim, copies both agent code AND `kb/` folder into container.

#### `requirements.txt`
Additional dependency: `redis>=5.0`, `google-genai>=1.0`

---

## Knowledge Base (`kb/`)

### `policy.md`
Master policy document for the CS agent covering:

1. **General Guidelines**: Don't make up policies, be polite, use tools for time
2. **Discoverable Tools**: How to give user tools vs unlock agent tools
3. **User Authentication**: Verify identity (2 of: DOB, email, phone, address)
4. **Transfer Protocol**: When and how to transfer to human agents

### `documents/`
Contains **698 JSON documents** with banking knowledge:

**Document structure:**
```json
{
  "id": "doc_bank_accounts_bank_accounts_(general)_001",
  "title": "Internal: Opening Personal Checking Accounts",
  "content": "## Eligibility Requirements\n\nTo open a personal checking account..."
}
```

**Topics covered (based on filenames):**
- Bank accounts (general procedures)
- Business checking accounts (Beige accounts)
- Credit cards (logistics, applications)
- Account management procedures
- Customer service protocols
- Internal tools and procedures

### `embeddings.json` (generated)
Pre-computed embedding cache mapping `doc_id` → `base64(float32_vector)`.
Generated by `precompute_embeddings.py` to avoid live embedding at startup.

---

## Data Flow Deep Dive

### Session/Context Flow
```
1. Harness creates session with contextId="ctx123"
2. User message arrives at personal-agent with contextId="ctx123"
3. personal-agent:
   - Uses "ctx123" to fetch user tools from env API
   - Uses "ctx123" when calling CS agent
   - Uses "ctx123" when executing user tools
4. cs-agent:
   - Receives message with contextId="ctx123"
   - Uses "ctx123" to fetch bank tools from env API
   - Uses "ctx123" when executing bank tools
   - Uses "ctx123" for KB search context (if any)
5. Environment:
   - All tools for session "ctx123" are isolated
   - User-side and bank-side tools share session state via contextId
```

### Tool Discovery Flow
```
personal-agent receives message
         │
         ▼
EnvApiToolset.get_tools(context) called
         │
         ▼
GET /sessions/{contextId}/tools ──► Environment API
         │
         ▼
Returns OpenAI-style tool schemas
         │
         ▼
ADK converts schemas to FunctionTools
         │
         ▼
LLM can now call tools by name
         │
         ▼
Tool call ──► EnvApiTool.run_async() ──► POST /sessions/{contextId}/tools/{name}
```

### RAG Flow (CS Agent)
```
CS agent receives policy question
         │
         ▼
LLM decides to search KB
         │
         ▼
kb_search_bm25("opening checking account") OR kb_search_vector("how do I open an account?")
         │
         ▼
Redis FT.SEARCH query
         │
         ▼
Returns top_k documents {doc_id, title, content}
         │
         ▼
LLM uses content to answer question
```

---

## Technology Stack

| Component | Technology | Purpose |
|-----------|------------|---------|
| Agent Framework | Google ADK (Agent Development Kit) | Agent logic, tool integration |
| Protocol | A2A (Agent-to-Agent) | Inter-agent communication |
| LLM | Gemini 3.5 Flash (Vertex AI) | Language model |
| Embeddings | Gemini Embedding-001 | Vector search |
| Vector DB | Redis 8 with RediSearch | Full-text + vector search |
| HTTP Client | httpx | Async API calls |
| Server | Uvicorn | ASGI HTTP server |
| Container | Docker + Compose | Deployment |

---

## Key Design Patterns

1. **Dynamic Tool Discovery**: Tools are fetched live per session, enabling mid-conversation tool grants
2. **Context Propagation**: `contextId` flows through A2A messages and env API calls, maintaining session state
3. **A2A Protocol**: Standardized agent communication with agent cards, JSON-RPC, streaming support
4. **RAG Architecture**: Hybrid BM25 + vector search over pre-indexed knowledge base
5. **Pre-computed Embeddings**: Cache embeddings for instant startup, fallback to live embedding
6. **Readiness Gates**: CS agent only serves after KB index is built

---

## Execution Flow Example

**Task**: "Refer my friend Dana for a Blue Account"

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ 1. User ──► personal-agent                                                   │
│    A2A: "Please refer my friend Dana for a Blue Account."                    │
│    contextId: "ctx42"                                                        │
├──────────────────────────────────────────────────────────────────────────────┤
│ 2. personal-agent (internal)                                                 │
│    LLM: Need to submit referral, but first check how...                      │
│    Tool: ask_customer_service("How do I submit a referral?")                 │
│    A2A out ──► cs-agent (contextId: "ctx42")                                  │
├──────────────────────────────────────────────────────────────────────────────┤
│ 3. cs-agent (internal)                                                       │
│    Tool: kb_search_bm25("submit referral")                                   │
│    Result: "Have user call submit_referral() with account_type..."           │
│    A2A back ──► personal-agent: "Verify customer first..."                  │
├──────────────────────────────────────────────────────────────────────────────┤
│ 4. personal-agent (internal)                                                 │
│    Tool: submit_referral({"account_type": "Blue Account", "friend_name":     │
│          "Dana", ...})                                                       │
│    POST /sessions/ctx42/tools/submit_referral                                 │
│    Result: {"content": "Referral submitted.", "error": false}                │
├──────────────────────────────────────────────────────────────────────────────┤
│ 5. personal-agent ──► User                                                   │
│    A2A: Task completed, artifact: "Done — I've submitted the referral..."    │
└──────────────────────────────────────────────────────────────────────────────┘
```
