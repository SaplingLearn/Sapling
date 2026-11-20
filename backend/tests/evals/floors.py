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
    `_raised` (a run in which a case or an evaluator raised is a failed run for
    routing), `<routing>.recorded_under.<dataset>`: the model, prompt hash and
    schema hash every one of those runs was recorded under (runs recorded under
    different ones are refused), and `<routing>.runs` = N — the input
    `agents.loop_tutor.LOOP_ROUTABLE_TIERS` and `services.loop.guard.
    CONFRONT_TIERS` are pinned to (tests/test_loop_tutor_agent.py,
    tests/test_learning_misconceptions.py).

It refuses (exit 2) when a dataset has fewer than N recorded runs, or when the
runs do not all score the same evaluators. It prints each run and the floor, so
the hand-off can quote them. It never records anything itself.

`--check` validates baselines.json instead (D10; tests/test_eval_floors.py runs
it too): every floor of a routed dataset is the minimum of its routing block's
runs, every floor of a dataset with a committed run log (`runs/<dataset>_<date>
.jsonl`, the newest one) is the minimum of that log's last N recorded runs, and
any other floor belongs to a dataset named in SINGLE_RECORDING_FLOORS.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).parent))

from _replay import BASELINES_PATH, _load_baselines, _write_baselines  # noqa: E402

#: The committed run logs (one JSON line per evaluated dataset per run).
RUNS_DIR = Path(__file__).parent / "runs"
#: A40 06(s): the fewest recordings a floor may come from.
MIN_RUNS = 3
#: The confront routing block was written by hand at three decimals before
#: floors.py wrote routing blocks; a floor matches a run's score to this.
ROUTING_ROUNDING = 5e-4

#: Datasets whose committed floors predate the A40 06(s) rule: each is ONE
#: recording's replay score, with no run log behind it. Their next re-record
#: follows the README's three-run procedure and drops the name from here; a
#: dataset not named here needs recorded runs (`--check`).
SINGLE_RECORDING_FLOORS: dict[str, str] = {
    "document_classification": "re-recorded on Claude 2026-10-22, one run",
    "document_summary": "re-recorded on Claude 2026-10-22, one run",
    "concept_extraction": "re-recorded on Claude 2026-10-22, one run",
    "syllabus_extraction": "re-recorded on Claude 2026-10-22, one run",
    "quiz_generation": "re-recorded on Claude 2026-10-22, one run",
    "check_items": "PKG-04/A37 recordings, one run each (Gemini; re-record pending)",
    "grader": "the A33-finish recording, one run (Gemini; re-record pending)",
    "decisions": "PKG-05b recording, one run (re-record pending)",
    "loop_rung_judge": "a calibration of hand-written replies, gated at 1.0",
}


def recorded_runs(log_lines: list[dict], dataset: str, n: int) -> list[dict]:
    runs = [r for r in log_lines if r.get("dataset") == dataset and r.get("mode") == "record"]
    return runs[-n:] if len(runs) >= n else []


def floor_of(runs: list[dict]) -> dict[str, float]:
    names = {frozenset(r["scores"]) for r in runs}
    if len(names) != 1:
        raise ValueError("the runs do not score the same evaluators")
    (evaluators,) = names
    return {ev: min(r["scores"][ev] for r in runs) for ev in sorted(evaluators)}


def identity_of(runs: list[dict], dataset: str) -> dict:
    """The one `recorded_under` every run shares (model, prompt and schema
    hash); refused when a run has none or they differ — a floor and a routing
    decision stand on runs of ONE prompt on ONE model."""
    ids = [r.get("recorded_under") for r in runs]
    if not all(isinstance(i, dict) and i.get("model") and i.get("prompt_hash") for i in ids):
        raise ValueError(
            f"{dataset}: a run has no recorded_under (model, prompt hash); record it "
            "with this harness's SAPLING_EVAL_RUNS_LOG"
        )
    if any(i != ids[0] for i in ids):
        raise ValueError(f"{dataset}: the runs were recorded under different prompts or models")
    return dict(ids[0])


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
            block.setdefault("recorded_under", {})[name] = identity_of(runs, name)
    return out


# ── --check (D10): every floor is the minimum of its recorded runs ───────────


def routing_blocks(baselines: dict) -> dict[str, dict]:
    """Every routing block: a `*_routing` key holding `runs` and run lists."""
    return {
        k: v
        for k, v in baselines.items()
        if k.endswith("_routing") and isinstance(v, dict) and isinstance(v.get("runs"), int)
    }


