"""Spec §13 A123: void evidence is excluded wherever the journal is read AS
EVIDENCE — and kept where it is read as EXPOSURE.

A row is void when `learning_evidence_voids` names its id (written with the
recomputed state by the single graph writer's void branch). Excluded from: the
post-test windows' anchor and last evidence (eligibility), the planning history
(a void row consumes its hash's first exposure but certifies nothing), a
session's close, the learner brief's past closes, the learning velocity (the
Tree and the quiz prompt) and the nightly ZPD metrics. Kept by: the seen /
revealed sets (the student did see the question).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

T0 = datetime(2026, 9, 1, tzinfo=timezone.utc)


def _paged(rows):
    handle = MagicMock()
    handle.select_with_count.return_value = (rows, len(rows))
    handle.select.return_value = rows
    return handle


# ── the void record's reads ─────────────────────────────────────────────────


def test_void_reads_name_their_scope_and_page_in_a_total_order():
    from learning import void_store

    handle = _paged([{"event_id": "e1"}, {"event_id": "e2"}])
    with patch("learning.void_store.table", return_value=handle) as tbl:
        assert void_store.voided_event_ids(user_id="u1") == {"e1", "e2"}
    tbl.assert_called_with("learning_evidence_voids")
    kw = handle.select_with_count.call_args.kwargs
    assert kw["filters"] == {"user_id": "eq.u1"} and kw["order"] == "event_id"
    with patch("learning.void_store.table", return_value=_paged([])) as tbl:
        void_store.voided_event_ids(node_id="n1", session_id="s1")
    with pytest.raises(ValueError):
        void_store.voided_event_ids()
    sessions = _paged([{"event_id": "e1", "session_id": "s1"}, {"event_id": "e2", "session_id": None}])
    with patch("learning.void_store.table", return_value=sessions):
        assert void_store.voided_sessions("u1") == {"s1"}
    assert sessions.select_with_count.call_args.kwargs["filters"] == {
        "user_id": "eq.u1", "session_id": "not.is.null",
    }


# ── post-test eligibility: the windows' anchor ─────────────────────────────


def test_a_void_row_neither_anchors_a_concept_nor_is_its_last_evidence():
    """The post-test windows run from the concept's FIRST VALID evidence; a
    concept whose every row is void has no span (no valid evidence)."""
    from learning import loop_state_store

    rows = [
        {"id": "e-void-first", "node_id": "n1", "created_at": T0.isoformat()},
        {"id": "e2", "node_id": "n1", "created_at": (T0 + timedelta(days=2)).isoformat()},
        {"id": "e-void-last", "node_id": "n1", "created_at": (T0 + timedelta(days=9)).isoformat()},
        {"id": "e-only-void", "node_id": "n2", "created_at": T0.isoformat()},
    ]
    with (
        patch("learning.loop_state_store.table", return_value=_paged(rows)),
        patch(
            "learning.void_store.voided_event_ids",
            return_value={"e-void-first", "e-void-last", "e-only-void"},
        ) as voids,
    ):
        spans = loop_state_store.evidence_spans("u", "c")
    voids.assert_called_once_with(user_id="u")
    assert spans["n1"].first_id == "e2"
    assert spans["n1"].first_at == spans["n1"].last_at == T0 + timedelta(days=2)
    assert "n2" not in spans


def test_seen_and_revealed_keep_void_rows_as_exposure():
    """A voided grade was still SEEN (and its answer released): exposure is not
    evidence, and the void record is not even read."""
    from learning import loop_state_store

    rows = [{"question_hash": "q-void", "correct": False, "max_rung": 0}]
    with (
        patch("learning.loop_state_store.table", return_value=_paged(rows)),
        patch("learning.void_store.voided_event_ids", side_effect=AssertionError("not read")),
    ):
        assert loop_state_store.seen_hashes("u") == {"q-void"}
        assert "q-void" in loop_state_store.revealed_hashes("u")


# ── the planning history ────────────────────────────────────────────────────


def _planning_row(event_id, qh, *, node="n1", course="c1"):
    from learning.evidence import Evidence, planning_observation

    ev = Evidence(
        node_id=node, channel="free_response", correct=True, session_id="s1",
        check_item_id=f"item-{qh}", question_hash=qh,
        planning_provenance={"check_item_id": f"item-{qh}", "difficulty": 2,
                             "synthetic_idk": False, "previously_seen": False},
    )
    return {
        "id": event_id, "node_id": node, "question_hash": qh, "check_item_id": ev.check_item_id,
        "channel": ev.channel, "correct": ev.correct, "assisted": ev.assisted, "max_rung": ev.max_rung,
        "reason": "evidence:free_response", "planning_observation": planning_observation(ev),
        "graph_nodes": {"user_id": "u1", "course_id": course},
    }


def test_a_void_row_consumes_its_exposure_but_certifies_nothing():
    from learning import planning_history

    rows = [_planning_row("e-void", "q-bad"), _planning_row("e-ok", "q-ok")]
    with (
        patch("learning.planning_history.page_all", return_value=iter(rows)),
        patch("learning.planning_history.voided_event_ids", return_value={"e-void"}) as voids,
    ):
        history = planning_history.read_planning_history("u1", "c1", ["n1"])
    voids.assert_called_once_with(user_id="u1")
    assert history[0] == {"question_hash": "q-bad"}  # the exposure only
    assert history[1]["question_hash"] == "q-ok" and history[1]["independent"] is True
    # nothing void: both certify
    full = planning_history.project_planning_history(rows, "u1", "c1", ["n1"])
    assert all("independent" in h for h in full)


def test_an_unreadable_void_record_fails_the_planning_read_closed():
    from learning import planning_history
    from learning.evidence import PlanningPersistenceUnavailable

    with (
        patch("learning.planning_history.page_all", return_value=iter([_planning_row("e", "q")])),
        patch("learning.planning_history.voided_event_ids", side_effect=RuntimeError("down")),
        pytest.raises(PlanningPersistenceUnavailable),
    ):
        planning_history.read_planning_history("u1", "c1", ["n1"])


# ── a session's close and the brief's past closes ──────────────────────────


def test_a_close_leaves_out_every_concept_a_void_row_touched_in_the_session():
    from routes import learn_loop

    evidence = [
        {"id": "e1", "node_id": "n-bad", "p_before": 0.35, "p_after": 0.6, "correct": True, "channel": "mc"},
        {"id": "e2", "node_id": "n-bad", "p_before": 0.6, "p_after": 0.7, "correct": True, "channel": "mc"},
        {"id": "e3", "node_id": "n-ok", "p_before": 0.35, "p_after": 0.5, "correct": True, "channel": "mc"},
    ]

    def table(name):
        return _paged(evidence if name == "node_mastery_events" else [])

    with (
        patch("routes.learn_loop.table", side_effect=table),
        patch("routes.learn_loop.voided_event_ids", return_value={"e1"}) as voids,
    ):
        _transcript, kept = learn_loop._session_record("s1")
    voids.assert_called_once_with(session_id="s1")
    assert [e["id"] for e in kept] == ["e3"]  # e2 ran through the void e1: no valid trajectory


def test_the_brief_never_renders_a_close_of_a_session_with_void_evidence():
    from learning import learner_brief
    from services.encryption import encrypt_json

    rows = [
        {"id": "s-void", "started_at": "2026-09-02T00:00:00+00:00", "close_json": encrypt_json({"concepts": [{"node_id": "n", "p_before": 0.2, "p_after": 0.9}]}), "close_phase": "close"},
        {"id": "s-ok", "started_at": "2026-09-01T00:00:00+00:00", "close_json": encrypt_json({"concepts": []}), "close_phase": "close"},
    ]
    with (
        patch("learning.learner_brief.course_offering_ids", return_value=["off-1"]),
        patch("learning.learner_brief.table", return_value=_paged(rows)),
        patch("learning.learner_brief.voided_sessions", return_value={"s-void"}) as voids,
    ):
        closes = learner_brief._read_closes("u1", "c1")
    voids.assert_called_once_with("u1")
    assert [day for day, _ in closes] == ["2026-09-01"]


# ── the learning velocity and the ZPD metrics ──────────────────────────────


def test_the_tree_velocity_leaves_out_void_rows_and_keeps_its_api_shape():
    from services import graph_service

    recent = datetime.now(timezone.utc) - timedelta(days=2)
    events = [
        {"id": "e-void", "node_id": "n1", "delta": 0.4, "reason": "evidence:mc", "created_at": recent.isoformat()},
        {"id": "e-ok", "node_id": "n1", "delta": 0.1, "reason": "evidence:mc", "created_at": recent.isoformat()},
    ]
    node = {"id": "n1", "mastery_tier": "learning", "mastery_score": 0.5, "course_id": "c1", "times_studied": 2}

    def table(name):
        return _paged({"graph_nodes": [node], "node_mastery_events": events}.get(name, []))

    with (
        patch("services.graph_service.table", side_effect=table),
        patch("services.graph_service._user_enrolled_courses", return_value=[]),
        patch("services.graph_service.ensure_user_exists"),
        patch("services.graph_service.voided_event_ids", return_value={"e-void"}),
    ):
        out = graph_service.get_graph("u1")
    (n1,) = [n for n in out["nodes"] if n["id"] == "n1"]
    assert n1["learning_velocity"] == pytest.approx(0.1 / 2)
    assert n1["mastery_events"] == [{k: v for k, v in events[1].items() if k != "id"}]


def test_the_quiz_prompt_velocity_leaves_out_void_rows_before_its_cap():
    from services import quiz_signals

    handle = _paged([])
    with (
        patch("services.quiz_signals.voided_event_ids", return_value={"e2", "e1"}) as voids,
        patch("services.quiz_signals.table", return_value=handle),
    ):
        quiz_signals._velocity("n1")
    voids.assert_called_once_with(node_id="n1")
    assert handle.select.call_args.kwargs["filters"] == {
        "node_id": "eq.n1", "id": 'not.in.("e1","e2")',
    }


def test_the_zpd_metrics_read_no_void_row():
    import scripts.derive_zpd_metrics as metrics

    handle = _paged([])
    with (
        patch.object(metrics, "voided_event_ids", return_value={"e9"}),
        patch.object(metrics, "table", return_value=handle),
    ):
        metrics._evidence("n1")
    filters = handle.select.call_args.kwargs["filters"]
    assert filters["id"] == 'not.in.("e9")' and filters["node_id"] == "eq.n1"
    with (
        patch.object(metrics, "voided_event_ids", return_value=set()),
        patch.object(metrics, "table", return_value=handle),
    ):
        metrics._evidence("n1")
    assert "id" not in handle.select.call_args.kwargs["filters"]
