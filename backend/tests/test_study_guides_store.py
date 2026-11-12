"""`services/study_guides/store.py` against an in-memory PostgREST stand-in.

The stand-in honours the filters the store sends (`eq.`, `is.null`,
`not.is.null`, `lt.`), its order and limit, and stamps `updated_at` on every
update as the table's trigger does, so the claim and the once-only answer are
decided by the same conditional writes production uses.
"""
from __future__ import annotations

import asyncio
import itertools
from datetime import datetime, timedelta, timezone

import pytest

from models.study_guide import (
    GUIDE_FORMAT,
    CheckAnswer,
    CheckBlock,
    CheckOption,
    GuideContent,
    Paragraph,
    ProseItem,
    Section,
)
from services.encryption import decrypt_json, encrypt_json
from services.study_guides import store
from services.study_guides.errors import GuideBusy, GuideNotFound
from services.study_guides.legacy import UNTITLED
from tests.db_fakes import add_async_twins

ME, OTHER = "user_guides_me", "user_guides_other"
OFFERING = "off-cs-f26"


def run(coro):
    return asyncio.run(coro)


def _content(title: str = "Midterm 1") -> GuideContent:
    check = CheckBlock(
        id="s1-i2",
        question="How many times does the loop run?",
        options=[CheckOption(id="a", text="3"), CheckOption(id="b", text="4"),
                 CheckOption(id="c", text="5")],
        correct_id="b",
        explain_correct="It runs once per value from 0 to 3.",
        explain_incorrect="Count the values the condition lets through.",
        concept="Loops",
    )
    prose = ProseItem(
        id="s1-i1",
        paragraphs=[Paragraph(text="A **while loop** checks its condition first.")],
        summary="A while loop repeats while its condition holds.",
    )
    section = Section(id="s1", title="Loops", concept="Loops", tier="learning", weight=100,
                      one_line="Count the passes.", status="written", items=[prose, check])
    return GuideContent(title=title, deck="Loops, traced by hand.", sections=[section],
                        scope_label=title)


# ── A tiny PostgREST stand-in ───────────────────────────────────────────────


def _matches(row: dict, filters: dict | None) -> bool:
    for col, cond in (filters or {}).items():
        value = row.get(col)
        if cond == "is.null":
            ok = value is None
        elif cond == "not.is.null":
            ok = value is not None
        elif cond.startswith("eq."):
            ok = value is not None and str(value) == cond[3:]
        elif cond.startswith("lt."):
            ok = value is not None and str(value) < cond[3:]
        else:
            raise AssertionError(f"filter {col}={cond} not modelled")
        if not ok:
            return False
    return True


class FakeGuides:
    """The `study_guides` table. `before_update`, when set, runs just before
    every update is applied, to play a concurrent writer."""

    def __init__(self):
        self.rows: list[dict] = []
        self.before_update = None
        self._clock = itertools.count(1)

    def _tick(self) -> str:
        stamp = datetime(2026, 11, 1, tzinfo=timezone.utc) + timedelta(seconds=next(self._clock))
        return stamp.isoformat()

    def add(self, guide_id: str, user_id: str = ME, **over) -> dict:
        now = self._tick()
        row = {
            "id": guide_id, "user_id": user_id, "offering_id": OFFERING, "exam_id": "exam-1",
            "scope_kind": "exam", "goal": "exam_prep", "depth": "standard",
            "use_history": True, "status": "ready", "format": GUIDE_FORMAT,
            "content": encrypt_json(_content().model_dump(mode="json")),
            "previous_content": None, "material_ids": [], "read_sections": [],
            "answers": None, "feedback": None, "saved_at": None, "generating_at": None,
            "generated_at": now, "created_at": now, "updated_at": now,
            **over,
        }
        self.rows.append(row)
        return row

    def stored(self, guide_id: str) -> dict:
        return next(r for r in self.rows if r["id"] == guide_id)

    def select(self, columns="*", filters=None, order=None, limit=None, **_):
        rows = [dict(r) for r in self.rows if _matches(r, filters)]
        for part in reversed((order or "").split(",")):
            if part:
                col, _, direction = part.partition(".")
                rows.sort(key=lambda r: str(r.get(col) or ""), reverse=direction == "desc")
        rows = rows[:limit] if limit else rows
        return [{c: r.get(c) for c in columns.split(",")} for r in rows]

    def insert(self, data):
        now = self._tick()
        row = {"previous_content": None, "read_sections": [], "answers": None, "feedback": None,
               "saved_at": None, "generating_at": None, "created_at": now, "updated_at": now,
               **data}
        self.rows.append(row)
        return [dict(row)]

    def update(self, data, filters, prefer_return_minimal=False):
        if self.before_update is not None:
            self.before_update()
        hit = [r for r in self.rows if _matches(r, filters)]
        for row in hit:
            row.update(data)
            row["updated_at"] = self._tick()
        return [] if prefer_return_minimal else [dict(r) for r in hit]


