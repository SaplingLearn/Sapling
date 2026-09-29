"""PKG-14: within-student arms are plumbing — NULL arm means variant A everywhere.

Spec §4 (`user_settings.loop_arm`), §10 rung 2, §13 A8 (`zpd.step.variant`),
A20 (arm sessions are exempt from tier downgrades and pause at hard).
"""

from __future__ import annotations

import pathlib
import re
from collections import Counter
from unittest.mock import MagicMock, patch

import pytest

from learning import params
from tests import test_learn_loop_routes as _routes
from tests.test_learn_loop_routes import _answer, _feedback_agent, client

# the route suite's fixtures (no_rate_limit is autouse there, so here too)
gate_on, no_rate_limit, seams = _routes.gate_on, _routes.no_rate_limit, _routes.seams

MIG_DIR = pathlib.Path(__file__).resolve().parents[1] / "db" / "migrations"


def test_migration_adds_nullable_loop_arm():
    hits = sorted(MIG_DIR.glob("*_learning_loop_arm.sql"))
    assert len(hits) == 1, hits
    assert re.match(r"^\d{14}_learning_loop_arm\.sql$", hits[0].name)
    sql = hits[0].read_text()
    assert re.search(r"ADD COLUMN IF NOT EXISTS loop_arm text\s*;", sql)
    assert "NOT NULL" not in sql


def test_null_arm_is_always_a():
    from learning.arms import variant_for

    for node in ("n1", "n2", "n3", "n4"):
        assert variant_for("u", node, None) == "A"
        assert variant_for("u", node, "") == "A"


def test_arm_randomises_within_student_and_is_stable():
    from learning.arms import variant_for

    nodes = [f"node-{i}" for i in range(200)]
    first = [variant_for("student", n, "exp1") for n in nodes]
    again = [variant_for("student", n, "exp1") for n in nodes]
    assert first == again
    counts = Counter(first)
    assert 60 <= counts["A"] <= 140 and 60 <= counts["B"] <= 140, counts
    assert [variant_for("student", n, "exp2") for n in nodes] != first


def test_variant_b_changes_only_the_non_novice_gate():
    from learning.policy import independent_min_s

    assert independent_min_s("develop", "A") == params.GATE_INDEPENDENT_MIN_S
    assert independent_min_s("profic", "A") == params.GATE_INDEPENDENT_MIN_S
    assert independent_min_s("develop", "B") == params.GATE_INDEPENDENT_MIN_S_VARIANT_B
    assert independent_min_s("profic", "B") == params.GATE_INDEPENDENT_MIN_S_VARIANT_B
    assert independent_min_s("novice", "A") == params.GATE_INDEPENDENT_MIN_S_NOVICE
    assert independent_min_s("novice", "B") == params.GATE_INDEPENDENT_MIN_S_NOVICE


def test_independent_min_s_refuses_an_unknown_variant():
    from learning.policy import independent_min_s

    with pytest.raises(ValueError):
        independent_min_s("develop", "C")


def test_genuine_attempt_reads_the_variant_threshold():
    """The one reader of the independent-time threshold (learning.gates) goes
    through policy.independent_min_s: 60 s is genuine for variant A (45 s) and
    not for variant B (90 s) on a develop concept; novice is 90 s for both."""
    from learning import gates

    def genuine(seconds, band, variant):
        return gates.is_genuine_attempt(40, False, False, seconds, band, variant=variant)

    between = (params.GATE_INDEPENDENT_MIN_S + params.GATE_INDEPENDENT_MIN_S_VARIANT_B) / 2
    assert genuine(between, "develop", "A") is True
    assert genuine(between, "develop", "B") is False
    assert genuine(params.GATE_INDEPENDENT_MIN_S_VARIANT_B, "develop", "B") is True
    assert genuine(between, "novice", "A") is genuine(between, "novice", "B")
    # the default is variant A: unchanged behaviour for every existing caller
    assert gates.is_genuine_attempt(40, False, False, between, "develop") is True
    # A5 time scale still applies to the variant threshold
    assert (
        gates.is_genuine_attempt(
            40, False, False, between * 0.01, "develop", variant="B", time_scale=0.01
        )
        is False
    )


def test_loop_arm_is_in_no_settings_api_field():
    """CONTINUE §4.4 (PKG-14 note) over the prompt's "readable in the settings
    GET": the A31 reason — a settings select naming a column breaks settings
    GET/PATCH for every student when code deploys before its migration. The
    arm is the series owner's, set by SQL, and only the loop routes read it."""
    import inspect

    from models import SettingsResponse, UpdateSettingsBody
    from routes import profile

    assert "loop_arm" not in profile._SETTINGS_COLS
    assert "loop_arm" not in inspect.getsource(profile)
    assert "loop_arm" not in SettingsResponse.model_fields
    assert "loop_arm" not in UpdateSettingsBody.model_fields


