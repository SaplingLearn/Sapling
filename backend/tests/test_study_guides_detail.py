"""A guide as the reader renders it (services/study_guides/detail.py).

The withholding and the concept list are pure and tested directly.
`abuild_detail` is tested with the card, scope and mastery reads replaced
where the module looks them up.
"""
from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest

from models.study_guide import (
    CheckAnswer,
    CheckBlock,
    CheckOption,
    ConceptMapBlock,
    ConceptMapNode,
    GuideCard,
    GuideContent,
    GuideCounts,
    Paragraph,
    ProseItem,
    Section,
)
from services.study_guides import detail
from services.study_guides.errors import GuideInvalid, GuideNotFound
from services.study_guides.scopes import WHOLE_COURSE, Scope
from services.study_guides.store import GuideRow

ME = "user_detail_me"
OFFERING = "off-cs-f26"
MADE_AT = "2026-10-01T12:00:00+00:00"
WITHHELD = ("correct_id", "explain_correct", "explain_incorrect")


def _check(item_id: str, concept: str | None) -> CheckBlock:
    return CheckBlock(
        id=item_id, question="How many passes?",
        options=[CheckOption(id="a", text="3"), CheckOption(id="b", text="4"),
                 CheckOption(id="c", text="5")],
        correct_id="b", explain_correct="Four values pass.", explain_incorrect="Count them.",
        concept=concept,
    )


def _content() -> GuideContent:
    prose = ProseItem(id="s1-i1", paragraphs=[Paragraph(text="A loop repeats a block.")])
    concept_map = ConceptMapBlock(id="s2-i1", title="Builds on", nodes=[
        ConceptMapNode(concept="Loops", step="Before this"),
        ConceptMapNode(concept="Recursion", step="This section"),
        ConceptMapNode(concept="Algorithms", step="Up next"),
    ])
    return GuideContent(
        title="Control flow",
        scope_label="Midterm 1",
        sections=[
            Section(id="s1", title="Loops", concept="Loops", tier="struggling", weight=60,
                    status="written", items=[prose, _check("s1-i2", "Loops")]),
            Section(id="s2", title="Recursion", concept="Recursion", tier="learning", weight=40,
                    status="written", items=[concept_map, _check("s2-i2", "Base Cases")]),
            Section(id="s3", title="Wrap-up", weight=0, status="queued"),
        ],
    )


def _guide(**over) -> GuideRow:
    fields = dict(
        id="g1", user_id=ME, offering_id=OFFERING, exam_id="exam-1", scope_kind="exam",
        goal="exam_prep", depth="standard", use_history=False, status="ready", format=2,
        content=_content(), material_ids=["doc-1"], read_sections=["s1"], answers={},
        feedback="yes", saved_at=None, generating_at=None, generated_at=MADE_AT,
        created_at=MADE_AT, updated_at=MADE_AT,
    )
    return GuideRow(**{**fields, **over})


def _card(guide: GuideRow) -> GuideCard:
    return GuideCard(
        id=guide.id, title=guide.content.title, course_id="course-cs",
        course_name="Intro to CS", semester="Fall 2026", scope_kind=guide.scope_kind,
        scope_label=guide.content.scope_label, goal=guide.goal, depth=guide.depth,
        status=guide.status, generated_at=guide.generated_at, created_at=guide.created_at,
        saved_at=guide.saved_at, new_materials=2, bars=[],
        counts=GuideCounts(sections=3, blocks=3, practice=2, minutes=4),
    )


def _checks(content: GuideContent) -> dict[str, CheckBlock]:
    return {i.id: i for s in content.sections for i in s.items if i.type == "check"}


# ── Check answers ─────────────────────────────────────────────────────────────


def test_an_unanswered_check_comes_without_its_answer():
    stored = _content()
    shown = _checks(detail.reader_content(stored, {}))
    for block in shown.values():
        assert [getattr(block, field) for field in WITHHELD] == [None, None, None]
        assert block.question and len(block.options) == 3 and block.concept
    # The stored content is not touched.
    assert all(block.correct_id == "b" for block in _checks(stored).values())


def test_an_answered_check_comes_with_its_answer_and_the_others_stay_withheld():
    answers = {"s1-i2": CheckAnswer(option_id="a", correct=False)}
    shown = _checks(detail.reader_content(_content(), answers))
    assert (shown["s1-i2"].correct_id, shown["s1-i2"].explain_correct,
            shown["s1-i2"].explain_incorrect) == ("b", "Four values pass.", "Count them.")
    assert shown["s2-i2"].correct_id is None and shown["s2-i2"].explain_correct is None


def test_other_items_pass_through_unchanged():
    stored = _content()
    shown = detail.reader_content(stored, {})
    assert shown.sections[0].items[0] == stored.sections[0].items[0]
    assert shown.sections[1].items[0] == stored.sections[1].items[0]
    assert shown.model_dump(exclude={"sections"}) == stored.model_dump(exclude={"sections"})


# ── Concepts ──────────────────────────────────────────────────────────────────


def test_mentioned_concepts_are_sections_map_nodes_and_checks_once_each():
    assert detail.mentioned_concepts(_content()) == [
        "Loops", "Recursion", "Algorithms", "Base Cases",
    ]


# ── The detail ────────────────────────────────────────────────────────────────


