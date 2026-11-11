"""Spec §13 A127: the student's stated confidence, and misconceptions that resolve.

1. Confidence capture. The check, probe and review answer bodies take an
   optional `confidence` — "guessing" / "fairly_sure" / "sure", nothing else,
   and no field the body does not name. It is mapped onto the 0..1 scale the
   §3.3 rule reads (params.STUDENT_CONFIDENCE_LEVELS, †), put on the attempt
   the rule reads (`Attempt.confidence`), so its confidence branches fire —
   "sure" and wrong is a misconception at once, "guessing" and wrong is a gap —
   and stored with the evidence (`node_mastery_events.student_confidence`)
   through the single writer only. A skip is absent, never a default; an idk
   states none; the grader's confidence never stands in for it.
2. Resolution. A correct, unassisted first attempt (rung 0, no help, no
   re-check after a release) on an isomorph — another question on the same
   concept — whose item lists the key closes the open misconception, after the
   grading route's flush and claimed save, with one learn.misconception_resolved
   event; a resolved row leaves the brief, the close and the interleave.
3. The admin's metacognitive calibration: stated confidence vs correctness,
   per channel.
"""

from __future__ import annotations

import asyncio
import pathlib
import re
from datetime import datetime, timedelta, timezone
from typing import Optional, get_args

import pytest

from agents.grader import GradeResult
from learning.checks import WrongReason
from learning.params import (
    GAP_CONFIDENCE_MAX,
    MISCONCEPTION_CONFIDENCE,
    MISCONCEPTION_RECENT_DAYS,
    STUDENT_CONFIDENCE_LEVELS,
)
from tests import test_learn_loop_routes as _routes
from tests import test_learning_probe_planner as _planner
from tests.test_learn_loop_routes import ITEM, _answer, _feedback_agent, _state, client
from tests.split_patches import patch_loop
import services.loop.closing
import services.loop.practice

BACKEND = pathlib.Path(__file__).resolve().parents[1]
MIGRATION = BACKEND / "db" / "migrations" / "20261108092032_learning_student_confidence.sql"

# the route suites' fixtures (their autouse rate-limit overrides apply here too)
gate_on, no_rate_limit, seams = _routes.gate_on, _routes.no_rate_limit, _routes.seams
probe, _no_rate_limit = _planner.probe, _planner._no_rate_limit

GUESSING, FAIRLY_SURE, SURE = (
    STUDENT_CONFIDENCE_LEVELS[k] for k in ("guessing", "fairly_sure", "sure")
)
KEY = "no_base"  # ITEM's listed wrong reason (tests/test_learn_loop_routes.py)
UNASSISTED = {
    "correct": True,
    "idk": False,
    "max_rung": 0,
    "assisted": False,
    "same_session_recheck": False,
}


# ── the store, in memory (the PostgREST filters resolve() and the readers use) ─


class FakeMisconceptions:
    """`table("misconceptions")` over in-memory rows: select and the
    conditional update, with the filter ops the store uses (eq, neq, in,
    is.null, gte, an `or=(…)` tree and `select=`). PostgREST semantics: `neq`
    is false on NULL."""

    def __init__(self, rows=()):
        self.rows = [dict(r) for r in rows]
        self.updates: list[dict] = []

    @staticmethod
    def _holds(row, col, cond) -> bool:
        if col == "select":
            return True
        if col == "or":
            parts = cond.strip("()").split(",")
            return any(FakeMisconceptions._holds(row, *p.split(".", 1)) for p in parts)
        op, _, target = cond.partition(".")
        value = row.get(col)
        if op == "eq":
            return value is not None and str(value) == target
        if op == "neq":
            return value is not None and str(value) != target.strip('"')
        if op == "is" and target == "null":
            return value is None
        if op == "in":
            return value in [v.strip('"') for v in target.strip("()").split(",")]
        if op == "gte":
            return value is not None and str(value) >= target
        raise AssertionError(f"unsupported filter {col}={cond}")

    def _matching(self, filters):
        return [r for r in self.rows if all(self._holds(r, c, v) for c, v in filters.items())]

    @staticmethod
    def _project(row, cols):
        return {c: row.get(c) for c in cols.split(",")} if cols and cols != "*" else dict(row)

    def select(self, cols="*", filters=None, **_kw):
        return [self._project(r, cols) for r in self._matching(filters or {})]

    def update(self, data, filters):
        self.updates.append({"data": dict(data), "filters": dict(filters)})
        hit = self._matching(filters)
        for row in hit:
            row.update(data)
        return [self._project(r, filters.get("select", "*")) for r in hit]


def _row(node="n1", key="k1", item="ci-0", *, days_ago=1, resolved=None, count=1, user="u1"):
    seen = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()
    return {
        "id": f"m-{node}-{key}-{item}",
        "user_id": user,
        "node_id": node,
        "check_item_id": item,
        "wrong_key": key,
        "evidence_text": "CIPHERTEXT",
        "count": count,
        "first_seen_at": seen,
        "last_seen_at": seen,
        "resolved_at": resolved,
    }


