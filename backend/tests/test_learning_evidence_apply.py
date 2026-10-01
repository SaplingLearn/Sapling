"""PKG-03: Evidence model + weights (spec §3.1, §5), learner_state access,
and apply_graph_update's evidence path (spec §5). Mocks follow
tests/test_graph_service.py::_bulk_factory."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import get_args
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from learning.params import (
    BKT_L0,
    CHANNELS,
    GRADER_LOW_CONFIDENCE,
    LADDER_MAX_RUNG,
    RUNG_ASSISTED_MIN,
    RUNG_NO_CREDIT_MIN,
    WEIGHT_ASSISTED,
    WEIGHT_LOW_CONFIDENCE,
    WEIGHT_PROPAGATION,
    WEIGHT_SAME_SESSION_RECHECK,
)

NOW = datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc)
SPEC_CHANNELS = ("free_response", "mc_reasoned", "mc", "teachback_llm", "chat_turn")


# ── Evidence model + weights ──────────────────────────────────────────────────


def _ev(**kw):
    from learning.evidence import Evidence

    base = {"node_id": "n1", "channel": "free_response", "correct": True}
    base.update(kw)
    return Evidence(**base)


class TestEvidenceModel:
    def test_minimal_defaults_match_spec(self):
        ev = _ev()
        assert (ev.assisted, ev.max_rung, ev.weight, ev.idk) == (False, 0, 1.0, False)
        assert ev.session_id is None and ev.check_item_id is None
        assert ev.question_hash is None and ev.confidence is None
        assert ev.same_session_recheck is False

    def test_channel_is_the_spec_literal(self):
        from learning import fsrs
        from learning.evidence import Channel

        # Spec §13 A1: five item channels; "I don't know" is the idk flag.
        assert get_args(Channel) == SPEC_CHANNELS
        assert set(get_args(Channel)) == fsrs.RATING_CHANNELS == set(CHANNELS)
        for channel in SPEC_CHANNELS:
            _ev(channel=channel, correct=False)
        for bad in ("vibes", "idk"):
            with pytest.raises(ValidationError):
                _ev(channel=bad, correct=False)

    def test_idk_is_a_flag_and_cannot_be_correct(self):
        assert _ev(channel="mc", idk=True, correct=False).idk is True
        with pytest.raises(ValidationError, match="idk"):
            _ev(idk=True, correct=True)

    def test_max_rung_bounded_and_any_rung_implies_assisted(self):
        with pytest.raises(ValidationError):
            _ev(max_rung=LADDER_MAX_RUNG + 1)
        with pytest.raises(ValidationError):
            _ev(max_rung=-1)
        with pytest.raises(ValidationError):
            _ev(max_rung=2.5)
        assert _ev(max_rung=RUNG_ASSISTED_MIN).assisted is True
        assert _ev(max_rung=LADDER_MAX_RUNG).assisted is True
        assert _ev(max_rung=0).assisted is False

    def test_assisted_without_a_rung_is_raised_to_the_first_assisted_rung(self):
        """Spec §5: assisted means a rung H1..H3 was used, so `assisted=True`
        with `max_rung=0` is read as H1. BKT (assisted weight), the counters
        and FSRS (rating_for keys on max_rung: Hard) then agree."""
        from learning import fsrs

        ev = _ev(assisted=True)
        assert (ev.assisted, ev.max_rung) == (True, RUNG_ASSISTED_MIN)
        assert ev.weight == WEIGHT_ASSISTED
        assert fsrs.rating_for(ev.channel, ev.correct, ev.max_rung) == fsrs.Rating.HARD
        assert _ev(assisted=True, max_rung=3).max_rung == 3

    def test_confidence_and_weight_are_unit_interval(self):
        for bad in (-0.1, 1.1, float("nan"), float("inf")):
            with pytest.raises(ValidationError):
                _ev(confidence=bad)
            with pytest.raises(ValidationError):
                _ev(weight=bad)


class TestEvidenceWeight:
    def test_unassisted_first_attempt_is_full_weight(self):
        from learning.evidence import evidence_weight

        assert evidence_weight(_ev()) == 1.0

    def test_assisted_correct_halves_but_assisted_wrong_is_standard(self):
        from learning.evidence import evidence_weight

        assert evidence_weight(_ev(assisted=True, max_rung=2)) == WEIGHT_ASSISTED
        assert evidence_weight(_ev(correct=False, assisted=True, max_rung=3)) == 1.0
        assert evidence_weight(_ev(correct=False, max_rung=LADDER_MAX_RUNG)) == 1.0
        assert evidence_weight(_ev(idk=True, correct=False, max_rung=2)) == 1.0

    def test_same_session_recheck_halves(self):
        from learning.evidence import evidence_weight

        assert evidence_weight(_ev(same_session_recheck=True)) == WEIGHT_SAME_SESSION_RECHECK

    def test_low_confidence_halves_and_threshold_is_exclusive(self):
        from learning.evidence import evidence_weight

        assert evidence_weight(_ev(confidence=GRADER_LOW_CONFIDENCE)) == 1.0
        assert (
            evidence_weight(_ev(confidence=GRADER_LOW_CONFIDENCE - 0.01)) == WEIGHT_LOW_CONFIDENCE
        )

    def test_weights_compose_as_a_product(self):
        from learning.evidence import evidence_weight

        ev = _ev(assisted=True, max_rung=1, same_session_recheck=True, confidence=0.1)
        assert evidence_weight(ev) == pytest.approx(
            WEIGHT_ASSISTED * WEIGHT_SAME_SESSION_RECHECK * WEIGHT_LOW_CONFIDENCE
        )

    def test_correct_after_worked_example_is_no_upward_evidence(self):
        from learning.evidence import evidence_weight

        assert evidence_weight(_ev(max_rung=RUNG_NO_CREDIT_MIN - 1)) == WEIGHT_ASSISTED
        assert evidence_weight(_ev(max_rung=RUNG_NO_CREDIT_MIN)) == 0.0
        assert evidence_weight(_ev(max_rung=LADDER_MAX_RUNG)) == 0.0

    def test_input_weight_field_is_ignored_and_the_model_carries_the_derived_weight(self):
        from learning.evidence import evidence_weight

        assert evidence_weight(_ev(weight=0.2)) == 1.0
        assert _ev(weight=0.2).weight == 1.0
        assert _ev(assisted=True, max_rung=2, weight=1.0).weight == WEIGHT_ASSISTED
        assert _ev(max_rung=RUNG_NO_CREDIT_MIN, weight=1.0).weight == 0.0

    def test_strong_channels_match_spec_table(self):
        from learning.evidence import is_strong_channel

        assert {c for c in SPEC_CHANNELS if is_strong_channel(c)} == {
            "free_response",
            "mc_reasoned",
        }
        for bad in ("idk", "vibes"):
            with pytest.raises(ValueError):
                is_strong_channel(bad)

    def test_module_constants(self):
        from learning import evidence, params

        assert evidence.PROPAGATION_CHANNEL == params.PROPAGATION_CHANNEL == "chat_turn"
        assert evidence.EVIDENCE_EVENT_TYPE == "evidence"
        assert evidence.PREREQ_RELATIONSHIP_TYPE == "prerequisite"


# ── learner_state ─────────────────────────────────────────────────────────────


def _state_row(**over):
    row = {
        "user_id": "u1",
        "node_id": "n1",
        "p_known": 0.9,
        "n_strong_unassisted": 2,
        "streak_unassisted": 1,
        "max_streak_unassisted": 3,
        "opps": 4,
        "fsrs_d": 5.0,
        "fsrs_s": 10.0,
        "fsrs_last_review_at": (NOW - timedelta(days=3)).isoformat(),
        "fsrs_due_at": (NOW + timedelta(days=7)).isoformat(),
        "htc_k": 0.5,
        "unassisted_next": 0.7,
        "assist_gap": 0.1,
        "in_zone": True,
        "last_evidence_at": (NOW - timedelta(days=3)).isoformat(),
        "updated_at": (NOW - timedelta(days=3)).isoformat(),
    }
    row.update(over)
    return row


def _ls_table(rows):
    t = MagicMock()
    t.select.return_value = rows
    t.upsert.return_value = []
    return t


class TestLearnerState:
    def test_missing_row_defaults_to_prior_and_exists_false(self):
        from learning import learner_state as ls

        t = _ls_table([])
        with patch("learning.learner_state.table", return_value=t):
            st = ls.read_state("u1", "n1", now=NOW)
        assert st.exists is False and st.p_known == BKT_L0
        assert (st.opps, st.streak_unassisted, st.n_strong_unassisted) == (0, 0, 0)
        assert st.max_streak_unassisted == 0
        assert st.fsrs_s is None and st.last_evidence_at is None
        _, kwargs = t.select.call_args
        assert kwargs["filters"] == {"user_id": "eq.u1", "node_id": "in.(n1)"}

    def test_read_decays_toward_prior_with_elapsed_time(self):
        from learning import bkt
        from learning import learner_state as ls

        with patch("learning.learner_state.table", return_value=_ls_table([_state_row()])):
            st = ls.read_state("u1", "n1", now=NOW)
        assert st.exists is True
        assert st.p_known == pytest.approx(bkt.decayed_p(0.9, 3.0, 10.0))
        assert BKT_L0 < st.p_known < 0.9
        assert (st.opps, st.streak_unassisted, st.max_streak_unassisted) == (4, 1, 3)
        assert st.fsrs_last_review_at == NOW - timedelta(days=3)
        assert (st.htc_k, st.in_zone) == (0.5, True)

    def test_no_elapsed_time_means_no_decay_and_missing_stability_uses_s0_good(self):
        from learning import bkt
        from learning import learner_state as ls
        from learning.params import FSRS_S0_GOOD

        rows = [_state_row(last_evidence_at=NOW.isoformat())]
        with patch("learning.learner_state.table", return_value=_ls_table(rows)):
            assert ls.read_state("u1", "n1", now=NOW).p_known == pytest.approx(0.9)
        rows = [_state_row(fsrs_s=None, fsrs_d=None)]
        with patch("learning.learner_state.table", return_value=_ls_table(rows)):
            st = ls.read_state("u1", "n1", now=NOW)
        assert st.p_known == pytest.approx(bkt.decayed_p(0.9, 3.0, FSRS_S0_GOOD))

    def test_future_or_null_last_evidence_reads_undecayed_and_z_suffix_parses(self):
        from learning import learner_state as ls

        for last in (None, (NOW + timedelta(hours=5)).isoformat()):
            rows = [_state_row(last_evidence_at=last)]
            with patch("learning.learner_state.table", return_value=_ls_table(rows)):
                assert ls.read_state("u1", "n1", now=NOW).p_known == pytest.approx(0.9)
        rows = [_state_row(last_evidence_at="2026-09-23T12:00:00Z")]
        with patch("learning.learner_state.table", return_value=_ls_table(rows)):
            st = ls.read_state("u1", "n1", now=NOW)
        assert st.last_evidence_at == NOW - timedelta(days=3)

    def test_read_states_is_one_batched_select(self):
        from learning import learner_state as ls

        t = _ls_table([_state_row(node_id="n1"), _state_row(node_id="n2", p_known=0.2)])
        with patch("learning.learner_state.table", return_value=t):
            states = ls.read_states("u1", ["n2", "n1", "n2"], now=NOW)
            assert ls.read_states("u1", [], now=NOW) == {}
        assert set(states) == {"n1", "n2"}
        t.select.assert_called_once()
        assert t.select.call_args.kwargs["filters"]["node_id"] == "in.(n1,n2)"
        assert t.select.call_args.args[0] == ls.LEARNER_STATE_COLUMNS

    def test_read_never_swallows(self):
        """A PostgREST error propagates, and a corrupt stored row raises
        instead of reading as the prior (spec §Error semantics)."""
        from learning import learner_state as ls

        t = MagicMock()
        t.select.side_effect = RuntimeError("PostgREST 400")
        with patch("learning.learner_state.table", return_value=t):
            with pytest.raises(RuntimeError):
                ls.read_states("u1", ["n1"], now=NOW)
        for corrupt in (
            {"fsrs_s": 0.0},
            {"fsrs_s": float("nan")},
            {"p_known": None},
            {"p_known": 1.5},
        ):
            rows = [_state_row(**corrupt)]
            with patch("learning.learner_state.table", return_value=_ls_table(rows)):
                with pytest.raises(ValueError):
                    ls.read_state("u1", "n1", now=NOW)

    def test_write_upserts_on_user_node_and_never_names_derived_columns(self):
        from learning import learner_state as ls

        st = ls.LearnerState(
            user_id="u1",
            node_id="n1",
            p_known=0.7,
            opps=1,
            streak_unassisted=1,
            max_streak_unassisted=1,
            n_strong_unassisted=1,
            fsrs_d=5.0,
            fsrs_s=3.0,
            fsrs_last_review_at=NOW,
            fsrs_due_at=NOW + timedelta(days=2),
            last_evidence_at=NOW,
            htc_k=0.4,
            in_zone=False,
        )
        t = _ls_table([])
        with patch("learning.learner_state.table", return_value=t):
            ls.write_state(st, now=NOW)
            ls.write_state(ls.LearnerState(user_id="u1", node_id="n1", p_known=0.5), now=NOW)
        full, bare = [c.args[0] for c in t.upsert.call_args_list]
        assert t.upsert.call_args.kwargs == {"on_conflict": "user_id,node_id"}
        assert full["p_known"] == 0.7 and full["opps"] == 1
        assert full["max_streak_unassisted"] == 1
        assert full["updated_at"] == NOW.isoformat()
        assert full["fsrs_due_at"] == (NOW + timedelta(days=2)).isoformat()
        for derived in ("htc_k", "unassisted_next", "assist_gap", "in_zone"):
            assert derived not in full
        assert bare["fsrs_last_review_at"] is None and bare["last_evidence_at"] is None
        assert set(full) == set(ls.LEARNER_STATE_COLUMNS.split(",")) - {
            "htc_k",
            "unassisted_next",
            "assist_gap",
            "in_zone",
        }

    def test_columns_match_the_migration(self):
        """read_states selects LEARNER_STATE_COLUMNS by name; a column the
        migration does not create is a PostgREST 400 on every read."""
        import pathlib

        from learning.learner_state import LEARNER_STATE_COLUMNS

        mig_dir = pathlib.Path(__file__).resolve().parents[1] / "db" / "migrations"
        [path] = sorted(mig_dir.glob("*_learning_learner_state.sql"))
        body = path.read_text().split("CREATE TABLE IF NOT EXISTS learner_state (", 1)[1]
        body = body.split("PRIMARY KEY", 1)[0]
        created = set(re.findall(r"^\s*([a-z_]+)\s+[a-z]", body, re.M))
        assert set(LEARNER_STATE_COLUMNS.split(",")) == created


# ── legacy byte-identity ──────────────────────────────────────────────────────

_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
_ISO = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?\+00:00")


def _norm(value):
    if isinstance(value, dict):
        return {k: _norm(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_norm(v) for v in value]
    if isinstance(value, str):
        if _UUID.fullmatch(value):
            return "<UUID>"
        if _ISO.fullmatch(value):
            return "<TS>"
    return value


def _tracing_factory(rows_by_table: dict, trace: list):
    """Every table call lands in `trace` as (table, method, args, kwargs);
    graph_nodes.upsert echoes its payload like live PostgREST does."""
    mocks: dict = {}

    def factory(name):
        if name in mocks:
            return mocks[name]
        m = MagicMock()

        def _rec(method):
            def _call(*args, **kwargs):
                trace.append((name, method, _norm(args), _norm(kwargs)))
                if method == "select":
                    return list(rows_by_table.get(name, []))
                if method == "upsert" and name == "graph_nodes":
                    return [args[0]] if isinstance(args[0], dict) else list(args[0])
                return []

            return _call

        for method in ("select", "insert", "update", "upsert", "delete"):
            setattr(m, method, MagicMock(side_effect=_rec(method)))
        mocks[name] = m
        return m

    return factory


LEGACY_NODES = [
    {
        "id": "n1",
        "concept_name": "Recursion",
        "mastery_score": 0.5,
        "times_studied": 1,
        "course_id": "c1",
    },
]
LEGACY_PAYLOAD = {
    "new_nodes": [{"concept_name": "Loops", "initial_mastery": 0.0}],
    "new_edges": [
        {
            "source": "Loops",
            "target": "Recursion",
            "relationship_type": "prerequisite",
            "strength": 0.8,
        },
    ],
}
LEGACY_TRACE = [
    (
        "graph_nodes",
        "select",
        ["id,concept_name,mastery_score,times_studied,course_id"],
        {"filters": {"user_id": "eq.u1", "course_id": "eq.c1"}},
    ),
    (
        "graph_nodes",
        "upsert",
        [
            {
                "id": "<UUID>",
                "user_id": "u1",
                "concept_name": "Loops",
                "mastery_score": 0.0,
                "mastery_tier": "unexplored",
                "course_id": "c1",
            }
        ],
        {"on_conflict": "user_id,course_id,concept_name"},
    ),
    (
        "graph_edges",
        "upsert",
        [
            {
                "id": "<UUID>",
                "user_id": "u1",
                "source_node_id": "<UUID>",
                "target_node_id": "n1",
                "strength": 0.8,
                "relationship_type": "prerequisite",
            }
        ],
        {"on_conflict": "user_id,source_node_id,target_node_id,relationship_type"},
    ),
]


def _run_legacy(payload):
    from services.graph_service import apply_graph_update

    trace: list = []
    factory = _tracing_factory({"graph_nodes": LEGACY_NODES}, trace)
    # learner_state's own `table` is traced too, so a legacy payload that
    # reached read_states/write_state would show up in the trace.
    with (
        patch("services.graph_service.table", side_effect=factory),
        patch("learning.learner_state.table", side_effect=factory),
        patch("services.graph_service.touch_streak_safe"),
        patch("services.course_context_service.update_course_context"),
        patch("services.academics.user_offering_ids_for_course", return_value=[]),
        patch("services.achievement_service.check_achievements"),
    ):
        result = apply_graph_update("u1", payload, course_id="c1")
    return result, trace


def test_legacy_payload_table_trace_unchanged():
    """Green on main BEFORE Task 6, green after: a payload without `evidence`
    makes exactly these table calls, in this order, with these arguments.
    (PKG-14b: the `updated_nodes` key is gone, spec §11.2 — the legacy payload
    is `new_nodes` + `new_edges`, and it moves no mastery.)"""
    result, trace = _run_legacy(LEGACY_PAYLOAD)
    assert result == []
    assert trace == LEGACY_TRACE


@pytest.mark.parametrize("evidence_value", [None, []])
def test_empty_evidence_key_is_the_legacy_path(evidence_value):
    result, trace = _run_legacy({**LEGACY_PAYLOAD, "evidence": evidence_value})
    assert result == []
    assert trace == LEGACY_TRACE


# ── apply_graph_update evidence path ──────────────────────────────────────────


def _evidence_factory(nodes, edges=(), states=()):
    """Per-table mocks. learner_state.select returns `states` regardless of the
    filter (read_states maps by node_id); graph_edges.select returns every edge
    (the adapter picks the direction)."""
    mocks: dict = {}

    def factory(name):
        if name not in mocks:
            m = MagicMock()
            rows = {"graph_nodes": nodes, "graph_edges": edges, "learner_state": states}.get(
                name, []
            )
            m.select.return_value = [dict(r) for r in rows]
            for method in ("insert", "update", "upsert", "delete"):
                getattr(m, method).return_value = []
            if name == "graph_nodes":
                m.upsert.side_effect = lambda data, **kw: [data]
            mocks[name] = m
        return mocks[name]

    return factory, mocks


NODES = [
    {
        "id": "n1",
        "concept_name": "Recursion",
        "mastery_score": 0.5,
        "times_studied": 1,
        "course_id": "c1",
    },
    {
        "id": "n0",
        "concept_name": "Functions",
        "mastery_score": 0.5,
        "times_studied": 3,
        "course_id": "c1",
    },
    {
        "id": "n2",
        "concept_name": "Memoization",
        "mastery_score": 0.5,
        "times_studied": 0,
        "course_id": "c1",
    },
]
# n0 (Functions) is a prerequisite of n1 (Recursion); n1 is a prerequisite of n2.
EDGES = [
    {"source_node_id": "n0", "target_node_id": "n1", "relationship_type": "prerequisite"},
    {"source_node_id": "n1", "target_node_id": "n2", "relationship_type": "prerequisite"},
]


def _apply(payload, nodes=NODES, edges=EDGES, states=(), now=None, **kwargs):
    """`kwargs` are apply_graph_update's keyword options (PKG-12: `retention`)."""
    from services.graph_service import apply_graph_update

    factory, mocks = _evidence_factory(nodes, edges, states)
    clock = patch("services.graph_service.datetime", wraps=datetime)
    with (
        patch("services.graph_service.table", side_effect=factory),
        patch("learning.learner_state.table", side_effect=factory),
        patch("services.graph_service.touch_streak_safe") as streak,
        patch("services.course_context_service.update_course_context"),
        patch("services.academics.user_offering_ids_for_course", return_value=[]),
        patch("services.achievement_service.check_achievements"),
        clock as fake_dt,
    ):
        fake_dt.now.return_value = now or NOW
        result = apply_graph_update("u1", payload, course_id="c1", **kwargs)
    return result, mocks, streak


