"""The reshaped `study_guides` table (20261112094239_study_guides_durable.sql)
and `services/study_guides/store.py` against real Postgres.

The hermetic suite (tests/test_study_guides_store.py) runs the store against
an in-memory stand-in that models the conditional writes as the store sends
them. This pins what the real table does with them: the defaults an insert
from before the redesign gets, the scope CHECK, the claim's compare-and-set
on a real `timestamptz` (the token is a timestamp PostgREST prints and then
has to match in a filter), the once-only answer under two writers racing on
the `updated_at` trigger, and the three encrypted columns at rest.

Writes go through the store (PostgREST) or, for what the app never sends, raw
SQL; every assertion about the row reads it back over `db_conn`. Rows are the
baseline student's; the autouse reset removes them between tests.
"""
import asyncio
import uuid
from datetime import datetime

import psycopg
import pytest
from psycopg.types.json import Jsonb

pytestmark = pytest.mark.integration

# Baseline ids from db/seed_local_rich (literals, as in the conftest).
USER = "rich-user-active"
OTHER = "rich-user-second"
OFFERING = "rich-off-cs101-f25"

LEGACY = {
    "exam": "Midterm 1",
    "due_date": "2026-10-20",
    "overview": "Covers loops and functions.",
    "topics": [{"name": "Loops", "importance": "Most trace questions are loops.",
                "concepts": ["while loops"]}],
}


def run(coro):
    return asyncio.run(coro)


def _content(title: str = "Loops, traced by hand"):
    from models.study_guide import (
        CheckBlock,
        CheckOption,
        GuideContent,
        Paragraph,
        ProseItem,
        Section,
    )

    check = CheckBlock(
        id="s1-i2", question="How many times does the loop run?", correct_id="b",
        options=[CheckOption(id="a", text="3"), CheckOption(id="b", text="4"),
                 CheckOption(id="c", text="5")],
        explain_correct="Once per value from 0 to 3.", explain_incorrect="Count the values.",
    )
    prose = ProseItem(
        id="s1-i1", paragraphs=[Paragraph(text="A **while loop** checks its condition first.")])
    section = Section(id="s1", title="Loops", weight=100, status="written", items=[prose, check])
    return GuideContent(title=title, sections=[section], scope_label="Midterm 1")


def _new_guide(**over) -> str:
    """A guide inserted the way `create` does: through the store."""
    from services.study_guides import store

    fields = dict(
        user_id=USER, offering_id=OFFERING, scope_kind="exam", exam_id="it-exam-1",
        goal="review", depth="deep", use_history=False, material_ids=["it-doc-1", "it-doc-2"],
        content=_content(),
    )
    return run(store.ainsert_guide(**{**fields, **over}))


def _row(db_conn, guide_id: str) -> dict:
    row = db_conn.execute(
        "SELECT * FROM public.study_guides WHERE id = %s", (guide_id,)).fetchone()
    assert row is not None, f"study_guides row {guide_id} is missing"
    return row


def _sqlstate(db_conn, sql: str, params=None) -> str | None:
    try:
        with db_conn.transaction():
            db_conn.execute(sql, params)
    except psycopg.Error as e:
        return e.sqlstate
    return None


# ── The migrated table ──────────────────────────────────────────────────────


def test_a_new_style_row_is_stored_as_the_store_sends_it(db_conn):
    guide_id = _new_guide()

    row = _row(db_conn, guide_id)
    assert (row["user_id"], row["offering_id"], row["exam_id"]) == (USER, OFFERING, "it-exam-1")
    assert (row["scope_kind"], row["goal"], row["depth"]) == ("exam", "review", "deep")
    assert (row["use_history"], row["status"], row["format"]) == (False, "generating", 2)
    assert row["material_ids"] == ["it-doc-1", "it-doc-2"] and row["read_sections"] == []
    # NULL on purpose: the column's default is now(), and nothing is written yet.
    assert row["generated_at"] is None and row["generating_at"] is None
    assert row["previous_content"] is None and row["answers"] is None
    assert row["feedback"] is None and row["saved_at"] is None
    assert row["created_at"] is not None and row["updated_at"] is not None


