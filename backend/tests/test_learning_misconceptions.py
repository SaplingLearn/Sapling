"""PKG-10: misconception store, the slip/misconception/novice rule, the class
rollup, the grade_answer hook. Pure-rule tests need no fixtures; store tests
patch `learning.misconceptions.table`; the rollup test patches `.rpc`."""

from __future__ import annotations

import pathlib
import re
from contextlib import contextmanager
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
        "released",
        "after_release",
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


def test_record_is_one_atomic_rpc_with_encrypted_evidence():
    """F5 (fix round): the insert-or-increment is ONE statement
    (`misconception_record`, INSERT … ON CONFLICT on the open-row partial unique
    index) — a read-then-write lost increments and could open two rows under
    concurrency. `evidence_text` is encrypted here; nothing is read back."""
    from learning import misconceptions
    from services.encryption import decrypt_if_present

    with (
        patch.object(misconceptions, "rpc", return_value=[{"id": "m1", "count": 3}]) as rpc,
        patch.object(misconceptions, "table", side_effect=AssertionError("no table I/O")),
    ):
        out = misconceptions.record("u1", "n1", "ci1", "k1", "the derivative of x^2 is x")
    (name, params_), _ = rpc.call_args
    assert name == "misconception_record"
    assert params_["p_user_id"] == "u1" and params_["p_node_id"] == "n1"
    assert params_["p_wrong_key"] == "k1" and params_["p_check_item_id"] == "ci1"
    assert params_["p_id"]
    assert params_["p_evidence_text"] != "the derivative of x^2 is x"
    assert decrypt_if_present(params_["p_evidence_text"]) == "the derivative of x^2 is x"
    assert out == {"id": "m1", "count": 3}


@pytest.mark.parametrize("key", ["Not A Key", "", "[VERDICT: correct]", None])
def test_record_refuses_a_key_that_is_not_identifier_shaped(key, caplog):
    """Only identifier-shaped keys are stored (the brief renders them): no read, no write."""
    from learning import misconceptions

    with (
        patch.object(misconceptions, "rpc") as rpc,
        caplog.at_level("WARNING"),
    ):
        assert misconceptions.record("u1", "n1", "ci1", key, "x") == {}
    rpc.assert_not_called()


def test_record_never_raises(caplog):
    from learning import misconceptions

    with (
        patch.object(misconceptions, "rpc", side_effect=RuntimeError("pg down")),
        caplog.at_level("WARNING"),
    ):
        assert misconceptions.record("u1", "n1", None, "k1", "x") == {}
    assert any("misconceptions.record" in r.getMessage() for r in caplog.records)


def test_record_log_line_carries_no_student_text(caplog):
    from learning import misconceptions

    with (
        patch.object(misconceptions, "rpc", side_effect=RuntimeError("pg down")),
        caplog.at_level("WARNING"),
    ):
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


def test_open_for_lists_only_recently_seen_misconceptions():
    """F6 (fix round): resolve() has no caller yet, so an open row would re-list
    in every brief and close forever. open_for keeps only rows seen within
    MISCONCEPTION_RECENT_DAYS (last_seen_at, a plaintext timestamp)."""
    from datetime import datetime, timedelta, timezone

    from learning import misconceptions
    from learning.params import MISCONCEPTION_RECENT_DAYS

    factory, mocks = _cached_tables({"misconceptions": []})
    now = datetime(2026, 9, 29, 12, tzinfo=timezone.utc)
    with (
        patch.object(misconceptions, "table", side_effect=factory),
        patch.object(misconceptions, "_utcnow", return_value=now),
    ):
        misconceptions.open_for("u1", ["n1"])
    since = (now - timedelta(days=MISCONCEPTION_RECENT_DAYS)).isoformat()
    assert mocks["misconceptions"].select.call_args[1]["filters"]["last_seen_at"] == f"gte.{since}"


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


@contextmanager
def _no_store_write():
    """grade_answer never touches the misconception store (PKG-10: the route
    writes it, after the one flush); the yielded mock proves nothing called it."""
    boom = AssertionError("grade_answer wrote the misconceptions store")
    with (
        patch("learning.misconceptions.record", side_effect=boom) as rec,
        patch("learning.misconceptions.table", side_effect=boom),
    ):
        yield rec


# ── the grade_answer hook (post-hoc PKG-05) ─────────────────────────────────


def _loop_deps(state=None, **over):
    from agents.deps import SaplingDeps

    kw = dict(
        user_id="u1",
        course_id="c1",
        supabase=None,
        request_id="r",
        session_id="s1",
        learning_loop=True,
        loop_state=_fresh_loop_state() if state is None else state,
    )
    kw.update(over)
    return SaplingDeps(**kw)


def _prior_attempt(qh="h1", key="k1"):
    return dict(
        question_hash=qh,
        node_id="n1",
        correct=False,
        wrong_key=key,
        confidence=None,
        difficulty=2,
        idk=False,
        isomorph_of=None,
    )


def _ev(correct, **kw):
    from learning.evidence import Evidence

    return Evidence(node_id="n1", channel="free_response", correct=correct, **kw)


def _run(coro):
    import asyncio

    return asyncio.run(coro)


def test_hook_marks_a_record_on_misconception_and_sets_confront():
    from agents.tools import check as check_mod
    from agents.tools.check import GradeOutcome
    from learning.misconceptions import attempts_of, confront_of

    deps = _loop_deps()
    attempts_of(deps.loop_state).append(_prior_attempt())
    item = MagicMock(id="ci2", question_hash="h2", difficulty=2)
    grade = GradeOutcome(correct=False, confidence=0.9, matched_wrong_key="k1", wrong_key="k1")
    with _no_store_write():
        verdict = _run(
            check_mod.apply_misconception_rule(deps, item=item, grade=grade, evidence=_ev(False))
        )
    assert verdict == "misconception"
    assert grade.diagnosis["record"] == {
        "node_id": "n1",
        "check_item_id": "ci2",
        "wrong_key": "k1",
    }
    assert attempts_of(deps.loop_state)[-1]["isomorph_of"] == "h1"
    marker = {"node_id": "n1", "wrong_key": "k1", "check_item_id": "ci2"}
    assert confront_of(deps.loop_state) == marker
    # the change the route re-applies to its fresh CAS document
    assert grade.diagnosis == {
        "attempt": attempts_of(deps.loop_state)[-1],
        "confront": marker,
        "cleared": None,
        "record": {"node_id": "n1", "check_item_id": "ci2", "wrong_key": "k1"},
    }


