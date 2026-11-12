"""The three study-guide agents: their slot, the outline's schema, and prompts
that still describe the contract (`models/study_guide.py`)."""

from __future__ import annotations

import json
import re
import typing

import pytest
from pydantic import BaseModel, BeforeValidator, ValidationError

from agents import study_guide as agents
from agents.study_guide import (
    BLOCK_REWRITE_MARKER,
    MAX_OUTLINE_SECTIONS,
    GuideOutline,
    study_guide_block_agent,
    study_guide_outline_agent,
    study_guide_section_agent,
)
from models.study_guide import BLOCK_TYPES, Block
from services.prompt_safety import INJECTION_GUARD_PROMPT
from services.study_guides.markup import parse_block
from tests.test_agent_output_schemas import schema_violations

AGENTS = {
    "outline": study_guide_outline_agent,
    "section": study_guide_section_agent,
    "block": study_guide_block_agent,
}
PROMPTS = {
    "outline": agents._OUTLINE_PROMPT,
    "section": agents._SECTION_PROMPT,
    "block": agents._BLOCK_PROMPT,
}


def _section(**fields) -> dict:
    return {"title": "Loops", "one_line": "A loop repeats a block.", **fields}


def _outline(**fields) -> dict:
    return {
        "title": "Control flow",
        "deck": "What the midterm covers.",
        "takeaways": ["One.", "Two.", "Three."],
        "sections": [_section()],
        **fields,
    }


# ── The agents ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("name", sorted(AGENTS))
def test_agent_runs_on_the_study_guide_slot(name):
    # The slot a real model was built for (agents/_providers.py): it decides
    # the model, the effort and the timeout. No slot of their own is intended.
    assert AGENTS[name].model._res_task == "study_guide"


def test_only_the_outline_is_structured():
    assert study_guide_outline_agent.output_type is GuideOutline
    assert study_guide_section_agent.output_type is str
    assert study_guide_block_agent.output_type is str


@pytest.mark.parametrize("name", sorted(PROMPTS))
def test_every_prompt_carries_the_injection_guard(name):
    assert INJECTION_GUARD_PROMPT in PROMPTS[name]


# ── The outline ───────────────────────────────────────────────────────────────


def test_outline_schema_is_within_the_structured_output_budget():
    assert schema_violations(GuideOutline) == []


def test_outline_optional_fields_default_to_null():
    (section,) = GuideOutline.model_validate(_outline()).sections

    assert section.concept is None
    assert section.keep_id is None


def test_outline_clips_what_claude_cannot_bound():
    outline = GuideOutline.model_validate(
        _outline(
            deck="word " * 100,
            takeaways=["One.", "Two.", "Three.", "Four."],
            sections=[_section(title=f"Section {n}") for n in range(MAX_OUTLINE_SECTIONS + 3)],
        )
    )

    assert len(outline.deck) <= 240
    assert outline.takeaways == ["One.", "Two.", "Three."]
    assert [s.title for s in outline.sections] == [
        f"Section {n}" for n in range(MAX_OUTLINE_SECTIONS)
    ]


def test_outline_needs_a_section_and_keeps_names_strict():
    with pytest.raises(ValidationError):
        GuideOutline.model_validate(_outline(sections=[]))
    # A clipped concept name would no longer match the student's tree.
    with pytest.raises(ValidationError):
        GuideOutline.model_validate(_outline(sections=[_section(concept="x" * 121)]))


def test_outline_prompt_names_every_field_it_asks_for():
    for field in ("title", "deck", "takeaways", "concept", "one_line", "keep_id"):
        assert field in PROMPTS["outline"]
    assert "CONCEPTS" in PROMPTS["outline"]
    assert "CURRENT OUTLINE" in PROMPTS["outline"]


# ── The block samples the prompts print ───────────────────────────────────────


def test_there_is_one_sample_and_one_rule_per_block_type():
    assert tuple(agents._BLOCK_SHAPES) == BLOCK_TYPES
    assert set(agents._BLOCK_RULES) == set(BLOCK_TYPES)


@pytest.mark.parametrize("kind", BLOCK_TYPES)
def test_block_sample_is_a_valid_block_of_its_type(kind):
    """The sample is what the model is told to write. If the contract moves
    and the prompt does not, the sample stops validating here."""
    reply = f"```block\n{json.dumps(agents._BLOCK_SHAPES[kind])}\n```"

    block = parse_block(reply, block_id="s1-i1", sources={"S1": "document:d1"})

    assert block is not None and block.type == kind


@pytest.mark.parametrize("kind", BLOCK_TYPES)
def test_block_sample_never_shows_a_server_owned_field(kind):
    sample = agents._BLOCK_SHAPES[kind]

    assert not {"id", "illustrative", "source_id"} & set(sample)
    assert all("evidence" not in mistake for mistake in sample.get("mistakes", []))