def test_a_whole_course_guide_has_no_exam(db_conn):
    guide_id = _new_guide(scope_kind="course", exam_id=None)

    row = _row(db_conn, guide_id)
    assert (row["scope_kind"], row["exam_id"]) == ("course", None)


def test_an_insert_from_before_the_redesign_still_lands_and_reads_as_the_old_shape(db_conn):
    """Code deployed before the migration writes only these six columns."""
    from services.encryption import encrypt_json
    from services.study_guides import store

    guide_id = f"it-guide-{uuid.uuid4().hex[:12]}"
    db_conn.execute(
        "INSERT INTO public.study_guides (id, user_id, offering_id, exam_id, content, generated_at) "
        "VALUES (%s, %s, %s, 'it-exam-old', %s, '2026-10-01T12:00:00+00:00')",
        (guide_id, USER, OFFERING, Jsonb(encrypt_json(LEGACY))),
    )

    row = _row(db_conn, guide_id)
    assert (row["scope_kind"], row["goal"], row["depth"]) == ("exam", "exam_prep", "standard")
    assert (row["use_history"], row["status"], row["format"]) == (True, "ready", 1)
    assert row["material_ids"] == [] and row["read_sections"] == []
    assert row["created_at"] is not None and row["updated_at"] is not None
    guide = run(store.aload_guide(USER, guide_id))
    assert (guide.format, guide.status, guide.content.title) == (1, "ready", "Midterm 1")
    assert [section.title for section in guide.content.sections] == ["Loops"]
    assert guide.generated_at is not None and guide.material_ids == []


@pytest.mark.parametrize(
    ("scope_kind", "exam_id", "sqlstate"),
    [
        ("course", None, None),
        ("exam", "it-exam-1", None),
        ("assignment", "it-hw-1", None),
        # A whole-course guide names no assignment; every other guide names one.
        ("course", "it-exam-1", "23514"),
        ("exam", None, "23514"),
        ("assignment", None, "23514"),
        ("midterm", "it-exam-1", "23514"),
    ],
)
def test_the_scope_kind_and_the_exam_id_agree(db_conn, scope_kind, exam_id, sqlstate):
    insert = (
        "INSERT INTO public.study_guides (user_id, offering_id, scope_kind, exam_id, content) "
        "VALUES (%s, %s, %s, %s, %s)"
    )

    assert _sqlstate(db_conn, insert, (USER, OFFERING, scope_kind, exam_id, Jsonb("x"))) == sqlstate


def test_several_guides_for_one_exam_are_allowed(db_conn):
    first, second = _new_guide(), _new_guide()

    assert first != second
    count = db_conn.execute(
        "SELECT count(*) AS n FROM public.study_guides WHERE user_id = %s AND exam_id = 'it-exam-1'",
        (USER,)).fetchone()["n"]
    assert count == 2


# ── updated_at ──────────────────────────────────────────────────────────────


def test_updated_at_moves_on_every_write(db_conn):
    """The once-only answer's compare-and-set keys on it, so every writer of
    the row has to move it: the trigger does, whatever the write."""
    from models.study_guide import CheckAnswer
    from services.study_guides import store

    guide_id = _new_guide()
    stamps = [_row(db_conn, guide_id)["updated_at"]]

    def after(coro):
        result = run(coro)
        stamps.append(_row(db_conn, guide_id)["updated_at"])
        return result

    after(store.apatch_state(USER, guide_id, read_sections=["s1"]))
    after(store.apatch_state(USER, guide_id, saved=True))
    token = after(store.aclaim_generation(USER, guide_id))
    token = after(store.atouch_generation(USER, guide_id, token))
    guide = run(store.aload_guide(USER, guide_id))
    saved = after(store.asave_content(guide, _content("Rewritten"), claim=token))
    after(store.arelease_generation(USER, guide_id, saved.generating_at))
    guide = run(store.aload_guide(USER, guide_id))
    after(store.arecord_answer(guide, "s1-i2", CheckAnswer(option_id="b", correct=True)))

    assert len(stamps) == 8
    assert all(later > earlier for earlier, later in zip(stamps, stamps[1:])), stamps
    # And the store hands back the value the next compare-and-set must match.
    assert datetime.fromisoformat(run(store.aload_guide(USER, guide_id)).updated_at) == stamps[-1]


