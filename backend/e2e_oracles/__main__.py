"""`python -m e2e_oracles` — the #400 E2E Chapter 2 oracle CLI.

Invocation (from `backend/`):

    venv/bin/python -m e2e_oracles [--json] [--check NAME]... [--user ID] \\
        [--base-url URL] [--log PATH]

Check names: `graph`, `counts`, `ciphertext`, `logscan`, `orphans`, `ragstore`, `flags`
— default is all of them, in that (sorted) order. `--check` may repeat to select a subset.

Exit codes: 0 clean / 1 findings / 2 infra error — ANY `Finding(oracle=
"oracle-error", ...)` FORCES exit 2, even if every other check came back
clean (an infra failure means the run's other results can't be trusted
either). A check can produce that finding two ways: by raising (`main()`
catches it and synthesizes the finding itself) or by returning one directly
(e.g. `gather.run_logscan`'s missing-log-file case) — both are checked.

`CHECKS` is a thin registry (`name -> Callable[[argparse.Namespace],
tuple[list[Finding], int]]`) over `gather.run_<name>`; tests monkeypatch this
dict wholesale with fakes, so `main()` itself never opens a DB connection or
makes an HTTP call in the hermetic suite. `gather` carries no top-level side
effects (see its module docstring), so importing it here — needed to build
`CHECKS` at module scope, before `main()` runs — never trips the
`load_dotenv`-before-`services.*` ordering the deferred-import pattern
protects.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable
from pathlib import Path

from e2e_oracles import gather
from e2e_oracles.findings import Finding, render_json, render_text

# backend/e2e_oracles/__main__.py -> parents[1] = backend, parents[2] = repo root.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_LOG = _REPO_ROOT / ".e2e" / "backend.log"

CHECKS: dict[str, Callable[[argparse.Namespace], tuple[list[Finding], int]]] = {
    "graph": lambda args: gather.run_graph(args),
    "counts": lambda args: gather.run_counts(args),
    "ciphertext": lambda args: gather.run_ciphertext(args),
    "logscan": lambda args: gather.run_logscan(args),
    "orphans": lambda args: gather.run_orphans(args),
    "ragstore": lambda args: gather.run_ragstore(args),
    "flags": lambda args: gather.run_flags(args),
}


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m e2e_oracles",
        description="Run the #400 E2E Chapter 2 oracles against the local stack.",
    )
    parser.add_argument("--json", action="store_true", help="emit JSON instead of text")
    parser.add_argument(
        "--check",
        action="append",
        dest="checks",
        choices=sorted(CHECKS),
        help="check to run (repeatable); default: all",
    )
    parser.add_argument("--user", default="rich-user-active", help="user id to check")
    parser.add_argument(
        "--base-url",
        # The E2E slot's backend (scripts/lib/e2e-slot.sh exports it); 5000
        # is the classic CI stack.
        default=os.environ.get("E2E_BACKEND_URL", "").strip() or "http://localhost:5000",
        help="local backend base URL (default: $E2E_BACKEND_URL)",
    )
    parser.add_argument("--log", default=str(_DEFAULT_LOG), help="backend log path for logscan")
    return parser.parse_args(argv)


# Written by scripts/e2e-up.sh for the stack this checkout is running.
_STACK_MANIFEST = Path(__file__).resolve().parents[2] / ".e2e" / "stack.json"


def _adopt_e2e_stack(argv: list[str]) -> str | None:
    """Point the oracles at the E2E stack, or say why there is none.

    A cycle exports E2E_BACKEND_URL + SUPABASE_DB_URL for its slot. After a
    bare `make e2e-up`, .e2e/stack.json names the slot — adopted here, before
    backend/.env is loaded (load_dotenv never overrides, so the slot's DB URL
    wins over .env's). With neither, outside CI, the only stack left is the DEV
    one (:5000 / :54322): judging it would report on the wrong data, so refuse
    unless --base-url was given explicitly.
    """
    if os.environ.get("E2E_BACKEND_URL", "").strip():
        return None
    try:
        stack = json.loads(_STACK_MANIFEST.read_text())
    except (OSError, ValueError):
        stack = None
    if stack and stack.get("backendUrl") and stack.get("dbUrl"):
        os.environ["E2E_BACKEND_URL"] = stack["backendUrl"]
        os.environ["SUPABASE_DB_URL"] = stack["dbUrl"]
        return None
    if os.environ.get("CI") == "true" or any(a.startswith("--base-url") for a in argv):
        return None
    return (
        "no E2E stack to judge: E2E_BACKEND_URL is unset and there is no .e2e/stack.json. "
        "Outside CI the classic :5000/:54322 is the dev stack. Boot a slot "
        "(scripts/e2e-cycle.sh or make e2e-up), or `source .e2e/env.sh`."
    )


def main(argv: list[str] | None = None) -> int:
    from dotenv import load_dotenv

    problem = _adopt_e2e_stack(sys.argv[1:] if argv is None else argv)
    if problem:
        print(f"e2e_oracles: {problem}", file=sys.stderr)
        return 2

    # Must run before any real check imports config/services: populates
    # SUPABASE_DB_URL / SESSION_SECRET / ENCRYPTION_KEY etc. from backend/.env
    # (no override — an already-exported shell var still wins) so those
    # modules see real values instead of freezing empty defaults at import
    # time. Mirrors tests/integration/conftest.py's load-env-before-services
    # ordering.
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")

    args = _parse_args(argv)
    selected = args.checks or sorted(CHECKS)

    findings: list[Finding] = []
    suppressed = 0
    infra_error = False

    try:
        for name in selected:
            check = CHECKS[name]
            try:
                check_findings, check_suppressed = check(args)
            except Exception as exc:  # a crashing check is itself a finding
                infra_error = True
                findings.append(
                    Finding(oracle="oracle-error", summary=f"{name} crashed: {exc}")
                )
                continue
            findings.extend(check_findings)
            suppressed += check_suppressed
            if any(f.oracle == "oracle-error" for f in check_findings):
                # A check can signal an infra failure by RETURNING an
                # oracle-error finding (e.g. run_logscan's missing-log-file
                # case) rather than raising. Either way it forces exit 2 —
                # an oracle-error means the run's other results can't be
                # trusted.
                infra_error = True
    finally:
        gather.close_conn()

    output = render_json(findings, suppressed) if args.json else render_text(findings, suppressed)
    print(output)

    if infra_error:
        return 2
    if findings:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