def test_hook_slip_records_nothing():
    from agents.tools import check as check_mod
    from agents.tools.check import GradeOutcome
    from learning.misconceptions import attempts_of, confront_of

    deps = _loop_deps()
    attempts_of(deps.loop_state).append(_prior_attempt())
    item = MagicMock(id="ci2", question_hash="h2", difficulty=2)
    grade = GradeOutcome(correct=True, confidence=0.9)
    with _no_store_write():
        verdict = _run(
            check_mod.apply_misconception_rule(deps, item=item, grade=grade, evidence=_ev(True))
        )
    assert verdict == "slip"
    assert confront_of(deps.loop_state) is None
    assert grade.diagnosis["confront"] is None and grade.diagnosis["attempt"]["correct"] is True


def test_hook_is_inert_without_loop_or_loop_state():
    from agents.deps import SaplingDeps
    from agents.tools import check as check_mod
    from agents.tools.check import GradeOutcome

    off = SaplingDeps(user_id="u1", course_id="c1", supabase=None, request_id="r")
    no_state = SaplingDeps(
        user_id="u1", course_id="c1", supabase=None, request_id="r", learning_loop=True
    )
    off_with_state = _loop_deps(learning_loop=False)
    item = MagicMock(id="ci1", question_hash="h1", difficulty=1)
    with _no_store_write():
        for deps in (off, no_state, off_with_state):
            grade = GradeOutcome(correct=False, confidence=0.9, wrong_key="k1")
            verdict = _run(
                check_mod.apply_misconception_rule(
                    deps, item=item, grade=grade, evidence=_ev(False)
                )
            )
            assert verdict is None and grade.diagnosis is None
    assert no_state.loop_state is None and "attempts" not in off_with_state.loop_state


def test_hook_uses_student_confidence_not_grader_confidence():
    """Spec §3.3: the grader's confidence is diagnosis-only and never enters the
    rule. A grader-confident wrong answer with no student confidence is `unknown`."""
    from agents.tools import check as check_mod
    from agents.tools.check import GradeOutcome
    from learning.misconceptions import attempts_of

    deps = _loop_deps()
    grade = GradeOutcome(correct=False, confidence=0.99, matched_wrong_key="k1", wrong_key="k1")
    with _no_store_write():
        verdict = _run(
            check_mod.apply_misconception_rule(
                deps,
                item=MagicMock(id="ci1", question_hash="h1", difficulty=2),
                grade=grade,
                evidence=_ev(False, confidence=0.99),
            )
        )
    assert verdict == "unknown"
    assert attempts_of(deps.loop_state)[-1]["confidence"] is None


def test_hook_keeps_the_attempt_log_free_of_student_text():
    """spec §4: sessions.loop_state holds no free text — the answer goes to the
    encrypted store only."""
    import json

    from agents.tools import check as check_mod
    from agents.tools.check import GradeOutcome

    deps = _loop_deps()
    attempts = [_prior_attempt()]
    deps.loop_state["attempts"] = attempts
    grade = GradeOutcome(correct=False, confidence=0.9, wrong_key="k1")
    with _no_store_write():
        _run(
            check_mod.apply_misconception_rule(
                deps,
                item=MagicMock(id="ci2", question_hash="h2", difficulty=2),
                grade=grade,
                evidence=_ev(False),
            )
        )
    assert "MY SECRET ANSWER TEXT" not in json.dumps(deps.loop_state)
    assert "MY SECRET ANSWER TEXT" not in json.dumps(grade.diagnosis)


def test_hook_a_misconception_without_a_key_records_nothing():
    """The stated-confidence path (unreachable until a confidence field exists)
    stamps the verdict but records nothing: the store keys on wrong_key."""
    from agents.tools import check as check_mod
    from agents.tools.check import GradeOutcome

    deps = _loop_deps()
    with (
        _no_store_write(),
        patch.object(check_mod, "slip_or_misconception", return_value="misconception"),
    ):
        grade = GradeOutcome(correct=False, confidence=0.9, wrong_key=None)
        verdict = _run(
            check_mod.apply_misconception_rule(
                deps,
                item=MagicMock(id="ci1", question_hash="h1", difficulty=2),
                grade=grade,
                evidence=_ev(False),
            )
        )
    assert verdict == "misconception" and grade.diagnosis["confront"] is None


# ── the key comes only from the decision seam (A22/A24) ────────────────────


def _wrong_item(keys=("k1",)):
    from learning.checks import WrongReason

    return MagicMock(
        id="ci1",
        prompt="What is d/dx x^2?",
        question_hash="h1",
        difficulty=2,
        common_wrong=[WrongReason(key=k, text=f"text of {k}") for k in keys],
    )


def test_match_wrong_key_calls_the_seam_with_prior():
    from unittest.mock import AsyncMock

    from agents.tools import check as check_mod

    prior = MagicMock(matched_wrong_key="k1")
    seam = AsyncMock(return_value=MagicMock(value="k1"))
    with patch.object(check_mod.decisions, "match_wrong_reason", seam):
        got = _run(
            check_mod.match_wrong_key(
                _wrong_item(), prior=prior, answer_text="it is x", deps=_loop_deps()
            )
        )
    assert got == "k1"
    (state,), kwargs = seam.call_args
    assert kwargs["prior"] is prior
    assert state.question == "What is d/dx x^2?" and state.answer == "it is x"
    assert state.wrong == {"k1": "text of k1"}