# ── The generation claim ────────────────────────────────────────────────────


def test_of_two_claims_on_a_free_guide_exactly_one_wins(db_conn):
    from services.study_guides import store

    guide_id = _new_guide()

    async def race():
        return await asyncio.gather(
            store.aclaim_generation(USER, guide_id), store.aclaim_generation(USER, guide_id),
        )

    tokens = run(race())

    won = [token for token in tokens if token is not None]
    assert len(won) == 1, tokens
    assert datetime.fromisoformat(won[0]) == _row(db_conn, guide_id)["generating_at"]
    # Held: nobody else gets it, the owner included, and not another student.
    assert run(store.aclaim_generation(USER, guide_id)) is None
    assert run(store.aclaim_generation(OTHER, guide_id)) is None


def test_the_token_the_claim_returns_is_the_one_its_holder_writes_with(db_conn):
    """The token is a timestamp as PostgREST prints it, sent back as a filter
    value. It has to match the stored instant exactly, `+00:00` and all."""
    from services.study_guides import store

    guide_id = _new_guide()
    token = run(store.aclaim_generation(USER, guide_id))

    touched = run(store.atouch_generation(USER, guide_id, token))
    guide = run(store.aload_guide(USER, guide_id))
    saved = run(store.asave_content(guide, _content("Section written"), claim=touched))

    assert len({token, touched, saved.generating_at}) == 3
    assert datetime.fromisoformat(saved.generating_at) == _row(db_conn, guide_id)["generating_at"]
    run(store.arelease_generation(USER, guide_id, saved.generating_at))
    assert _row(db_conn, guide_id)["generating_at"] is None
    assert run(store.aclaim_generation(USER, guide_id)) is not None


def test_a_runs_last_save_gives_the_claim_up_in_the_same_write(db_conn):
    from services.study_guides import store

    guide_id = _new_guide()
    token = run(store.aclaim_generation(USER, guide_id))
    guide = run(store.aload_guide(USER, guide_id))

    saved = run(store.asave_content(
        guide, _content("Finished"), claim=token, release=True,
        status="ready", generated_at="2026-11-12T10:00:00+00:00",
    ))

    row = _row(db_conn, guide_id)
    assert saved.generating_at is None and row["generating_at"] is None
    assert row["status"] == "ready" and row["generated_at"] is not None
    assert run(store.aclaim_generation(USER, guide_id)) is not None


def test_a_fresh_claim_is_refused_and_a_stale_one_is_taken(db_conn):
    from services.study_guides import store

    guide_id = _new_guide()
    db_conn.execute(
        "UPDATE public.study_guides SET generating_at = now() - interval '14 minutes' WHERE id = %s",
        (guide_id,))
    assert run(store.aclaim_generation(USER, guide_id)) is None
    assert store.claim_is_held(run(store.aload_guide(USER, guide_id))) is True

    db_conn.execute(
        "UPDATE public.study_guides SET generating_at = now() - interval '16 minutes' WHERE id = %s",
        (guide_id,))
    assert store.claim_is_held(run(store.aload_guide(USER, guide_id))) is False
    token = run(store.aclaim_generation(USER, guide_id))

    assert token is not None
    assert datetime.fromisoformat(token) == _row(db_conn, guide_id)["generating_at"]


