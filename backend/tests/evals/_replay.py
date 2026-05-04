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


def cli_main(make_dataset, run_fn) -> None:
    """Shared `__main__` entrypoint for eval scripts.

    Runs the dataset, prints a report, and exits non-zero when any case
    raised (e.g. missing cassette in replay mode) or any evaluator score
    is below 1.0. Without this, pydantic-evals catches per-case errors
    and the script exits 0, which would let CI silently rubber-stamp a
    completely-broken run.
    """
    import asyncio
    import sys

    dataset = make_dataset()
    report = asyncio.run(dataset.evaluate(run_fn))
    report.print(include_input=False, include_output=True)

    failed = False
    if report.failures:
        print(
            f"\n{len(report.failures)} case(s) raised during evaluation.",
            file=sys.stderr,
        )
        failed = True

    # Surface any evaluator score < 1.0 as a CI failure.
    bad_scores: list[str] = []
    for case in report.cases:
        for ev_name, result in case.scores.items():
            if result.value < 1.0:
                bad_scores.append(f"{case.name}:{ev_name}={result.value}")
    if bad_scores:
        print(
            f"\n{len(bad_scores)} evaluator score(s) below 1.0:",
            file=sys.stderr,
        )
        for line in bad_scores:
            print(f"  - {line}", file=sys.stderr)
        failed = True

    if failed:
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
    result = await agent.run(case_input, deps=deps)
    output = result.output

    if MODE == "record":
        save_cassette(dataset, case_name, output)

    return output
