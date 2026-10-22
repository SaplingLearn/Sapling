"""The topic-checklist agent's model-facing schema carries no array-length bounds.

Gemini serves structured output by compiling the schema into a constrained-
decoding automaton, and array bounds multiply its state count: a `maxItems`
on a list nested inside another bounded list is repeated per outer item.
#726 shipped `topics` (maxItems=60) holding `prerequisites` (10),
`source_ids` (1..30) and `assessment_ids` (20), and every live refresh 400'd
on gemini-2.5-flash with "too many states for serving" (503 at the route).

Measured live 2026-10-19 against the real agent (prompt, model slot, output
validator): current schema -> 400; array bounds removed, string bounds kept
-> served; string bounds removed, array bounds kept -> 400. So the array caps
now live in OUR validation (`agents/topic_checklist.py` clips after the call,
keeping the first N in model order — what decoding-time `maxItems` did) and
the schema Gemini compiles has none. The string and `importance` bounds are
served fine and stay on the fields.

The live counterpart is tests/test_live_topic_checklist_schema.py. Same fix
shape as the quiz agent's (#729, tests/test_quiz_schema_states.py).
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from agents.topic_checklist import (
    MAX_ASSESSMENT_IDS,
    MAX_PREREQUISITES,
    MAX_SOURCE_IDS,
    MAX_TOPICS,
    ChecklistTopic,
    TopicOutline,
    topic_checklist_agent,
)

_ARRAY_LENGTH_KEYWORDS = {"maxItems", "minItems"}


def _topic(n: int = 0, **overrides) -> dict:
    topic = {
        "name": f"Topic {n}",
        "description": f"What topic {n} covers.",
        "importance": 0.5,
        "source_ids": ["s1"],
    }
    topic.update(overrides)
    return topic


def _array_keywords(schema) -> set[str]:
    found: set[str] = set()
    if isinstance(schema, dict):
        found |= _ARRAY_LENGTH_KEYWORDS & schema.keys()
        for value in schema.values():
            found |= _array_keywords(value)
    elif isinstance(schema, list):
        for value in schema:
            found |= _array_keywords(value)
    return found


def _deps(sources=("s1",), assessments=()) -> dict:
    return {
        "sources": [{"id": s, "label": s, "text": s} for s in sources],
        "assessments": [{"id": a} for a in assessments],
    }


# ── The schema Gemini sees ──────────────────────────────────────────────────


def test_outline_json_schema_has_no_array_length_constraints():
    assert _array_keywords(TopicOutline.model_json_schema()) == set()


def test_final_result_tool_sent_to_the_model_has_no_array_length_constraints():
    """Pin the definition pydantic-ai actually hands the model (the
    `final_result` function declaration), not just the Pydantic schema."""
    seen: dict = {}

    def handler(messages, info: AgentInfo) -> ModelResponse:
        seen["output_tools"] = info.output_tools
        return ModelResponse(parts=[ToolCallPart(
            tool_name=info.output_tools[0].name, args={"topics": [_topic()]},
        )])

    with topic_checklist_agent.override(model=FunctionModel(handler)):
        result = topic_checklist_agent.run_sync("{}", deps=_deps())

    assert [t.name for t in result.output.topics] == ["Topic 0"]
    [output_tool] = seen["output_tools"]
    assert _array_keywords(output_tool.parameters_json_schema) == set(), json.dumps(
        output_tool.parameters_json_schema, indent=1
    )


# ── The caps, enforced after the call ───────────────────────────────────────


def test_caps_are_unchanged_from_726():
    assert (MAX_TOPICS, MAX_PREREQUISITES, MAX_SOURCE_IDS, MAX_ASSESSMENT_IDS) == (60, 10, 30, 20)


def test_over_cap_topics_are_clipped_in_order():
    outline = TopicOutline.model_validate({"topics": [_topic(i) for i in range(MAX_TOPICS + 5)]})
    assert [t.name for t in outline.topics] == [f"Topic {i}" for i in range(MAX_TOPICS)]


def test_over_cap_topic_lists_are_clipped_in_order():
    names = [f"P{i}" for i in range(MAX_PREREQUISITES + 3)]
    topic = ChecklistTopic.model_validate(_topic(
        prerequisites=names,
        source_ids=[f"s{i}" for i in range(MAX_SOURCE_IDS + 3)],
        assessment_ids=[f"a{i}" for i in range(MAX_ASSESSMENT_IDS + 3)],
    ))
    assert topic.prerequisites == names[:MAX_PREREQUISITES]
    assert topic.source_ids == [f"s{i}" for i in range(MAX_SOURCE_IDS)]
    assert topic.assessment_ids == [f"a{i}" for i in range(MAX_ASSESSMENT_IDS)]


def test_a_topic_without_sources_is_still_a_validation_error():
    """minItems=1 left the schema, not the contract: every topic must cite
    evidence, so an uncited topic still fails and the output retry fires."""
    with pytest.raises(ValidationError):
        ChecklistTopic.model_validate(_topic(source_ids=[]))


def test_a_reference_to_a_clipped_topic_is_dropped_not_fatal():
    """Under decoding-time maxItems the model could never name topic 61, so a
    kept topic pointing at a clipped one is an artefact of the clip: the
    reference goes (a clipped parent leaves the topic at the root) instead of
    failing the whole outline and spending a retry on a topic it did return."""
    topics = [_topic(i) for i in range(MAX_TOPICS)]
    topics[0]["prerequisites"] = ["Overflow", "Topic 1"]
    topics[2]["parent"] = "overflow"
    outline = TopicOutline.model_validate({"topics": topics + [_topic(name="Overflow")]})
    assert len(outline.topics) == MAX_TOPICS
    assert outline.topics[0].prerequisites == ["Topic 1"]
    assert outline.topics[2].parent == ""


def test_a_reference_to_a_topic_never_returned_is_still_a_hierarchy_error():
    topics = [_topic(i) for i in range(3)]
    topics[0]["prerequisites"] = ["Nowhere"]
    with pytest.raises(ValidationError):
        TopicOutline.model_validate({"topics": topics})


def test_over_cap_output_is_clipped_without_spending_a_retry():
    calls = {"n": 0}

    def handler(messages, info: AgentInfo) -> ModelResponse:
        calls["n"] += 1
        return ModelResponse(parts=[ToolCallPart(
            tool_name=info.output_tools[0].name,
            args={"topics": [
                _topic(i, source_ids=["s1"] * (MAX_SOURCE_IDS + 2)) for i in range(MAX_TOPICS + 2)
            ]},
        )])

    with topic_checklist_agent.override(model=FunctionModel(handler)):
        result = topic_checklist_agent.run_sync("{}", deps=_deps())

    assert calls["n"] == 1
    assert len(result.output.topics) == MAX_TOPICS
    assert all(len(t.source_ids) == MAX_SOURCE_IDS for t in result.output.topics)


def test_malformed_surplus_past_the_caps_is_discarded_not_fatal():
    """Clipping runs BEFORE item validation, as decoding-time maxItems did:
    surplus a bounded schema never generated must not reject the valid
    prefix (and spend an output retry) now either."""
    outline = TopicOutline.model_validate({"topics": [
        _topic(i, source_ids=["s1"] * MAX_SOURCE_IDS + [None],
               assessment_ids=["a1"] * MAX_ASSESSMENT_IDS + [{"bad": 1}],
)
        for i in range(MAX_TOPICS)
    ] + [{"name": "malformed surplus, missing every other field"}]})
    assert len(outline.topics) == MAX_TOPICS
    assert all(len(t.source_ids) == MAX_SOURCE_IDS for t in outline.topics)
    assert all(len(t.assessment_ids) == MAX_ASSESSMENT_IDS for t in outline.topics)
    topic = ChecklistTopic.model_validate(_topic(prerequisites=[f"P{i}" for i in range(MAX_PREREQUISITES)] + [7]))
    assert topic.prerequisites == [f"P{i}" for i in range(MAX_PREREQUISITES)]
