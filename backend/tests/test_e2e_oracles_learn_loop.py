"""PKG-13: the `learn_loop` oracle (spec §8 inv 1, §5, §6) — the pure judge, the
gatherer's wiring over a fake connection, and the CLI registration."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from e2e_oracles import gather
from e2e_oracles.learn_loop import ORACLE_P_TOLERANCE, learn_loop_findings


def _clean():
    return dict(
        evidence_pairs=[("u", "n1")],
        state_rows=[{"user_id": "u", "node_id": "n1", "p_known": 0.61}],
        leak_count=0,
        step_payloads=[{"p_known_before": 0.35, "p_known_after": 0.61}],
        node_scores=[{"id": "n1", "mastery_score": 0.61}],
    )


def test_clean_run_has_no_findings():
    assert learn_loop_findings(**_clean()) == []


def test_evidence_without_learner_state_is_a_single_writer_finding():
    kw = _clean()
    kw["state_rows"] = []
    f = learn_loop_findings(**kw)
    assert len(f) == 1 and f[0].oracle == "learn_loop" and "learner_state" in f[0].summary


def test_any_leak_event_is_a_finding():
    kw = _clean()
    kw["leak_count"] = 2
    f = learn_loop_findings(**kw)
    assert len(f) == 1 and "zpd.leak" in f[0].summary and f[0].evidence == {"count": 2}


@pytest.mark.parametrize(
    "payload",
    [
        {"p_known_before": 1.2, "p_known_after": 0.5},
        {"p_known_after": 0.5},
        {"p_known_before": None, "p_known_after": 0.5},
        {"p_known_before": True, "p_known_after": 0.5},  # a bool is not a probability
        {"p_known_before": "0.5", "p_known_after": 0.5},
        {"p_known_before": float("nan"), "p_known_after": 0.5},
    ],
)
def test_step_payload_bounds_and_missing_keys(payload):
    kw = _clean()
    kw["step_payloads"] = [payload]
    f = learn_loop_findings(**kw)
    assert len(f) == 1 and "zpd.step" in f[0].summary


def test_a_payload_that_is_not_an_object_is_a_finding():
    kw = _clean()
    kw["step_payloads"] = ["oops"]
    assert len(learn_loop_findings(**kw)) == 2  # both keys missing


def test_mastery_score_must_mirror_p_known():
    kw = _clean()
    kw["node_scores"] = [{"id": "n1", "mastery_score": 0.61 + 10 * ORACLE_P_TOLERANCE}]
    f = learn_loop_findings(**kw)
    assert len(f) == 1 and "mastery_score" in f[0].summary


def test_untouched_nodes_are_not_compared():
    kw = _clean()
    kw["node_scores"].append({"id": "n2", "mastery_score": 0.0})
    assert learn_loop_findings(**kw) == []


def test_a_propagated_node_with_state_is_compared_too():
    """apply_graph_update writes learner_state AND the mirror for a one-hop
    propagation target as well — a node with a state row mirrors it whether or
    not it has its own evidence row."""
    kw = _clean()
    kw["state_rows"].append({"user_id": "u", "node_id": "n0", "p_known": 0.4})
    kw["node_scores"].append({"id": "n0", "mastery_score": 0.3})
    f = learn_loop_findings(**kw)
    assert len(f) == 1 and "n0" in f[0].summary


def test_a_never_studied_node_only_propagated_to_stays_off_the_map():
    """#866 K22: a state row with no observation of its own (opps 0) on a
    concept the map shows at 0 is the writer's design, not a mirror drift; an
    observed node at 0, or an unobserved one showing a score, is still judged."""
    kw = _clean()
    kw["state_rows"].append({"user_id": "u", "node_id": "n0", "p_known": 0.45, "opps": 0})
    kw["node_scores"].append({"id": "n0", "mastery_score": 0.0})
    assert learn_loop_findings(**kw) == []
    kw["state_rows"][-1]["opps"] = 1
    assert len(learn_loop_findings(**kw)) == 1
    kw["state_rows"][-1]["opps"] = 0
    kw["node_scores"][-1]["mastery_score"] = 0.3
    assert len(learn_loop_findings(**kw)) == 1


def test_cli_registers_learn_loop():
    from e2e_oracles import __main__ as cli

    assert "learn_loop" in cli.CHECKS


# ── gather.run_learn_loop over a fake connection ────────────────────────────


class _Conn:
    """Answers the gatherer's queries by a substring of their SQL."""

    def __init__(self, answers: dict[str, list[dict]]):
        self.answers, self.sql = answers, []

    def execute(self, sql, params=None):
        self.sql.append((sql, params))
        for key, rows in self.answers.items():
            if key in sql:
                return SimpleNamespace(
                    fetchall=lambda rows=rows: list(rows),
                    fetchone=lambda rows=rows: rows[0] if rows else None,
                )
        raise AssertionError(f"unexpected query: {sql}")


