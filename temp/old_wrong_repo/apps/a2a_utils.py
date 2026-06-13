"""
Shared A2A envelope parsing for worker /run endpoints.

Extracts plain-text intent and stable IDs from JSON-RPC params before ADK runs.
"""


def extract_message_text(msg_dict: dict) -> str:
    """Extract text from the first text part (accepts kind or legacy type)."""
    parts = msg_dict.get("parts", [])
    for part in parts:
        if part.get("kind") == "text" or part.get("type") == "text":
            return part.get("text", "")
    if parts:
        return parts[0].get("text", "")
    return ""


def resolve_ids_from_envelope(
    body: dict,
    peer_id: str | None = None,
) -> tuple[str, str, str]:
    """
    Return (session_id, task_id, message_text) from a JSON-RPC body.

    Uses deterministic derivation when IDs are absent so retries are idempotent.
    """
    from redis_fabric.ids import derive_session_id, derive_task_id

    params = body.get("params", {})
    msg_dict = params.get("message", {})
    message_id = msg_dict.get("messageId", "")
    text = extract_message_text(msg_dict)

    session_id = derive_session_id(
        context_id=msg_dict.get("contextId") or params.get("sessionId"),
        message_id=message_id,
        raw_message=text,
        peer_id=peer_id,
    )
    task_id = derive_task_id(
        explicit_task_id=msg_dict.get("taskId") or params.get("taskId"),
        session_id=session_id,
        message_id=message_id,
        rpc_id=body.get("id"),
        peer_id=peer_id,
    )
    return session_id, task_id, text