def _event_rows(mocks):
    if "node_mastery_events" not in mocks:
        return []
    return [c.args[0] for c in mocks["node_mastery_events"].insert.call_args_list]


def _state_writes(mocks):
    if "learner_state" not in mocks:
        return []
    return [c.args[0] for c in mocks["learner_state"].upsert.call_args_list]


def _node_updates(mocks):
    return [
        (c.kwargs["filters"]["id"], c.args[0]) for c in mocks["graph_nodes"].update.call_args_list
    ]


def _read_back(row, write, when):
    """p_known that learner_state.read_state returns at `when` for `row` after
    the upsert `write` merged onto it (PostgREST merge-duplicates)."""
    from learning import learner_state as ls

    merged = {**row, **write}
    with patch("learning.learner_state.table", return_value=_ls_table([merged])):
        return ls.read_state("u1", merged["node_id"], now=when).p_known


class TestApplyEvidence:
    def test_one_event_row_per_evidence_with_every_column(self):
        from learning.evidence import EVIDENCE_EVENT_TYPE

        payload = {
            "evidence": [
                {
                    "node_id": "n1",
                    "channel": "free_response",
                    "correct": True,
                    "session_id": "s1",
                    "check_item_id": "ci1",
                    "question_hash": "q1",
                    "confidence": 0.9,
                },
                {
                    "node_id": "n1",
                    "channel": "mc",
                    "correct": False,
                    "session_id": "s1",
                    "question_hash": "q2",
                },
            ]
        }
        _, mocks, _ = _apply(payload, edges=[])
        rows = [r for r in _event_rows(mocks) if r["event_type"] == EVIDENCE_EVENT_TYPE]
        assert len(rows) == 2
        first = rows[0]
        for col in (
            "id",
            "node_id",
            "delta",
            "reason",
            "created_at",
            "event_type",
            "channel",
            "correct",
            "weight",
            "assisted",
            "max_rung",
            "p_before",
            "p_after",
            "session_id",
            "check_item_id",
            "question_hash",
            "confidence",
        ):
            assert col in first, col
        assert set(first) == set(rows[1]), "every evidence row names the same columns"
        assert first["node_id"] == "n1" and first["channel"] == "free_response"
        assert first["correct"] is True and first["weight"] == 1.0
        assert first["delta"] == pytest.approx(first["p_after"] - first["p_before"])
        assert first["reason"] == "evidence:free_response"
        assert first["created_at"] == NOW.isoformat()
        assert first["check_item_id"] == "ci1" and first["confidence"] == 0.9
        assert rows[1]["check_item_id"] is None and rows[1]["confidence"] is None

    def test_correct_strong_evidence_raises_p_from_prior_and_mirrors_the_node(self):
        from learning import bkt

        result, mocks, streak = _apply(
            {"evidence": [{"node_id": "n1", "channel": "free_response", "correct": True}]},
            edges=[],
        )
        [row] = _event_rows(mocks)
        assert row["p_before"] == pytest.approx(BKT_L0)
        assert row["p_after"] == pytest.approx(bkt.update(BKT_L0, "free_response", True))
        assert row["p_after"] > row["p_before"]
        assert result == [
            {"concept": "Recursion", "before": row["p_before"], "after": row["p_after"]}
        ]
        streak.assert_called_once_with("u1")
        [(node_filter, upd)] = _node_updates(mocks)
        assert node_filter == "eq.n1"
        assert upd["mastery_score"] == pytest.approx(row["p_after"])
        assert upd["mastery_tier"] == bkt.tier_for(row["p_after"])
        assert upd["times_studied"] == 2 and _ISO.fullmatch(upd["last_studied_at"])

    def test_second_evidence_on_same_node_sees_first_posterior(self):
        _, mocks, _ = _apply(
            {
                "evidence": [
                    {"node_id": "n1", "channel": "mc", "correct": True},
                    {"node_id": "n1", "channel": "mc", "correct": True},
                ]
            },
            edges=[],
        )
        a, b = _event_rows(mocks)
        assert b["p_before"] == pytest.approx(a["p_after"])
        assert mocks["learner_state"].select.call_count == 1
        (_, upd_a), (_, upd_b) = _node_updates(mocks)
        assert (upd_a["times_studied"], upd_b["times_studied"]) == (2, 3)

    def test_existing_state_is_read_decayed(self):
        from learning import bkt

        states = [_state_row(node_id="n1", p_known=0.9)]  # 3 days old, S = 10 d
        _, mocks, _ = _apply(
            {"evidence": [{"node_id": "n1", "channel": "mc", "correct": True}]},
            edges=[],
            states=states,
        )
        [row] = _event_rows(mocks)
        assert row["p_before"] == pytest.approx(bkt.decayed_p(0.9, 3.0, 10.0))
        [st] = _state_writes(mocks)
        assert (st["opps"], st["streak_unassisted"], st["n_strong_unassisted"]) == (5, 2, 2)
        assert st["max_streak_unassisted"] == 3, "the stored maximum is kept"

    def test_weights_are_journaled_from_flags_not_input(self):
        _, mocks, _ = _apply(
            {
                "evidence": [
                    {
                        "node_id": "n1",
                        "channel": "free_response",
                        "correct": True,
                        "assisted": True,
                        "max_rung": 2,
                        "weight": 0.9,
                    },
                ]
            },
            edges=[],
        )
        [row] = _event_rows(mocks)
        assert row["weight"] == WEIGHT_ASSISTED and row["assisted"] is True
        assert row["max_rung"] == 2

    def test_same_session_recheck_detected_within_one_call(self):
        _, mocks, _ = _apply(
            {
                "evidence": [
                    {
                        "node_id": "n1",
                        "channel": "free_response",
                        "correct": False,
                        "session_id": "s",
                        "question_hash": "q",
                    },
                    {
                        "node_id": "n1",
                        "channel": "free_response",
                        "correct": True,
                        "session_id": "s",
                        "question_hash": "q",
                    },
                    # a null half never matches
                    {
                        "node_id": "n1",
                        "channel": "free_response",
                        "correct": True,
                        "session_id": "s",
                    },
                    {
                        "node_id": "n1",
                        "channel": "free_response",
                        "correct": True,
                        "session_id": "s",
                    },
                ]
            },
            edges=[],
        )
        rows = _event_rows(mocks)
        assert [r["weight"] for r in rows] == [1.0, WEIGHT_SAME_SESSION_RECHECK, 1.0, 1.0]

    def test_idk_lowers_p_resets_streak_and_is_marked_in_the_journal(self):
        from learning import bkt

        states = [
            _state_row(
                node_id="n1",
                p_known=0.8,
                streak_unassisted=2,
                max_streak_unassisted=2,
                opps=5,
                last_evidence_at=NOW.isoformat(),
            )
        ]
        _, mocks, _ = _apply(
            {"evidence": [{"node_id": "n1", "channel": "mc", "idk": True, "correct": False}]},
            edges=[],
            states=states,
        )
        [row] = _event_rows(mocks)
        assert row["p_after"] < row["p_before"]
        assert row["p_after"] == pytest.approx(bkt.update(0.8, "mc", False, idk=True))
        assert row["p_after"] < bkt.update(0.8, "mc", False), "S_IDK makes idk stronger than a miss"
        assert row["channel"] == "mc" and row["correct"] is False
        assert row["reason"] == "evidence:mc:idk"
        [st] = [w for w in _state_writes(mocks) if w["node_id"] == "n1"]
        assert st["streak_unassisted"] == 0 and st["opps"] == 6
        assert st["max_streak_unassisted"] == 2

    def test_counters_follow_the_evidence_mapping(self):
        _, mocks, _ = _apply(
            {
                "evidence": [
                    {"node_id": "n1", "channel": "free_response", "correct": True},  # strong
                    {"node_id": "n1", "channel": "mc", "correct": True},  # not strong
                    {"node_id": "n1", "channel": "free_response", "correct": True, "max_rung": 2},
                    {"node_id": "n1", "channel": "mc_reasoned", "correct": True},  # strong
                ]
            },
            edges=[],
        )
        a, b, c, d = [w for w in _state_writes(mocks) if w["node_id"] == "n1"]
        assert (a["opps"], a["streak_unassisted"], a["n_strong_unassisted"]) == (1, 1, 1)
        assert (b["opps"], b["streak_unassisted"], b["n_strong_unassisted"]) == (2, 2, 1)
        assert (c["opps"], c["streak_unassisted"], c["n_strong_unassisted"]) == (3, 0, 1)
        assert (d["opps"], d["streak_unassisted"], d["n_strong_unassisted"]) == (4, 1, 2)
        assert [w["max_streak_unassisted"] for w in (a, b, c, d)] == [1, 2, 2, 2]

    def test_same_session_recheck_is_not_a_first_attempt(self):
        """Spec §3.3 / ZPD STATE: the streak and the strong-channel count take
        unassisted FIRST-attempt corrects. A re-check of a question already
        asked this session (the student has seen the answer) counts as an
        opportunity only: it neither extends nor breaks the streak."""
        seen = {"channel": "free_response", "session_id": "s", "question_hash": "q"}
        _, mocks, _ = _apply(
            {
                "evidence": [
                    {"node_id": "n1", "correct": True, **seen},
                    {"node_id": "n1", "correct": True, **seen},  # detected in-call
                    {"node_id": "n1", "correct": True, **seen},
                    {
                        "node_id": "n1",
                        "channel": "mc_reasoned",
                        "correct": True,
                        "same_session_recheck": True,  # flagged by the caller
                    },
                ]
            },
            edges=[],
        )
        writes = [w for w in _state_writes(mocks) if w["node_id"] == "n1"]
        assert [w["opps"] for w in writes] == [1, 2, 3, 4]
        assert [w["streak_unassisted"] for w in writes] == [1, 1, 1, 1]
        assert [w["n_strong_unassisted"] for w in writes] == [1, 1, 1, 1]
        assert writes[-1]["max_streak_unassisted"] == 1
        _, mocks, _ = _apply(
            {
                "evidence": [
                    {"node_id": "n1", "correct": True, **seen},
                    {"node_id": "n1", "correct": False, **seen},
                ]
            },
            edges=[],
        )
        assert [w["streak_unassisted"] for w in _state_writes(mocks)] == [1, 0], (
            "a wrong re-check still breaks the streak"
        )

    def test_correct_after_worked_example_leaves_p_and_still_schedules(self):
        from learning import fsrs

        _, mocks, _ = _apply(
            {
                "evidence": [
                    {
                        "node_id": "n1",
                        "channel": "free_response",
                        "correct": True,
                        "max_rung": RUNG_NO_CREDIT_MIN,
                    },
                ]
            },
            edges=[],
        )
        [row] = _event_rows(mocks)
        assert row["p_after"] == row["p_before"] and row["weight"] == 0.0
        [st] = _state_writes(mocks)
        assert fsrs.rating_for("free_response", True, RUNG_NO_CREDIT_MIN) == fsrs.Rating.AGAIN
        assert st["fsrs_s"] == pytest.approx(fsrs.initial_stability(fsrs.Rating.AGAIN))
        assert st["fsrs_d"] == pytest.approx(fsrs.initial_difficulty(fsrs.Rating.AGAIN))
        assert st["fsrs_last_review_at"] == st["last_evidence_at"] == NOW.isoformat()
        assert st["streak_unassisted"] == 0

    def test_first_review_sets_fsrs_state_and_due_date(self):
        from learning import fsrs
        from learning.params import FSRS_RETENTION_DEFAULT

        _, mocks, _ = _apply(
            {"evidence": [{"node_id": "n1", "channel": "free_response", "correct": True}]},
            edges=[],
        )
        [st] = _state_writes(mocks)
        s0 = fsrs.initial_stability(fsrs.Rating.GOOD)
        assert st["fsrs_s"] == pytest.approx(s0)
        assert st["fsrs_d"] == pytest.approx(fsrs.initial_difficulty(fsrs.Rating.GOOD))
        due = NOW + timedelta(days=fsrs.interval(FSRS_RETENTION_DEFAULT, s0))
        assert st["fsrs_due_at"] == due.isoformat()

    def test_later_review_feeds_elapsed_days_and_the_mc_cap(self):
        from learning import fsrs
        from learning.params import FSRS_RETENTION_DEFAULT

        # 30 days since a review at S = 2.3065: an uncapped Good would reach
        # ~37 d; unassisted mc is capped at S·MC_STABILITY_GAIN_CAP.
        states = [
            _state_row(
                node_id="n1",
                fsrs_d=2.1181,
                fsrs_s=2.3065,
                fsrs_last_review_at=(NOW - timedelta(days=30)).isoformat(),
                last_evidence_at=(NOW - timedelta(days=30)).isoformat(),
            )
        ]
        _, mocks, _ = _apply(
            {"evidence": [{"node_id": "n1", "channel": "mc", "correct": True}]},
            edges=[],
            states=states,
        )
        [st] = _state_writes(mocks)
        d, s = fsrs.next_state(2.1181, 2.3065, fsrs.Rating.GOOD, 30.0, mc_unassisted=True)
        assert (st["fsrs_d"], st["fsrs_s"]) == (pytest.approx(d), pytest.approx(s))
        assert s < fsrs.next_state(2.1181, 2.3065, fsrs.Rating.GOOD, 30.0)[1]
        due = NOW + timedelta(days=fsrs.interval(FSRS_RETENTION_DEFAULT, s))
        assert st["fsrs_due_at"] == due.isoformat()

    def test_retention_keyword_schedules_the_due_date(self):
        """PKG-12 reopen: a review passes its retention target (spec §3.2,
        exam window → FSRS_RETENTION_EXAM); omitted or None keeps
        FSRS_RETENTION_DEFAULT. A higher target is a shorter interval for the
        same state; D and S are untouched by it."""
        from learning import fsrs
        from learning.params import FSRS_RETENTION_DEFAULT, FSRS_RETENTION_EXAM

        payload = {"evidence": [{"node_id": "n1", "channel": "free_response", "correct": True}]}
        writes = {}
        for label, kwargs in (
            ("omitted", {}),
            ("none", {"retention": None}),
            ("exam", {"retention": FSRS_RETENTION_EXAM}),
        ):
            _, mocks, _ = _apply(payload, edges=[], **kwargs)
            [writes[label]] = _state_writes(mocks)
        s0 = fsrs.initial_stability(fsrs.Rating.GOOD)
        for label in ("omitted", "none"):
            due = NOW + timedelta(days=fsrs.interval(FSRS_RETENTION_DEFAULT, s0))
            assert writes[label]["fsrs_due_at"] == due.isoformat(), label
        exam_due = NOW + timedelta(days=fsrs.interval(FSRS_RETENTION_EXAM, s0))
        assert writes["exam"]["fsrs_due_at"] == exam_due.isoformat()
        assert writes["exam"]["fsrs_due_at"] < writes["omitted"]["fsrs_due_at"]
        assert writes["exam"]["fsrs_s"] == writes["omitted"]["fsrs_s"]
        assert writes["exam"]["fsrs_d"] == writes["omitted"]["fsrs_d"]

    def test_review_within_a_day_takes_the_same_day_branch(self):
        from learning import fsrs

        last = NOW - timedelta(hours=2)
        states = [
            _state_row(
                node_id="n1",
                fsrs_d=5.0,
                fsrs_s=10.0,
                fsrs_last_review_at=last.isoformat(),
                last_evidence_at=last.isoformat(),
            )
        ]
        _, mocks, _ = _apply(
            {"evidence": [{"node_id": "n1", "channel": "free_response", "correct": False}]},
            edges=[],
            states=states,
        )
        [st] = _state_writes(mocks)
        days = 2 / 24
        expected = fsrs.next_state(5.0, 10.0, fsrs.Rating.AGAIN, days, same_day=True)
        assert (st["fsrs_d"], st["fsrs_s"]) == (
            pytest.approx(expected[0]),
            pytest.approx(expected[1]),
        )
        assert expected != fsrs.next_state(5.0, 10.0, fsrs.Rating.AGAIN, days)

    def test_correct_propagates_to_prerequisite_parent_only(self):
        from learning import bkt
        from learning.evidence import PROPAGATION_CHANNEL

        _, mocks, _ = _apply(
            {"evidence": [{"node_id": "n1", "channel": "free_response", "correct": True}]}
        )
        writes = {w["node_id"]: w for w in _state_writes(mocks)}
        assert set(writes) == {"n1", "n0"}, "parent n0 updated, child n2 untouched"
        assert writes["n0"]["p_known"] == pytest.approx(
            bkt.update(BKT_L0, PROPAGATION_CHANNEL, True, weight=WEIGHT_PROPAGATION)
        )
        assert writes["n0"]["opps"] == 0 and writes["n0"]["fsrs_s"] is None
        assert writes["n0"]["last_evidence_at"] == NOW.isoformat()
        updates = dict(_node_updates(mocks))
        assert set(updates) == {"eq.n1", "eq.n0"}
        assert set(updates["eq.n0"]) == {"mastery_score", "mastery_tier"}
        assert [r["node_id"] for r in _event_rows(mocks)] == ["n1"], (
            "no journal row for propagation"
        )
        calls = mocks["graph_edges"].select.call_args_list
        assert len(calls) == 2
        assert {c.kwargs["filters"].get("source_node_id") for c in calls} == {"eq.n1", None}
        assert {c.kwargs["filters"].get("target_node_id") for c in calls} == {"eq.n1", None}
        for call in calls:
            f = call.kwargs["filters"]
            assert f["user_id"] == "eq.u1" and f["relationship_type"] == "eq.prerequisite"

    def test_incorrect_propagates_to_dependent_child_only(self):
        _, mocks, _ = _apply(
            {"evidence": [{"node_id": "n1", "channel": "free_response", "correct": False}]}
        )
        writes = {w["node_id"]: w for w in _state_writes(mocks)}
        assert set(writes) == {"n1", "n2"}, "child n2 updated, parent n0 untouched"
        assert writes["n2"]["p_known"] < BKT_L0

    def test_propagation_updates_the_targets_decayed_state(self):
        from learning import bkt
        from learning.evidence import PROPAGATION_CHANNEL

        states = [_state_row(node_id="n0", p_known=0.9, opps=7, streak_unassisted=3)]
        _, mocks, _ = _apply(
            {"evidence": [{"node_id": "n1", "channel": "free_response", "correct": True}]},
            states=states,
        )
        writes = {w["node_id"]: w for w in _state_writes(mocks)}
        decayed = bkt.decayed_p(0.9, 3.0, 10.0)
        posterior = bkt.update(decayed, PROPAGATION_CHANNEL, True, weight=WEIGHT_PROPAGATION)
        # The row is stored against the target's own decay anchor, so it is
        # the READ at NOW that equals the posterior; the mirror shows it too.
        assert _read_back(states[0], writes["n0"], NOW) == pytest.approx(posterior)
        assert dict(_node_updates(mocks))["eq.n0"]["mastery_score"] == pytest.approx(posterior)
        assert (writes["n0"]["opps"], writes["n0"]["streak_unassisted"]) == (7, 3)
        assert writes["n0"]["fsrs_s"] == 10.0, "propagation never touches FSRS"
        # n0 was not an evidence node, so its state was one extra read.
        assert mocks["learner_state"].select.call_count == 2

    def test_propagation_keeps_the_targets_decay_anchor(self):
        """A propagated observation is not a check on the target (spec §1:
        belief decays "between checks"), so it does not restart the target's
        forgetting curve: last_evidence_at is kept and p_known is stored
        against it."""
        from learning import bkt
        from learning.evidence import PROPAGATION_CHANNEL

        anchor = NOW - timedelta(days=3)
        row = _state_row(node_id="n0", p_known=0.6, last_evidence_at=anchor.isoformat())
        _, mocks, _ = _apply(
            {"evidence": [{"node_id": "n1", "channel": "free_response", "correct": True}]},
            states=[row],
        )
        write = {w["node_id"]: w for w in _state_writes(mocks)}["n0"]
        assert write["last_evidence_at"] == anchor.isoformat()
        posterior = bkt.update(
            bkt.decayed_p(0.6, 3.0, 10.0), PROPAGATION_CHANNEL, True, weight=WEIGHT_PROPAGATION
        )
        assert _read_back(row, write, NOW) == pytest.approx(posterior)
        later = NOW + timedelta(days=30)
        assert _read_back(row, write, later) > _read_back(row, {}, later)

    def test_propagation_never_moves_a_later_read_the_wrong_way(self):
        """A correct propagated observation never leaves a parent's belief
        LOWER at a later read than no observation would have, and an incorrect
        one never leaves a child's HIGHER — including where the stored value
        would leave [0, 1] against the old anchor (then the anchor moves
        forward only as far as it must)."""
        from learning import bkt
        from learning.evidence import PROPAGATION_CHANNEL
        from learning.params import BKT_P_MAX

        cases = 0
        for correct, target in ((True, "n0"), (False, "n2")):
            payload = {
                "evidence": [{"node_id": "n1", "channel": "free_response", "correct": correct}]
            }
            for p in (0.01, 0.2, 0.5, 0.8, 0.99, 1.0):
                for stability in (None, 0.5, 30.0):
                    for gap in (0.0, 2.0, 10.0, 200.0):
                        anchor = NOW - timedelta(days=gap)
                        row = _state_row(
                            node_id=target,
                            p_known=p,
                            fsrs_s=stability,
                            fsrs_d=None if stability is None else 5.0,
                            fsrs_last_review_at=None if stability is None else anchor.isoformat(),
                            last_evidence_at=anchor.isoformat(),
                        )
                        _, mocks, _ = _apply(payload, states=[row])
                        write = {w["node_id"]: w for w in _state_writes(mocks)}[target]
                        at = (p, stability, gap, correct)
                        assert 0.0 <= write["p_known"] <= 1.0, at
                        kept = datetime.fromisoformat(write["last_evidence_at"])
                        assert anchor <= kept <= NOW, at
                        posterior = bkt.update(
                            bkt.decayed_p(p, gap, stability),
                            PROPAGATION_CHANNEL,
                            correct,
                            weight=WEIGHT_PROPAGATION,
                        )
                        assert _read_back(row, write, NOW) == pytest.approx(posterior, abs=1e-9), at
                        # bkt.update never returns above BKT_P_MAX, so a stored
                        # 1.0 (outside what update can produce) is compared with
                        # the capped belief it stands for.
                        baseline = {**row, "p_known": min(p, BKT_P_MAX)}
                        for later_days in (1.0, 30.0, 365.0):
                            later = NOW + timedelta(days=later_days)
                            moved = _read_back(row, write, later)
                            untouched = _read_back(baseline, {}, later)
                            if correct:
                                assert moved >= untouched - 1e-9, (at, later_days)
                            else:
                                assert moved <= untouched + 1e-9, (at, later_days)
                        cases += 1
        assert cases == 144

    def test_propagation_target_outside_the_course_is_skipped(self):
        edges = [{"source_node_id": "elsewhere", "target_node_id": "n1"}]
        _, mocks, _ = _apply(
            {"evidence": [{"node_id": "n1", "channel": "free_response", "correct": True}]},
            edges=edges,
        )
        assert [w["node_id"] for w in _state_writes(mocks)] == ["n1"]
        assert [f for f, _ in _node_updates(mocks)] == ["eq.n1"]

    def test_no_credit_evidence_does_not_propagate(self):
        """Spec §3.3: a correct answer after H4–H6 is NO upward BKT evidence —
        for the node's prerequisite parents as much as for the node itself."""
        _, mocks, _ = _apply(
            {
                "evidence": [
                    {
                        "node_id": "n1",
                        "channel": "free_response",
                        "correct": True,
                        "max_rung": RUNG_NO_CREDIT_MIN,
                    },
                ]
                * 4
            }
        )
        assert [w["node_id"] for w in _state_writes(mocks)] == ["n1"] * 4, "parent n0 unwritten"
        assert [f for f, _ in _node_updates(mocks)] == ["eq.n1"] * 4
        assert "graph_edges" not in mocks, "no edge read for evidence that cannot propagate"

    def test_propagation_carries_the_evidences_own_weight(self):
        """The propagated observation's weight is WEIGHT_PROPAGATION times the
        evidence's own §3.1 weight (spec §5: weight = the product of the
        applicable weights), so a discounted answer cannot move a neighbour
        more than it moves the node it was about."""
        from learning import bkt
        from learning.evidence import PROPAGATION_CHANNEL

        _, mocks, _ = _apply(
            {
                "evidence": [
                    {"node_id": "n1", "channel": "free_response", "correct": True, "max_rung": 2},
                ]
            }
        )
        writes = {w["node_id"]: w for w in _state_writes(mocks)}
        assert writes["n0"]["p_known"] == pytest.approx(
            bkt.update(
                BKT_L0, PROPAGATION_CHANNEL, True, weight=WEIGHT_PROPAGATION * WEIGHT_ASSISTED
            )
        )
        _, mocks, _ = _apply(
            {
                "evidence": [
                    {
                        "node_id": "n1",
                        "channel": "free_response",
                        "correct": False,
                        "confidence": 0.1,
                    },
                ]
            }
        )
        writes = {w["node_id"]: w for w in _state_writes(mocks)}
        assert writes["n2"]["p_known"] == pytest.approx(
            bkt.update(
                BKT_L0,
                PROPAGATION_CHANNEL,
                False,
                weight=WEIGHT_PROPAGATION * WEIGHT_LOW_CONFIDENCE,
            )
        )

    def test_unowned_node_is_skipped_with_a_warning(self, caplog):
        with caplog.at_level("WARNING"):
            result, mocks, streak = _apply(
                {"evidence": [{"node_id": "ghost", "channel": "mc", "correct": True}]}, edges=[]
            )
        assert result == []
        assert (
            _state_writes(mocks) == [] and _event_rows(mocks) == [] and _node_updates(mocks) == []
        )
        assert "learner_state" not in mocks, "an unowned node's state is never read either"
        streak.assert_not_called()
        assert any(
            "ghost" in r.getMessage() and "not owned or outside course" in r.getMessage()
            for r in caplog.records
        )

    def test_invalid_evidence_raises_before_any_read_or_write(self):
        from services.graph_service import apply_graph_update

        factory = MagicMock()
        with (
            patch("services.graph_service.table", factory),
            patch("learning.learner_state.table", factory),
        ):
            for bad in (
                {"node_id": "n1", "channel": "mc", "idk": True, "correct": True},
                {"node_id": "n1", "channel": "idk", "correct": False},
                {
                    "node_id": "n1",
                    "channel": "mc",
                    "correct": True,
                    "max_rung": LADDER_MAX_RUNG + 1,
                },
                {"node_id": "n1", "channel": "mc"},
            ):
                good = {"node_id": "n1", "channel": "free_response", "correct": True}
                with pytest.raises(ValidationError):
                    apply_graph_update(
                        "u1", {"new_nodes": [{"concept_name": "X"}], "evidence": [good, bad]}
                    )
        assert factory.call_count == 0, "validation runs before any table() call"

    def test_evidence_and_legacy_keys_coexist(self):
        payload = {
            **LEGACY_PAYLOAD,
            "evidence": [{"node_id": "n1", "channel": "mc", "correct": True}],
        }
        result, mocks, _ = _apply(payload, edges=[])
        # PKG-14b: the legacy keys left are new_nodes/new_edges, which move no
        # mastery; only the evidence is a study of n1 (times_studied 1 → 2).
        assert [c["concept"] for c in result] == ["Recursion"]
        assert [r.get("event_type") for r in _event_rows(mocks)] == ["evidence"]
        n1_counts = [u["times_studied"] for f, u in _node_updates(mocks) if f == "eq.n1"]
        assert n1_counts == [2]

    def test_evidence_instances_are_accepted(self):
        from learning.evidence import Evidence

        _, mocks, _ = _apply(
            {"evidence": [Evidence(node_id="n1", channel="mc", correct=True)]}, edges=[]
        )
        assert [r["channel"] for r in _event_rows(mocks)] == ["mc"]

    def test_mutated_evidence_instances_are_revalidated_before_any_read_or_write(self):
        """Evidence is a plain mutable model: an attribute set after
        construction skips its validators, so an instance is re-validated
        like a dict, before any table() call."""
        from learning.evidence import Evidence
        from services.graph_service import apply_graph_update

        idk_made_correct = Evidence(node_id="n1", channel="mc", correct=False, idk=True)
        idk_made_correct.correct = True
        rung_past_the_ladder = Evidence(node_id="n1", channel="mc", correct=True, max_rung=2)
        rung_past_the_ladder.max_rung = LADDER_MAX_RUNG + 3
        idk_as_a_channel = Evidence(node_id="n1", channel="mc", correct=False)
        idk_as_a_channel.channel = "idk"

        factory = MagicMock()
        with (
            patch("services.graph_service.table", factory),
            patch("learning.learner_state.table", factory),
        ):
            for bad in (idk_made_correct, rung_past_the_ladder, idk_as_a_channel):
                with pytest.raises(ValidationError):
                    apply_graph_update("u1", {"evidence": [bad]})
        assert factory.call_count == 0, "validation runs before any table() call"

    def test_a_valid_instance_is_rederived_not_trusted(self):
        """A mutated flag re-derives the model's consistency rules and weight."""
        from learning.evidence import Evidence

        ev = Evidence(node_id="n1", channel="mc", correct=True)
        ev.assisted = True  # no rung: read as H1, weighed as assisted
        _, mocks, _ = _apply({"evidence": [ev]}, edges=[])
        (row,) = _event_rows(mocks)
        assert (row["max_rung"], row["weight"]) == (RUNG_ASSISTED_MIN, WEIGHT_ASSISTED)


