"""
Phalanx Gateway — AXIOM A2A Entry Point.

Defensive, zero-trust-inspired validation pipeline applied in strict order:

  Layer 0  Content-Length guard (before body read, fast-path 413)
  Layer 1  JSON-RPC 2.0 structural validation
  Layer 2  Unimplemented method stubs (push-notification config)
  Layer 3  tasks/get and tasks/cancel handled directly in the gateway
  Layer 4  Payload sanitization (zero-width chars, 512 KB cap)
  Layer 5  A2A semantic validation (TolerantMessage, TolerantPart)
  Layer 6  Message deduplication keyed by {peer_id}:{messageId}
  Layer 7  State machine shadow tracking + circuit breaker
  Layer 8  Terminal state guard (reject appends to completed/canceled tasks)
  Layer 9  Internal routing — synchronous (blocking) or fire-and-forget

Design decisions:
  - _ACTIVE_TASKS is keyed by taskId, not contextId/session, so cancel
    requests can target the exact running coroutine.
  - tasks/cancel propagates to the downstream worker via POST /cancel.
  - blocking=false returns a submitted Task immediately without awaiting.
  - Deduplication is scoped to peer_id so different callers can use the
    same messageId without interfering with each other.
"""
import asyncio
import json
import logging
import os
import time
import uuid
from typing import Any
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from dotenv import load_dotenv

from .validators.rpc_validator import validate_rpc_envelope, UNIMPLEMENTED_METHODS
from .validators.a2a_validator import TolerantMessage, sanitise_payload, TolerantPart
from .state_machine import TaskStateMachineTracker
from frontend.ag_ui_bridge import stream_axiom_response
from redis_fabric.fabric import (
    get_redis,
    get_session_by_task_id,
    get_session_data,
    set_session_status,
)
from redis_fabric.ids import derive_task_id
from config import AXIOM_MODE

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# In-memory fallbacks for when Redis is unavailable
# Dedup: {dedup_key: task_id}, Circuit: {agent_id: failure_count}
# ---------------------------------------------------------------------------
_DEDUP_CACHE: dict[str, str] = {}
_CIRCUIT_FAILURES: dict[str, int] = {}

# ---------------------------------------------------------------------------
# Cancellation Registry
# Keyed by taskId (not contextId) so tasks/cancel targets the exact coroutine.
# ---------------------------------------------------------------------------
_ACTIVE_TASKS: dict[str, asyncio.Task] = {}
_TERMINAL_TASK_IDS: set[str] = set()

load_dotenv()

# Single global httpx client — maintains connection pool and SSL sessions.
# Never create AsyncClient inside a handler (Bug Fix: connection exhaustion).
GATEWAY_CLIENT = httpx.AsyncClient(
    timeout=httpx.Timeout(connect=5.0, read=120.0, write=10.0, pool=5.0),
    limits=httpx.Limits(max_connections=50, max_keepalive_connections=20),
    headers={"User-Agent": "Axiom-Phalanx/1.0"},
)

port_personal = os.environ.get("PORT_PERSONAL", "8081")
port_cs       = os.environ.get("PORT_CS",       "8082")
port_research  = os.environ.get("PORT_RESEARCH",  "8083")


def _internal_agent_routes() -> dict[str, str]:
    """Read ports at call time so subprocess env overrides are respected."""
    return {
        "personal":         f"http://127.0.0.1:{os.environ.get('PORT_PERSONAL', port_personal)}",
        "customer_service": f"http://127.0.0.1:{os.environ.get('PORT_CS', port_cs)}",
        "research":         f"http://127.0.0.1:{os.environ.get('PORT_RESEARCH', port_research)}",
    }


tracker: TaskStateMachineTracker | None = None


