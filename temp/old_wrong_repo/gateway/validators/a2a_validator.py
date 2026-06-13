"""
A2A Message and Payload Validators.

TolerantPart: accepts both 'kind' (v0.3) and 'type' (legacy) field. Always emits 'kind'.
TolerantMessage: enforces A2A v0.3 required fields: role, parts, messageId.
sanitise_payload: strips zero-width injection chars; enforces 512KB serialized cap.
"""
import json
from pydantic import BaseModel, field_validator


class TolerantPart(BaseModel):
    """
    A2A message part with tolerant kind/type discriminator.

    A2A v0.3.x uses 'kind'. Pre-v0.3 tutorials and some SDKs use 'type'.
    Both are accepted inbound. Only 'kind' is emitted outbound for spec compliance.
    """

    model_config = {"extra": "ignore"}

    kind: str | None = None
    type: str | None = None  # legacy field from pre-0.3 tutorials
    text: str | None = None
    data: dict | None = None

    @property
    def normalized_kind(self) -> str:
        """Return the canonical 'kind' value regardless of which field was set."""
        raw = self.kind or self.type
        if raw:
            return raw
        if self.text is not None:
            return "text"
        if self.data is not None:
            return "data"
        raise ValueError(
            "Cannot determine part kind — no kind, type, text, or data field"
        )


class TolerantMessage(BaseModel):
    """
    A2A v0.3 message model.

    Required by spec: role, parts, messageId.
    messageId must be a non-empty string provided by the sender for deduplication.
    role must be 'user' or 'agent'.
    parts must be a non-empty list.
    """

    model_config = {"extra": "ignore"}

    role: str
    parts: list[TolerantPart]
    messageId: str
    metadata: dict | None = None
    contextId: str | None = None
    taskId: str | None = None

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: str) -> str:
        """Enforce A2A v0.3 role values."""
        if v not in ("user", "agent"):
            raise ValueError(f"Invalid role '{v}': must be 'user' or 'agent'")
        return v

    @field_validator("parts")
    @classmethod
    def validate_parts_nonempty(cls, v: list) -> list:
        """Enforce non-empty parts list per A2A v0.3 spec."""
        if not v:
            raise ValueError("parts must not be empty")
        return v

    @field_validator("messageId")
    @classmethod
    def validate_message_id(cls, v: str) -> str:
        """Enforce non-empty messageId for sender-side deduplication."""
        if not v or not v.strip():
            raise ValueError("messageId must be a non-empty string")
        return v



# [FIXED BUG 9] sanitise_payload now returns the cleaned dict, not raw.
def sanitise_payload(raw: dict) -> tuple[dict, list[str]]:
    """
    Strip zero-width injection characters and enforce the 512KB serialized cap.

    Returns (sanitised_dict, warnings). Raises ValueError on oversized payload.
    Does not reject on anomaly — strips and logs warnings so valid messages
    from slightly non-conformant callers are not blocked.

    Note: this check runs on the serialized form after request.json() has already
    consumed the body. A Content-Length guard at the ASGI/proxy level should be
    the primary size enforcement; this is a secondary serialized-size check.
    """
    warnings: list[str] = []
    ZERO_WIDTH = {"\u200b", "\u200c", "\u200d", "\ufeff", "\u2060"}

    payload_str = json.dumps(raw, ensure_ascii=False)

    # Secondary size cap (primary should be proxy/ASGI Content-Length limit)
    if len(payload_str.encode("utf-8")) > 512 * 1024:
        raise ValueError(f"Payload too large: {len(payload_str.encode())} bytes")

    clean_str = payload_str
    for char in ZERO_WIDTH:
        if char in clean_str:
            warnings.append(f"Stripped zero-width character U+{ord(char):04X}")
            clean_str = clean_str.replace(char, "")

    # [FIXED] Parse cleaned string back to dict — not returning raw
    try:
        return json.loads(clean_str), warnings
    except json.JSONDecodeError as e:
        raise ValueError(f"Payload undeserializable after sanitisation: {e}")