LEGACY_GRAPH_KEYS = frozenset({"new_nodes", "updated_nodes", "new_edges"})
_READ_ONLY_DICT_METHODS = frozenset({"get", "items", "keys", "values"})


def _graph_update_payloads(source: str) -> list[tuple[int, str | None]]:
    """(line, problem) for every apply_graph_update reference in `source`;
    problem is None when the payload provably carries only LEGACY_GRAPH_KEYS.

    A payload passes when it is a dict literal whose keys are all string
    constants in LEGACY_GRAPH_KEYS, or a local name that is bound only to
    such literals, extended only by `name["<legacy key>"] = …`, never
    mutated through a method and never handed to another call. The function
    may be called directly (`apply_graph_update(u, payload)`, by alias or as
    `module.apply_graph_update`) or passed positionally to a runner
    (`asyncio.to_thread(apply_graph_update, u, payload)`). Anything the scan
    cannot resolve is a problem, so the check fails closed."""
    import ast

    tree = ast.parse(source)
    parents = {c: n for n in ast.walk(tree) for c in ast.iter_child_nodes(n)}
    aliases = {"apply_graph_update"} | {
        a.asname
        for n in ast.walk(tree)
        if isinstance(n, ast.ImportFrom)
        for a in n.names
        if a.name == "apply_graph_update" and a.asname
    }

    def is_agu(n):
        return (isinstance(n, ast.Name) and n.id in aliases) or (
            isinstance(n, ast.Attribute) and n.attr == "apply_graph_update"
        )

    def legacy_dict(n):
        return isinstance(n, ast.Dict) and all(
            isinstance(k, ast.Constant) and k.value in LEGACY_GRAPH_KEYS for k in n.keys
        )

    def scope_of(n):
        while n in parents:
            n = parents[n]
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                return n
        return tree

    def name_problem(name, scope, call):
        if isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef)):
            a = scope.args
            params = a.posonlyargs + a.args + a.kwonlyargs + [x for x in (a.vararg, a.kwarg) if x]
            if name in {p.arg for p in params}:
                return f"payload {name!r} is a parameter: built elsewhere"
        bound = False
        for n in ast.walk(scope):
            if not (isinstance(n, ast.Name) and n.id == name):
                continue
            up = parents.get(n)
            if isinstance(n.ctx, ast.Store):
                if isinstance(up, (ast.Assign, ast.AnnAssign)) and legacy_dict(up.value):
                    bound = True
                    continue
                return f"payload {name!r} is bound to something other than a legacy dict"
            if isinstance(up, ast.Subscript) and up.value is n:
                if isinstance(up.ctx, ast.Load):
                    continue
                key = up.slice
                if isinstance(key, ast.Constant) and key.value in LEGACY_GRAPH_KEYS:
                    continue
                return f"payload {name!r} gains a key that is not a legacy constant"
            if isinstance(up, ast.Attribute) and up.value is n:
                if up.attr in _READ_ONLY_DICT_METHODS:
                    continue
                return f"payload {name!r} is mutated via .{up.attr}()"
            if isinstance(up, ast.Call) and n in up.args and up is not call:
                return f"payload {name!r} is handed to another call"
            if isinstance(up, ast.keyword) and parents.get(up) is not call:
                return f"payload {name!r} is handed to another call"
        return None if bound else f"payload {name!r} is never bound in scope"

    results = []
    for node in ast.walk(tree):
        if not is_agu(node):
            continue
        call = parents.get(node)
        if isinstance(call, ast.Call) and call.func is node:
            index = 1
        elif isinstance(call, ast.Call) and any(a is node for a in call.args):
            index = next(i for i, a in enumerate(call.args) if a is node) + 2
        else:
            results.append((node.lineno, "apply_graph_update is referenced, not called"))
            continue
        payload = call.args[index] if len(call.args) > index else None
        if payload is None:
            payload = next((k.value for k in call.keywords if k.arg == "graph_update"), None)
        if legacy_dict(payload):
            problem = None
        elif isinstance(payload, ast.Name):
            problem = name_problem(payload.id, scope_of(call), call)
        else:
            problem = "payload is not a legacy-keyed dict literal or a checkable local"
        results.append((node.lineno, problem))
    return results