@pytest.mark.parametrize("value", [None, "none", "", "zz_not_listed"])
def test_match_wrong_key_rejects_unavailable_none_and_unlisted_keys(value):
    """None = the seam reported the prior unavailable (PKG-05b); "none" = NO_MATCH."""
    from unittest.mock import AsyncMock

    from agents.tools import check as check_mod

    seam = AsyncMock(return_value=None if value is None else MagicMock(value=value))
    with patch.object(check_mod.decisions, "match_wrong_reason", seam):
        got = _run(
            check_mod.match_wrong_key(
                _wrong_item(), prior=MagicMock(), answer_text="a", deps=_loop_deps()
            )
        )
    assert got is None


def test_match_wrong_key_rejects_a_listed_key_that_is_not_identifier_shaped():
    """A legacy item may list a key outside wrong_key_form: it is never stored or rendered."""
    from unittest.mock import AsyncMock

    from agents.tools import check as check_mod

    seam = AsyncMock(return_value=MagicMock(value="Mixed Key"))
    with patch.object(check_mod.decisions, "match_wrong_reason", seam):
        got = _run(
            check_mod.match_wrong_key(
                _wrong_item(keys=("Mixed Key",)),
                prior=MagicMock(),
                answer_text="a",
                deps=_loop_deps(),
            )
        )
    assert got is None


def test_match_wrong_key_no_listed_keys_no_prior_no_call_and_seam_failure_is_none(caplog):
    from unittest.mock import AsyncMock

    from agents.tools import check as check_mod

    seam = AsyncMock(side_effect=RuntimeError("seam down"))
    with (
        patch.object(check_mod.decisions, "match_wrong_reason", seam),
        caplog.at_level("WARNING"),
    ):
        no_keys = check_mod.match_wrong_key(
            _wrong_item(keys=()), prior=MagicMock(), answer_text="a", deps=_loop_deps()
        )
        assert _run(no_keys) is None
        no_prior = check_mod.match_wrong_key(
            _wrong_item(), prior=None, answer_text="a", deps=_loop_deps()
        )
        assert _run(no_prior) is None, "never a decision run of its own (A24, the grade cap)"
        seam.assert_not_called()
        failing = check_mod.match_wrong_key(
            _wrong_item(), prior=MagicMock(), answer_text="a", deps=_loop_deps()
        )
        assert _run(failing) is None
    assert any("match_wrong_reason" in r.getMessage() for r in caplog.records)


# ── through the real grade_answer (the grader stubbed, the seam real) ───────


@pytest.fixture
def graded(monkeypatch):
    """grade_answer with its one model seam stubbed (agents.grader.grade, as
    tests/test_learning_check_tool.py's `check` fixture does); the decision
    seam — match_wrong_reason with the grader's result as `prior` — runs for
    real and makes no model call."""
    import agents.grader
    from tests.test_learning_check_tool import _result

    state = {"result": _result(), "calls": 0}

    async def _grade(item, *, format, student_answer, deps):
        state["calls"] += 1
        return state["result"]

    def set_result(**over):
        state["result"] = _result(**over)

    monkeypatch.setattr(agents.grader, "grade", _grade)
    state["set"] = set_result
    return state


def _free(qh, qid=None):
    from tests.test_learning_check_tool import _item

    return _item(id=qid or f"ci-{qh}", question_hash=qh, difficulty=2)


def _mc(qh):
    from tests.test_learning_check_tool import _mc_item

    return _mc_item(id=f"ci-{qh}", question_hash=qh, difficulty=2)


def test_grade_answer_two_isomorphs_same_matched_key_marks_one_record(graded):
    """Two wrong free answers on two isomorphs whose reasons the grader matched
    to w_loop: the second is a misconception, recorded once; the Evidence
    dicts carry verdict and wrong_key; the store gets the student's answer."""
    from agents.tools.check import CheckAnswer, grade_answer
    from learning.misconceptions import confront_of

    deps = _loop_deps()
    graded["set"](item_results={"r1": True, "r2": False}, all_yes=False, matched_wrong_key="w_loop")
    with _no_store_write():
        first = _run(
            grade_answer(
                _free("h1"),
                CheckAnswer(question_hash="h1", answer_text="x"),
                deps=deps,
                node_id="n1",
            )
        )
        second = _run(
            grade_answer(
                _free("h2"),
                CheckAnswer(question_hash="h2", answer_text="x again"),
                deps=deps,
                node_id="n1",
            )
        )
    assert (first.verdict, second.verdict) == ("unknown", "misconception")
    assert first.wrong_key == second.wrong_key == "w_loop"
    ev = deps.pending_evidence
    assert [e["verdict"] for e in ev] == ["unknown", "misconception"]
    assert [e["wrong_key"] for e in ev] == ["w_loop", "w_loop"]
    assert first.diagnosis["record"] is None
    assert second.diagnosis["record"] == {
        "node_id": "n1",
        "check_item_id": "ci-h2",
        "wrong_key": "w_loop",
    }
    assert confront_of(deps.loop_state)["wrong_key"] == "w_loop"


def test_grade_answer_takes_the_key_from_the_seam_with_the_graders_result(graded):
    """A22/A24: the key is decisions.match_wrong_reason's, called with the
    grader's own GradeResult as `prior` (no model call)."""
    from agents.tools import check as check_mod
    from agents.tools.check import CheckAnswer, grade_answer
    from services import decisions

    graded["set"](
        item_results={"r1": False, "r2": False}, all_yes=False, matched_wrong_key="w_loop"
    )
    seen = {}
    real = decisions.match_wrong_reason

    async def spy(state, *, deps, prior=None):
        seen["prior"], seen["state"] = prior, state
        return await real(state, deps=deps, prior=prior)

    with (
        patch.object(check_mod.decisions, "match_wrong_reason", spy),
        _no_store_write(),
        patch.object(decisions, "_run_decision") as run,
    ):
        out = _run(
            grade_answer(
                _free("h1"),
                CheckAnswer(question_hash="h1", answer_text="it loops"),
                deps=_loop_deps(),
                node_id="n1",
            )
        )
    run.assert_not_called()
    assert seen["prior"] is graded["result"] and seen["state"].answer == "it loops"
    assert seen["state"].wrong == {"w_loop": "confuses recursion with a loop"}
    assert out.wrong_key == "w_loop" and graded["calls"] == 1


