"""Pass/fail a locust run against the plan's targets (#117).

Reads the `<prefix>_stats.csv` locust writes with ``--csv <prefix>`` and
exits non-zero when a target is missed:

* every non-LLM route (anything but the tutor's chat/start-session calls and
  the session setup): p95 under ``--max-p95-ms`` (300 ms);
* the tutor's time to first token (``chat_stream TTFT``): p95 under
  ``--max-ttft-p95-ms`` (3000 ms), when ``--require-chat`` (the run included
  the chat task);
* any route's failure ratio over ``--max-failure-ratio`` (1%) fails too: a
  run whose requests all bounce off a 401 in 5 ms is not a fast run.

Stdlib only, so the workflow runs it without installing anything more. The
logic is unit-tested hermetically (backend/tests/test_loadtest_thresholds.py).

    python loadtest/check_thresholds.py loadtest/out/run_stats.csv --require-chat
"""
from __future__ import annotations

import argparse
import csv
import sys
from dataclasses import dataclass

#: Locust's name for the tutor's time-to-first-token sample (locustfile.py).
TTFT_NAME = "chat_stream TTFT"
#: Rows that are not "non-LLM routes": the tutor's LLM calls, the one-off
#: session setup, and locust's own total row.
_LLM_OR_SETUP_PREFIXES = (
    "chat_stream ",                       # SSE TTFT / full turn
    "POST /api/learn/",                   # the chat stream's connect
    "learn start-session",                # a tutor greeting (LLM)
    "auth test-login",                    # setup, once per simulated user
)
AGGREGATED = "Aggregated"

DEFAULT_MAX_P95_MS = 300.0
DEFAULT_MAX_TTFT_P95_MS = 3000.0
DEFAULT_MAX_FAILURE_RATIO = 0.01


@dataclass(frozen=True)
class Row:
    type: str
    name: str
    requests: int
    failures: int
    p95_ms: float | None


def _num(value: str | None) -> float | None:
    try:
        return float(value) if value not in (None, "", "N/A") else None
    except ValueError:
        return None


def load_stats(path: str) -> list[Row]:
    """The per-name rows of a locust ``*_stats.csv`` (the Aggregated row
    included; callers skip it)."""
    with open(path, newline="") as fh:
        reader = csv.DictReader(fh)
        rows = []
        for r in reader:
            rows.append(Row(
                type=(r.get("Type") or "").strip(),
                name=(r.get("Name") or "").strip(),
                requests=int(_num(r.get("Request Count")) or 0),
                failures=int(_num(r.get("Failure Count")) or 0),
                p95_ms=_num(r.get("95%")),
            ))
        return rows


def is_non_llm(row: Row) -> bool:
    return row.name != AGGREGATED and not row.name.startswith(_LLM_OR_SETUP_PREFIXES)


def evaluate(
    rows: list[Row], *, max_p95_ms: float = DEFAULT_MAX_P95_MS,
    max_ttft_p95_ms: float = DEFAULT_MAX_TTFT_P95_MS,
    max_failure_ratio: float = DEFAULT_MAX_FAILURE_RATIO, require_chat: bool = False,
) -> tuple[list[str], list[str]]:
    """(failures, report lines). Empty failures = the run met every target."""
    failures: list[str] = []
    report: list[str] = []
    non_llm = [r for r in rows if is_non_llm(r) and r.requests > 0]
    if not non_llm:
        failures.append("no non-LLM requests were recorded: the run did not exercise the mix")
    for r in non_llm:
        ok = r.p95_ms is not None and r.p95_ms < max_p95_ms
        report.append(f"{'ok  ' if ok else 'FAIL'} {r.name}: p95 {r.p95_ms} ms "
                      f"(< {max_p95_ms:g}), {r.requests} requests")
        if not ok:
            failures.append(f"{r.name}: p95 {r.p95_ms} ms is not under {max_p95_ms:g} ms")

    ttft = next((r for r in rows if r.name == TTFT_NAME), None)
    if ttft is None or ttft.requests == 0:
        if require_chat:
            failures.append(f"no '{TTFT_NAME}' samples, but the run was meant to include chat")
    else:
        ok = ttft.p95_ms is not None and ttft.p95_ms < max_ttft_p95_ms
        report.append(f"{'ok  ' if ok else 'FAIL'} {TTFT_NAME}: p95 {ttft.p95_ms} ms "
                      f"(< {max_ttft_p95_ms:g}), {ttft.requests} turns")
        if not ok:
            failures.append(f"{TTFT_NAME}: p95 {ttft.p95_ms} ms is not under "
                            f"{max_ttft_p95_ms:g} ms")

    for r in rows:
        if r.name == AGGREGATED or r.requests == 0:
            continue
        ratio = r.failures / r.requests
        if ratio > max_failure_ratio:
            failures.append(f"{r.name}: {r.failures}/{r.requests} requests failed "
                            f"({ratio:.1%} > {max_failure_ratio:.1%})")
    return failures, report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("stats_csv", help="locust's <prefix>_stats.csv")
    ap.add_argument("--max-p95-ms", type=float, default=DEFAULT_MAX_P95_MS)
    ap.add_argument("--max-ttft-p95-ms", type=float, default=DEFAULT_MAX_TTFT_P95_MS)
    ap.add_argument("--max-failure-ratio", type=float, default=DEFAULT_MAX_FAILURE_RATIO)
    ap.add_argument("--require-chat", action="store_true",
                    help="fail when the run recorded no chat TTFT samples")
    args = ap.parse_args(argv)
    try:
        rows = load_stats(args.stats_csv)
    except OSError as exc:
        print(f"cannot read {args.stats_csv}: {exc}", file=sys.stderr)
        return 2
    failures, report = evaluate(
        rows, max_p95_ms=args.max_p95_ms, max_ttft_p95_ms=args.max_ttft_p95_ms,
        max_failure_ratio=args.max_failure_ratio, require_chat=args.require_chat,
    )
    print("\n".join(report))
    if failures:
        print("\nthresholds missed:", file=sys.stderr)
        for f in failures:
            print(f"  - {f}", file=sys.stderr)
        return 1
    print("\nall thresholds met")
    return 0


if __name__ == "__main__":
    sys.exit(main())
