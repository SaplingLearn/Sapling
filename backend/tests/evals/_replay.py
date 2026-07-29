"""Record-and-replay layer for offline eval runs.

Mode is selected by the SAPLING_EVAL_MODE env var:
  - "record": run agents against live Gemini, write each response to a
    cassette file keyed by (dataset, case_name).
  - "replay" (default): load cassettes; if a case has no cassette, raise
    so CI fails loudly instead of silently skipping.
  - "live": run live; do not record. Useful for one-off experimentation.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from agents.deps import SaplingDeps


CASSETTE_DIR = Path(__file__).parent / "cassettes"
MODE = os.getenv("SAPLING_EVAL_MODE", "replay").lower()


def _safe_filename(name: str) -> str:
    """Cassette filename derived from the case name, slug-style."""
    return re.sub(r"[^A-Za-z0-9_\-]", "_", name)[:120]


def _cassette_path(dataset: str, case_name: str) -> Path:
    return CASSETTE_DIR / dataset / f"{_safe_filename(case_name)}.json"


def load_cassette(dataset: str, case_name: str) -> dict[str, Any] | None:
    p = _cassette_path(dataset, case_name)
    if not p.exists():
        return None
    return json.loads(p.read_text())


def save_cassette(dataset: str, case_name: str, output: Any) -> None:
    p = _cassette_path(dataset, case_name)
    p.parent.mkdir(parents=True, exist_ok=True)
    if hasattr(output, "model_dump"):
        body = output.model_dump(mode="json")
    else:
        body = output
    p.write_text(json.dumps(body, indent=2, sort_keys=True))


def make_deps() -> SaplingDeps:
    return SaplingDeps(
        user_id="eval-user",
        course_id="eval-course",
        supabase=None,
        request_id="eval",
    )


BASELINES_PATH = Path(__file__).parent / "baselines.json"

# Accuracy is measured, not assumed perfect: replay is deterministic (the model
# output is frozen in the cassette), so a task's aggregate score only moves when
# evaluators, expected outputs, or cassettes change. We gate on *regression*
# below a committed baseline rather than on "< 1.0" — the whole point of the
# harness is to track sub-100% accuracy over time. A small tolerance absorbs
# float noise.
BASELINE_TOLERANCE = 1e-6


def _aggregate_scores(report) -> dict[str, float]:
    """Mean of each evaluator's score across all (non-errored) cases."""
    sums: dict[str, float] = {}
    counts: dict[str, int] = {}
    for case in report.cases:
        for ev_name, result in case.scores.items():
            sums[ev_name] = sums.get(ev_name, 0.0) + float(result.value)
            counts[ev_name] = counts.get(ev_name, 0) + 1
    return {ev: sums[ev] / counts[ev] for ev in sums if counts[ev]}


def _load_baselines() -> dict[str, dict[str, float]]:
    if not BASELINES_PATH.exists():
        return {}
    return json.loads(BASELINES_PATH.read_text())


def _write_baselines(all_baselines: dict[str, dict[str, float]]) -> None:
    BASELINES_PATH.write_text(json.dumps(all_baselines, indent=2, sort_keys=True) + "\n")