def test_option_prior_alone_never_records(graded):
    """A22: an mc_reason wrong option keyed w_loop whose reason matched nothing
    carries no key — twice, on two isomorphs, is still not a misconception."""
    from agents.tools.check import CheckAnswer, grade_answer

    deps = _loop_deps()
    graded["set"](item_results={"r1": False, "r2": False}, all_yes=False, matched_wrong_key="")
    with _no_store_write():
        for qh in ("h1", "h2"):
            out = _run(
                grade_answer(
                    _mc(qh),
                    CheckAnswer(question_hash=qh, selected_option="C", reason="because"),
                    deps=deps,
                    node_id="n1",
                )
            )
            assert out.wrong_key is None and out.verdict == "unknown"


def test_a_reason_matched_to_another_options_key_never_records(graded):
    """The chosen option C is keyed w_loop; the reason matched w_speed: no key (A22)."""
    from agents.tools.check import CheckAnswer, grade_answer

    deps = _loop_deps()
    graded["set"](
        item_results={"r1": False, "r2": False}, all_yes=False, matched_wrong_key="w_speed"
    )
    with _no_store_write():
        for qh in ("h1", "h2"):
            out = _run(
                grade_answer(
                    _mc(qh),
                    CheckAnswer(question_hash=qh, selected_option="C", reason="it is faster"),
                    deps=deps,
                    node_id="n1",
                )
            )
            assert out.wrong_key is None


def test_a_matched_mc_reason_on_two_isomorphs_marks_a_record(graded):
    from agents.tools.check import CheckAnswer, grade_answer

    deps = _loop_deps()
    graded["set"](
        item_results={"r1": False, "r2": False}, all_yes=False, matched_wrong_key="w_loop"
    )
    with _no_store_write():
        outs = [
            _run(
                grade_answer(
                    _mc(qh),
                    CheckAnswer(question_hash=qh, selected_option="C", reason="it ends itself"),
                    deps=deps,
                    node_id="n1",
                )
            )
            for qh in ("h1", "h2")
        ]
    assert [o.verdict for o in outs] == ["unknown", "misconception"]
    assert outs[1].diagnosis["record"]["wrong_key"] == "w_loop"
    # the store's evidence text is the text the grader saw (the route writes it)
    from agents.tools.check import grader_answer_text

    answer = CheckAnswer(question_hash="h2", selected_option="C", reason="it ends itself")
    assert grader_answer_text(_mc("h2"), answer) == "Selected option: C\nReason: it ends itself"


def test_unavailable_or_refused_grade_logs_no_attempt_for_either_outcome(graded):
    """Invariant 28: no grade → no attempt, no verdict, no record — for a
    would-be-correct and a would-be-wrong answer alike (A33 refusals too)."""
    from agents.tools.check import CheckAnswer, grade_answer
    from learning.misconceptions import attempts_of

    deps = _loop_deps()
    with _no_store_write():
        for over in ({"unavailable": True}, {"unavailable": True, "refused": "grader_directive"}):
            for all_yes in (True, False):
                graded["set"](all_yes=all_yes, matched_wrong_key="w_loop", **over)
                out = _run(
                    grade_answer(
                        _free("h1"),
                        CheckAnswer(question_hash="h1", answer_text="text"),
                        deps=deps,
                        node_id="n1",
                    )
                )
                assert out.unavailable and out.verdict is None and out.diagnosis is None
    assert attempts_of(deps.loop_state) == [] and deps.pending_evidence == []


def test_idk_is_an_attempt_with_no_key_and_no_grader_call(graded):
    from agents.tools.check import CheckAnswer, grade_answer
    from learning.misconceptions import attempts_of

    deps = _loop_deps()
    out = _run(
        grade_answer(
            _free("h1"), CheckAnswer(question_hash="h1", idk=True), deps=deps, node_id="n1"
        )
    )
    assert graded["calls"] == 0 and out.verdict == "unknown" and out.wrong_key is None
    [attempt] = attempts_of(deps.loop_state)
    assert attempt["idk"] is True and attempt["correct"] is False
    assert deps.pending_evidence[-1]["verdict"] == "unknown"


def test_grade_answer_without_loop_state_is_unchanged(graded):
    """The probe and the review pass no loop state: no rule, no attempt, no
    record; the Evidence carries the matched key and no verdict."""
    from agents.tools.check import CheckAnswer, grade_answer

    graded["set"](item_results={"r1": True, "r2": False}, all_yes=False, matched_wrong_key="w_loop")
    deps = _loop_deps()
    deps.loop_state = None
    with _no_store_write():
        out = _run(
            grade_answer(
                _free("h1"),
                CheckAnswer(question_hash="h1", answer_text="x"),
                deps=deps,
                node_id="n1",
            )
        )
    assert out.verdict is None and out.diagnosis is None and out.wrong_key == "w_loop"
    assert deps.pending_evidence[-1]["verdict"] is None
    assert deps.pending_evidence[-1]["wrong_key"] == "w_loop"