# PKG-11 (a PKG-03 reopen): the one evidence caller sanctioned before PKG-05.
# submit_quiz sends {"evidence": ...} only in the body of its `if loop_on:`
# branch (spec §7); every other apply_graph_update call stays legacy-keyed.
# PKG-14b (spec §11.2): the quiz is evidence-only for every student, so its
# call is no longer behind `if loop_on:` — it moved to
# SANCTIONED_EVIDENCE_PERSISTERS below. No gated caller is sanctioned now.
SANCTIONED_EVIDENCE_CALLERS: frozenset = frozenset()
LOOP_GATE_LOCAL = "loop_on"


def _gated_evidence_calls(source: str) -> list[tuple[int, str]]:
    """(line, enclosing def) for each apply_graph_update call whose payload is
    a dict literal with exactly one key, the constant "evidence", and which
    sits in the BODY (not the else) of an `if loop_on:` inside that def.
    `line` is the callee's line, as _graph_update_payloads reports it."""
    import ast

    tree = ast.parse(source)
    parents = {c: n for n in ast.walk(tree) for c in ast.iter_child_nodes(n)}
    found = []
    for call in ast.walk(tree):
        if not (isinstance(call, ast.Call) and len(call.args) > 1):
            continue
        func = call.func
        if not (
            (isinstance(func, ast.Name) and func.id == "apply_graph_update")
            or (isinstance(func, ast.Attribute) and func.attr == "apply_graph_update")
        ):
            continue
        payload = call.args[1]
        if not (
            isinstance(payload, ast.Dict)
            and len(payload.keys) == 1
            and isinstance(payload.keys[0], ast.Constant)
            and payload.keys[0].value == "evidence"
        ):
            continue
        gated, child, node = False, call, parents.get(call)
        while node is not None and not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if (
                isinstance(node, ast.If)
                and isinstance(node.test, ast.Name)
                and node.test.id == LOOP_GATE_LOCAL
                and any(child is s for s in node.body)
            ):
                gated = True
            child, node = node, parents.get(node)
        if gated and node is not None:
            found.append((func.lineno, node.name))
    return found