async def seed_mock_data(redis_client) -> None:
    """Seed sample customer account data and policy documents into Redis at startup."""
    # ACC-12345 — Premium customer, order queries
    acc_12345 = {
        "account_id":     "ACC-12345",
        "name":           "Alice Johnson",
        "tier":           "premium",
        "lifetime_value": 2450.00,
        "email":          "alice.johnson@example.com",
        "recent_orders":  [
            {
                "order_id": "ORD-99887",
                "date":     "2026-06-05",
                "total":    120.50,
                "status":   "delivered",
                "items":    ["Wireless Headphones", "USB-C Cable"],
            },
            {
                "order_id": "ORD-55443",
                "date":     "2026-05-12",
                "total":    89.99,
                "status":   "delivered",
                "items":    ["Smart Water Bottle"],
            },
        ],
    }
    await redis_client.hset("account:ACC-12345", "context", json.dumps(acc_12345))

    # ACC-67890 — Standard customer, billing queries
    acc_67890 = {
        "account_id":     "ACC-67890",
        "name":           "Bob Smith",
        "tier":           "standard",
        "lifetime_value": 350.00,
        "email":          "bob.smith@example.com",
        "recent_orders":  [
            {
                "order_id": "ORD-11223",
                "date":     "2026-06-10",
                "total":    45.00,
                "status":   "processing",
                "items":    ["Ergonomic Mouse"],
            },
        ],
    }
    await redis_client.hset("account:ACC-67890", "context", json.dumps(acc_67890))

    # Policy documents
    policies = {
        "return_policy":   (
            "Standard 30-day return policy. Items must be in original packaging "
            "and unused. Premium customers get free returns."
        ),
        "refund_policy":   (
            "Refunds are processed within 5-7 business days of receiving the "
            "returned item. Billing disputes must be reported within 60 days."
        ),
        "shipping_policy": (
            "Standard shipping takes 3-5 business days. Express shipping takes "
            "1-2 business days. Premium customers get free express shipping."
        ),
        "warranty_policy": (
            "All products have a 1-year limited warranty covering manufacturer "
            "defects. Replacement products are shipped free of charge."
        ),
    }
    for name, content in policies.items():
        await redis_client.hset(f"policy:{name}", "content", content)
        await redis_client.hset(
            f"policy:{name}", "context",
            json.dumps({"policy_name": name, "content": content})
        )


@asynccontextmanager
async def lifespan(app_instance):
    """Startup: connect Redis, seed mock data, initialise tracker. Shutdown: close client."""
    global tracker
    redis_client = await get_redis()
    # Always create the tracker — it wraps all Redis calls in try/except
    # and degrades to in-memory counters when Redis is unavailable.
    tracker = TaskStateMachineTracker(redis_client)
    if os.environ.get("AXIOM_MODE", "development") != "test":
        try:
            await seed_mock_data(redis_client)
            logger.info("Mock accounts and policy documents seeded in Redis.")
        except Exception as exc:
            logger.warning(
                "Redis unavailable at startup (%s); using in-memory fallback.", exc
            )

    yield

    await GATEWAY_CLIENT.aclose()


app = FastAPI(lifespan=lifespan)


def _extract_agent_logical_id(body: dict, request: Request) -> str:
    """
    Parse a stable logical peer ID from the request.

    Preference order:
      1. params.message.metadata.agentId  — explicitly set by well-behaved peers
      2. SHA-256[:16] of host:port        — fingerprint of anonymous callers

    Never uses raw IP alone — port is included so multiple processes on the
    same host get distinct circuit-breaker buckets.
    """
    try:
        agent_id = (
            body.get("params", {})
                .get("message", {})
                .get("metadata", {})
                .get("agentId", "")
        )
        if agent_id:
            return str(agent_id)
    except (AttributeError, TypeError):
        pass

    client = request.client
    if client:
        import hashlib
        return hashlib.sha256(f"{client.host}:{client.port}".encode()).hexdigest()[:16]
    return "unknown"


async def _register_message_dedup(peer_id: str, message_id: str, task_id: str) -> None:
    """Register messageId → taskId before dispatch so in-flight retries dedup."""
    dedup_key = f"dedup:{peer_id}:{message_id}"
    _DEDUP_CACHE[dedup_key] = task_id
    if AXIOM_MODE == "test":
        return
    try:
        rc = await get_redis()
        await rc.setex(dedup_key, 86400, task_id)
    except Exception:
        pass  # in-memory cache is authoritative for same-process retries


