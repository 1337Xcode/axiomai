"""[FIXED BUG 1] The original spec used socket.gethostbyname() decorated with
@lru_cache. This is a synchronous blocking system call. If called from within
an async FastAPI handler or an ADK dynamic node, it blocks the entire Python
event loop until the OS resolves the DNS — freezing all active SSE streams.

The correct approach:
1. Use asyncio.get_running_loop().getaddrinfo() for non-blocking DNS resolution
   if you genuinely need a custom cache.
2. More practically: use the global GATEWAY_CLIENT (httpx.AsyncClient), which
   already maintains connection keep-alive that effectively caches DNS via
   persistent TCP connections. No separate DNS cache is needed.

The global AGENT_DISCOVERY_CLIENT below replaces the custom DNS cache entirely.
"""

import httpx

# This client handles all agent card discovery calls.
# Its connection pool keeps TCP connections alive, which inherently avoids
# repeated DNS lookups for the same host within the connection's lifetime.
# httpx also uses the OS DNS cache (typically 30-300s TTL) for new connections.
AGENT_DISCOVERY_CLIENT = httpx.AsyncClient(
    timeout=httpx.Timeout(connect=5.0, read=10.0, write=5.0, pool=5.0),
    limits=httpx.Limits(max_connections=50, max_keepalive_connections=20),
    headers={"User-Agent": "Axiom-A2A-Client/1.0"},
)


async def fetch_agent_card(agent_url: str) -> dict:
    """Fetch remote AgentCard. Non-blocking. Reuses TCP connection if possible."""
    resp = await AGENT_DISCOVERY_CLIENT.get(f"{agent_url}/.well-known/agent-card.json")
    resp.raise_for_status()
    return resp.json()
