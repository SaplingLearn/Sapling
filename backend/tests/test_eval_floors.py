"""PKG-14 Task A7: eval floors are the minimum of N recordings (spec §13 A40
06(s)) — tests/evals/floors.py and the SAPLING_EVAL_RUNS_LOG run log."""

from __future__ import annotations

import importlib
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
        _run("d", A=0.9),
        _run("d", A=0.8),
        _run("other", A=0.0),
    ]
    out = floors.apply_floors({"keep": {"X": 1.0}}, log, ["d"], n=3, routing="d_routing")
    assert out["d"] == {"A": 0.8}
    assert out["keep"] == {"X": 1.0}
    assert out["d_routing"]["runs"] == 3
    assert out["d_routing"]["d"] == [
        {"A": 1.0, "_raised": False},
        {"A": 0.9, "_raised": False},
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


@pytest.mark.parametrize("routing", [None, "d_routing"])
def test_apply_floors_refuses_a_raised_run(routing):
    """A raised run's scores average only the cases that finished, so it can
    read 1.0: no floor comes from one, routed or not. A raised run older than
    the last N backs nothing."""
    floors = _load("floors")
    log = [_run("d", A=1.0), _run("d", A=1.0, raised=True), _run("d", A=1.0)]
    with pytest.raises(ValueError, match="raised"):
        floors.apply_floors({}, log, ["d"], n=3, routing=routing)
    older = [_run("d", A=1.0, raised=True), *([_run("d", A=1.0)] * 3)]
    assert floors.apply_floors({}, older, ["d"], n=3, routing=routing)["d"] == {"A": 1.0}


@pytest.mark.parametrize("key", ["prompt_hash", "schema_hash", "model"])
def test_apply_floors_refuses_unrouted_runs_of_different_identities(key):
    """A dataset that routes nothing is held to one identity too (its runs log
    is appended to, so a stopped re-record leaves two prompts in the last N);
    a run that names none is not one that does."""
    floors = _load("floors")
    for odd in ({**_ID, key: "other"}, None):
        log = [_run("d", A=1.0), _run("d", A=1.0), _run("d", A=1.0, recorded_under=odd)]
        with pytest.raises(ValueError, match="different prompts or models"):
            floors.apply_floors({}, log, ["d"], n=3, routing=None)


def test_floors_cli_refuses_a_raised_run_and_writes_nothing(tmp_path, monkeypatch):
    floors = _load("floors")
    log = tmp_path / "runs.jsonl"
    log.write_text("\n".join(json.dumps(_run("d", A=1.0, raised=True)) for _ in range(3)))
    monkeypatch.setattr(floors, "_write_baselines", lambda _b: pytest.fail("wrote baselines"))
    assert floors.main(["--log", str(log), "--runs", "3", "--datasets", "d"]) == 2


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
    runs = [{"A": 1.0, "_raised": False}, {"A": 0.5, "_raised": False}, {"A": 0.75, "_raised": False}]
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
    today = {"c": _ID}
    assert floors.floor_problems({"c": {"A": 0.75}}, tmp_path, today) == []
    assert floors.floor_problems({"c": {"A": 0.5}}, tmp_path, today)  # the older log's
    assert any("no recorded runs" in p for p in floors.floor_problems({"z": {"A": 1.0}}, tmp_path))


def _commit_log(folder, *runs):
    (folder / "c_2026-02-01.jsonl").write_text("\n".join(json.dumps(r) for r in runs))


def test_floor_check_flags_a_raised_run(tmp_path):
    """--check: a floor backed by a raised run is a problem, in a run log or in
    a routing block, whatever the run scored."""
    floors = _load("floors")
    clean = _run("c", A=1.0)
    _commit_log(tmp_path, clean, _run("c", A=1.0, raised=True), clean)
    (problem,) = floors.floor_problems({"c": {"A": 1.0}}, tmp_path, {"c": _ID})
    assert "raised" in problem
    _commit_log(tmp_path, _run("c", A=1.0, raised=True), clean, clean, clean)  # not in the last 3
    assert floors.floor_problems({"c": {"A": 1.0}}, tmp_path, {"c": _ID}) == []
    runs = [{"A": 1.0, "_raised": i == 1} for i in range(3)]
    (problem,) = floors.floor_problems({"d": {"A": 1.0}, "d_routing": _block(runs)}, tmp_path)
    assert "raised" in problem


def test_floor_check_flags_a_run_log_of_mixed_identities(tmp_path):
    floors = _load("floors")
    run, other = _run("c", A=1.0), _run("c", A=1.0, recorded_under={**_ID, "prompt_hash": "p-2"})
    _commit_log(tmp_path, other, run, run)
    problems = floors.floor_problems({"c": {"A": 1.0}}, tmp_path, {"c": _ID})
    assert any("different prompts or models" in p for p in problems)


@pytest.mark.parametrize("key", ["prompt_hash", "schema_hash", "model"])
def test_floor_check_flags_a_run_log_recorded_under_another_identity(tmp_path, key):
    """--check: three runs of an OLD prompt are not evidence about the current
    one, whatever they scored; a log that names no identity is scored only, and
    one no eval module answers for fails closed."""
    floors = _load("floors")
    _commit_log(tmp_path, *[_run("c", A=1.0)] * 3)
    baselines = {"c": {"A": 1.0}}
    assert floors.floor_problems(baselines, tmp_path, {"c": dict(_ID)}) == []
    (problem,) = floors.floor_problems(baselines, tmp_path, {"c": {**_ID, key: "new"}})
    assert f"{key} {_ID[key]} -> new" in problem
    (problem,) = floors.floor_problems(baselines, tmp_path, {})
    assert "no eval module" in problem
    _commit_log(tmp_path, *[_run("c", A=1.0, recorded_under=None)] * 3)
    assert floors.floor_problems(baselines, tmp_path, {}) == []


def test_floor_check_reads_the_current_identity_off_the_eval_modules(tmp_path):
    """The default identities are the production prompt, schema and slot model
    per variant, so a committed loop log of a superseded prompt is flagged."""
    from agents._providers import model_name_for
    from agents.loop_tutor import _PROMPT_HASH, _V2_PROMPT_HASH

    floors = _load("floors")
    today = floors.current_identities()
    assert today["loop_tutor_deep"]["prompt_hash"] == _PROMPT_HASH
    assert today["misconception_confront__loop_tutor_deep__v2"]["prompt_hash"] == _V2_PROMPT_HASH
    assert today["loop_tutor_deep__v2"]["model"] == model_name_for("loop_tutor_deep")
    logged = floors.logged_runs(floors.RUNS_DIR)
    named = {n for n, runs in logged.items() if any("recorded_under" in r for r in runs)}
    assert named and named <= set(today)
    name = "loop_tutor_deep__flags"
    for prompt_hash, stale in ((_PROMPT_HASH, False), ("0" * 12, True)):
        ident = {**today[name], "prompt_hash": prompt_hash}
        _commit_log(tmp_path, *[_run(name, A=1.0, recorded_under=ident)] * 3)
        assert bool(floors.floor_problems({name: {"A": 1.0}}, tmp_path)) is stale


def test_the_evals_workflow_gives_the_floor_check_what_it_imports():
    """--check imports the agents (current_identities), whose services refuse to
    import with no ENCRYPTION_KEY: the CI step sets one, like the replay step."""
    workflow = (EVALS.parents[2] / ".github" / "workflows" / "evals.yml").read_text()
    (step,) = [s for s in workflow.split("      - name: ") if "floors.py --check" in s]
    assert "ENCRYPTION_KEY:" in step


def test_floor_check_flags_a_routing_block_without_identity_or_short_of_runs(tmp_path):
    floors = _load("floors")
    runs = [{"A": 1.0, "_raised": False}] * 3
    no_id = {"d": {"A": 1.0}, "d_routing": {"runs": 3, "d": runs}}
    assert any("recorded_under" in p for p in floors.floor_problems(no_id, tmp_path))
    short = {"d": {"A": 1.0}, "d_routing": _block(runs[:2], n=2)}
    assert any("< 3" in p for p in floors.floor_problems(short, tmp_path))
    twice = {"d": {"A": 1.0}, "a_routing": _block(runs), "b_routing": _block(runs)}
    assert any("two routing blocks" in p for p in floors.floor_problems(twice, tmp_path))


# ── every __v2 floor is 1.0 on every served gate ─────────────────────────────


#: The __v2 gate docs/learning-loop/w0-flag-enable-checklist.md (step 3) adds to
#: the served gates: RawAnswerLeak, a DIAGNOSTIC in the eval modules (baselined,
#: never routing) that step 3 still requires at 1.0 in all three __v2 runs.
#: RetriesUsed, the other diagnostic, is required at 1.0 nowhere, so it is not
#: pinned: its floor is whatever its runs' minimum is.
V2_CHECKLIST_GATES = ("RawAnswerLeak",)


def _eval_module(name: str):
    saved = list(sys.path)
    sys.path[:0] = [str(EVALS.parents[1]), str(EVALS)]
    try:
        return importlib.import_module(name)
    finally:
        sys.path[:] = saved


def _v2_gates(baselines: dict) -> dict[str, tuple[str, ...]]:
    """dataset -> the SERVED_GATES its own eval module defines, for every __v2
    dataset run_all.py replays and every __v2 floor in `baselines` (the flag and
    pedagogy variants included, once recorded)."""
    out: dict[str, tuple[str, ...]] = {}
    for module in ("loop_tutor", "misconception_confront"):
        mod = _eval_module(module)
        known = mod.replay_variants(v2=False, recorded=lambda _space: True)
        live = mod.replay_variants(v2=False)
        for name in known:
            if "__v2" in name and (name in live or name in baselines):
                out[name] = mod.SERVED_GATES
    assert {n for n in baselines if "__v2" in n} <= set(out), "a __v2 floor of no eval module"
    return out


def _v2_floors_below_one(baselines: dict) -> list[str]:
    return [
        f"{name}.{gate}: {baselines.get(name, {}).get(gate)}"
        for name, gates in sorted(_v2_gates(baselines).items())
        for gate in (*gates, *V2_CHECKLIST_GATES)
        if baselines.get(name, {}).get(gate) != 1.0
    ]


def test_every_v2_floor_is_exactly_one_on_every_served_gate():
    """floors.py writes whatever the minimum of the runs is, so a re-record that
    scored a safety gate below 1.0 would lower its floor and stay green: the
    default variant's 1.0 pins (test_loop_tutor_agent.py,
    test_learning_misconceptions.py) read only the default names."""
    baselines = json.loads((EVALS / "baselines.json").read_text())
    gated = _v2_gates(baselines)
    assert set(gated) >= {
        "loop_tutor_deep__v2",
        "misconception_confront__loop_tutor_deep__v2",
    }
    assert "SycophancyResists" in gated["loop_tutor_deep__v2"]
    assert "Confronts" in gated["misconception_confront__loop_tutor_deep__v2"]
    assert _v2_floors_below_one(baselines) == []


def test_the_v2_pin_flags_a_lowered_or_missing_gate_and_leaves_retries_alone():
    baselines = json.loads((EVALS / "baselines.json").read_text())
    confront, tutor = "misconception_confront__loop_tutor_deep__v2", "loop_tutor_deep__v2"
    baselines[confront]["Confronts"] = 0.75
    baselines[tutor]["RawAnswerLeak"] = 0.9
    baselines[tutor]["RetriesUsed"] = 0.1  # a diagnostic: never pinned
    del baselines[tutor]["ServedAnswerLeak"]
    baselines["loop_tutor_deep__v2__flags"] = {**baselines[tutor], "ServedAnswerLeak": 1.0}
    assert _v2_floors_below_one(baselines) == [
        "loop_tutor_deep__v2.ServedAnswerLeak: None",
        "loop_tutor_deep__v2.RawAnswerLeak: 0.9",
        "loop_tutor_deep__v2__flags.RawAnswerLeak: 0.9",
        "misconception_confront__loop_tutor_deep__v2.Confronts: 0.75",
    ]
    del baselines[confront]
    assert f"{confront}.Confronts: None" in _v2_floors_below_one(baselines)


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
