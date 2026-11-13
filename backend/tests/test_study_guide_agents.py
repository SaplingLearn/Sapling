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
from models.study_guide import BLOCK_TYPES, Block, GuideContent, Section
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


def test_an_over_long_title_or_takeaway_is_clipped_not_refused():
    """A refusal here would spend the outline's retries and fail the guide."""
    outline = GuideOutline.model_validate(
        _outline(
            title="word " * 40,
            takeaways=["One.", "word " * 100, "Three."],
            sections=[_section(title="word " * 40, one_line="word " * 100)],
        )
    )

    (section,) = outline.sections
    assert 100 < len(outline.title) <= 120 and 100 < len(section.title) <= 120
    assert 200 < len(outline.takeaways[1]) <= 240 and 200 < len(section.one_line) <= 240
    assert outline.takeaways[0] == "One."
    # What is stored as the guide's content holds the same limits.
    assert GuideContent(
        title=outline.title, deck=outline.deck, takeaways=outline.takeaways,
        sections=[Section(id="s1", title=section.title, one_line=section.one_line)],
    )


def test_outline_needs_a_section_and_keeps_identifiers_strict():
    with pytest.raises(ValidationError):
        GuideOutline.model_validate(_outline(sections=[]))
    # A clipped concept name would no longer match the student's tree, and a
    # clipped id would name no section.
    with pytest.raises(ValidationError):
        GuideOutline.model_validate(_outline(sections=[_section(concept="x" * 121)]))
    with pytest.raises(ValidationError):
        GuideOutline.model_validate(_outline(sections=[_section(keep_id="s" * 41)]))


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


def test_section_prompt_says_a_summary_line_is_plain_text():
    """The reader draws the Skim summary as plain text, not Markdown: marks,
    math and an escaped dollar sign would all show as written."""
    rule = " ".join(PROMPTS["section"].split())

    assert "summary line is shown as plain text" in rule
    assert "write money plainly ($4)" in rule
    assert "no ** marks and no $...$ math" in rule


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


# ── How much the section writer is asked to write ─────────────────────────────


def _said(prompt: str) -> str:
    """The prompt as the model reads it: one line, single spaces."""
    return " ".join(prompt.split())


def test_the_lengths_are_floors_and_ranges_that_fit_inside_each_other():
    words, passages = agents.SECTION_WORDS, agents.SECTION_PASSAGES
    assert words == {"cram": (90, 160), "standard": (280, 450), "deep": (500, 800)}
    assert passages == {"cram": (1, 2), "standard": (3, 4), "deep": (4, 6)}
    assert agents.PARAGRAPH_WORDS == (60, 130) and agents.PARAGRAPH_FLOOR == 40
    # A deeper guide always has more to read, and a mastered section less
    # than any other section of its guide.
    assert words["cram"][1] < words["standard"][0] and words["standard"][1] < words["deep"][0]
    assert {depth: agents.mastered_words(depth) for depth in words} == {
        "cram": (45, 90), "standard": (140, 280), "deep": (250, 500),
    }
    # The fewest passages can hold the most words: a passage is at most three
    # paragraphs (`ProseItem`), and a usual paragraph tops out at 130 words.
    for depth, (_, most) in words.items():
        assert most <= passages[depth][1] * 3 * agents.PARAGRAPH_WORDS[1]


def test_the_block_counts_fit_the_passages_and_the_words():
    """Every block has a passage of its own in front of it, so the most
    blocks a depth allows must fit its passages, and the paragraphs that
    takes (two to open, one more per further block) must fit its words."""
    usual = agents.PARAGRAPH_WORDS[0]
    for depth, most_blocks in agents.SECTION_BLOCKS.items():
        _, most_words = agents.SECTION_WORDS[depth]
        assert most_blocks <= agents.SECTION_PASSAGES[depth][1]
        floor = agents.PARAGRAPH_FLOOR if depth == "cram" else usual
        assert (2 + most_blocks - 1) * floor <= most_words, depth
    # A mastered cram section has room for its opening and the check alone.
    assert 2 * agents.PARAGRAPH_FLOOR <= agents.mastered_words("cram")[1] < 3 * agents.PARAGRAPH_FLOOR


@pytest.mark.parametrize("depth", ["cram", "standard", "deep"])
def test_section_prompt_states_each_depths_passages_and_words(depth):
    said = _said(PROMPTS["section"])
    rule = said[said.index(f"- {depth}:"):]
    rule = rule[: rule.index(" - ", 1)] if " - " in rule[1:] else rule
    fewest, most = agents.SECTION_WORDS[depth]
    low, high = agents.SECTION_PASSAGES[depth]

    assert f"{fewest} to {most} words of prose" in rule
    assert re.search(rf"\b{low} (?:or|to) {high} passages", rule)
    assert f"at most {agents.SECTION_BLOCKS[depth]} blocks, counting the check" in rule


