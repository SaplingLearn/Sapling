"""Guard: no LLM seam is left uninstrumented (issue #118 success criterion).

Two invariants, enforced by static analysis so a *future* call site that skips
usage capture fails CI rather than silently dropping billing data:

1. Every production module that runs a Pydantic AI agent (``*_agent.run(...)``
   / ``.run_sync(...)``) must also reference ``record_agent_usage``.
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


def _is_agent_run_call(node: ast.AST) -> bool:
    """True for ``<something>agent.run(...)`` / ``.run_sync(...)`` calls."""
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if not isinstance(func, ast.Attribute) or func.attr not in {"run", "run_sync"}:
        return False
    # Receiver is a bare name like `quiz_agent`, `agent`, `health_probe_agent`.
    recv = func.value
    if isinstance(recv, ast.Name):
        return recv.id == "agent" or recv.id.endswith("_agent")
    return False


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
        src = py.read_text(encoding="utf-8")
        tree = ast.parse(src, filename=str(py))
        if any(_is_agent_run_call(n) for n in ast.walk(tree)):
            if "record_agent_usage" not in src:
                offenders.append(str(py.relative_to(BACKEND)))
    assert not offenders, (
        "These modules run an agent but never call record_agent_usage "
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
