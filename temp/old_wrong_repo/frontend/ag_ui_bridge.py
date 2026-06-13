"""
AG-UI SSE Bridge.

Streams AG-UI protocol events from the Redis event plane to the CopilotKit frontend.

AG-UI event compliance notes:
- RUN_STARTED and RUN_FINISHED both require threadId (conversation) AND runId (execution).
- TEXT_MESSAGE_START must include role="assistant" and a stable messageId.
- All event type names are SCREAMING_SNAKE_CASE; CopilotKit's router is case-sensitive.
- Heartbeat comments keep SSE connections alive through NAT timeouts (15s interval).
"""

import json
import time
import uuid

from config import SSE_HEARTBEAT_INTERVAL, SSE_MAX_WAIT


def build_ag_ui_event(event_type: str, data: dict) -> str:
    """
    Serialize a single AG-UI SSE frame.

    event_type must be SCREAMING_SNAKE_CASE.
    """
    return f"data: {json.dumps({'type': event_type, **data})}\n\n"


async def stream_axiom_response(session_id: str):
    """
    Yield AG-UI SSE events for a session until resolution or timeout.

    session_id serves as the threadId (long-lived conversation).
    A unique runId is generated per execution to satisfy AG-UI's requirement
    that both fields are present and distinct on RUN_STARTED / RUN_FINISHED.
    """
    from redis_fabric.fabric import get_redis

    redis = await get_redis()

    # runId identifies this particular execution within the conversation thread.
    run_id = f"run_{uuid.uuid4().hex[:12]}"

    yield build_ag_ui_event("RUN_STARTED", {
        "threadId": session_id,
        "runId": run_id,
    })

    last_id = "0"
    start_time = time.time()
    max_wait = SSE_MAX_WAIT
    heartbeat_interval = SSE_HEARTBEAT_INTERVAL
    last_heartbeat = start_time

    while time.time() - start_time < max_wait:
        messages = await redis.xread({"axiom:events": last_id}, count=10, block=1000)

        now = time.time()
        # Heartbeat keeps SSE connections alive through corporate NAT timeouts.
        # NAT devices typically kill connections idle for 30-60s.
        if now - last_heartbeat >= heartbeat_interval:
            yield ": heartbeat\n\n"
            last_heartbeat = now

        if not messages:
            continue

        for _stream, events in messages:
            for event_id, fields in events:
                last_id = event_id
                if fields.get("session_id") != session_id:
                    continue

                event_type = fields.get("event")

                if event_type == "session_created":
                    yield build_ag_ui_event(
                        "STATE_SNAPSHOT",
                        {
                            "snapshot": {
                                "session_id": session_id,
                                "status": "processing",
                            },
                        },
                    )

                elif event_type == "intake_completed":
                    classification_raw = await redis.hget(
                        f"session:{session_id}", "intake_classification"
                    )
                    if classification_raw:
                        yield build_ag_ui_event(
                            "STATE_DELTA",
                            {
                                "delta": [
                                    {
                                        "op": "add",
                                        "path": "/intake",
                                        "value": json.loads(classification_raw),
                                    }
                                ],
                            },
                        )

                elif event_type == "research_completed":
                    yield build_ag_ui_event(
                        "STATE_DELTA",
                        {
                            "delta": [
                                {
                                    "op": "add",
                                    "path": "/research_status",
                                    "value": "complete",
                                }
                            ],
                        },
                    )

                elif event_type == "external_task_polling":
                    # Emit STATE_DELTA so frontend shows "waiting for external agent"
                    # instead of a blank spinner during ghost polling (design.md §4.5).
                    yield build_ag_ui_event(
                        "STATE_DELTA",
                        {
                            "delta": [
                                {
                                    "op": "add",
                                    "path": "/external_task_status",
                                    "value": "polling",
                                }
                            ],
                        },
                    )

                elif event_type in ("session_stalled", "ghost_timeout"):
                    stall_reason = fields.get("stall_reason", event_type)
                    yield build_ag_ui_event("RUN_ERROR", {
                        "message": f"Session stalled: {stall_reason}",
                        "threadId": session_id,
                        "runId": run_id,
                    })
                    return

                elif event_type == "task_canceled":
                    yield build_ag_ui_event("RUN_ERROR", {
                        "message": "Task was cancelled.",
                        "threadId": session_id,
                        "runId": run_id,
                    })
                    return

                elif event_type == "resolution_completed":
                    resolution_raw = await redis.hget(
                        f"session:{session_id}", "resolution_payload"
                    )
                    if resolution_raw:
                        res_data = json.loads(resolution_raw)
                        yield build_ag_ui_event(
                            "STATE_DELTA",
                            {
                                "delta": [
                                    {
                                        "op": "add",
                                        "path": "/resolution",
                                        "value": res_data,
                                    }
                                ],
                            },
                        )

                        # TEXT_MESSAGE_* events surface the summary as a chat
                        # message in the CopilotKit UI before the run finishes.
                        summary_text = res_data.get("resolution_summary", "Resolution completed.")
                        # Stable messageId scoped to this session+run pair.
                        message_id = f"msg_{session_id[:8]}_{run_id[:8]}"
                        yield build_ag_ui_event("TEXT_MESSAGE_START", {
                            "messageId": message_id,
                            "role": "assistant",
                        })
                        yield build_ag_ui_event("TEXT_MESSAGE_CONTENT", {
                            "messageId": message_id,
                            "delta": summary_text,
                        })
                        yield build_ag_ui_event("TEXT_MESSAGE_END", {
                            "messageId": message_id,
                        })

                    # Both threadId and runId required on RUN_FINISHED.
                    yield build_ag_ui_event("RUN_FINISHED", {
                        "threadId": session_id,
                        "runId": run_id,
                    })
                    return

    yield build_ag_ui_event("RUN_ERROR", {
        "message": f"Request timed out after {int(max_wait)}s",
        "threadId": session_id,
        "runId": run_id,
    })