def ensure_utf8_output() -> None:
    """Force UTF-8 on stdout/stderr.

    Cases carry non-ASCII content (e.g. Mandarin syllabi). rich renders the
    report through the console's native encoding, which is cp1252 on Windows
    when stdout is redirected/piped, and crashes on CJK. Forcing UTF-8 makes the
    harness run identically on every platform.
    """
    import sys

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def evaluate_dataset(make_dataset, run_fn, *, update: bool, print_report: bool = True) -> bool:
    """Evaluate one dataset, print an accuracy summary, and return ``ok``.

    ``ok`` is False when a case raised (e.g. a missing cassette in replay mode)
    or a task's aggregate evaluator score regressed below its committed baseline
    in ``baselines.json``. Sub-1.0 scores alone are NOT failures — the harness
    measures accuracy, it doesn't assume perfection. With ``update=True`` the
    current scores are written back as the new baseline (unless the run had
    failures). This function never calls ``sys.exit`` so callers can aggregate
    across datasets.
    """
    import asyncio
    import sys

    dataset = make_dataset()
    report = asyncio.run(dataset.evaluate(run_fn))
    if print_report:
        report.print(include_input=False, include_output=True)

    name = getattr(dataset, "name", None) or "unknown"
    scores = _aggregate_scores(report)

    print(f"\nAccuracy ({name}):")
    for ev_name in sorted(scores):
        print(f"  {ev_name}: {scores[ev_name]:.3f}")

    ok = True
    if report.failures:
        print(
            f"\n{len(report.failures)} case(s) raised during evaluation.",
            file=sys.stderr,
        )
        ok = False

    all_baselines = _load_baselines()

    if update:
        # Never persist baselines from a partially-broken run — that would bake
        # a crash's degraded scores in as the new "expected".
        if not ok:
            print(
                f"\nRefusing to update {name} baselines: run had case failures.",
                file=sys.stderr,
            )
            return False
        all_baselines[name] = {ev: round(scores[ev], 6) for ev in scores}
        _write_baselines(all_baselines)
        print(f"\nUpdated baselines for {name} in {BASELINES_PATH.name}.")
        return True

    baseline = all_baselines.get(name)
    if baseline is None:
        print(
            f"\nNo committed baseline for {name}; run with "
            "SAPLING_EVAL_UPDATE_BASELINES=1 to record one.",
            file=sys.stderr,
        )
    else:
        regressions: list[str] = []
        for ev_name, base in baseline.items():
            got = scores.get(ev_name)
            if got is None:
                regressions.append(f"{ev_name}: missing (baseline {base:.3f})")
            elif got < base - BASELINE_TOLERANCE:
                regressions.append(f"{ev_name}: {got:.3f} < baseline {base:.3f}")
        if regressions:
            print(
                f"\n{len(regressions)} accuracy regression(s) in {name} vs baseline:",
                file=sys.stderr,
            )
            for line in regressions:
                print(f"  - {line}", file=sys.stderr)
            ok = False

    return ok


def cli_main(make_dataset, run_fn) -> None:
    """Shared `__main__` entrypoint for a single eval script."""
    import sys

    ensure_utf8_output()
    update = os.getenv("SAPLING_EVAL_UPDATE_BASELINES") == "1"
    ok = evaluate_dataset(make_dataset, run_fn, update=update)
    if not ok:
        sys.exit(1)


async def run_with_cassette(
    *,
    dataset: str,
    case_name: str,
    agent,
    case_input: str,
    output_model,
):
    """Drive an agent through record/replay/live modes.

    `agent` is a Pydantic AI Agent; `output_model` is its `output_type` so we
    can hydrate replayed JSON back into the typed object that evaluators
    expect.
    """
    if MODE == "replay":
        body = load_cassette(dataset, case_name)
        if body is None:
            raise RuntimeError(
                f"No cassette for {dataset}/{case_name}. "
                f"Run with SAPLING_EVAL_MODE=record to capture it."
            )
        return output_model.model_validate(body)

    deps = make_deps()
    result = await _run_with_retry(agent, case_input, deps)
    output = result.output

    if MODE == "record":
        save_cassette(dataset, case_name, output)

    return output


# Gemini returns 503/UNAVAILABLE under load; a whole record run shouldn't lose a
# case (and leave a permanent cassette gap) to a transient blip. Retry only the
# transient provider errors, with linear backoff. Passed timestamps aren't
# available here and we're offline-recording, so a fixed short sleep is fine.
_TRANSIENT_RECORD_RETRIES = 4
_TRANSIENT_BACKOFF_SECONDS = 3.0


async def _run_with_retry(agent, case_input: str, deps):
    import asyncio

    last_exc: Exception | None = None
    for attempt in range(_TRANSIENT_RECORD_RETRIES + 1):
        try:
            return await agent.run(case_input, deps=deps)
        except Exception as exc:  # noqa: BLE001 - re-raised below if non-transient
            if not _is_transient(exc) or attempt == _TRANSIENT_RECORD_RETRIES:
                raise
            last_exc = exc
            await asyncio.sleep(_TRANSIENT_BACKOFF_SECONDS * (attempt + 1))
    # Unreachable: the loop either returns or raises. Kept for type-checkers.
    raise last_exc  # type: ignore[misc]


def _is_transient(exc: Exception) -> bool:
    status = getattr(exc, "status_code", None)
    if status in (429, 503):
        return True
    text = str(exc).upper()
    return "UNAVAILABLE" in text or "503" in text or "RESOURCE_EXHAUSTED" in text
