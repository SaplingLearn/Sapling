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


_ID = {"model": "m-1", "prompt_hash": "p-1", "schema_hash": "s-1"}


def _run(dataset, raised=False, mode="record", recorded_under=_ID, **scores):
    line = {"dataset": dataset, "mode": mode, "raised": raised, "scores": scores}
    if recorded_under is not None:
        line["recorded_under"] = recorded_under
    return line


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
    assert out["d_routing"]["recorded_under"] == {"d": _ID}


def test_apply_floors_refuses_routing_runs_of_other_prompts_or_with_no_identity():
    """D6: a routing block names the model and prompt hash its runs were
    recorded under, so runs of two prompts (or of unknown ones) never share one."""
    floors = _load("floors")
    other = {**_ID, "prompt_hash": "p-2"}
    mixed = [_run("d", A=1.0), _run("d", A=1.0, recorded_under=other), _run("d", A=1.0)]
    with pytest.raises(ValueError, match="different prompts"):
        floors.apply_floors({}, mixed, ["d"], n=3, routing="d_routing")
    bare = [_run("d", A=1.0, recorded_under=None)] * 3
    with pytest.raises(ValueError, match="recorded_under"):
        floors.apply_floors({}, bare, ["d"], n=3, routing="d_routing")
    # a floor alone (no routing) needs no identity
    assert floors.apply_floors({}, bare, ["d"], n=3, routing=None)["d"] == {"A": 1.0}


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
    replay._log_run("d", {"A": 1.0}, raised=False, recorded_under=_ID)
    assert json.loads(log.read_text().splitlines()[2])["recorded_under"] == _ID


def test_runs_log_is_off_by_default(tmp_path, monkeypatch):
    replay = _load("_replay")
    monkeypatch.delenv(replay.RUNS_LOG_ENV, raising=False)
    monkeypatch.chdir(tmp_path)
    replay._log_run("d", {"A": 1.0}, raised=False)
    assert list(tmp_path.iterdir()) == []


# ── D10: every committed floor is the minimum of its recorded runs ───────────


def test_committed_floors_are_the_minimum_of_their_recorded_runs():
    """baselines.json as committed: a routed dataset's floor is the minimum of
    its routing block's runs, a logged dataset's the minimum of its newest run
    log's last three, and any other floor is a named single-recording one."""
    floors = _load("floors")
    assert floors.floor_problems(floors._load_baselines()) == []
    assert floors.main(["--check"]) == 0


def _block(runs, n=3, ident=_ID, name="d"):
    return {"runs": n, name: runs, "recorded_under": {name: ident}}


def test_floor_check_flags_a_floor_that_is_not_the_minimum(tmp_path):
    floors = _load("floors")
    runs = [{"A": 1.0, "_raised": False}, {"A": 0.5, "_raised": True}, {"A": 0.75, "_raised": False}]
    ok = {"d": {"A": 0.5}, "d_routing": _block(runs)}
    assert floors.floor_problems(ok, tmp_path) == []
    one_recording = {"d": {"A": 0.75}, "d_routing": _block(runs)}  # the last run's score
    assert any("not the minimum" in p for p in floors.floor_problems(one_recording, tmp_path))


def test_floor_check_reads_the_newest_run_log_and_refuses_unlogged_floors(tmp_path):
    floors = _load("floors")
    old = [_run("c", A=0.5)] * 3
    new = [_run("c", A=1.0), _run("c", A=0.75), _run("c", A=1.0)]
    (tmp_path / "c_2026-01-01.jsonl").write_text("\n".join(json.dumps(r) for r in old))
    (tmp_path / "c_2026-02-01.jsonl").write_text("\n".join(json.dumps(r) for r in new))
    assert floors.floor_problems({"c": {"A": 0.75}}, tmp_path) == []
    assert floors.floor_problems({"c": {"A": 0.5}}, tmp_path)  # the older log's
    assert any("no recorded runs" in p for p in floors.floor_problems({"z": {"A": 1.0}}, tmp_path))


