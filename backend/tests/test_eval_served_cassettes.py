"""D5: the evals fail closed when the code that feeds them changes.

Two halves. (1) The judge cassettes and the session_close recordings must
match what the CURRENT production code serves: every served text is
re-derived here from the committed tutor recordings with the current
`served_texts` (render_turn → served_render → served_model_text), and each
rung-judge and confront-judge judgement must have been made of exactly that
text, by the current judge prompt and model; every session_close recording
must have been made under the current close prompt, schema, model and
rendered draft. A served-code change that would move a judged text fails
here, in the unit suite, even while the loop recordings themselves are stale
(their replay stops at the prompt hash first). (2) The `evals.yml` path
filter covers every first-party module the eval harness imports, so a
change to any of them runs the evals job."""

from __future__ import annotations

import ast
import importlib
import re
import sys
from pathlib import Path

import pytest
import yaml

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent
EVALS = BACKEND / "tests" / "evals"
WORKFLOW = REPO / ".github" / "workflows" / "evals.yml"


@pytest.fixture(scope="module")
def evals():
    saved = list(sys.path)
    for p in (str(EVALS), str(BACKEND)):
        if p not in sys.path:
            sys.path.insert(0, p)
    try:
        yield {
            name: importlib.import_module(name)
            for name in (
                "_replay",
                "_rung_judge",
                "_confront_judge",
                "loop_tutor",
                "misconception_confront",
                "session_close",
            )
        }
    finally:
        sys.path[:] = saved


def _fresh(judge, path, served, item) -> str | None:
    try:
        judge._load_fresh(path, served, item)
    except (judge.MissingJudgementError, judge.StaleJudgementError) as exc:
        return str(exc)
    return None


def test_every_rung_and_confront_judgement_judged_the_text_served_today(evals):
    """loop_tutor (every tier slot) and misconception_confront (every slot):
    the judged served text is what today's served path makes of the committed
    recording. The recording's own hashes are NOT checked here (the cassette
    pins do that); this pins the served code and the judges."""
    from agents.loop_tutor import LOOP_TIER_SLOTS

    lt, mc = evals["loop_tutor"], evals["misconception_confront"]
    rj, cj, replay = evals["_rung_judge"], evals["_confront_judge"], evals["_replay"]
    problems, checked = [], 0
    for slot in LOOP_TIER_SLOTS.values():
        for case in lt.CASES:
            meta = dict(case.metadata or {})
            rec = lt.LoopRecording.model_validate(replay.load_cassette(slot, case.name))
            _raw, served, _turn = lt.served_texts(rec.output, case.inputs, meta, False)
            item = rj._coerce_item(rj.JudgeItem.from_metadata(meta, student_message=case.inputs[3]))
            problems.append(_fresh(rj, rj.cassette_path(slot, case.name), served, item))
            checked += 1
            if meta.get("wrong_claim"):
                confront = cj.ConfrontCase(
                    item_prompt=meta.get("item_prompt") or "",
                    misconception=meta["wrong_claim"],
                    student_message=case.inputs[3],
                )
                problems.append(_fresh(cj, cj.cassette_path(slot, case.name), served, confront))
                checked += 1
    for slot in mc.CONFRONT_SLOTS:
        for case in mc.CASES:
            meta = dict(case.metadata or {})
            body = replay.load_cassette(mc._cassette_dataset(slot, False), case.name)
            rec = lt.LoopRecording.model_validate(body)
            _raw, served, turn = mc.served_texts(rec.output, case.inputs, meta, False)
            item = rj._coerce_item(rj.JudgeItem.from_metadata(meta, student_message=case.inputs[3]))
            problems.append(_fresh(rj, rj.cassette_path(slot, case.name), served, item))
            confront = cj.ConfrontCase(
                item_prompt=meta.get("item_prompt") or "",
                misconception=meta["misconception"],
                student_message="" if meta.get("trusted") else case.inputs[3],
            )
            problems.append(_fresh(cj, cj.cassette_path(slot, case.name), turn, confront))
            checked += 2
    assert checked >= 50, checked
    assert [p for p in problems if p] == []


