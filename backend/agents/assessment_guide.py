"""One grounded outline supplies the guide, checklist and study schedule."""
import hashlib
from typing import Annotated

from pydantic import ConfigDict, Field
from pydantic_ai import Agent, ModelRetry, RunContext
from pydantic_ai.settings import ModelSettings

from agents._providers import model_for
from agents.topic_checklist import (
    ChecklistTopic, TopicOutline, SYSTEM_PROMPT, CHECKLIST_MAX_OUTPUT_TOKENS,
    CHECKLIST_REQUEST_TIMEOUT_SECONDS, CHECKLIST_OUTPUT_RETRIES,
)
from agents.topic_checklist_model import wrap_topic_checklist_model


def _simple_generation_schema(schema: dict) -> None:
    """Avoid Gemini's combinatorial grammar limits; Pydantic still enforces bounds.

    Nested min/max array and string constraints multiply the provider's schema
    states. Remove them only from the wire schema, never from local validation.
    The full-request counter sees this same schema and token limits still apply.
    """
    for key in ("minLength", "maxLength", "minItems", "maxItems", "minimum", "maximum"):
        schema.pop(key, None)
    for value in schema.values():
        if isinstance(value, dict):
            _simple_generation_schema(value)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    _simple_generation_schema(item)


class GuideTopic(ChecklistTopic):
    model_config = ConfigDict(json_schema_extra=_simple_generation_schema)
    study_points: list[Annotated[str, Field(min_length=1, max_length=500)]] = Field(min_length=1, max_length=5,
        description="Concise concepts or questions to understand, supported by the cited material.")


class AssessmentGuide(TopicOutline):
    model_config = ConfigDict(json_schema_extra=_simple_generation_schema)
    overview: str = Field(min_length=1, max_length=1200)
    topics: list[GuideTopic] = Field(max_length=60)


PROMPT = SYSTEM_PROMPT + (
    " This outline is the student's combined assessment study guide and plan. "
    "Focus on the supplied assessment coverage and selected materials. "
    "Provide a short overview of what to study and how the topics relate, plus "
    "1–5 concise study points per topic: concepts to explain, distinctions to "
    "understand or questions to practice. Ground all points in the topic's cited "
    "sources. Do not invent worked answers or unsupported facts. Do not claim "
    "student mastery or generate dates; those come from the application. "
    "If no academic topics are supported, return no topics and explain the missing context."
)
assessment_guide_agent = Agent(
    model=wrap_topic_checklist_model(model_for("assessment_guide")), deps_type=dict,
    output_type=AssessmentGuide, retries=CHECKLIST_OUTPUT_RETRIES, system_prompt=PROMPT,
    model_settings=ModelSettings(max_tokens=CHECKLIST_MAX_OUTPUT_TOKENS, timeout=CHECKLIST_REQUEST_TIMEOUT_SECONDS),
    metadata={"agent": "topic_checklist", "purpose": "assessment_guide",
              "prompt_version": hashlib.sha256(PROMPT.encode()).hexdigest()[:12]},
)


@assessment_guide_agent.output_validator
def validate_sources(ctx: RunContext[dict], outline: AssessmentGuide) -> AssessmentGuide:
    sources = {s["id"] for s in ctx.deps["sources"]}
    assessments = {a["id"] for a in ctx.deps["assessments"]}
    if any(not set(t.source_ids) <= sources or not set(t.assessment_ids) <= assessments for t in outline.topics):
        raise ModelRetry("Only cite sources and assessments in the supplied context.")
    return outline