T0 = datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc)


def _answers(*, tables=("learner_state",), states=(), scores=(), pairs=(), steps=(), leaks=0):
    return {
        # the activity queries (tagged; matched before the generic keys below)
        "learn_loop:sessions": [],
        "learn_loop:evidence_hashes": [],
        "learn_loop:messages": [],
        "information_schema.tables": [{"table_name": t} for t in tables],
        "FROM node_mastery_events": list(pairs),
        "FROM learner_state": list(states),
        "event_type = 'zpd.leak'": [{"n": leaks}],
        "event_type = 'zpd.step'": [{"payload": p} for p in steps],
        "FROM graph_nodes": list(scores),
    }


def test_a_missing_learner_state_table_is_an_oracle_error(monkeypatch):
    monkeypatch.setattr(gather, "_db_conn", lambda: _Conn(_answers(tables=())))
    findings, suppressed = gather.run_learn_loop(SimpleNamespace(user="rich-user-active"))
    assert suppressed == 0
    assert [f.oracle for f in findings] == ["oracle-error"]
    assert "learner_state" in findings[0].summary


def test_run_learn_loop_compares_the_mirror_at_the_rows_last_write(monkeypatch):
    """A one-hop propagation stores the belief against the node's KEPT decay
    anchor (graph_service._keep_decay_anchor), so the stored p_known differs
    from the mirror by design; the mirror equals the belief read at the row's
    last write — learning.bkt.decayed_p over (updated_at − last_evidence_at)."""
    from learning.bkt import decayed_p

    anchor = T0 - timedelta(minutes=5)
    stored = 0.7
    mirror = decayed_p(stored, 5 / (24 * 60), 3.0)
    assert abs(mirror - stored) > 1e-9  # the case the raw comparison would misjudge
    states = [
        {
            "user_id": "u",
            "node_id": "n0",
            "p_known": stored,
            "fsrs_s": 3.0,
            "last_evidence_at": anchor,
            "updated_at": T0,
        },
        {
            "user_id": "u",
            "node_id": "n1",
            "p_known": 0.61,
            "fsrs_s": None,
            "last_evidence_at": T0,
            "updated_at": T0,
        },
    ]
    conn = _Conn(
        _answers(
            states=states,
            scores=[{"id": "n0", "mastery_score": mirror}, {"id": "n1", "mastery_score": 0.61}],
            pairs=[{"user_id": "u", "node_id": "n1"}],
            steps=[{"p_known_before": 0.35, "p_known_after": 0.61}],
        )
    )
    monkeypatch.setattr(gather, "_db_conn", lambda: conn)
    findings, _ = gather.run_learn_loop(SimpleNamespace(user="rich-user-active"))
    assert findings == []
    (node_sql, node_params) = next(q for q in conn.sql if "FROM graph_nodes" in q[0])
    assert sorted(node_params[0]) == ["n0", "n1"]


def test_run_learn_loop_reports_what_the_judge_finds(monkeypatch):
    conn = _Conn(
        _answers(
            states=[],
            pairs=[{"user_id": "u", "node_id": "n1"}],
            steps=[{"p_known_after": 0.5}],
            leaks=1,
        )
    )
    monkeypatch.setattr(gather, "_db_conn", lambda: conn)
    findings, _ = gather.run_learn_loop(SimpleNamespace(user="rich-user-active"))
    summaries = " | ".join(f.summary for f in findings)
    assert "learner_state" in summaries and "zpd.leak" in summaries and "zpd.step" in summaries
    # no state row → no node read
    assert not any("FROM graph_nodes" in q[0] for q in conn.sql)


# ── PKG-13 fix round: the oracle must not pass vacuously ─────────────────────
# (e) a check step the session graded has an evidence row for its hash, (f) a
# step whose feedback turn ran has a zpd.step event, (g) no assistant message of
# a loop session states the seeded final answer before the session released an
# answer (a wrong/idk grade, or an H6 worked answer), (h) under
# --expect-loop-activity (the loop journey runs the oracle right after its
# walk, before the next test's truncate), no loop users or no graded step at
# all is itself a finding.