def test_every_session_close_recording_matches_the_current_close(evals):
    """session_close replays a recording only under the close agent's current
    prompt, schema, slot model and the rendered draft; pinned hermetically
    here too, so a changed close prompt fails the unit suite and not only the
    evals job. Fails until session_close is re-recorded (its prompt changed)."""
    from agents._providers import model_name_for
    from agents.session_close import _PROMPT_HASH, render_draft

    sc, replay = evals["session_close"], evals["_replay"]
    stale = []
    for name, case in sc._cases():
        body = replay.load_cassette(sc.DATASET, name)
        if body is None:
            stale.append(f"{name}: not recorded")
            continue
        rec = sc.CloseRecording.model_validate(body)
        want = (
            _PROMPT_HASH,
            sc._schema_hash(),
            model_name_for("session_close"),
            sc._input_sha(render_draft(case.draft, nonce=sc.EVAL_NONCE)),
        )
        got = (rec.prompt_hash, rec.schema_hash, rec.model, rec.input_sha256)
        if got != want:
            stale.append(f"{name}: recorded under {got}, now {want}")
    assert stale == []


# ── (2) the evals.yml path filter covers what the harness imports ────────────


def _module_file(name: str) -> Path | None:
    parts = name.split(".")
    for base in (BACKEND, EVALS):
        p = base.joinpath(*parts)
        if p.with_suffix(".py").is_file():
            return p.with_suffix(".py")
        if (p / "__init__.py").is_file():
            return p / "__init__.py"
    return None


def _imports(path: Path) -> set[str]:
    out: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            out.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            out.add(node.module)
            out.update(f"{node.module}.{a.name}" for a in node.names)
    return out


def harness_closure() -> set[str]:
    """Every first-party file (backend-relative) reachable by import from
    tests/evals/*.py — top-level and function-level imports alike, so the
    served path's lazy imports (services.loop.*) are in it."""
    seen: set[Path] = set()
    todo = sorted(EVALS.glob("*.py"))
    while todo:
        path = todo.pop()
        if path in seen:
            continue
        seen.add(path)
        for name in _imports(path):
            parts = name.split(".")
            for i in range(1, len(parts) + 1):
                found = _module_file(".".join(parts[:i]))
                if found is not None and found not in seen:
                    todo.append(found)
    return {str(p.relative_to(BACKEND)) for p in seen}


def _glob_re(pattern: str) -> re.Pattern:
    """GitHub's paths-filter glob: ** crosses directories, * and ? do not."""
    out, i = "", 0
    while i < len(pattern):
        if pattern.startswith("**", i):
            out += ".*"
            i += 2
        elif pattern[i] == "*":
            out += "[^/]*"
            i += 1
        elif pattern[i] == "?":
            out += "[^/]"
            i += 1
        else:
            out += re.escape(pattern[i])
            i += 1
    return re.compile(out + r"\Z")


def _workflow_paths() -> list[str]:
    doc = yaml.safe_load(WORKFLOW.read_text())
    on = doc.get("on", doc.get(True))  # PyYAML reads a bare `on:` key as True
    return list(on["pull_request"]["paths"])


def test_the_evals_workflow_runs_on_every_module_the_harness_imports():
    patterns = [_glob_re(p) for p in _workflow_paths()]
    closure = harness_closure()
    assert "services/loop/served.py" in closure and "learning/leak.py" in closure
    missing = sorted(
        f for f in closure if not any(p.match(f"backend/{f}") for p in patterns)
    )
    assert missing == [], (
        "add these to .github/workflows/evals.yml `paths:` (they feed a served text "
        f"or a recorded request): {missing}"
    )


def test_the_evals_workflow_also_runs_on_its_own_inputs():
    paths = _workflow_paths()
    for must in (
        "backend/tests/evals/**",
        ".github/workflows/evals.yml",
        "backend/requirements.lock",
    ):
        assert must in paths, must


def test_glob_matching_follows_github_semantics():
    assert _glob_re("backend/services/loop/**").match("backend/services/loop/served.py")
    assert not _glob_re("backend/db/*.py").match("backend/db/migrations/x.py")
    assert _glob_re("backend/db/*.py").match("backend/db/connection.py")