@pytest.fixture
def store(monkeypatch):
    """learning.misconceptions over a FakeMisconceptions; `events` collects
    what the resolution logs."""
    from learning import misconceptions

    fake = FakeMisconceptions()
    events: list = []
    monkeypatch.setattr(misconceptions, "table", lambda name: fake)
    monkeypatch.setattr(misconceptions, "log_event", lambda et, **kw: events.append((et, kw)))
    fake.events = events
    return fake


# ── 1. the mapping (†) and the rule's dead branches ────────────────────────


def test_the_labels_are_the_answer_bodies_enum():
    from learning.evidence import StudentConfidence
    from models import LoopCheckAnswerBody, ProbeAnswerBody, ReviewAnswerBody

    assert get_args(StudentConfidence) == tuple(STUDENT_CONFIDENCE_LEVELS)
    for body in (LoopCheckAnswerBody, ProbeAnswerBody, ReviewAnswerBody):
        assert body.model_fields["confidence"].annotation == Optional[StudentConfidence]
        assert body.model_fields["confidence"].default is None  # a skip is absent
        assert body.model_config.get("extra") == "forbid"


def test_the_post_test_takes_no_confidence():
    """The post-test stays tool-free and minimal (A127): no control, no field."""
    from models import PosttestAnswerBody

    assert "confidence" not in PosttestAnswerBody.model_fields


def test_each_label_is_the_midpoint_of_its_rule_band():
    assert 0 <= GUESSING <= GAP_CONFIDENCE_MAX < FAIRLY_SURE < MISCONCEPTION_CONFIDENCE <= SURE <= 1
    assert GUESSING == pytest.approx(GAP_CONFIDENCE_MAX / 2)
    assert FAIRLY_SURE == pytest.approx((GAP_CONFIDENCE_MAX + MISCONCEPTION_CONFIDENCE) / 2)
    assert SURE == pytest.approx((MISCONCEPTION_CONFIDENCE + 1) / 2)


def test_stated_confidence_is_absent_for_a_skip_and_an_idk():
    from learning.evidence import stated_confidence

    assert [stated_confidence(k) for k in STUDENT_CONFIDENCE_LEVELS] == [GUESSING, FAIRLY_SURE, SURE]
    assert stated_confidence(None) is None
    assert stated_confidence("sure", idk=True) is None
    with pytest.raises(KeyError):
        stated_confidence("certain")


@pytest.mark.parametrize(
    "label,verdict",
    [("guessing", "gap"), ("fairly_sure", "unknown"), ("sure", "misconception"), (None, "unknown")],
)
def test_a_stated_label_selects_its_rule_branch(label, verdict):
    """Spec §3.3 on one wrong, keyless attempt: the confidence branches fire."""
    from learning.evidence import stated_confidence
    from learning.misconceptions import Attempt, slip_or_misconception

    attempt = Attempt(
        question_hash="h1",
        node_id="n1",
        correct=False,
        confidence=stated_confidence(label),
        difficulty=2,
    )
    assert slip_or_misconception([attempt]) == verdict


# ── 1b. through the real grade_answer (the hook reads the attempt log) ─────


def _grade_result(*, correct: bool, matched: str = "") -> GradeResult:
    return GradeResult(
        item_results={"r1": correct, "r2": correct},
        all_yes=correct,
        confidence=0.95,  # the GRADER's: it never reaches the rule or the column
        matched_wrong_key=matched,
        backend="gemini",
    )


@pytest.fixture
def grader(monkeypatch):
    """grade_answer's one model seam stubbed; `grader["result"]` is the verdict."""
    import agents.grader

    state = {"result": _grade_result(correct=False, matched=KEY)}

    async def _grade(item, *, format, student_answer, deps):
        return state["result"]

    monkeypatch.setattr(agents.grader, "grade", _grade)
    return state


def _deps(**over):
    from agents.deps import SaplingDeps

    kw = dict(
        user_id="u1",
        course_id="c1",
        supabase=None,
        request_id="r",
        session_id="s1",
        feature="loop_check",
        learning_loop=True,
        loop_state={},
    )
    kw.update(over)
    return SaplingDeps(**kw)


def _item(qh="qh-1", item_id="item-1", keys=(KEY,)):
    from tests.test_learning_check_tool import _item as base

    return base(
        id=item_id,
        question_hash=qh,
        difficulty=2,
        common_wrong=[WrongReason(key=k, text=f"believes {k}") for k in keys],
    )


def _graded(deps, *, confidence=None, idk=False, item=None, confront=True):
    from agents.tools.check import CheckAnswer, grade_answer

    item = item or _item()
    answer = CheckAnswer(
        question_hash=item.question_hash,
        answer_text="" if idk else "an answer",
        idk=idk,
        confidence=confidence,
    )
    return asyncio.run(grade_answer(item, answer, deps=deps, node_id="n1", confront=confront))