@pytest.mark.parametrize("name", ["section", "block"])
@pytest.mark.parametrize("kind", BLOCK_TYPES)
def test_writer_prompts_describe_every_block_type(name, kind):
    prompt = PROMPTS[name]

    assert json.dumps(agents._BLOCK_SHAPES[kind]) in prompt
    assert agents._BLOCK_RULES[kind] in prompt


# ── The limits a block is rejected for breaking ───────────────────────────────

BLOCK_MODELS = {model.model_fields["type"].default: model for model in typing.get_args(Block)}
#: Set by the server; the model is told never to write them.
SERVER_OWNED = {"id", "evidence"}


def _models_in(annotation) -> list[type[BaseModel]]:
    """Every model named anywhere in a field's annotation."""
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return [annotation]
    return [m for arg in typing.get_args(annotation) for m in _models_in(arg)]


def _strict_limits(model: type[BaseModel]) -> set[tuple[str, int]]:
    """`(field, max length)` for every string the model writes that is rejected
    when too long: a `max_length` with no clip in front of it. Nested models
    are walked too."""
    limits: set[tuple[str, int]] = set()
    for name, field in model.model_fields.items():
        for nested in _models_in(field.annotation):
            limits |= _strict_limits(nested)
        clipped = any(isinstance(m, BeforeValidator) for m in field.metadata)
        is_text = str in (field.annotation, *typing.get_args(field.annotation))
        longest = next((m.max_length for m in field.metadata if hasattr(m, "max_length")), None)
        if is_text and longest and not clipped and name not in SERVER_OWNED:
            limits.add((name, longest))
    return limits


def test_the_limit_walk_finds_strict_fields_and_skips_clipped_ones():
    worked = _strict_limits(BLOCK_MODELS["worked_example"])
    assert worked == {("title", 80), ("math", 200)}
    chart = _strict_limits(BLOCK_MODELS["chart"])
    assert {("label", 40), ("label", 24), ("x_label", 32), ("x_label", 16)} <= chart
    assert not any(name == "alt" for name, _ in chart)


@pytest.mark.parametrize("kind", BLOCK_TYPES)
def test_block_rules_state_every_strict_length_limit(kind):
    """An overshoot of a strict limit rejects the whole block, so the writer
    is told each one: the field's name and its limit in the same sentence of
    the block's rule (or, for a title, of the rule every block shares)."""
    stated = f"{agents._BLOCK_RULES[kind]} {agents._TITLE_RULE}"
    limits = _strict_limits(BLOCK_MODELS[kind])

    assert limits
    for name, longest in sorted(limits):
        assert re.search(rf"\b{name}\b[^.]*\b{longest} characters", stated), (
            f"{kind}: the rule does not say that {name} is at most {longest} characters"
        )


@pytest.mark.parametrize("name", ["section", "block"])
def test_writer_prompts_carry_the_shared_title_limit_and_the_json_escaping_rule(name):
    assert agents._TITLE_RULE in PROMPTS[name]
    # As the model reads it: each LaTeX backslash doubled inside a JSON string.
    assert r"written twice (\\frac, \\neq)" in PROMPTS[name]


def test_a_comparison_row_has_exactly_one_cell_per_column():
    assert "exactly one cell per column" in agents._BLOCK_RULES["comparison"]


# ── The rules the server relies on the prompt for ─────────────────────────────


def test_section_prompt_defines_the_markup():
    prompt = PROMPTS["section"]

    assert "```block" in prompt
    assert '">> "' in prompt
    assert "[S2]" in prompt
    assert "**base case**" in prompt


def test_section_prompt_allows_a_code_sample_only_in_a_fence_that_names_its_language():
    prompt = PROMPTS["section"]

    assert "```python" in prompt
    assert "always name the language" in prompt
    assert "code fences in prose" not in prompt


def test_check_explanations_do_not_repeat_the_readers_verdict():
    rule = agents._BLOCK_RULES["check"]

    assert 'Do not begin explain_correct with "Correct"' in rule
    assert '"Not quite"' in rule


def test_section_prompt_states_the_grounding_rules():
    prompt = PROMPTS["section"]

    assert "QUIZ HISTORY" in agents._BLOCK_RULES["mistakes"]
    assert "evidence_id" in agents._BLOCK_RULES["mistakes"]
    assert "CONCEPTS" in agents._BLOCK_RULES["concept_map"]
    assert "at most one check" in agents._BLOCK_RULES["check"]
    assert "only numbers that appear in the source" in agents._BLOCK_RULES["chart"]
    assert "page or slide number" in prompt
    for word in ("cram", "standard", "deep", "practice", "review", "exam prep"):
        assert f"- {word}:" in prompt


def test_only_the_block_prompt_carries_the_rewrite_marker():
    assert BLOCK_REWRITE_MARKER in PROMPTS["block"]
    assert BLOCK_REWRITE_MARKER not in PROMPTS["section"]
    assert BLOCK_REWRITE_MARKER not in PROMPTS["outline"]