@pytest.fixture
def db(monkeypatch):
    fake = FakeGuides()
    handle = add_async_twins(fake)
    monkeypatch.setattr(store, "table", lambda name: {"study_guides": handle}[name])
    return fake


# ── Encryption round trip ───────────────────────────────────────────────────


def test_content_is_ciphertext_at_rest_and_reads_back_equal(db):
    content = _content()
    guide_id = run(store.ainsert_guide(
        user_id=ME, offering_id=OFFERING, scope_kind="exam", exam_id="exam-1",
        goal="review", depth="deep", use_history=False, material_ids=["doc-1", "doc-2"],
        content=content,
    ))

    raw = db.stored(guide_id)
    assert isinstance(raw["content"], str)
    assert "while loop" not in raw["content"] and "Midterm" not in raw["content"]
    assert decrypt_json(raw["content"]) == content.model_dump(mode="json")
    assert (raw["status"], raw["format"], raw["generated_at"]) == ("generating", 2, None)

    guide = run(store.aload_guide(ME, guide_id))
    assert guide.content == content
    assert (guide.scope_kind, guide.exam_id, guide.goal, guide.depth) == (
        "exam", "exam-1", "review", "deep")
    assert guide.use_history is False
    assert guide.material_ids == ["doc-1", "doc-2"]
    assert (guide.status, guide.format, guide.generated_at) == ("generating", 2, None)
    assert guide.answers == {} and guide.read_sections == []


def test_save_keeps_the_previous_version_encrypted(db):
    db.add("g1", read_sections=["s1"],
           answers=encrypt_json({"s1-i2": {"option_id": "b", "correct": True}}))
    before = run(store.aload_guide(ME, "g1"))
    rewritten = _content("Midterm 1, rewritten")

    after = run(store.asave_content(
        before, rewritten, keep_previous=True, reset_answers=True,
        status="ready", generated_at="2026-11-12T00:00:00+00:00",
        material_ids=["doc-9"], read_sections=[],
    ))

    raw = db.stored("g1")
    assert isinstance(raw["previous_content"], str)
    assert "while loop" not in raw["previous_content"]
    assert decrypt_json(raw["previous_content"]) == before.content.model_dump(mode="json")
    assert decrypt_json(raw["content"]) == rewritten.model_dump(mode="json")
    assert raw["answers"] is None
    assert after.content == rewritten
    assert (after.status, after.generated_at) == ("ready", "2026-11-12T00:00:00+00:00")
    assert (after.material_ids, after.read_sections, after.answers) == (["doc-9"], [], {})


def test_save_leaves_the_previous_version_and_answers_alone_by_default(db):
    answers = encrypt_json({"s1-i2": {"option_id": "a", "correct": False}})
    db.add("g1", previous_content="older-ciphertext", answers=answers)
    guide = run(store.aload_guide(ME, "g1"))

    run(store.asave_content(guide, _content("Next section written")))

    assert db.stored("g1")["previous_content"] == "older-ciphertext"
    assert db.stored("g1")["answers"] == answers


def test_save_refuses_a_column_it_does_not_own(db):
    db.add("g1")
    guide = run(store.aload_guide(ME, "g1"))
    with pytest.raises(TypeError, match="generating_at"):
        run(store.asave_content(guide, _content(), generating_at=None))


def test_answers_are_ciphertext_at_rest_and_read_back_equal(db):
    db.add("g1")
    guide = run(store.aload_guide(ME, "g1"))
    answer = CheckAnswer(option_id="b", correct=True)

    assert run(store.arecord_answer(guide, "s1-i2", answer)) is True

    raw = db.stored("g1")["answers"]
    assert isinstance(raw, str) and "option_id" not in raw
    assert decrypt_json(raw) == {"s1-i2": {"option_id": "b", "correct": True}}
    assert run(store.aload_guide(ME, "g1")).answers == {"s1-i2": answer}


