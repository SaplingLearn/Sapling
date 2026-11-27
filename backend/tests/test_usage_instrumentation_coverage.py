"""Guard: no LLM seam is left uninstrumented (issue #118 success criterion).

One invariant, enforced by static analysis so a *future* call site that skips
usage capture fails CI rather than silently dropping billing data:

Every agent run site in a production module — ``<x>agent.<runner>(...)``
where the receiver is a name or attribute ending in ``agent`` (``quiz_agent``,
``agent``, ``turn.agent``) and the runner is any of ``run``, ``run_sync``,
``run_stream``, ``run_stream_events``, ``run_stream_sync``, ``iter`` (#866
Z52: the loop tutor's ``turn.agent.run`` and the streamed tutors'
``agent.run_stream_events`` / ``agent.iter`` were invisible) — must be
usage-recorded **per call site**: a function enclosing the call must record,
by calling ``record_agent_usage``, a usage callback (``on_usage`` /
``on_incomplete_usage``, which the streamed turns' callers pass), a turn's
``record_usage`` (which calls ``record_agent_usage``, pinned below), or a
module-local function that does. Two documented escape hatches defer the
recording to a helper's callers, every module-local call to the helper then
being checked under the same rule: a helper that directly ``return``s the
run result (a "pass-through runner", e.g. ``notes._run_note_worker``), and a
helper that runs the agent for a caller that settles its usage (a "producer",
e.g. ``chat_stream._relay_structured_run``), which must have a module-local
caller. Cross-module runner indirection is NOT tracked: keep the run and its
recording in the same module, or this guard goes blind; the callers of the
two streamed runners must pass their usage callbacks (checked below).

(The checklist uses a deliberately separate durable receipt path, checked by
``_durable_checklist_site`` below: queueing it too would double bill.

The second invariant this guard used to enforce — ``_log_gemini_usage`` in
the direct-Gemini helpers — died with ``services/gemini_service.py`` in
#151b / ADR 0024: agents are the only LLM seam left to instrument.)
"""
from __future__ import annotations

import ast
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]

# Production trees that may run agents. Tests and one-off scripts are excluded:
# scripts are dev tooling, not the served app.
_SCAN_ROOTS = ("routes", "services", "agents")

_FUNC_DEFS = (ast.FunctionDef, ast.AsyncFunctionDef)


#: Every pydantic-ai Agent method that runs the model (test_learning_loop_invariants'
#: AGENT_RUN_METHODS pins the full list against the installed pydantic-ai).
_RUN_METHODS = frozenset({"run", "run_sync", "run_stream", "run_stream_events", "run_stream_sync", "iter"})
#: Calls that record a run's usage: the canonical helper, the streamed turns'
#: usage callbacks, and a loop turn's own recorder (pinned to call the helper).
_RECORDERS = frozenset({"record_agent_usage", "on_usage", "on_incomplete_usage", "record_usage"})


def _terminal(expr: ast.AST) -> str | None:
    if isinstance(expr, ast.Name):
        return expr.id
    if isinstance(expr, ast.Attribute):
        return expr.attr
    return None


def _is_agent_receiver(expr: ast.AST) -> bool:
    """`agent`, `quiz_agent`, `turn.agent`, `self.health_probe_agent`."""
    name = _terminal(expr)
    return name is not None and (name == "agent" or name.endswith("_agent"))


def _is_agent_run_call(node: ast.AST, runner_names: set[str] = frozenset()) -> bool:
    """True for ``<something>agent.<runner>(...)`` calls (any receiver whose
    last segment ends in ``agent``; any runner in _RUN_METHODS), and for calls
    to a known module-local runner helper."""
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if isinstance(func, ast.Attribute) and func.attr in _RUN_METHODS:
        return _is_agent_receiver(func.value)
    if isinstance(func, ast.Name):
        return func.id in runner_names
    return False


def _calls_record_usage(fn: ast.AST, recording: set[str] = frozenset()) -> bool:
    """True if the function body calls a recorder (_RECORDERS) or a
    module-local function known to record (`recording`)."""
    for n in ast.walk(fn):
        if isinstance(n, ast.Call):
            name = _terminal(n.func)
            if name in _RECORDERS or (isinstance(n.func, ast.Name) and name in recording):
                return True
    return False


def _recording_functions(functions: list) -> set[str]:
    """Module-local functions that record, directly or through another (fixpoint)."""
    recording: set[str] = set()
    changed = True
    while changed:
        changed = False
        for fn in functions:
            if fn.name not in recording and _calls_record_usage(fn, recording):
                recording.add(fn.name)
                changed = True
    return recording


def _called_names(tree: ast.AST) -> set[str]:
    return {
        n.func.id for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
    }


