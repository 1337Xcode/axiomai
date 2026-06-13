"""
Task State Machine Shadow Tracker and Circuit Breaker.

Tracks task state transitions in a Redis shadow store to enforce A2A protocol
correctness. Also implements a short-window rate-limit style circuit breaker
(not a 30-minute spoofable ban).

Idempotency rules:
  - Repeated terminal state (completed->completed) is silently accepted.
  - Repeated in-progress state (working->working) is accepted as an observation.
  - Genuinely invalid transitions are rejected and logged.

Redis resilience:
  All Redis operations are wrapped in try/except. If Redis is unavailable,
  the tracker degrades gracefully:
    - is_agent_degraded   → returns False (open gate, no false positives)
    - record_agent_failure → increments in-memory counter only
    - validate_incoming_state → returns (True, "") — unknown task, tolerated
    - record_outbound_task → silently skipped
"""
import logging

import redis.asyncio as aioredis
from enum import Enum

from config import CIRCUIT_BAN_SECONDS, CIRCUIT_FAILURE_THRESHOLD

logger = logging.getLogger(__name__)

# In-process fallback for circuit breaker when Redis is unavailable.
_CIRCUIT_FAILURES_LOCAL: dict[str, int] = {}


class TaskState(str, Enum):
    """Valid A2A v0.3.0 task states (lowercase)."""

    SUBMITTED = "submitted"
    WORKING = "working"
    INPUT_REQUIRED = "input-required"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"
    AUTH_REQUIRED = "auth-required"
    REJECTED = "rejected"


TERMINAL_STATES: frozenset[TaskState] = frozenset({
    TaskState.COMPLETED,
    TaskState.FAILED,
    TaskState.CANCELED,
    TaskState.REJECTED,
})

# A2A v0.3.0 valid forward transitions.
VALID_TRANSITIONS: dict[TaskState, set[TaskState]] = {
    TaskState.SUBMITTED: {
        TaskState.WORKING,
        TaskState.FAILED,
        TaskState.CANCELED,
        TaskState.AUTH_REQUIRED,
        TaskState.REJECTED,
    },
    TaskState.WORKING: {
        TaskState.COMPLETED,
        TaskState.FAILED,
        TaskState.INPUT_REQUIRED,
        TaskState.CANCELED,
    },
    TaskState.INPUT_REQUIRED: {
        TaskState.WORKING,
        TaskState.CANCELED,
        TaskState.FAILED,
    },
    TaskState.AUTH_REQUIRED: {TaskState.SUBMITTED, TaskState.FAILED},
    TaskState.COMPLETED: set(),   # terminal
    TaskState.FAILED: set(),      # terminal
    TaskState.CANCELED: set(),    # terminal
    TaskState.REJECTED: set(),    # terminal
}


class TaskStateMachineTracker:
    """
    Shadow-tracks A2A task states in Redis to enforce protocol correctness.

    Idempotent for repeated terminal events (e.g. at-least-once delivery).
    Uses a configurable short-window circuit breaker rather than a fixed
    30-minute ban, making it resistant to spoofed agentId attacks.

    All Redis calls are wrapped in try/except — the tracker degrades
    gracefully to in-memory or no-op fallbacks when Redis is unreachable.
    """

    def __init__(self, redis: aioredis.Redis) -> None:
        """Initialize with a live Redis client."""
        self._redis = redis

    async def record_outbound_task(self, task_id: str, remote_agent_id: str) -> None:
        """Register a newly delegated outbound task at the SUBMITTED state."""
        try:
            await self._redis.hset(
                f"shadow:task:{task_id}",
                mapping={"state": TaskState.SUBMITTED.value, "agent_id": remote_agent_id},
            )
            await self._redis.expire(f"shadow:task:{task_id}", 3600)
        except Exception as exc:
            logger.debug("record_outbound_task Redis unavailable (%s); skipping shadow write.", exc)

    async def validate_incoming_state(
        self, task_id: str, claimed_state: str
    ) -> tuple[bool, str]:
        """
        Validate an inbound state claim against the shadow tracker.

        Returns (True, "") if the transition is valid or idempotent.
        Returns (False, reason) for genuinely invalid transitions.
        """
        try:
            raw = await self._redis.hgetall(f"shadow:task:{task_id}")
        except Exception as exc:
            logger.debug("validate_incoming_state Redis unavailable (%s); tolerating unknown task.", exc)
            return True, ""  # Redis down — tolerate, no tracking data

        if not raw:
            return True, ""  # Unknown task — tolerate, no tracking data

        current = TaskState(raw["state"])
        try:
            incoming = TaskState(claimed_state)
        except ValueError:
            return False, f"Unknown task state value: {claimed_state}"

        # Idempotent: same state reported again (at-least-once delivery / retry).
        if incoming == current:
            logger.debug("Idempotent state report for task %s: %s", task_id, current)
            return True, "idempotent"

        # Idempotent: terminal state notified again (polling/replay).
        if current in TERMINAL_STATES and incoming in TERMINAL_STATES:
            logger.debug(
                "Duplicate terminal event for task %s: %s -> %s (accepted)",
                task_id, current, incoming,
            )
            return True, "idempotent_terminal"

        if incoming not in VALID_TRANSITIONS.get(current, set()):
            return (
                False,
                f"Invalid transition {current.value} -> {incoming.value} for task {task_id}",
            )

        try:
            await self._redis.hset(f"shadow:task:{task_id}", "state", incoming.value)
        except Exception as exc:
            logger.debug("validate_incoming_state Redis write failed (%s); transition accepted anyway.", exc)
        return True, ""

    async def is_agent_degraded(self, agent_logical_id: str) -> bool:
        """
        Return True if the agent has tripped the short-window circuit breaker.

        The ban window is controlled by CIRCUIT_BAN_SECONDS (default 2 min),
        deliberately short to avoid long-running bans triggered by spoofed IDs.

        Falls back to in-process counter when Redis is unavailable.
        """
        try:
            count = await self._redis.get(f"circuit:{agent_logical_id}:failures")
            return int(count or 0) >= CIRCUIT_FAILURE_THRESHOLD
        except Exception:
            # Redis down — use in-memory fallback
            return _CIRCUIT_FAILURES_LOCAL.get(agent_logical_id, 0) >= CIRCUIT_FAILURE_THRESHOLD

    async def record_agent_failure(self, agent_logical_id: str) -> None:
        """
        Increment the failure counter for an agent with a short TTL.

        Counter resets automatically after CIRCUIT_BAN_SECONDS.
        Also increments the in-process fallback counter.
        """
        _CIRCUIT_FAILURES_LOCAL[agent_logical_id] = (
            _CIRCUIT_FAILURES_LOCAL.get(agent_logical_id, 0) + 1
        )
        try:
            pipe = self._redis.pipeline()
            pipe.incr(f"circuit:{agent_logical_id}:failures")
            pipe.expire(f"circuit:{agent_logical_id}:failures", CIRCUIT_BAN_SECONDS)
            await pipe.execute()
        except Exception as exc:
            logger.debug("record_agent_failure Redis unavailable (%s); using in-memory counter.", exc)
        logger.warning(
            "Circuit breaker: failure recorded for agent %s", agent_logical_id
        )
