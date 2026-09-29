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
        "learn_loop:loop_users": [{"n": 0}],
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
        evidence_hashes={("u", "qh")},
        step_event_hashes={("u", "qh")},
        messages=[{"session_id": "s1", "at": 50.0, "content": "Key idea: bits."}],
        sentinel=SENTINEL,
        loop_users=2,
        expect_activity=True,
    )
    kw.update(over)
    return kw


def test_activity_clean_run_has_no_findings():
    assert learn_loop_activity_findings(**_activity()) == []


def test_a_graded_step_without_an_evidence_row_is_a_finding():
    f = learn_loop_activity_findings(**_activity(evidence_hashes=set()))
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
    kw.update(evidence_hashes=set(), step_event_hashes=set(), expect_activity=False)
    assert learn_loop_activity_findings(**kw) == []


def test_a_served_feedback_without_a_zpd_step_event_is_a_finding():
    f = learn_loop_activity_findings(**_activity(step_event_hashes=set()))
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


def test_an_h6_worked_answer_is_a_release_at_its_logged_time():
    steps = {"qh": _step(graded_at=None, feedback_given=False, rungs=[{"rung": 6, "at": 80.0}])}
    kw = _activity(
        sessions=[_session(steps)],
        evidence_hashes=set(),
        step_event_hashes=set(),
        messages=[{"session_id": "s1", "at": 81.0, "content": SENTINEL}],
        expect_activity=False,
    )
    assert learn_loop_activity_findings(**kw) == []


def test_another_sessions_release_does_not_open_this_one():
    released = _session({"qa": _step(last_verdict="idk", graded_at=10.0)}, sid="s0")
    kw = _activity(
        sessions=[released, _session({"qh": _step()})],
        evidence_hashes={("u", "qa"), ("u", "qh")},
        step_event_hashes={("u", "qa"), ("u", "qh")},
        messages=[{"session_id": "s1", "at": 150.0, "content": SENTINEL}],
    )
    assert len(learn_loop_activity_findings(**kw)) == 1


@pytest.mark.parametrize(
    "over, needle",
    [
        ({"loop_users": 0}, "no loop users"),
        ({"sessions": [_session({})], "messages": []}, "no graded check"),
    ],
)
def test_expect_activity_refuses_a_vacuous_pass(over, needle):
    f = learn_loop_activity_findings(**_activity(**over))
    assert any(needle in x.summary for x in f)


def test_without_expect_activity_an_idle_stack_is_clean():
    kw = _activity(sessions=[], evidence_hashes=set(), step_event_hashes=set(), messages=[])
    kw["expect_activity"] = False
    assert learn_loop_activity_findings(**kw) == []


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
            "learn_loop:loop_users": [{"n": 2}],
            "event_type = 'zpd.step'": [
                {
                    "user_id": "u",
                    "payload": {"p_known_before": 0.3, "p_known_after": 0.5, "question_hash": "qh"},
                }
            ],
        }
    )
    monkeypatch.setattr(gather, "_db_conn", lambda: conn)
    monkeypatch.setattr(enc, "decrypt_if_present", lambda v: SENTINEL if v == "ct" else v)
    findings, _ = gather.run_learn_loop(SimpleNamespace(user="x", expect_loop_activity=True))
    summaries = " | ".join(f.summary for f in findings)
    assert "evidence" in summaries and "final answer" in summaries
    assert "zpd.step" not in summaries  # the step event is there
