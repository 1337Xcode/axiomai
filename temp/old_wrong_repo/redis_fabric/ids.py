"""
Deterministic A2A / session ID derivation.

Network retries must map to the same taskId and session_id when the caller
re-sends the same messageId and payload. Random uuid4() breaks deduplication.
"""
import hashlib


def stable_id(prefix: str, *parts: str) -> str:
    """SHA256-based ID stable across process restarts and workers."""
    blob = "|".join(p for p in parts if p)
    if not blob:
        blob = prefix
    return f"{prefix}_{hashlib.sha256(blob.encode()).hexdigest()[:20]}"


def derive_session_id(
    *,
    context_id: str | None = None,
    message_id: str | None = None,
    raw_message: str = "",
    peer_id: str | None = None,
) -> str:
    """Derive session_id from explicit contextId or payload fingerprint."""
    if context_id:
        return str(context_id)
    return stable_id("ses", peer_id or "", message_id or "", raw_message)


def derive_task_id(
    *,
    explicit_task_id: str | None = None,
    session_id: str = "",
    message_id: str | None = None,
    rpc_id: str | int | None = None,
    peer_id: str | None = None,
) -> str:
    """Derive task_id from explicit taskId or dedup-stable fingerprint."""
    if explicit_task_id:
        return str(explicit_task_id)
    if message_id and peer_id:
        return stable_id("tsk", peer_id, message_id)
    if message_id and session_id:
        return stable_id("tsk", session_id, message_id)
    if rpc_id is not None:
        return stable_id("tsk", str(rpc_id))
    return stable_id("tsk", session_id, message_id or "")
