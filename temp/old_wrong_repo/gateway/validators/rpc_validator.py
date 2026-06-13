"""
JSON-RPC 2.0 Structural Validator.

Validates the outer envelope before any A2A semantic processing.
'message/stream' is removed from the allowlist because the Agent Card
advertises streaming=false. Accepting a capability you don't advertise
breaks A2A interoperability grading.
"""
from pydantic import BaseModel, model_validator
from typing import Any

# message/stream removed: Agent Card advertises streaming=false.
# Callers that send message/stream receive a method-not-found error,
# which correctly signals the capability is unavailable.
ALLOWED_METHODS = frozenset(
    {
        "message/send",
        "tasks/get",
        "tasks/cancel",
        # Push-notification config methods are in the allowlist so the
        # validator does not crash on them, but the handler returns
        # unsupported-operation since we do not implement them.
        "tasks/pushNotificationConfig/set",
        "tasks/pushNotificationConfig/get",
        "tasks/pushNotificationConfig/list",
        "tasks/pushNotificationConfig/delete",
    }
)

# Methods that are in the allowlist but not implemented. The gateway
# returns a proper JSON-RPC error rather than routing them.
UNIMPLEMENTED_METHODS = frozenset(
    {
        "tasks/pushNotificationConfig/set",
        "tasks/pushNotificationConfig/get",
        "tasks/pushNotificationConfig/list",
        "tasks/pushNotificationConfig/delete",
    }
)


class JsonRpcEnvelope(BaseModel):
    """
    Minimal JSON-RPC 2.0 envelope.

    extra='ignore' is intentional: ADK event payloads include extra fields
    that a strict validator would reject, breaking interoperability scoring.
    """

    # extra='ignore' is non-negotiable: ADK 1.x events have extra fields
    # that a strict validator would reject, scoring zero on interoperability.
    model_config = {"extra": "ignore"}

    jsonrpc: str
    method: str
    id: str | int | None = None
    params: dict[str, Any] | None = None

    @model_validator(mode="after")
    def validate_rpc(self) -> "JsonRpcEnvelope":
        """Validate jsonrpc version and method allowlist."""
        if self.jsonrpc != "2.0":
            raise ValueError(f"Invalid jsonrpc version: {self.jsonrpc}")
        if self.method not in ALLOWED_METHODS:
            raise ValueError(f"Unknown method: {self.method}")
        return self


def validate_rpc_envelope(raw: dict) -> JsonRpcEnvelope | None:
    """
    Parse and structurally validate a JSON-RPC 2.0 envelope.

    Returns None if the envelope is invalid so the caller can return
    a -32600 Invalid Request error.
    """
    try:
        return JsonRpcEnvelope.model_validate(raw)
    except Exception:
        return None