def test_section_prompt_says_what_the_word_counts_count():
    said = _said(PROMPTS["section"])

    assert "the words of your paragraphs in the whole section" in said
    assert "Summary lines and blocks do not count" in said
    assert "A run with its summary line is one passage" in said


def test_section_prompt_states_the_paragraph_length_and_its_floor():
    said = _said(PROMPTS["section"])

    assert "normally 60 to 130 words" in said
    assert "Never write a paragraph under 40 words, and never a one-sentence paragraph" in said
    # A lead-in to a block is the end of its paragraph, never a line alone:
    # alone it would have no Skim summary, and Skim would show two blocks
    # back to back.
    assert "never set such a sentence on a line of its own" in said
    assert "bridge" not in said
    # The contract clips a paragraph, so the writer is told where.
    assert "over 1200 characters is cut off" in said


def test_section_prompt_asks_for_clear_sentences_and_never_for_brevity():
    said = _said(PROMPTS["section"])
    voice = said[said.index("VOICE"):said.index("GROUNDING")]

    assert "clear, complete sentences" in voice and "short" not in voice
    for asks_for_less in ("under about 120 words", "shortest useful", "brief setup", "One short passage"):
        assert asks_for_less not in said
    assert "Longer means more explanation, never more words around the same content" in said


def test_section_prompt_never_lets_two_blocks_touch():
    said = _said(PROMPTS["section"])

    assert "Every section opens with at least two full paragraphs before its first block" in said
    assert "Never put two blocks next to each other" in said
    assert (
        "Before every block, write at least one full paragraph that explains what the "
        "block is about to show, work through or test"
    ) in said
    assert "a section never has more blocks than passages" in said
    assert "explain, show, explain, practise, sum up, test" in said
    assert "A mistakes block follows prose about why those slips happen" in said


def test_section_prompt_closes_on_a_summing_up_and_the_check():
    said = _said(PROMPTS["section"])

    assert "The check question is the last thing in the section" in said
    assert "The paragraph before it pulls the section together" in said
    assert "what the student should now be able to do" in said


def _sample_layout() -> list[str]:
    """The SHAPE sample as the kinds of its parts, in order."""
    shape = PROMPTS["section"]
    shape = shape[shape.index("SHAPE"):shape.index("CHOOSING BLOCKS")]
    parts = [part.strip() for part in shape.split("\n\n")[1:] if part.strip()]
    return ["block" if p.startswith("```block") else "summary" if p.startswith(">> ") else "paragraph" for p in parts]


def test_the_sample_layout_follows_its_own_rules():
    layout = _sample_layout()

    assert layout[:3] == ["paragraph", "paragraph", "summary"]
    assert layout[-1] == "block" and layout.count("block") == 3
    # Every block stands directly under the summary line of its own passage:
    # never under another block, and never under a paragraph with no summary.
    assert all(layout[at - 1] == "summary" for at, kind in enumerate(layout) if kind == "block")
    assert all(layout[at - 1] == "paragraph" for at, kind in enumerate(layout) if kind == "summary")
    assert '{"type": "check"' in PROMPTS["section"].split("CHOOSING BLOCKS")[0].rsplit("```block", 1)[1]


def test_section_prompt_keeps_read_and_skim_apart():
    said = _said(PROMPTS["section"])

    assert "one or two short plain sentences, about 8 to 25 words and at most a third as long as the run" in said
    assert "the two must never look alike" in said
    # Skim hides a passage with no summary, so every passage has one.
    assert (
        'Every passage gets a ">> " line, including the short ones between blocks, so that '
        "Skim always has a sentence between two blocks"
    ) in said


def test_section_prompt_halves_a_mastered_section_and_scales_by_share():
    said = _said(PROMPTS["section"])

    assert "For one they have mastered, write a refresher at about half length" in said
    assert "(cram 45 to 90 words, standard 140 to 280, deep 250 to 500)" in said
    assert "in about half the passages and with about half the blocks" in said
    assert 'behind "Show full section"' in said
    assert "Above the even share, write toward the top of the range" in said
    assert "The share never takes you outside the range" in said
    # A thin source still wins over a word count.
    assert "when the sources say little, the grounding rule comes first" in said


def test_only_the_block_prompt_carries_the_rewrite_marker():
    assert BLOCK_REWRITE_MARKER in PROMPTS["block"]
    assert BLOCK_REWRITE_MARKER not in PROMPTS["section"]
    assert BLOCK_REWRITE_MARKER not in PROMPTS["outline"]
