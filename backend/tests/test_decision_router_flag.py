"""#620/#672: the decision_router flag picks the tutor router's backends."""
import asyncio
from unittest.mock import patch

import pytest

from services import decisions


@pytest.fixture(autouse=True)
def _real_mode(monkeypatch):
    monkeypatch.delenv("SAPLING_MODEL_MODE", raising=False)
    monkeypatch.delenv("SAPLING_FLAG_DECISION_ROUTER", raising=False)


@pytest.mark.parametrize("variant,expected", [
    ("off", (decisions.OFF, decisions.OFF)),
    ("jev", (decisions.JEV, decisions.OFF)),
    ("jev_shadow", (decisions.JEV, decisions.FLASH_LITE)),
])
def test_flag_variant_maps_to_backends(variant, expected):
    with patch("services.feature_flags.flag_variant", return_value=variant):
        assert decisions.router_backends("u1") == expected


def test_the_flag_is_resolved_for_the_turns_student():
    with patch("services.feature_flags.flag_variant", return_value="off") as fv:
        decisions.router_backends("u-42")
    fv.assert_called_once_with("decision_router", "u-42")


def test_env_override_is_the_kill_switch(monkeypatch):
    """No bespoke env var: the generic SAPLING_FLAG_<KEY> override wins over
    any stored rule, so `off` there stops the router everywhere."""
    monkeypatch.setenv("SAPLING_FLAG_DECISION_ROUTER", "off")
    assert decisions.router_backends("u1") == (decisions.OFF, decisions.OFF)
    monkeypatch.setenv("SAPLING_FLAG_DECISION_ROUTER", "jev_shadow")
    assert decisions.router_backends("u1") == (decisions.JEV, decisions.FLASH_LITE)


@pytest.mark.parametrize("variant", ["jev", "jev_shadow"])
def test_function_mode_runs_any_on_variant_as_function_without_a_shadow(monkeypatch, variant):
    monkeypatch.setenv("SAPLING_MODEL_MODE", "function")
    with patch("services.feature_flags.flag_variant", return_value=variant):
        assert decisions.router_backends("u1") == (decisions.FUNCTION, decisions.OFF)


def test_function_mode_respects_an_off_flag(monkeypatch):
    monkeypatch.setenv("SAPLING_MODEL_MODE", "function")
    with patch("services.feature_flags.flag_variant", return_value="off"):
        assert decisions.router_backends("u1") == (decisions.OFF, decisions.OFF)


def test_router_skips_everything_when_flag_off():
    from services import tutor_router

    async def run():
        task = tutor_router.observe_tutor_turn(
            user_id="u1", session_id="s1", message="hi", history=[],
            mode="socratic", request_id="r1", model_pref_requested=None,
            model_tier="default", tutor_model="m",
        )
        return await task

    with patch("services.feature_flags.flag_variant", return_value="off"), \
         patch("services.tutor_router._route") as route:
        assert asyncio.run(run()) is None
    assert not route.called


def test_decide_uses_the_backend_it_is_given():
    q = [decisions.YesNo(key="k", instructions="?", default=False)]
    with patch("services.decisions._answer_with") as aw:
        aw.side_effect = Exception("stop")  # we only assert which backend was requested
        asyncio.run(decisions.decide("s", q, feature="t", backend=decisions.JEV,
                                     shadow=decisions.OFF))
    assert aw.call_args.args[0] == decisions.JEV  # decide() never raises (fails soft)