def test_a_correct_answer_on_the_node_clears_a_pending_marker():
    """A marker still pending (its feedback turn was a template at the hard
    budget level) is never used to confront a student who has since answered
    the concept right: the correct attempt clears it, in the snapshot and in
    the change the route re-applies (only if the fresh marker is that one)."""
    from agents.tools import check as check_mod
    from agents.tools.check import GradeOutcome
    from learning.misconceptions import attempts_of, carry, confront_of, set_confront

    marker = {"node_id": "n1", "wrong_key": "k1", "check_item_id": "ci1"}
    deps = _loop_deps()
    attempts_of(deps.loop_state).extend([_prior_attempt("h0"), _prior_attempt("h1")])
    set_confront(deps.loop_state, marker)
    grade = GradeOutcome(correct=True, confidence=0.9)
    with _no_store_write():
        _run(
            check_mod.apply_misconception_rule(
                deps,
                item=MagicMock(id="ci2", question_hash="h2", difficulty=2),
                grade=grade,
                evidence=_ev(True),
            )
        )
    assert confront_of(deps.loop_state) is None
    assert grade.diagnosis["cleared"] == marker
    fresh = {**_fresh_loop_state(), "confront": dict(marker)}
    carry(fresh, grade.diagnosis)
    assert confront_of(fresh) is None
    other = {"node_id": "n1", "wrong_key": "k2", "check_item_id": "ci9"}
    newer = {**_fresh_loop_state(), "confront": dict(other)}
    carry(newer, grade.diagnosis)
    assert confront_of(newer) == other, "a newer marker is never cleared by an older change"


def test_a_correct_answer_on_another_node_keeps_the_marker():
    from agents.tools import check as check_mod
    from agents.tools.check import GradeOutcome
    from learning.evidence import Evidence
    from learning.misconceptions import confront_of, set_confront

    marker = {"node_id": "n9", "wrong_key": "k1", "check_item_id": "ci1"}
    deps = _loop_deps()
    set_confront(deps.loop_state, marker)
    grade = GradeOutcome(correct=True, confidence=0.9)
    _run(
        check_mod.apply_misconception_rule(
            deps,
            item=MagicMock(id="ci2", question_hash="h2", difficulty=2),
            grade=grade,
            evidence=Evidence(node_id="n1", channel="free_response", correct=True),
        )
    )
    assert confront_of(deps.loop_state) == marker and grade.diagnosis.get("cleared") is None


def test_grade_answer_never_persists_the_misconception_store():
    """Spec §13 A75: grade_answer marks the row (diagnosis["record"]); only the
    check route writes it, after its one flush_pending. check.py imports no
    store writer (inv 14's posture: grade_answer persists nothing)."""
    import ast

    src = (BACKEND / "agents" / "tools" / "check.py").read_text()
    names = {
        a.name
        for node in ast.walk(ast.parse(src))
        if isinstance(node, ast.ImportFrom) and node.module == "learning.misconceptions"
        for a in node.names
    }
    assert names and not names & {"record", "resolve", "open_for", "rollup"}


# ── the confrontation eval gates what the route serves (spec §13 A75) ───────


def _confront_eval():
    import importlib
    import sys

    evals = BACKEND / "tests" / "evals"
    for p in (str(evals), str(BACKEND)):
        if p not in sys.path:
            sys.path.insert(0, p)
    return importlib.import_module("misconception_confront")


def test_confront_tiers_match_the_eval_baselines():
    """routes.learn_loop.CONFRONT_TIERS is exactly the tiers whose fresh
    recordings (baselines.json `misconception_confront_routing`, one score
    block per run, >= 3 runs) ALL score 1.0 on every served gate with no case
    raised — A49's min-of-N direction; diagnostics never route."""
    import json

    from agents.loop_tutor import LOOP_ROUTABLE_TIERS, LOOP_TIER_SLOTS
    from routes.learn_loop import CONFRONT_TIERS

    mod = _confront_eval()
    baselines = json.loads((BACKEND / "tests" / "evals" / "baselines.json").read_text())
    routing = baselines["misconception_confront_routing"]
    assert routing["runs"] >= 3
    passing = set()
    for tier, slot in LOOP_TIER_SLOTS.items():
        if slot not in mod.CONFRONT_SLOTS:
            continue
        assert set(baselines[mod.dataset_name(slot)]) == set(mod.SERVED_GATES) | set(
            mod.DIAGNOSTICS
        )
        runs = routing.get(slot) or []
        assert len(runs) == routing["runs"], slot
        if all(not run["_raised"] and all(run[g] >= 1.0 for g in mod.SERVED_GATES) for run in runs):
            passing.add(tier)
    assert passing, "no tier confronts on every served gate"
    assert set(CONFRONT_TIERS) == passing
    assert set(CONFRONT_TIERS) <= set(LOOP_ROUTABLE_TIERS)


def test_the_eval_assembles_the_route_s_confronting_message():
    """The eval's message is the route's: the prefix, then the line built by
    routes.learn_loop.confront_line_for, placed by with_confrontation."""
    from routes.learn_loop import confront_line_for

    mod = _confront_eval()
    for case in mod.CASES:
        msg = mod.assembled(case.inputs)
        line = confront_line_for(case.metadata["misconception"])
        assert msg.count(line) == 1
        assert msg.index("[LOOP PHASE:") < msg.index(line)
        if "[STUDENT MESSAGE]" in msg:
            assert msg.index(line) < msg.index("[STUDENT MESSAGE]")
    assert len(mod.CASES) <= 8


def test_every_confrontation_cassette_is_fresh():
    """Replay would raise on a stale recording; pin it hermetically too."""
    from _replay import load_cassette
    from loop_tutor import LoopRecording

    mod = _confront_eval()
    for slot in mod.CONFRONT_SLOTS:
        for case in mod.CASES:
            body = load_cassette(mod._cassette_dataset(slot), case.name)
            assert body is not None, f"{slot}/{case.name} not recorded"
            mod.check_fresh(LoopRecording.model_validate(body), slot, case.inputs)


# ── fix round F1: an item served after a released answer is a re-check ──────


