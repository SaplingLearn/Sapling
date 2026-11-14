"""The tutor's per-student cost guard (services/tutor/limits.py).

Every other model-spending feature had a rate limit; the tutor did not — and
`agents/_providers.py` puts the tutor on the most expensive slot. The other
half of the guard, the per-user daily token budget in
`services/llm_budget.py`, is behind a feature flag whose first (default)
variant is "off", so with the flag off nothing stood between a signed-in
account and an unbounded number of model calls.

Driven with `asyncio.run`: this suite has no pytest-asyncio plugin, so an
`async def test_` would be collected and silently skipped rather than run.
"""

import asyncio

import pytest
from fastapi import HTTPException

from services.tutor import limits


def _run(coro):
    return asyncio.run(coro)


class TestEnforceTurnLimit:
    @pytest.fixture(autouse=True)
    def _small_window(self, monkeypatch):
        """A small window, so these do not depend on the shipped numbers
        (which TestShippedDefaults pins separately)."""
        monkeypatch.setattr(limits, "TUTOR_TURN_RATE_LIMIT", 3)
        monkeypatch.setattr(limits, "TUTOR_TURN_RATE_WINDOW_SEC", 60)

    def test_allows_turns_up_to_the_limit(self, monkeypatch):
        calls = []

        async def fake_check(key, *, limit, window_sec, memory_only=False):
            calls.append((key, limit, window_sec, memory_only))
            return None

        monkeypatch.setattr(limits, "acheck_rate_limit", fake_check)
        for _ in range(3):
            _run(limits.enforce_turn_limit("u1"))
        assert len(calls) == 3
        # Keyed per student: one caller cannot spend another's budget.
        assert calls[0][0] == "tutor_turn:u1"
        assert calls[0][1] == 3
        # No feature-flag read on the tutor's hot path (see limits.py).
        assert calls[0][3] is True

    def test_raises_429_with_retry_after(self, monkeypatch):
        async def fake_check(key, *, limit, window_sec, memory_only=False):
            return 42

        monkeypatch.setattr(limits, "acheck_rate_limit", fake_check)
        with pytest.raises(HTTPException) as exc:
            _run(limits.enforce_turn_limit("u1"))
        assert exc.value.status_code == 429
        assert exc.value.headers["Retry-After"] == "42"

    def test_the_real_limiter_refuses_past_the_window(self):
        """End-to-end against the actual limiter, not a fake."""
        user = "limit-probe-user"
        for _ in range(3):
            _run(limits.enforce_turn_limit(user))
        with pytest.raises(HTTPException) as exc:
            _run(limits.enforce_turn_limit(user))
        assert exc.value.status_code == 429

    def test_one_student_cannot_exhaust_anothers_budget(self):
        for _ in range(3):
            _run(limits.enforce_turn_limit("noisy-student"))
        # A different student is unaffected: the key carries the user id.
        _run(limits.enforce_turn_limit("quiet-student"))


class TestShippedDefaults:
    """A cost guard that interrupts real studying is a worse bug than the one
    it prevents, so pin that the shipped limit stays well above an intense
    human session."""

    def test_the_default_is_generous(self):
        assert limits.TUTOR_TURN_RATE_LIMIT >= 100
        assert limits.TUTOR_TURN_RATE_WINDOW_SEC <= 3600

    def test_env_override_ignores_a_bad_value(self):
        assert limits._positive_int_env("NO_SUCH_ENV_VAR_HERE", 120) == 120

    def test_env_override_accepts_a_good_value(self, monkeypatch):
        monkeypatch.setenv("TUTOR_TURN_RATE_LIMIT", "not-a-number")
        assert limits._positive_int_env("TUTOR_TURN_RATE_LIMIT", 120) == 120
        monkeypatch.setenv("TUTOR_TURN_RATE_LIMIT", "0")
        assert limits._positive_int_env("TUTOR_TURN_RATE_LIMIT", 120) == 120
        monkeypatch.setenv("TUTOR_TURN_RATE_LIMIT", "25")
        assert limits._positive_int_env("TUTOR_TURN_RATE_LIMIT", 120) == 25


class TestEveryTurnEntryPointIsGuarded:
    """The limit is only real if every path that starts a model run calls it.
    Pins the wiring so a new turn endpoint cannot quietly skip the guard."""

    def test_all_five_entry_points_enforce(self):
        import inspect

        from services.tutor import streams, turns

        for mod, names in ((turns, ("start_session", "chat", "action")),
                           (streams, ("chat_stream", "start_session_stream"))):
            for name in names:
                src = inspect.getsource(getattr(mod, name))
                assert "enforce_turn_limit" in src, f"{mod.__name__}.{name} is unguarded"
