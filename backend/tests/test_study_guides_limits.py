"""`services.study_guides.limits`: the three hourly limits, their overrides
from the environment, and a charge against one."""
from __future__ import annotations

import asyncio
import importlib

import pytest

from services import request_limits
from services.study_guides import limits
from services.study_guides.errors import GuideRateLimited

ME = "user_limits_me"
NAMES = {
    "STUDY_GUIDE_GENERATE_LIMIT": ("STUDY_GUIDE_GENERATE_RATE_LIMIT", 20),
    "STUDY_GUIDE_BLOCK_LIMIT": ("STUDY_GUIDE_BLOCK_RATE_LIMIT", 40),
    "STUDY_GUIDE_CREATE_LIMIT": ("STUDY_GUIDE_CREATE_RATE_LIMIT", 60),
}


@pytest.fixture
def reloaded(monkeypatch):
    """Re-import the module against the environment a test set. `reload`
    changes the module in place, so it is read again once the test's
    environment is undone."""
    yield lambda: importlib.reload(limits)
    monkeypatch.undo()
    importlib.reload(limits)


@pytest.fixture
def per_process(monkeypatch):
    async def stateless():
        return False

    monkeypatch.setattr(request_limits, "_astateless", stateless)
    monkeypatch.setattr(request_limits, "_rate_state", {})


def test_the_shipped_limits(monkeypatch, reloaded):
    for variable, _ in NAMES.values():
        monkeypatch.delenv(variable, raising=False)

    module = reloaded()

    assert {name: getattr(module, name) for name in NAMES} == {
        name: default for name, (_, default) in NAMES.items()
    }
    assert module.RATE_WINDOW_S == 3600


def test_each_limit_has_its_own_override(monkeypatch, reloaded):
    for number, (variable, _) in enumerate(NAMES.values(), start=1):
        monkeypatch.setenv(variable, str(1000 * number))

    module = reloaded()

    assert [getattr(module, name) for name in NAMES] == [1000, 2000, 3000]


@pytest.mark.parametrize("junk", ["", "   ", "twenty", "0", "-5", "3.5"])
def test_a_junk_override_falls_back_to_the_shipped_limit(monkeypatch, reloaded, junk):
    """A stray value must neither switch a limit off nor stop the app from
    starting."""
    for variable, _ in NAMES.values():
        monkeypatch.setenv(variable, junk)

    module = reloaded()

    assert [getattr(module, name) for name in NAMES] == [20, 40, 60]


def test_a_charge_counts_per_student_and_action_and_can_be_given_back(per_process):
    async def scenario():
        first = await limits.acharge(ME, action="create", limit=2)
        await limits.acharge(ME, action="create", limit=2)
        with pytest.raises(GuideRateLimited) as limited:
            await limits.acharge(ME, action="create", limit=2)
        # Another action and another student have budgets of their own.
        await limits.acharge(ME, action="generate", limit=1)
        await limits.acharge("user_limits_other", action="create", limit=1)
        first.refund()
        await limits.acharge(ME, action="create", limit=2)
        return limited.value

    limited = asyncio.run(scenario())

    assert (limited.status_code, limited.detail) == (429, limits.RATE_LIMITED_DETAIL)
    assert len(request_limits._rate_state[f"study-guide-create:{ME}"]) == 2
