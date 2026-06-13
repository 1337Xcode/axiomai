"""
Timeout Manager — Ghost Agent Detection.

When a third-party A2A agent accepts a task (HTTP 200) but never delivers
a completion event, the orchestrator must detect the ghost and degrade
gracefully rather than hanging indefinitely.

This module polls both the Redis shadow state and the remote agent's
tasks/get endpoint until one of them reports a terminal state, or the
deadline is reached.

While this loop runs, the AG-UI SSE heartbeat runs concurrently (separate
asyncio coroutine), so the frontend remains live and does not freeze.

Correction: uses "canceled" (A2A v0.3.0 spelling), not "cancelled".
"""
import asyncio
import logging
import time

from gateway.main import GATEWAY_CLIENT
from redis_fabric.fabric import get_redis

logger = logging.getLogger(__name__)

# A2A v0.3.0 terminal states (lowercase)
_TERMINAL_STATES = frozenset({"completed", "failed", "canceled", "rejected"})


async def await_task_completion_with_timeout(
    task_id: str,
    remote_agent_url: str,
    timeout_seconds: int = 30,
) -> dict | None:
    """
    Poll shadow state and remote agent for task completion.

    Returns the result dict on completion, or None if the deadline is
    reached (ghost confirmed).

    Parameters
    ----------
    task_id:
        The A2A task ID to monitor.
    remote_agent_url:
        Full URL to the remote agent's A2A endpoint (e.g.
        "https://peer.example.com/a2a/agent"). tasks/get will be POSTed here.
    timeout_seconds:
        Maximum seconds to wait before declaring the remote agent a ghost.
        Default 30s per the design spec.
    """
    deadline = time.time() + timeout_seconds
    poll_interval = 2.0

    # Emit a STATE_DELTA at the start of the wait so the frontend shows
    # progress rather than a spinner for up to 30 seconds.
    try:
        redis = await get_redis()
        await redis.xadd(
            "axiom:events",
            {
                "event": "external_task_polling",
                "task_id": task_id,
                "remote_url": remote_agent_url,
                "timestamp": str(int(time.time())),
            },
            maxlen=10000,
            approximate=True,
        )
    except Exception:
        pass

    while time.time() < deadline:
        # 1. Check shadow state first (fast, local Redis)
        try:
            redis = await get_redis()
            shadow = await redis.hgetall(f"shadow:task:{task_id}")
            state = shadow.get("state", "")
            if isinstance(state, bytes):
                state = state.decode()
            if state in _TERMINAL_STATES:
                logger.info("Ghost check: task %s reached terminal state %s via shadow", task_id, state)
                return {"state": state, "task_id": task_id}
        except Exception as exc:
            logger.warning("Shadow state lookup failed for %s: %s", task_id, exc)

        # 2. Poll the remote agent directly
        try:
            resp = await GATEWAY_CLIENT.post(
                remote_agent_url,
                json={
                    "jsonrpc": "2.0",
                    "method": "tasks/get",
                    "id": task_id,
                    "params": {"id": task_id},
                },
                timeout=5.0,
            )
            if resp.status_code == 200:
                result = resp.json().get("result", {})
                remote_state = result.get("status", {}).get("state", "")
                if remote_state in _TERMINAL_STATES:
                    logger.info(
                        "Ghost check: task %s completed remotely with state %s",
                        task_id, remote_state,
                    )
                    return result
        except Exception as exc:
            logger.debug("Poll request failed for %s: %s (continuing)", task_id, exc)

        await asyncio.sleep(poll_interval)

    # Ghost confirmed — mark the shadow task as failed
    logger.warning("Ghost timeout: task %s did not complete within %ds", task_id, timeout_seconds)
    try:
        redis = await get_redis()
        await redis.hset(f"shadow:task:{task_id}", "state", "failed")
        await redis.xadd(
            "axiom:events",
            {
                "event": "ghost_timeout",
                "task_id": task_id,
                "timestamp": str(int(time.time())),
            },
            maxlen=10000,
            approximate=True,
        )
    except Exception as exc:
        logger.warning("Failed to mark ghost task %s as failed: %s", task_id, exc)

    return None
