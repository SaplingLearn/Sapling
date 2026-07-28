"""`python -m e2e_oracles` — the #400 E2E Chapter 2 oracle CLI.

Invocation (from `backend/`):

    venv/bin/python -m e2e_oracles [--json] [--check NAME]... [--user ID] \\
        [--base-url URL] [--log PATH]

Check names: `graph`, `counts`, `ciphertext`, `logscan`, `orphans` — default
is all five, in that (sorted) order. `--check` may repeat to select a subset.

Exit codes: 0 clean / 1 findings / 2 infra error — a check that raises
becomes a single `Finding(oracle="oracle-error", ...)` and FORCES exit 2,
even if every other check came back clean (an infra failure means the run's
other results can't be trusted either).

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
        help="check to run (repeatable); default: all five",
    )
    parser.add_argument("--user", default="rich-user-active", help="user id to check")
    parser.add_argument(
        "--base-url", default="http://localhost:5000", help="local backend base URL"
    )
    parser.add_argument("--log", default=str(_DEFAULT_LOG), help="backend log path for logscan")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    from dotenv import load_dotenv

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
