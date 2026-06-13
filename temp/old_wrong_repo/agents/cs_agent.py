"""
Customer Service Agents (Tier 2) — Two-Stage Pattern.

Stage A (cs_reasoning_agent): tool-using reasoning. No output_schema.
Stage B (cs_formatter_agent): schema formatting. No tools.

Separating the two stages avoids the ADK Trap 1 conflict where combining
output_schema with tools causes unpredictable LLM parsing failures.
"""
from typing import Literal

from google.adk.agents import LlmAgent
from google.genai import types
from pydantic import BaseModel, Field

from config import (
    FORMATTER_MAX_TOKENS,
    FORMATTER_MODEL,
    FORMATTER_TEMPERATURE,
    REASONING_MAX_TOKENS,
    REASONING_MODEL,
    REASONING_TEMPERATURE,
)
from tools.account_tools import (
    check_return_eligibility,
    fetch_account_data,
    get_policy_document,
    lookup_order_status,
    write_resolution_draft,
)


class ResolutionPayloadPublic(BaseModel):
    """Customer-facing resolution schema."""
    resolution_status: Literal["resolved", "partial", "escalated", "requires_input"]
    resolution_summary: str = Field(description="Customer-facing text, max 300 words")
    follow_up_actions: list[str] = Field(default_factory=list)

class ResolutionPayloadInternal(ResolutionPayloadPublic):
    """Structured resolution output produced by the CS formatter agent."""
    internal_notes: str
    confidence_score: float = Field(ge=0.0, le=1.0)
    requires_human_review: bool
    missing_context: list[str] = Field(default_factory=list)


# Stage A: Tool-using reasoning agent. NO output_schema.
# Writes resolution draft to session.state via write_resolution_draft tool.
cs_reasoning_agent = LlmAgent(
    model=REASONING_MODEL,
    name="cs_reasoning_agent",
    instruction="""You are a customer service resolution specialist.

Context:
- Intake classification: {intake_classification}
- Research evidence: {research_results}
- Account context: {account_context}

Research evidence rules:
- If any research entry has result_type='error' or confidence=0.0, treat external
  retrieval as FAILED for that query — do not cite policy, product facts, or URLs
  from that entry.
- If research evidence contains a SYSTEM ERROR message, acknowledge missing context
  explicitly in your draft and escalate or request more input rather than guessing.

Resolve the customer's issue using your tools. When complete, call
write_resolution_draft with your full resolution. Do NOT write free text.
ONLY call write_resolution_draft as your final action.
""",
    tools=[
        fetch_account_data,
        lookup_order_status,
        check_return_eligibility,
        get_policy_document,
        write_resolution_draft,
    ],
    include_contents="none",
    generate_content_config=types.GenerateContentConfig(
        temperature=REASONING_TEMPERATURE, max_output_tokens=REASONING_MAX_TOKENS
    ),
)

# Stage B: Formatter agent. output_schema only. NO tools.
# Reads resolution_draft from session.state written by Stage A.
cs_formatter_agent = LlmAgent(
    model=FORMATTER_MODEL,
    name="cs_formatter_agent",
    instruction="""Format the resolution draft into the required structured output.

Draft data: {resolution_draft}

Produce a complete ResolutionPayload. Follow the schema exactly.
Every field is required. missing_context and follow_up_actions default to [].
""",
    output_schema=ResolutionPayloadInternal,
    output_key="resolution_payload",
    include_contents="none",
    generate_content_config=types.GenerateContentConfig(
        temperature=FORMATTER_TEMPERATURE, max_output_tokens=FORMATTER_MAX_TOKENS
    ),
)