def test_last_release_on_node_reads_only_the_concepts_latest_attempt():
    """Spec §13 A76: only the NEXT graded item on a concept after a release is a
    re-check (the copy risk). `last_release_on_node` reads the concept's latest
    attempt in this session: True when its reference was released, False when
    not, None when the session has no attempt on the concept (the route then
    reads the evidence journal, R2-2)."""
    from learning.misconceptions import last_release_on_node

    wrong = {**_prior_attempt("h1"), "released": True}
    right = {**_prior_attempt("h2"), "correct": True, "wrong_key": None, "released": False}
    assert last_release_on_node({"attempts": [wrong]}, "n1") is True
    assert last_release_on_node({"attempts": [wrong, right]}, "n1") is False, "the one after"
    assert last_release_on_node({"attempts": [right, wrong]}, "n1") is True
    assert last_release_on_node({"attempts": [wrong]}, "n2") is None
    assert last_release_on_node({}, "n1") is None
    assert last_release_on_node({"attempts": ["junk", {"node_id": "n1"}]}, "n1") is None


@pytest.mark.parametrize(
    "correct,idk,max_rung,released",
    [
        (False, False, 0, True),  # a wrong answer releases the reference (A16)
        (False, True, 0, True),  # idk too
        (True, False, 0, False),
        (True, False, 3, False),  # H1–H3 show no worked answer
        (True, False, 4, True),  # R2-1: an H4 worked sibling was shown
        (True, False, 6, True),  # R2-1: the H6 worked answer was shown
    ],
)
def test_released_is_the_codebase_s_revealed_rule(correct, idk, max_rung, released):
    """R2-1: `released` = not correct, idk, or max_rung >= RUNG_NO_CREDIT_MIN —
    loop_state_store.revealed_hashes' definition."""
    from agents.tools import check as check_mod
    from agents.tools.check import GradeOutcome
    from learning.evidence import Evidence
    from learning.misconceptions import attempts_of

    deps = _loop_deps()
    ev = Evidence(
        node_id="n1", channel="free_response", correct=correct, idk=idk, max_rung=max_rung
    )
    _run(
        check_mod.apply_misconception_rule(
            deps,
            item=MagicMock(id="ci1", question_hash="h1", difficulty=2),
            grade=GradeOutcome(correct=correct, confidence=0.9),
            evidence=ev,
        )
    )
    assert attempts_of(deps.loop_state)[-1]["released"] is released


def test_hook_marks_released_and_after_release_on_the_attempt():
    from agents.tools import check as check_mod
    from agents.tools.check import GradeOutcome
    from learning.misconceptions import attempts_of

    deps = _loop_deps()
    _run(
        check_mod.apply_misconception_rule(
            deps,
            item=MagicMock(id="ci1", question_hash="h1", difficulty=2),
            grade=GradeOutcome(correct=False, confidence=0.9),
            evidence=_ev(False),
        )
    )
    _run(
        check_mod.apply_misconception_rule(
            deps,
            item=MagicMock(id="ci2", question_hash="h2", difficulty=2),
            grade=GradeOutcome(correct=True, confidence=0.9),
            evidence=_ev(True, same_session_recheck=True),
        )
    )
    first, second = attempts_of(deps.loop_state)
    assert (first["released"], first["after_release"]) == (True, False)
    assert (second["released"], second["after_release"]) == (False, True)


def _twin_evidence(recheck: bool) -> dict:
    """The Evidence dict grade_answer builds for a correct free answer on a twin."""
    from agents.tools.check import CheckAnswer, grade_answer
    from tests.test_learning_check_tool import _result

    import agents.grader

    async def _grade(item, *, format, student_answer, deps):
        return _result()

    deps = _loop_deps()
    with patch.object(agents.grader, "grade", _grade):
        _run(
            grade_answer(
                _free("h2"),
                CheckAnswer(question_hash="h2", answer_text="right"),
                deps=deps,
                node_id="n1",
                same_session_recheck=recheck,
            )
        )
    return deps.pending_evidence[-1]


def test_a_twin_after_a_released_answer_is_neither_full_weight_nor_a_streak():
    """F1: wrong → the reference is shown → the twin answered right. Graded as a
    same-session re-check it is down-weighted and the unassisted streak and the
    strong-channel count do not grow (graph_service's rule for a re-check)."""
    from learning.params import WEIGHT_SAME_SESSION_RECHECK
    from tests.test_learning_evidence_apply import _apply, _state_writes

    twin = _twin_evidence(True)
    assert twin["same_session_recheck"] is True
    assert twin["weight"] == WEIGHT_SAME_SESSION_RECHECK < 1.0
    fresh = _twin_evidence(False)
    assert fresh["weight"] == 1.0
    for ev, streak in ((twin, 0), (fresh, 1)):
        row = {**ev, "node_id": "n1"}
        _, mocks, _ = _apply({"evidence": [row]}, edges=[])
        [w] = [w for w in _state_writes(mocks) if w["node_id"] == "n1"]
        assert (w["streak_unassisted"], w["n_strong_unassisted"]) == (streak, streak)


# ── fix round F5/F6: the follow-up migration ────────────────────────────────


def _followup() -> str:
    hits = sorted(MIG_DIR.glob("*_learning_misconceptions_atomic.sql"))
    assert len(hits) == 1, hits
    first = sorted(MIG_DIR.glob("*_learning_misconceptions.sql"))[0]
    assert hits[0].name > first.name, "a NEW migration, after the table's"
    return hits[0].read_text()


