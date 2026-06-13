"""
Intake Personal Agent (Tier 1).

Classifies inbound customer messages into structured IntakeClassification objects.
Uses no tools — avoids the ADK output_schema + tools conflict (Trap 1).
"""
from typing import Literal

from google.adk.agents import LlmAgent
from google.genai import types
from pydantic import BaseModel, Field

from config import (
    INTAKE_MAX_TOKENS,
    INTAKE_MODEL,
    INTAKE_TEMPERATURE,
)


class IntakeClassification(BaseModel):
    """Structured output of the Tier 1 personal agent."""

    intent: Literal[
        "billing_dispute",
        "technical_support",
        "order_status",
        "product_return",
        "general_inquiry",
        "escalation_required",
    ]
    session_id: str
    task_id: str
    confidence: float = Field(ge=0.0, le=1.0)
    requires_research: bool
    extracted_account_id: str | None = None
    sanitised_summary: str = Field(
        description=(
            "Compressed 1-2 sentence version of the customer message. "
            "This is the ONLY form of the raw message that travels downstream. "
            "Never pass raw customer text further."
        )
    )


# No tools. output_schema only. No model-dependency on SetModelResponseTool.
personal_agent = LlmAgent(
    model=INTAKE_MODEL,
    name="personal_agent",
    instruction="""You are a classification-only intake processor.

Your ONLY job is to classify the incoming message and produce a structured output.
Do NOT attempt to resolve the issue. Do NOT generate customer-facing responses.

Steps:
1. Classify intent from the allowed literal values.
2. Extract account_id if present (ACC-XXXXX format, order numbers, account numbers).
3. Write a sanitised_summary in 1-2 sentences of plain English. Include account_id only.
4. Set requires_research=True for: product specs, policy questions, compatibility,
   pricing, warranty info — anything needing external knowledge.
5. Set confidence based on the clarity of the intent signal (0.0-1.0).
6. Copy session_id and task_id unchanged from your context. Do not generate new ones.

Do not output free text. Produce only the structured classification.""",
    output_schema=IntakeClassification,
    output_key="intake_classification",
    include_contents="none",
    generate_content_config=types.GenerateContentConfig(
        temperature=INTAKE_TEMPERATURE,
        max_output_tokens=INTAKE_MAX_TOKENS,
    ),
)
