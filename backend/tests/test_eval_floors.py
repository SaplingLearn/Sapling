"""PKG-14 Task A7: eval floors are the minimum of N recordings (spec §13 A40
06(s)) — tests/evals/floors.py and the SAPLING_EVAL_RUNS_LOG run log."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

EVALS = Path(__file__).parent / "evals"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"_eval_{name}", EVALS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    saved = list(sys.path)
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.path[:] = saved
    return mod


# ── floors: the minimum of N recordings (A40 06(s)) ──────────────────────────


def _run(dataset, raised=False, mode="record", **scores):
    return {"dataset": dataset, "mode": mode, "raised": raised, "scores": scores}


def test_floor_is_the_minimum_per_evaluator():
    floors = _load("floors")
    runs = [_run("d", A=1.0, B=0.5), _run("d", A=0.75, B=1.0), _run("d", A=1.0, B=0.875)]
    assert floors.floor_of(runs) == {"A": 0.75, "B": 0.5}


def test_apply_floors_takes_the_last_n_recorded_runs_and_writes_routing():
    floors = _load("floors")
    log = [
        _run("d", A=0.1),  # older: outside the last 3
        _run("d", A=1.0),
        _run("d", mode="replay", A=0.0),  # a replay is not a recording
        _run("d", A=0.9, raised=True),
        _run("d", A=0.8),
        _run("other", A=0.0),
    ]
    out = floors.apply_floors({"keep": {"X": 1.0}}, log, ["d"], n=3, routing="d_routing")
    assert out["d"] == {"A": 0.8}
    assert out["keep"] == {"X": 1.0}
    assert out["d_routing"]["runs"] == 3
    assert out["d_routing"]["d"] == [
        {"A": 1.0, "_raised": False},
        {"A": 0.9, "_raised": True},
        {"A": 0.8, "_raised": False},
    ]


def test_apply_floors_refuses_too_few_runs_or_mismatched_evaluators():
    floors = _load("floors")
    with pytest.raises(ValueError):
        floors.apply_floors({}, [_run("d", A=1.0)] * 2, ["d"], n=3, routing=None)
    with pytest.raises(ValueError):
        floors.apply_floors(
            {}, [_run("d", A=1.0), _run("d", B=1.0), _run("d", A=1.0)], ["d"], n=3, routing=None
        )


def test_floors_cli_refuses_fewer_than_three_runs(tmp_path):
    floors = _load("floors")
    log = tmp_path / "runs.jsonl"
    log.write_text("")
    assert floors.main(["--log", str(log), "--runs", "2", "--datasets", "d"]) == 2


def test_runs_log_appends_one_line_per_evaluated_dataset(tmp_path, monkeypatch):
    replay = _load("_replay")
    log = tmp_path / "runs.jsonl"
    monkeypatch.setenv(replay.RUNS_LOG_ENV, str(log))
    replay._log_run("d", {"B": 0.5, "A": 1.0}, raised=False)
    replay._log_run("d", {"A": 0.25}, raised=True)
    lines = [json.loads(ln) for ln in log.read_text().splitlines()]
    assert lines[0] == {
        "dataset": "d",
        "mode": replay.MODE,
        "raised": False,
        "scores": {"A": 1.0, "B": 0.5},
    }
    assert lines[1]["raised"] is True


def test_runs_log_is_off_by_default(tmp_path, monkeypatch):
    replay = _load("_replay")
    monkeypatch.delenv(replay.RUNS_LOG_ENV, raising=False)
    monkeypatch.chdir(tmp_path)
    replay._log_run("d", {"A": 1.0}, raised=False)
    assert list(tmp_path.iterdir()) == []