def test_sure_and_wrong_with_a_matched_key_is_a_misconception_on_one_attempt(grader):
    """Before A127 one matched answer was `unknown` (wrong once); stated "sure",
    it records and confronts at once (§3.3 "or wrong with stated confidence
    ≥ MISCONCEPTION_CONFIDENCE")."""
    from learning.misconceptions import attempts_of, confront_of

    deps = _deps()
    out = _graded(deps, confidence="sure")
    assert out.verdict == "misconception"
    marker = {"node_id": "n1", "wrong_key": KEY, "check_item_id": "item-1"}
    assert out.diagnosis["record"] == marker and out.diagnosis["confront"] == marker
    assert confront_of(deps.loop_state) == marker
    [attempt] = attempts_of(deps.loop_state)
    assert attempt["confidence"] == SURE
    assert out.evidence["student_confidence"] == SURE
    assert out.evidence["confidence"] == 0.95  # the grader's stays in its own field
    assert out.evidence["verdict"] == "misconception"


def test_the_probe_records_a_sure_misconception_but_never_confronts(grader):
    deps = _deps(feature="loop_probe")
    out = _graded(deps, confidence="sure", confront=False)
    assert out.verdict == "misconception" and out.diagnosis["record"] is not None
    assert out.diagnosis["confront"] is None and deps.loop_state.get("confront") is None


def test_sure_and_wrong_without_a_key_stamps_the_verdict_and_records_nothing(grader):
    grader["result"] = _grade_result(correct=False)
    out = _graded(_deps(), confidence="sure")
    assert out.verdict == "misconception"
    assert out.diagnosis["record"] is None and out.diagnosis["confront"] is None


def test_guessing_and_wrong_is_a_gap_so_no_isomorph_is_re_asked(grader):
    """§3.3 "wrong with low confidence → gap: teach" — the check route's
    re-ask of an isomorph follows `unknown` only (A75 (g))."""

    deps = _deps()
    out = _graded(deps, confidence="guessing")
    assert out.verdict == "gap" and out.diagnosis["record"] is None
    twin = _item(qh="qh-2", item_id="item-2")
    assert services.loop.practice._isomorph_after_unknown(deps.loop_state, "n1", [_item(), twin], set()) is None


@pytest.mark.parametrize("confidence", ["fairly_sure", None])
def test_fairly_sure_or_skipped_and_wrong_stays_unknown(grader, confidence):
    deps = _deps()
    out = _graded(deps, confidence=confidence)
    assert out.verdict == "unknown"
    assert deps.loop_state["attempts"][-1]["confidence"] == (
        None if confidence is None else FAIRLY_SURE
    )
    assert out.evidence["student_confidence"] == (None if confidence is None else FAIRLY_SURE)


def test_an_idk_states_no_confidence(grader):
    deps = _deps()
    out = _graded(deps, confidence="sure", idk=True)
    assert out.evidence["idk"] is True and out.evidence["student_confidence"] is None
    assert deps.loop_state["attempts"][-1]["confidence"] is None
    assert out.verdict == "unknown"  # never "misconception" off a confidence the idk overrode


def test_the_stated_confidence_never_weights_the_evidence(grader):
    """A127: the student's confidence is a diagnosis input and a report column;
    the BKT weight reads the grader's confidence only."""
    from learning.evidence import Evidence

    base = dict(node_id="n1", channel="free_response", correct=True)
    for stated in (None, GUESSING, SURE):
        assert Evidence(**base, student_confidence=stated).weight == 1.0
    assert Evidence(**base, confidence=0.3, student_confidence=SURE).weight == Evidence(
        **base, confidence=0.3
    ).weight


# ── 2. the answer routes: validation, and the label reaching the grade ─────


@pytest.mark.parametrize(
    "extra",
    [
        {"confidence": "very_sure"},
        {"confidence": "Sure"},
        {"confidence": 0.9},
        {"confidence": ""},
        {"confidance": "sure"},  # an unknown field is refused, never dropped
        {"model_pref": "smart"},
    ],
)
@pytest.mark.parametrize("path", ["/check/answer", "/check/answer/stream"])
def test_the_check_answer_body_refuses_anything_else(gate_on, seams, path, extra):
    r = client.post(f"/api/learn/loop{path}", json=_answer(answer="n == 0", **extra))
    assert r.status_code == 422, r.text
    seams.grade.assert_not_called()


@pytest.mark.parametrize("label", list(STUDENT_CONFIDENCE_LEVELS) + [None])
def test_the_check_route_hands_the_label_to_the_grade(gate_on, seams, label):
    agent_p, usage_p, _ = _feedback_agent()
    body = _answer(answer="n == 0 returns 1") | ({"confidence": label} if label else {})
    with agent_p, usage_p:
        r = client.post("/api/learn/loop/check/answer", json=body)
    assert r.status_code == 200, r.text
    _, answer = seams.grade.call_args.args
    assert answer.confidence == label


