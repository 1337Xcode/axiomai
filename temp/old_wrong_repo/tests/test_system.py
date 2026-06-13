"""
AXIOM System Test Suite.

10 unit tests covering protocol correctness, edge cases, and resilience.
All tests run without real API calls (mocked Redis, no live Gemini/LinkUp).

Run with:
  .axiom_env\\Scripts\\python.exe -m pytest tests/test_system.py -v
"""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock

from gateway.validators.rpc_validator import validate_rpc_envelope, ALLOWED_METHODS, UNIMPLEMENTED_METHODS
from gateway.validators.a2a_validator import TolerantPart, TolerantMessage, sanitise_payload
from gateway.state_machine import TaskStateMachineTracker


# ---------------------------------------------------------------------------
# 1. RPC envelope validation
# ---------------------------------------------------------------------------

def test_rpc_envelope_validation():
    """Validate JSON-RPC 2.0 envelope acceptance and rejection rules."""
    # Valid message/send
    env = validate_rpc_envelope({
        "jsonrpc": "2.0",
        "method": "message/send",
        "id": "req-001",
        "params": {"message": "hello"},
    })
    assert env is not None
    assert env.method == "message/send"
    assert env.id == "req-001"

    # Invalid method rejected
    assert validate_rpc_envelope({"jsonrpc": "2.0", "method": "invalid/method", "id": 1}) is None

    # Invalid version rejected
    assert validate_rpc_envelope({"jsonrpc": "1.0", "method": "message/send", "id": 1}) is None

    # message/stream must NOT be in ALLOWED_METHODS (streaming=false in Agent Card)
    assert "message/stream" not in ALLOWED_METHODS

    # tasks/get and tasks/cancel must be allowed
    assert "tasks/get" in ALLOWED_METHODS
    assert "tasks/cancel" in ALLOWED_METHODS

    # Push-notification methods are in allowlist but marked as unimplemented
    assert "tasks/pushNotificationConfig/set" in UNIMPLEMENTED_METHODS


# ---------------------------------------------------------------------------
# 2. TolerantPart kind/type normalization
# ---------------------------------------------------------------------------

def test_tolerant_part_normalization():
    """Accept both 'kind' (v0.3) and legacy 'type', always emit 'kind'."""
    # Standard kind field
    assert TolerantPart(kind="text", text="hello").normalized_kind == "text"
    # Legacy type field
    assert TolerantPart(type="text", text="hello").normalized_kind == "text"
    # Inferred from text field
    assert TolerantPart(text="hello").normalized_kind == "text"
    # Inferred from data field
    assert TolerantPart(data={"key": "val"}).normalized_kind == "data"


# ---------------------------------------------------------------------------
# 3. Payload sanitisation
# ---------------------------------------------------------------------------

def test_sanitise_payload():
    """Strip zero-width chars and reject oversized payloads."""
    # Zero-width space stripped with warning
    clean, warnings = sanitise_payload({"message": "he\u200bllo"})
    assert clean["message"] == "hello"
    assert any("U+200B" in w for w in warnings)

    # Oversized payload rejected
    with pytest.raises(ValueError, match="Payload too large"):
        sanitise_payload({"data": "A" * (513 * 1024)})


# ---------------------------------------------------------------------------
# 4. TolerantMessage — A2A v0.3 required field enforcement
# ---------------------------------------------------------------------------

def test_tolerant_message_requires_role_and_parts():
    """A2A v0.3 message must have role, parts, and messageId."""
    # Valid complete message
    msg = TolerantMessage.model_validate({
        "role": "user",
        "messageId": "msg-001",
        "parts": [{"kind": "text", "text": "I need a refund"}],
        "metadata": {"agentId": "peer-agent-xyz"},
    })
    assert msg.role == "user"
    assert msg.messageId == "msg-001"
    assert len(msg.parts) == 1

    # Invalid role rejected
    with pytest.raises(Exception):
        TolerantMessage.model_validate({
            "role": "system",
            "messageId": "msg-002",
            "parts": [{"kind": "text", "text": "test"}],
        })

    # Empty parts rejected
    with pytest.raises(Exception):
        TolerantMessage.model_validate({
            "role": "user",
            "messageId": "msg-003",
            "parts": [],
        })

    # Missing messageId: required, raises ValidationError
    with pytest.raises(Exception):
        TolerantMessage.model_validate({
            "role": "user",
            "parts": [{"kind": "text", "text": "hello"}],
        })