@pytest.mark.parametrize(
    "raw,expected", [(None, None), ("", None), ("exp1", "exp1"), (7, None), (True, None)]
)
def test_loop_arm_read_takes_only_a_string(raw, expected):
    """The arm is a label: anything but a non-empty string is no arm (variant A,
    no exemption) — never a truthy non-string turned into an arm session."""
    from routes import learn_loop

    handle = MagicMock()
    handle.select.return_value = [{"loop_arm": raw}]
    with patch("routes.learn_loop.table", return_value=handle) as tbl:
        assert learn_loop._loop_arm("u1") == expected
    tbl.assert_called_once_with("user_settings")
    assert handle.select.call_args.args[0] == "loop_arm"
    assert handle.select.call_args.kwargs["filters"] == {"user_id": "eq.u1"}


def test_loop_arm_read_error_is_no_arm():
    from routes import learn_loop

    handle = MagicMock()
    handle.select.side_effect = RuntimeError("postgrest down")
    with patch("routes.learn_loop.table", return_value=handle):
        assert learn_loop._loop_arm("u1") is None


# ── the route: arm_session and variant ───────────────────────────────────────


@pytest.fixture
def settings_row():
    return {"user_id": "u1", "loop_arm": None}


@pytest.fixture
def arm_reads(settings_row):
    """routes.learn_loop.table serving the user_settings row; counts the reads."""
    reads = []

    def _table(name):
        handle = MagicMock()
        if name == "user_settings":

            def _select(cols, **kw):
                reads.append((cols, kw))
                return [dict(settings_row)]

            handle.select.side_effect = _select
        else:
            handle.select.return_value = []
        return handle

    with patch("routes.learn_loop.table", side_effect=_table):
        yield reads


@pytest.fixture
def budget_calls(seams):
    return seams.ai_budget.check


@pytest.fixture
def tier_calls(seams):
    return seams.model_tier


@pytest.fixture
def run_check_answer(gate_on, seams, arm_reads):
    def _run():
        agent_p, usage_p, _ = _feedback_agent()
        with agent_p, usage_p:
            r = client.post("/api/learn/loop/check/answer", json=_answer(answer="n == 0 returns 1"))
        assert r.status_code == 200, r.text
        return r.json()

    return _run


@pytest.mark.parametrize("arm,expected", [(None, False), ("", False), ("exp1", True)])
def test_arm_session_follows_loop_arm(
    arm, expected, settings_row, budget_calls, tier_calls, run_check_answer, arm_reads
):
    """Spec §3.5/§13 A20: arm sessions are exempt from tier downgrades and pause at hard."""
    settings_row["loop_arm"] = arm
    run_check_answer()
    tutor = [c for c in budget_calls.call_args_list if c.args[1] == "tutor"]
    assert tutor and all(c.kwargs["arm_session"] is expected for c in tutor)
    assert tier_calls.call_args_list and all(
        c.kwargs["arm_session"] is expected for c in tier_calls.call_args_list
    )
    assert len(arm_reads) == 1, "loop_arm is read once per request"


@pytest.mark.parametrize("arm", [None, "exp1", "exp2"])
def test_zpd_step_carries_the_concepts_variant(arm, settings_row, seams, run_check_answer):
    from learning.arms import variant_for

    settings_row["loop_arm"] = arm
    run_check_answer()
    step = seams.zpd.emit_zpd_step.call_args.kwargs
    assert step["variant"] == variant_for("u1", "node-1", arm)
    if arm is None:
        assert step["variant"] == "A"


def test_zpd_step_payload_carries_variant_when_given():
    from learning import zpd_events
    from learning.ladder import Rung

    captured = []
    kwargs = dict(
        user_id="u1",
        request_id="r1",
        concept_id="n1",
        question_hash="q1",
        phase="check",
        channel="free_response",
        band="develop",
        ceiling=Rung.H3,
        ceiling_reason="develop",
        first_attempt_correct=True,
        n_attempts=1,
        max_rung_used=Rung.H0,
        rungs=[],
        time_to_first_attempt_ms=None,
        time_to_correct_ms=None,
        independent_time_ms=None,
        assisted=False,
        confidence=None,
        fsrs_rating=3,
        p_known_before=0.3,
        p_known_after=0.5,
        r_before=None,
        item_difficulty=2,
    )
    with patch.object(zpd_events, "log_event", lambda et, **kw: captured.append(kw["payload"])):
        zpd_events.emit_zpd_step(**kwargs, variant="B")
        zpd_events.emit_zpd_step(**kwargs)
    assert captured[0]["variant"] == "B"
    assert "variant" not in captured[1], "omitted when unknown, never guessed"
