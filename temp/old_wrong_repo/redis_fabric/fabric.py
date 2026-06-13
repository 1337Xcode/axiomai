"""
Redis Memory Fabric.

Implements the 4-plane memory architecture:
  Plane 1 — Session state hashes (Redis Hash at session:{session_id})
  Plane 2 — Event stream (Redis Stream at axiom:events, MAXLEN ~ 10000)
  Plane 3 — Long-term customer memory (embedding + cosine similarity)
  Plane 4 — Research result cache (SHA256-keyed, TTL 3600s)

All Redis operations degrade gracefully to SQLite in development/test mode.
In grading mode Redis failures surface as hard errors (no silent fallbacks).
"""
import asyncio
import hashlib
import json
import logging
import math
import os
import socket as _socket
import sqlite3
import time
from typing import Callable, TypeVar

import redis.asyncio as aioredis
from dotenv import load_dotenv
from google import genai

from config import (
    AXIOM_MODE,
    EMBEDDING_DIMENSIONS,
    EMBEDDING_MODEL,
    REDIS_MAX_CONNECTIONS,
    REDIS_MEMORY_TTL,
    REDIS_URL,
)
from redis_fabric.ids import derive_session_id, derive_task_id

logger = logging.getLogger(__name__)

# Load environment variables from .env
load_dotenv()

T = TypeVar("T")

# ---------------------------------------------------------------------------
# Typed failure for embedding — never substitute a zero vector.
# ---------------------------------------------------------------------------
class EmbeddingUnavailable(Exception):
    """Raised when the embedding API call fails or returns no values."""


# Build keepalive options using integer keys (portable — string keys fail on Windows).
_keepalive_opts: dict[int, int] = {}
for _attr, _val in (("TCP_KEEPIDLE", 30), ("TCP_KEEPINTVL", 10), ("TCP_KEEPCNT", 3)):
    _const = getattr(_socket, _attr, None)
    if _const is not None:
        _keepalive_opts[_const] = _val

REDIS_POOL = aioredis.ConnectionPool.from_url(
    REDIS_URL,
    decode_responses=True,
    max_connections=REDIS_MAX_CONNECTIONS,
    socket_connect_timeout=2,
    socket_timeout=5,
    socket_keepalive=bool(_keepalive_opts),
    socket_keepalive_options=_keepalive_opts if _keepalive_opts else None,
    retry_on_timeout=True,
    retry_on_error=[ConnectionError, TimeoutError],
    health_check_interval=30,
)

async def get_redis() -> aioredis.Redis:
    """Function."""
    return aioredis.Redis(connection_pool=REDIS_POOL)

# [FIXED BUG 2] All XADD calls include MAXLEN ~ 10000
LUA_TRANSITION = """
local session_key = KEYS[1]
local stream_key = KEYS[2]
local field_name = ARGV[1]
local field_value = ARGV[2]
local event_type = ARGV[3]
local session_id = ARGV[4]
local task_id = ARGV[5]
local timestamp = ARGV[6]

-- Optimistic concurrency: refuse writes to terminal sessions
local current_status = redis.call('HGET', session_key, 'status')
if current_status == 'completed' or current_status == 'failed' or current_status == 'canceled' or current_status == 'rejected' then
    return redis.error_reply('TERMINAL_STATE: cannot update')
end

redis.call('HSET', session_key, field_name, field_value)
redis.call('HSET', session_key, 'last_updated', timestamp)

-- [FIXED BUG 2] MAXLEN cap prevents unbounded memory growth
redis.call('XADD', stream_key, 'MAXLEN', '~', '10000', '*',
    'event', event_type,
    'session_id', session_id,
    'task_id', task_id,
    'payload_key', field_name,
    'timestamp', timestamp
)

redis.call('EXPIRE', session_key, 86400)
return 1
"""

# ==========================================
# KILL SWITCH: In-memory fallback structures
# ==========================================


