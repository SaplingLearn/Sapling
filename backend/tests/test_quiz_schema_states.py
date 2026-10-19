"""The quiz agent's model-facing schema carries no array-length constraints.

Gemini serves structured output by compiling the schema into a constrained-
decoding automaton, and array bounds multiply its state count: every
`maxItems` on a list nested inside another bounded list is repeated per outer
item. Once #726 added `accepted_answers` (maxItems=8) next to `options`
(maxItems=4) inside `questions` (minItems=1, maxItems=10), the `final_result`
function declaration — unioned with the three read tools under
function-calling mode ANY — crossed gemini-2.5-flash-lite's limit and every
live quiz request 400'd with "too many states for serving" before generating
anything (502 at the route).

Measured live 2026-10-19 against the real request shape (three read tools +
`final_result`, mode ANY): all three bounds -> 400; any one of the two
nestings removed -> served; no bounds -> served. So the bounds now live in
OUR validation (`agents/quiz.py` clips deterministically after the call) and
the schema Gemini compiles has none. These tests pin both halves: the schema
stays bound-free, and the caps still hold on what the route receives.

The live counterpart is tests/test_live_quiz_schema.py.
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from agents.deps import SaplingDeps
from agents.quiz import (
    MAX_ACCEPTED_ANSWERS,
    MAX_OPTIONS,
    MAX_QUESTIONS,
    Quiz,
    QuizQuestion,
    quiz_agent,
)

# Every JSON-schema keyword that bounds a length. Strings already carry none
# (see QuizQuestion's note); arrays must not either.
_LENGTH_KEYWORDS = {"maxItems", "minItems", "maxLength", "minLength"}


def _mcq(n: int = 0, **overrides) -> dict:
    item = {
        "question": f"Which option is right ({n})?",
        "type": "multiple_choice",
        "difficulty": "medium",
        "options": ["a", "b", "c", "d"],
        "correct_answer": "a",
        "explanation": "Because a.",
        "concept": "Pointers",
    }
    item.update(overrides)
    return item


def _length_keywords(schema) -> set[str]:
    found: set[str] = set()
    if isinstance(schema, dict):
        found |= _LENGTH_KEYWORDS & schema.keys()
        for value in schema.values():
            found |= _length_keywords(value)
    elif isinstance(schema, list):
        for value in schema:
            found |= _length_keywords(value)
    return found


def _deps() -> SaplingDeps:
    return SaplingDeps(user_id="u", course_id="c", supabase=None, request_id="t")


# ── The schema Gemini sees ──────────────────────────────────────────────────


def test_quiz_json_schema_has_no_length_constraints():
    assert _length_keywords(Quiz.model_json_schema()) == set()


def test_final_result_tool_sent_to_the_model_has_no_length_constraints():
    """Pin the definition pydantic-ai actually hands the model, not just the
    Pydantic schema: this is the `final_result` function declaration the
    Google model sends (tool output mode; never native response_schema)."""
    seen: dict = {}

    def handler(messages, info: AgentInfo) -> ModelResponse:
        seen["output_tools"] = info.output_tools
        seen["function_tools"] = info.function_tools
        return ModelResponse(parts=[ToolCallPart(
            tool_name=info.output_tools[0].name,
            args={"questions": [_mcq()]},
        )])

    with quiz_agent.override(model=FunctionModel(handler)):
        result = quiz_agent.run_sync("quiz me", deps=_deps())

    assert len(result.output.questions) == 1
    [output_tool] = seen["output_tools"]
    assert output_tool.name == "final_result"
    assert _length_keywords(output_tool.parameters_json_schema) == set(), json.dumps(
        output_tool.parameters_json_schema, indent=1
    )
    # The read tools ride in the same request (mode ANY unions them); keep
    # them bound-free too so they never add to the state budget.
    for tool in seen["function_tools"]:
        assert _length_keywords(tool.parameters_json_schema) == set(), tool.name


# ── The caps, enforced after the call ───────────────────────────────────────


def test_caps_match_the_product_and_route_contracts():
    from routes.quiz import _MCQ_OPTIONS
    from services.quiz_config import QUIZ_MAX_QUESTIONS

    assert MAX_QUESTIONS == QUIZ_MAX_QUESTIONS == 10
    assert MAX_OPTIONS == _MCQ_OPTIONS == 4
    assert MAX_ACCEPTED_ANSWERS == 8


def test_valid_output_is_unchanged():
    body = {"questions": [
        _mcq(i) for i in range(MAX_QUESTIONS - 1)
    ] + [{
        **_mcq(99, type="short_answer", options=[], correct_answer="base case"),
        "accepted_answers": [f"alias {i}" for i in range(MAX_ACCEPTED_ANSWERS)],
    }]}
    quiz = Quiz.model_validate(body)
    assert quiz.model_dump(exclude_defaults=False) == Quiz.model_validate(
        quiz.model_dump()
    ).model_dump()
    assert [q.question for q in quiz.questions] == [q["question"] for q in body["questions"]]
    assert quiz.questions[0].options == ["a", "b", "c", "d"]
    assert quiz.questions[-1].accepted_answers == body["questions"][-1]["accepted_answers"]


def test_over_cap_questions_are_clipped_in_order():
    quiz = Quiz.model_validate({"questions": [_mcq(i) for i in range(MAX_QUESTIONS + 5)]})
    assert [q.question for q in quiz.questions] == [
        _mcq(i)["question"] for i in range(MAX_QUESTIONS)
    ]


def test_over_cap_options_are_clipped_in_order():
    q = QuizQuestion.model_validate(_mcq(options=["a", "b", "c", "d", "e", "f"]))
    assert q.options == ["a", "b", "c", "d"]


def test_over_cap_accepted_answers_are_clipped_in_order():
    aliases = [f"alias {i}" for i in range(MAX_ACCEPTED_ANSWERS + 4)]
    q = QuizQuestion.model_validate(
        _mcq(type="short_answer", options=[], accepted_answers=aliases)
    )
    assert q.accepted_answers == aliases[:MAX_ACCEPTED_ANSWERS]


def test_empty_quiz_is_still_a_validation_error():
    """minItems=1 left the schema, not the contract: an empty quiz still
    fails validation, so the agent's bounded output retry still fires."""
    with pytest.raises(ValidationError):
        Quiz.model_validate({"questions": []})


