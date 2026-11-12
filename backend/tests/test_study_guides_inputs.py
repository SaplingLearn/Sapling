"""`services.study_guides.inputs`: what a generation run and a block rewrite
read for one guide."""
from __future__ import annotations

import asyncio

import pytest

from models.study_guide import Section
from services.study_guides import inputs, store
from services.study_guides.errors import GuideInvalid
from services.study_guides.signals import QuizMistake
from tests.test_study_guides_generation import (  # noqa: F401 (fixtures)
    CONCEPTS,
    COURSE,
    GUIDE,
    MADE_AT,
    world,
)
from tests.test_study_guides_store import ME, OFFERING


def run(coro):
    return asyncio.run(coro)


def test_inputs_are_the_sources_the_tree_and_the_history(world):  # noqa: F811
    world.guide()
    world.mistakes = [QuizMistake(id="m1", concept="Recursion", text="Forgets the base case")]
    guide = run(store.aload_guide(ME, GUIDE))

    read = run(inputs.aload_inputs(guide, guide.material_ids))

    assert [s.source.id for s in read.brief.sources] == ["document:doc-1"]
    assert read.brief.concepts == CONCEPTS
    assert read.brief.tiers == {
        "Recursion": "struggling", "Control Flow": "learning", "Variables and Types": "mastered"}
    assert read.brief.mistakes == world.mistakes
    assert (read.deps.user_id, read.deps.course_id, read.deps.feature) == (
        ME, COURSE, "study_guide")


def test_without_history_no_mastery_or_mistake_is_read_into_the_brief(world):  # noqa: F811
    world.guide(use_history=False)
    world.mistakes = [QuizMistake(id="m1", concept="Recursion", text="Never offered")]
    guide = run(store.aload_guide(ME, GUIDE))

    brief = run(inputs.aload_inputs(guide, guide.material_ids)).brief

    # The concept names are still there: a section is tied to one by name.
    assert (brief.concepts, brief.tiers, brief.mistakes) == (CONCEPTS, {}, [])


def test_no_readable_source_is_invalid(world):  # noqa: F811
    world.guide()
    guide = run(store.aload_guide(ME, GUIDE))

    with pytest.raises(GuideInvalid) as refused:
        run(inputs.aload_inputs(guide, ["doc-gone"]))

    assert refused.value.detail == "None of this guide's materials can be read."


def test_a_guide_that_recorded_no_materials_is_made_from_all_the_classs(world):  # noqa: F811
    world.documents["doc-2"] = ("lecture-9.pdf", "Types.", [])
    world.guide(material_ids=[])
    world.guide(guide_id="chosen", material_ids=["doc-2"])

    old, chosen = (run(store.aload_guide(ME, guide_id)) for guide_id in (GUIDE, "chosen"))

    assert run(inputs.amaterial_ids(old)) == ["doc-1", "doc-2"]
    assert run(inputs.amaterial_ids(chosen)) == ["doc-2"]


def test_new_lectures_are_the_classs_lectures_added_since_the_guide_was_made(world):  # noqa: F811
    world.lectures = [
        {"id": "doc-1", "offering_id": OFFERING, "created_at": "2026-10-01T00:00:00+00:00"},
        {"id": "doc-2", "offering_id": OFFERING, "created_at": "2026-11-05T00:00:00+00:00"},
        {"id": "doc-9", "offering_id": "off-other", "created_at": "2026-11-05T00:00:00+00:00"},
    ]
    world.guide(status="ready", generated_at=MADE_AT)
    world.guide(guide_id="unfinished")

    made, unfinished = (run(store.aload_guide(ME, guide_id)) for guide_id in (GUIDE, "unfinished"))

    assert run(inputs.anew_lectures(made)) == ["doc-2"]
    assert run(inputs.anew_lectures(unfinished)) == []


def test_a_section_is_held_to_the_sources_text_and_its_own_concepts_mistakes(world):  # noqa: F811
    world.guide()
    world.mistakes = [
        QuizMistake(id="m1", concept="Recursion", text="Forgets the base case"),
        QuizMistake(id="m2", concept="Control Flow", text="Off by one"),
    ]
    guide = run(store.aload_guide(ME, GUIDE))
    brief = run(inputs.aload_inputs(guide, guide.material_ids)).brief

    facts = inputs.facts_for(brief, Section(id="s1", title="Recursion", concept="recursion"))

    assert facts.sources == {"document:doc-1": "A recursive function calls itself."}
    assert facts.mistakes == world.mistakes[:1] and facts.concepts == CONCEPTS
