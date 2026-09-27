"""PKG-03: Evidence model + weights (spec §3.1, §5), learner_state access,
and apply_graph_update's evidence path (spec §5). Mocks follow
tests/test_graph_service.py::_bulk_factory."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
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
    "updated_nodes": [
        {
            "concept_name": "recursion",
            "mastery_delta": 0.1,
            "reason": "Quiz: 3/3 correct",
            "event_type": "quiz_correct",
        },
    ],
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
        "graph_nodes",
        "update",
        [
            {
                "mastery_score": 0.6,
                "mastery_tier": "learning",
                "times_studied": 2,
                "last_studied_at": "<TS>",
            }
        ],
        {"filters": {"id": "eq.n1"}},
    ),
    (
        "node_mastery_events",
        "insert",
        [
            {
                "id": "<UUID>",
                "node_id": "n1",
                "delta": 0.1,
                "reason": "Quiz: 3/3 correct",
                "created_at": "<TS>",
                "event_type": "quiz_correct",
            }
        ],
        {},
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
    makes exactly these table calls, in this order, with these arguments."""
    result, trace = _run_legacy(LEGACY_PAYLOAD)
    assert result == [{"concept": "Recursion", "before": 0.5, "after": 0.6}]
    assert trace == LEGACY_TRACE


@pytest.mark.parametrize("evidence_value", [None, []])
def test_empty_evidence_key_is_the_legacy_path(evidence_value):
    result, trace = _run_legacy({**LEGACY_PAYLOAD, "evidence": evidence_value})
    assert result == [{"concept": "Recursion", "before": 0.5, "after": 0.6}]
    assert trace == LEGACY_TRACE