async def _reject_terminal_append(
    task_id: str | None,
    rpc_id: str | int | None,
) -> JSONResponse | None:
    """Layer 8: reject message/send appends to terminal tasks (SQLite-first)."""
    if not task_id:
        return None
    if task_id in _TERMINAL_TASK_IDS:
        return JSONResponse(content={
            "jsonrpc": "2.0",
            "error":   {
                "code":    -32600,
                "message": (
                    f"Task {task_id} is in terminal state "
                    f"'canceled'. Start a new task."
                ),
            },
            "id": rpc_id,
        })
    try:
        existing_session = await get_session_by_task_id(task_id)
        if existing_session:
            sess = await get_session_data(existing_session)
            if sess:
                current_status = sess.get("status", "")
                if current_status in ("completed", "failed", "canceled", "rejected"):
                    _TERMINAL_TASK_IDS.add(task_id)
                    return JSONResponse(content={
                        "jsonrpc": "2.0",
                        "error":   {
                            "code":    -32600,
                            "message": (
                                f"Task {task_id} is in terminal state "
                                f"'{current_status}'. Start a new task."
                            ),
                        },
                        "id": rpc_id,
                    })
    except Exception as exc:
        logger.warning("Layer 8 terminal guard failed for %s: %s", task_id, exc)
    return None


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    """Liveness probe for integration tests and deploy orchestration."""
    return {"status": "ok", "service": "phalanx-gateway"}


@app.get("/.well-known/agent-card.json")
async def get_agent_card():
    """Serve the A2A v0.3 identity card (agent discovery)."""
    from agent_card import AXIOM_AGENT_CARD
    return AXIOM_AGENT_CARD


@app.get("/sse/{session_id}")
async def sse_stream(session_id: str):
    """
    Serve AG-UI v1.0 event stream for a session.

    Connects to the CopilotKit frontend via SSE. Events sourced from the
    Redis axiom:events stream (Plane 2) and translated by ag_ui_bridge.
    """
    return StreamingResponse(
        stream_axiom_response(session_id),
        media_type="text/event-stream",
    )


