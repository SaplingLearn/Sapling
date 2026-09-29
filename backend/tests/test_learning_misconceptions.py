"""PKG-10: misconception store, the slip/misconception/novice rule, the class
rollup, the grade_answer hook. Pure-rule tests need no fixtures; store tests
patch `learning.misconceptions.table`; the rollup test patches `.rpc`."""

from __future__ import annotations

import pathlib
import re
from unittest.mock import MagicMock, patch

import pytest

from learning import params
from learning.params import (
    GAP_CONFIDENCE_MAX,
    MISCONCEPTION_CONFIDENCE,
    MISCONCEPTION_MIN_ISOMORPHS,
    NOVICE_FLOOR_IDK,
    NOVICE_FLOOR_MISSES,
)

BACKEND = pathlib.Path(__file__).resolve().parents[1]
MIG_DIR = BACKEND / "db" / "migrations"


def _migration() -> str:
    hits = sorted(MIG_DIR.glob("*_learning_misconceptions.sql"))
    assert len(hits) == 1, f"expected exactly one learning_misconceptions migration, got {hits}"
    return hits[0].read_text()


def _function_body(sql: str) -> str:
    start = sql.index("CREATE OR REPLACE FUNCTION misconception_rollup")
    return sql[start : sql.index("$$;", start)]


