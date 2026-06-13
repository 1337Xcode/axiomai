"""
Background Sweeper — Stalled Message Recovery.

Runs as a background asyncio task inside each agent worker process.
Detects messages stuck in the Redis Stream PEL (Pending Entry List)
for longer than 5 seconds using XAUTOCLAIM.

[FIXED BUG 8] XAUTOCLAIM already claims the message to the sweeper.
Do NOT call XADD — that creates a duplicate that gets claimed again on
the next sweep cycle, producing an infinite loop. Process in place, ACK.

Usage:
    asyncio.create_task(run_sweeper())
"""
import asyncio
import logging

logger = logging.getLogger(__name__)

# Minimum time a message must be idle in the PEL before the sweeper
# reclaims it (milliseconds). 5000ms = 5 seconds.
_MIN_IDLE_MS = 5000

# How often the sweeper wakes up to check the PEL (seconds).
_SWEEP_INTERVAL_S = 10

# Maximum number of stalled messages to reclaim per sweep cycle.
_SWEEP_COUNT = 10


async def _process_recovered_message(redis, fields: dict) -> None:
    """
    Handle a recovered stalled message.

    Updates the session status to 'stalled' (not terminal — 'failed' would
    block future writes if the session somehow recovers) and logs the event.
    Uses HSET directly, NOT LUA_TRANSITION — the Lua script enforces terminal
    state guards which would reject writes to completed sessions.
    """
    session_id = fields.get("session_id", "unknown")
    event_type = fields.get("event", "unknown")
    task_id = fields.get("task_id", "unknown")

    logger.warning(
        "Sweeper: recovered stalled message — session=%s event=%s task=%s",
        session_id, event_type, task_id,
    )

    if session_id != "unknown":
        try:
            await redis.hset(
                f"session:{session_id}",
                mapping={
                    "status": "failed",
                    "stall_reason": f"recovered_stalled_{event_type}",
                },
            )
            # Emit a stream event so the AG-UI bridge can emit RUN_ERROR
            import time
            await redis.xadd(
                "axiom:events",
                {
                    "event": "session_stalled",
                    "session_id": session_id,
                    "task_id": task_id,
                    "stall_reason": f"recovered_stalled_{event_type}",
                    "timestamp": str(int(time.time())),
                },
                maxlen=10000,
                approximate=True,
            )
        except Exception as exc:
            logger.error("Sweeper: failed to update session %s: %s", session_id, exc)


async def pending_entry_sweeper(redis, stream: str, group: str) -> None:
    """
    Background task. Reclaims messages stuck in the PEL for > 5 seconds.

    [FIXED BUG 8] XAUTOCLAIM claims the message — do NOT call XADD.
    Process in place, then XACK.
    """
    while True:
        await asyncio.sleep(_SWEEP_INTERVAL_S)
        try:
            # XAUTOCLAIM: atomically reassigns idle PEL entries to the sweeper.
            # Returns (next_start_id, [(msg_id, fields), ...], [deleted_ids])
            result = await redis.xautoclaim(
                name=stream,
                groupname=group,
                consumername="sweeper",
                min_idle_time=_MIN_IDLE_MS,
                start_id="0-0",
                count=_SWEEP_COUNT,
            )

            if not result or not result[1]:
                continue

            for msg_id, fields in result[1]:
                try:
                    # [FIXED BUG 8] Process the claimed message directly.
                    # Do NOT call redis.xadd() — that creates a new duplicate.
                    await _process_recovered_message(redis, fields)
                    await redis.xack(stream, group, msg_id)
                    logger.info("Sweeper: ACKed stalled message %s", msg_id)
                except Exception as exc:
                    logger.error(
                        "Sweeper: failed to process message %s: %s", msg_id, exc
                    )

        except Exception as exc:
            logger.error("Sweeper error (will retry in %ds): %s", _SWEEP_INTERVAL_S, exc)


async def run_sweeper(stream: str = "axiom:events", group: str = "cs_group") -> None:
    """
    Entry point for the background sweeper task.

    Initialises the Redis consumer group if it does not yet exist,
    then runs the sweep loop indefinitely.

    Call as:  asyncio.create_task(run_sweeper())
    """
    try:
        from redis_fabric.fabric import get_redis
        redis = await get_redis()

        # Create consumer group (idempotent — MKSTREAM creates stream if absent)
        try:
            await redis.xgroup_create(stream, group, id="0", mkstream=True)
            logger.info("Sweeper: created consumer group %s on %s", group, stream)
        except Exception:
            # BUSYGROUP error is expected when the group already exists — ignore it.
            pass

        await pending_entry_sweeper(redis, stream, group)

    except asyncio.CancelledError:
        logger.info("Sweeper task cancelled.")
        raise
    except Exception as exc:
        logger.error("Sweeper failed to start: %s", exc)
