"""
LinkUp Search Tool.

Single global httpx client reused across all parallel searches.
[FIXED BUG 3] Never instantiate AsyncClient inside the function — that
destroys connection pooling and adds ~200ms SSL overhead per search.

[FIXED BUG 4] On any exception, raises so the orchestrator can catch it
and return a structured SYSTEM ERROR artifact. The function never silently
swallows errors and returns None/empty — that causes the CS agent to
hallucinate an answer with no evidence base.
"""
import os
import logging
import httpx

logger = logging.getLogger(__name__)

# [FIXED BUG 3] Single global client. Connection pool and SSL session are
# reused across all parallel searches. Never instantiate inside the function.
LINKUP_CLIENT = httpx.AsyncClient(
    timeout=30.0,
    limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
    headers={"User-Agent": "Axiom-Research/1.0"},
)

LINKUP_STRUCTURED_SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {"type": "string"},
        "sources": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                    "title": {"type": "string"},
                    "snippet": {"type": "string"},
                },
                "required": ["url", "snippet"],
            },
        },
        "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
    },
    "required": ["answer", "sources"],
}


async def linkup_search(query: str, depth: str = "standard") -> dict:
    """
    Execute a LinkUp structured search.

    Called directly by the orchestrator before research_formatter runs.
    Results are injected into ctx.state as explicit inputs — not set as
    LlmAgent tools — which avoids the output_schema + tools ADK trap.

    Raises httpx.HTTPStatusError or httpx.RequestError on failure.
    The orchestrator catches these and builds a structured error artifact
    so the CS agent knows retrieval failed and does not hallucinate.

    If LINKUP_API_KEY is absent, raises EnvironmentError with an explicit
    message so the error artifact surfaces a clear failure reason.
    """
    api_key = os.environ.get("LINKUP_API_KEY", "").strip()
    if not api_key:
        raise EnvironmentError(
            "LINKUP_API_KEY is not set. "
            "Set this environment variable to enable external knowledge retrieval."
        )

    resp = await LINKUP_CLIENT.post(
        "https://api.linkup.so/v1/search",
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "q": query,
            "depth": depth,
            "outputType": "structured",
            "structuredOutputSchema": LINKUP_STRUCTURED_SCHEMA,
        },
    )
    resp.raise_for_status()
    return resp.json()
