"""
CS Agent FastAPI Worker — port 8082.

Exposes:
  POST /run     — blocking execution; orchestrates all three tiers
  POST /cancel  — cancel a running task by taskId
  GET  /active_tasks — list currently running task IDs
"""
import asyncio
import json
import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from dotenv import load_dotenv

from apps.a2a_utils import resolve_ids_from_envelope
from config import AXIOM_MODE
from network.adk_helper import create_adk_context
from orchestrator.workflow import AxiomOrchestrator
from redis_fabric.fabric import (
    record_session_transition,
    seed_session,
    set_session_status,
)

load_dotenv()

logger = logging.getLogger(__name__)
app = FastAPI()

_ACTIVE_TASKS: dict[str, asyncio.Task] = {}


def _public_resolution(resolution_dict: dict) -> dict:
    return {
        "resolution_status": resolution_dict.get("resolution_status", "resolved"),
        "resolution_summary": resolution_dict.get("resolution_summary", ""),
        "follow_up_actions": resolution_dict.get("follow_up_actions", []),
        "confidence_score": resolution_dict.get("confidence_score", 0.0),
        "requires_human_review": resolution_dict.get("requires_human_review", False),
    }


def _completed_task_response(
    body: dict,
    task_id: str,
    session_id: str,
    public_dict: dict,
) -> JSONResponse:
    return JSONResponse(content={
        "jsonrpc": "2.0",
        "result": {
            "id": task_id,
            "contextId": session_id,
            "kind": "task",
            "status": {"state": "completed"},
            "artifacts": [{
                "artifactId": "resolution_artifact",
                "parts": [{"kind": "data", "data": public_dict}],
            }],
        },
        "id": body.get("id"),
    })


async def _run_test_mode(
    body: dict,
    session_id: str,
    task_id: str,
    input_text: str,
) -> JSONResponse:
    """
    CI/test short-circuit: no ADK or live LLM calls.

    Holds the task open when the message contains 'slow task please' so
    tasks/cancel integration tests have a cancellable in-flight coroutine.
    """
    current = asyncio.current_task()
    if current is not None:
        _ACTIVE_TASKS[task_id] = current

    try:
        if "slow task please" in input_text.lower():
            await asyncio.sleep(30)
        else:
            session_id, task_id = await seed_session(
                input_text, session_id, task_id
            )
            resolution = json.dumps({
                "resolution_status": "resolved",
                "resolution_summary": f"Test-mode resolution for: {input_text[:120]}",
                "internal_notes": "AXIOM_MODE=test short-circuit",
                "confidence_score": 1.0,
                "requires_human_review": False,
                "follow_up_actions": [],
            })
            await record_session_transition(
                session_id, task_id,
                "resolution_payload", resolution,
                "resolution_completed",
            )
            await set_session_status(session_id, "completed")
            public_dict = _public_resolution(json.loads(resolution))
            return _completed_task_response(body, task_id, session_id, public_dict)
    except asyncio.CancelledError:
        return JSONResponse(content={
            "jsonrpc": "2.0",
            "result": {
                "id": task_id,
                "contextId": session_id,
                "kind": "task",
                "status": {"state": "canceled"},
            },
            "id": body.get("id"),
        })
    finally:
        _ACTIVE_TASKS.pop(task_id, None)

    # Unreachable unless slow-task sleep completes without cancel
    return JSONResponse(content={
        "jsonrpc": "2.0",
        "result": {
            "id": task_id,
            "contextId": session_id,
            "kind": "task",
            "status": {"state": "failed"},
            "error": {"code": -32000, "message": "slow test task timed out"},
        },
        "id": body.get("id"),
    })


@app.get("/health")
async def health():
    return {"status": "ok", "service": "cs-agent"}


@app.get("/active_tasks")
async def get_active_tasks():
    return list(_ACTIVE_TASKS.keys())


@app.post("/cancel")
async def cancel_task(request: Request):
    try:
        body = await request.json()
        task_id = body.get("taskId")
        if task_id and task_id in _ACTIVE_TASKS:
            task = _ACTIVE_TASKS[task_id]
            if not task.done():
                task.cancel()
                logger.info("Cancelled task %s", task_id)
            return JSONResponse(content={"status": "cancelled", "taskId": task_id})
        return JSONResponse(content={"status": "not_running", "taskId": task_id})
    except Exception as exc:
        logger.exception("cancel_task error")
        return JSONResponse(status_code=500, content={"error": str(exc)})


@app.post("/run")
async def run_cs(request: Request):
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"error": "Parse error"})

    session_id, task_id, input_text = resolve_ids_from_envelope(body)

    if AXIOM_MODE == "test":
        return await _run_test_mode(body, session_id, task_id, input_text)

    ctx = await create_adk_context(str(session_id))

    input_data = {
        "message": input_text,
        "session_id": str(session_id),
        "task_id": str(task_id),
    }

    orchestrator = AxiomOrchestrator(name="axiom_orchestrator")
    current = asyncio.current_task()
    if current is not None:
        _ACTIVE_TASKS[task_id] = current

    final_result: dict | None = None
    try:
        async for output in orchestrator.run(ctx, input_data):
            final_result = output
    except asyncio.CancelledError:
        return JSONResponse(content={
            "jsonrpc": "2.0",
            "result": {
                "id": task_id,
                "contextId": session_id,
                "kind": "task",
                "status": {"state": "canceled"},
            },
            "id": body.get("id"),
        })
    except Exception as exc:
        logger.exception("Orchestrator failed for task %s", task_id)
        return JSONResponse(content={
            "jsonrpc": "2.0",
            "result": {
                "id": task_id,
                "contextId": session_id,
                "kind": "task",
                "status": {"state": "failed"},
                "error": {"code": -32000, "message": str(exc)},
            },
            "id": body.get("id"),
        })
    finally:
        _ACTIVE_TASKS.pop(task_id, None)

    if final_result and final_result.get("status") != "failed":
        resolution_str = final_result.get("resolution", "{}")
        try:
            resolution_dict = (
                json.loads(resolution_str)
                if isinstance(resolution_str, str)
                else resolution_str
            )
        except Exception:
            resolution_dict = {"resolution_summary": str(resolution_str)}

        return _completed_task_response(
            body, task_id, session_id, _public_resolution(resolution_dict)
        )

    error_reason = (
        final_result.get("error", "Unknown error") if final_result else "No output"
    )
    return JSONResponse(content={
        "jsonrpc": "2.0",
        "result": {
            "id": task_id,
            "contextId": session_id,
            "kind": "task",
            "status": {"state": "failed"},
            "error": {"code": -32000, "message": error_reason},
        },
        "id": body.get("id"),
    })
