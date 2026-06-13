"""
Research Formatter Agents (Tier 3).

Three instances are defined:
- research_formatter       : generic single-use formatter
- research_formatter_0/1   : concurrency-safe parallel instances with isolated
                             input/output state keys to prevent race conditions
                             (Trap 11) when asyncio.gather runs both concurrently.
"""
from typing import Literal

from google.adk.agents import LlmAgent
from google.genai import types
from pydantic import BaseModel, Field

from config import RESEARCH_MAX_TOKENS, RESEARCH_MODEL, RESEARCH_TEMPERATURE


class ResearchResult(BaseModel):
    """Structured knowledge artifact produced by a research formatter agent."""

    query_answered: str
    answer: str
    sources: list[str]
    confidence: float = Field(ge=0.0, le=1.0)
    result_type: Literal["policy", "product_info", "procedure", "general", "error"]


_RESEARCH_INSTRUCTION_TEMPLATE = """Synthesise the provided search results into a structured knowledge artifact.

Search query: {{{query_key}}}
Raw search results: {{{results_key}}}

Produce a ResearchResult. Be factual. Include source URLs from the results.
Assign confidence 0.0-1.0 based on source quality and answer directness.
If raw_search_results contains a SYSTEM ERROR message, set result_type='error'
and confidence=0.0 and reproduce the error message in the answer field.
"""

_SHARED_CONFIG = types.GenerateContentConfig(
    temperature=RESEARCH_TEMPERATURE, max_output_tokens=RESEARCH_MAX_TOKENS
)

# Generic formatter (single-use, not parallel-safe)
research_formatter = LlmAgent(
    model=RESEARCH_MODEL,
    name="research_agent",
    instruction=_RESEARCH_INSTRUCTION_TEMPLATE.format(
        query_key="research_query", results_key="raw_search_results"
    ),
    output_schema=ResearchResult,
    output_key="research_results",
    include_contents="none",
    generate_content_config=_SHARED_CONFIG,
)

# Concurrency-safe formatter 0: reads research_query_0 / raw_search_results_0
# and writes to research_results_0. Isolated from formatter_1.
research_formatter_0 = LlmAgent(
    model=RESEARCH_MODEL,
    name="research_formatter_0",
    instruction=_RESEARCH_INSTRUCTION_TEMPLATE.format(
        query_key="research_query_0", results_key="raw_search_results_0"
    ),
    output_schema=ResearchResult,
    output_key="research_results_0",
    include_contents="none",
    generate_content_config=_SHARED_CONFIG,
)

# Concurrency-safe formatter 1: reads research_query_1 / raw_search_results_1
# and writes to research_results_1. Isolated from formatter_0.
research_formatter_1 = LlmAgent(
    model=RESEARCH_MODEL,
    name="research_formatter_1",
    instruction=_RESEARCH_INSTRUCTION_TEMPLATE.format(
        query_key="research_query_1", results_key="raw_search_results_1"
    ),
    output_schema=ResearchResult,
    output_key="research_results_1",
    include_contents="none",
    generate_content_config=_SHARED_CONFIG,
)
