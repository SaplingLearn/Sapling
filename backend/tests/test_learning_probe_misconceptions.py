"""Spec §13 A120 (2): probe answers feed the slip/misconception machinery.

A live probe answer ("linear probing stores the new key in a linked list
hanging off that bucket") matched its item's common wrong reason
`chains_on_collision`, yet no `misconceptions` row was written and neither the
plan nor the tutor learned of it: grade_answer's §3.3 hook was inert because
the probe loaded no loop state.

Step 1 (verified first): the matched key itself was never lost. In a default
real-mode deployment the misconception seam is `services/learning_decisions.py`
(not ADR 0027's `services/decisions.py`, whose default backend is `off`), its
`match_wrong_reason` serves `gemini` and answers from the grader's own result
(`prior`) with no model call. Pinned below so a rewiring through `decide()` or
an off backend fails.

Step 2: the probe now passes the session's loop state, so each graded probe
answer joins the session attempt log and the §3.3 rule runs over it: one
matched answer is `unknown` (never a record: wrong once is no misconception);
the same key on two isomorphs is a `misconception`, recorded after the flush
like the check route's (A75 (a)). The probe stays a diagnostic: it never sets
or clears the confrontation marker and its response is unchanged; the brief
built at plan approval and a later check on the concept (A75 (d)) carry it on.
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from agents.grader import GradeResult
from learning.checks import RubricItem, WrongReason
from tests import test_learning_probe_planner as _planner
from tests.test_learning_probe_planner import LOOP, UID, _ci, _probing, client

probe, _no_rate_limit = _planner.probe, _planner._no_rate_limit

KEY = "chains_on_collision"
KEY_TEXT = "Believes the colliding key is kept in a chain attached to the occupied slot"
LIVE_ANSWER = "linear probing stores the new key in a linked list hanging off that bucket"


# ── step 1: the grader's matched key in a default deployment ────────────────


@pytest.fixture
def default_deployment(monkeypatch):
    """A default real-mode deployment: SAPLING_MODEL_MODE unset (real), no
    DECISION_BACKEND_* override, JEV_ENABLED false. Every model run that
    could answer the decision instead of the grader fails the test."""
    from agents.learning_decision import learning_decision_agent
    from services import decisions as adr0027
    from services import learning_decisions

    monkeypatch.delenv("SAPLING_MODEL_MODE", raising=False)
    for name in learning_decisions.DECISION_NAMES:
        monkeypatch.delenv(f"DECISION_BACKEND_{name.upper()}", raising=False)
    monkeypatch.setattr(learning_decisions, "JEV_ENABLED", False)

    async def _no_model(*_a, **_k):
        raise AssertionError("no decision model may run: the grader already matched the key")

    monkeypatch.setattr(learning_decision_agent, "run", _no_model)
    monkeypatch.setattr(adr0027, "decide", _no_model)
    return learning_decisions


def _hash_item(qh: str, item_id: str | None = None, difficulty: int = 2):
    from tests.test_learning_check_tool import _item

    return _item(
        id=item_id or f"ci-{qh}",
        concept_key="hashing",
        difficulty=difficulty,
        prompt="What does linear probing do when the slot is taken?",
        common_wrong=[WrongReason(key=KEY, text=KEY_TEXT)],
        question_hash=qh,
    )


def _deps(**over):
    from agents.deps import SaplingDeps

    kw = dict(
        user_id=UID,
        course_id="c1",
        supabase=None,
        request_id="r",
        session_id="s1",
        feature="loop_probe",
        learning_loop=True,
    )
    kw.update(over)
    return SaplingDeps(**kw)


def _matched(**over) -> GradeResult:
    kw = dict(
        item_results={"r1": False, "r2": False},
        all_yes=False,
        confidence=0.9,
        matched_wrong_key=KEY,
        backend="gemini",
    )
    kw.update(over)
    return GradeResult(**kw)


def test_the_default_backend_returns_the_graders_key_with_no_model_call(default_deployment):
    """A120 step 1: `gemini` is served by default, and with the grader's result
    as `prior` it answers that result's key — no decision run, no `decide()`."""
    from agents.tools import check

    seam = default_deployment
    sel = seam.select_backend("match_wrong_reason")
    assert (sel.served, sel.requested, sel.fallback_reason) == ("gemini", "gemini", None)
    state = seam.WrongReasonState(question="q", answer=LIVE_ANSWER, wrong={KEY: KEY_TEXT})
    pick = asyncio.run(seam.match_wrong_reason(state, deps=_deps(), prior=_matched()))
    assert (pick.value, pick.backend, pick.latency_ms) == (KEY, "gemini", 0)
    key = asyncio.run(
        check.match_wrong_key(
            _hash_item("h1"), prior=_matched(), answer_text=LIVE_ANSWER, deps=_deps()
        )
    )
    assert key == KEY