from e2e_oracles.learn_loop import learn_loop_activity_findings  # noqa: E402

SENTINEL = "the kilo sentinel phrase"


def _session(steps=None, sid="s1", user="u"):
    return {"id": sid, "user_id": user, "loop_state": {"phase": "teach", "steps": steps or {}}}


def _step(**over):
    step = {"graded_at": 100.0, "last_verdict": "correct", "feedback_given": True, "rungs": []}
    step.update(over)
    return step


def _activity(**over):
    kw = dict(
        sessions=[_session({"qh": _step()})],
        evidence_keys={("s1", "qh")},
        step_event_keys={("s1", "qh")},
        messages=[{"session_id": "s1", "at": 50.0, "content": "Key idea: bits."}],
        sentinel=SENTINEL,
        expect_activity=True,
    )
    kw.update(over)
    return kw


def test_activity_clean_run_has_no_findings():
    assert learn_loop_activity_findings(**_activity()) == []


def test_a_graded_step_without_an_evidence_row_is_a_finding():
    f = learn_loop_activity_findings(**_activity(evidence_keys=set()))
    assert len(f) == 1 and "evidence" in f[0].summary
    assert f[0].evidence["sample"] == [["s1", "qh"]]


def test_an_ungraded_step_needs_no_evidence():
    kw = _activity(
        sessions=[
            _session(
                {"qh": _step(graded_at=None, feedback_given=False)},
            )
        ]
    )
    kw.update(evidence_keys=set(), step_event_keys=set(), expect_activity=False)
    assert learn_loop_activity_findings(**kw) == []


def test_a_served_feedback_without_a_zpd_step_event_is_a_finding():
    f = learn_loop_activity_findings(**_activity(step_event_keys=set()))
    assert len(f) == 1 and "zpd.step" in f[0].summary


def test_the_final_answer_in_a_message_before_any_release_is_a_finding():
    msgs = [{"session_id": "s1", "at": 150.0, "content": f"Well — {SENTINEL.upper()}!"}]
    f = learn_loop_activity_findings(**_activity(messages=msgs))  # correct: nothing released
    assert len(f) == 1 and "final answer" in f[0].summary
    assert SENTINEL not in str(f[0].evidence).lower()  # never echo the text


def test_the_final_answer_after_a_released_grade_is_the_release():
    steps = {"qh": _step(last_verdict="not_yet", graded_at=100.0)}
    before = {"session_id": "s1", "at": 99.0, "content": SENTINEL}
    after = {"session_id": "s1", "at": 101.0, "content": f"The answer: {SENTINEL}."}
    kw = _activity(sessions=[_session(steps)], messages=[after])
    assert learn_loop_activity_findings(**kw) == []
    kw["messages"] = [before, after]
    assert len(learn_loop_activity_findings(**kw)) == 1


PQ_SENTINEL = "the papa sentinel phrase"


def _with_prequestion(answered_at, status="resolved", records=None):
    s = _session({"qh": _step()})
    s["loop_state"]["prequestion"] = records or {
        "n1": {"status": status, "answered_at": answered_at, "check_item_id": "rich-check-loop-a-mc-pq1"},
    }
    return s


def _key(token="loop-a-pq1"):
    return f"{PQ_SENTINEL} {token}"


def test_a_prequestion_release_opens_only_its_own_sentinel():
    # review fix (spec §13 A138): each release opens its own sentinel. An answered
    # prequestion releases the prequestion items' answer, never a check's.
    pq_after = {"session_id": "s1", "at": 61.0, "content": f"The answer: B. {_key()}"}
    check_answer = {"session_id": "s1", "at": 70.0, "content": f"It is {SENTINEL}."}
    kw = _activity(sessions=[_with_prequestion(60.0)], messages=[pq_after], prequestion_sentinel=PQ_SENTINEL)
    assert learn_loop_activity_findings(**kw) == []
    kw["messages"] = [pq_after, check_answer]  # the check's answer is still unreleased (graded correct)
    f = learn_loop_activity_findings(**kw)
    assert len(f) == 1 and "final answer" in f[0].summary