@app.post("/a2a/{target_agent}")
async def a2a_inbound(target_agent: str, request: Request) -> Response:
    """
    Handle all inbound A2A v0.3 requests.

    Applies the 9-layer validation pipeline (see module docstring) before
    routing to an internal worker. Returns JSON-RPC 2.0 responses throughout.
    """
    # ── Layer 0: Content-Length guard ────────────────────────────────────────
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > 512 * 1024:
        return JSONResponse(
            status_code=413,
            content={
                "jsonrpc": "2.0",
                "error":   {"code": -32600, "message": "Payload too large"},
                "id":      None,
            },
        )

    try:
        body = await request.json()
    except Exception:
        return JSONResponse(
            status_code=400,
            content={
                "jsonrpc": "2.0",
                "error":   {"code": -32700, "message": "Parse error"},
                "id":      None,
            },
        )

    # ── Layer 1: JSON-RPC 2.0 structural validation ───────────────────────────
    envelope = validate_rpc_envelope(body)
    if envelope is None:
        return JSONResponse(content={
            "jsonrpc": "2.0",
            "error":   {"code": -32600, "message": "Invalid Request"},
            "id":      body.get("id"),
        })

    # ── Layer 3a: tasks/get ───────────────────────────────────────────────────
    if envelope.method == "tasks/get":
        task_id_raw = body.get("params", {}).get("id") or envelope.id
        if not task_id_raw:
            return JSONResponse(content={
                "jsonrpc": "2.0",
                "error":   {"code": -32602, "message": "Missing task ID parameter"},
                "id":      envelope.id,
            })

        task_id    = str(task_id_raw)
        session_id = await get_session_by_task_id(task_id)
        if not session_id:
            return JSONResponse(content={
                "jsonrpc": "2.0",
                "error":   {"code": -32602, "message": f"Task {task_id} not found"},
                "id":      envelope.id,
            })

        session_data = await get_session_data(session_id)
        if not session_data:
            return JSONResponse(content={
                "jsonrpc": "2.0",
                "error":   {"code": -32602, "message": f"Session for task {task_id} not found"},
                "id":      envelope.id,
            })

        status_state = session_data.get("status", "working")
        a2a_state = status_state if status_state in (
            "completed", "failed", "canceled", "rejected", "working", "submitted"
        ) else "working"

        result: dict[str, Any] = {
            "id":        task_id,
            "contextId": session_id,
            "kind":      "task",
            "status":    {"state": a2a_state},
        }

        if a2a_state == "completed":
            resolution = session_data.get("resolution_payload")
            try:
                res_dict = json.loads(resolution) if resolution else {}
            except Exception:
                res_dict = {"resolution_summary": resolution or ""}
            
            public_dict = {
                "resolution_status": res_dict.get("resolution_status", "resolved"),
                "resolution_summary": res_dict.get("resolution_summary", ""),
                "follow_up_actions": res_dict.get("follow_up_actions", []),
            }
            
            result["artifacts"] = [
                {
                    "artifactId": "resolution_artifact",
                    "parts": [{"kind": "data", "data": public_dict}],
                }
            ]
        elif a2a_state == "failed":
            result["error"] = {
                "code":    -32000,
                "message": session_data.get("error", "Task execution failed"),
            }

        return JSONResponse(content={"jsonrpc": "2.0", "result": result, "id": envelope.id})

    # ── Layer 3b: tasks/cancel ────────────────────────────────────────────────
    if envelope.method == "tasks/cancel":
        task_id_raw = body.get("params", {}).get("id") or envelope.id
        if not task_id_raw:
            return JSONResponse(content={
                "jsonrpc": "2.0",
                "error":   {"code": -32602, "message": "Missing task ID parameter"},
                "id":      envelope.id,
            })

        task_id    = str(task_id_raw)
        session_id = await get_session_by_task_id(task_id)
        if not session_id:
            return JSONResponse(content={
                "jsonrpc": "2.0",
                "error":   {"code": -32001, "message": f"Task {task_id} not found"},
                "id":      envelope.id,
            })

        # 1. Cancel the local asyncio Task (if still running in this gateway process).
        active_task = _ACTIVE_TASKS.pop(task_id, None)
        if active_task and not active_task.done():
            active_task.cancel()
            logger.info("Cancelled local asyncio task for taskId=%s", task_id)

        # 2. Propagate cancellation to the owning downstream worker.
        target_url = _internal_agent_routes().get(target_agent)
        if target_url:
            try:
                await GATEWAY_CLIENT.post(
                    f"{target_url}/cancel",
                    json={"taskId": task_id},
                    timeout=5.0,
                )
                logger.info("Propagated cancel to %s for taskId=%s", target_url, task_id)
            except Exception as exc:
                logger.warning("Could not reach %s/cancel: %s", target_url, exc)

        # 3. Mark session canceled in Redis/SQLite and record terminal taskId.
        await set_session_status(session_id, "canceled")
        _TERMINAL_TASK_IDS.add(task_id)

        # 4. Write event to axiom:events stream.
        try:
            rc = await get_redis()
            await rc.xadd(
                "axiom:events",
                {
                    "event":      "task_canceled",
                    "session_id": session_id,
                    "task_id":    task_id,
                    "timestamp":  str(int(time.time())),
                },
                maxlen=10000,
                approximate=True,
            )
        except Exception:
            pass

        return JSONResponse(content={
            "jsonrpc": "2.0",
            "result":  {
                "id":        task_id,
                "contextId": session_id,
                "kind":      "task",
                "status":    {"state": "canceled"},
            },
            "id": envelope.id,
        })

    # ── Layer 2: Unimplemented method stubs ───────────────────────────────────
    if envelope.method in UNIMPLEMENTED_METHODS:
        return JSONResponse(content={
            "jsonrpc": "2.0",
            "error":   {
                "code":    -32004,
                "message": f"Method '{envelope.method}' is not supported by this agent",
            },
            "id": envelope.id,
        })

    # ── Layer 4: Payload sanitisation ─────────────────────────────────────────
    try:
        clean_body, warnings = sanitise_payload(body)
    except ValueError as exc:
        return JSONResponse(content={
            "jsonrpc": "2.0",
            "error":   {"code": -32602, "message": str(exc)},
            "id":      envelope.id,
        })

    # ── Layer 8 (early): Terminal state guard before Redis dedup/state machine ─
    if envelope.method in ("message/send", "message/stream"):
        terminal_reject = await _reject_terminal_append(
            (clean_body.get("params") or {}).get("taskId"),
            envelope.id,
        )
        if terminal_reject is not None:
            return terminal_reject

    # ── Layer 5: A2A semantic validation ──────────────────────────────────────
    if envelope.method in ("message/send", "message/stream"):
        params       = clean_body.get("params", {})
        message_dict = params.get("message", {})

        # Extract a stable peer ID for dedup scoping
        peer_id    = _extract_agent_logical_id(clean_body, request)
        message_id = message_dict.get("messageId", "")

        # ── Layer 6: Deduplication scoped to peer_id:messageId ────────────────
        if message_id:
            dedup_key = f"dedup:{peer_id}:{message_id}"
            dedup_task = _DEDUP_CACHE.get(dedup_key)
            if dedup_task is None and AXIOM_MODE != "test":
                try:
                    rc = await get_redis()
                    dedup_task = await rc.get(dedup_key)
                except Exception:
                    dedup_task = _DEDUP_CACHE.get(dedup_key)

            if dedup_task:
                logger.info(
                    "Dedup hit peer=%s messageId=%s -> taskId=%s",
                    peer_id, message_id, dedup_task,
                )
                shadow_state = "working"
                try:
                    rc = await get_redis()
                    shadow = await rc.hgetall(f"shadow:task:{dedup_task}")
                    if shadow:
                        state_val = shadow.get("state", "working")
                        shadow_state = state_val.decode() if isinstance(state_val, bytes) else state_val
                except Exception:
                    pass
                return JSONResponse(content={
                    "jsonrpc": "2.0",
                    "result":  {
                        "id":     str(dedup_task),
                        "kind":   "task",
                        "status": {"state": shadow_state},
                    },
                    "id": envelope.id,
                })

        try:
            TolerantMessage.model_validate(message_dict)
        except Exception as exc:
            return JSONResponse(content={
                "jsonrpc": "2.0",
                "error":   {"code": -32602, "message": f"Invalid A2A message: {exc}"},
                "id":      envelope.id,
            })

        # Normalize parts: accept kind or type inbound, emit only kind outbound
        if "parts" in message_dict:
            new_parts = []
            for part in message_dict.get("parts", []):
                try:
                    tp = TolerantPart.model_validate(part)
                    new_part: dict[str, Any] = {"kind": tp.normalized_kind}
                    if tp.text is not None:
                        new_part["text"] = tp.text
                    if tp.data is not None:
                        new_part["data"] = tp.data
                    new_parts.append(new_part)
                except Exception:
                    new_parts.append(part)
            message_dict["parts"]          = new_parts
            clean_body["params"]["message"] = message_dict

    # ── Layer 7: State machine + circuit breaker ───────────────────────────────
    agent_logical_id = _extract_agent_logical_id(clean_body, request)
    task_id_param    = (clean_body.get("params") or {}).get("taskId")
    if task_id_param and AXIOM_MODE != "test":
        claimed_state = (clean_body.get("params") or {}).get("status", {}).get("state")
        if claimed_state and tracker is not None:
            if await tracker.is_agent_degraded(agent_logical_id):
                return JSONResponse(content={
                    "jsonrpc": "2.0",
                    "error":   {"code": -32000, "message": "Remote agent circuit open"},
                    "id":      envelope.id,
                })
            valid, err = await tracker.validate_incoming_state(task_id_param, claimed_state)
            if not valid:
                await tracker.record_agent_failure(agent_logical_id)
                return JSONResponse(content={
                    "jsonrpc": "2.0",
                    "result":  {"status": {"state": "failed"}, "error": err},
                    "id":      envelope.id,
                })

    # ── Layer 8 (late): belt-and-suspenders terminal guard ───────────────────
    if task_id_param:
        terminal_reject = await _reject_terminal_append(task_id_param, envelope.id)
        if terminal_reject is not None:
            return terminal_reject

    # ── Layer 9: Route to internal agent ──────────────────────────────────────
    target_url = _internal_agent_routes().get(target_agent)
    if not target_url:
        return JSONResponse(
            status_code=404,
            content={"error": f"Unknown agent route: '{target_agent}'"},
        )

    if envelope.method == "message/stream":
        return JSONResponse(content={
            "jsonrpc": "2.0",
            "error":   {
                "code":    -32004,
                "message": "Streaming is not supported. Use message/send and poll tasks/get.",
            },
            "id": envelope.id,
        })

    correlation_id = str(uuid.uuid4())
    headers = {
        "X-Correlation-ID": correlation_id,
        "Content-Type":     "application/json",
    }

    params = clean_body.get("params") or {}
    peer_id_route = _extract_agent_logical_id(clean_body, request)
    msg_id_route = (params.get("message") or {}).get("messageId", "")

    new_task_id = derive_task_id(
        explicit_task_id=params.get("taskId"),
        message_id=msg_id_route or None,
        rpc_id=envelope.id,
        peer_id=peer_id_route,
    )

    # Ensure downstream workers receive the generated taskId
    if "params" not in clean_body:
        clean_body["params"] = {}
    clean_body["params"]["taskId"] = new_task_id

    # Register dedup BEFORE dispatch (blocking and non-blocking) so retries
    # during in-flight execution return the same taskId.
    if envelope.method == "message/send" and msg_id_route:
        await _register_message_dedup(peer_id_route, msg_id_route, new_task_id)

    # Check if the caller wants non-blocking dispatch.
    configuration = params.get("configuration") or {}
    blocking: bool = configuration.get("blocking", True)

    async def _run_internal():
        return await GATEWAY_CLIENT.post(
            f"{target_url}/run", json=clean_body, headers=headers
        )

    task = asyncio.create_task(_run_internal())
    _ACTIVE_TASKS[new_task_id] = task

    if not blocking:
        # Non-blocking: return submitted Task immediately; processing continues.
        # The caller must poll tasks/get to observe completion.

        # Seed a minimal session record immediately so tasks/cancel and Layer 8
        # can find this task without waiting for the worker to seed Redis.
        try:
            from redis_fabric.fabric import seed_session
            msg_text = (
                (clean_body.get("params") or {})
                .get("message", {})
                .get("parts", [{}])[0]
                .get("text", "")
            )
            await seed_session(
                msg_text,
                session_id=None,
                task_id=new_task_id,
                message_id=msg_id_route or None,
                peer_id=peer_id_route,
            )
        except Exception:
            pass

        return JSONResponse(content={
            "jsonrpc": "2.0",
            "result":  {
                "id":     new_task_id,
                "kind":   "task",
                "status": {"state": "submitted"},
            },
            "id": envelope.id,
        })

    # Blocking (default): await the task coroutine.
    try:
        resp = await task
    except asyncio.CancelledError:
        return JSONResponse(content={
            "jsonrpc": "2.0",
            "result":  {
                "id":     new_task_id,
                "kind":   "task",
                "status": {"state": "canceled"},
            },
            "id": envelope.id,
        })
    finally:
        _ACTIVE_TASKS.pop(new_task_id, None)

    return Response(
        content=resp.content,
        media_type="application/json",
        status_code=resp.status_code,
    )