def test_grade_answer_reaches_the_misconception_seam_not_adr_0027(default_deployment, monkeypatch):
    """The learning loop's key comes from services/learning_decisions.py. ADR
    0027's seam (services/decisions.py: `decide()`, default backend `off`, the
    observe-only router's) is not on the path — it has no match_wrong_reason,
    and grading never calls `decide()` (it would raise here)."""
    import agents.grader
    from agents.tools import check
    from services import decisions as adr0027

    assert check.decisions is default_deployment
    assert not hasattr(adr0027, "match_wrong_reason")

    async def _grade(item, *, format, student_answer, deps):
        return _matched()

    monkeypatch.setattr(agents.grader, "grade", _grade)
    out = asyncio.run(
        check.grade_answer(
            _hash_item("h1"),
            check.CheckAnswer(question_hash="h1", answer_text=LIVE_ANSWER),
            deps=_deps(),
            node_id="n1",
        )
    )
    assert out.correct is False and out.matched_wrong_key == KEY and out.wrong_key == KEY


@pytest.mark.parametrize(
    "env,jev,mode,served",
    [
        (None, False, None, "gemini"),  # the default
        ("gemini", False, None, "gemini"),
        ("jev", False, None, "gemini"),  # JEV_ENABLED false overrides every request
        ("shadow_jev", True, None, "gemini"),  # Gemini serves; Jev only shadows
        ("not-a-backend", False, None, "gemini"),  # an unknown value serves gemini
        (None, False, "function", "gemini"),  # the E2E lane: the prior's provenance
    ],
)
def test_the_prior_is_honoured_whatever_backend_serves_the_decision(
    default_deployment, monkeypatch, env, jev, mode, served
):
    """No selection the seam can make (short of a promoted, answering Jev,
    A98) drops the grader's key: the prior answers, with no model run."""
    seam = default_deployment
    if env is not None:
        monkeypatch.setenv("DECISION_BACKEND_MATCH_WRONG_REASON", env)
    if mode is not None:
        monkeypatch.setenv("SAPLING_MODEL_MODE", mode)
    monkeypatch.setattr(seam, "JEV_ENABLED", jev)
    monkeypatch.setattr(seam, "_shadow", lambda *a, **k: None)  # never awaited by the served path
    state = seam.WrongReasonState(question="q", answer=LIVE_ANSWER, wrong={KEY: KEY_TEXT})
    pick = asyncio.run(seam.match_wrong_reason(state, deps=_deps(), prior=_matched()))
    assert (pick.value, pick.backend) == (KEY, served)


def test_a_jev_backend_that_fails_falls_back_to_the_prior(default_deployment, monkeypatch):
    """A requested and enabled Jev that cannot answer (no client, timeout, …)
    falls back to the grader's key — never to "no key"."""
    seam = default_deployment
    monkeypatch.setenv("DECISION_BACKEND_MATCH_WRONG_REASON", "jev")
    monkeypatch.setattr(seam, "JEV_ENABLED", True)

    async def _unanswered(*_a, **_k):
        return None, "timeout"

    monkeypatch.setattr(seam, "_serve_jev", _unanswered)
    state = seam.WrongReasonState(question="q", answer=LIVE_ANSWER, wrong={KEY: KEY_TEXT})
    pick = asyncio.run(seam.match_wrong_reason(state, deps=_deps(), prior=_matched()))
    assert pick.value == KEY


# ── step 2: the rule over probe and check attempts (the hook) ───────────────


@pytest.fixture
def graded(monkeypatch):
    """grade_answer with its one model seam stubbed: every answer is wrong and
    the grader matched KEY (the decision seam runs for real, no model call)."""
    import agents.grader

    state = {"result": _matched()}

    async def _grade(item, *, format, student_answer, deps):
        return state["result"]

    monkeypatch.setattr(agents.grader, "grade", _grade)
    return state


