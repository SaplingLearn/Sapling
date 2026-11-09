"""Run canonical E2E mode setup without starting servers, DBs, or models."""
from __future__ import annotations

import os
from pathlib import Path
import shlex
import subprocess
import sys

import pytest
import yaml

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
        ("function", None, 1000),
        ("real", None, 20),
        ("test", None, 20),
        ("function", "0", 0),
        ("function", "7", 7),
        ("real", "7", 7),
    ],
)
def test_only_function_lane_defaults_to_relaxed_burst_cap(mode, explicit, expected):
    assert _configured_rate(mode, explicit) == expected


def test_canonical_ci_exposes_burst_override_and_uploads_hidden_logs():
    workflow = yaml.safe_load((REPO / ".github/workflows/e2e.yml").read_text())
    steps = workflow["jobs"]["e2e"]["steps"]
    boot = next(step for step in steps if step.get("run") == "make e2e-up")
    assert boot["env"]["SAPLING_MODEL_MODE"] == "function"
    assert boot["env"]["LEARNING_GATE_TIME_SCALE"] == "0.01"
    assert boot["env"]["LEARN_RATE_LIMIT_PER_MIN"] == "1000"
    upload = next(step for step in steps if step.get("uses", "").startswith("actions/upload-artifact@"))
    assert upload["with"]["include-hidden-files"] is True
    assert ".e2e/*.log" in upload["with"]["path"].splitlines()


@pytest.mark.parametrize(
    "mode,explicit,expected",
    [
        ("function", None, 1000),
        ("real", None, 30),
        ("test", None, 30),
        ("function", "7", 7),
        ("real", "7", 7),
        ("function", "0", 30),
        ("function", "-1", 30),
        ("function", "invalid", 30),
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
    from routes import learn_loop
    from services import request_limits

    monkeypatch.setattr(config, "LOOP_PROBE_PLAN_READS_PER_MIN", 2)
    monkeypatch.setattr(request_limits, "_rate_state", {})
    learn_loop._probe_plan_read_limit("diagnostic-user")
    learn_loop._probe_plan_read_limit("diagnostic-user")
    with pytest.raises(HTTPException) as raised:
        learn_loop._probe_plan_read_limit("diagnostic-user")
    assert raised.value.status_code == 429
    assert raised.value.detail == "too many requests"
    assert 1 <= int(raised.value.headers["Retry-After"]) <= 60
    learn_loop._probe_plan_read_limit("another-user")