def test_clipped_mcq_keeps_the_route_per_item_contract():
    """Clipping can only shorten a list; the route's per-item checks still
    decide each item. A sixth-option correct answer clipped away is dropped
    on its own, never fatal to the quiz."""
    from routes.quiz import _agent_question_to_wire

    quiz = Quiz.model_validate({"questions": [
        _mcq(1, options=["a", "b", "c", "d", "e"]),
        _mcq(2, options=["a", "b", "c", "d", "e"], correct_answer="e"),
    ]})
    kept = _agent_question_to_wire(quiz.questions[0], 1)
    assert kept is not None and [o["text"] for o in kept["options"]] == ["a", "b", "c", "d"]
    assert _agent_question_to_wire(quiz.questions[1], 2) is None


def test_over_cap_output_is_clipped_without_spending_a_retry():
    """Before: an 11-question or 5-option output failed Quiz validation and
    burned the agent's output retries (502 after two more). Now it is
    clipped on the first response."""
    calls = {"n": 0}

    def handler(messages, info: AgentInfo) -> ModelResponse:
        calls["n"] += 1
        return ModelResponse(parts=[ToolCallPart(
            tool_name=info.output_tools[0].name,
            args={"questions": [
                _mcq(i, options=["a", "b", "c", "d", "e"]) for i in range(MAX_QUESTIONS + 2)
            ]},
        )])

    with quiz_agent.override(model=FunctionModel(handler)):
        result = quiz_agent.run_sync("quiz me", deps=_deps())

    assert calls["n"] == 1
    assert len(result.output.questions) == MAX_QUESTIONS
    assert all(q.options == ["a", "b", "c", "d"] for q in result.output.questions)


def test_malformed_surplus_past_the_caps_is_discarded_not_fatal():
    """Clipping runs BEFORE item validation, as decoding-time maxItems
    did: a malformed eleventh question, fifth option or ninth alias is
    never generated under a bounded schema, so it must not reject the valid
    prefix (and spend an output retry) now either."""
    body = {"questions": [
        _mcq(i, options=["a", "b", "c", "d", {"not": "a string"}],
             accepted_answers=[f"alias {k}" for k in range(MAX_ACCEPTED_ANSWERS)] + [None])
        for i in range(MAX_QUESTIONS)
    ] + [{"question": "malformed surplus, missing every other field"}]}
    quiz = Quiz.model_validate(body)
    assert len(quiz.questions) == MAX_QUESTIONS
    assert all(q.options == ["a", "b", "c", "d"] for q in quiz.questions)
    assert all(len(q.accepted_answers) == MAX_ACCEPTED_ANSWERS for q in quiz.questions)


def test_malformed_item_inside_the_caps_is_still_a_validation_error():
    with pytest.raises(ValidationError):
        Quiz.model_validate({"questions": [_mcq(0), {"question": "missing fields"}]})