def test_the_check_route_drops_the_confidence_of_an_idk(gate_on, seams):
    """An idk phrase routes to idk (A16): it states no confidence (A127)."""
    seams.grade.return_value = _routes.WRONG  # an idk is never correct
    agent_p, usage_p, _ = _feedback_agent()
    with agent_p, usage_p:
        r = client.post(
            "/api/learn/loop/check/answer", json=_answer(answer="idk", confidence="sure")
        )
    assert r.status_code == 200, r.text
    _, answer = seams.grade.call_args.args
    assert answer.idk is True and answer.confidence is None


def _probe_body(**kw):
    return {"session_id": "s1", "user_id": _planner.UID, "question_hash": "h-A-3", **kw}


@pytest.mark.parametrize(
    "extra", [{"confidence": "certain"}, {"confidence": 1}, {"confidance": "sure"}]
)
def test_the_probe_answer_body_refuses_anything_else(probe, extra):
    _planner._answer_doc(probe)
    r = client.post(f"{_planner.LOOP}/probe/answer", json=_probe_body(answer="x", **extra))
    assert r.status_code == 422, r.text
    probe.grade.assert_not_called()


@pytest.mark.parametrize("label", ["guessing", None])
def test_the_probe_hands_the_label_to_the_grade(probe, label):
    _planner._answer_doc(probe)
    body = _probe_body(answer="because") | ({"confidence": label} if label else {})
    r = client.post(f"{_planner.LOOP}/probe/answer", json=body)
    assert r.status_code == 200, r.text
    _, answer = probe.grade.call_args.args
    assert answer.confidence == label


# ── 3. the evidence column, through the single writer only ─────────────────


def test_the_single_writer_journals_the_stated_confidence():
    from tests.test_learning_evidence_apply import _apply, _event_rows

    base = {"node_id": "n1", "channel": "free_response", "correct": True, "confidence": 0.95}
    _, mocks, _ = _apply({"evidence": [{**base, "student_confidence": SURE}, base]}, edges=[])
    stated, skipped = _event_rows(mocks)
    assert stated["student_confidence"] == SURE and stated["confidence"] == 0.95
    # none stated: the key is absent — the row (and its plan) as before A127
    assert "student_confidence" not in skipped and skipped["confidence"] == 0.95


@pytest.mark.parametrize("bad", [-0.1, 1.5, float("nan")])
def test_an_out_of_range_stated_confidence_writes_nothing(bad):
    from pydantic import ValidationError

    from tests.test_learning_evidence_apply import _apply

    with pytest.raises(ValidationError):
        _apply(
            {"evidence": [{"node_id": "n1", "channel": "mc", "correct": True,
                           "student_confidence": bad}]},
            edges=[],
        )