class TestFollowupMigration:
    def test_one_open_row_per_key_is_enforced(self):
        sql = _followup()
        assert (
            "CREATE UNIQUE INDEX IF NOT EXISTS misconceptions_open_key_uidx\n"
            "  ON misconceptions (user_id, node_id, wrong_key) WHERE resolved_at IS NULL;" in sql
        )
        # duplicates an old read-then-write left behind are merged first
        assert sql.index("DELETE FROM misconceptions") < sql.index("CREATE UNIQUE INDEX")

    def test_record_is_one_insert_on_conflict_increment(self):
        sql = _followup()
        fn = sql[sql.index("CREATE OR REPLACE FUNCTION misconception_record") :]
        assert "ON CONFLICT (user_id, node_id, wrong_key) WHERE resolved_at IS NULL" in fn
        assert "SET count = misconceptions.count + 1" in fn
        assert "SET search_path = public, pg_temp" in fn

    def test_both_functions_are_backend_only(self):
        sql = _followup()
        for sig in ("misconception_record(text, text, text, text, text, text)",):
            assert f"REVOKE ALL ON FUNCTION {sig} FROM PUBLIC;" in sql
            assert f"EXECUTE format('REVOKE ALL ON FUNCTION {sig} FROM %I', r);" in sql
            assert f"GRANT EXECUTE ON FUNCTION {sig} TO service_role;" in sql

    def test_rollup_joins_the_node_to_its_own_student(self):
        """F6: defense in depth — a row whose node belongs to another student
        never counts toward the rollup."""
        sql = _followup()
        fn = sql[sql.index("CREATE OR REPLACE FUNCTION misconception_rollup") :]
        assert "g.user_id = m.user_id" in fn
        assert f"HAVING count(DISTINCT m.user_id) >= {params.MISCONCEPTION_ROLLUP_MIN_USERS}" in fn
        assert "RETURNS TABLE (concept_key text, wrong_key text, users int)" in fn
        assert "SET search_path = public, pg_temp" in fn
        assert "GROUP BY m.node_id" not in fn

    def test_no_unique_on_the_encrypted_column(self):
        sql = _followup()
        for line in sql.splitlines():
            if "UNIQUE" in line.upper():
                assert "evidence_text" not in line


def test_every_unreleased_eval_case_is_a_line_production_would_send():
    """The eval scores only lines the route would serve: an unreleased case's
    misconception text passes the route's pre-check (F3) — the one function
    drafting also refuses with (fix round 4, spec §13 A77)."""
    from learning.leak import confront_text_states_answer

    mod = _confront_eval()
    for case in mod.CASES:
        meta = case.metadata
        if meta.get("answer_released"):
            continue
        assert not confront_text_states_answer(
            meta["misconception"],
            final_answer=meta["final_answer"],
            prompt=meta.get("item_prompt", ""),
        ), case.name


class _FakeJournal:
    """node_mastery_events + check_items as recent_evidence reads them."""

    def __init__(self, rows, items):
        self.rows, self.items, self.calls = rows, items, []

    def __call__(self, name):
        fake = MagicMock()
        if name == "node_mastery_events":
            fake.select.side_effect = lambda cols, **kw: (
                self.calls.append((name, cols, kw)) or [dict(r) for r in self.rows]
            )
        else:
            assert name == "check_items", name
            fake.select.side_effect = lambda cols, **kw: (
                self.calls.append((name, cols, kw)) or [dict(i) for i in self.items]
            )
        return fake


def test_recent_evidence_reads_the_nodes_rows_and_their_isomorph_classes():
    """A76 (R2-2, R4-1): the student's evidence rows on the node since the
    window, oldest first, each judged by revealed_hashes' rule and tagged with
    its item's (format, difficulty) from ONE check_items read."""
    from learning import loop_state_store as store
    from learning.params import RUNG_NO_CREDIT_MIN

    fake = _FakeJournal(
        [
            {"check_item_id": "ci-a", "question_hash": "a", "correct": False, "max_rung": 0},
            {"check_item_id": "ci-b", "question_hash": "b", "correct": True, "max_rung": 1},
            {
                "check_item_id": "ci-c",
                "question_hash": "c",
                "correct": True,
                "max_rung": RUNG_NO_CREDIT_MIN,
            },
            {"check_item_id": "ci-gone", "question_hash": "d", "correct": True, "max_rung": 0},
        ],
        [
            {"id": "ci-a", "format": "free", "difficulty": 2},
            {"id": "ci-b", "format": "mc_reason", "difficulty": 1},
            {"id": "ci-c", "format": "free", "difficulty": 2},
        ],
    )
    with patch.object(store, "table", side_effect=fake):
        rows = store.recent_evidence("u1", "n1", since="2026-09-28T00:00:00+00:00")
    assert rows == [
        {"question_hash": "a", "released": True, "shape": ("free", 2)},
        {"question_hash": "b", "released": False, "shape": ("mc_reason", 1)},
        {"question_hash": "c", "released": True, "shape": ("free", 2)},
        {"question_hash": "d", "released": False, "shape": None},
    ]
    (_, cols, kw), (name, icols, ikw) = fake.calls
    assert "graph_nodes!inner(user_id)" in cols
    assert kw["filters"] == {
        "graph_nodes.user_id": "eq.u1",
        "node_id": "eq.n1",
        "event_type": "eq.evidence",
        "created_at": "gte.2026-09-28T00:00:00+00:00",
    }
    assert kw["order"] == "created_at.asc,evidence_seq.asc"
    assert name == "check_items" and icols == "id,format,difficulty"
    assert ikw["filters"]["id"].startswith("in.(")


def test_recent_evidence_never_raises():
    """A failed read cannot decide: None (graded normally) with a WARNING."""
    from learning import loop_state_store as store

    t = MagicMock()
    t.select.side_effect = RuntimeError("pg down")
    with patch.object(store, "table", return_value=t):
        assert store.recent_evidence("u1", "n1", since="x") is None


# ── fix round 3 (R3-1): ONE re-check decision for every grading caller ──────


_ITEM = MagicMock(question_hash="h9", format="free", difficulty=2)


def _row(qh, released, shape=("mc_reason", 1)):
    return {"question_hash": qh, "released": released, "shape": shape}