def test_a_prequestions_answer_before_its_guess_is_a_finding():
    before = {"session_id": "s1", "at": 59.0, "content": _key()}
    for session in (_with_prequestion(60.0), _with_prequestion(60.0, status="posed"), _session({"qh": _step()})):
        kw = _activity(sessions=[session], messages=[before], prequestion_sentinel=PQ_SENTINEL)
        f = learn_loop_activity_findings(**kw)
        assert len(f) == 1 and "prequestion" in f[0].summary
        assert PQ_SENTINEL not in str(f[0].evidence).lower()


def test_one_answered_prequestion_opens_only_its_own_items_key():
    # second review, item 5: per ITEM — the first answer must not open another
    # item's key for the rest of the session
    records = {
        "n1": {"status": "resolved", "answered_at": 60.0, "check_item_id": "rich-check-loop-a-mc-pq1"},
        "n2": {"status": "posed", "check_item_id": "rich-check-loop-b-mc-pq1"},
    }
    other = {"session_id": "s1", "at": 90.0, "content": f"It is {_key('loop-b-pq1')}."}
    kw = _activity(sessions=[_with_prequestion(None, records=records)], messages=[other],
                   prequestion_sentinel=PQ_SENTINEL)
    f = learn_loop_activity_findings(**kw)
    assert len(f) == 1 and "prequestion" in f[0].summary
    kw["messages"] = [{"session_id": "s1", "at": 90.0, "content": _key("loop-a-pq1")}]
    assert learn_loop_activity_findings(**kw) == []
    kw["messages"] = [{"session_id": "s1", "at": 90.0, "content": f"bare {PQ_SENTINEL}"}]  # unknown: fails closed
    assert len(learn_loop_activity_findings(**kw)) == 1


def test_an_h6_worked_answer_is_a_release_at_its_logged_time():
    steps = {"qh": _step(graded_at=None, feedback_given=False, rungs=[{"rung": 6, "at": 80.0}])}
    kw = _activity(
        sessions=[_session(steps)],
        evidence_keys=set(),
        step_event_keys=set(),
        messages=[{"session_id": "s1", "at": 81.0, "content": SENTINEL}],
        expect_activity=False,
    )
    assert learn_loop_activity_findings(**kw) == []


def test_another_sessions_release_does_not_open_this_one():
    released = _session({"qa": _step(last_verdict="idk", graded_at=10.0)}, sid="s0")
    kw = _activity(
        sessions=[released, _session({"qh": _step()})],
        evidence_keys={("s0", "qa"), ("s1", "qh")},
        step_event_keys={("s0", "qa"), ("s1", "qh")},
        messages=[{"session_id": "s1", "at": 150.0, "content": SENTINEL}],
    )
    assert len(learn_loop_activity_findings(**kw)) == 1


@pytest.mark.parametrize(
    "over, needle",
    [
        ({"sessions": [], "messages": []}, "no loop users"),
        ({"sessions": [_session({})], "messages": []}, "no graded check"),
    ],
)
def test_expect_activity_refuses_a_vacuous_pass(over, needle):
    f = learn_loop_activity_findings(**_activity(**over))
    assert any(needle in x.summary for x in f)


def test_without_expect_activity_an_idle_stack_is_clean():
    kw = _activity(sessions=[], evidence_keys=set(), step_event_keys=set(), messages=[])
    kw["expect_activity"] = False
    assert learn_loop_activity_findings(**kw) == []


def test_loop_users_are_the_students_with_a_loop_session_never_the_retired_toggle(monkeypatch):
    """Z50: (h)'s "no loop users" half counts the students who have a loop
    session (non-empty loop_state, not a review session). The gate never reads
    `user_settings.learning_loop_beta` (PKG-14b) and the seed writes it as inert
    fixture data, so a stack with the loop off for everyone still has two
    rows there — and no loop user."""
    conn = _Conn(
        {
            **_answers(steps=[]),
            "learn_loop:sessions": [],
            "learn_loop:evidence_hashes": [],
            "learn_loop:messages": [],
            "learn_loop:loop_users": [{"n": 2}],  # the retired toggle's rows
            "event_type = 'zpd.step'": [],
        }
    )
    monkeypatch.setattr(gather, "_db_conn", lambda: conn)
    findings, _ = gather.run_learn_loop(SimpleNamespace(user="x", expect_loop_activity=True))
    assert any("no loop users" in f.summary for f in findings)
    assert not any("learning_loop_beta" in sql for sql, _ in conn.sql)


def test_cli_accepts_expect_loop_activity():
    from e2e_oracles import __main__ as cli

    assert cli._parse_args(["--check", "learn_loop", "--expect-loop-activity"]).expect_loop_activity
    assert cli._parse_args([]).expect_loop_activity is False