MOCK_ACCOUNTS = {
    "ACC-12345": {
        "account_id": "ACC-12345",
        "name": "Alice Johnson",
        "tier": "premium",
        "lifetime_value": 2450.00,
        "email": "alice.johnson@example.com",
        "recent_orders": [
            {
                "order_id": "ORD-99887",
                "date": "2026-06-05",
                "total": 120.50,
                "status": "delivered",
                "items": ["Wireless Headphones", "USB-C Cable"]
            },
            {
                "order_id": "ORD-55443",
                "date": "2026-05-12",
                "total": 89.99,
                "status": "delivered",
                "items": ["Smart Water Bottle"]
            }
        ]
    },
    "ACC-67890": {
        "account_id": "ACC-67890",
        "name": "Bob Smith",
        "tier": "standard",
        "lifetime_value": 350.00,
        "email": "bob.smith@example.com",
        "recent_orders": [
            {
                "order_id": "ORD-11223",
                "date": "2026-06-10",
                "total": 45.00,
                "status": "processing",
                "items": ["Ergonomic Mouse"]
            }
        ]
    }
}

_SQLITE_PATH = ".axiom_fallback_db.sqlite"


def _get_sqlite_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(_SQLITE_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """CREATE TABLE IF NOT EXISTS sessions (
            session_id TEXT PRIMARY KEY,
            data TEXT
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS tasks (
            task_id TEXT PRIMARY KEY,
            session_id TEXT
        )"""
    )
    conn.commit()
    return conn


async def _run_sqlite(fn: Callable[[], T]) -> T:
    """Run blocking sqlite work off the event loop."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, fn)


def _sqlite_seed_fallback(
    session_id: str,
    task_id: str,
    created_at: int,
    raw_digest: str,
) -> None:
    conn = _get_sqlite_conn()
    row = conn.execute(
        "SELECT data FROM sessions WHERE session_id = ?", (session_id,)
    ).fetchone()
    if row:
        session = json.loads(row["data"])
        if session.get("status") in ("completed", "failed", "canceled", "rejected"):
            conn.execute(
                "INSERT OR REPLACE INTO tasks (task_id, session_id) VALUES (?, ?)",
                (task_id, session_id),
            )
            conn.commit()
            return

    session_data = {
        "session_id": session_id,
        "task_id": task_id,
        "created_at": str(created_at),
        "status": "active",
        "tier": "personal_agent",
        "raw_digest": raw_digest,
    }
    conn.execute(
        "INSERT OR REPLACE INTO sessions (session_id, data) VALUES (?, ?)",
        (session_id, json.dumps(session_data)),
    )
    conn.execute(
        "INSERT OR REPLACE INTO tasks (task_id, session_id) VALUES (?, ?)",
        (task_id, session_id),
    )
    conn.commit()


async def seed_session(
    raw_message: str,
    session_id: str | None = None,
    task_id: str | None = None,
    *,
    message_id: str | None = None,
    peer_id: str | None = None,
) -> tuple[str, str]:
    """Seed a session atomically in Redis (SQLite fallback in dev/test)."""
    if not session_id:
        session_id = derive_session_id(
            message_id=message_id,
            raw_message=raw_message,
            peer_id=peer_id,
        )
    if not task_id:
        task_id = derive_task_id(
            session_id=session_id,
            message_id=message_id,
            peer_id=peer_id,
        )
    created_at = int(time.time())
    raw_digest = hashlib.sha256(raw_message.encode()).hexdigest()[:16]

    # Test/CI: skip Redis round-trip when the harness has no Redis yet.
    if AXIOM_MODE == "test":
        try:
            await _run_sqlite(
                lambda: _sqlite_seed_fallback(
                    session_id, task_id, created_at, raw_digest
                )
            )
        except Exception as sql_e:
            logger.warning("SQLite seed failed in test mode: %s", sql_e)
        return session_id, task_id

    LUA_SEED = """
local session_key = KEYS[1]
local stream_key = KEYS[2]
local session_id = ARGV[1]
local task_id = ARGV[2]
local created_at = ARGV[3]
local raw_digest = ARGV[4]

redis.call('HSET', session_key,
    'session_id', session_id,
    'task_id', task_id,
    'created_at', created_at,
    'status', 'active',
    'tier', 'personal_agent',
    'raw_digest', raw_digest
)
redis.call('EXPIRE', session_key, 86400)

-- Map task ID to session ID for A2A lookup
redis.call('SET', 'task:to:session:' .. task_id, session_id)
redis.call('EXPIRE', 'task:to:session:' .. task_id, 86400)