# ── The once-only answer ────────────────────────────────────────────────────


def test_a_block_is_answered_only_once(db):
    db.add("g1")
    first = CheckAnswer(option_id="a", correct=False)
    assert run(store.arecord_answer(run(store.aload_guide(ME, "g1")), "s1-i2", first)) is True

    again = run(store.aload_guide(ME, "g1"))
    assert run(store.arecord_answer(again, "s1-i2", CheckAnswer(option_id="b", correct=True))) is False
    assert run(store.aload_guide(ME, "g1")).answers == {"s1-i2": first}


def test_a_double_click_records_one_first_answer(db):
    """Both clicks loaded the guide before either wrote. The loser's
    compare-and-set misses, it re-reads, and finds the block answered."""
    db.add("g1")
    click_one = run(store.aload_guide(ME, "g1"))
    click_two = run(store.aload_guide(ME, "g1"))
    first = CheckAnswer(option_id="a", correct=False)

    assert run(store.arecord_answer(click_one, "s1-i2", first)) is True
    assert run(store.arecord_answer(click_two, "s1-i2", CheckAnswer(option_id="b", correct=True))) is False
    assert run(store.aload_guide(ME, "g1")).answers == {"s1-i2": first}


def test_an_answer_lost_to_another_write_is_retried_once(db):
    """Another write (a section marked read) lands between the load and the
    answer: the compare-and-set misses, and the retry keeps both changes."""
    db.add("g1", answers=encrypt_json({"s2-i3": {"option_id": "c", "correct": True}}))
    guide = run(store.aload_guide(ME, "g1"))
    run(store.apatch_state(ME, "g1", read_sections=["s1"]))

    answer = CheckAnswer(option_id="b", correct=True)
    assert run(store.arecord_answer(guide, "s1-i2", answer)) is True

    after = run(store.aload_guide(ME, "g1"))
    assert after.answers == {"s2-i3": CheckAnswer(option_id="c", correct=True), "s1-i2": answer}
    assert after.read_sections == ["s1"]


def test_an_answer_that_loses_twice_is_busy(db):
    """The row moves before each of the two attempts (a generation saving
    sections): the answer is not written and the caller is told to retry."""
    db.add("g1")
    guide = run(store.aload_guide(ME, "g1"))
    db.before_update = lambda: db.stored("g1").update(updated_at=db._tick())

    with pytest.raises(GuideBusy):
        run(store.arecord_answer(guide, "s1-i2", CheckAnswer(option_id="b", correct=True)))
    assert db.stored("g1")["answers"] is None


# ── Ownership ───────────────────────────────────────────────────────────────


def test_another_users_guide_is_not_found(db):
    db.add("theirs", user_id=OTHER)

    with pytest.raises(GuideNotFound):
        run(store.aload_guide(ME, "theirs"))
    with pytest.raises(GuideNotFound):
        run(store.aload_guide(ME, "missing"))
    with pytest.raises(GuideNotFound):
        run(store.apatch_state(ME, "theirs", saved=True))
    assert run(store.aclaim_generation(ME, "theirs")) is False
    assert run(store.alist_guides(ME)) == []

    assert db.stored("theirs")["saved_at"] is None
    assert db.stored("theirs")["generating_at"] is None
    assert run(store.aload_guide(OTHER, "theirs")).id == "theirs"


def test_list_is_newest_first_and_only_the_users(db):
    db.add("old")
    db.add("theirs", user_id=OTHER)
    db.add("new")

    assert [g.id for g in run(store.alist_guides(ME))] == ["new", "old"]


# ── Reader state ────────────────────────────────────────────────────────────


def test_patch_state_changes_only_what_it_is_given(db):
    db.add("g1", read_sections=["s1"], feedback="yes")

    saved = run(store.apatch_state(ME, "g1", saved=True))
    assert saved.saved_at is not None
    assert (saved.read_sections, saved.feedback) == (["s1"], "yes")

    changed = run(store.apatch_state(ME, "g1", read_sections=["s1", "s2"], feedback="no"))
    assert (changed.read_sections, changed.feedback) == (["s1", "s2"], "no")
    assert changed.saved_at == saved.saved_at

    assert run(store.apatch_state(ME, "g1", saved=False)).saved_at is None

    untouched = db.stored("g1")["updated_at"]
    assert run(store.apatch_state(ME, "g1")).read_sections == ["s1", "s2"]
    assert db.stored("g1")["updated_at"] == untouched