def test_the_fingerprint_of_evidence_without_a_stated_confidence_is_unchanged():
    """A grade committed before A127 replays after the deploy: an absent stated
    confidence leaves the operation's fingerprint as it was; a stated one is
    part of the operation's identity."""
    import hashlib
    import json

    from learning.evidence import Evidence
    from learning.evidence_transaction import fingerprint

    ev = Evidence(node_id="n1", channel="mc", correct=True, session_id="s1", question_hash="q")
    before = ev.model_dump(mode="json", exclude={"operation_id", "student_confidence"})
    legacy = hashlib.sha256(
        json.dumps(
            {"user_id": "u1", "course_id": "c1", "retention": None, "evidence": [before]},
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    ).hexdigest()
    assert fingerprint("u1", "c1", [ev], None) == legacy
    stated = ev.model_copy(update={"student_confidence": SURE})
    assert fingerprint("u1", "c1", [stated], None) != legacy


def test_the_migration_adds_the_column_and_the_commit_function_admits_it():
    sql = MIGRATION.read_text()
    assert re.search(
        r"ALTER TABLE public\.node_mastery_events ADD COLUMN IF NOT EXISTS "
        r"student_confidence double precision;",
        sql,
    )
    assert "CHECK (student_confidence IS NULL OR (student_confidence >= 0 AND " in sql
    fn = sql[sql.index("CREATE OR REPLACE FUNCTION learning_evidence_commit") :]
    allow = fn[fn.index("'id','node_id','delta'") : fn.index("RAISE EXCEPTION 'Invalid transaction evidence'")]
    assert "'student_confidence'" in allow
    assert "ev.student_confidence BETWEEN 0 AND 1" in allow
    insert = fn[fn.index("INSERT INTO node_mastery_events") :]
    columns, values = insert.split("VALUES", 1)
    assert "student_confidence" in columns and "ev.student_confidence" in values.split(";")[0]
    assert "GRANT EXECUTE ON FUNCTION learning_evidence_commit" in sql


#: The A123 × A127 reconcile, the definition A141's review re-creates.
RECONCILE = (
    BACKEND / "db" / "migrations" / "20261108103333_learning_evidence_commit_reconcile.sql"
)
#: A123's definition, the one A127's three edits are applied to.
A123_VOID = BACKEND / "db" / "migrations" / "20261108072715_learning_evidence_void.sql"
#: Spec §13 A141's review: the LAST definition of learning_evidence_commit, the
#: reconcile's with the journal's multi_concept key.
A141_REVIEW = BACKEND / "db" / "migrations" / "20261108205812_learning_varied_practice_review.sql"


def _commit_body(text: str) -> str:
    start = text.index("CREATE OR REPLACE FUNCTION learning_evidence_commit")
    return text[start : text.index("END $$;", start)]


def test_the_function_the_database_runs_is_a123s_plus_the_new_key():
    """Re-created, never rewritten. A127's own migration re-created the
    pre-A123 body (20261019141950) plus the key, which, applied after A123's,
    dropped A123's item lock and retired refusal. The reconcile's definition,
    with A127's three edits taken out, is byte-identical to A123's. The
    function the database runs is A141's review's (20261108205812): with its
    three edits taken out (the multi_concept key admitted, checked and
    inserted), it is byte-identical to the reconcile's, and no later
    migration re-creates it."""
    new = _commit_body(RECONCILE.read_text())
    new = new.replace(
        "'retention','same_session_recheck','propagated_to',\n                'student_confidence'))\n"
        "           -- spec §13 A127: a stated confidence is a JSON number in [0, 1], or absent/null\n"
        "           OR (x ? 'student_confidence' AND jsonb_typeof(x->'student_confidence') NOT IN ('number','null'))\n"
        "           OR NOT (ev.student_confidence IS NULL OR ev.student_confidence BETWEEN 0 AND 1) THEN",
        "'retention','same_session_recheck','propagated_to')) THEN",
    )
    new = new.replace(
        "retention,same_session_recheck,propagated_to,\n            student_confidence)",
        "retention,same_session_recheck,propagated_to)",
    )
    new = new.replace(
        "ev.retention,ev.same_session_recheck,ev.propagated_to,\n            ev.student_confidence);",
        "ev.retention,ev.same_session_recheck,ev.propagated_to);",
    )
    assert new == _commit_body(A123_VOID.read_text())
    review = _commit_body(A141_REVIEW.read_text())
    for edited, original in (
        (
            "                'student_confidence',\n                'multi_concept'))",
            "                'student_confidence'))",
        ),
        (
            "           OR NOT (ev.student_confidence IS NULL OR ev.student_confidence BETWEEN 0 AND 1)\n"
            "           -- spec §13 A141: a multi-concept item's row says so: a JSON boolean, or absent/null\n"
            "           OR (x ? 'multi_concept' AND jsonb_typeof(x->'multi_concept') NOT IN ('boolean','null')) THEN",
            "           OR NOT (ev.student_confidence IS NULL OR ev.student_confidence BETWEEN 0 AND 1) THEN",
        ),
        ("            multi_concept,\n            student_confidence)", "            student_confidence)"),
        ("            ev.multi_concept,\n            ev.student_confidence);", "            ev.student_confidence);"),
    ):
        assert review.count(edited) == 1, edited
        review = review.replace(edited, original)
    assert review == _commit_body(RECONCILE.read_text())
    later = [
        p.name
        for p in sorted((BACKEND / "db" / "migrations").glob("*.sql"))
        if p.name > RECONCILE.name
        and "CREATE OR REPLACE FUNCTION learning_evidence_commit" in p.read_text()
    ]
    assert later == [A141_REVIEW.name], "a later migration re-creates the function: re-pin it here"


# ── 4. the resolution rule ──────────────────────────────────────────────────


@pytest.mark.parametrize(
    "change,resolves",
    [
        ({}, True),
        ({"max_rung": 1, "assisted": True}, False),  # H1–H3: assisted
        ({"max_rung": 4, "assisted": True}, False),  # a worked answer / a reveal
        ({"max_rung": 4}, False),  # each flag is read on its own: the rung …
        ({"assisted": True}, False),  # … the assisted flag …
        ({"idk": True}, False),  # … and an idk (never correct; refused even if marked so)
        ({"same_session_recheck": True}, False),  # A76: a re-check after a release
        ({"correct": False}, False),
        ({"correct": False, "idk": True}, False),
        ({"max_rung": True}, False),  # a bool is no rung
        ({"max_rung": None}, False),
    ],
)
def test_resolves_only_a_correct_unassisted_first_attempt(change, resolves):
    from learning.misconceptions import resolves as rule

    assert rule({**UNASSISTED, **change}) is resolves


def test_the_closable_keys_are_the_items_but_one_the_reason_matched():
    from learning.misconceptions import resolvable_keys

    item = _item(keys=("k_b", "k_a", "k_a", "Not A Key"))
    assert resolvable_keys(item, correct=True) == ["k_a", "k_b"]
    assert resolvable_keys(item, correct=True, matched_wrong_key="k_a") == ["k_b"]
    assert resolvable_keys(item, correct=False) == []
    assert resolvable_keys(item, correct=True, idk=True) == []


def test_a_correct_unassisted_isomorph_answer_closes_the_key_once(store):
    from learning.misconceptions import resolve_after_grade

    store.rows = [_row(item="ci-0", count=3)]
    closed = resolve_after_grade(
        "u1", "n1", keys=["k1"], item_id="ci-1", attempt=UNASSISTED, surface="check",
        session_id="s1", request_id="r1",
    )
    assert closed == ["k1"] and store.rows[0]["resolved_at"] is not None
    assert store.events == [
        (
            "learn.misconception_resolved",
            {
                "category": "usage",
                "user_id": "u1",
                "request_id": "r1",
                "payload": {
                    "node_id": "n1",
                    "wrong_key": "k1",
                    "check_item_id": "ci-1",
                    "recorded_on": "ci-0",
                    "count": 3,
                    "surface": "check",
                    "session_id": "s1",
                },
            },
        )
    ]
    # a second grade finds nothing open: no second close, no second event
    again = resolve_after_grade(
        "u1", "n1", keys=["k1"], item_id="ci-2", attempt=UNASSISTED, surface="review"
    )
    assert again == [] and len(store.events) == 1


@pytest.mark.parametrize(
    "attempt",
    [
        {**UNASSISTED, "max_rung": 2, "assisted": True},
        {**UNASSISTED, "same_session_recheck": True},
        {**UNASSISTED, "correct": False},
    ],
    ids=["assisted", "recheck", "wrong"],
)
def test_an_assisted_rechecked_or_wrong_answer_closes_nothing(store, attempt):
    from learning.misconceptions import resolve_after_grade

    store.rows = [_row()]
    assert resolve_after_grade(
        "u1", "n1", keys=["k1"], item_id="ci-1", attempt=attempt, surface="check"
    ) == []
    assert store.rows[0]["resolved_at"] is None and store.updates == [] and store.events == []


def test_an_answer_that_tests_a_different_key_closes_nothing(store):
    from learning.misconceptions import resolve_after_grade

    store.rows = [_row(key="k1")]
    assert resolve_after_grade(
        "u1", "n1", keys=["k2"], item_id="ci-1", attempt=UNASSISTED, surface="check"
    ) == []
    assert store.rows[0]["resolved_at"] is None and store.events == []


def test_the_question_it_was_recorded_on_is_no_isomorph(store):
    from learning.misconceptions import resolve_after_grade

    store.rows = [_row(item="ci-1")]
    assert resolve_after_grade(
        "u1", "n1", keys=["k1"], item_id="ci-1", attempt=UNASSISTED, surface="check"
    ) == []
    assert store.rows[0]["resolved_at"] is None


def test_only_the_students_open_row_on_that_concept_closes(store):
    from learning.misconceptions import resolve_after_grade

    other_node, other_user = _row(node="n2"), _row(user="u2")
    already = _row(item="ci-7", resolved="2026-10-01T00:00:00+00:00")
    store.rows = [_row(), other_node, other_user, already]
    assert resolve_after_grade(
        "u1", "n1", keys=["k1"], item_id="ci-1", attempt=UNASSISTED, surface="probe"
    ) == ["k1"]
    assert [r["resolved_at"] is not None for r in store.rows] == [True, False, False, True]
    assert already["resolved_at"] == "2026-10-01T00:00:00+00:00"  # never re-stamped


def test_an_unknown_surface_is_a_caller_bug():
    from learning.misconceptions import resolve_after_grade

    with pytest.raises(ValueError):
        resolve_after_grade("u1", "n1", keys=["k1"], item_id="ci-1", attempt=UNASSISTED,
                            surface="posttest")


# ── 5. a resolved misconception leaves every reader ────────────────────────


def _resolve_k1(store):
    from learning.misconceptions import resolve_after_grade

    return resolve_after_grade(
        "u1", "n1", keys=["k1"], item_id="ci-1", attempt=UNASSISTED, surface="check"
    )


def test_a_resolved_key_leaves_the_store_readers(store):
    from learning.misconceptions import open_for, open_keys

    store.rows = [_row(), _row(node="n2", key="k2")]
    assert {r["wrong_key"] for r in open_for("u1", ["n1", "n2"])} == {"k1", "k2"}
    assert open_keys("u1", ["k1", "k2"]) == {"k1", "k2"}
    _resolve_k1(store)
    assert [r["wrong_key"] for r in open_for("u1", ["n1", "n2"])] == ["k2"]
    assert open_keys("u1", ["k1", "k2"]) == {"k2"}


def test_open_keys_keeps_the_recency_window_and_reads_nothing_for_nothing(store):
    from learning.misconceptions import open_keys

    store.rows = [_row(days_ago=MISCONCEPTION_RECENT_DAYS + 1)]
    assert open_keys("u1", ["k1"]) == set()
    assert open_keys("u1", []) == set() and open_keys("u1", ["Not A Key"]) == set()


def test_open_keys_never_raises(monkeypatch):
    from learning import misconceptions

    def boom(name):
        raise RuntimeError("pg down")

    monkeypatch.setattr(misconceptions, "table", boom)
    assert misconceptions.open_keys("u1", ["k1"]) == set()


def test_a_resolved_key_leaves_the_brief(store):
    """Both halves of the brief's list: the in-play rows and a recent close's key."""
    import learning.learner_brief as lb

    store.rows = [_row()]
    closes = [{"misconceptions": ["k1"]}]
    assert lb._open_misconception_keys("u1", ["n1"], closes) == ["k1"]
    assert lb._open_misconception_keys("u1", ["n9"], closes) == ["k1"]  # off-play: the close's
    _resolve_k1(store)
    assert lb._open_misconception_keys("u1", ["n1"], closes) == []
    assert lb._open_misconception_keys("u1", ["n9"], closes) == []


def test_a_resolved_key_leaves_the_session_close(store):

    store.rows = [_row()]
    evidence = [{"node_id": "n1"}]
    assert services.loop.closing._close_misconception_keys("u1", evidence) == ["k1"]
    _resolve_k1(store)
    assert services.loop.closing._close_misconception_keys("u1", evidence) == []


# ── 6. the routes resolve after their claimed save ─────────────────────────


@pytest.fixture
def real_check(gate_on, seams, grader, store):
    """The check route with the REAL grade_answer (the grader stubbed) over the
    fake misconception store; qh-1 is posed at rung 0 (no hint yet)."""
    from agents.tools.check import grade_answer

    seams.store["doc"] = _state(rung=0)
    grader["result"] = _grade_result(correct=True)
    with (
        patch_loop("grade_answer", grade_answer),
        patch_loop("record") as rec,
    ):
        seams.record = rec
        yield seams


def _check(seams, **body):
    agent_p, usage_p, _ = _feedback_agent()
    with agent_p, usage_p:
        r = client.post("/api/learn/loop/check/answer", json=_answer(**body))
    assert r.status_code == 200, r.text
    return r.json()


def test_the_check_route_closes_the_key_after_a_correct_unassisted_isomorph(real_check, store):
    store.rows = [_row(node="node-1", key=KEY, item="item-0")]
    _check(real_check, answer="n == 0 returns 1", confidence="fairly_sure")
    assert store.rows[0]["resolved_at"] is not None
    [(event, kw)] = store.events
    assert event == "learn.misconception_resolved"
    assert kw["payload"]["surface"] == "check" and kw["payload"]["check_item_id"] == ITEM.id
    real_check.flush.assert_called_once()  # after the one flush …
    graded = real_check.store["doc"]["steps"]["qh-1"]
    assert graded["graded_at"] is not None  # … and the claimed save that recorded it
    (update,) = store.updates
    assert update["filters"]["node_id"] == "eq.node-1"


def test_the_check_route_closes_nothing_after_a_hint(real_check, store):
    real_check.store["doc"] = _state(rung=1)  # H1 used: assisted
    store.rows = [_row(node="node-1", key=KEY, item="item-0")]
    _check(real_check, answer="n == 0 returns 1")
    assert store.rows[0]["resolved_at"] is None and store.updates == []


def test_the_check_route_closes_nothing_when_the_reason_matched_the_key(real_check, grader, store):
    """A right answer whose reason the grader matched to the key: it is held."""
    grader["result"] = _grade_result(correct=True, matched=KEY)
    store.rows = [_row(node="node-1", key=KEY, item="item-0")]
    _check(real_check, answer="n == 0 returns 1")
    assert store.rows[0]["resolved_at"] is None


def test_the_check_route_closes_nothing_when_its_flush_fails(real_check, store):
    from learning.evidence import PlanningPersistenceUnavailable

    store.rows = [_row(node="node-1", key=KEY, item="item-0")]
    real_check.flush.side_effect = PlanningPersistenceUnavailable("down")
    agent_p, usage_p, _ = _feedback_agent()
    with agent_p, usage_p:
        r = client.post("/api/learn/loop/check/answer", json=_answer(answer="n == 0 returns 1"))
    assert r.status_code == 503
    assert store.rows[0]["resolved_at"] is None and store.updates == []


def test_the_check_route_stores_the_label_with_the_evidence_it_flushes(real_check):
    """The label rides the sealed checkpoint's evidence into the ONE flush
    (the single writer's input) and the attempt log the §3.3 rule reads."""
    _check(real_check, answer="n == 0 returns 1", confidence="sure")
    (deps, course), _ = real_check.flush.call_args
    [ev] = deps.pending_evidence  # what flush_pending hands apply_graph_update
    assert course == "c1" and ev["student_confidence"] == SURE and ev["confidence"] == 0.95
    assert real_check.store["doc"]["attempts"][-1]["confidence"] == SURE


@pytest.fixture
def real_probe(probe, grader, store):
    """The probe route with the REAL grade_answer over the fake store."""
    from agents.tools.check import grade_answer
    from tests.test_learning_probe_misconceptions import _probe_items

    probe.full = _probe_items()
    probe.grade.side_effect = grade_answer
    grader["result"] = _grade_result(correct=True)
    _planner._probing(probe, current=None)
    with patch_loop("record"):
        yield probe


def _probe_answer(probe, k: int, **extra):
    from tests.test_learning_probe_misconceptions import _pose

    _pose(probe, k)
    r = client.post(
        f"{_planner.LOOP}/probe/answer",
        json={"session_id": "s1", "user_id": _planner.UID, "question_hash": f"h-A-{k}",
              "answer": "the next free slot in the same table", **extra},
    )
    assert r.status_code == 200, r.text
    return r.json()


def test_a_correct_probe_answer_closes_the_key_and_its_response_is_unchanged(real_probe, store):
    """The probe stays a diagnostic (A120 (e)): the same answer, with and
    without an open misconception to close, gets the same response."""
    from tests.test_learning_probe_misconceptions import KEY as PROBE_KEY

    store.rows = [_row(node="A", key=PROBE_KEY, item="A-i1")]
    closing = _probe_answer(real_probe, 2, confidence="sure")
    assert store.rows[0]["resolved_at"] is not None
    assert [kw["payload"]["surface"] for _, kw in store.events] == ["probe"]
    assert real_probe.store["doc"].get("confront") is None  # the probe never confronts
    _planner._probing(real_probe, current=None)  # the same probe, before that answer
    store.rows = []
    plain = _probe_answer(real_probe, 2, confidence="sure")
    assert closing == plain


def test_a_probe_answer_carries_the_label_into_the_attempt_log_and_the_evidence(real_probe):
    _probe_answer(real_probe, 2, confidence="guessing")
    [attempt] = real_probe.store["doc"]["attempts"]
    assert attempt["confidence"] == GUESSING
    [[ev]] = real_probe.commits
    assert ev["student_confidence"] == GUESSING and ev["confidence"] == 0.95


# ── 7. the admin's metacognitive calibration (pure) ────────────────────────


def _ev(correct, stated, channel="free_response"):
    return {"channel": channel, "correct": correct, "student_confidence": stated}


def test_confidence_calibration_per_level_and_channel():
    from learning.calibration import confidence_calibration

    rows = [
        _ev(True, SURE), _ev(False, SURE), _ev(True, SURE),  # sure: 2 of 3
        _ev(False, GUESSING),  # guessing: 0 of 1
        _ev(True, FAIRLY_SURE, "mc_reasoned"),
        _ev(True, None),  # none stated: not a calibration row
        {"channel": "free_response", "correct": None, "student_confidence": SURE},  # no outcome
    ]
    out = confidence_calibration(rows)
    every = out["all"]
    assert every["n"] == 5
    assert every["observed_rate"] == pytest.approx(3 / 5)
    stated = [SURE, SURE, SURE, GUESSING, FAIRLY_SURE]
    assert every["mean_stated"] == pytest.approx(sum(stated) / 5)
    assert every["overconfidence"] == pytest.approx(sum(stated) / 5 - 3 / 5)
    outcomes = [1, 0, 1, 0, 1]
    assert every["brier"] == pytest.approx(
        sum((s - o) ** 2 for s, o in zip(stated, outcomes)) / 5
    )
    assert [c["channel"] for c in out["channels"]] == ["free_response", "mc_reasoned"]
    free = out["channels"][0]
    levels = {lv["level"]: lv for lv in free["levels"]}
    assert list(levels) == list(STUDENT_CONFIDENCE_LEVELS)  # scale order, every level
    assert (levels["sure"]["n"], levels["sure"]["correct"]) == (3, 2)
    assert levels["sure"]["observed"] == pytest.approx(2 / 3) and levels["sure"]["stated"] == SURE
    assert (levels["guessing"]["n"], levels["guessing"]["observed"]) == (1, 0.0)
    assert levels["fairly_sure"]["n"] == 0 and levels["fairly_sure"]["observed"] is None


def test_confidence_calibration_is_empty_not_zero():
    from learning.calibration import confidence_calibration

    out = confidence_calibration([_ev(True, None)])
    assert out["channels"] == []
    every = out["all"]
    assert every["n"] == 0
    assert all(every[k] is None for k in ("mean_stated", "observed_rate", "overconfidence", "brier"))
    assert [lv["n"] for lv in every["levels"]] == [0, 0, 0]


def test_a_value_the_mapping_no_longer_names_is_kept_apart():
    from learning.calibration import confidence_calibration

    out = confidence_calibration([_ev(True, 0.6), _ev(False, SURE)])
    levels = out["all"]["levels"]
    assert [lv["level"] for lv in levels] == [*STUDENT_CONFIDENCE_LEVELS, None]
    assert levels[-1]["stated"] == 0.6 and levels[-1]["n"] == 1


def test_the_grader_confidence_never_enters_the_students_calibration():
    from learning.calibration import confidence_calibration

    out = confidence_calibration([{"channel": "free_response", "correct": True, "confidence": 0.9}])
    assert out["all"]["n"] == 0
