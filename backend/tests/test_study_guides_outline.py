"""`services.study_guides.outline`: how many sections a guide may have, and
the outline as the guide's sections and sources."""
from __future__ import annotations

import pytest

from agents.study_guide import MAX_OUTLINE_SECTIONS, OutlineSection
from models.study_guide import (
    QUIZ_HISTORY_SOURCE,
    CheckAnswer,
    CheckBlock,
    CheckOption,
    GuideContent,
    Paragraph,
    ProseItem,
    Section,
    Source,
)
from services.study_guides import outline
from services.study_guides.materials import SourceText
from services.study_guides.prompts import Brief
from services.study_guides.signals import QuizMistake
from services.study_guides.store import GuideRow

DOC_1 = Source(id="document:doc-1", name="week-1.pdf", kind="PDF")
DOC_2 = Source(id="document:doc-2", name="week-2.pdf", kind="PDF")


def _brief(*sources: Source, mistakes=(), tiers=None) -> Brief:
    return Brief(
        scope_kind="course", scope_label="Whole course", goal="review", depth="standard",
        sources=[SourceText(label=f"S{n}", source=source, concepts=[], text="Text.")
                 for n, source in enumerate(sources, start=1)],
        concepts=list(tiers or {}), tiers=tiers or {}, mistakes=list(mistakes),
    )


def _section(section_id: str, status: str = "written") -> Section:
    check = CheckBlock(
        id=f"{section_id}-i2", question="Which one?", correct_id="a",
        options=[CheckOption(id="a", text="1"), CheckOption(id="b", text="2"),
                 CheckOption(id="c", text="3")],
    )
    prose = ProseItem(id=f"{section_id}-i1", paragraphs=[Paragraph(text="Written.")])
    items = [prose, check] if status == "written" else []
    return Section(id=section_id, title=section_id.upper(), status=status, items=items)


def _guide(*sections: Section, depth="standard", **over) -> GuideRow:
    fields = dict(
        id="g1", user_id="user_outline", offering_id="off-1", exam_id=None, scope_kind="course",
        goal="review", depth=depth, use_history=True, status="ready", format=2,
        content=GuideContent(title="Guide", sections=list(sections)),
        material_ids=[], read_sections=[], answers={}, feedback=None, saved_at=None,
        generating_at=None, generated_at=None, created_at="", updated_at="",
    )
    return GuideRow(**{**fields, **over})


# ── How many sections ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("depth", "expected"), [("cram", (1, 3)), ("standard", (3, 5)), ("deep", (6, 8))],
)
def test_the_section_range_follows_the_depth(depth, expected):
    """And nothing else: the outline is planned from the source text, so the
    number of concepts the materials happen to name does not cap it."""
    assert outline.section_range(depth) == expected


def test_an_update_has_room_for_what_it_keeps_but_never_past_the_outlines_cap():
    assert outline.section_range("cram", room_for=6) == (4, 6)
    assert outline.section_range("standard", room_for=2) == (3, 5)
    assert outline.section_range("deep", room_for=40) == (
        MAX_OUTLINE_SECTIONS - 2, MAX_OUTLINE_SECTIONS)


def test_only_an_update_makes_room_for_the_sections_it_could_keep():
    guide = _guide(*(_section(f"s{n}") for n in range(1, 5)), _section("s5", "failed"), depth="cram")

    # Four written sections it could keep, and two new lectures.
    assert outline.plan_range(guide, updating=True, new_labels=["S3", "S4"]) == (4, 6)
    assert outline.plan_range(guide, updating=False, new_labels=[]) == (1, 3)
    # Nothing to keep: the new lectures alone do not widen the range.
    empty = _guide(_section("s1", "failed"), depth="cram")
    assert outline.plan_range(empty, updating=True, new_labels=["S3", "S4"]) == (1, 3)


# ── The outline as sections ───────────────────────────────────────────────────


def _planned(title: str, concept: str | None = None, keep_id: str | None = None) -> OutlineSection:
    return OutlineSection(title=title, concept=concept, one_line=f"{title}.", keep_id=keep_id)


def test_new_sections_are_numbered_after_every_id_the_guide_had():
    current = [_section("s1"), _section("s4", "failed"), _section("intro")]
    brief = _brief(DOC_1, tiers={"Loops": "struggling"})

    sections = outline.planned_sections(
        [_planned("Kept", keep_id="s1"), _planned("Loops", "loops"), _planned("Failed", keep_id="s4")],
        current, brief, use_history=True,
    )

    # A failed section is not kept: it is written fresh under a new id.
    assert [(s.id, s.status) for s in sections] == [("s1", "written"), ("s5", "queued"), ("s6", "queued")]
    # The tree's spelling and tier; struggling 5, unexplored 3 and 3.
    assert (sections[1].concept, sections[1].tier) == ("Loops", "struggling")
    assert [s.weight for s in sections] == [27, 46, 27] and sections[0].items == current[0].items


def test_the_sources_are_what_was_read_then_the_quiz_history():
    mistake = QuizMistake(id="m1", concept="Loops", text="Off by one")

    assert outline.guide_sources(_brief(DOC_1, DOC_2), []) == [DOC_1, DOC_2]
    assert [s.id for s in outline.guide_sources(_brief(DOC_1, mistakes=[mistake]), [])] == [
        DOC_1.id, QUIZ_HISTORY_SOURCE]


def test_an_update_keeps_listing_a_source_it_had_no_room_to_read():
    """A section it keeps may cite that document."""
    history = Source(id=QUIZ_HISTORY_SOURCE, name="Your quiz history", kind="Sapling")

    sources = outline.guide_sources(_brief(DOC_2), [DOC_1, DOC_2, history])

    assert sources == [DOC_2, DOC_1, history]


# ── What survives an update ───────────────────────────────────────────────────


def test_read_marks_and_answers_stay_only_on_the_sections_an_update_keeps():
    answer = CheckAnswer(option_id="a", correct=True)
    guide = _guide(
        _section("s1"), _section("s2"), read_sections=["s1", "s2"],
        answers={"s1-i2": answer, "s2-i2": answer},
    )
    # s1 is kept; s2 was planned again as s3, which this run has just written.
    after = [_section("s1"), _section("s3")]

    assert outline.kept_state(guide, after) == {
        "read_sections": ["s1"], "answers": {"s1-i2": answer}}
