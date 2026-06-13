"""
Research Agent FastAPI Worker — port 8083.

Exposes:
  POST /run     — synchronous research execution
  POST /cancel  — cancel a running task by taskId
  GET  /active_tasks — list running task IDs

Pipeline per request:
  1. Extract query text from A2A message parts.
  2. Run linkup_search; on failure build a structured error artifact
     (Bug #4 fix — never return None/empty on error).
  3. Run the research_formatter ADK agent to synthesise results into
     a ResearchResult schema.
  4. Return an A2A Task with status=completed and a research_result artifact.

Note: research agents are called directly from the orchestrator via ADK,
not via this HTTP endpoint, in the normal flow. This endpoint exists for
external A2A peers that want to invoke the research agent independently.
"""
import asyncio
import json
import logging
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from dotenv import load_dotenv

from apps.a2a_utils import resolve_ids_from_envelope
from network.adk_helper import create_adk_context
from agents.research_agent import research_formatter
from tools.linkup_search import linkup_search

load_dotenv()

logger = logging.getLogger(__name__)
app = FastAPI()

_ACTIVE_TASKS: dict[str, asyncio.Task] = {}


@app.get("/health")
async def health():
    return {"status": "ok", "service": "research-agent"}


@app.get("/active_tasks")
async def get_active_tasks():
    """List currently running task IDs."""
    return list(_ACTIVE_TASKS.keys())


@app.post("/cancel")
async def cancel_task(request: Request):
    """
    Cancel a running research task by taskId.

    Called by the gateway when tasks/cancel is received for a task
    currently owned by this worker.
    """
    try:
        body = await request.json()
        task_id = body.get("taskId")
        if task_id and task_id in _ACTIVE_TASKS:
            task = _ACTIVE_TASKS[task_id]
            if not task.done():
                task.cancel()
                logger.info("Cancelled research task %s", task_id)
            return JSONResponse(content={"status": "cancelled", "taskId": task_id})
        return JSONResponse(content={"status": "not_running", "taskId": task_id})
    except Exception as exc:
        logger.exception("cancel_task error")
        return JSONResponse(status_code=500, content={"error": str(exc)})


@app.post("/run")
async def run_research(request: Request):
    """
    Execute a research query and return a completed A2A Task object.

    Pipeline:
    1. Extract query text from A2A message parts.
    2. Run linkup_search; on failure return a structured error artifact.
    3. Run research_formatter ADK agent to produce ResearchResult schema.
    4. Return A2A Task with status=completed.
    """
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"error": "Parse error"})

    session_id, task_id, input_text = resolve_ids_from_envelope(body)

    current = asyncio.current_task()
    if current is not None:
        _ACTIVE_TASKS[task_id] = current

    try:
        # Run LinkUp search; surface structured error artifact on failure.
        # [FIXED BUG 4] Never return None — always return a typed artifact.
        try:
            raw_results = await linkup_search(input_text, depth="standard")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("LinkUp search failed for '%s': %s", input_text, exc)
            raw_results = {
                "answer": (
                    f"SYSTEM ERROR: Information retrieval failed "
                    f"({type(exc).__name__}: {exc}). "
                    "Do not hallucinate data for this query."
                ),
                "sources": [],
                "confidence": 0.0,
            }

        ctx = await create_adk_context(str(session_id))
        ctx.state["research_query"] = input_text
        ctx.state["raw_search_results"] = (
            json.dumps(raw_results)
            if not isinstance(raw_results, str)
            else raw_results
        )

        await ctx.run_node(research_formatter, input_text)

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
        logger.exception("Research pipeline failed for task %s", task_id)
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

    research_raw = ctx.state.get("research_results")
    if isinstance(research_raw, dict):
        res_dict = research_raw
    else:
        try:
            res_dict = json.loads(research_raw) if research_raw else {}
        except Exception:
            res_dict = {}

    return JSONResponse(content={
        "jsonrpc": "2.0",
        "result": {
            "id": task_id,
            "contextId": session_id,
            "kind": "task",
            "status": {"state": "completed"},
            "artifacts": [{
                "artifactId": "research_result",
                "parts": [{"kind": "data", "data": res_dict}],
            }],
        },
        "id": body.get("id"),
    })