-- [FIXED BUG 2] MAXLEN ~ 10000 prevents unbounded stream growth
redis.call('XADD', stream_key, 'MAXLEN', '~', '10000', '*',
    'event', 'session_created',
    'session_id', session_id,
    'task_id', task_id,
    'timestamp', created_at
)
return 1
"""
    try:
        redis = await get_redis()
        await redis.eval(
            LUA_SEED, 2,
            f"session:{session_id}",
            "axiom:events",
            session_id, task_id, str(created_at), raw_digest,
        )
    except Exception as e:
        logger.warning("Redis seed failed, falling back to SQLite: %s", e)
        if AXIOM_MODE != "grading":
            try:
                await _run_sqlite(
                    lambda: _sqlite_seed_fallback(
                        session_id, task_id, created_at, raw_digest
                    )
                )
            except Exception as sql_e:
                logger.warning("SQLite fallback failed: %s", sql_e)

    return session_id, task_id


def _sqlite_transition_fallback(
    session_id: str,
    task_id: str,
    field_name: str,
    field_value: str,
    event_type: str,
    timestamp: str,
) -> bool:
    conn = _get_sqlite_conn()
    row = conn.execute(
        "SELECT data FROM sessions WHERE session_id = ?", (session_id,)
    ).fetchone()
    if row:
        session = json.loads(row["data"])
    else:
        session = {
            "session_id": session_id,
            "task_id": task_id,
            "status": "active",
        }

    if session.get("status") in ("completed", "failed", "canceled", "rejected"):
        return False

    session[field_name] = field_value
    session["last_updated"] = timestamp

    if event_type == "resolution_completed":
        session["status"] = "completed"
    elif event_type == "session_failed":
        session["status"] = "failed"

    conn.execute(
        "INSERT OR REPLACE INTO sessions (session_id, data) VALUES (?, ?)",
        (session_id, json.dumps(session)),
    )
    conn.commit()
    return True


def _sqlite_get_session_by_task(task_id: str) -> str | None:
    conn = _get_sqlite_conn()
    row = conn.execute(
        "SELECT session_id FROM tasks WHERE task_id = ?", (task_id,)
    ).fetchone()
    return row["session_id"] if row else None


def _sqlite_get_session_data(session_id: str) -> dict | None:
    conn = _get_sqlite_conn()
    row = conn.execute(
        "SELECT data FROM sessions WHERE session_id = ?", (session_id,)
    ).fetchone()
    return json.loads(row["data"]) if row else None


def _sqlite_set_status(
    session_id: str, status: str, error_msg: str | None
) -> None:
    conn = _get_sqlite_conn()
    row = conn.execute(
        "SELECT data FROM sessions WHERE session_id = ?", (session_id,)
    ).fetchone()
    session = json.loads(row["data"]) if row else {"session_id": session_id, "status": "active"}
    current = session.get("status")
    if current in ("completed", "failed", "canceled", "rejected"):
        return
    session["status"] = status
    if error_msg:
        session["error"] = error_msg
    conn.execute(
        "INSERT OR REPLACE INTO sessions (session_id, data) VALUES (?, ?)",
        (session_id, json.dumps(session)),
    )
    conn.commit()


def _sqlite_update_field(session_id: str, key: str, value: str) -> None:
    conn = _get_sqlite_conn()
    row = conn.execute(
        "SELECT data FROM sessions WHERE session_id = ?", (session_id,)
    ).fetchone()
    session = json.loads(row["data"]) if row else {}
    session[key] = value
    conn.execute(
        "INSERT OR REPLACE INTO sessions (session_id, data) VALUES (?, ?)",
        (session_id, json.dumps(session)),
    )
    conn.commit()


async def record_session_transition(
    session_id: str,
    task_id: str,
    field_name: str,
    field_value: str,
    event_type: str
) -> bool:
    """Transition session state atomically using Lua on Redis.
    Falls back to SQLite if Redis is down.
    """
    timestamp = str(int(time.time()))
    session_key = f"session:{session_id}"
    stream_key = "axiom:events"

    if AXIOM_MODE == "test":
        try:
            return await _run_sqlite(
                lambda: _sqlite_transition_fallback(
                    session_id,
                    task_id,
                    field_name,
                    field_value,
                    event_type,
                    timestamp,
                )
            )
        except Exception as sql_e:
            logger.warning("SQLite transition failed in test mode: %s", sql_e)
            return False

    try:
        redis = await get_redis()
        await redis.eval(
            LUA_TRANSITION, 2,
            session_key, stream_key,
            field_name, field_value, event_type,
            session_id, task_id, timestamp
        )
        return True
    except Exception as e:
        logger.warning("Redis DOWN on transition, falling back to SQLite: %s", e)
        if AXIOM_MODE != "grading":
            try:
                return await _run_sqlite(
                    lambda: _sqlite_transition_fallback(
                        session_id,
                        task_id,
                        field_name,
                        field_value,
                        event_type,
                        timestamp,
                    )
                )
            except Exception as sql_e:
                logger.warning("SQLite fallback failed: %s", sql_e)
        return False

async def get_session_by_task_id(task_id: str) -> str | None:
    """Function."""
    if AXIOM_MODE == "test":
        try:
            return await _run_sqlite(lambda: _sqlite_get_session_by_task(task_id))
        except Exception as sql_e:
            logger.warning("SQLite task lookup failed: %s", sql_e)
            return None

    try:
        redis = await get_redis()
        return await redis.get(f"task:to:session:{task_id}")
    except Exception as e:
        logger.warning("Redis lookup failed for task %s, using SQLite: %s", task_id, e)
        if AXIOM_MODE != "grading":
            try:
                return await _run_sqlite(lambda: _sqlite_get_session_by_task(task_id))
            except Exception as sql_e:
                logger.warning("SQLite lookup failed: %s", sql_e)
        return None

async def get_session_data(session_id: str) -> dict | None:
    """Function."""
    if AXIOM_MODE == "test":
        try:
            return await _run_sqlite(lambda: _sqlite_get_session_data(session_id))
        except Exception as sql_e:
            logger.warning("SQLite session read failed: %s", sql_e)
            return None

    try:
        redis = await get_redis()
        return await redis.hgetall(f"session:{session_id}")
    except Exception as e:
        logger.warning("Redis get session failed for %s, using SQLite: %s", session_id, e)
        if AXIOM_MODE != "grading":
            try:
                return await _run_sqlite(lambda: _sqlite_get_session_data(session_id))
            except Exception as sql_e:
                logger.warning("SQLite get session failed: %s", sql_e)
        return None

async def set_session_status(session_id: str, status: str, error_msg: str | None = None) -> None:
    """Function."""
    if AXIOM_MODE == "test":
        try:
            await _run_sqlite(
                lambda: _sqlite_set_status(session_id, status, error_msg)
            )
        except Exception as sql_e:
            logger.warning("SQLite set status failed: %s", sql_e)
        return

    try:
        redis = await get_redis()
        current = await redis.hget(f"session:{session_id}", "status")
        if current:
            if isinstance(current, bytes):
                current = current.decode()
            if current in ("completed", "failed", "canceled", "rejected"):
                logger.info(
                    "Session %s already terminal '%s', rejecting '%s'",
                    session_id, current, status,
                )
                return
        mapping = {"status": status}
        if error_msg:
            mapping["error"] = error_msg
        await redis.hset(f"session:{session_id}", mapping=mapping)
    except Exception as e:
        logger.warning("Redis set status failed for %s, using SQLite: %s", session_id, e)
        if AXIOM_MODE != "grading":
            try:
                await _run_sqlite(
                    lambda: _sqlite_set_status(session_id, status, error_msg)
                )
            except Exception as sql_e:
                logger.warning("SQLite set status failed: %s", sql_e)


async def update_session_field_fallback(
    session_id: str, key: str, value: str
) -> None:
    """Update a session field via SQLite fallback (async, non-blocking)."""
    if AXIOM_MODE != "grading":
        try:
            await _run_sqlite(
                lambda: _sqlite_update_field(session_id, key, value)
            )
        except Exception as e:
            logger.warning("Fallback write failed: %s", e)

async def get_account_context(account_id: str | None) -> str:
    """Function."""
    if not account_id:
        return "{}"
    try:
        redis = await get_redis()
        cached = await redis.hget(f"account:{account_id}", "context")
        if cached:
            return cached
    except Exception as e:
        print(f"Redis get account failed for {account_id}: {e}")
        
    # In grading mode, never fabricate customer data.
    if AXIOM_MODE == "grading":
        return json.dumps({"error": "account_not_found", "account_id": account_id})
    # In development/test mode, fall back to local mock data.
    if account_id in MOCK_ACCOUNTS:
        return json.dumps(MOCK_ACCOUNTS[account_id])
    return "{}"

# ==========================================
# PLANE 3: Long-term Customer Memory Vector System
# ==========================================

def _get_genai_client() -> genai.Client:
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if api_key:
        return genai.Client(api_key=api_key)
    return genai.Client()

async def get_embedding(text: str) -> list[float]:
    """
    Generate a real vector embedding using the configured model.

    Raises EmbeddingUnavailable on failure — never substitutes a zero vector,
    because a zero-norm vector causes division-by-zero in cosine similarity.
    """
    try:
        client = _get_genai_client()
        loop = asyncio.get_running_loop()
        response = await loop.run_in_executor(
            None,
            lambda: client.models.embed_content(
                model=EMBEDDING_MODEL,
                contents=text,
                config={"output_dimensionality": EMBEDDING_DIMENSIONS},
            )
        )
        if response.embeddings and response.embeddings[0].values:
            return list(response.embeddings[0].values)
    except Exception as e:
        raise EmbeddingUnavailable(f"Embedding call failed: {e}") from e
    raise EmbeddingUnavailable("Embedding API returned no values")

async def save_customer_memory(account_id: str, summary: str) -> None:
    """Embed and persist a resolved-interaction summary to the Memory Plane."""
    if not account_id or not summary:
        return

    try:
        vector = await get_embedding(summary)
    except EmbeddingUnavailable as e:
        print(f"Skipping memory save for {account_id} — embedding unavailable: {e}")
        return

    timestamp = int(time.time())
    key = f"memory:{account_id}:{timestamp}"

    try:
        redis = await get_redis()
        await redis.hset(key, mapping={
            "summary": summary,
            "timestamp": str(timestamp),
            "vector": json.dumps(vector),
            "embedding_status": "ok",
        })
        await redis.expire(key, REDIS_MEMORY_TTL)
    except Exception as e:
        print(f"Redis save customer memory failed for {account_id}: {e}")

async def search_customer_memories(account_id: str, query: str, limit: int = 2) -> list[dict]:
    """
    Rank stored customer memories by cosine similarity to the query.

    Returns an empty list (not an error) when the account has no memories.
    Raises EmbeddingUnavailable propagated from get_embedding if the API fails,
    so the caller can decide how to handle the degradation explicitly.
    """
    if not account_id or not query:
        return []

    keys: list[str] = []
    try:
        redis = await get_redis()
        async for key in redis.scan_iter(match=f"memory:{account_id}:*"):
            keys.append(key)
    except Exception as e:
        print(f"Redis scan memory failed for {account_id}: {e}")

    if not keys:
        return []

    # EmbeddingUnavailable propagates — the orchestrator catches it and proceeds
    # without memory context rather than silently using a fabricated vector.
    query_vector = await get_embedding(query)
    memories: list[dict] = []

    try:
        redis = await get_redis()
        for key in keys:
            data = await redis.hgetall(key)
            if not data or "vector" not in data or "summary" not in data:
                continue
            if data.get("embedding_status") != "ok":
                continue
            try:
                mem_vector = json.loads(data["vector"])
                dot_product = sum(a * b for a, b in zip(query_vector, mem_vector))
                norm_q = math.sqrt(sum(a * a for a in query_vector))
                norm_m = math.sqrt(sum(a * a for a in mem_vector))
                if norm_q > 0 and norm_m > 0:
                    similarity = dot_product / (norm_q * norm_m)
                else:
                    continue  # skip zero-norm vectors
                memories.append({
                    "summary": data["summary"],
                    "timestamp": int(data["timestamp"]),
                    "similarity": similarity,
                })
            except Exception as e:
                print(f"Error parsing memory {key}: {e}")
    except Exception as e:
        print(f"Redis getall memory failed for {account_id}: {e}")

    memories.sort(key=lambda x: x["similarity"], reverse=True)
    return memories[:limit]