def _grade(item, deps, *, confront: bool, text: str = LIVE_ANSWER):
    from agents.tools.check import CheckAnswer, grade_answer

    return asyncio.run(
        grade_answer(
            item,
            CheckAnswer(question_hash=item.question_hash, answer_text=text),
            deps=deps,
            node_id="n1",
            confront=confront,
        )
    )


def test_one_matched_probe_answer_is_unknown_and_records_nothing(graded):
    """Spec §3.3: wrong once → `unknown` (re-ask an isomorph), never a record —
    even with a matched key. The attempt (and its key) joins the log."""
    from learning.misconceptions import attempts_of, confront_of

    deps = _deps(loop_state={})
    out = _grade(_hash_item("h1"), deps, confront=False)
    assert out.verdict == "unknown" and out.wrong_key == KEY
    assert out.diagnosis == {
        "attempt": attempts_of(deps.loop_state)[-1],
        "confront": None,
        "cleared": None,
        "record": None,
    }
    [attempt] = attempts_of(deps.loop_state)
    assert attempt["wrong_key"] == KEY and attempt["correct"] is False
    assert confront_of(deps.loop_state) is None


def test_the_same_key_on_two_probe_isomorphs_is_recorded_but_never_confronted(graded):
    """Spec §3.3 "wrong on ≥ 2 isomorphs with the same wrong_key → misconception:
    record". The probe marks the row (the route writes it after the flush) and
    leaves the marker alone (A120: the probe stays a diagnostic)."""
    from learning.misconceptions import confront_of

    deps = _deps(loop_state={})
    first = _grade(_hash_item("h1"), deps, confront=False)
    second = _grade(_hash_item("h2"), deps, confront=False)
    assert (first.verdict, second.verdict) == ("unknown", "misconception")
    assert second.diagnosis["record"] == {
        "node_id": "n1",
        "wrong_key": KEY,
        "check_item_id": "ci-h2",
    }
    assert second.diagnosis["confront"] is None and second.diagnosis["cleared"] is None
    assert confront_of(deps.loop_state) is None
    assert [e["verdict"] for e in deps.pending_evidence] == ["unknown", "misconception"]


def test_a_probe_slip_records_nothing(graded):
    """Wrong then right on the isomorph → `slip`: no record (§3.3)."""
    deps = _deps(loop_state={})
    _grade(_hash_item("h1"), deps, confront=False)
    graded["result"] = _matched(
        item_results={"r1": True, "r2": True}, all_yes=True, matched_wrong_key=""
    )
    out = _grade(_hash_item("h2"), deps, confront=False)
    assert out.verdict == "slip" and out.diagnosis["record"] is None


def test_a_probe_answer_and_a_later_check_with_the_same_key_confront_in_teaching(graded):
    """The log is the session's: a probe answer with KEY, then the check phase's
    answer on an isomorph with KEY → misconception at the check, which records
    AND sets the marker (the check route's turn confronts, A75 (d))."""
    from learning.misconceptions import confront_of

    deps = _deps(loop_state={})
    _grade(_hash_item("h1"), deps, confront=False)  # the probe
    check = _grade(_hash_item("h2"), deps, confront=True)  # the check route
    marker = {"node_id": "n1", "wrong_key": KEY, "check_item_id": "ci-h2"}
    assert check.verdict == "misconception"
    assert check.diagnosis["record"] == marker and check.diagnosis["confront"] == marker
    assert confront_of(deps.loop_state) == marker


def test_the_probe_never_clears_a_pending_marker(graded):
    """`confront=False` neither sets nor clears: a correct probe answer on a
    marked concept leaves the marker to the teaching flow."""
    from learning.misconceptions import confront_of, set_confront

    marker = {"node_id": "n1", "wrong_key": KEY, "check_item_id": "ci-h0"}
    deps = _deps(loop_state={})
    set_confront(deps.loop_state, marker)
    graded["result"] = _matched(
        item_results={"r1": True, "r2": True}, all_yes=True, matched_wrong_key=""
    )
    out = _grade(_hash_item("h1"), deps, confront=False)
    assert out.diagnosis["cleared"] is None and confront_of(deps.loop_state) == marker


# ── step 2 through the probe route (the real grade_answer, the grader stubbed) ─