def test_a_run_that_lost_its_claim_cannot_save_touch_or_release(db_conn):
    from services.study_guides import store

    guide_id = _new_guide()
    lost = run(store.aclaim_generation(USER, guide_id))
    guide = run(store.aload_guide(USER, guide_id))
    # The run went silent past the stale window and another took the guide.
    db_conn.execute(
        "UPDATE public.study_guides SET generating_at = now() - interval '16 minutes' WHERE id = %s",
        (guide_id,))
    holder = run(store.aclaim_generation(USER, guide_id))
    before = _row(db_conn, guide_id)

    with pytest.raises(store.ClaimLost):
        run(store.atouch_generation(USER, guide_id, lost))
    with pytest.raises(store.ClaimLost):
        run(store.asave_content(
            guide, _content("Written by the overtaken run"), claim=lost,
            keep_previous=True, answers={}, status="ready",
        ))
    with pytest.raises(store.ClaimLost):
        run(store.asave_content(guide, _content("Nor this"), claim=lost, release=True))
    run(store.arelease_generation(USER, guide_id, lost))

    assert holder is not None and _row(db_conn, guide_id) == before
    assert run(store.aclaim_generation(USER, guide_id)) is None


# ── The once-only answer ────────────────────────────────────────────────────


def test_two_first_answers_at_once_record_exactly_one(db_conn):
    """Both loaded the guide before either wrote (a double click, two tabs).
    The compare-and-set on `updated_at` lets one through; the other re-reads
    and finds the block answered."""
    from models.study_guide import CheckAnswer
    from services.encryption import decrypt_json
    from services.study_guides import store

    guide_id = _new_guide()
    guide = run(store.aload_guide(USER, guide_id))
    wrong, right = CheckAnswer(option_id="a", correct=False), CheckAnswer(option_id="b", correct=True)

    async def race():
        return await asyncio.gather(
            store.arecord_answer(guide, "s1-i2", wrong), store.arecord_answer(guide, "s1-i2", right),
        )

    counted = run(race())

    assert sorted(counted) == [False, True], counted
    winner = wrong if counted[0] else right
    stored = decrypt_json(_row(db_conn, guide_id)["answers"])
    assert stored == {"s1-i2": winner.model_dump()}
    assert run(store.aload_guide(USER, guide_id)).answers == {"s1-i2": winner}
    # A later click is not counted either.
    again = run(store.aload_guide(USER, guide_id))
    assert run(store.arecord_answer(again, "s1-i2", right)) is False


# ── Encryption at rest ──────────────────────────────────────────────────────


def test_content_previous_content_and_answers_are_ciphertext_and_round_trip(db_conn):
    from models.study_guide import CheckAnswer, GuideContent
    from services.encryption import decrypt_json
    from services.study_guides import store

    first, rewritten = _content(), _content("Rewritten for the round trip")
    guide_id = _new_guide(content=first)
    guide = run(store.aload_guide(USER, guide_id))
    assert guide.content == first

    saved = run(store.asave_content(guide, rewritten, keep_previous=True, status="ready"))
    answer = CheckAnswer(option_id="b", correct=True)
    assert run(store.arecord_answer(saved, "s1-i2", answer)) is True

    row = _row(db_conn, guide_id)
    for column in ("content", "previous_content", "answers"):
        assert isinstance(row[column], str), f"{column} stored as PLAINTEXT JSONB"
        assert "while loop" not in row[column] and "option_id" not in row[column]
    # Validated, not compared as a dict: the store keeps fields no dump has
    # (`last_section_number`, `materials_read_at`).
    assert GuideContent.model_validate(decrypt_json(row["content"])) == rewritten
    assert GuideContent.model_validate(decrypt_json(row["previous_content"])) == first
    assert decrypt_json(row["answers"]) == {"s1-i2": {"option_id": "b", "correct": True}}
    after = run(store.aload_guide(USER, guide_id))
    assert (after.content, after.answers, after.format) == (rewritten, {"s1-i2": answer}, 2)
    # Another student reads none of it.
    from services.study_guides.errors import GuideNotFound

    with pytest.raises(GuideNotFound):
        run(store.aload_guide(OTHER, guide_id))