class TestMigration:
    def test_rollup_floor_literal_matches_params(self):
        sql = _migration()
        assert f"HAVING count(DISTINCT m.user_id) >= {params.MISCONCEPTION_ROLLUP_MIN_USERS}" in sql

    def test_rollup_is_backend_only(self):
        """Executable by service_role only (ADR 0023 §5: a backend function, not a
        tutor tool). Functions grant EXECUTE to PUBLIC by default, so PUBLIC is
        revoked unguarded; the Supabase roles are revoked/granted inside the
        role-existence guard (a plain Postgres has none of them, and an
        unguarded REVOKE naming one aborts the migration — the house idiom of
        20260929050404_learning_ai_tutor_daily_calls.sql)."""
        sql = _migration()
        assert "REVOKE ALL ON FUNCTION misconception_rollup(text) FROM PUBLIC;" in sql
        assert re.search(
            r"FOREACH r IN ARRAY ARRAY\['anon', 'authenticated'\] LOOP\s+"
            r"IF EXISTS \(SELECT 1 FROM pg_roles WHERE rolname = r\) THEN\s+"
            r"EXECUTE format\('REVOKE ALL ON TABLE misconceptions FROM %I', r\);\s+"
            r"EXECUTE format\('REVOKE ALL ON FUNCTION misconception_rollup\(text\) FROM %I', r\);",
            sql,
        )
        assert re.search(
            r"IF EXISTS \(SELECT 1 FROM pg_roles WHERE rolname = 'service_role'\) THEN\s+"
            r"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE misconceptions TO service_role;\s+"
            r"GRANT EXECUTE ON FUNCTION misconception_rollup\(text\) TO service_role;",
            sql,
        )

    def test_table_is_rls_locked(self):
        """The anon key the frontend ships reaches every public table through
        PostgREST: RLS with no policy denies every non-bypass role."""
        sql = _migration()
        assert "ALTER TABLE misconceptions ENABLE ROW LEVEL SECURITY;" in sql
        assert "REVOKE ALL ON TABLE misconceptions FROM PUBLIC;" in sql
        assert "CREATE POLICY" not in sql

    def test_security_definer_pins_its_search_path(self):
        fn = _function_body(_migration())
        assert "SECURITY DEFINER" in fn
        assert "SET search_path = public, pg_temp" in fn

    def test_rollup_excludes_resolved_rows(self):
        assert "m.resolved_at IS NULL" in _migration()

    def test_rollup_groups_by_course_concept_not_node(self):
        """Spec §13 A29: graph_nodes rows are per user, so a node_id group holds
        one student and never reaches the distinct-user floor. The rollup keys on
        the course concept (the A2 concept_key) and returns it, never a node id."""
        sql = _migration()
        fn = _function_body(sql)
        key = r"lower(btrim(regexp_replace(g.concept_name, '\s+', ' ', 'g')))"
        assert "RETURNS TABLE (concept_key text, wrong_key text, users int)" in fn
        assert f"GROUP BY g.course_id, {key}, m.wrong_key" in fn
        assert "m.node_id," not in fn.split("FROM", 1)[1].split("FROM", 1)[0]
        assert "GROUP BY m.node_id" not in fn

    def test_rollup_concept_key_mirrors_normalize_concept(self):
        """The SQL key must equal the A2 key check_items use. Mirror the SQL
        expression (whitespace runs → one space, trim, lower) in Python. SQL
        lower() stands in for casefold(): they agree on ASCII names and can
        differ on some non-ASCII characters (e.g. ß) — spec §13 A29's known gap."""
        from services.graph_service import _normalize_concept

        for name in [
            "Derivative",
            "  chain   Rule ",
            "Chain\tRule\n",
            "L'Hôpital's Rule",
            "big-O  Notation",
        ]:
            assert re.sub(r"\s+", " ", name).strip(" ").lower() == _normalize_concept(name)

    def test_evidence_text_has_no_unique(self):
        """Spec §4 encryption rule / inv 9: an encrypted column is never a key."""
        sql = _migration()
        col = re.search(r"^\s*evidence_text\s+text,.*$", sql, re.M)
        assert col, "evidence_text column missing"
        assert "UNIQUE" not in col.group(0).upper()
        assert "UNIQUE INDEX" not in sql.upper()
        assert not re.search(r"UNIQUE\s*\([^)]*evidence_text", sql)

    def test_table_and_index_are_idempotent(self):
        sql = _migration()
        assert "CREATE TABLE IF NOT EXISTS misconceptions" in sql
        assert (
            "CREATE INDEX IF NOT EXISTS misconceptions_user_node_idx "
            "ON misconceptions (user_id, node_id, wrong_key)" in sql
        )
        assert "CREATE OR REPLACE FUNCTION misconception_rollup(p_course_id text)" in sql
        assert "node_id        text NOT NULL REFERENCES graph_nodes(id) ON DELETE CASCADE" in sql

    def test_evidence_text_is_in_the_ciphertext_manifest(self):
        """The E2E `ciphertext` oracle samples the encrypted column (the PKG-04 /
        PKG-09 precedent)."""
        from e2e_oracles.gather import _CIPHERTEXT_MANIFEST

        assert ("misconceptions", "id", "evidence_text") in _CIPHERTEXT_MANIFEST


# ── the rule (pure) ─────────────────────────────────────────────────────────


def _att(
    qh,
    *,
    correct=False,
    wrong_key=None,
    confidence=None,
    difficulty=2,
    idk=False,
    isomorph_of=None,
    node_id="n1",
):
    from learning.misconceptions import Attempt

    return Attempt(
        question_hash=qh,
        node_id=node_id,
        correct=correct,
        wrong_key=wrong_key,
        confidence=confidence,
        difficulty=difficulty,
        idk=idk,
        isomorph_of=isomorph_of,
    )


def _fresh_loop_state() -> dict:
    """The runtime shape of deps.loop_state: the sessions.loop_state JSON
    document PKG-07 carries (HANDOFF-07: `_load_loop_state` returns
    `LoopState.to_json()`)."""
    from learning.policy import LoopState

    return LoopState().to_json()


HIGH = MISCONCEPTION_CONFIDENCE
MID = (GAP_CONFIDENCE_MAX + MISCONCEPTION_CONFIDENCE) / 2
LOW = GAP_CONFIDENCE_MAX / 2
assert MISCONCEPTION_MIN_ISOMORPHS == 2, "rule table below enumerates two isomorphs"
assert NOVICE_FLOOR_IDK >= 2, "one idk alone must not be 'repeated idk'"