def test_run_learn_loop_gathers_activity_and_decrypts_messages(monkeypatch):
    import services.encryption as enc

    conn = _Conn(
        {
            **_answers(steps=[]),
            "learn_loop:sessions": [_session({"qh": _step()})],
            "learn_loop:evidence_hashes": [],  # the graded step's evidence is missing
            "learn_loop:messages": [{"session_id": "s1", "at": 150.0, "content": "ct"}],
            "event_type = 'zpd.step'": [
                {
                    "user_id": "u",
                    "payload": {"p_known_before": 0.3, "p_known_after": 0.5, "question_hash": "qh",
                                "phase": "check", "session_id": "s1"},
                }
            ],
        }
    )
    monkeypatch.setattr(gather, "_db_conn", lambda: conn)
    monkeypatch.setattr(enc, "decrypt_if_present", lambda v, **_: SENTINEL if v == "ct" else v)
    findings, _ = gather.run_learn_loop(SimpleNamespace(user="x", expect_loop_activity=True))
    summaries = " | ".join(f.summary for f in findings)
    assert "evidence" in summaries and "final answer" in summaries
    assert "zpd.step" not in summaries  # the step event is there


def test_a_grade_in_one_session_never_vouches_for_the_same_item_in_another(monkeypatch):
    """Z47: (e) and (f) tie each graded step to ITS session's rows. The student
    answered item qh in s1 (its evidence row and its feedback zpd.step are
    there) and again in s2, where the evidence flush was lost and no zpd.step
    was emitted: s2's step is two findings, though the (user, qh) pair has both
    rows table-wide."""
    import services.encryption as enc

    step_payload = {"p_known_before": 0.3, "p_known_after": 0.5, "question_hash": "qh",
                    "phase": "check", "session_id": "s1"}
    conn = _Conn(
        {
            **_answers(steps=[]),
            "learn_loop:sessions": [
                _session({"qh": _step()}, sid="s1"),
                _session({"qh": _step(graded_at=300.0)}, sid="s2"),
            ],
            "learn_loop:evidence_hashes": [{"user_id": "u", "session_id": "s1", "question_hash": "qh"}],
            "learn_loop:messages": [],
            "event_type = 'zpd.step'": [{"user_id": "u", "payload": step_payload}],
        }
    )
    monkeypatch.setattr(gather, "_db_conn", lambda: conn)
    monkeypatch.setattr(enc, "decrypt_if_present", lambda v, **_: v)
    findings, _ = gather.run_learn_loop(SimpleNamespace(user="x", expect_loop_activity=True))
    [evidence] = [f for f in findings if "evidence row" in f.summary]
    [stepped] = [f for f in findings if "zpd.step event" in f.summary]
    assert evidence.evidence["sample"] == [["s2", "qh"]]
    assert stepped.evidence["sample"] == [["s2", "qh"]]


# ── D7: the leak check is per ITEM, and an unreadable row is a finding ───────


def _item(slug, fmt="free", d=1):
    return f"rich-check-{slug}-{fmt}-d{d}"


def _ckey(slug, fmt="free", d=1):
    return f"{SENTINEL} {slug}-{fmt}-d{d}"


def test_a_released_item_opens_only_its_own_key():
    """Item A released at 100; item B still open. B's key at 120 is a leak;
    A's key at 120 is A's release."""
    steps = {
        "qa": _step(check_item_id=_item("loop-a"), last_verdict="not_yet", graded_at=100.0,
                    first_shown_at=10.0),
        "qb": _step(check_item_id=_item("loop-b"), graded_at=None, feedback_given=False,
                    first_shown_at=110.0),
    }
    kw = _activity(
        sessions=[_session(steps)],
        evidence_keys={("s1", "qa")},
        step_event_keys={("s1", "qa")},
        messages=[{"session_id": "s1", "at": 120.0, "content": f"It is {_ckey('loop-a')}."}],
    )
    assert learn_loop_activity_findings(**kw) == []
    kw["messages"] = [{"session_id": "s1", "at": 120.0, "content": f"It is {_ckey('loop-b')}."}]
    f = learn_loop_activity_findings(**kw)
    assert len(f) == 1 and "final answer" in f[0].summary
    kw["messages"] = [{"session_id": "s1", "at": 120.0, "content": _ckey("loop-z")}]  # no such step
    assert len(learn_loop_activity_findings(**kw)) == 1


