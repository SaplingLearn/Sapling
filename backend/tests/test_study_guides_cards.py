"""A guide as its card (services/study_guides/cards.py).

`reading_minutes`, `counts` and `card` are pure and tested directly.
`alist_cards` is tested with its reads replaced where the module looks them
up, counting them: the list must not read once per guide.
"""
from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest

from models.study_guide import (
    CheckBlock,
    CheckOption,
    GuideContent,
    KeyTerm,
    KeyTermsBlock,
    Paragraph,
    ProseItem,
    Section,
)
from services.study_guides import cards
from services.study_guides.cards import GuideClass
from services.study_guides.store import GuideRow
from tests.db_fakes import fake_table

ME = "user_cards_me"
OFFERING = "off-cs-f26"
MADE_AT = "2026-10-01T12:00:00+00:00"
CS = GuideClass(course_id="course-cs", course_name="Intro to CS", semester="Fall 2026")


def _prose(item_id: str, words: int) -> ProseItem:
    """A passage of that many words, 200 to a paragraph (a paragraph is
    clipped at 1200 characters)."""
    sizes = [min(200, words - start) for start in range(0, words, 200)]
    return ProseItem(id=item_id, paragraphs=[Paragraph(text=" ".join(["ab"] * n)) for n in sizes])


def _check(item_id: str) -> CheckBlock:
    return CheckBlock(
        id=item_id, question="How many passes?",
        options=[CheckOption(id="a", text="3"), CheckOption(id="b", text="4"),
                 CheckOption(id="c", text="5")],
        correct_id="b", explain_correct="Four.", explain_incorrect="Count them.",
        concept="Loops",
    )


def _terms(item_id: str) -> KeyTermsBlock:
    return KeyTermsBlock(
        id=item_id, title="Key terms",
        terms=[KeyTerm(term="Loop", definition="Repeats a block."),
               KeyTerm(term="Branch", definition="Chooses a block.")],
    )


def _content() -> GuideContent:
    return GuideContent(
        title="Control flow",
        scope_label="Midterm 1",
        sections=[
            Section(id="s1", title="Loops", concept="Loops", tier="struggling", weight=70,
                    status="written", items=[_prose("s1-i1", 150), _terms("s1-i2"), _check("s1-i3")]),
            Section(id="s2", title="Branches", tier="mastered", weight=30,
                    status="written", items=[_prose("s2-i1", 50), _check("s2-i2")]),
        ],
    )


def _guide(guide_id: str = "g1", **over) -> GuideRow:
    fields = dict(
        id=guide_id, user_id=ME, offering_id=OFFERING, exam_id="exam-1", scope_kind="exam",
        goal="exam_prep", depth="standard", use_history=True, status="ready", format=2,
        content=_content(), material_ids=["doc-1"], read_sections=[], answers={},
        feedback=None, saved_at=None, generating_at=None, generated_at=MADE_AT,
        created_at=MADE_AT, updated_at=MADE_AT,
    )
    return GuideRow(**{**fields, **over})


def _lecture(doc_id: str, created_at: str, offering_id: str = OFFERING) -> dict:
    return {"id": doc_id, "offering_id": offering_id, "created_at": created_at}


# ── Counts ────────────────────────────────────────────────────────────────────


def test_counts_sections_blocks_and_practice():
    counted = cards.counts(_content())
    assert (counted.sections, counted.blocks, counted.practice) == (2, 3, 2)


def test_reading_minutes_is_words_at_200_a_minute_plus_half_a_minute_a_block():
    one_passage = GuideContent(title="t", sections=[
        Section(id="s1", title="Loops", items=[_prose("s1-i1", 600)]),
    ])
    assert cards.reading_minutes(one_passage) == 3
    with_blocks = GuideContent(title="t", sections=[
        Section(id="s1", title="Loops", items=[
            _prose("s1-i1", 600), _terms("s1-i2"), _terms("s1-i3"), _terms("s1-i4"), _terms("s1-i5"),
        ]),
    ])
    # Four blocks add two minutes; their few words do not reach another one.
    assert cards.reading_minutes(with_blocks) == 5


def test_block_text_counts_toward_reading_time():
    long_terms = KeyTermsBlock(id="s1-i1", title="Key terms", terms=[
        KeyTerm(term="Loop", definition=" ".join(["word"] * 30)) for _ in range(6)
    ])
    content = GuideContent(title="t", sections=[Section(id="s1", title="Loops", items=[long_terms] * 3)])
    # About 560 words (2.8 minutes) and three blocks (1.5 minutes).
    assert cards.reading_minutes(content) == 4


def test_a_guide_with_nothing_written_still_reads_as_one_minute():
    assert cards.reading_minutes(GuideContent(title="t")) == 1
    assert cards.counts(GuideContent(title="t")).model_dump() == {
        "sections": 0, "blocks": 0, "practice": 0, "minutes": 1,
    }


# ── One card ──────────────────────────────────────────────────────────────────