# ---------------------------------------------------------------------------
# 5. State machine: transitions, idempotency, circuit breaker
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_task_state_machine_tracker():
    """Test valid/invalid transitions and idempotent terminal events."""
    redis_mock = AsyncMock()
    tracker = TaskStateMachineTracker(redis_mock)

    # Register outbound task
    await tracker.record_outbound_task("task_1", "agent_1")
    redis_mock.hset.assert_called_with(
        "shadow:task:task_1",
        mapping={"state": "submitted", "agent_id": "agent_1"}
    )

    # Valid transition: submitted -> working
    redis_mock.hgetall.return_value = {"state": "submitted", "agent_id": "agent_1"}
    valid, err = await tracker.validate_incoming_state("task_1", "working")
    assert valid is True
    assert err == ""

    # Invalid transition: working -> submitted
    redis_mock.hgetall.return_value = {"state": "working", "agent_id": "agent_1"}
    valid, err = await tracker.validate_incoming_state("task_1", "submitted")
    assert valid is False
    assert "Invalid transition" in err

    # Idempotent: same state reported again (at-least-once delivery)
    redis_mock.hgetall.return_value = {"state": "completed", "agent_id": "agent_1"}
    valid, err = await tracker.validate_incoming_state("task_1", "completed")
    assert valid is True
    assert "idempotent" in err

    # Idempotent: terminal -> different terminal (completed -> failed replay)
    redis_mock.hgetall.return_value = {"state": "completed", "agent_id": "agent_1"}
    valid, err = await tracker.validate_incoming_state("task_1", "failed")
    assert valid is True
    assert "idempotent" in err

    # Circuit breaker incrementing uses short window
    pipe_mock = AsyncMock()
    pipe_mock.incr = MagicMock()
    pipe_mock.expire = MagicMock()
    redis_mock.pipeline = MagicMock(return_value=pipe_mock)
    await tracker.record_agent_failure("agent_1")
    pipe_mock.incr.assert_called_with("circuit:agent_1:failures")
    pipe_mock.execute.assert_called_once()


# ---------------------------------------------------------------------------
# 6. Redis offline fallback (development mode only)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_redis_offline_fallback(monkeypatch, tmp_path):
    """In development mode, seed_session and record_session_transition fall back to SQLite."""
    from redis_fabric.fabric import (
        seed_session,
        record_session_transition,
        get_session_by_task_id,
        get_session_data,
    )

    db_file = tmp_path / "fallback.sqlite"
    monkeypatch.setattr("redis_fabric.fabric._SQLITE_PATH", str(db_file))

    async def mock_get_redis_fail():
        raise ConnectionError("Redis server is offline.")

    monkeypatch.setattr("redis_fabric.fabric.get_redis", mock_get_redis_fail)
    monkeypatch.setattr("redis_fabric.fabric.AXIOM_MODE", "development")

    session_id, task_id = await seed_session("Test message offline fallback")
    
    got_session_id = await get_session_by_task_id(task_id)
    assert got_session_id == session_id

    success = await record_session_transition(
        session_id, task_id,
        "resolution_payload", '{"resolution_summary": "Resolved"}',
        "resolution_completed"
    )
    assert success is True
    
    sess_data = await get_session_data(session_id)
    assert sess_data is not None
    assert sess_data["status"] == "completed"


# ---------------------------------------------------------------------------
# 7. Account context fallback (development mode)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_account_context_fallback(monkeypatch):
    """In development mode, account lookup falls back to MOCK_ACCOUNTS on Redis failure."""
    # Set development mode so mock fallback is enabled
    monkeypatch.setenv("AXIOM_MODE", "development")
    # Reload config to pick up the env change
    import importlib
    import config
    import redis_fabric.fabric as fabric
    importlib.reload(config)
    importlib.reload(fabric)
    from redis_fabric.fabric import get_account_context

    async def mock_get_redis_fail():
        raise ConnectionError("Redis server is offline.")

    monkeypatch.setattr("redis_fabric.fabric.get_redis", mock_get_redis_fail)

    # Known mock account (ACC-12345 = Alice Johnson in development mode)
    acc_data = await get_account_context("ACC-12345")
    assert "Alice Johnson" in acc_data

    # Unknown account returns empty JSON
    invalid_data = await get_account_context("ACC-INVALID")
    assert invalid_data == "{}"


# ---------------------------------------------------------------------------
# 8. Boundary cases for TolerantPart
# ---------------------------------------------------------------------------

def test_tolerant_part_boundary_cases():
    """Empty TolerantPart raises ValueError on normalized_kind access."""
    part_text = TolerantPart(text="Hello text")
    assert part_text.normalized_kind == "text"

    part_data = TolerantPart(data={"payload": "value"})
    assert part_data.normalized_kind == "data"

    part_empty = TolerantPart()
    with pytest.raises(ValueError, match="Cannot determine part kind"):
        _ = part_empty.normalized_kind


# ---------------------------------------------------------------------------
# 9. State machine: unknown task is tolerated
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_state_machine_tracker_unknown_task():
    """Unknown task ID (no shadow entry) is tolerated without error."""
    redis_mock = AsyncMock()
    redis_mock.hgetall.return_value = {}
    tracker = TaskStateMachineTracker(redis_mock)

    valid, err = await tracker.validate_incoming_state("unknown_task", "working")
    assert valid is True
    assert err == ""