def test_a_bare_sentinel_after_one_release_still_leaks_the_next_item():
    """The old per-session rule passed any mention after the FIRST release; a
    bare sentinel is every seeded item's answer, read as the answer of the
    item in front of the student — with B shown and unreleased, B's."""
    steps = {
        "qa": _step(check_item_id=_item("loop-a"), last_verdict="idk", graded_at=100.0,
                    first_shown_at=10.0),
        "qb": _step(check_item_id=_item("loop-b"), graded_at=None, feedback_given=False,
                    first_shown_at=110.0),
    }
    kw = _activity(
        sessions=[_session(steps)],
        evidence_keys={("s1", "qa")},
        step_event_keys={("s1", "qa")},
        messages=[{"session_id": "s1", "at": 120.0, "content": SENTINEL}],
    )
    f = learn_loop_activity_findings(**kw)
    assert len(f) == 1 and "final answer" in f[0].summary
    # before B was shown, the same bare mention is A's release
    kw["messages"] = [{"session_id": "s1", "at": 105.0, "content": SENTINEL}]
    assert learn_loop_activity_findings(**kw) == []
    # B graded correct releases nothing (the feedback never states it) ...
    steps["qb"].update(graded_at=115.0, last_verdict="correct", feedback_given=True)
    kw.update(evidence_keys={("s1", "qa"), ("s1", "qb")}, step_event_keys={("s1", "qa"), ("s1", "qb")},
              messages=[{"session_id": "s1", "at": 120.0, "content": SENTINEL}])
    assert len(learn_loop_activity_findings(**kw)) == 1
    # ... B's own release does
    steps["qb"].update(last_verdict="not_yet")
    assert learn_loop_activity_findings(**kw) == []


def test_an_abandoned_item_does_not_hold_back_a_later_items_release():
    """A left unanswered (never graded, no H6), then B posed and released: a
    bare mention after B's release is B's answer, not a leak of A."""
    steps = {
        "qa": _step(check_item_id=_item("loop-a"), graded_at=None, feedback_given=False,
                    first_shown_at=10.0),
        "qb": _step(check_item_id=_item("loop-b"), last_verdict="idk", graded_at=100.0,
                    first_shown_at=50.0),
    }
    kw = _activity(
        sessions=[_session(steps)],
        evidence_keys={("s1", "qb")},
        step_event_keys={("s1", "qb")},
        messages=[{"session_id": "s1", "at": 120.0, "content": SENTINEL}],
    )
    assert learn_loop_activity_findings(**kw) == []
    kw["messages"] = [{"session_id": "s1", "at": 30.0, "content": SENTINEL}]  # while A was in front
    assert len(learn_loop_activity_findings(**kw)) == 1


def test_an_undecryptable_assistant_row_is_a_finding_not_empty_text():
    kw = _activity(messages=[{"session_id": "s1", "at": 50.0, "content": "", "undecryptable": True}])
    f = learn_loop_activity_findings(**kw)
    assert len(f) == 1 and "could not be decrypted" in f[0].summary
    assert f[0].evidence == {"sessions": ["s1"]}


def test_run_learn_loop_marks_a_row_it_cannot_decrypt(monkeypatch):
    import services.encryption as enc

    conn = _Conn(
        {
            **_answers(steps=[]),
            "learn_loop:sessions": [_session({"qh": _step()})],
            "learn_loop:evidence_hashes": [{"session_id": "s1", "question_hash": "qh"}],
            "learn_loop:messages": [
                {"session_id": "s1", "at": 150.0, "content": "enc2:0:bad"},
                {"session_id": "s1", "at": 151.0, "content": "boom"},
            ],
            "event_type = 'zpd.step'": [
                {"user_id": "u", "payload": {"p_known_before": 0.3, "p_known_after": 0.5,
                                             "question_hash": "qh", "phase": "check",
                                             "session_id": "s1"}}
            ],
        }
    )

    def decrypt(v, **_):
        if v == "boom":
            raise ValueError("bad key")
        return None  # decrypt_if_present fails soft on a binding mismatch

    monkeypatch.setattr(gather, "_db_conn", lambda: conn)
    monkeypatch.setattr(enc, "decrypt_if_present", decrypt)
    findings, _ = gather.run_learn_loop(SimpleNamespace(user="x", expect_loop_activity=True))
    [unreadable] = [f for f in findings if "decrypted" in f.summary]
    assert unreadable.summary.startswith("2 assistant message(s)")
