"""Guard: no LLM seam is left uninstrumented (issue #118 success criterion).

Two invariants, enforced by static analysis so a *future* call site that skips
usage capture fails CI rather than silently dropping billing data:

1. Every ``*_agent.run(...)`` / ``.run_sync(...)`` call site in a production
   module must be usage-recorded **per call site**: a function enclosing the
   call must invoke ``record_agent_usage``. One documented escape hatch: a
   helper that directly ``return``s the run result (a "pass-through runner",
   e.g. ``notes._run_note_worker``) defers recording to its callers — every
   module-local call to such a helper is then itself checked under the same
   rule. Cross-module runner indirection is NOT tracked: keep the run and its
   ``record_agent_usage`` wrap in the same module, or this guard goes blind.
2. Every direct-Gemini helper in ``gemini_service`` (``call_gemini`` and
   ``call_gemini_multiturn``) must call ``_log_gemini_usage``; ``call_gemini_json``
   delegates to ``call_gemini`` and is exempt (it would double-count otherwise).
"""
from __future__ import annotations

import ast
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]

# Production trees that may run agents. Tests and one-off scripts are excluded:
# scripts are dev tooling, not the served app.
_SCAN_ROOTS = ("routes", "services", "agents")

_FUNC_DEFS = (ast.FunctionDef, ast.AsyncFunctionDef)


def _is_agent_run_call(node: ast.AST, runner_names: set[str] = frozenset()) -> bool:
    """True for ``<something>agent.run(...)`` / ``.run_sync(...)`` calls, and
    for calls to a known module-local pass-through runner helper."""
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if isinstance(func, ast.Attribute) and func.attr in {"run", "run_sync"}:
        # Receiver is a bare name like `quiz_agent`, `agent`, `health_probe_agent`.
        recv = func.value
        if isinstance(recv, ast.Name):
            return recv.id == "agent" or recv.id.endswith("_agent")
        return False
    if isinstance(func, ast.Name):
        return func.id in runner_names
    return False


def _calls_record_usage(fn: ast.AST) -> bool:
    """True if the function body contains a ``record_agent_usage(...)`` call."""
    for n in ast.walk(fn):
        if isinstance(n, ast.Call):
            f = n.func
            if isinstance(f, ast.Name) and f.id == "record_agent_usage":
                return True
            if isinstance(f, ast.Attribute) and f.attr == "record_agent_usage":
                return True
    return False


def _returned_call(stmt: ast.AST) -> ast.Call | None:
    """The Call a ``return``/``return await`` statement passes through, if any."""
    if not isinstance(stmt, ast.Return):
        return None
    value = stmt.value
    if isinstance(value, ast.Await):
        value = value.value
    return value if isinstance(value, ast.Call) else None


def _module_offenders(py: Path) -> list[str]:
    """Uninstrumented agent-run call sites in one module, as ``path:line``."""
    tree = ast.parse(py.read_text(encoding="utf-8"), filename=str(py))
    functions = [n for n in ast.walk(tree) if isinstance(n, _FUNC_DEFS)]

    # Pass 1 (fixpoint): find pass-through runners — functions that hand an
    # agent-run result straight back via ``return`` — so their callers can be
    # held to the recording rule instead.
    runners: set[str] = set()
    changed = True
    while changed:
        changed = False
        for fn in functions:
            if fn.name in runners:
                continue
            for stmt in ast.walk(fn):
                call = _returned_call(stmt)
                if call is not None and _is_agent_run_call(call, runners):
                    runners.add(fn.name)
                    changed = True
                    break

    # Pass 2: every run site (including calls to pass-through runners) must sit
    # inside an enclosing function that calls record_agent_usage — unless the
    # site is itself a runner's returned expression (its callers are checked).
    offenders: list[str] = []

    def walk(node: ast.AST, stack: list) -> None:
        if isinstance(node, _FUNC_DEFS):
            stack = stack + [node]
        if _is_agent_run_call(node, runners):
            innermost = stack[-1] if stack else None
            deferred_to_callers = (
                innermost is not None
                and innermost.name in runners
                and any(_returned_call(s) is node for s in ast.walk(innermost))
            )
            if not deferred_to_callers and not any(_calls_record_usage(f) for f in stack):
                offenders.append(f"{py.relative_to(BACKEND)}:{node.lineno}")
        for child in ast.iter_child_nodes(node):
            walk(child, stack)

    walk(tree, [])
    return offenders


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


def test_gemini_helpers_log_usage():
    src = (BACKEND / "services" / "gemini_service.py").read_text(encoding="utf-8")
    tree = ast.parse(src)

    logged: dict[str, bool] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in {
            "call_gemini", "call_gemini_multiturn",
        }:
            logged[node.name] = any(
                isinstance(c, ast.Call)
                and isinstance(c.func, ast.Name)
                and c.func.id == "_log_gemini_usage"
                for c in ast.walk(node)
            )

    assert logged.get("call_gemini"), "call_gemini must call _log_gemini_usage"
    assert logged.get("call_gemini_multiturn"), (
        "call_gemini_multiturn must call _log_gemini_usage"
    )
