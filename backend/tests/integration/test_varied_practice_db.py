"""Spec §13 A140 / A141, real-DB half: migration 20261108185101_learning_
varied_practice.sql on the local stack.

- the four check_items columns have the declared shape (nullable text /
  text[]), and the migration's SQL runs again, in a rolled-back transaction,
  unchanged (idempotent);
- its CHECKs refuse what the code never writes: an unknown representation, a
  half descriptor, a multi-concept row whose key, apex and components
  disagree (or with more than three), and a concept's own row whose key holds
  the separator;
- the app's own writes and reads over PostgREST: a varied draft stores its
  representation in plaintext and its context as ciphertext that decrypts to
  the label (read back over psycopg, #397); a multi-concept draft is stored
  under its combination's key with its apex and components; concept_surfaces,
  multi_concept_items and course_has_items read them back.

Run inside the flock'd local-stack cycle with RUN_INTEGRATION=1."""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest

from tests.integration.conftest import _require_local_db_url

pytestmark = pytest.mark.integration

COURSE = "rich-course-cs101"
MIGRATION = next(
    (Path(__file__).resolve().parents[2] / "db" / "migrations").glob("*_learning_varied_practice.sql")
)
SEP = "\x1f"


def _columns(conn) -> dict:
    rows = conn.execute(
        "SELECT column_name, data_type, is_nullable, column_default FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = 'check_items' AND column_name = ANY(%s)",
        (["surface_representation", "surface_context", "apex_key", "component_keys"],),
    ).fetchall()
    return {r["column_name"]: (r["data_type"], r["is_nullable"], r["column_default"]) for r in rows}


def test_the_columns_have_the_declared_shape_and_the_migration_is_idempotent(db_conn):
    import psycopg
    from psycopg.rows import dict_row

    before = _columns(db_conn)
    assert before == {
        "surface_representation": ("text", "YES", None),
        "surface_context": ("text", "YES", None),
        "apex_key": ("text", "YES", None),
        "component_keys": ("ARRAY", "YES", None),
    }
    url = (os.getenv("SUPABASE_DB_URL") or "").strip()
    _require_local_db_url(url)
    with psycopg.connect(url, row_factory=dict_row) as conn:
        try:
            conn.execute(MIGRATION.read_text(encoding="utf-8"))
            assert _columns(conn) == before
        finally:
            conn.rollback()


def _draft(prompt: str, concept: str, **over):
    from learning.checks import CheckItemDraft

    return CheckItemDraft(
        concept=concept,
        format="free",
        difficulty=over.pop("difficulty", 2),
        prompt=prompt,
        reference_answer="The step size along the gradient. Final answer: The step size.",
        final_answer="The step size",
        rubric=["Names the step size.", "Ties it to the gradient."],
        wrong_keys=["rate_is_count"],
        wrong_texts=["Counts iterations."],
        **over,
    )


def _store(key: str, drafts) -> list[str]:
    from services.check_item_service import _Screened, _store_screened

    written = _store_screened(COURSE, key, None, [_Screened(d.format, d) for d in drafts])
    return written.ids


def _refused(db_conn, sql: str, params: tuple) -> None:
    import psycopg

    with pytest.raises(psycopg.errors.CheckViolation):
        with db_conn.transaction():
            db_conn.execute(sql, params)


def test_a_varied_draft_stores_its_representation_plain_and_its_context_encrypted(db_conn):
    from learning.surface import Surface, SurfacedCheckItemDraft
    from services.check_item_service import concept_surfaces
    from services.encryption import decrypt_if_present

    key = f"it varied {uuid.uuid4().hex[:8]}"
    tag = uuid.uuid4().hex[:8]
    surfaced = SurfacedCheckItemDraft(
        **_draft(f"What does the rate scale in run {tag}?", key).model_dump(),
        surface_representation="numeric",
        surface_context="Phone contacts",
    )
    (rid,) = _store(key, [surfaced])
    row = db_conn.execute(
        "SELECT surface_representation, surface_context, apex_key, component_keys, question_hash "
        "FROM check_items WHERE id = %s",
        (rid,),
    ).fetchone()
    assert row["surface_representation"] == "numeric"
    assert row["surface_context"] != "Phone contacts"  # ciphertext at rest
    assert decrypt_if_present(row["surface_context"]) == "Phone contacts"
    assert row["apex_key"] is None and row["component_keys"] is None
    assert concept_surfaces(COURSE, key) == {row["question_hash"]: Surface("numeric", "phone contacts")}


def test_a_multi_concept_draft_is_stored_under_its_combination(db_conn):
    from learning.multi_concept import combo_key
    from services.check_item_service import course_has_items, multi_concept_items

    tag = uuid.uuid4().hex[:8]
    apex, pre = f"it apex {tag}", f"it pre {tag}"
    key = combo_key([apex, pre])
    (rid,) = _store(key, [_draft(f"Pick a rate for this descent run {tag}.", f"{apex} + {pre}", difficulty=3)])
    row = db_conn.execute(
        "SELECT concept_key, apex_key, component_keys FROM check_items WHERE id = %s", (rid,)
    ).fetchone()
    assert row == {"concept_key": key, "apex_key": apex, "component_keys": [apex, pre]}
    assert [i.id for i in multi_concept_items(COURSE, apex)] == [rid]
    assert multi_concept_items(COURSE, pre) == []
    assert course_has_items(COURSE) is True  # the seeded course's own items count; the combination never alone


def test_the_checks_refuse_what_the_code_never_writes(db_conn):
    from learning.multi_concept import combo_key

    tag = uuid.uuid4().hex[:8]
    key = f"it checks {tag}"
    (single,) = _store(key, [_draft(f"Single {tag}?", key)])
    apex, pre, other = f"it a {tag}", f"it b {tag}", f"it c {tag}"
    (combo,) = _store(combo_key([apex, pre]), [_draft(f"Combo {tag}?", "x", difficulty=3)])
    upd = "UPDATE check_items SET {} WHERE id = %s"
    _refused(db_conn, upd.format("surface_representation = 'cartoon', surface_context = 'x'"), (single,))
    _refused(db_conn, upd.format("surface_representation = 'verbal'"), (single,))  # half a descriptor
    _refused(db_conn, upd.format("concept_key = concept_key || chr(31) || 'x'"), (single,))
    _refused(db_conn, upd.format("apex_key = %s"), (pre, combo))  # the apex must lead the components
    _refused(db_conn, upd.format("component_keys = ARRAY[apex_key, %s]"), (other, combo))  # key disagrees
    _refused(db_conn, upd.format("apex_key = NULL"), (combo,))
    four = SEP.join([apex, pre, other, "d"])
    _refused(
        db_conn,
        upd.format("concept_key = %s, component_keys = %s"),
        (four, [apex, pre, other, "d"], combo),
    )
    # what the code writes is accepted
    with db_conn.transaction():
        db_conn.execute(
            upd.format("surface_representation = 'visual', surface_context = 'cipher'"), (single,)
        )
        db_conn.execute(
            upd.format("concept_key = %s, component_keys = %s"),
            (SEP.join([apex, other, pre]), [apex, other, pre], combo),
        )
