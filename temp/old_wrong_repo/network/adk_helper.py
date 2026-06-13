"""
ADK Context Factory.

Creates a valid ADK 2.0 Context for direct agent invocation
(ctx.run_node) without going through the full HTTP/A2A stack.

Uses InMemorySessionService which is the correct lightweight choice for
per-request contexts within a single process. The session service is
shared across all requests in the process so sessions are addressable
by session_id for the duration of the process lifetime.

Important: Context is not thread-safe. Each request must get its own
Context instance. The shared InMemorySessionService is safe for
concurrent access.
"""
import logging
from google.adk import Runner
from google.adk.sessions import InMemorySessionService

logger = logging.getLogger(__name__)

# Shared session service — safe for concurrent access.
# Reuse across requests so sessions are addressable within the process.
_SESSION_SERVICE = InMemorySessionService()


async def create_adk_runner(
    agent, session_id: str, user_id: str = "default_user"
) -> tuple[Runner, object]:
    """
    Create an ADK Runner for direct single-agent invocation.

    Returns a Runner pre-configured with the agent and session.
    Use runner.run_async() to execute the agent.
    """
    session = await _SESSION_SERVICE.create_session(
        app_name="axiom",
        user_id=user_id,
        session_id=session_id,
    )
    runner = Runner(
        agent=agent,
        app_name="axiom",
        session_service=_SESSION_SERVICE,
    )
    return runner, session


async def create_adk_context(session_id: str, user_id: str = "default_user"):
    """
    Create an ADK InvocationContext for use with ctx.run_node().

    This is the correct ADK 2.0 pattern for dynamic workflow nodes.
    Returns a Context object whose .state dict is live for the request.
    """
    from google.adk.agents.invocation_context import InvocationContext
    from google.adk.agents.run_config import RunConfig

    session = await _SESSION_SERVICE.create_session(
        app_name="axiom",
        user_id=user_id,
        session_id=session_id,
    )

    run_config = RunConfig()

    ic = InvocationContext(
        session_service=_SESSION_SERVICE,
        session=session,
        invocation_id=f"inv_{session_id}",
        run_config=run_config,
    )
    import asyncio
    ic._event_queue = asyncio.Queue()

    # ADK 2.0: Context wraps InvocationContext.
    # Do NOT monkey-patch private methods — that breaks on ADK minor version bumps.
    from google.adk import Context
    return Context(ic)
