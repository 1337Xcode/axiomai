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