def test_card_carries_the_row_the_class_and_the_bars():
    out = cards.card(_guide(saved_at="2026-10-02T08:00:00+00:00"), CS, [])
    assert out.model_dump(exclude={"bars", "counts"}) == {
        "id": "g1", "title": "Control flow", "course_id": "course-cs",
        "course_name": "Intro to CS", "semester": "Fall 2026", "scope_kind": "exam",
        "scope_label": "Midterm 1", "goal": "exam_prep", "depth": "standard",
        "status": "ready", "generated_at": MADE_AT, "created_at": MADE_AT,
        "saved_at": "2026-10-02T08:00:00+00:00", "new_materials": 0,
    }
    assert [bar.model_dump() for bar in out.bars] == [
        {"title": "Loops", "tier": "struggling", "weight": 70},
        {"title": "Branches", "tier": "mastered", "weight": 30},
    ]
    assert out.counts.sections == 2


def test_new_materials_counts_lectures_added_since_the_guide_was_made():
    lectures = [
        _lecture("doc-1", "2026-10-05T00:00:00+00:00"),            # already in the guide
        _lecture("doc-2", "2026-09-01T00:00:00+00:00"),            # older than the guide
        _lecture("doc-3", "2026-10-05T00:00:00+00:00"),            # new
        _lecture("doc-4", "2026-10-06T00:00:00+00:00"),            # new
        _lecture("doc-5", "2026-10-06T00:00:00+00:00", "off-other"),  # another class
    ]
    assert cards.card(_guide(), CS, lectures).new_materials == 2


def test_a_guide_never_generated_has_no_new_materials():
    lectures = [_lecture("doc-3", "2026-10-05T00:00:00+00:00")]
    out = cards.card(_guide(generated_at=None, status="generating"), CS, lectures)
    assert out.new_materials == 0 and out.generated_at is None


def test_an_unreadable_guide_is_a_failed_card():
    guide = _guide(content=GuideContent(title="Study guide"))
    if not hasattr(guide, "unreadable"):
        pytest.skip("GuideRow.unreadable has not landed in store.py yet")
    out = cards.card(replace(guide, unreadable=True), CS, [])
    assert (out.status, out.title, out.bars) == ("failed", "Study guide", [])


# ── The list ──────────────────────────────────────────────────────────────────


@pytest.fixture
def reads(monkeypatch):
    """Replace the list's reads and count them."""
    seen = {"lectures": 0, "offerings": [], "courses": []}
    guides = [
        _guide("g-new"),
        _guide("g-mid", offering_id="off-bio-f26"),
        _guide("g-old"),
    ]
    offerings = {OFFERING: ("course-cs", "Fall 2026"), "off-bio-f26": ("course-bio", None)}

    async def alist_guides(user_id):
        assert user_id == ME
        return guides

    async def alist_lecture_docs(user_id):
        seen["lectures"] += 1
        return [_lecture("doc-9", "2026-10-05T00:00:00+00:00")]

    def course_and_term(offering_id):
        seen["offerings"].append(offering_id)
        return offerings[offering_id]

    courses = fake_table()

    def select(columns, filters=None, **_):
        seen["courses"].append(filters["id"])
        return [{"id": "course-cs", "course_name": "Intro to CS"},
                {"id": "course-bio", "course_name": "Cell Biology"}]

    courses.select.side_effect = select
    monkeypatch.setattr(cards.store, "alist_guides", alist_guides)
    monkeypatch.setattr(cards.materials, "alist_lecture_docs", alist_lecture_docs)
    monkeypatch.setattr(cards, "_course_and_term", course_and_term)
    monkeypatch.setattr(cards, "table", lambda name: courses)
    return seen, guides


def test_list_keeps_the_stores_order_and_names_each_class(reads):
    out = asyncio.run(cards.alist_cards(ME))
    assert [(c.id, c.course_id, c.course_name, c.semester) for c in out] == [
        ("g-new", "course-cs", "Intro to CS", "Fall 2026"),
        ("g-mid", "course-bio", "Cell Biology", None),
        ("g-old", "course-cs", "Intro to CS", "Fall 2026"),
    ]
    assert [c.new_materials for c in out] == [1, 0, 1]


def test_list_reads_once_per_offering_not_per_guide(reads):
    seen, _ = reads
    asyncio.run(cards.alist_cards(ME))
    assert seen["lectures"] == 1
    assert sorted(seen["offerings"]) == ["off-bio-f26", OFFERING]
    assert seen["courses"] == ['in.("course-bio","course-cs")']


def test_no_guides_reads_nothing_else(reads):
    seen, guides = reads
    guides.clear()
    assert asyncio.run(cards.alist_cards(ME)) == []
    assert seen == {"lectures": 0, "offerings": [], "courses": []}


def test_a_class_whose_course_row_is_missing_still_lists(monkeypatch, reads):
    monkeypatch.setattr(cards, "_course_and_term", lambda offering_id: ("", None))
    out = asyncio.run(cards.alist_cards(ME))
    assert {(c.course_id, c.course_name, c.semester) for c in out} == {("", "", None)}


def test_course_and_term_come_from_academics(monkeypatch):
    def academics_table(name):
        handle = fake_table()
        handle.select.return_value = {
            "course_offerings": [{"course_id": "course-cs", "term_id": "term-f26"}],
            "terms": [{"id": "term-f26", "label": "Fall 2026"}],
        }[name]
        return handle

    monkeypatch.setattr(cards.academics, "table", academics_table)
    assert cards._course_and_term(OFFERING) == ("course-cs", "Fall 2026")