def _returned_call(stmt: ast.AST) -> ast.Call | None:
    """The Call a ``return``/``return await`` statement passes through, if any."""
    if not isinstance(stmt, ast.Return):
        return None
    value = stmt.value
    if isinstance(value, ast.Await):
        value = value.value
    return value if isinstance(value, ast.Call) else None


def _named_calls(fn: ast.AST) -> set[str]:
    names = set()
    for node in ast.walk(fn):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                names.add(node.func.id)
            elif isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
                names.add(f"{node.func.value.id}.{node.func.attr}")
    return names


def _durable_checklist_site(py: Path, fn: ast.AST, functions: list) -> bool:
    # Narrow alternative instrumentation contract: this one known paid path
    # collects SDK usage and every dispatch, then prepares and atomically writes
    # a strict stable receipt. All other sites still require the ordinary hook.
    if py != BACKEND / "services/topic_checklist_service.py" or fn is None or fn.name != "_generate":
        return False
    by_name = {f.name: f for f in functions}
    generated = _named_calls(fn)
    finished = _named_calls(by_name.get("_finish_generation", ast.Pass()))
    refreshed = _named_calls(by_name.get("refresh_checklist", ast.Pass()))
    return (
        {"ChecklistDispatches", "ChecklistGeneration", "topic_checklist_agent.run"} <= generated
        and {"prepare_checklist_receipt", "checklist_budget.reconcile"} <= finished
        and {"checklist_budget.admit", "_generate", "_finish_generation"} <= refreshed
        and not _calls_record_usage(fn)
    )


def _module_offenders(py: Path, source: str | None = None) -> list[str]:
    """Uninstrumented agent-run call sites in one module, as ``path:line``.
    ``source`` (tests) replaces the file's text."""
    text = py.read_text(encoding="utf-8") if source is None else source
    tree = ast.parse(text, filename=str(py))
    functions = [n for n in ast.walk(tree) if isinstance(n, _FUNC_DEFS)]
    recording = _recording_functions(functions)
    called = _called_names(tree)

    def records(fn: ast.AST) -> bool:
        return fn.name in recording

    # Pass 1 (fixpoint): find runners whose callers are held to the recording
    # rule instead — functions that hand an agent-run result straight back via
    # ``return`` (pass-through), and functions that run an agent without
    # recording and are called in this module (producers: the caller settles).
    runners: set[str] = set()
    changed = True
    while changed:
        changed = False
        for fn in functions:
            if fn.name in runners:
                continue
            for stmt in ast.walk(fn):
                call = _returned_call(stmt)
                producer = (
                    _is_agent_run_call(stmt, runners) and not records(fn) and fn.name in called
                )
                if producer or (call is not None and _is_agent_run_call(call, runners)):
                    runners.add(fn.name)
                    changed = True
                    break

    # Pass 2: every run site (including calls to runners) must sit inside an
    # enclosing function that records — unless the site is a runner's own run
    # (its callers are checked).
    offenders: list[str] = []

    def walk(node: ast.AST, stack: list) -> None:
        if isinstance(node, _FUNC_DEFS):
            stack = stack + [node]
        if _is_agent_run_call(node, runners):
            innermost = stack[-1] if stack else None
            deferred_to_callers = innermost is not None and innermost.name in runners and (
                any(_returned_call(s) is node for s in ast.walk(innermost)) or not records(innermost)
            )
            if not deferred_to_callers and not any(records(f) for f in stack) and not _durable_checklist_site(py, innermost, functions):
                offenders.append(f"{py.relative_to(BACKEND) if py.is_absolute() else py}:{node.lineno}")
        for child in ast.iter_child_nodes(node):
            walk(child, stack)

    walk(tree, [])
    return offenders


def _run_sites(py: Path) -> list[int]:
    """Lines of every direct agent run site in one module (the scan's reach)."""
    tree = ast.parse(py.read_text(encoding="utf-8"), filename=str(py))
    return [n.lineno for n in ast.walk(tree) if _is_agent_run_call(n)]


def _production_py_files():
    files = [BACKEND / "main.py"]
    for root in _SCAN_ROOTS:
        for py in (BACKEND / root).rglob("*.py"):
            if py.name.startswith("test_") or "tests" in py.parts:
                continue
            files.append(py)
    return files


def test_every_agent_run_site_records_usage():
    offenders: list[str] = []
    for py in _production_py_files():
        offenders.extend(_module_offenders(py))
    assert not offenders, (
        "These agent-run call sites have no enclosing record_agent_usage call "
        f"(uninstrumented LLM spend): {offenders}"
    )


