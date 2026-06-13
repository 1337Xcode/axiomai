"""Shared pytest fixtures and helpers."""
import asyncio
import os
import time

import httpx

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

PYTHON_EXE = os.environ.get(
    "PYTHON_EXE",
    os.path.join(REPO_ROOT, ".axiom_env", "Scripts", "python.exe"),
)


async def wait_for_health(url: str, timeout: float = 60.0) -> None:
    """Poll /health until the service is ready or timeout."""
    deadline = time.monotonic() + timeout
    last_err: Exception | None = None
    async with httpx.AsyncClient() as client:
        while time.monotonic() < deadline:
            try:
                resp = await client.get(f"{url}/health", timeout=5.0)
                if resp.status_code == 200:
                    return
            except (
                httpx.ConnectError,
                httpx.ConnectTimeout,
                httpx.ReadTimeout,
                httpx.TimeoutException,
                httpx.RemoteProtocolError,
            ) as exc:
                last_err = exc
            await asyncio.sleep(0.5)
    raise TimeoutError(
        f"Service at {url} did not become healthy within {timeout}s: {last_err}"
    )