# ---------------------------------------------------------------------------
# 10. Agent Card required A2A v0.3 fields
# ---------------------------------------------------------------------------

def test_agent_card_validation():
    """Agent Card must include all required A2A v0.3 top-level and skill fields."""
    from agent_card import AXIOM_AGENT_CARD

    # Top-level required fields
    assert AXIOM_AGENT_CARD["protocolVersion"] == "0.3.0"
    assert "name" in AXIOM_AGENT_CARD
    assert "description" in AXIOM_AGENT_CARD
    assert "version" in AXIOM_AGENT_CARD
    assert "url" in AXIOM_AGENT_CARD
    assert "defaultInputModes" in AXIOM_AGENT_CARD
    assert "defaultOutputModes" in AXIOM_AGENT_CARD

    # Capabilities must match implementation
    caps = AXIOM_AGENT_CARD["capabilities"]
    assert caps["streaming"] is False
    assert caps["pushNotifications"] is False
    assert caps["stateTransitionHistory"] is False

    # Skill required fields
    skill = AXIOM_AGENT_CARD["skills"][0]
    assert "id" in skill
    assert "name" in skill
    assert "description" in skill
    assert "tags" in skill
    assert isinstance(skill["tags"], list)
    assert len(skill["tags"]) > 0


# ---------------------------------------------------------------------------
# 12. Deterministic ID derivation (retry-safe)
# ---------------------------------------------------------------------------

def test_deterministic_ids_from_message_id():
    """Same messageId + peer produces the same taskId across calls."""
    from redis_fabric.ids import derive_task_id, stable_id

    t1 = derive_task_id(message_id="msg-abc", peer_id="peer-1")
    t2 = derive_task_id(message_id="msg-abc", peer_id="peer-1")
    assert t1 == t2
    assert t1.startswith("tsk_")

    s1 = stable_id("ses", "peer-1", "msg-abc", "hello")
    s2 = stable_id("ses", "peer-1", "msg-abc", "hello")
    assert s1 == s2


# ---------------------------------------------------------------------------
# 11b. ADK context factory smoke (event queue init)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_adk_context_event_queue():
    """
    create_adk_context must initialise InvocationContext._event_queue.

    Without it, ctx.run_node() raises at runtime. Guards against ADK internal
    attribute renames when google-adk==2.0.0 is the pinned version.
    """
    from network.adk_helper import create_adk_context

    ctx = await create_adk_context("unit_test_session")
    ic = ctx._invocation_context
    assert getattr(ic, "_event_queue", None) is not None


# ---------------------------------------------------------------------------
# 13. AG-UI SSE heartbeat yields NAT keepalive comment
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_sse_heartbeat_comment(monkeypatch):
    """SSE bridge emits ': heartbeat\\n\\n' while waiting on Redis."""
    from unittest.mock import AsyncMock

    import frontend.ag_ui_bridge as bridge

    clock = [1000.0, 1000.0, 1016.0]

    def fake_time():
        return clock.pop(0) if clock else 1016.0

    monkeypatch.setattr(bridge.time, "time", fake_time)
    monkeypatch.setattr(bridge, "SSE_HEARTBEAT_INTERVAL", 15.0)
    monkeypatch.setattr(bridge, "SSE_MAX_WAIT", 120.0)

    mock_redis = AsyncMock()
    mock_redis.xread = AsyncMock(return_value=[])
    mock_redis.hget = AsyncMock(return_value=None)
    monkeypatch.setattr(
        "redis_fabric.fabric.get_redis", AsyncMock(return_value=mock_redis)
    )

    events: list[str] = []
    async for chunk in bridge.stream_axiom_response("ses_test_heartbeat"):
        events.append(chunk)
        if ": heartbeat\n\n" in chunk:
            break

    assert any(": heartbeat\n\n" in e for e in events)


# ---------------------------------------------------------------------------
# 11. AG-UI event format: both threadId and runId required
# ---------------------------------------------------------------------------

def test_ag_ui_event_serialization():
    """AG-UI RUN_STARTED must include both threadId and runId."""
    from frontend.ag_ui_bridge import build_ag_ui_event

    # RUN_STARTED with both required fields
    event = build_ag_ui_event("RUN_STARTED", {"threadId": "ses_123", "runId": "run_abc"})
    assert "data: " in event
    data = json.loads(event.replace("data: ", "").strip())
    assert data["type"] == "RUN_STARTED"
    assert data["threadId"] == "ses_123"
    assert data["runId"] == "run_abc"

    # TEXT_MESSAGE_START requires role
    msg_start = build_ag_ui_event("TEXT_MESSAGE_START", {
        "messageId": "msg_001",
        "role": "assistant",
    })
    msg_data = json.loads(msg_start.replace("data: ", "").strip())
    assert msg_data["role"] == "assistant"
    assert msg_data["type"] == "TEXT_MESSAGE_START"
