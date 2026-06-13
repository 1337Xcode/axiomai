"""
Integration Tests for AXIOM.

Spins up the four Uvicorn workers, waits for /health, and exercises the
real HTTP + JSON-RPC protocol layer. AXIOM_MODE=test short-circuits the
orchestrator so tests do not require live Gemini/LinkUp.
"""
import asyncio
import os
import socket
import subprocess

import httpx
import pytest

from tests.conftest import PYTHON_EXE, REPO_ROOT, wait_for_health


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


PORT_GATEWAY = find_free_port()
PORT_PERSONAL = find_free_port()
PORT_CS = find_free_port()
PORT_RESEARCH = find_free_port()

env = os.environ.copy()
env["PYTHONPATH"] = REPO_ROOT
env["PORT_PERSONAL"] = str(PORT_PERSONAL)
env["PORT_CS"] = str(PORT_CS)
env["PORT_RESEARCH"] = str(PORT_RESEARCH)
env["PORT_GATEWAY"] = str(PORT_GATEWAY)
env["AXIOM_MODE"] = "test"
env["REASONING_MODEL"] = "gemini-3.1-flash-lite"


@pytest.fixture(scope="session", autouse=True)
def spin_up_servers():
    """Spin up the 4 uvicorn workers and wait for health."""
    procs = []

    for module, port in (
        ("apps.app_personal:app", PORT_PERSONAL),
        ("apps.app_cs:app", PORT_CS),
        ("apps.app_research:app", PORT_RESEARCH),
        ("gateway.main:app", PORT_GATEWAY),
    ):
        proc = subprocess.Popen(
            [PYTHON_EXE, "-m", "uvicorn", module, "--port", str(port)],
            env=env,
            cwd=REPO_ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        procs.append(proc)

    async def _wait_all():
        await wait_for_health(f"http://127.0.0.1:{PORT_PERSONAL}")
        await wait_for_health(f"http://127.0.0.1:{PORT_CS}")
        await wait_for_health(f"http://127.0.0.1:{PORT_RESEARCH}")
        await wait_for_health(f"http://127.0.0.1:{PORT_GATEWAY}")

    asyncio.run(_wait_all())

    yield

    for p in procs:
        p.terminate()
        p.wait()


def _message_send_payload(
    msg_id: str,
    text: str = "hello",
    *,
    blocking: bool = True,
    rpc_id: str = "req-1",
    extra_params: dict | None = None,
) -> dict:
    params: dict = {
        "message": {
            "role": "user",
            "messageId": msg_id,
            "parts": [{"kind": "text", "text": text}],
        },
    }
    if not blocking:
        params["configuration"] = {"blocking": False}
    if extra_params:
        params.update(extra_params)
    return {
        "jsonrpc": "2.0",
        "method": "message/send",
        "id": rpc_id,
        "params": params,
    }


@pytest.mark.asyncio
async def test_external_message_send():
    """Blocking message/send completes with a task result in test mode."""
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"http://127.0.0.1:{PORT_GATEWAY}/a2a/customer_service",
            json=_message_send_payload("msg-123", rpc_id="req-1"),
            timeout=30.0,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("jsonrpc") == "2.0"
        assert "result" in data
        assert data["result"]["kind"] == "task"
        assert data["result"]["status"]["state"] == "completed"
        assert "id" in data["result"]


@pytest.mark.asyncio
async def test_external_tasks_get():
    """tasks/get returns the session state after message/send."""
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"http://127.0.0.1:{PORT_GATEWAY}/a2a/customer_service",
            json=_message_send_payload("msg-456", rpc_id="req-2"),
            timeout=30.0,
        )
        task_id = resp.json()["result"]["id"]

        resp2 = await client.post(
            f"http://127.0.0.1:{PORT_GATEWAY}/a2a/customer_service",
            json={
                "jsonrpc": "2.0",
                "method": "tasks/get",
                "id": "req-3",
                "params": {"id": task_id},
            },
            timeout=10.0,
        )
        assert resp2.status_code == 200
        data = resp2.json()
        assert data["result"]["id"] == task_id
        assert data["result"]["status"]["state"] == "completed"
        assert "artifacts" in data["result"]


