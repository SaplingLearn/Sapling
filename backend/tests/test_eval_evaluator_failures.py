"""D3: an evaluator that raises fails the eval run.

pydantic-evals files an evaluator's exception under `case.evaluator_failures`
and leaves its score out, and the harness used to read `report.failures` (task
errors) alone: an evaluator that crashed on 9 of 10 cases averaged 1.000 over
the one it finished, passed its baseline and logged an unraised run. Now each
crash scores 0.0 on its case, fails the run, refuses a baseline update and is
logged `raised` (the flag floors.py and the routing blocks read)."""

from __future__ import annotations

import importlib.util
import json
import sys
from dataclasses import dataclass
from pathlib import Path

from pydantic_evals import Case, Dataset
from pydantic_evals.evaluators import Evaluator, EvaluatorContext

EVALS = Path(__file__).parent / "evals"


def _replay():
    spec = importlib.util.spec_from_file_location("_eval__replay_d3", EVALS / "_replay.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@dataclass
class Crashy(Evaluator[int, int]):
    """1.0 on case 0; raises on every other case."""

    def evaluate(self, ctx: EvaluatorContext[int, int]) -> float:
        if ctx.inputs:
            raise RuntimeError("evaluator bug")
        return 1.0


@dataclass
class Fine(Evaluator[int, int]):
    def evaluate(self, ctx: EvaluatorContext[int, int]) -> float:
        return 1.0


def _dataset():
    return Dataset(
        name="d3_probe",
        cases=[Case(name=f"c{i}", inputs=i) for i in range(10)],
        evaluators=[Crashy(), Fine()],
    )


async def _task(x: int) -> int:
    return x


def _setup(tmp_path, monkeypatch, baselines):
    replay = _replay()
    path = tmp_path / "baselines.json"
    path.write_text(json.dumps(baselines))
    monkeypatch.setattr(replay, "BASELINES_PATH", path)
    log = tmp_path / "runs.jsonl"
    monkeypatch.setenv(replay.RUNS_LOG_ENV, str(log))
    return replay, path, log


def test_a_crashing_evaluator_fails_the_run_and_scores_zero_where_it_crashed(
    tmp_path, monkeypatch, capsys
):
    replay, _path, log = _setup(
        tmp_path, monkeypatch, {"d3_probe": {"Crashy": 1.0, "Fine": 1.0}}
    )
    ok = replay.evaluate_dataset(_dataset, _task, update=False, print_report=False)
    assert ok is False
    line = json.loads(log.read_text().splitlines()[-1])
    assert line["raised"] is True
    assert line["scores"]["Crashy"] == 0.1  # 1 of 10, not 1.000 over the one it finished
    assert line["scores"]["Fine"] == 1.0
    err = capsys.readouterr().err
    assert "9 evaluator failure(s)" in err and "evaluator bug" in err


def test_a_crashing_evaluator_never_becomes_a_baseline(tmp_path, monkeypatch):
    before = {"d3_probe": {"Crashy": 1.0, "Fine": 1.0}}
    replay, path, _log = _setup(tmp_path, monkeypatch, before)
    assert replay.evaluate_dataset(_dataset, _task, update=True, print_report=False) is False
    assert json.loads(path.read_text()) == before


def test_aggregate_counts_an_evaluator_failure_as_zero():
    replay = _replay()

    class _Score:
        def __init__(self, v):
            self.value = v

    class _Failure:
        def __init__(self, name):
            self.name, self.error_message = name, "boom"

    class _Case:
        def __init__(self, name, scores, failures):
            self.name, self.scores, self.evaluator_failures = name, scores, failures

    class _Report:
        cases = [
            _Case("a", {"E": _Score(1.0)}, []),
            _Case("b", {}, [_Failure("E")]),
        ]
        report_evaluator_failures = [_Failure("R")]

    assert replay._aggregate_scores(_Report) == {"E": 0.5}
    assert replay._evaluator_failures(_Report) == ["b: E: boom", "(report) R: boom"]
