"""Eval floors from repeated recordings (spec §13 A40 06(s), PKG-14).

A floor set from one recording is not accepted: record the dataset N times with
SAPLING_EVAL_RUNS_LOG=<log> (each run appends one JSON line per dataset, see
_replay.RUNS_LOG_ENV), then:

    cd backend
    python tests/evals/floors.py --log <log> --runs 3 \\
        --datasets loop_tutor_deep --routing loop_tutor_routing

For every named dataset it takes the LAST `--runs` recorded runs in the log
(mode `record`), and writes to baselines.json:

  - `<dataset>`: the MINIMUM score per evaluator across those runs (the floor);
  - with --routing, `<routing>.<dataset>`: the per-run score blocks, each with
    `_raised` (always False: see the refusals), `<routing>.recorded_under.
    <dataset>`: the model, prompt hash and schema hash every one of those runs
    was recorded under, and `<routing>.runs` = N — the input
    `agents.loop_tutor.LOOP_ROUTABLE_TIERS` and `services.loop.guard.
    CONFRONT_TIERS` are pinned to (tests/test_loop_tutor_agent.py,
    tests/test_learning_misconceptions.py).

It refuses (exit 2), routed dataset or not, when a dataset has fewer than N
recorded runs, when one of them raised (a case or an evaluator: its scores
average only what finished), when the runs were recorded under different
prompts, schemas or models, or when they do not all score the same evaluators.
It prints each run and the floor, so the hand-off can quote them. It never
records anything itself.

`--check` validates baselines.json instead (D10; tests/test_eval_floors.py runs
it too): every floor of a routed dataset is the minimum of its routing block's
runs, every floor of a dataset with a committed run log (`runs/<dataset>_<date>
.jsonl`, the newest one) is the minimum of that log's last N recorded runs, and
any other floor belongs to a dataset named in SINGLE_RECORDING_FLOORS. None of
those runs raised, and a logged run that names what it was recorded under
(`recorded_under`) names one identity, the one the dataset records under TODAY
(`current_identities`): a floor is evidence about the current prompt. A log
whose lines carry no `recorded_under` is compared by score only. The identities
come from the eval modules, so `--check` imports the agents (ENCRYPTION_KEY set
to any 64 hex characters; no model, no network).
"""

from __future__ import annotations

import argparse
import importlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).parent))

from _replay import (  # noqa: E402
    BASELINES_PATH,
    _load_baselines,
    _recorded_under_of,
    _write_baselines,
)

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
    "loop_rung_judge": "a calibration of hand-written replies, gated at 1.0",
}


#: The eval modules whose run functions name what they record under
#: (`run_fn.recorded_under`), so whose run-log lines carry it.
IDENTITY_MODULES = ("loop_tutor", "misconception_confront")


def current_identities() -> dict[str, dict]:
    """dataset -> what it records under today (model, prompt and schema hash),
    for every dataset of IDENTITY_MODULES, its recorded and unrecorded variants
    alike, whatever LOOP_EVAL_VARIANT this process runs under."""
    evals = Path(__file__).resolve().parent
    saved = list(sys.path)
    sys.path[:0] = [str(evals.parents[1]), str(evals)]
    try:
        out: dict[str, dict] = {}
        for module in IDENTITY_MODULES:
            mod = importlib.import_module(module)
            variants = mod.replay_variants(v2=False, recorded=lambda _space: True)
            for name, (_make, run_fn) in variants.items():
                identity = _recorded_under_of(run_fn)
                if identity is not None:
                    out[name] = identity
        return out
    finally:
        sys.path[:] = saved


def recorded_runs(log_lines: list[dict], dataset: str, n: int) -> list[dict]:
    runs = [r for r in log_lines if r.get("dataset") == dataset and r.get("mode") == "record"]
    return runs[-n:] if len(runs) >= n else []


def floor_of(runs: list[dict]) -> dict[str, float]:
    names = {frozenset(r["scores"]) for r in runs}
    if len(names) != 1:
        raise ValueError("the runs do not score the same evaluators")
    (evaluators,) = names
    return {ev: min(r["scores"][ev] for r in runs) for ev in sorted(evaluators)}