def test_durable_checklist_contract_cannot_hide_missing_settlement(tmp_path, monkeypatch):
    # The exception is path- and function-specific, and requires the whole
    # admission/collection/strict-receipt/settlement chain in that module.
    module = BACKEND / "services/topic_checklist_service.py"
    text = module.read_text()
    assert _module_offenders(module) == []
    tree = ast.parse(text)
    functions = [n for n in ast.walk(tree) if isinstance(n, _FUNC_DEFS)]
    generate = next(f for f in functions if f.name == "_generate")
    assert _durable_checklist_site(module, generate, functions)
    assert not _durable_checklist_site(tmp_path / "other.py", generate, functions)
    for missing in ("_finish_generation", "refresh_checklist"):
        assert not _durable_checklist_site(module, generate, [f for f in functions if f.name != missing])


# ── #866 Z52: the loop tutor's and the streamed tutors' run sites ─────────────


def _offenders_in(source: str) -> list[str]:
    return _module_offenders(Path("synthetic.py"), source)


def test_the_matcher_sees_every_runner_and_attribute_receiver():
    """A run through an attribute (`turn.agent.run`) or a streaming runner
    (`run_stream_events`, `iter`) with no recording is an offender; the same
    run beside a recorder is not."""
    for site in ("await turn.agent.run(m)", "agent.run_stream_events(m)", "agent.iter(m)",
                 "await self.quiz_agent.run_stream(m)"):
        bare = f"async def f(turn, agent, self, m):\n    return_value = {site}\n"
        assert _offenders_in(bare) == ["synthetic.py:2"], site
    for recorder in ("record_agent_usage(r)", "turn.record_usage(r)", "on_usage(r)",
                     "on_incomplete_usage(r)"):
        ok = f"async def f(turn, r):\n    r = await turn.agent.run('m')\n    {recorder}\n"
        assert _offenders_in(ok) == [], recorder
    assert _offenders_in("def f(loop):\n    loop.run('x')\n") == []  # not an agent


def test_a_producer_is_covered_only_by_a_settling_caller():
    """chat_stream's shape: the run lives in a helper; its module-local caller
    settles the usage through another local function."""
    producer = (
        "async def _relay(agent, m):\n    async with agent.iter(m) as run:\n        return_value = run\n"
        "def _settle(outcome, on_usage):\n    on_usage(outcome)\n"
    )
    settled = producer + "async def turn(agent, on_usage):\n    await _relay(agent, 'm')\n    _settle(1, on_usage)\n"
    assert _offenders_in(settled) == []
    unsettled = producer + "async def turn(agent):\n    await _relay(agent, 'm')\n"
    assert _offenders_in(unsettled) == ["synthetic.py:7"]
    orphan = "async def _relay(agent, m):\n    async with agent.iter(m) as run:\n        return_value = run\n"
    assert _offenders_in(orphan) == ["synthetic.py:2"]  # no local caller: nobody settles it


def test_the_scan_reaches_the_loop_and_stream_run_sites():
    """Not vacuous: the loop tutor's runs and the streamed runners are run sites
    the guard checks (each covered by a recording today)."""
    for rel in ("services/loop/runner.py", "services/loop/continuation.py", "services/chat_stream.py"):
        assert _run_sites(BACKEND / rel), rel
        assert _module_offenders(BACKEND / rel) == [], rel


def test_the_loop_turn_recorder_records():
    """`turn.record_usage` counts as a recording because it calls
    record_agent_usage — pinned, so the alias cannot go blind."""
    tree = ast.parse((BACKEND / "services/loop/turn.py").read_text(encoding="utf-8"))
    methods = [
        f for c in ast.walk(tree) if isinstance(c, ast.ClassDef)
        for f in c.body if isinstance(f, _FUNC_DEFS) and f.name == "record_usage"
    ]
    assert methods and all(
        any(isinstance(n, ast.Call) and _terminal(n.func) == "record_agent_usage" for n in ast.walk(m))
        for m in methods
    )


def test_every_streamed_turn_passes_its_usage_callbacks():
    """The streamed runners record through the caller's callbacks, so every
    production call passes them (a structured turn also its incomplete one)."""
    needed = {"stream_agent_turn": {"on_usage"}, "stream_structured_turn": {"on_usage", "on_incomplete_usage"}}
    calls = 0
    for py in _production_py_files():
        for node in ast.walk(ast.parse(py.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call) and _terminal(node.func) in needed:
                calls += 1
                given = {
                    k.arg for k in node.keywords
                    if k.arg and not (isinstance(k.value, ast.Constant) and k.value.value is None)
                }
                missing = needed[_terminal(node.func)] - given
                assert not missing, f"{py.relative_to(BACKEND)}:{node.lineno} passes no {sorted(missing)}"
    assert calls >= 3  # the two chat_tutor streams and the loop's structured stream