_GATED_QUIZ = """
def submit_quiz(u, evs):
    loop_on = learning_loop_active(u)
    if loop_on:
        applied = apply_graph_update(u, {"evidence": evs}, course_id=None)
    else:
        applied = apply_graph_update(u, {"updated_nodes": []}, course_id=None)
"""


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (_GATED_QUIZ, ["submit_quiz"]),
        (_GATED_QUIZ.replace("def submit_quiz", "def other_route"), ["other_route"]),
        (_GATED_QUIZ.replace('{"evidence": evs}', '{"updated_nodes": []}'), []),
        (_GATED_QUIZ.replace("if loop_on:", "if not loop_on:"), []),
        (_GATED_QUIZ.replace("if loop_on:", "if True:"), []),
        (
            "def submit_quiz(u, evs):\n    if loop_on:\n        for e in evs:\n"
            '            apply_graph_update(u, {"evidence": [e]})',
            ["submit_quiz"],
        ),
        (
            _GATED_QUIZ.replace('{"evidence": evs}', '{"evidence": evs, "updated_nodes": []}'),
            [],
        ),
        (
            'def submit_quiz(u, evs):\n    apply_graph_update(u, {"evidence": evs})',
            [],
        ),
        (
            "def submit_quiz(u, evs):\n    if loop_on:\n        pass\n"
            '    else:\n        apply_graph_update(u, {"evidence": evs})',
            [],
        ),
        ('if loop_on:\n    apply_graph_update(u, {"evidence": evs})', []),
    ],
)
def test_gated_evidence_call_detector(source, expected):
    """Mutation cases for the PKG-11 excuse in the caller scan below: only a
    pure-evidence literal in the body of `if loop_on:` inside a def counts."""
    assert [fn for _, fn in _gated_evidence_calls(source)] == expected


