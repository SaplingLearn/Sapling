"""PKG-07 Task 9 follow-up: the eval-side rung judge (tests/evals/_rung_judge.py)
and its calibration dataset (tests/evals/loop_rung_judge.py).

The judge replaces `loop_tutor._infer_rung`, which scores any unmarked reply as
H3 and so fails every compliant reply at an H1/H2 ceiling (HANDOFF-07 Known
gaps). These tests never call a model: judgements replay from cassettes, and a
stale cassette (served text or judge prompt changed) must fail loudly.
"""

from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

EVALS = Path(__file__).parent / "evals"


def _load(name: str):
    """Load an eval module by path; the evals prepend tests/evals to sys.path,
    which is restored so the suite's import path stays clean."""
    if name in sys.modules:
        return sys.modules[name]
    saved = list(sys.path)
    sys.path.insert(0, str(EVALS))
    try:
        spec = importlib.util.spec_from_file_location(name, EVALS / f"{name}.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod  # pydantic resolves postponed annotations through it
        spec.loader.exec_module(mod)
    finally:
        sys.path[:] = saved
    return mod


@pytest.fixture
def judge():
    return _load("_rung_judge")


_ITEM = {
    "item_prompt": "What stops factorial(0) from recursing forever?",
    "reference": "The base case returns 1 when n equals 0 so the function stops calling itself.",
    "final_answer": "returns 1",
}


def _write_cassette(judge, tmp_path, slot, case_id, served, item, **override):
    body = {
        "served_sha256": hashlib.sha256(served.encode("utf-8")).hexdigest(),
        "judge_model": judge.RUNG_JUDGE_MODEL,
        "judge_prompt_hash": judge.judge_prompt_hash(item),
        "output": {"rung": 1, "reveals_final_answer": False, "evidence": "a pump question"},
    }
    body.update(override)
    path = judge.cassette_path(slot, case_id, root=tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(body))
    return path


def test_rung_judge_prompt_embeds_ladder_intents(judge):
    from learning.ladder import RUNG_INTENT, Rung

    for rung in Rung:
        assert RUNG_INTENT[rung] in judge.JUDGE_INSTRUCTIONS, rung
        assert f"H{int(rung)}" in judge.JUDGE_INSTRUCTIONS
    item = judge.JudgeItem.from_metadata(_ITEM)
    msg = judge.build_judge_message("What do you need first?", item)
    # the judge sees the item, its reference and final answer, and the reply
    for part in (
        _ITEM["item_prompt"],
        _ITEM["reference"],
        _ITEM["final_answer"],
        "What do you need first?",
    ):
        assert part in msg
    # eval-only: no production model slot for the judge
    from agents import _providers

    assert "rung_judge" not in _providers._DEFAULTS


def test_judge_replays_a_fresh_cassette(judge, tmp_path):
    item = judge.JudgeItem.from_metadata(_ITEM)
    served = "What is the first thing you need to know here?"
    _write_cassette(judge, tmp_path, "loop_tutor", "c1", served, item)
    got = judge.judge_rung("c1", "loop_tutor", served, item, mode="replay", cassette_dir=tmp_path)
    assert got == judge.RungJudgement(
        rung=1, reveals_final_answer=False, evidence="a pump question"
    )
    # a mapping (the loop_tutor case metadata) is accepted as the item too
    assert (
        judge.judge_rung(
            "c1", "loop_tutor", served, _ITEM, mode="replay", cassette_dir=tmp_path
        ).rung
        == 1
    )


def test_judge_cassette_path_scheme(judge, tmp_path):
    p = judge.cassette_path("loop_tutor_lite", "hint_develop_h1_pump", root=tmp_path)
    assert p == tmp_path / "loop_tutor_rung_judge" / "loop_tutor_lite__hint_develop_h1_pump.json"


def test_judge_cassette_stale_on_served_change(judge, tmp_path):
    item = judge.JudgeItem.from_metadata(_ITEM)
    _write_cassette(judge, tmp_path, "loop_tutor", "c1", "old reply?", item)
    with pytest.raises(judge.StaleJudgementError, match="served"):
        judge.judge_rung(
            "c1", "loop_tutor", "new reply?", item, mode="replay", cassette_dir=tmp_path
        )


def test_judge_cassette_stale_on_prompt_change(judge, tmp_path, monkeypatch):
    item = judge.JudgeItem.from_metadata(_ITEM)
    served = "What is the first thing you need?"
    _write_cassette(judge, tmp_path, "loop_tutor", "c1", served, item)
    monkeypatch.setattr(judge, "JUDGE_INSTRUCTIONS", judge.JUDGE_INSTRUCTIONS + "\nNew rule.")
    with pytest.raises(judge.StaleJudgementError, match="prompt"):
        judge.judge_rung("c1", "loop_tutor", served, item, mode="replay", cassette_dir=tmp_path)
    monkeypatch.undo()
    # the item is part of the judge prompt: a changed reference is stale too
    changed = judge.JudgeItem.from_metadata({**_ITEM, "reference": "something else"})
    with pytest.raises(judge.StaleJudgementError, match="prompt"):
        judge.judge_rung("c1", "loop_tutor", served, changed, mode="replay", cassette_dir=tmp_path)


def test_judge_cassette_stale_on_model_change(judge, tmp_path):
    item = judge.JudgeItem.from_metadata(_ITEM)
    served = "What is the first thing you need?"
    _write_cassette(
        judge, tmp_path, "loop_tutor", "c1", served, item, judge_model="some-other-model"
    )
    with pytest.raises(judge.StaleJudgementError, match="model"):
        judge.judge_rung("c1", "loop_tutor", served, item, mode="replay", cassette_dir=tmp_path)


def test_judge_missing_cassette_raises(judge, tmp_path):
    with pytest.raises(judge.MissingJudgementError):
        judge.judge_rung("nope", "loop_tutor", "x?", _ITEM, mode="replay", cassette_dir=tmp_path)


def test_calibration_baseline_gated_at_one():
    baselines = json.loads((EVALS / "baselines.json").read_text())
    assert baselines["loop_rung_judge"] == {"RevealAgreement": 1.0, "RungJudgeAgreement": 1.0}

    cal = _load("loop_rung_judge")
    ds = cal.make_dataset()
    assert ds.name == "loop_rung_judge"
    assert 1 <= len(ds.cases) <= 8
    golds = {c.metadata["gold_rung"] for c in ds.cases}
    assert golds == set(range(7)), "calibration spans H0..H6"
    # at least two plain H1/H2 replies the old marker classifier misreads
    from learning.ladder import Rung

    loop = _load_loop_tutor()
    misread = [
        c
        for c in ds.cases
        if c.metadata["gold_rung"] in (1, 2)
        and int(loop._infer_rung(c.inputs.served_text)) != c.metadata["gold_rung"]
    ]
    assert len(misread) >= 2
    assert all(isinstance(Rung(c.metadata["gold_rung"]), Rung) for c in ds.cases)

    # the committed judgements replay fresh (no stale cassette) and agree with gold
    report = asyncio.run(ds.evaluate(cal.replay_run))
    assert not report.failures
    for case in report.cases:
        assert case.scores["RungJudgeAgreement"].value == 1.0, case.name
        assert case.scores["RevealAgreement"].value == 1.0, case.name


def _load_loop_tutor():
    saved = list(sys.path)
    try:
        spec = importlib.util.spec_from_file_location(
            "_eval_loop_tutor_for_judge", EVALS / "loop_tutor.py"
        )
        mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = mod
        spec.loader.exec_module(mod)
    finally:
        sys.path[:] = saved
    return mod
