"""Run every offline eval dataset in one process and report a combined result.

    cd backend
    python tests/evals/run_all.py                     # replay (default), gate on baselines
    SAPLING_EVAL_MODE=record python tests/evals/run_all.py            # refresh cassettes
    SAPLING_EVAL_UPDATE_BASELINES=1 python tests/evals/run_all.py     # refresh baselines

Exits non-zero if any dataset regressed below its committed baseline or had a
case failure (e.g. a missing cassette). This is the single command CI runs and
the one to run locally before changing an agent's prompt or model.

``chat_tutor`` is intentionally excluded: its retrieval tool reads a live
Supabase and cannot run offline against cassettes. Bringing it into the harness
is tracked with the graph-grounded tutor work (#149).
"""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

# `python tests/evals/run_all.py` from backend/: add backend/ (for `agents.*`)
# and tests/evals/ (so the datasets' top-level `from _replay import ...` and the
# `import <dataset>` below both resolve).
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _replay import ensure_utf8_output, evaluate_dataset  # noqa: E402

# Offline datasets only. Keep in sync with the datasets that have cassettes.
DATASETS = [
    "document_classification",
    "document_summary",
    "concept_extraction",
    "syllabus_extraction",
    "quiz_generation",
]


def main() -> None:
    ensure_utf8_output()
    update = os.getenv("SAPLING_EVAL_UPDATE_BASELINES") == "1"

    results: list[tuple[str, bool]] = []
    for name in DATASETS:
        mod = importlib.import_module(name)
        print(f"\n{'=' * 78}\n{name}\n{'=' * 78}")
        # Suppress the giant per-case rich table here; the per-task accuracy
        # summary and any regression lines still print.
        ok = evaluate_dataset(mod.make_dataset, mod._run, update=update, print_report=False)
        results.append((name, ok))

    print(f"\n{'=' * 78}\nSummary\n{'=' * 78}")
    for name, ok in results:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")

    if not all(ok for _, ok in results):
        sys.exit(1)


if __name__ == "__main__":
    main()