def test_recheck_after_release_reads_the_session_log_then_the_journal():
    """A76: the concept's latest attempt in the session decides "next item"
    when there is one; otherwise the journal's newest row on the node within
    RECHECK_RELEASE_WINDOW_HOURS of `now`. A failed read (None) is no re-check."""
    from datetime import datetime, timedelta, timezone

    from learning import misconceptions as store
    from learning.misconceptions import recheck_after_release
    from learning.params import RECHECK_RELEASE_WINDOW_HOURS

    now = datetime(2026, 9, 29, 12, tzinfo=timezone.utc)
    released = {"attempts": [{**_prior_attempt("h1"), "released": True}]}
    with patch.object(store, "recent_evidence", return_value=[]) as journal:
        assert recheck_after_release("u1", "n1", released, now=now, item=_ITEM) is True
        journal.assert_not_called()  # the session's own log answers first
    for rows, expected in (([_row("a", True)], True), ([_row("a", False)], False), (None, False)):
        with patch.object(store, "recent_evidence", return_value=rows) as journal:
            assert recheck_after_release("u1", "n1", {}, now=now, item=_ITEM) is expected
            assert recheck_after_release("u1", "n1", None, now=now, item=_ITEM) is expected
        since = (now - timedelta(hours=RECHECK_RELEASE_WINDOW_HOURS)).isoformat()
        journal.assert_called_with("u1", "n1", since=since)


def test_recheck_after_release_never_mutates_the_loop_state():
    """The review and the probe pass their own session documents: reading the
    rule must not add an `attempts` key to them."""
    from learning import misconceptions as store
    from learning.misconceptions import last_release_on_node, recheck_after_release

    doc: dict = {"review": {}}
    with patch.object(store, "recent_evidence", return_value=None):
        recheck_after_release("u1", "n1", doc, now=_utc_now(), item=_ITEM)
    assert last_release_on_node(doc, "n1") is None
    assert doc == {"review": {}}


def _utc_now():
    from datetime import datetime, timezone

    return datetime(2026, 9, 29, 12, tzinfo=timezone.utc)


def test_every_grading_caller_decides_the_recheck_through_the_one_helper():
    """R3-1: the review and the probe graded at full weight after a release
    because only the check route asked. Structurally: every production call of
    grade_answer passes `same_session_recheck=`, and the function making it
    calls `recheck_after_release` — a new grading caller cannot forget A76."""
    import ast

    callers = []
    for path in sorted(BACKEND.rglob("*.py")):
        rel = path.relative_to(BACKEND).as_posix()
        if rel.startswith(("tests/", "venv/", ".venv/")) or "/site-packages/" in rel:
            continue
        tree = ast.parse(path.read_text())
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            calls = [
                n
                for n in ast.walk(fn)
                if isinstance(n, ast.Call)
                and (getattr(n.func, "id", None) or getattr(n.func, "attr", None))
                in ("grade_answer", "recheck_after_release")
            ]
            grades = [
                c
                for c in calls
                if (getattr(c.func, "id", None) or getattr(c.func, "attr", None)) == "grade_answer"
            ]
            if not grades:
                continue
            callers.append(f"{rel}::{fn.name}")
            assert len(calls) > len(grades), f"{rel}::{fn.name} never calls recheck_after_release"
            for c in grades:
                assert any(k.arg == "same_session_recheck" for k in c.keywords), (
                    f"{rel}:{c.lineno} grade_answer without same_session_recheck"
                )
    assert {c.split("::")[1] for c in callers} >= {
        "_grade_submission",
        "_probe_submission",
        "grade_review",
    }, callers


@pytest.mark.parametrize(
    "rows,expected",
    [
        ([], False),
        ([_row("x", True, ("free", 2))], True),
        # R4-1: an intermediate item of another class pays nothing
        ([_row("x", True, ("free", 2)), _row("p", False)], True),
        ([_row("x", True, ("free", 2)), _row("p", False), _row("r", False, ("free", 3))], True),
        # an item of the class graded since the release pays the debt
        ([_row("x", True, ("free", 2)), _row("y", False, ("free", 2))], False),
        # ...and a released one of the class opens a new debt
        ([_row("x", True, ("free", 2)), _row("y", True, ("free", 2))], True),
        ([_row("x", True, None), _row("p", False)], False),  # an unreadable item: no class
    ],
)
def test_owed_isomorph_pays_only_on_an_item_of_the_released_class(rows, expected):
    from learning.misconceptions import owed_isomorph

    assert owed_isomorph(rows, ("free", 2)) is expected


def test_the_twin_after_an_intermediate_probe_or_review_is_still_a_recheck():
    """R4-1 sequence, through the real journal read: session A — X (free, d2)
    graded wrong, released. Session B — a probe/review item P (mc_reason, d1)
    on the node takes the "next item" re-check; its correct row becomes the
    newest. X's twin Y (free, d2) is still a re-check (down-weighted, no
    streak). Then Y's own row pays the debt: the next free/d2 item is normal."""
    from learning import loop_state_store as store
    from learning.misconceptions import recheck_after_release
    from learning.params import WEIGHT_SAME_SESSION_RECHECK

    items = [
        {"id": "ci-x", "format": "free", "difficulty": 2},
        {"id": "ci-p", "format": "mc_reason", "difficulty": 1},
        {"id": "ci-y", "format": "free", "difficulty": 2},
    ]
    journal = [{"check_item_id": "ci-x", "question_hash": "x", "correct": False, "max_rung": 0}]
    fake = _FakeJournal(journal, items)
    probe = MagicMock(question_hash="p", format="mc_reason", difficulty=1)
    twin = MagicMock(question_hash="y", format="free", difficulty=2)
    later = MagicMock(question_hash="z", format="free", difficulty=2)
    with patch.object(store, "table", side_effect=fake):
        assert recheck_after_release("u1", "n1", {}, now=_utc_now(), item=probe) is True
        journal.append(
            {"check_item_id": "ci-p", "question_hash": "p", "correct": True, "max_rung": 0}
        )
        assert recheck_after_release("u1", "n1", {}, now=_utc_now(), item=twin) is True
        assert _twin_evidence(True)["weight"] == WEIGHT_SAME_SESSION_RECHECK
        journal.append(
            {"check_item_id": "ci-y", "question_hash": "y", "correct": True, "max_rung": 0}
        )
        assert recheck_after_release("u1", "n1", {}, now=_utc_now(), item=later) is False