@pytest.fixture
def reads(monkeypatch):
    """Replace the card, scope and mastery reads; record what they were asked."""
    seen = {"scope": [], "mastery": []}
    state = {
        "scope": Scope(kind="exam", id="exam-1", title="Midterm 1 (moved)", due_date="2026-11-20"),
        "scores": {"Loops": 0.2, "recursion": 0.9, "Unrelated": 0.5},
    }

    async def acards(user_id, guides):
        assert user_id == ME
        return [_card(guide) for guide in guides]

    async def ascope_of(user_id, offering_id, scope_kind, scope_id):
        seen["scope"].append((user_id, offering_id, scope_kind, scope_id))
        if isinstance(state["scope"], Exception):
            raise state["scope"]
        return state["scope"]

    async def amastery(user_id, course_id):
        seen["mastery"].append((user_id, course_id))
        return state["scores"]

    monkeypatch.setattr(detail.cards, "acards", acards)
    monkeypatch.setattr(detail.scopes, "ascope_of", ascope_of)
    monkeypatch.setattr(detail.signals, "amastery", amastery)
    return seen, state


def test_detail_is_the_card_plus_the_readers_state(reads):
    seen, _ = reads
    guide = _guide()
    out = asyncio.run(detail.abuild_detail(guide))
    card = _card(guide).model_dump(exclude={"scope_label"})
    assert out.model_dump(include=set(card)) == card
    assert (out.scope_id, out.use_history, out.read_sections, out.feedback) == (
        "exam-1", False, ["s1"], "yes",
    )
    assert out.answers == {}
    assert seen["scope"] == [(ME, OFFERING, "exam", "exam-1")]


def test_scope_title_and_date_are_read_live(reads):
    out = asyncio.run(detail.abuild_detail(_guide()))
    assert (out.scope_label, out.due_date) == ("Midterm 1 (moved)", "2026-11-20")


@pytest.mark.parametrize("gone", [
    GuideNotFound("That exam or assignment was not found. Pick another one."),
    GuideInvalid("Pick the exam or assignment this guide is for."),
])
def test_a_guide_whose_exam_is_gone_still_opens_under_its_stored_label(reads, gone):
    _, state = reads
    state["scope"] = gone
    out = asyncio.run(detail.abuild_detail(_guide()))
    assert (out.scope_label, out.due_date, out.scope_id) == ("Midterm 1", None, "exam-1")
    assert out.content.title == "Control flow"


def test_a_whole_course_guide_has_no_scope_id_or_date(reads):
    seen, state = reads
    state["scope"] = WHOLE_COURSE
    out = asyncio.run(detail.abuild_detail(_guide(scope_kind="course", exam_id=None)))
    assert (out.scope_kind, out.scope_id, out.scope_label, out.due_date) == (
        "course", None, "Whole course", None,
    )
    assert seen["scope"] == [(ME, OFFERING, "course", None)]


def test_mastery_is_the_live_tier_of_each_concept_the_tree_has(reads):
    seen, _ = reads
    out = asyncio.run(detail.abuild_detail(_guide()))
    # Keyed by the guide's spelling; "Algorithms" and "Base Cases" are not in
    # the tree and "Unrelated" is not in the guide.
    assert out.mastery == {"Loops": "struggling", "Recursion": "mastered"}
    assert seen["mastery"] == [(ME, "course-cs")]


def test_a_guide_that_mentions_no_concept_does_not_read_mastery(reads):
    seen, _ = reads
    plain = GuideContent(title="Notes", sections=[Section(id="s1", title="Notes")])
    out = asyncio.run(detail.abuild_detail(_guide(content=plain)))
    assert out.mastery == {} and seen["mastery"] == []


def test_answers_are_withheld_in_the_detail_until_given(reads):
    before = asyncio.run(detail.abuild_detail(_guide()))
    assert all(block.correct_id is None for block in _checks(before.content).values())

    answered = {"s2-i2": CheckAnswer(option_id="b", correct=True)}
    after = asyncio.run(detail.abuild_detail(_guide(answers=answered)))
    shown = _checks(after.content)
    assert shown["s2-i2"].correct_id == "b" and shown["s2-i2"].explain_correct
    assert shown["s1-i2"].correct_id is None and shown["s1-i2"].explain_incorrect is None
    assert after.answers == answered


def test_an_unreadable_guide_opens_as_failed(monkeypatch):
    """The real card builder: an unreadable row is served as it comes, with
    its status forced to failed so the reader shows the error state."""
    from services.study_guides import cards
    from services.study_guides.cards import GuideClass

    guide = _guide(content=GuideContent(title="Study guide"), scope_kind="course", exam_id=None)
    if not hasattr(guide, "unreadable"):
        pytest.skip("GuideRow.unreadable has not landed in store.py yet")

    async def alist_lecture_docs(user_id):
        return []

    async def aclasses(offering_ids):
        return {OFFERING: GuideClass("course-cs", "Intro to CS", "Fall 2026")}

    monkeypatch.setattr(cards.materials, "alist_lecture_docs", alist_lecture_docs)
    monkeypatch.setattr(cards, "_aclasses", aclasses)
    out = asyncio.run(detail.abuild_detail(replace(guide, unreadable=True)))
    assert (out.status, out.title, out.content.sections) == ("failed", "Study guide", [])


def test_get_detail_loads_the_users_own_guide(monkeypatch, reads):
    asked = []

    async def aload_guide(user_id, guide_id):
        asked.append((user_id, guide_id))
        return _guide()

    monkeypatch.setattr(detail.store, "aload_guide", aload_guide)
    out = asyncio.run(detail.aget_detail(ME, "g1"))
    assert out.id == "g1" and asked == [(ME, "g1")]


def test_get_detail_passes_not_found_through(monkeypatch):
    async def aload_guide(user_id, guide_id):
        raise GuideNotFound("Study guide not found.")

    monkeypatch.setattr(detail.store, "aload_guide", aload_guide)
    with pytest.raises(GuideNotFound):
        asyncio.run(detail.aget_detail(ME, "someone-elses"))