RULE_TABLE = [
    ("empty", [], "none"),
    ("plain correct", [_att("h1", correct=True)], "none"),
    ("wrong once, no confidence", [_att("h1", wrong_key="k1")], "unknown"),
    ("wrong once, mid confidence", [_att("h1", wrong_key="k1", confidence=MID)], "unknown"),
    (
        "wrong then right on isomorph",
        [_att("h1", wrong_key="k1"), _att("h2", correct=True, isomorph_of="h1")],
        "slip",
    ),
    (
        "right on non-isomorph after wrong",
        [_att("h1", wrong_key="k1"), _att("h2", correct=True)],
        "none",
    ),
    (
        "two isomorphs same key",
        [_att("h1", wrong_key="k1"), _att("h2", wrong_key="k1", isomorph_of="h1")],
        "misconception",
    ),
    (
        "two isomorphs different keys",
        [_att("h1", wrong_key="k1"), _att("h2", wrong_key="k2", isomorph_of="h1")],
        "unknown",
    ),
    ("two isomorphs, no matched key", [_att("h1"), _att("h2", isomorph_of="h1")], "unknown"),
    (
        "same hash twice same key",
        [_att("h1", wrong_key="k1"), _att("h1", wrong_key="k1")],
        "unknown",
    ),
    (
        "wrong, confidence at threshold",
        [_att("h1", wrong_key="k1", confidence=HIGH)],
        "misconception",
    ),
    ("wrong, confidence at threshold, no key", [_att("h1", confidence=HIGH)], "misconception"),
    ("wrong, low confidence", [_att("h1", wrong_key="k1", confidence=LOW)], "gap"),
    (
        "wrong, confidence at gap max (A6: <=)",
        [_att("h1", wrong_key="k1", confidence=GAP_CONFIDENCE_MAX)],
        "gap",
    ),
    ("right answer wrong reason", [_att("h1", correct=True, wrong_key="k1")], "not_known"),
    (
        "novice: misses at difficulty 1",
        [_att(f"h{i}", difficulty=1) for i in range(NOVICE_FLOOR_MISSES)],
        "novice",
    ),
    (
        "novice: repeated idk",
        [_att(f"h{i}", idk=True, difficulty=3) for i in range(NOVICE_FLOOR_IDK)],
        "novice",
    ),
    ("one idk is not novice", [_att("h1", idk=True, difficulty=3)], "unknown"),
    (
        "below novice floor",
        [_att(f"h{i}", difficulty=1) for i in range(NOVICE_FLOOR_MISSES - 1)],
        "unknown",
    ),
    (
        "misconception outranks novice",
        [_att(f"h{i}", difficulty=1, wrong_key="k1") for i in range(NOVICE_FLOOR_MISSES)],
        "misconception",
    ),
    (
        "slip after novice-count misses still slip",
        [_att(f"h{i}", difficulty=1) for i in range(NOVICE_FLOOR_MISSES)]
        + [_att("hx", correct=True, isomorph_of=f"h{NOVICE_FLOOR_MISSES - 1}")],
        "slip",
    ),
    (
        "a key matched only on the other isomorph does not count",
        [_att("h1", wrong_key="k1"), _att("h2", wrong_key="k1", correct=True, isomorph_of="h1")],
        "not_known",
    ),
]


@pytest.mark.parametrize("label,history,expected", RULE_TABLE, ids=[r[0] for r in RULE_TABLE])
def test_rule_table(label, history, expected):
    from learning.misconceptions import slip_or_misconception

    assert slip_or_misconception(history) == expected


def test_verdict_is_the_evidence_verdict():
    """One vocabulary: the rule's Verdict IS Evidence.verdict's type (PKG-03 reopen)."""
    from learning.evidence import MisconceptionVerdict
    from learning.misconceptions import Verdict

    assert Verdict is MisconceptionVerdict