# PKG-05 (a PKG-03 reopen): learning/evidence.py::flush_pending is the one
# route persister (spec §5, §13 A16) — grade_answer appends, the route calls
# flush_pending, which sends a pure {"evidence": ...} literal. No route calls it
# yet; the package that adds the first route caller (PKG-07's /check/answer)
# retires this scan, its detectors and both sanctioned sets.
# PKG-12 (a PKG-03 reopen): learning/review.py::grade_review persists the one
# Evidence dict grade_answer returned with ONE apply_graph_update call, because
# flush_pending cannot carry the review's retention target (spec §3.2).
SANCTIONED_EVIDENCE_PERSISTERS = frozenset(
    {
        ("learning/evidence.py", "flush_pending"),
        ("learning/review.py", "grade_review"),
        # PKG-14b: ungated after the cutover (spec §11.2), one mc evidence per
        # question — was a SANCTIONED_EVIDENCE_CALLERS (gated) entry.
        ("routes/quiz.py", "submit_quiz"),
    }
)


def _evidence_persister_calls(source: str) -> list[tuple[int, str]]:
    """(line, nearest enclosing def) for each apply_graph_update call — bare or
    `module.apply_graph_update` — whose second positional argument is a dict
    literal with exactly one key, the constant "evidence". `line` is the
    callee's line, as _graph_update_payloads reports it. A module-level call
    has no def and is never returned."""
    import ast

    tree = ast.parse(source)
    parents = {c: n for n in ast.walk(tree) for c in ast.iter_child_nodes(n)}
    found = []
    for call in ast.walk(tree):
        if not (isinstance(call, ast.Call) and len(call.args) > 1):
            continue
        func = call.func
        if not (
            (isinstance(func, ast.Name) and func.id == "apply_graph_update")
            or (isinstance(func, ast.Attribute) and func.attr == "apply_graph_update")
        ):
            continue
        payload = call.args[1]
        if not (
            isinstance(payload, ast.Dict)
            and len(payload.keys) == 1
            and isinstance(payload.keys[0], ast.Constant)
            and payload.keys[0].value == "evidence"
        ):
            continue
        node = parents.get(call)
        while node is not None and not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            node = parents.get(node)
        if node is not None:
            found.append((func.lineno, node.name))
    return found


_FLUSH = """
def flush_pending(deps, course_id):
    if not deps.pending_evidence:
        return []
    from services.graph_service import apply_graph_update

    changes = apply_graph_update(deps.user_id, {"evidence": list(deps.pending_evidence)}, course_id)
    deps.pending_evidence.clear()
    return changes
"""


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (_FLUSH, ["flush_pending"]),
        (_FLUSH.replace("def flush_pending", "def persist_more"), ["persist_more"]),
        (
            _FLUSH.replace("apply_graph_update(deps", "gs.apply_graph_update(deps"),
            ["flush_pending"],
        ),
        (_FLUSH.replace('{"evidence": list(', '{"updated_nodes": [], "evidence": list('), []),
        (_FLUSH.replace('{"evidence": list(deps.pending_evidence)}', "payload"), []),
        (_FLUSH.replace('{"evidence": ', '{"new_nodes": '), []),
        ('apply_graph_update(u, {"evidence": evs})', []),
        (
            "def flush_pending(deps, c):\n    def inner():\n"
            '        return apply_graph_update(u, {"evidence": evs}, c)\n    return inner()',
            ["inner"],
        ),
    ],
)
def test_evidence_persister_detector(source, expected):
    """Mutation cases for the PKG-05 excuse in the caller scan below: only a
    pure-evidence literal whose nearest def is named counts, and the scan
    excuses it only for a (file, def) in SANCTIONED_EVIDENCE_PERSISTERS."""
    assert [fn for _, fn in _evidence_persister_calls(source)] == expected


def test_no_production_caller_passes_evidence_yet():
    """PKG-03 adds the path and no caller: every apply_graph_update call in
    application code passes a payload that provably carries only the legacy
    keys. PKG-11 (reopen) excuses exactly the SANCTIONED_EVIDENCE_CALLERS
    call that _gated_evidence_calls finds behind `if loop_on:`. PKG-05
    (reopen) excuses exactly the SANCTIONED_EVIDENCE_PERSISTERS call that
    _evidence_persister_calls finds (learning/evidence.py::flush_pending, the
    route persister; spec §13 A16 builds no graded_check_tool). The package
    that adds the first route caller of flush_pending (PKG-07) retires this
    test and its detectors."""
    import test_learning_loop_invariants as inv

    problems, callers = [], set()
    for rel, path in inv._application_py_files():
        text = path.read_text()
        if "apply_graph_update" not in text:
            continue
        excused = {
            line
            for line, fn in _gated_evidence_calls(text)
            if (rel, fn) in SANCTIONED_EVIDENCE_CALLERS
        } | {
            line
            for line, fn in _evidence_persister_calls(text)
            if (rel, fn) in SANCTIONED_EVIDENCE_PERSISTERS
        }
        for line, problem in _graph_update_payloads(text):
            callers.add(rel)
            if problem and line not in excused:
                problems.append(f"{rel}:{line} {problem}")
    assert problems == [], "\n".join(problems)
    # Non-vacuous: the scan reached the known legacy callers.
    assert callers >= {
        "routes/quiz.py",
        "routes/documents.py",
        "agents/tools/graph.py",
        "services/graph_service.py",
    }, callers


_ADD_NODE_SHAPE = """
def add_node(u, c, anchor):
    update: dict = {"new_nodes": [{"concept_name": "X"}]}
    if anchor:
        update["new_edges"] = []
    apply_graph_update(u, update, course_id=c)
"""