def run_problems(runs: list[dict], dataset: str) -> list[str]:
    """Why these run-log lines cannot back one floor: a run raised (its scores
    average only the cases and evaluators that finished, so a crash can read as
    1.0), or they were recorded under different identities (a run that names
    none differs from one that does)."""
    problems: list[str] = []
    raised = [i for i, r in enumerate(runs, 1) if r.get("raised")]
    if raised:
        problems.append(
            f"{dataset}: recorded run(s) {raised} of {len(runs)} raised (a case or an "
            "evaluator); a floor comes from complete runs only"
        )
    ids = [r.get("recorded_under") for r in runs]
    if any(i != ids[0] for i in ids):
        problems.append(
            f"{dataset}: the runs were recorded under different prompts or models "
            f"({' / '.join(str(i) for i in ids)})"
        )
    return problems


def identity_of(runs: list[dict], dataset: str) -> dict:
    """The one `recorded_under` every run shares (model, prompt and schema
    hash), for a routing block; refused when a run has none or they differ — a
    floor and a routing decision stand on runs of ONE prompt on ONE model."""
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
        bad = run_problems(runs, name)
        if bad:
            raise ValueError("; ".join(bad))
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
    """dataset -> the last `n` recorded runs (whole log lines) of the NEWEST
    committed log naming it (logs are `<label>_<YYYY-MM-DD>.jsonl`; a later date
    wins)."""
    newest: dict[str, tuple[str, list[dict]]] = {}
    for path in sorted(runs_dir.glob("*.jsonl")):
        m = _LOG_NAME.search(path.name)
        if not m:
            continue
        lines = [json.loads(ln) for ln in path.read_text().splitlines() if ln.strip()]
        for name in {r.get("dataset") for r in lines}:
            if name and (name not in newest or m.group(1) > newest[name][0]):
                newest[name] = (m.group(1), recorded_runs(lines, name, n))
    return {name: runs for name, (_date, runs) in newest.items()}


def stale_problems(runs: list[dict], dataset: str, identities: dict[str, dict]) -> list[str]:
    """Every identity these runs were recorded under that is not the one
    `dataset` records under today. Runs that name none have nothing to compare;
    a named one no eval module answers for is a problem, not a pass."""
    recorded = [r["recorded_under"] for r in runs if r.get("recorded_under") is not None]
    if not recorded:
        return []
    today = identities.get(dataset)
    if today is None:
        return [
            f"{dataset}: its run log names what it was recorded under, but no eval module in "
            "IDENTITY_MODULES says what the dataset records under today"
        ]
    stale = [i for i in recorded if i != today]
    if not stale:
        return []
    keys = [k for k in sorted({*today, *stale[0]}) if stale[0].get(k) != today.get(k)]
    moved = ", ".join(f"{k} {stale[0].get(k)} -> {today.get(k)}" for k in keys)
    return [
        f"{dataset}: {len(stale)} of {len(runs)} run log runs were recorded under another "
        f"identity than the dataset's current one ({moved}); re-record it"
    ]


def floor_problems(
    baselines: dict, runs_dir: Path = RUNS_DIR, identities: dict[str, dict] | None = None
) -> list[str]:
    """Every floor in `baselines` that is not the minimum of its recorded runs
    (D10), or whose runs raised, mix identities or are not the current one's. A
    routed dataset's runs are its routing block's (written at up to
    ROUTING_ROUNDING); another dataset's are its newest committed run log's.
    `identities` is what each dataset records under today (default: read from
    the eval modules, when a log names one)."""
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
            raised = [i for i, r in enumerate(block[name], 1) if r.get("_raised")]
            if raised:
                problems.append(f"{key}.{name}: routing run(s) {raised} raised")
    logged = logged_runs(runs_dir)
    for name, floor in sorted(baselines.items()):
        if name in blocks or not isinstance(floor, dict):
            continue
        lines = logged.get(name) or []
        problems += run_problems(lines, name)
        if any(r.get("recorded_under") is not None for r in lines):
            if identities is None:
                identities = current_identities()
            problems += stale_problems(lines, name, identities)
        runs, tol, source = routed.get(name), ROUTING_ROUNDING, "routing block"
        if runs is None:
            runs, tol, source = [r["scores"] for r in lines], 1e-6, "run log"
        if name not in routed and name not in logged:
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
