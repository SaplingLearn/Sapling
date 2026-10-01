"""Eval floors from repeated recordings (spec §13 A40 06(s), PKG-14).

A floor set from one recording is not accepted: record the dataset N times with
SAPLING_EVAL_RUNS_LOG=<log> (each run appends one JSON line per dataset, see
_replay.RUNS_LOG_ENV), then:

    cd backend
    python tests/evals/floors.py --log <log> --runs 3 \\
        --datasets loop_tutor_lite,loop_tutor,loop_tutor_deep --routing loop_tutor_routing

For every named dataset it takes the LAST `--runs` recorded runs in the log
(mode `record`), and writes to baselines.json:

  - `<dataset>`: the MINIMUM score per evaluator across those runs (the floor);
  - with --routing, `<routing>.<dataset>`: the per-run score blocks, each with
    `_raised` (a run in which a case raised is a failed run for routing), and
    `<routing>.runs` = N — the input `agents.loop_tutor.LOOP_ROUTABLE_TIERS`
    is pinned to (tests/test_loop_tutor_agent.py).

It refuses (exit 2) when a dataset has fewer than N recorded runs, or when the
runs do not all score the same evaluators. It prints each run and the floor, so
the hand-off can quote them. It never records anything itself.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).parent))

from _replay import BASELINES_PATH, _load_baselines, _write_baselines  # noqa: E402


def recorded_runs(log_lines: list[dict], dataset: str, n: int) -> list[dict]:
    runs = [r for r in log_lines if r.get("dataset") == dataset and r.get("mode") == "record"]
    return runs[-n:] if len(runs) >= n else []


def floor_of(runs: list[dict]) -> dict[str, float]:
    names = {frozenset(r["scores"]) for r in runs}
    if len(names) != 1:
        raise ValueError("the runs do not score the same evaluators")
    (evaluators,) = names
    return {ev: min(r["scores"][ev] for r in runs) for ev in sorted(evaluators)}


def apply_floors(
    baselines: dict,
    log_lines: list[dict],
    datasets: list[str],
    *,
    n: int,
    routing: str | None,
) -> dict:
    """baselines.json with each dataset's floor (and routing runs) replaced."""
    out = json.loads(json.dumps(baselines))
    for name in datasets:
        runs = recorded_runs(log_lines, name, n)
        if not runs:
            raise ValueError(f"{name}: fewer than {n} recorded runs in the log")
        out[name] = floor_of(runs)
        if routing:
            block = out.setdefault(routing, {})
            block["runs"] = n
            block[name] = [{**r["scores"], "_raised": bool(r.get("raised"))} for r in runs]
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--log", required=True, type=Path)
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--datasets", required=True)
    ap.add_argument("--routing", default=None)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    if args.runs < 3:
        print("A40 06(s): a floor is the minimum of at least 3 recordings", file=sys.stderr)
        return 2
    lines = [json.loads(ln) for ln in args.log.read_text().splitlines() if ln.strip()]
    datasets = [d for d in args.datasets.split(",") if d]
    try:
        updated = apply_floors(
            _load_baselines(), lines, datasets, n=args.runs, routing=args.routing
        )
    except ValueError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    for name in datasets:
        runs = recorded_runs(lines, name, args.runs)
        print(f"\n{name}:")
        for ev in sorted(updated[name]):
            per_run = " / ".join(f"{r['scores'][ev]:.3f}" for r in runs)
            print(f"  {ev}: {per_run}  → floor {updated[name][ev]:.3f}")
        print(f"  raised: {[bool(r.get('raised')) for r in runs]}")
    if not args.dry_run:
        _write_baselines(updated)
        print(f"\nWrote {BASELINES_PATH.name}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