@pytest.mark.asyncio
async def test_duplicate_message_id():
    """Duplicate messageId returns the same taskId (in-flight dedup)."""
    async with httpx.AsyncClient() as client:
        payload = _message_send_payload("msg-dup-1", text="duplicate test", rpc_id="req-4")
        resp1 = await client.post(
            f"http://127.0.0.1:{PORT_GATEWAY}/a2a/customer_service",
            json=payload,
            timeout=30.0,
        )
        assert resp1.status_code == 200
        task_id_1 = resp1.json()["result"]["id"]

        payload["id"] = "req-5"
        resp2 = await client.post(
            f"http://127.0.0.1:{PORT_GATEWAY}/a2a/customer_service",
            json=payload,
            timeout=30.0,
        )
        assert resp2.status_code == 200
        task_id_2 = resp2.json()["result"]["id"]
        assert task_id_1 == task_id_2


@pytest.mark.asyncio
async def test_external_tasks_cancel():
    """Non-blocking task appears in active_tasks and can be canceled."""
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"http://127.0.0.1:{PORT_GATEWAY}/a2a/customer_service",
            json=_message_send_payload(
                "msg-cancel-1",
                text="slow task please",
                blocking=False,
                rpc_id="req-cancel-1",
            ),
            timeout=15.0,
        )
        task_id = resp.json()["result"]["id"]

        await asyncio.sleep(0.5)

        resp_tasks = await client.get(f"http://127.0.0.1:{PORT_CS}/active_tasks")
        assert task_id in resp_tasks.json()

        resp2 = await client.post(
            f"http://127.0.0.1:{PORT_GATEWAY}/a2a/customer_service",
            json={
                "jsonrpc": "2.0",
                "method": "tasks/cancel",
                "id": "req-cancel-2",
                "params": {"id": task_id},
            },
            timeout=10.0,
        )
        assert resp2.status_code == 200
        assert resp2.json()["result"]["status"]["state"] == "canceled"

        await asyncio.sleep(0.5)
        resp_tasks_after = await client.get(f"http://127.0.0.1:{PORT_CS}/active_tasks")
        assert task_id not in resp_tasks_after.json()


@pytest.mark.asyncio
async def test_invalid_terminal_restart():
    """Layer 8 rejects appending to a canceled task."""
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"http://127.0.0.1:{PORT_GATEWAY}/a2a/customer_service",
            json=_message_send_payload(
                "msg-term-nb-1",
                text="quick non-blocking test",
                blocking=False,
                rpc_id="req-terminal-1",
            ),
            timeout=15.0,
        )
        assert resp.status_code == 200
        task_id = resp.json()["result"]["id"]

        resp_cancel = await client.post(
            f"http://127.0.0.1:{PORT_GATEWAY}/a2a/customer_service",
            json={
                "jsonrpc": "2.0",
                "method": "tasks/cancel",
                "id": "req-terminal-cancel",
                "params": {"id": task_id},
            },
            timeout=10.0,
        )
        assert resp_cancel.status_code == 200
        assert resp_cancel.json()["result"]["status"]["state"] == "canceled"

        resp2 = await client.post(
            f"http://127.0.0.1:{PORT_GATEWAY}/a2a/customer_service",
            json={
                "jsonrpc": "2.0",
                "method": "message/send",
                "id": "req-terminal-2",
                "params": {
                    "taskId": task_id,
                    "status": {"state": "working"},
                    "message": {
                        "role": "user",
                        "messageId": "msg-term-nb-2",
                        "parts": [{"kind": "text", "text": "append to canceled task"}],
                    },
                },
            },
            timeout=10.0,
        )
        assert resp2.status_code == 200
        assert "error" in resp2.json()


@pytest.mark.asyncio
async def test_legacy_type_discriminator_accepted():
    """Inbound parts using legacy 'type' are accepted and normalized."""
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"http://127.0.0.1:{PORT_GATEWAY}/a2a/customer_service",
            json={
                "jsonrpc": "2.0",
                "method": "message/send",
                "id": "req-legacy-type",
                "params": {
                    "message": {
                        "role": "user",
                        "messageId": "msg-legacy-1",
                        "parts": [{"type": "text", "text": "legacy type field"}],
                    },
                },
            },
            timeout=30.0,
        )
        assert resp.status_code == 200
        assert resp.json()["result"]["status"]["state"] == "completed"
