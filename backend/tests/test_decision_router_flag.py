"""#620: the decision_router flag picks the tutor router's backends."""
import asyncio
from unittest.mock import patch

import pytest

from services import decisions


@pytest.fixture(autouse=True)
def _real_mode(monkeypatch):
    monkeypatch.delenv("SAPLING_MODEL_MODE", raising=False)
    monkeypatch.delenv("SAPLING_DECISIONS_BACKEND", raising=False)
    monkeypatch.delenv("SAPLING_DECISIONS_SHADOW", raising=False)


@pytest.mark.parametrize("variant,expected", [
    ("off", (decisions.OFF, decisions.OFF)),
    ("jev", (decisions.JEV, decisions.OFF)),
    ("jev_shadow", (decisions.JEV, decisions.FLASH_LITE)),
])
def test_flag_variant_maps_to_backends(variant, expected):
    with patch("services.feature_flags.flag_variant", return_value=variant):
        assert decisions.router_backends("u1") == expected


def test_explicit_env_backend_wins_over_flag(monkeypatch):
    monkeypatch.setenv("SAPLING_DECISIONS_BACKEND", "flash_lite")
    with patch("services.feature_flags.flag_variant", return_value="jev") as fv:
        assert decisions.router_backends("u1") == (decisions.FLASH_LITE, decisions.OFF)
    fv.assert_not_called()


def test_function_mode_ignores_flag(monkeypatch):
    monkeypatch.setenv("SAPLING_MODEL_MODE", "function")
    with patch("services.feature_flags.flag_variant", return_value="off") as fv:
        assert decisions.router_backends("u1")[0] == decisions.FUNCTION
    fv.assert_not_called()


def test_router_skips_everything_when_flag_off():
    from services import tutor_router

    with patch("services.feature_flags.flag_variant", return_value="off"), \
         patch("services.tutor_router.build_state") as build:
        out = tutor_router.observe_tutor_turn(
            user_id="u1", session_id="s1", message="hi", history=[],
            mode="socratic", request_id="r1", model_pref_requested=None,
            model_tier="default", tutor_model="m",
        )
    assert out is None and not build.called


def test_decide_uses_explicit_overrides():
    q = [decisions.YesNo(key="k", instructions="?", default=False)]
    with patch("services.decisions._answer_with") as aw:
        aw.side_effect = Exception("stop")  # we only assert which backend was requested
        asyncio.run(decisions.decide("s", q, feature="t", backend=decisions.JEV, shadow=decisions.OFF))
    assert aw.call_args.args[0] == decisions.JEV  # decide() never raises (fails soft)
