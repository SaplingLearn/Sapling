"""#529 repair, real-DB half (Workstream B, epic #537).

The class of bug this file exists to catch: the hermetic suite mocked
`table()` and so never saw that quiz_context's UNIQUE was gone — the
upsert 42P10'd in every real environment for ~7.5 weeks while tests
stayed green. These assertions run against the local Supabase stack
(#397 seam: writes through the app, raw reads through psycopg).
"""
import pytest

pytestmark = pytest.mark.integration

USER = "rich-user-active"


def _seeded_node_id(db_conn) -> str:
    row = db_conn.execute(
        "SELECT id FROM graph_nodes WHERE user_id = %s ORDER BY id LIMIT 1",
        (USER,),
    ).fetchone()
    assert row is not None, "rich seed should provide graph nodes for the active user"
    return row["id"]


def test_quiz_context_unique_constraint_is_restored(db_conn):
    """The #529 repair migration must leave a UNIQUE covering exactly
    (user_id, concept_node_id) — the columns save_quiz_context's
    on_conflict names."""
    rows = db_conn.execute(
        """
        SELECT c.conname,
               array_agg(a.attname ORDER BY k.ord) AS cols
        FROM pg_constraint c
        CROSS JOIN LATERAL unnest(c.conkey) WITH ORDINALITY AS k(attnum, ord)
        JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = k.attnum
        WHERE c.conrelid = 'quiz_context'::regclass AND c.contype = 'u'
        GROUP BY c.conname
        """
    ).fetchall()
    col_sets = [tuple(r["cols"]) for r in rows]
    assert ("user_id", "concept_node_id") in col_sets, (
        f"no UNIQUE on (user_id, concept_node_id); found: {col_sets!r} — "
        "the 0025 regression (#529) is back"
    )


def test_save_quiz_context_upserts_one_row_and_encrypts(db_conn):
    """Two writes for the same (user, concept): before the repair the FIRST
    write already failed with 42P10; after it, the second must replace the
    first (one row), the raw column must be ciphertext, and the app read
    must round-trip the latest payload."""
    from services.quiz_context_service import get_quiz_context, save_quiz_context

    node_id = _seeded_node_id(db_conn)
    save_quiz_context(USER, node_id, {"weak_areas": ["first write"]})
    save_quiz_context(USER, node_id, {"weak_areas": ["second write"]})

    rows = db_conn.execute(
        "SELECT context_json FROM quiz_context "
        "WHERE user_id = %s AND concept_node_id = %s",
        (USER, node_id),
    ).fetchall()
    assert len(rows) == 1, f"upsert must keep exactly one row, found {len(rows)}"

    raw = rows[0]["context_json"]
    # #521: ciphertext stored as a JSONB string scalar — a dict here means
    # the encrypt-at-write path regressed to plaintext.
    assert isinstance(raw, str), f"context_json at rest should be ciphertext str, got {type(raw)}"
    assert "second write" not in raw

    assert get_quiz_context(USER, node_id) == {"weak_areas": ["second write"]}