def test_rule_is_over_one_node_only():
    from learning.misconceptions import slip_or_misconception

    with pytest.raises(ValueError):
        slip_or_misconception([_att("h1", node_id="n1"), _att("h2", node_id="n2")])


def test_attempt_holds_no_free_text_and_bounds_confidence():
    """The attempt log lives in sessions.loop_state (spec §4: no free text): ids,
    enums, bools, numbers and the plaintext key only."""
    from pydantic import ValidationError

    from learning.misconceptions import Attempt

    assert set(Attempt.model_fields) == {
        "question_hash",
        "node_id",
        "correct",
        "wrong_key",
        "confidence",
        "difficulty",
        "idk",
        "isomorph_of",
    }
    with pytest.raises(ValidationError):
        _att("h1", confidence=1.5)
    with pytest.raises(ValidationError):
        Attempt.model_validate({**_att("h1").model_dump(), "evidence_text": "free text"})


def test_attempts_for_node_filters_keeps_order_and_skips_malformed_entries():
    from learning.misconceptions import attempts_for_node

    log = [
        _att("h1", node_id="n2").model_dump(),
        _att("h2").model_dump(),
        {"node_id": "n1", "question_hash": "broken"},  # a malformed row never breaks the rule
        "not a dict",
        _att("h3").model_dump(),
    ]
    got = attempts_for_node(log, "n1")
    assert [a.question_hash for a in got] == ["h2", "h3"]


def test_loop_state_accessors_use_the_one_shape():
    """One accessor set over the runtime loop-state shape; callers never branch on it."""
    from learning.misconceptions import attempts_of, confront_of, set_confront

    s = _fresh_loop_state()
    attempts_of(s).append(_att("h1").model_dump())
    assert attempts_of(s)[0]["question_hash"] == "h1"
    marker = {"node_id": "n1", "wrong_key": "k1", "check_item_id": "ci1"}
    set_confront(s, marker)
    assert confront_of(s) == marker
    set_confront(s, None)
    assert confront_of(s) is None


@pytest.mark.parametrize(
    "bad",
    [
        {"attempts": "x", "confront": "x"},
        {"attempts": None, "confront": ["k1"]},
        {"confront": {"node_id": "n1"}},  # incomplete marker
        {"confront": {"node_id": "n1", "wrong_key": "Bad Key!", "check_item_id": "c"}},
    ],
)
def test_malformed_loop_state_keys_read_as_empty(bad):
    """A malformed stored value reads as empty (fail closed: a lost diagnosis,
    never an error on the student's turn), and appending replaces it."""
    from learning.misconceptions import attempts_of, confront_of

    s = {**_fresh_loop_state(), **bad}
    assert confront_of(s) is None
    log = attempts_of(s)
    assert log == [] or all(isinstance(a, dict) for a in log)
    log.append({"question_hash": "h1"})
    assert attempts_of(s)[-1] == {"question_hash": "h1"}


def test_carry_applies_the_hooks_change_to_a_fresh_document():
    """The route's compare-and-set mutate re-applies the hook's change (the
    attempt, the marker) to the FRESH document; `carry` is that change."""
    from learning.misconceptions import attempts_of, carry, confront_of

    diag = {
        "attempt": _att("h2", wrong_key="k1", isomorph_of="h1").model_dump(),
        "confront": {"node_id": "n1", "wrong_key": "k1", "check_item_id": "ci2"},
    }
    fresh = {**_fresh_loop_state(), "attempts": [_att("h1", wrong_key="k1").model_dump()]}
    carry(fresh, diag)
    assert [a["question_hash"] for a in attempts_of(fresh)] == ["h1", "h2"]
    assert confront_of(fresh) == diag["confront"]
    untouched = {**_fresh_loop_state(), "confront": diag["confront"]}
    carry(untouched, {"attempt": _att("h3").model_dump(), "confront": None})
    assert confront_of(untouched) == diag["confront"], "no new marker never clears a pending one"
    carry(untouched, None)  # an outcome the rule never ran on changes nothing
    assert len(attempts_of(untouched)) == 1