def _probe_items():
    """Concept A's items, each listing KEY as a common wrong reason; h-A-0 is
    A's post-test reserve, so A-i1..A-i3 are posed."""
    return [
        _ci(
            f"A-i{k}",
            "A",
            "free",
            2,
            f"h-A-{k}",
            rubric=[
                RubricItem(id="r1", text="next free slot"),
                RubricItem(id="r2", text="same table"),
            ],
            common_wrong=[WrongReason(key=KEY, text=KEY_TEXT)],
        )
        for k in range(4)
    ]


def _pose(probe, k: int) -> None:
    probe.store["doc"]["probe"]["current"] = {
        "check_item_id": f"A-i{k}",
        "question_hash": f"h-A-{k}",
        "node_id": "A",
        "difficulty": 2,
        "channel": "free_response",
    }


@pytest.fixture
def real_probe(probe, graded):
    """The probe route with the REAL grade_answer; the store write is captured."""
    from agents.tools.check import grade_answer

    probe.full = _probe_items()
    probe.grade.side_effect = grade_answer
    _probing(probe, current=None)
    with patch("routes.learn_loop.record") as rec:
        probe.record = rec
        yield probe


def _answer(probe, k: int, text: str = LIVE_ANSWER):
    _pose(probe, k)
    r = client.post(
        f"{LOOP}/probe/answer",
        json={"session_id": "s1", "user_id": UID, "question_hash": f"h-A-{k}", "answer": text},
    )
    assert r.status_code == 200, r.text
    return r.json()


def test_a_probe_answer_matching_a_common_wrong_key_reaches_the_rule(real_probe):
    """The live case: one probe answer whose reason the grader matched to KEY is
    in the session attempt log the §3.3 rule reads, with its key — and, wrong
    once, it is `unknown`: no row, no marker."""
    body = _answer(real_probe, 1)
    assert body["graded"] is True and body["correct"] is False
    doc = real_probe.store["doc"]
    [attempt] = doc["attempts"]
    assert attempt["question_hash"] == "h-A-1" and attempt["node_id"] == "A"
    assert attempt["wrong_key"] == KEY and attempt["correct"] is False
    assert attempt["released"] is True  # the probe showed the reference (A76)
    assert doc.get("confront") is None
    real_probe.record.assert_not_called()
    [[ev]] = real_probe.commits
    assert ev["wrong_key"] == KEY and ev["verdict"] == "unknown"


def test_the_same_key_on_a_second_probe_isomorph_writes_one_row_after_the_flush(real_probe):
    """§3.3's isomorph rule, recorded by the route after its one flush and the
    claimed save (A75 (a)); evidence_text = the text the grader saw."""
    _answer(real_probe, 1)
    flushed_before = len(real_probe.commits)
    _answer(real_probe, 2, "it keeps the key in a chain at the full slot")
    real_probe.record.assert_called_once_with(
        UID, "A", "A-i2", KEY, "it keeps the key in a chain at the full slot"
    )
    assert len(real_probe.commits) == flushed_before + 1
    doc = real_probe.store["doc"]
    assert [a["question_hash"] for a in doc["attempts"]] == ["h-A-1", "h-A-2"]
    assert doc.get("confront") is None  # the probe never confronts
    assert real_probe.commits[-1][0]["verdict"] == "misconception"


def test_a_probe_slip_writes_no_row(real_probe, graded):
    _answer(real_probe, 1)
    graded["result"] = _matched(
        item_results={"r1": True, "r2": True}, all_yes=True, matched_wrong_key=""
    )
    body = _answer(real_probe, 2, "the next free slot in the same table")
    assert body["correct"] is True
    real_probe.record.assert_not_called()
    assert [a["correct"] for a in real_probe.store["doc"]["attempts"]] == [False, True]


def test_the_probe_response_is_unchanged_by_a_matched_key(real_probe, graded):
    """The probe stays a diagnostic: a matched key changes no field of the
    response (the corrective reference is the same as without a key)."""
    with_key = _answer(real_probe, 1)
    graded["result"] = _matched(matched_wrong_key="")
    without_key = _answer(real_probe, 2, "something else entirely")
    assert set(with_key) == set(without_key)
    assert with_key["reference_answer"] == without_key["reference_answer"] == "SECRET-REFERENCE"
    assert {k: v for k, v in with_key.items() if k not in ("diagnosis", "p_known")} == {
        k: v for k, v in without_key.items() if k not in ("diagnosis", "p_known")
    }