def test_floor_check_flags_a_routing_block_without_identity_or_short_of_runs(tmp_path):
    floors = _load("floors")
    runs = [{"A": 1.0, "_raised": False}] * 3
    no_id = {"d": {"A": 1.0}, "d_routing": {"runs": 3, "d": runs}}
    assert any("recorded_under" in p for p in floors.floor_problems(no_id, tmp_path))
    short = {"d": {"A": 1.0}, "d_routing": _block(runs[:2], n=2)}
    assert any("< 3" in p for p in floors.floor_problems(short, tmp_path))
    twice = {"d": {"A": 1.0}, "a_routing": _block(runs), "b_routing": _block(runs)}
    assert any("two routing blocks" in p for p in floors.floor_problems(twice, tmp_path))


# ── D6: SAPLING_EVAL_UPDATE_BASELINES rewrites a routed floor with its block ──


def _replay_with(tmp_path, monkeypatch, baselines):
    replay = _load("_replay")
    path = tmp_path / "baselines.json"
    path.write_text(json.dumps(baselines))
    monkeypatch.setattr(replay, "BASELINES_PATH", path)
    return replay, path


def test_update_flow_rewrites_a_routed_floor_and_its_block_from_the_runs_log(
    tmp_path, monkeypatch
):
    old = {"d": {"A": 1.0}, "d_routing": _block([{"A": 1.0, "_raised": False}] * 3)}
    replay, path = _replay_with(tmp_path, monkeypatch, old)
    new_id = {**_ID, "prompt_hash": "p-new"}
    log = tmp_path / "runs.jsonl"
    log.write_text(
        "\n".join(json.dumps(_run("d", A=a, recorded_under=new_id)) for a in (1.0, 0.5, 0.75))
    )
    monkeypatch.setenv(replay.RUNS_LOG_ENV, str(log))
    assert replay._update_routed(json.loads(path.read_text()), "d", "d_routing") is True
    out = json.loads(path.read_text())
    assert out["d"] == {"A": 0.5}
    assert out["d_routing"]["recorded_under"]["d"] == new_id
    assert [r["A"] for r in out["d_routing"]["d"]] == [1.0, 0.5, 0.75]


def test_update_flow_refuses_a_routed_floor_from_one_run(tmp_path, monkeypatch):
    old = {"d": {"A": 1.0}, "d_routing": _block([{"A": 1.0, "_raised": False}] * 3)}
    replay, path = _replay_with(tmp_path, monkeypatch, old)
    log = tmp_path / "runs.jsonl"
    log.write_text(json.dumps(_run("d", A=0.25)))
    monkeypatch.setenv(replay.RUNS_LOG_ENV, str(log))
    assert replay._update_routed(json.loads(path.read_text()), "d", "d_routing") is False
    assert json.loads(path.read_text()) == old
    assert replay._routing_block_of(old, "d") == "d_routing"
    assert replay._routing_block_of(old, "other") is None


def test_update_flow_refuses_runs_recorded_under_another_prompt(tmp_path, monkeypatch):
    """Three runs of an OLD prompt never become the floor of what the dataset
    records under today."""
    old = {"d": {"A": 1.0}, "d_routing": _block([{"A": 1.0, "_raised": False}] * 3)}
    replay, path = _replay_with(tmp_path, monkeypatch, old)
    log = tmp_path / "runs.jsonl"
    log.write_text("\n".join(json.dumps(_run("d", A=0.5)) for _ in range(3)))  # under _ID
    monkeypatch.setenv(replay.RUNS_LOG_ENV, str(log))
    now = {**_ID, "prompt_hash": "p-today"}
    assert replay._update_routed(json.loads(path.read_text()), "d", "d_routing", now) is False
    assert json.loads(path.read_text()) == old
    assert replay._update_routed(json.loads(path.read_text()), "d", "d_routing", dict(_ID)) is True