@pytest.mark.parametrize(
    ("source", "offends"),
    [
        ('apply_graph_update(u, {"new_nodes": nodes}, course_id=c)', False),
        ('asyncio.to_thread(apply_graph_update, u, {"updated_nodes": ups}, c)', False),
        (_ADD_NODE_SHAPE, False),
        ("from services.graph_service import apply_graph_update", False),
        ('verdict = {"evidence": "JUDGE ERROR"}', False),
        ('apply_graph_update(u, {"evidence": evs}, c)', True),
        ('apply_graph_update(u, graph_update={"evidence": evs})', True),
        ('upd = {"new_nodes": []}\nupd["evidence"] = evs\napply_graph_update(u, upd)', True),
        ("apply_graph_update(u, dict(evidence=evs))", True),
        ('upd = {}\nupd.setdefault("evidence", evs)\napply_graph_update(u, upd)', True),
        ('upd = {"new_nodes": []}\nupd.update(evidence=evs)\napply_graph_update(u, upd)', True),
        ('K = "evidence"\napply_graph_update(u, {K: evs})', True),
        ('apply_graph_update(u, {**base, "new_nodes": []})', True),
        ('upd = {"new_nodes": []}\nfill(upd)\napply_graph_update(u, upd)', True),
        ("def persist(u, payload):\n    return apply_graph_update(u, payload)", True),
        ('asyncio.to_thread(apply_graph_update, u, {"evidence": evs}, c)', True),
        (
            "from services.graph_service import apply_graph_update as agu\n"
            'agu(u, {"evidence": evs})',
            True,
        ),
        ('import services.graph_service as gs\ngs.apply_graph_update(u, {"evidence": e})', True),
        ("f = functools.partial(apply_graph_update, u)", True),
    ],
)
def test_legacy_payload_detector(source, offends):
    """Mutation cases for test_no_production_caller_passes_evidence_yet: its
    first form matched only a quoted `"evidence":` dict key, and only under
    routes/, agents/ and services/."""
    problems = [p for _, p in _graph_update_payloads(source) if p]
    assert bool(problems) is offends, problems


def test_fsrs_importers_are_sanctioned():
    """HANDOFF-02 Known gaps: the packages that add a learning.fsrs importer
    pin the set. PKG-03 adds services/graph_service.py (reached only through
    apply_graph_update's evidence branch). PKG-11 (reopen) adds
    routes/flashcards.py, whose FSRS calls run only when learning_loop_active
    is true (test_learning_flashcards_fsrs.py pins the gate-off path). PKG-08
    adds routes/learn_loop.py (GET /plan's due reviews: order_due +
    budget_select; every loop route 404s before any read when the gate is
    false). A later package that adds an importer extends this set."""
    import ast
    import pathlib

    backend = pathlib.Path(__file__).resolve().parents[1]
    sanctioned = {"services/graph_service.py", "routes/flashcards.py", "routes/learn_loop.py"}
    importers = set()
    for path in sorted(backend.rglob("*.py")):
        rel = path.relative_to(backend).as_posix()
        if rel.startswith(("tests/", "venv/", "learning/")):
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                names = [mod] + [f"{mod}.{a.name}" for a in node.names]
            else:
                continue
            if "learning.fsrs" in names:
                importers.add(rel)
    assert importers <= sanctioned, importers - sanctioned
    assert "services/graph_service.py" in importers


@pytest.mark.parametrize(
    ("source", "rel", "offends"),
    [
        ('table("graph_nodes").select("id")', "services/x.py", False),
        ('table("graph_nodes").select_with_count("id")', "services/x.py", False),
        ('table("graph_nodes").insert({})', "services/x.py", True),
        ("table('graph_edges').upsert({})", "services/x.py", True),
        ('t = table("node_mastery_events")\nt.insert({})', "services/x.py", True),
        ('table("graph_nodes").delete(filters={})', "routes/x.py", True),
        ('db.connection.table("learner_state").update({}, filters={})', "agents/x.py", True),
        ('table("users").insert({})', "services/x.py", False),
        ('def write_state(s):\n    table("learner_state").upsert({})', "services/x.py", True),
        (
            'def write_state(s):\n    table("learner_state").upsert({})',
            "learning/learner_state.py",
            False,
        ),
        ('def other(s):\n    table("learner_state").upsert({})', "learning/learner_state.py", True),
        (
            'def write_state(s):\n    table("graph_nodes").upsert({})',
            "learning/learner_state.py",
            True,
        ),
    ],
)
def test_inv_01_write_detector(source, rel, offends):
    """Mutation cases for inv_01's ast half: the regex half sees only a direct
    double-quoted `.insert(`/`.update(`/`.upsert(` chain."""
    import test_learning_loop_invariants as inv

    assert bool(inv._graph_table_offenders(rel, source)) is offends


_CALL_PRIVATE = "_apply_evidence(u, [], {}, set(), None)"


@pytest.mark.parametrize(
    ("source", "rel", "offends"),
    [
        (
            f"def apply_graph_update(u, g):\n    return {_CALL_PRIVATE}",
            "services/graph_service.py",
            False,
        ),
        (f"def add_node(u):\n    return {_CALL_PRIVATE}", "services/graph_service.py", True),
        (f"def _apply_evidence(u):\n    return {_CALL_PRIVATE}", "services/graph_service.py", True),
        ("from services.graph_service import _apply_evidence", "routes/x.py", True),
        ("from services.graph_service import _apply_evidence as ae", "learning/x.py", True),
        (f"import services.graph_service as gs\ngs.{_CALL_PRIVATE}", "routes/x.py", True),
        ('getattr(gs, "_apply_evidence")(u)', "scripts/x.py", True),
        ("from services.graph_service import apply_graph_update", "routes/x.py", False),
        ('x = "_apply_evidence is private"', "routes/x.py", False),
    ],
)
def test_inv_01_private_writer_detector(source, rel, offends):
    """inv_01 pins write_state to the writer's functions, but _apply_evidence
    writes learner_state, graph_nodes and node_mastery_events without naming
    either, so it must be reachable only through apply_graph_update."""
    import test_learning_loop_invariants as inv

    assert bool(inv._private_writer_offenders(rel, source)) is offends


# ── grader_backend (reopened by PKG-05; spec §5, §13 A22) ─────────────────────


class TestGraderBackend:
    def test_field_defaults_to_none_and_accepts_only_the_four_backends(self):
        assert _ev().grader_backend is None
        for backend in ("deterministic", "gemini", "gemini_second", "jev"):
            assert _ev(grader_backend=backend).grader_backend == backend
        with pytest.raises(ValidationError):
            _ev(grader_backend="gpt")

    def test_evidence_row_journals_grader_backend_null_when_absent(self):
        _, mocks, _ = _apply(
            {
                "evidence": [
                    {
                        "node_id": "n1",
                        "channel": "free_response",
                        "correct": True,
                        "grader_backend": "gemini",
                    },
                    {"node_id": "n1", "channel": "mc", "correct": False},
                ]
            },
            edges=[],
        )
        first, second = _event_rows(mocks)
        assert first["grader_backend"] == "gemini"
        assert "grader_backend" in second and second["grader_backend"] is None


# ── the journal on an environment a migration has not reached (CodeRabbit PR #673) ──


def _apply_with_unknown_columns(unknown: set[str], payload=None, caplog=None, errors=()):
    """One evidence row whose node_mastery_events insert 400s (PGRST204) while it
    names any column in `unknown`, as PostgREST does before the migration that
    adds it is applied — naming the first one, as PostgREST does. `errors` are
    raised first, one per attempt. Returns (attempted rows, learner_state writes)."""
    from services.graph_service import apply_graph_update

    factory, mocks = _evidence_factory(NODES, [], ())
    attempts: list[dict] = []
    queued = list(errors)

    def _insert(row):
        attempts.append(dict(row))
        if queued:
            raise queued.pop(0)
        missing = sorted(unknown & set(row))
        if missing:
            raise RuntimeError(
                f"PGRST204 Could not find the '{missing[0]}' column of "
                "'node_mastery_events' in the schema cache"
            )
        return []

    factory("node_mastery_events").insert.side_effect = _insert
    clock = patch("services.graph_service.datetime", wraps=datetime)
    with (
        patch("services.graph_service.table", side_effect=factory),
        patch("learning.learner_state.table", side_effect=factory),
        patch("services.graph_service.touch_streak_safe"),
        patch("services.course_context_service.update_course_context"),
        patch("services.academics.user_offering_ids_for_course", return_value=[]),
        patch("services.achievement_service.check_achievements"),
        clock as fake_dt,
    ):
        fake_dt.now.return_value = NOW
        apply_graph_update(
            "u1",
            payload
            or {
                "evidence": [
                    {
                        "node_id": "n1",
                        "channel": "free_response",
                        "correct": True,
                        "grader_backend": "gemini",
                    }
                ]
            },
            course_id="c1",
        )
    return attempts, _state_writes(mocks)