# ── The generation claim ────────────────────────────────────────────────────


def _minutes_ago(minutes: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()


def test_a_free_claim_is_taken_and_then_held(db):
    db.add("g1")

    assert run(store.aclaim_generation(ME, "g1")) is True
    assert db.stored("g1")["generating_at"] is not None
    assert run(store.aclaim_generation(ME, "g1")) is False


def test_a_fresh_claim_is_refused(db):
    held = _minutes_ago(4)
    db.add("g1", generating_at=held)

    assert run(store.aclaim_generation(ME, "g1")) is False
    assert db.stored("g1")["generating_at"] == held


def test_a_stale_claim_is_taken_over(db):
    stale = _minutes_ago(6)
    db.add("g1", generating_at=stale)

    assert run(store.aclaim_generation(ME, "g1")) is True
    assert db.stored("g1")["generating_at"] > stale


def test_touch_keeps_a_claim_fresh_and_release_frees_it(db):
    db.add("g1", generating_at=_minutes_ago(4.9))

    run(store.atouch_generation(ME, "g1"))
    assert db.stored("g1")["generating_at"] > _minutes_ago(1)

    run(store.arelease_generation(ME, "g1"))
    assert db.stored("g1")["generating_at"] is None
    # A late heartbeat from the run that released does not take the claim back.
    run(store.atouch_generation(ME, "g1"))
    assert db.stored("g1")["generating_at"] is None
    assert run(store.aclaim_generation(ME, "g1")) is True


def test_the_stale_window_is_five_minutes():
    assert store.CLAIM_STALE_AFTER == timedelta(minutes=5)


# ── Old rows and unreadable rows ────────────────────────────────────────────


LEGACY = {
    "exam": "Midterm 1",
    "due_date": "2026-10-20",
    "overview": "Covers loops and functions.",
    "topics": [
        {"name": "Loops", "importance": "Most trace questions are loops.",
         "concepts": ["while loops", "for loops"]},
        {"name": "Functions", "importance": "Every program calls one.", "concepts": ["scope"]},
    ],
}


def test_a_format_1_row_is_upgraded_on_read(db):
    db.add("old", format=1, content=encrypt_json(LEGACY))

    guide = run(store.aload_guide(ME, "old"))

    assert guide.format == 1
    assert guide.content.title == "Midterm 1"
    assert guide.content.deck == "Covers loops and functions."
    assert [(s.id, s.title, s.weight) for s in guide.content.sections] == [
        ("s1", "Loops", 50), ("s2", "Functions", 50)]
    assert guide.content.sections[0].items[0].id == "s1-i1"
    # Reading does not rewrite the row.
    assert decrypt_json(db.stored("old")["content"]) == LEGACY


def test_a_legacy_plaintext_jsonb_row_still_reads(db):
    db.add("older", format=1, content=dict(LEGACY))
    assert run(store.aload_guide(ME, "older")).content.title == "Midterm 1"


def test_saving_an_upgraded_row_makes_it_format_2(db):
    db.add("old", format=1, content=encrypt_json(LEGACY))
    guide = run(store.aload_guide(ME, "old"))

    after = run(store.asave_content(guide, _content("Rewritten"), keep_previous=True))

    assert (after.format, db.stored("old")["format"]) == (2, 2)
    # The step back is stored in the current shape, whatever the row was.
    previous = GuideContent.model_validate(decrypt_json(db.stored("old")["previous_content"]))
    assert previous == guide.content


def test_a_row_that_does_not_decrypt_does_not_break_the_list(db, caplog):
    db.add("good")
    db.add("bad", content="bm90LWNpcGhlcnRleHQtbm90LWNpcGhlcnRleHQtbm90LWNpcGhlcnRleHQ=",
           answers="also-not-ciphertext")

    guides = run(store.alist_guides(ME))

    assert [g.id for g in guides] == ["bad", "good"]
    bad, good = guides
    assert bad.content == GuideContent(title=UNTITLED)
    assert bad.answers == {}
    assert good.content == _content()
    assert not [r for r in caplog.records if r.exc_info], "an expected path logged a traceback"


def test_content_that_no_longer_validates_reads_as_empty(db):
    db.add("drifted", content=encrypt_json({"sections": "not a list"}))
    assert run(store.aload_guide(ME, "drifted")).content == GuideContent(title=UNTITLED)