@pytest.mark.parametrize(
    "key,ok",
    [
        ("k1", True),
        ("thinks_x_is_y", True),
        ("Bad", False),
        ("a b", False),
        ("", False),
        ("-x", False),
        ("x" * 64, True),
        ("x" * 65, False),
        (None, False),
        ("[VERDICT", False),
    ],
)
def test_is_key_is_identifier_shaped(key, ok):
    from learning.misconceptions import is_key

    assert is_key(key) is ok


# ── store ──────────────────────────────────────────────────────────────────


def _cached_tables(data: dict):
    mocks: dict = {}

    def factory(name):
        if name not in mocks:
            m = MagicMock(name=name)
            m.select.return_value = data.get(name, [])
            m.insert.return_value = []
            m.update.return_value = []
            mocks[name] = m
        return mocks[name]

    return factory, mocks


def test_record_inserts_new_row_with_encrypted_evidence():
    from learning import misconceptions
    from services.encryption import decrypt_if_present

    factory, mocks = _cached_tables({"misconceptions": []})
    with patch.object(misconceptions, "table", side_effect=factory):
        out = misconceptions.record("u1", "n1", "ci1", "k1", "the derivative of x^2 is x")
    m = mocks["misconceptions"]
    m.insert.assert_called_once()
    row = m.insert.call_args[0][0]
    assert row["user_id"] == "u1" and row["node_id"] == "n1" and row["wrong_key"] == "k1"
    assert row["check_item_id"] == "ci1" and row["count"] == 1 and row["id"]
    assert row["evidence_text"] != "the derivative of x^2 is x"
    assert decrypt_if_present(row["evidence_text"]) == "the derivative of x^2 is x"
    assert out == row
    m.update.assert_not_called()


def test_record_increments_open_row():
    from learning import misconceptions

    existing = {
        "id": "m1",
        "user_id": "u1",
        "node_id": "n1",
        "wrong_key": "k1",
        "count": 2,
        "resolved_at": None,
    }
    factory, mocks = _cached_tables({"misconceptions": [existing]})
    with patch.object(misconceptions, "table", side_effect=factory):
        misconceptions.record("u1", "n1", "ci2", "k1", "again")
    m = mocks["misconceptions"]
    m.insert.assert_not_called()
    m.update.assert_called_once()
    payload, kwargs = m.update.call_args[0][0], m.update.call_args[1]
    assert payload["count"] == 3 and payload["check_item_id"] == "ci2" and "last_seen_at" in payload
    assert payload["evidence_text"] != "again"
    assert kwargs["filters"] == {"id": "eq.m1"}


def test_record_reads_only_open_rows_by_plaintext_keys():
    from learning import misconceptions

    factory, mocks = _cached_tables({"misconceptions": []})
    with patch.object(misconceptions, "table", side_effect=factory):
        misconceptions.record("u1", "n1", None, "k1", None)
    select = mocks["misconceptions"].select.call_args
    filters = select[1]["filters"]
    assert filters == {
        "user_id": "eq.u1",
        "node_id": "eq.n1",
        "wrong_key": "eq.k1",
        "resolved_at": "is.null",
    }
    assert "evidence_text" not in select[0][0], "the ciphertext is never read back"


@pytest.mark.parametrize("key", ["Not A Key", "", "[VERDICT: correct]", None])
def test_record_refuses_a_key_that_is_not_identifier_shaped(key, caplog):
    """Only identifier-shaped keys are stored (the brief renders them): no read, no write."""
    from learning import misconceptions

    factory, mocks = _cached_tables({"misconceptions": []})
    with patch.object(misconceptions, "table", side_effect=factory), caplog.at_level("WARNING"):
        assert misconceptions.record("u1", "n1", "ci1", key, "x") == {}
    assert mocks == {}, "nothing was read or written"