class TestJournalBeforeAMigration:
    """A route that runs before 20260927182054_learning_mastery_event_seq.sql or
    20260927093149_learning_grader_backend.sql (or the older 20260814051517
    event_type migration) must still journal the evidence:
    learner_state and graph_nodes are already written when the journal insert
    runs, so a lost row is a silent gap in the replayable history."""

    def test_a_missing_grader_backend_column_keeps_the_row_and_its_event_type(self, caplog):
        from learning.evidence import EVIDENCE_EVENT_TYPE

        with caplog.at_level("WARNING", logger="services.graph_service"):
            attempts, writes = _apply_with_unknown_columns({"grader_backend"})
        assert len(writes) == 1  # learner_state was written before the journal
        assert [("grader_backend" in a, "event_type" in a) for a in attempts] == [
            (True, True),
            (False, True),
        ]
        landed = attempts[-1]
        assert landed["event_type"] == EVIDENCE_EVENT_TYPE and landed["channel"] == "free_response"
        assert landed["correct"] is True and landed["p_after"] > landed["p_before"]
        assert any(
            "grader_backend" in r.getMessage() and "20260927093149" in r.getMessage()
            for r in caplog.records
            if r.levelname == "WARNING"
        )

    def test_a_missing_evidence_seq_column_keeps_the_row_and_the_older_columns(self, caplog):
        """A36's evidence_seq (20260927182054) postdates the learner_state migration
        the evidence path needs, like grader_backend: a code-first deploy degrades
        the row to a NULL evidence_seq (as the migration's own header describes
        rows written before it) instead of losing it (a33 verification)."""
        with caplog.at_level("WARNING", logger="services.graph_service"):
            attempts, writes = _apply_with_unknown_columns({"evidence_seq"})
        assert len(writes) == 1
        assert [("evidence_seq" in a, "grader_backend" in a) for a in attempts] == [
            (True, True),
            (False, True),
        ]
        assert attempts[-1]["event_type"] and attempts[-1]["channel"] == "free_response"
        assert any("20260927182054" in r.getMessage() for r in caplog.records)

    def test_both_optional_columns_missing_still_lands_the_row(self):
        attempts, _ = _apply_with_unknown_columns({"grader_backend", "event_type"})
        assert len(attempts) == 3
        landed = attempts[-1]
        assert "grader_backend" not in landed and "event_type" not in landed
        # everything the PKG-03 migration added is kept: it is applied whenever
        # the evidence path runs at all (read_states needs learner_state first)
        assert {"channel", "correct", "weight", "p_before", "p_after", "reason"} <= set(landed)
        assert landed["reason"] == "evidence:free_response"

    def test_the_ladder_follows_migration_order_newest_first(self):
        """Each retry drops one more migration's columns, newest first. Migrations
        apply in timestamp order, so an environment that lacks a column also lacks
        every newer one: the ladder never drops a column the environment has."""
        from services.graph_service import _JOURNAL_OPTIONAL_COLUMNS

        migrations = [m for m, _ in _JOURNAL_OPTIONAL_COLUMNS]
        assert migrations == sorted(migrations, reverse=True)
        migrations_dir = Path(__file__).resolve().parents[1] / "db" / "migrations"
        assert set(migrations) <= {p.name for p in migrations_dir.glob("*.sql")}
        for migration, columns in _JOURNAL_OPTIONAL_COLUMNS:
            ddl = (migrations_dir / migration).read_text()
            for column in columns:
                assert re.search(rf"ADD COLUMN IF NOT EXISTS {column}\b", ddl), (migration, column)

    def test_only_the_column_the_error_names_is_dropped(self):
        """PostgREST names the unknown column; only that one is dropped, so a
        column the environment has is never lost to a rung it did not need."""
        attempts, _ = _apply_with_unknown_columns({"event_type"})
        assert [("grader_backend" in a, "event_type" in a) for a in attempts] == [
            (True, True),
            (True, False),
        ]

    def test_a_dead_journal_still_never_raises(self, caplog):
        with caplog.at_level("WARNING", logger="services.graph_service"):
            attempts, writes = _apply_with_unknown_columns(
                {"grader_backend", "event_type", "node_id"}
            )
        # event_type, then grader_backend, are named and dropped; node_id is no
        # optional column, so that error gets one unchanged retry and is logged
        assert [("grader_backend" in a, "event_type" in a) for a in attempts] == [
            (True, True),
            (True, False),
            (False, False),
            (False, False),
        ]
        assert len(writes) == 1
        [lost] = [r for r in caplog.records if "journal row is lost" in r.getMessage()]
        assert lost.levelname == "ERROR" and lost.exc_info and "node_id" in str(lost.exc_info[1])

    def test_every_retry_logs_the_error_it_follows(self, caplog):
        """A retry never hides the failure before it: each warning carries the
        exception, whatever the next attempt does."""
        with caplog.at_level("WARNING", logger="services.graph_service"):
            _apply_with_unknown_columns({"grader_backend"})
        [warning] = [r for r in caplog.records if r.levelname == "WARNING"]
        assert warning.exc_info and "PGRST204" in str(warning.exc_info[1])

    def test_a_check_violation_keeps_the_column_and_is_logged(self, caplog):
        """A non-schema error (a CHECK violation, a transient 5xx) never drops a
        column: the row is retried once unchanged and the error is logged — the
        constraint name mentions grader_backend, but it is not an unknown column."""
        violation = RuntimeError(
            '23514 new row for relation "node_mastery_events" violates check '
            'constraint "node_mastery_events_grader_backend_check"'
        )
        with caplog.at_level("WARNING", logger="services.graph_service"):
            attempts, _ = _apply_with_unknown_columns(set(), errors=[violation])
        assert [("grader_backend" in a, "event_type" in a) for a in attempts] == [
            (True, True),
            (True, True),
        ]
        [warning] = [r for r in caplog.records if r.levelname == "WARNING"]
        assert (
            warning.exc_info[1] is violation and "retrying once unchanged" in warning.getMessage()
        )

    def test_a_repeated_check_violation_loses_the_row_loudly(self, caplog):
        violation = RuntimeError(
            '23514 violates check constraint "node_mastery_events_grader_backend_check"'
        )
        with caplog.at_level("WARNING", logger="services.graph_service"):
            attempts, writes = _apply_with_unknown_columns(set(), errors=[violation, violation])
        assert len(attempts) == 2 and all("grader_backend" in a for a in attempts)
        assert len(writes) == 1  # learner_state was written before the journal
        [lost] = [r for r in caplog.records if r.levelname == "ERROR"]
        assert lost.exc_info[1] is violation and "journal row is lost" in lost.getMessage()

    def test_the_http_error_body_names_the_column(self):
        """db.connection raises httpx.HTTPStatusError, whose message omits the
        PostgREST body: the column name is read off the response body too."""
        import httpx

        request = httpx.Request("POST", "http://db/rest/v1/node_mastery_events")
        body = (
            '{"code":"PGRST204","message":"Could not find the \'grader_backend\' column of '
            "'node_mastery_events' in the schema cache\"}"
        )
        error = httpx.HTTPStatusError(
            "Client error '400 Bad Request'",
            request=request,
            response=httpx.Response(400, request=request, text=body),
        )
        attempts, _ = _apply_with_unknown_columns(set(), errors=[error])
        assert [("grader_backend" in a, "event_type" in a) for a in attempts] == [
            (True, True),
            (False, True),
        ]


# ── evidence_seq (reopened for the live sequence-test finding; spec §4, §13 A36) ──


class TestEvidenceSeq:
    """Every row one apply_graph_update call journals shares one created_at and
    has a random uuid id, so without evidence_seq nothing orders them for a
    replay: a 3-question quiz had to be re-ordered from its p_before → p_after
    links."""

    def test_a_three_evidence_flush_numbers_its_rows_along_the_p_chain(self):
        from types import SimpleNamespace

        from learning.evidence import flush_pending

        factory, mocks = _evidence_factory(NODES, [])
        deps = SimpleNamespace(
            user_id="u1",
            pending_evidence=[
                {"node_id": "n1", "channel": "mc", "correct": True},
                {"node_id": "n1", "channel": "mc", "correct": False},
                {"node_id": "n1", "channel": "free_response", "correct": True},
            ],
        )
        clock = patch("services.graph_service.datetime", wraps=datetime)
        with (
            patch("services.graph_service.table", side_effect=factory),
            patch("learning.learner_state.table", side_effect=factory),
            patch("services.graph_service.touch_streak_safe"),
            patch("services.course_context_service.update_course_context"),
            patch("services.academics.user_offering_ids_for_course", return_value=[]),
            patch("services.achievement_service.check_achievements"),
            clock as fake_dt,
        ):
            fake_dt.now.return_value = NOW
            flush_pending(deps, "c1")
        rows = _event_rows(mocks)
        assert [r["evidence_seq"] for r in rows] == [0, 1, 2]
        assert len({r["created_at"] for r in rows}) == 1, "the timestamp cannot order them"
        assert rows[0]["p_before"] == pytest.approx(BKT_L0)
        for earlier, later in zip(rows, rows[1:]):
            assert later["p_before"] == pytest.approx(earlier["p_after"])
        # Replaying in evidence_seq order reproduces every posterior.
        from learning import bkt

        p = rows[0]["p_before"]
        for row in sorted(rows, key=lambda r: r["evidence_seq"]):
            p = bkt.update(p, row["channel"], row["correct"], weight=row["weight"])
            assert p == pytest.approx(row["p_after"])

    def test_seq_follows_apply_order_across_nodes(self):
        _, mocks, _ = _apply(
            {
                "evidence": [
                    {"node_id": "n2", "channel": "mc", "correct": True},
                    {"node_id": "n1", "channel": "mc", "correct": False},
                    {"node_id": "n2", "channel": "mc", "correct": False},
                ]
            },
            edges=[],
        )
        rows = _event_rows(mocks)
        assert [(r["node_id"], r["evidence_seq"]) for r in rows] == [
            ("n2", 0),
            ("n1", 1),
            ("n2", 2),
        ]

    def test_skipped_evidence_takes_no_seq(self):
        _, mocks, _ = _apply(
            {
                "evidence": [
                    {"node_id": "ghost", "channel": "mc", "correct": True},
                    {"node_id": "n1", "channel": "mc", "correct": True},
                    {"node_id": "n1", "channel": "mc", "correct": False},
                ]
            },
            edges=[],
        )
        assert [r["evidence_seq"] for r in _event_rows(mocks)] == [0, 1]

    def test_each_call_starts_at_zero(self):
        payload = {"evidence": [{"node_id": "n1", "channel": "mc", "correct": True}]}
        first = [r["evidence_seq"] for r in _event_rows(_apply(payload, edges=[])[1])]
        second = [r["evidence_seq"] for r in _event_rows(_apply(payload, edges=[])[1])]
        assert first == second == [0]

    def test_propagation_writes_no_journal_row_and_takes_no_seq(self):
        _, mocks, _ = _apply(
            {
                "evidence": [
                    {"node_id": "n1", "channel": "free_response", "correct": True},
                    {"node_id": "n1", "channel": "mc", "correct": True},
                ]
            }
        )
        rows = _event_rows(mocks)
        assert [(r["node_id"], r["evidence_seq"]) for r in rows] == [("n1", 0), ("n1", 1)]

    def test_legacy_rows_never_carry_it(self):
        _, trace = _run_legacy(LEGACY_PAYLOAD)
        assert trace == LEGACY_TRACE
        payload = {
            **LEGACY_PAYLOAD,
            "evidence": [{"node_id": "n1", "channel": "mc", "correct": True}],
        }
        _, mocks, _ = _apply(payload, edges=[])
        # PKG-14b: no legacy journal row exists any more (updated_nodes is
        # gone, spec §11.2); the legacy trace carries no seq, the one evidence
        # row takes 0.
        (evidence_row,) = _event_rows(mocks)
        assert evidence_row["evidence_seq"] == 0


# ── PKG-10 post-hoc: the rule's verdict and the matched key ride the Evidence ──


def test_evidence_verdict_and_wrong_key_default_none():
    """PKG-10 post-hoc: two optional diagnosis fields; nothing existing changes."""
    from learning.evidence import Evidence

    e = Evidence(node_id="n1", channel="free_response", correct=False)
    assert e.verdict is None and e.wrong_key is None
    ok = Evidence(node_id="n1", channel="mc", correct=True, verdict="slip", wrong_key="k1")
    assert ok.verdict == "slip" and ok.wrong_key == "k1"


def test_evidence_verdict_is_one_of_the_rules_verdicts():
    """Spec §3.3's six verdicts plus `none` (PKG-10 Deviation): anything else is refused."""
    from learning.evidence import Evidence, MisconceptionVerdict

    assert set(get_args(MisconceptionVerdict)) == {
        "none",
        "unknown",
        "slip",
        "misconception",
        "gap",
        "not_known",
        "novice",
    }
    with pytest.raises(ValidationError):
        Evidence(node_id="n1", channel="mc", correct=False, verdict="confused")


def test_verdict_and_wrong_key_are_never_journaled():
    """Spec §4: no column carries them; the durable record is the misconceptions
    row. The evidence path validates them and journals its named columns only."""
    _, mocks, _ = _apply(
        {
            "evidence": [
                {
                    "node_id": "n1",
                    "channel": "free_response",
                    "correct": False,
                    "verdict": "misconception",
                    "wrong_key": "k1",
                }
            ]
        },
        edges=[],
    )
    [row] = _event_rows(mocks)
    assert "verdict" not in row and "wrong_key" not in row
