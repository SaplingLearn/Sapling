"""The `E2E_*` string constants of `agents/function_handlers_e2e.py`, read from
its SOURCE without importing it (PKG-13 fix round).

Importing the handler module pulls in pydantic-ai and google-genai (~2.5 s).
The rich seed runs in a fresh process before EVERY Playwright test
(`support/db.ts::reseedBaseline`), so that import cost every test ~2.4 s just
to read three strings. The constants still live — and are defined — only in
the handler module; this evaluates their assignments structurally:

- a string literal, an implicit concatenation of literals, `+` of strings;
- an f-string whose placeholders are bare names of constants defined EARLIER
  in the module (no format specs, no conversions, no expressions).

Anything else raises ValueError — never a guess.
`tests/test_e2e_handler_constants.py` pins the values to the imported module.
"""

from __future__ import annotations

import ast
from functools import lru_cache
from pathlib import Path

_SOURCE = Path(__file__).resolve().parents[1] / "agents" / "function_handlers_e2e.py"


def _eval(node: ast.expr, env: dict[str, str], name: str) -> str:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _eval(node.left, env, name) + _eval(node.right, env, name)
    if isinstance(node, ast.JoinedStr):
        parts = []
        for v in node.values:
            if isinstance(v, ast.Constant) and isinstance(v.value, str):
                parts.append(v.value)
            elif (
                isinstance(v, ast.FormattedValue)
                and v.conversion == -1
                and v.format_spec is None
                and isinstance(v.value, ast.Name)
                and v.value.id in env
            ):
                parts.append(env[v.value.id])
            else:
                raise ValueError(f"{name}: unsupported f-string part")
        return "".join(parts)
    if isinstance(node, ast.Name) and node.id in env:
        return env[node.id]
    raise ValueError(f"{name}: not a string constant expression")


@lru_cache(maxsize=1)
def _module_constants() -> dict[str, str]:
    """Deterministic per-process read of an immutable source file (no mutator:
    CLAUDE.md's lru_cache rule). Returns only top-level `E2E_*` strings."""
    tree = ast.parse(_SOURCE.read_text(encoding="utf-8"))
    env: dict[str, str] = {}
    for stmt in tree.body:
        if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
            targets, value = [stmt.target], stmt.value
        elif isinstance(stmt, ast.Assign):
            targets, value = stmt.targets, stmt.value
        else:
            continue
        names = [t.id for t in targets if isinstance(t, ast.Name) and t.id.startswith("E2E_")]
        if not names or value is None:
            continue
        try:
            text = _eval(value, env, names[0])
        except ValueError:
            continue  # not a string constant (a dict, a number, a call): never read here
        for n in names:
            env[n] = text
    return env


def read_constants(*names: str) -> tuple[str, ...]:
    """The named `E2E_*` string constants, in order. A name that is missing or
    not a plain string expression raises KeyError."""
    env = _module_constants()
    missing = [n for n in names if n not in env]
    if missing:
        raise KeyError(f"not string constants of function_handlers_e2e.py: {missing}")
    return tuple(env[n] for n in names)