def routed_runs(baselines: dict) -> dict[str, list[dict]]:
    """dataset -> its routing block's runs (scores only, `_raised` dropped).
    A dataset is keyed by its baselines name in exactly one block."""
    out: dict[str, list[dict]] = {}
    for key, block in routing_blocks(baselines).items():
        for name, runs in block.items():
            if isinstance(runs, list):
                if name in out:
                    raise ValueError(f"{name} has runs in two routing blocks (the second: {key})")
                out[name] = [{k: v for k, v in r.items() if not k.startswith("_")} for r in runs]
    return out


_LOG_NAME = re.compile(r"_(\d{4}-\d{2}-\d{2})\.jsonl$")


def logged_runs(runs_dir: Path, n: int = MIN_RUNS) -> dict[str, list[dict]]:
    """dataset -> the last `n` recorded runs of the NEWEST committed log naming
    it (logs are `<label>_<YYYY-MM-DD>.jsonl`; a later date wins)."""
    newest: dict[str, tuple[str, list[dict]]] = {}
    for path in sorted(runs_dir.glob("*.jsonl")):
        m = _LOG_NAME.search(path.name)
        if not m:
            continue
        lines = [json.loads(ln) for ln in path.read_text().splitlines() if ln.strip()]
        for name in {r.get("dataset") for r in lines}:
            if name and (name not in newest or m.group(1) > newest[name][0]):
                runs = [r["scores"] for r in recorded_runs(lines, name, n)]
                newest[name] = (m.group(1), runs)
    return {name: runs for name, (_date, runs) in newest.items()}


def floor_problems(baselines: dict, runs_dir: Path = RUNS_DIR) -> list[str]:
    """Every floor in `baselines` that is not the minimum of its recorded runs
    (D10). A routed dataset's runs are its routing block's (written at up to
    ROUTING_ROUNDING); another dataset's are its newest committed run log's."""
    problems: list[str] = []
    blocks = routing_blocks(baselines)
    for key, block in blocks.items():
        if block["runs"] < MIN_RUNS:
            problems.append(f"{key}: runs={block['runs']} < {MIN_RUNS} (A40 06(s))")
    try:
        routed = routed_runs(baselines)
    except ValueError as exc:
        return [*problems, str(exc)]
    for key, block in blocks.items():
        for name in (n for n, runs in block.items() if isinstance(runs, list)):
            if name not in baselines:
                problems.append(f"{key}.{name}: routing runs for a dataset with no floor")
            if len(block[name]) != block["runs"]:
                problems.append(f"{key}.{name}: {len(block[name])} runs, the block says {block['runs']}")
            if not isinstance((block.get("recorded_under") or {}).get(name), dict):
                problems.append(f"{key}.{name}: no recorded_under (model, prompt hash)")
    logged = logged_runs(runs_dir)
    for name, floor in sorted(baselines.items()):
        if name in blocks or not isinstance(floor, dict):
            continue
        runs, tol, source = routed.get(name), ROUTING_ROUNDING, "routing block"
        if runs is None:
            runs, tol, source = logged.get(name), 1e-6, "run log"
        if runs is None:
            if name not in SINGLE_RECORDING_FLOORS:
                problems.append(
                    f"{name}: no recorded runs (a routing block or runs/<dataset>_<date>.jsonl); "
                    f"a floor is the minimum of {MIN_RUNS} recordings (A40 06(s))"
                )
            continue
        if len(runs) < MIN_RUNS:
            problems.append(f"{name}: {len(runs)} recorded run(s) in its {source}, < {MIN_RUNS}")
            continue
        if any(set(r) != set(floor) for r in runs):
            problems.append(f"{name}: its {source} runs score other evaluators than its floor")
            continue
        for ev, value in sorted(floor.items()):
            low = min(r[ev] for r in runs)
            if abs(value - low) > tol:
                problems.append(
                    f"{name}.{ev}: floor {value} is not the minimum {low} of its {source} runs "
                    f"({' / '.join(str(r[ev]) for r in runs)})"
                )
    return problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--log", type=Path)
    ap.add_argument("--runs", type=int, default=MIN_RUNS)
    ap.add_argument("--datasets")
    ap.add_argument("--routing", default=None)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--check", action="store_true", help="validate baselines.json and exit")
    args = ap.parse_args(argv)
    if args.check:
        problems = floor_problems(_load_baselines())
        for line in problems:
            print(f"  - {line}", file=sys.stderr)
        print("floors: OK" if not problems else f"floors: {len(problems)} problem(s)")
        return 1 if problems else 0
    if args.log is None or not args.datasets:
        ap.error("--log and --datasets are required (or --check)")
    if args.runs < MIN_RUNS:
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
        if args.routing:
            print(f"  recorded under: {updated[args.routing]['recorded_under'][name]}")
    if not args.dry_run:
        _write_baselines(updated)
        print(f"\nWrote {BASELINES_PATH.name}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