def test_no_row_when_the_probe_flush_fails(real_probe):
    """A75 (a)'s order holds on the probe: the row is written after the flush,
    so a failed flush (the answer is retried) leaves nothing behind."""
    from learning.evidence import PlanningPersistenceUnavailable

    _answer(real_probe, 1)
    _pose(real_probe, 2)
    with patch(
        "routes.learn_loop.flush_pending", side_effect=PlanningPersistenceUnavailable("down")
    ):
        r = client.post(
            f"{LOOP}/probe/answer",
            json={
                "session_id": "s1",
                "user_id": UID,
                "question_hash": "h-A-2",
                "answer": LIVE_ANSWER,
            },
        )
    assert r.status_code == 503
    real_probe.record.assert_not_called()
    assert [a["question_hash"] for a in real_probe.store["doc"]["attempts"]] == ["h-A-1"]


# ── the probe checkpoint carries the diagnosis (grade recovery) ─────────────


def _probe_payload(diagnosis, answer=None):
    from tests.test_learning_grade_checkpoint import payload

    data = payload("probe")
    data["continuation"]["diagnosis"] = diagnosis
    if answer is not None:
        data["continuation"]["answer"] = answer
    return data


def _diagnosis(**over):
    record = {"node_id": "node", "wrong_key": "wrong_rule", "check_item_id": "item"}
    out = {
        "attempt": {
            "question_hash": "question-hash",
            "node_id": "node",
            "correct": False,
            "wrong_key": "wrong_rule",
            "confidence": None,
            "difficulty": 2,
            "idk": False,
            "isomorph_of": None,
            "released": True,
            "after_release": False,
        },
        "confront": None,
        "cleared": None,
        "record": record,
    }
    out.update(over)
    return out


_ANSWER = {
    "question_hash": "question-hash",
    "answer_text": "private probe answer",
    "selected_option": None,
    "reason": None,
    "idk": False,
}


def test_a_probe_checkpoint_round_trips_its_diagnosis_and_answer():
    from learning import grade_checkpoint as cp
    from tests.test_learning_grade_checkpoint import bindings

    data = _probe_payload(_diagnosis(), dict(_ANSWER))
    sealed = cp.seal(cp.GradeCheckpoint.model_validate(data))
    assert "private probe answer" not in sealed  # encrypted at rest
    recovered = cp.open_checkpoint(sealed, **bindings(data))
    assert recovered.continuation["diagnosis"] == _diagnosis()
    assert recovered.continuation["answer"] == _ANSWER


def test_a_probe_checkpoint_saved_before_a120_still_opens():
    from learning import grade_checkpoint as cp
    from tests.test_learning_grade_checkpoint import bindings, payload

    data = payload("probe")
    assert "diagnosis" not in data["continuation"] and "answer" not in data["continuation"]
    recovered = cp.open_checkpoint(
        cp.seal(cp.GradeCheckpoint.model_validate(data)), **bindings(data)
    )
    assert recovered.continuation["diagnosis"] is None and recovered.continuation["answer"] is None


@pytest.mark.parametrize(
    "diagnosis,answer",
    [
        # a probe diagnosis never touches the confrontation marker
        (
            _diagnosis(
                confront={"node_id": "node", "wrong_key": "wrong_rule", "check_item_id": "item"}
            ),
            None,
        ),
        (
            _diagnosis(
                cleared={"node_id": "node", "wrong_key": "wrong_rule", "check_item_id": "item"}
            ),
            None,
        ),
        # bound to the evidence like the check route's
        (
            _diagnosis(
                record={"node_id": "other", "wrong_key": "wrong_rule", "check_item_id": "item"}
            ),
            None,
        ),
        (
            _diagnosis(
                record={"node_id": "node", "wrong_key": "wrong_rule", "check_item_id": "other"}
            ),
            None,
        ),
        (
            _diagnosis(
                record={"node_id": "node", "wrong_key": "Not A Key", "check_item_id": "item"}
            ),
            None,
        ),
        (None, {**_ANSWER, "question_hash": "other-question"}),
        (None, {**_ANSWER, "idk": True}),
        (None, {**_ANSWER, "reference_answer": "forbidden"}),
    ],
)
def test_a_probe_checkpoint_refuses_a_diagnosis_or_answer_it_cannot_bind(diagnosis, answer):
    from pydantic import ValidationError

    from learning import grade_checkpoint as cp

    with pytest.raises(ValidationError):
        cp.GradeCheckpoint.model_validate(_probe_payload(diagnosis, answer))
