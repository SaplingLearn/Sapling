"""Spec §13 A117: the session wrap-up reports honest baselines.

The live walkthrough that found it: a new student answered three check-in
(probe) questions, was taught Collision Resolution, missed its check and then
taught it back correctly. The journal read Collision Resolution 0.35 → 0.197 →
0.319 and the probed concepts 0.35 → 0.198 / 0.257 / 0.162 — and the close said
every concept "moved down from 0.35", counted "5 graded checks of which 1 was
correct" and showed ↓ "worth another look" on every concept. 0.35 is the BKT
prior, not a measurement of the student; the check-in answers came before any
teaching; and the one real learning signal (0.20 → 0.32 after teaching) was
hidden.

Pinned here: a concept first measured this session starts at that measurement
(never the prior), a teach-phase rise reads as a rise, check-in answers are
counted apart from teaching checks (by the A112 probe-identification rule), and
a concept with evidence before the session still reports from its pre-session
estimate — in the draft the close agent reads, the deterministic close, the
stored record the wrap-up renders and the learner brief.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from learning.evidence import Evidence, planning_observation
from learning.params import BKT_L0, RUNG_ASSISTED_MIN
from learning.session_close import (
    build_close,
    fallback_close,
    is_probe_row,
    move,
    session_probe_hashes,
)

SID = "s1"
NAMES = {
    "n-oa": "Open Addressing",
    "n-lp": "Linear Probing",
    "n-td": "Tombstone Deletion",
    "n-cr": "Collision Resolution",
    "n-hf": "Hash Functions",
}


def _row(
    node,
    qh,
    before,
    after,
    *,
    correct,
    idk=False,
    channel="free_response",
    session=SID,
    previously_seen=False,
    synthetic_idk=False,
    max_rung=0,
    item=None,
):
    """A journal row as services/graph_service.py writes it, with the REAL planning
    envelope (learning.evidence.planning_observation) — the probe route and the
    in-session checks both tag theirs."""
    item = item or f"item-{qh}"
    ev = Evidence(
        node_id=node,
        channel=channel,
        correct=correct,
        idk=idk,
        max_rung=max_rung,
        session_id=session,
        check_item_id=item,
        question_hash=qh,
        planning_provenance={
            "check_item_id": item,
            "difficulty": 2,
            "synthetic_idk": synthetic_idk,
            "previously_seen": previously_seen,
        },
    )
    return {
        "node_id": node,
        "p_before": before,
        "p_after": after,
        "session_id": ev.session_id,
        "question_hash": qh,
        "check_item_id": item,
        "channel": ev.channel,
        "correct": ev.correct,
        "assisted": ev.assisted,
        "max_rung": ev.max_rung,
        "reason": f"evidence:{ev.channel}:idk" if ev.idk else f"evidence:{ev.channel}",
        "planning_observation": planning_observation(ev),
    }


# The walkthrough, in apply order: three check-in answers (an "I don't know" on
# Tombstone Deletion), then teaching on Collision Resolution — a missed check,
# then a correct teachback (weight 0.5).
PROBE = [
    _row("n-oa", "qh-oa", 0.35, 0.198, correct=False),
    _row("n-lp", "qh-lp", 0.35, 0.257, correct=False),
    _row("n-td", "qh-td", 0.35, 0.162, correct=False, idk=True),
]
TEACH = [
    _row("n-cr", "qh-cr-check", 0.35, 0.197, correct=False),
    _row("n-cr", "qh-cr-teach", 0.197, 0.319, correct=True, channel="teachback_llm"),
]
WALKTHROUGH = PROBE + TEACH
LOOP_STATE = {
    "phase": "teach",
    "probe": {
        "history": [{"node_id": r["node_id"], "question_hash": r["question_hash"]} for r in PROBE]
    },
}
PROBED = session_probe_hashes(LOOP_STATE)


def _walkthrough(**kw):
    return build_close(
        [], WALKTHROUGH, [], measured_before=(), probe_hashes=PROBED, concept_names=NAMES, **kw
    )


# ── first measurements never show the prior ──────────────────────────────────


def test_first_measured_concepts_never_report_the_prior_as_a_baseline():
    """No evidence before the session: each concept starts at the estimate right
    after its first evidence here (the check-in result, for a probed one)."""
    by_id = {c.node_id: c for c in _walkthrough().concepts}
    assert {n: (c.p_before, c.p_after, c.baseline) for n, c in by_id.items()} == {
        "n-oa": (0.198, 0.198, "check_in"),
        "n-lp": (0.257, 0.257, "check_in"),
        "n-td": (0.162, 0.162, "check_in"),
        "n-cr": (0.197, 0.319, "teaching"),
    }
    assert all(c.first_measured for c in by_id.values())
    assert not any(c.p_before == BKT_L0 for c in by_id.values())
    assert [move(c) for c in by_id.values()] == ["unchanged", "unchanged", "unchanged", "up"]


def test_the_agent_record_and_the_deterministic_close_never_state_the_prior():
    from agents.session_close import render_draft

    draft = _walkthrough()
    text = render_draft(draft, nonce="a1b2c3d4e5f6a1b2c3d4e5f6")
    assert f"{BKT_L0:.2f}" not in text and "(down)" not in text
    # the three check-in concepts are starting points, listed apart from the changes
    changes, starts = text.split("FIRST MEASURED THIS SESSION")
    for name, p in (
        ("Open Addressing", "0.20"),
        ("Linear Probing", "0.26"),
        ("Tombstone Deletion", "0.16"),
    ):
        assert f"{name}: p {p}, measured at the check-in, before any teaching" in starts
        assert name not in changes.split("CONCEPT CHANGES:")[1]
    summary = fallback_close(draft).summary
    assert f"{BKT_L0:.2f}" not in summary and "→ 0.20" not in summary
    assert "Open Addressing: first measured at the check-in, p 0.20" in summary
    assert "Tombstone Deletion: first measured at the check-in, p 0.16" in summary
    unnamed = fallback_close(draft, detail="unnamed").summary
    assert unnamed.startswith("a checked concept: first measured at the check-in, p 0.20")


# ── a teach-phase rise is a rise ─────────────────────────────────────────────


def test_a_teach_phase_rise_shows_as_a_rise():
    """Collision Resolution: first measured by the missed check (0.197), then the
    correct teachback (0.319) — up, from its first measurement; the old close
    reported it "down from 0.35"."""
    from agents.session_close import render_draft

    draft = _walkthrough()
    [cr] = [c for c in draft.concepts if c.node_id == "n-cr"]
    assert move(cr) == "up"
    text = render_draft(draft, nonce="a1b2c3d4e5f6a1b2c3d4e5f6")
    assert (
        "Collision Resolution: p 0.20 -> 0.32 (up), from its first measurement this session "
        "(in the teaching phase)" in text
    )
    assert (
        "Collision Resolution: first measured this session, p 0.20 → 0.32"
        in fallback_close(draft).summary
    )


def test_a_probed_concept_taught_after_the_check_in_rises_from_the_check_in_result():
    rows = [
        _row("n-oa", "qh-oa", 0.35, 0.198, correct=False),
        _row("n-oa", "qh-oa-check", 0.198, 0.41, correct=True),
    ]
    [c] = build_close([], rows, [], measured_before=(), probe_hashes={"qh-oa"}).concepts
    assert (c.p_before, c.p_after, c.baseline, move(c)) == (0.198, 0.41, "check_in", "up")


def test_another_check_in_answer_never_reads_as_a_move_of_a_taught_concept():
    """Prerequisite propagation is never journaled: Open Addressing's prerequisite
    missed at the check-in pulled it from 0.30 (its own check-in answer) to 0.22
    before teaching began. Its correct check after teaching (0.22 → 0.27) is a rise
    — from where teaching on it began, the check-in result — never "down from 0.30"."""
    from agents.session_close import render_draft

    rows = [
        _row("n-oa", "qh-oa", 0.35, 0.30, correct=True),
        _row("n-hf", "qh-hf", 0.35, 0.15, correct=False),  # check-in miss on the prerequisite
        _row("n-oa", "qh-oa-check", 0.22, 0.27, correct=True),  # teaching
    ]
    draft = build_close(
        [], rows, [], measured_before=(), probe_hashes={"qh-oa", "qh-hf"}, concept_names=NAMES
    )
    oa = next(c for c in draft.concepts if c.node_id == "n-oa")
    assert (oa.p_before, oa.p_after, oa.baseline, move(oa)) == (0.22, 0.27, "check_in", "up")
    assert (
        "Open Addressing: p 0.22 -> 0.27 (up), from its check-in result (first measured at the "
        "check-in, before any teaching)" in render_draft(draft, nonce="a1b2c3d4e5f6a1b2c3d4e5f6")
    )
    # the deterministic close states the change since the check-in, not a measured 0.22
    assert "Open Addressing: since the check-in, p 0.22 → 0.27" in fallback_close(draft).summary


def test_several_check_in_answers_on_one_concept_are_one_starting_point():
    """The adaptive check-in can ask a concept more than once (an easy item right,
    a harder one missed): every answer came before any teaching, so the start is
    the check-in RESULT — the estimate after the last of them — and nothing in
    the check-in reads as a move; teaching after it moves from there."""
    check_in = [
        _row("n-oa", "qh-oa-1", 0.35, 0.52, correct=True),
        _row("n-oa", "qh-oa-2", 0.52, 0.31, correct=False),
    ]
    probed = {"qh-oa-1", "qh-oa-2"}
    [only] = build_close([], check_in, [], measured_before=(), probe_hashes=probed).concepts
    assert (only.p_before, only.p_after, only.baseline, move(only)) == (
        0.31,
        0.31,
        "check_in",
        "unchanged",
    )
    taught = [*check_in, _row("n-oa", "qh-oa-check", 0.31, 0.44, correct=True)]
    [c] = build_close([], taught, [], measured_before=(), probe_hashes=probed).concepts
    assert (c.p_before, c.p_after, move(c)) == (0.31, 0.44, "up")
    draft = build_close([], check_in, [], measured_before=(), probe_hashes=probed)
    assert (draft.probe_answers, draft.probe_correct, draft.teach_checks) == (2, 1, 0)


# ── check-in answers are counted apart ───────────────────────────────────────


def test_check_in_answers_and_teaching_checks_are_counted_apart():
    from agents.session_close import render_draft

    draft = _walkthrough()
    assert (draft.probe_answers, draft.probe_correct) == (3, 0)
    assert (draft.teach_checks, draft.teach_correct) == (2, 1)
    text = render_draft(draft, nonce="a1b2c3d4e5f6a1b2c3d4e5f6")
    assert (
        "SESSION FACTS: At the check-in, before any teaching, you answered 3 questions: "
        "0 correct, 3 not yet. In the teaching phase you answered 2 graded checks: "
        "1 correct, 1 not yet." in text
    )
    assert "5 graded" not in text and "You answered 5" not in text


@pytest.mark.parametrize(
    "rows,facts",
    [
        (
            PROBE[:1],
            "At the check-in, before any teaching, you answered 1 question: 0 correct, "
            "1 not yet. No check was graded in the teaching phase.",
        ),
        (TEACH, "You answered 2 graded checks: 1 correct, 1 not yet."),
        ([], "No check was graded this session."),
    ],
    ids=["check-in-only", "teaching-only", "nothing"],
)
def test_the_facts_name_only_the_phases_that_were_graded(rows, facts):
    from agents.session_close import _facts

    assert _facts(build_close([], rows, [], measured_before=(), probe_hashes=PROBED)) == facts


def test_without_the_session_probe_history_every_answer_is_a_teaching_check():
    """The probe history is what says "check-in" (A112's rule); a session with no
    probe (quiz-ask, a resumed teach session) counts every answer as teaching."""
    draft = build_close([], WALKTHROUGH, [], measured_before=())
    assert (draft.probe_answers, draft.teach_checks, draft.teach_correct) == (0, 5, 1)
    assert {c.baseline for c in draft.concepts} == {"teaching"}


# ── evidence before the session: the pre-session estimate ───────────────────


def test_a_concept_with_evidence_before_the_session_reports_from_its_pre_session_estimate():
    """Hash Functions had evidence in an earlier session: its change runs from the
    estimate it had when this session started (the first row's p_before) — a
    check-in miss then a teaching rise nets to the honest down."""
    from agents.session_close import render_draft

    rows = [
        _row("n-hf", "qh-hf", 0.55, 0.40, correct=False),  # check-in
        _row("n-hf", "qh-hf-check", 0.40, 0.50, correct=True),  # teaching
        *TEACH,
    ]
    draft = build_close(
        [], rows, [], measured_before={"n-hf"}, probe_hashes={"qh-hf"}, concept_names=NAMES
    )
    by_id = {c.node_id: c for c in draft.concepts}
    assert (by_id["n-hf"].p_before, by_id["n-hf"].p_after, by_id["n-hf"].baseline) == (
        0.55,
        0.50,
        "pre_session",
    )
    assert move(by_id["n-hf"]) == "down"
    assert (by_id["n-cr"].p_before, by_id["n-cr"].baseline) == (
        0.197,
        "teaching",
    )  # still first-measured
    text = render_draft(draft, nonce="a1b2c3d4e5f6a1b2c3d4e5f6")
    assert "Hash Functions: p 0.55 -> 0.50 (down), from its estimate before this session" in text
    assert fallback_close(draft).summary.startswith("Hash Functions: p 0.55 → 0.50; ")


# ── the probe-identification rule (A112's) ───────────────────────────────────


@pytest.mark.parametrize(
    "row",
    [
        PROBE[0],
        _row("n-oa", "qh-oa", 0.35, 0.2, correct=False, previously_seen=True),
        _row("n-oa", "qh-oa", 0.35, 0.2, correct=False, idk=True, synthetic_idk=True),
        _row("n-oa", "qh-oa", 0.35, 0.2, correct=True, max_rung=RUNG_ASSISTED_MIN),
    ],
    ids=["independent", "seen-item", "refusal-graded-idk", "helped"],
)
def test_a_probe_row_is_a_check_in_answer_whether_or_not_it_was_independent(row):
    """Independence is the A112 pretest's further condition, not identification:
    a check-in answer on a seen item is still a check-in answer."""
    assert is_probe_row(row, {"qh-oa"}) is True


def test_a_row_is_a_check_in_answer_only_by_the_probe_history_and_a_bound_envelope():
    probed = {"qh-oa"}
    check = _row("n-oa", "qh-oa-check", 0.2, 0.3, correct=True)  # tagged too, not in the history
    sessionless = _row("n-oa", "qh-oa", 0.35, 0.2, correct=False, session=None)
    legacy = {**PROBE[0], "planning_observation": None}
    flipped = {
        **PROBE[0],
        "planning_observation": {**PROBE[0]["planning_observation"], "correct": True},
    }
    other_item = {
        **PROBE[0],
        "planning_observation": {**PROBE[0]["planning_observation"], "question_hash": "qh-x"},
    }
    idk_lie = {**PROBE[0], "reason": "evidence:free_response:idk"}
    for row in (check, sessionless, legacy, flipped, other_item, idk_lie, None):
        assert is_probe_row(row, probed) is False
    assert is_probe_row(PROBE[0], set()) is False


@pytest.mark.parametrize(
    "loop_state,expected",
    [
        (LOOP_STATE, {"qh-oa", "qh-lp", "qh-td"}),
        (
            {
                "probe": {
                    "history": [
                        {"question_hash": "q1"},
                        {"node_id": "n"},
                        "junk",
                        {"question_hash": 7},
                    ]
                }
            },
            {"q1"},
        ),
        ({"probe": {"history": {"question_hash": "q1"}}}, set()),
        ({"probe": None}, set()),
        ({}, set()),
        (None, set()),
    ],
    ids=["walkthrough", "malformed-entries", "not-a-list", "no-probe", "empty", "none"],
)
def test_session_probe_hashes_reads_the_recorded_probe_history(loop_state, expected):
    assert session_probe_hashes(loop_state) == frozenset(expected)


# ── the route: which nodes had evidence before the session ──────────────────


class _Journal:
    """`node_mastery_events` reads over an in-memory journal (list order = the
    journal's order), honouring the filters `_session_record` and
    `_measured_before` send; every call is recorded."""

    def __init__(self, rows):
        self.rows, self.calls = rows, []

    def __call__(self, name):
        journal = self
        assert name == "node_mastery_events", name

        class _T:
            def select(self, cols, filters=None, order=None, limit=None, **kw):
                filters = dict(filters or {})
                journal.calls.append((cols, filters, order, limit))
                rows = [r for r in journal.rows if r.get("event_type", "evidence") == "evidence"]
                for key in ("session_id", "node_id"):
                    if key in filters:
                        rows = [r for r in rows if f"eq.{r.get(key)}" == filters[key]]
                if "id" in filters:  # A123's void filter: not.in.("id",…)
                    assert filters["id"].startswith("not.in.(") and filters["id"].endswith(")")
                    out = {v.strip('"') for v in filters["id"][len("not.in.(") : -1].split(",")}
                    rows = [r for r in rows if r.get("id") not in out]
                return [dict(r) for r in rows][: limit or None]

        return _T()


def test_measured_before_is_the_nodes_whose_first_evidence_is_not_this_sessions(monkeypatch):
    import routes.learn_loop as loop

    journal = _Journal(
        [
            {"node_id": "n-hf", "session_id": "s0"},  # an earlier session
            {"node_id": "n-quiz", "session_id": None},  # a quiz / post-test answer (sessionless)
            {"node_id": "n-later", "session_id": SID},  # this session first; another after it
            {"node_id": "n-later", "session_id": "s9"},
            *[{**r, "session_id": SID} for r in WALKTHROUGH],
            {"node_id": "n-hf", "session_id": SID},
            {"node_id": "n-quiz", "session_id": SID},
        ]
    )
    monkeypatch.setattr(loop, "table", journal)
    evidence = [{"node_id": n} for n in ("n-hf", "n-quiz", "n-later", "n-oa", "n-cr", "n-cr")]
    assert loop._measured_before("u1", SID, evidence) == {"n-hf", "n-quiz"}
    # one owner-scoped, journal-ordered limit-1 read per distinct node
    assert [c[1]["node_id"] for c in journal.calls] == [
        f"eq.{n}" for n in ("n-hf", "n-quiz", "n-later", "n-oa", "n-cr")
    ]
    for cols, filters, order, limit in journal.calls:
        assert filters["graph_nodes.user_id"] == "eq.u1" and filters["event_type"] == "eq.evidence"
        assert "graph_nodes!inner(user_id)" in cols
        assert order == "created_at.asc,evidence_seq.asc" and limit == 1
    assert loop._measured_before("u1", SID, []) == set()


def test_a_void_earlier_row_does_not_measure_a_node_before_the_session(monkeypatch):
    """Spec §13 A123: a row graded against an item staff retired is no
    measurement, so the node's first VALID row decides. n-void's only earlier
    row is void: it was first measured in this session and starts at that
    measurement. n-old's earlier row stands. The student's void ids are read
    once, by node, and only n-void's read leaves its void id out."""
    import routes.learn_loop as loop

    journal = _Journal(
        [
            {"id": "e-void", "node_id": "n-void", "session_id": "s0"},
            {"id": "e-old", "node_id": "n-old", "session_id": "s0"},
            {"id": "e-void-here", "node_id": "n-void", "session_id": SID},
            {"id": "e-old-here", "node_id": "n-old", "session_id": SID},
        ]
    )
    reads = []

    def voided_by_node(user_id):
        reads.append(user_id)
        return {"n-void": {"e-void"}}

    monkeypatch.setattr(loop, "table", journal)
    monkeypatch.setattr(loop, "voided_by_node", voided_by_node)
    evidence = [{"node_id": "n-void"}, {"node_id": "n-old"}]
    assert loop._measured_before("u1", SID, evidence) == {"n-old"}
    assert reads == ["u1"]
    assert [c[1].get("id") for c in journal.calls] == ['not.in.("e-void")', None]
    monkeypatch.setattr(loop, "voided_by_node", lambda user_id: {})
    assert loop._measured_before("u1", SID, evidence) == {"n-old", "n-void"}  # nothing void


def test_the_session_evidence_read_carries_what_the_probe_rule_binds(monkeypatch):
    import routes.learn_loop as loop
    from learning.probe import PLANNING_BOUND_FIELDS

    journal = _Journal([])
    monkeypatch.setattr(
        loop,
        "table",
        lambda name: (
            journal(name)
            if name == "node_mastery_events"
            else SimpleNamespace(select=lambda *a, **k: [])
        ),
    )
    loop._session_record(SID)
    [(cols, filters, _, _)] = journal.calls
    assert filters == {"session_id": f"eq.{SID}", "event_type": "eq.evidence"}
    needed = {
        "node_id",
        "p_before",
        "p_after",
        "correct",
        "session_id",
        "reason",
        "planning_observation",
        *PLANNING_BOUND_FIELDS,
    }
    assert needed <= set(cols.split(","))


def _wire_walkthrough(monkeypatch, *, rows=WALKTHROUGH, earlier=(), loop_state=LOOP_STATE):
    """The close route over the walkthrough session: the shared close fakes, with
    the journal answering the session read and the per-node first-evidence reads
    (`earlier`: rows journaled before this session)."""
    import learning.session_close as sc
    import routes.learn_loop as loop
    from tests.test_learning_close_brief import _wire_close

    names = [{"id": n, "concept_name": v} for n, v in NAMES.items()]
    tables, events, store = _wire_close(
        monkeypatch, evidence=rows, loop_state=loop_state, names=names
    )
    journal = _Journal([*earlier, *rows])

    def routed(name):
        return journal(name) if name == "node_mastery_events" else tables(name)

    monkeypatch.setattr(loop, "table", routed)
    monkeypatch.setattr(sc, "table", routed)
    return tables, events


def test_the_close_route_gives_the_agent_honest_baselines_and_split_counts(monkeypatch):
    import routes.learn_loop as loop
    from tests.test_learning_close_brief import UID, _close_out, _fake_run, client

    _wire_walkthrough(monkeypatch)
    runs: list = []
    monkeypatch.setattr(loop, "run_session_close", _fake_run(_close_out(), runs))
    r = client.post("/api/learn/loop/close", json={"session_id": SID, "user_id": UID})
    assert r.status_code == 200, r.text
    [(draft, _)] = runs
    assert (draft.probe_answers, draft.probe_correct, draft.teach_checks, draft.teach_correct) == (
        3,
        0,
        2,
        1,
    )
    stored = {c["node_id"]: c for c in r.json()["close"]["concepts"]}
    assert stored == {
        "n-oa": {"node_id": "n-oa", "p_before": 0.198, "p_after": 0.198, "baseline": "check_in"},
        "n-lp": {"node_id": "n-lp", "p_before": 0.257, "p_after": 0.257, "baseline": "check_in"},
        "n-td": {"node_id": "n-td", "p_before": 0.162, "p_after": 0.162, "baseline": "check_in"},
        "n-cr": {"node_id": "n-cr", "p_before": 0.197, "p_after": 0.319, "baseline": "teaching"},
    }


def test_probe_answers_in_the_attempt_log_are_never_counted_twice(monkeypatch):
    """Spec §13 A120 × A117: since A120 a check-in answer also joins the
    session attempt log (`loop_state.attempts`, the §3.3 rule's input), beside
    the in-session checks. The close counts answers off the evidence journal
    alone, split by the one probe rule (`learning/probe.py::is_probe_row`), so a
    log holding every check-in and teaching answer leaves the split counts
    exactly as the journal says: one count per graded answer."""
    import routes.learn_loop as loop
    from tests.test_learning_close_brief import UID, _close_out, _fake_run, client

    attempts = [
        {
            "question_hash": r["question_hash"],
            "node_id": r["node_id"],
            "correct": r["correct"],
            "difficulty": 2,
            "idk": r["reason"].endswith(":idk"),
            "released": not r["correct"],
        }
        for r in WALKTHROUGH
    ]
    _wire_walkthrough(monkeypatch, loop_state={**LOOP_STATE, "attempts": attempts})
    runs: list = []
    monkeypatch.setattr(loop, "run_session_close", _fake_run(_close_out(), runs))
    r = client.post("/api/learn/loop/close", json={"session_id": SID, "user_id": UID})
    assert r.status_code == 200, r.text
    [(draft, _)] = runs
    counts = (draft.probe_answers, draft.probe_correct, draft.teach_checks, draft.teach_correct)
    assert counts == (3, 0, 2, 1)  # the journal's 3 check-in and 2 teaching answers, once each


def test_the_deterministic_close_over_the_route_never_states_the_prior(monkeypatch):
    import routes.learn_loop as loop
    from tests.test_learning_close_brief import UID, _fake_run, client

    _wire_walkthrough(monkeypatch)
    monkeypatch.setattr(loop, "run_session_close", _fake_run(None))  # the agent unavailable
    r = client.post("/api/learn/loop/close", json={"session_id": SID, "user_id": UID})
    assert r.status_code == 200, r.text
    close = r.json()["close"]
    assert close["model_written"] is False
    assert close["summary"] == (
        "Open Addressing: first measured at the check-in, p 0.20; "
        "Linear Probing: first measured at the check-in, p 0.26; "
        "Tombstone Deletion: first measured at the check-in, p 0.16; "
        "Collision Resolution: first measured this session, p 0.20 → 0.32"
    )


def test_the_route_reports_a_concept_measured_in_an_earlier_session_from_its_estimate_then(
    monkeypatch,
):
    """Collision Resolution has a row from session s0: this session opened on its
    decayed estimate 0.42, so the change runs 0.42 → 0.32 (down) — the
    `_measured_before` read is what tells the two cases apart."""
    import routes.learn_loop as loop
    from tests.test_learning_close_brief import UID, _fake_run, client

    rows = [
        *PROBE,
        _row("n-cr", "qh-cr-check", 0.42, 0.24, correct=False),
        _row("n-cr", "qh-cr-teach", 0.24, 0.32, correct=True, channel="teachback_llm"),
    ]
    _wire_walkthrough(monkeypatch, rows=rows, earlier=[{"node_id": "n-cr", "session_id": "s0"}])
    monkeypatch.setattr(loop, "run_session_close", _fake_run(None))
    r = client.post("/api/learn/loop/close", json={"session_id": SID, "user_id": UID})
    assert r.status_code == 200, r.text
    close = r.json()["close"]
    assert close["summary"].endswith("; Collision Resolution: p 0.42 → 0.32")
    [cr] = [c for c in close["concepts"] if c["node_id"] == "n-cr"]
    assert cr == {"node_id": "n-cr", "p_before": 0.42, "p_after": 0.32, "baseline": "pre_session"}


# ── the learner brief and the close's budget band ───────────────────────────


def test_the_brief_renders_a_first_measurement_as_one(monkeypatch):
    from tests.test_learning_close_brief import _close_row, _wire_brief

    row = _close_row("S.", "If a, then b.")
    row["close_json"]["concepts"] = [
        {"node_id": "n-oa", "p_before": 0.198, "p_after": 0.198, "baseline": "check_in"},
        {"node_id": "n-cr", "p_before": 0.197, "p_after": 0.319, "baseline": "teaching"},
        {"node_id": "n-hf", "p_before": 0.55, "p_after": 0.5, "baseline": "pre_session"},
        {"node_id": "n-lp", "p_before": 0.35, "p_after": 0.6},  # a close stored before A117
        {"node_id": "n-td", "p_before": 0.35, "p_after": 0.2, "baseline": "bogus"},  # skipped
    ]
    lb, _ = _wire_brief(
        monkeypatch,
        closes=[row],
        states=[],
        nodes=[{"id": n, "concept_name": name} for n, name in NAMES.items()],
    )
    text = lb.build_brief("u", "c", [])
    assert "Open Addressing first measured at 0.20" in text
    assert "Collision Resolution first measured at 0.20, then 0.32 (up)" in text
    assert "Hash Functions 0.55 → 0.50 (down)" in text
    assert "Linear Probing 0.35 → 0.60 (up)" in text
    assert "Tombstone Deletion" not in text


def test_the_close_band_reads_the_first_measurement_not_the_prior(monkeypatch):
    """A new student whose check-in put a concept in the novice band gets the novice
    allowance (spec §3.5); under the prior (0.35, develop) the close never did."""
    import agents.session_close as sc

    bands: list = []
    monkeypatch.setattr(
        sc.ai_budget,
        "check",
        lambda user_id, kind, band=None, **k: bands.append(band) or SimpleNamespace(level="hard"),
    )
    asyncio.run(sc.run_session_close(_walkthrough(), user_id="u", request_id="r"))
    assert bands == ["novice"]