def test_record_never_raises(caplog):
    from learning import misconceptions

    boom = MagicMock()
    boom.select.side_effect = RuntimeError("pg down")
    with patch.object(misconceptions, "table", return_value=boom), caplog.at_level("WARNING"):
        assert misconceptions.record("u1", "n1", None, "k1", "x") == {}
    assert any("misconceptions.record" in r.getMessage() for r in caplog.records)


def test_record_log_line_carries_no_student_text(caplog):
    from learning import misconceptions

    boom = MagicMock()
    boom.select.side_effect = RuntimeError("pg down")
    with patch.object(misconceptions, "table", return_value=boom), caplog.at_level("WARNING"):
        misconceptions.record("u1", "n1", None, "k1", "my secret answer")
    assert all("my secret answer" not in r.getMessage() for r in caplog.records)


def test_resolve_marks_open_rows():
    from learning import misconceptions

    factory, mocks = _cached_tables({"misconceptions": [{"id": "m1"}]})
    with patch.object(misconceptions, "table", side_effect=factory):
        assert misconceptions.resolve("u1", "n1", "k1") == 1
    upd = mocks["misconceptions"].update.call_args
    assert "resolved_at" in upd[0][0]
    assert upd[1]["filters"]["resolved_at"] == "is.null"
    assert upd[1]["filters"]["user_id"] == "eq.u1" and upd[1]["filters"]["wrong_key"] == "eq.k1"


def test_resolve_never_raises():
    from learning import misconceptions

    boom = MagicMock()
    boom.select.side_effect = RuntimeError("pg down")
    with patch.object(misconceptions, "table", return_value=boom):
        assert misconceptions.resolve("u1", "n1", "k1") == 0


def test_open_for_returns_keyed_counts_desc_and_skips_empty_input():
    from learning import misconceptions

    rows = [
        {"node_id": "n1", "wrong_key": "k1", "count": 1},
        {"node_id": "n2", "wrong_key": "k9", "count": 4},
        {"node_id": "n2", "wrong_key": "Not A Key", "count": 9},  # never rendered
    ]
    factory, mocks = _cached_tables({"misconceptions": rows})
    with patch.object(misconceptions, "table", side_effect=factory):
        assert misconceptions.open_for("u1", []) == []
        assert "misconceptions" not in mocks, "no read for an empty id list"
        got = misconceptions.open_for("u1", ["n1", "n2", "n1", ""])
    assert got == [
        {"node_id": "n2", "wrong_key": "k9", "count": 4},
        {"node_id": "n1", "wrong_key": "k1", "count": 1},
    ]
    sel = mocks["misconceptions"].select.call_args
    assert sel[1]["filters"]["node_id"] == 'in.("n1","n2")'
    assert sel[1]["filters"]["resolved_at"] == "is.null" and sel[1]["filters"]["user_id"] == "eq.u1"
    assert "evidence_text" not in sel[0][0]


def test_open_for_never_raises():
    from learning import misconceptions

    boom = MagicMock()
    boom.select.side_effect = RuntimeError("pg down")
    with patch.object(misconceptions, "table", return_value=boom):
        assert misconceptions.open_for("u1", ["n1"]) == []


# ── rollup ─────────────────────────────────────────────────────────────────


def test_rollup_calls_rpc_with_course_id():
    from learning import misconceptions

    rows = [{"concept_key": "chain rule", "wrong_key": "k1", "users": 7}]  # course concept (A29)
    with patch.object(misconceptions, "rpc", return_value=rows) as rpc:
        assert misconceptions.rollup("c1") == rows
    rpc.assert_called_once_with("misconception_rollup", {"p_course_id": "c1"})


def test_rollup_degrades_to_empty(caplog):
    from learning import misconceptions

    with (
        patch.object(misconceptions, "rpc", side_effect=RuntimeError("no fn")),
        caplog.at_level("WARNING"),
    ):
        assert misconceptions.rollup("c1") == []
