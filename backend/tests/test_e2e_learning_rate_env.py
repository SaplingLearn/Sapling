"""Run canonical E2E mode setup without starting servers, DBs, or models."""
from __future__ import annotations

import os
from pathlib import Path
import shlex
import subprocess
import sys

import pytest
import services.loop.planning

REPO = Path(__file__).resolve().parents[2]
BACKEND = REPO / "backend"


def _configured_rate(mode: str, explicit: str | None, variable: str = "LEARN_RATE_LIMIT_PER_MIN") -> int:
    source = (REPO / "scripts/e2e-up.sh").read_text()
    # Execute the actual isolated mode-selection block, not a second copy of
    # its defaults. Stop before the first stack-side-effect command.
    start = source.index('if [ "$MODEL_MODE" = "function" ]; then')
    end = source.index("\nfi", start) + len("\nfi")
    setup = source[start:end]
    env = os.environ.copy()
    env.pop("LEARN_RATE_LIMIT_PER_MIN", None)
    env.pop("LOOP_PROBE_PLAN_READS_PER_MIN", None)
    env.update(MODEL_MODE=mode, SAPLING_MODEL_MODE=mode, APP_ENV="production")
    if explicit is not None:
        env[variable] = explicit
    probe = (
        "import dotenv; dotenv.load_dotenv = lambda *a, **k: False; "
        f"import config; print(getattr(config, {variable!r}))"
    )
    result = subprocess.run(
        ["bash", "-eu", "-c", setup + "\n" + shlex.join([sys.executable, "-c", probe])],
        cwd=BACKEND, env=env, capture_output=True, text=True, check=True,
    )
    return int(result.stdout.strip())


@pytest.mark.parametrize(
    "mode,explicit,expected",
    [
        ("function", None, 1000),  # the scripted lane's burst allowance
        ("real", None, 20),  # every other mode keeps config.py's default
        ("function", "0", 0),  # an explicit caller cap wins, even 0
    ],
)
def test_only_function_lane_defaults_to_relaxed_burst_cap(mode, explicit, expected):
    assert _configured_rate(mode, explicit) == expected


@pytest.mark.parametrize(
    "mode,explicit,expected",
    [
        ("function", None, 1000),  # the scripted lane relaxes it
        ("function", "7", 7),  # an explicit positive cap wins
        ("function", "0", 30),  # <= 0 keeps the guard on (the policy default)
        ("function", "invalid", 30),  # so does a value that is not an integer
    ],
)
def test_probe_plan_guard_only_relaxes_in_scripted_lane(mode, explicit, expected):
    assert _configured_rate(mode, explicit, "LOOP_PROBE_PLAN_READS_PER_MIN") == expected


def test_probe_plan_config_default_is_the_named_policy():
    from learning.params import PROBE_PLAN_READS_PER_MIN

    assert _configured_rate("real", None, "LOOP_PROBE_PLAN_READS_PER_MIN") == PROBE_PLAN_READS_PER_MIN


def test_configured_probe_plan_guard_still_throttles_per_user(monkeypatch):
    import config
    from fastapi import HTTPException
    from services import request_limits

    monkeypatch.setattr(config, "LOOP_PROBE_PLAN_READS_PER_MIN", 2)
    monkeypatch.setattr(request_limits, "_rate_state", {})
    services.loop.planning._probe_plan_read_limit("diagnostic-user")
    services.loop.planning._probe_plan_read_limit("diagnostic-user")
    with pytest.raises(HTTPException) as raised:
        services.loop.planning._probe_plan_read_limit("diagnostic-user")
    assert raised.value.status_code == 429
    assert raised.value.detail == "too many requests"
    assert 1 <= int(raised.value.headers["Retry-After"]) <= 60
    services.loop.planning._probe_plan_read_limit("another-user")
