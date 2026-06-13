"""
Personal Agent FastAPI Worker — port 8081.

Exposes:
  POST /run     — run intake classification for one message
  POST /cancel  — cancel a running task by taskId
  GET  /active_tasks — list running task IDs

The personal agent is a pure classification step (Tier 1).
It does not resolve issues or make external calls.
Results are returned as an A2A Task with an intake_classification artifact.

Note: this worker is NOT normally called directly by the orchestrator.
The orchestrator invokes personal_agent via direct ADK context to avoid
the gateway circular routing problem. This /run endpoint exists so
external A2A peers can call /a2a/personal if they need classification only.
"""
import asyncio
import json
import logging
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from dotenv import load_dotenv

from apps.a2a_utils import resolve_ids_from_envelope
from network.adk_helper import create_adk_context
from agents.personal_agent import personal_agent

load_dotenv()

logger = logging.getLogger(__name__)
app = FastAPI()

_ACTIVE_TASKS: dict[str, asyncio.Task] = {}


@app.get("/health")
async def health():
    return {"status": "ok", "service": "personal-agent"}


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
            return JSONResponse(content={"status": "cancelled", "taskId": task_id})
        return JSONResponse(content={"status": "not_running", "taskId": task_id})
    except Exception as exc:
        return JSONResponse(status_code=500, content={"error": str(exc)})


@app.post("/run")
async def run_personal(request: Request):
    """
    Run intake classification on a customer message.

    Returns an A2A Task with an intake_classification artifact.
    """
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"error": "Parse error"})

    session_id, task_id, input_text = resolve_ids_from_envelope(body)

    intake_input = json.dumps({
        "message": input_text,
        "session_id": str(session_id),
        "task_id": str(task_id),
    })

    ctx = await create_adk_context(str(session_id))
    ctx.state["session_id"] = str(session_id)
    ctx.state["task_id"] = str(task_id)

    current = asyncio.current_task()
    if current is not None:
        _ACTIVE_TASKS[task_id] = current

    try:
        await ctx.run_node(personal_agent, intake_input)
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
        logger.exception("Personal agent failed for task %s", task_id)
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

    classification_raw = ctx.state.get("intake_classification")
    if isinstance(classification_raw, dict):
        class_dict = classification_raw
    else:
        try:
            class_dict = json.loads(classification_raw) if classification_raw else {}
        except Exception:
            class_dict = {}

    return JSONResponse(content={
        "jsonrpc": "2.0",
        "result": {
            "id": task_id,
            "contextId": session_id,
            "kind": "task",
            "status": {"state": "completed"},
            "artifacts": [{
                "artifactId": "intake_classification",
                "parts": [{"kind": "data", "data": class_dict}],
            }],
        },
        "id": body.get("id"),
    })
