"""Record-and-replay layer for offline eval runs.

Mode is selected by the SAPLING_EVAL_MODE env var:
  - "record": run agents against their live model, write each response to a
    cassette file keyed by (dataset, case_name).
  - "replay" (default): load cassettes; if a case has no cassette, raise
    so CI fails loudly instead of silently skipping.
  - "live": run live; do not record. Useful for one-off experimentation.

Every mode runs without a database: the AI budget reads an empty in-memory
store (`hermetic_budget`, below), and a model run's usage is captured, never
enqueued (`usage_log`; SAPLING_EVAL_USAGE_LOG writes it to a file).
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
from collections import Counter
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter

from agents.deps import SaplingDeps


CASSETTE_DIR = Path(__file__).parent / "cassettes"
MODE = os.getenv("SAPLING_EVAL_MODE", "replay").lower()


# ── The AI budget's store: empty and in memory ────────────────────────────────
#
# `services.ai_budget.check` reads the student's `llm_usage` rows before every
# grader, decision, close and tutor run (spec §3.5); a tutor run also reads and
# bumps today's `ai_tutor_daily_calls` row. The eval runner has no Supabase:
# `SUPABASE_URL` is empty, so every read failed with "Request URL is missing an
# 'http://' or 'https://' protocol.", logged one WARNING per graded case (31 per
# replay of the `grader` dataset, the noise in the `evals` CI job) and failed
# open. With a developer's `backend/.env` present, `db/connection.py`'s
# `load_dotenv()` sent the same read to whatever database that file names, so a
# replay's budget decisions could depend on that database's rows for `eval-user`.
#
# `hermetic_budget()` points ai_budget's two store seams, its module-level
# `table` and `rpc`, at `BudgetStore`: no recorded usage, so every check sees
# what a student with no spend gets. That is the decision the failed read's
# fail-open produced (normal, for every kind the evals reach), so no replay
# result moves. The tutor-call bump counts in memory and the tutor-call read
# returns that count. Any other table or function raises LookupError, so a new
# budget read is a deliberate decision here, never a silent network call. The
# production warning in services/ai_budget.py is unchanged. `evaluate_dataset`
# (every dataset, from run_all.py and each module's cli_main) runs inside it;
# tests/test_eval_budget_hermetic.py pins it.


class _EmptyLedger:
    """A `db.connection.SupabaseTable` stand-in for `llm_usage`: no rows."""

    def __init__(self, store: "BudgetStore", name: str):
        self._store = store
        self.name = name

    def select(self, columns="*", filters=None, order=None, limit=None, offset=None, timeout=None):
        self._store.reads.append((self.name, dict(filters or {})))
        return []

    def select_with_count(
        self, columns="*", filters=None, order=None, limit=None, offset=None, timeout=None
    ):
        return self.select(columns, filters, order, limit, offset, timeout), 0


def _eq(value: object) -> str:
    text = str(value or "")
    return text[3:] if text.startswith("eq.") else text


class _TutorCalls(_EmptyLedger):
    """`ai_tutor_daily_calls`: the count the in-memory bump wrote, if any."""

    def select(self, columns="*", filters=None, order=None, limit=None, offset=None, timeout=None):
        super().select(columns, filters, order, limit, offset, timeout)
        key = (_eq((filters or {}).get("user_id")), _eq((filters or {}).get("day")))
        calls = self._store.tutor_calls.get(key, 0)
        return [{"calls": calls}] if calls else []


class BudgetStore:
    """The AI budget's store for one eval run: no usage; tutor calls counted in memory."""

    def __init__(self) -> None:
        from services import ai_budget

        self._tables = {"llm_usage": _EmptyLedger, ai_budget._TUTOR_CALLS_TABLE: _TutorCalls}
        self._bump = ai_budget._TUTOR_CALLS_RPC
        self.reads: list[tuple[str, dict]] = []
        self.tutor_calls: Counter[tuple[str, str]] = Counter()

    def table(self, name: str):
        if name not in self._tables:
            raise LookupError(f"the eval budget store has no table {name!r}")
        return self._tables[name](self, name)

    def rpc(self, function_name: str, params: dict):
        if function_name != self._bump:
            raise LookupError(f"the eval budget store has no function {function_name!r}")
        key = (params["p_user_id"], params["p_day"])
        self.tutor_calls[key] += 1
        return self.tutor_calls[key]


@contextlib.contextmanager
def hermetic_budget() -> Iterator[BudgetStore]:
    """Run the block with `services.ai_budget` reading a fresh `BudgetStore`.

    Clears the module's per-process caches on entry and on exit, so no decision
    cached outside the block is used inside it or the other way round, and puts
    the module's own `table` and `rpc` back afterwards, whatever the block raised."""
    from services import ai_budget

    store = BudgetStore()
    saved = (ai_budget.table, ai_budget.rpc)
    ai_budget.reset_for_tests()
    ai_budget.table, ai_budget.rpc = store.table, store.rpc
    try:
        yield store
    finally:
        ai_budget.table, ai_budget.rpc = saved
        ai_budget.reset_for_tests()


#: spec §13 A137: SAPLING_EVAL_USAGE_LOG=<path> appends one JSON line per model
#: run a record or live evaluation makes (dataset, task, model, prompt /
#: completion / cached / thinking tokens, requests, cost_usd as llm_usage would
#: cost it), so a re-record measures what scripts/project_loop_cost.py has to
#: assume. Replay makes no run and writes nothing. Set or not, a run's usage
#: never reaches the events queue: the harness has no database.
USAGE_LOG_ENV = "SAPLING_EVAL_USAGE_LOG"


@contextlib.contextmanager
def usage_log(dataset: str) -> Iterator[list[dict]]:
    """Capture every `events_service.log_llm_usage` call of the block (each agent
    run reports through it) instead of enqueueing it; yield the captured rows."""
    from services import events_service

    rows: list[dict] = []
    path = os.getenv(USAGE_LOG_ENV)
    saved = events_service.log_llm_usage

    def capture(*, feature, task, model, usage, provider=None, user_id=None, request_id=None,
                cached_tokens=None, thinking_tokens=None, session_id=None, requests=None,
                course_id=None):
        row = events_service.build_llm_usage_row(
            feature=feature, task=task, model=model, usage=usage, provider=provider,
            cached_tokens=cached_tokens, thinking_tokens=thinking_tokens, requests=requests,
        )
        line = {
            "dataset": dataset,
            **{k: row[k] for k in ("feature", "task", "model", "prompt_tokens", "completion_tokens",
                                   "total_tokens", "cached_tokens", "thinking_tokens", "cost_usd")},
            "requests": requests or getattr(usage, "requests", None),
        }
        rows.append(line)
        if path:
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(line, sort_keys=True, default=str) + "\n")

    events_service.log_llm_usage = capture
    try:
        yield rows
    finally:
        events_service.log_llm_usage = saved


def _safe_filename(name: str) -> str:
    """Cassette filename derived from the case name, slug-style."""
    return re.sub(r"[^A-Za-z0-9_\-]", "_", name)[:120]


def _cassette_path(dataset: str, case_name: str) -> Path:
    return CASSETTE_DIR / dataset / f"{_safe_filename(case_name)}.json"


def load_cassette(dataset: str, case_name: str) -> dict[str, Any] | None:
    p = _cassette_path(dataset, case_name)
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def save_cassette(dataset: str, case_name: str, output: Any) -> None:
    p = _cassette_path(dataset, case_name)
    p.parent.mkdir(parents=True, exist_ok=True)
    if hasattr(output, "model_dump"):
        body = output.model_dump(mode="json")
    else:
        body = output
    p.write_text(json.dumps(body, indent=2, sort_keys=True))


# ── What a recording was made under (D4) ──────────────────────────────────────
#
# A cassette keyed by case name alone replays whatever the model said for that
# name, so a case whose prompt was swapped (for an injection, say) still scored
# the old answer. A recording therefore stores what it was recorded under —
# the agent's prompt hash (its fixed prompt and the tools it is sent), the
# output schema's hash, the slot's model and the hash of the exact message
# (plus the run's settings) — and replay raises StaleRecordingError on any
# difference, as the loop datasets have since PKG-07. A cassette written before
# a dataset stored these fails closed until it is re-recorded.


class StaleRecordingError(RuntimeError):
    """A cassette recorded under another prompt, schema, model or input."""


def text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def schema_hash(output_type: Any) -> str:
    """The JSON schema the model is sent for `output_type` (field descriptions
    included), hashed."""
    schema = TypeAdapter(output_type).json_schema()
    return hashlib.sha256(json.dumps(schema, sort_keys=True).encode("utf-8")).hexdigest()[:12]


def tool_defs(agent: Any) -> list[dict]:
    """The function tools `agent` sends the model: name, description and
    parameter schema, in registration order."""
    toolset = getattr(agent, "_function_toolset", None)
    tools = getattr(toolset, "tools", None) or {}
    out = []
    for tool in tools.values():
        d = tool.tool_def
        out.append(
            {
                "name": d.name,
                "description": d.description,
                "parameters": d.parameters_json_schema,
            }
        )
    return out


def prompt_identity(prompt_hash: str, agent: Any = None) -> str:
    """The agent's own prompt hash, extended by the tool definitions it sends
    (a tool's description or parameters are prompt too). An agent with no tools
    keeps its own hash."""
    tools = tool_defs(agent) if agent is not None else []
    if not tools:
        return prompt_hash
    body = prompt_hash + "\x00" + json.dumps(tools, sort_keys=True, default=str)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()[:12]


def run_settings(agent: Any, *, model: Any = None, extra: Any = None) -> dict:
    """The model settings a run is sent with: the model's own (a Claude slot's
    effort and max_tokens), the agent's, then the run's `extra`, later keys
    winning as in pydantic-ai. `model` overrides the agent's model (a run on
    another slot)."""
    m = model if model is not None else getattr(agent, "model", None)
    return {
        **dict(getattr(m, "settings", None) or {}),
        **dict(getattr(agent, "model_settings", None) or {}),
        **dict(extra or {}),
    }


def input_identity(message: str, settings: Any = None) -> str:
    """The message the model is sent plus the run's model settings."""
    body = message
    if settings:
        body += "\x00" + json.dumps(dict(settings), sort_keys=True, default=str)
    return text_sha256(body)


def recorded_under(*, prompt_hash: str, schema_hash: str, model: str, input_sha256: str) -> dict:
    return {
        "prompt_hash": prompt_hash,
        "schema_hash": schema_hash,
        "model": model,
        "input_sha256": input_sha256,
    }


def check_recorded_under(where: str, got: Any, expected: dict) -> None:
    """Raise StaleRecordingError unless `got` (a cassette's `recorded_under`)
    is `expected` exactly."""
    if not isinstance(got, dict):
        raise StaleRecordingError(
            f"Stale recording {where}: recorded before cassettes stored the prompt, "
            "schema, model and input they were recorded under. Re-record with "
            "SAPLING_EVAL_MODE=record."
        )
    names = {"prompt_hash": "prompt", "schema_hash": "output schema",
             "model": "model", "input_sha256": "message or run settings"}
    problems = [
        f"{names.get(k, k)} changed ({got.get(k)!r} -> {v!r})"
        for k, v in expected.items()
        if got.get(k) != v
    ]
    problems += [f"unexpected {k!r}" for k in sorted(set(got) - set(expected))]
    if problems:
        raise StaleRecordingError(
            f"Stale recording {where}: {'; '.join(problems)}. "
            "Re-record with SAPLING_EVAL_MODE=record."
        )


def save_recording(dataset: str, case_name: str, output: Any, identity: dict) -> None:
    """A cassette with what it was recorded under: {"output", "recorded_under"}."""
    body = output.model_dump(mode="json") if hasattr(output, "model_dump") else output
    save_cassette(dataset, case_name, {"output": body, "recorded_under": identity})


def load_recording(dataset: str, case_name: str, identity: dict) -> Any:
    """The recorded output of a case, after checking it was recorded under
    `identity`; a missing cassette raises like run_with_cassette."""
    body = load_cassette(dataset, case_name)
    if body is None:
        raise RuntimeError(
            f"No cassette for {dataset}/{case_name}. "
            "Run with SAPLING_EVAL_MODE=record to capture it."
        )
    got = body.get("recorded_under") if isinstance(body, dict) else None
    check_recorded_under(f"{dataset}/{case_name}", got, identity)
    return body["output"]


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
    """Mean of each evaluator's score across all (non-errored) cases. An
    evaluator that RAISED on a case scores 0.0 there: pydantic-evals files the
    crash under `case.evaluator_failures` and leaves the score out, so an
    evaluator that crashed on 9 of 10 cases used to average 1.000 over the one
    it finished (D3). `_evaluator_failures` also fails the run."""
    sums: dict[str, float] = {}
    counts: dict[str, int] = {}
    for case in report.cases:
        for ev_name, result in case.scores.items():
            sums[ev_name] = sums.get(ev_name, 0.0) + float(result.value)
            counts[ev_name] = counts.get(ev_name, 0) + 1
        for failure in getattr(case, "evaluator_failures", None) or []:
            sums[failure.name] = sums.get(failure.name, 0.0)
            counts[failure.name] = counts.get(failure.name, 0) + 1
    return {ev: sums[ev] / counts[ev] for ev in sums if counts[ev]}


def _evaluator_failures(report) -> list[str]:
    """Every evaluator crash in `report`, one line each: per case, then the
    report-level evaluators'. A crash is a failed run, like a case that raised."""
    lines = [
        f"{case.name}: {failure.name}: {failure.error_message}"
        for case in report.cases
        for failure in getattr(case, "evaluator_failures", None) or []
    ]
    lines += [
        f"(report) {failure.name}: {failure.error_message}"
        for failure in getattr(report, "report_evaluator_failures", None) or []
    ]
    return lines


def _load_baselines() -> dict[str, dict[str, float]]:
    if not BASELINES_PATH.exists():
        return {}
    return json.loads(BASELINES_PATH.read_text(encoding="utf-8"))


def _write_baselines(all_baselines: dict[str, dict[str, float]]) -> None:
    BASELINES_PATH.write_text(json.dumps(all_baselines, indent=2, sort_keys=True) + "\n")


#: A40 06(s) (PKG-14): an eval floor is the MINIMUM of LOOP-style repeated
#: recordings, never one. With SAPLING_EVAL_RUNS_LOG=<path>, every evaluated
#: dataset appends one JSON line {"dataset", "mode", "scores", "raised"} to
#: <path> — plus "recorded_under" (model, prompt and schema hash) for a dataset
#: whose run function names it (`run_fn.recorded_under`, the routed loop
#: datasets); tests/evals/floors.py turns N such runs into the floors (and a
#: routing block). Unset, nothing is written.
RUNS_LOG_ENV = "SAPLING_EVAL_RUNS_LOG"


def _log_run(
    name: str, scores: dict[str, float], *, raised: bool, recorded_under: dict | None = None
) -> None:
    path = os.getenv(RUNS_LOG_ENV)
    if not path:
        return
    line = {
        "dataset": name,
        "mode": MODE,
        "scores": {ev: round(v, 6) for ev, v in sorted(scores.items())},
        "raised": raised,
    }
    if recorded_under is not None:
        line["recorded_under"] = recorded_under
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(line, sort_keys=True) + "\n")


def _recorded_under_of(run_fn) -> dict | None:
    """What a run function's recordings are made under, when it says
    (`run_fn.recorded_under()`: the routed loop datasets)."""
    fn = getattr(run_fn, "recorded_under", None)
    return dict(fn()) if callable(fn) else None


def _routing_block_of(all_baselines: dict, name: str) -> str | None:
    """The `*_routing` block holding `name`'s routing runs, if any."""
    for key, block in all_baselines.items():
        if key.endswith("_routing") and isinstance(block, dict) and isinstance(block.get(name), list):
            return key
    return None


def _update_routed(
    all_baselines: dict, name: str, routing: str, current: dict | None = None
) -> bool:
    """SAPLING_EVAL_UPDATE_BASELINES for a ROUTED dataset (D6): its floor is the
    minimum of the block's N recordings and the block says what they were
    recorded under, so one run never rewrites either. The floor, the runs and
    `recorded_under` are rewritten together from SAPLING_EVAL_RUNS_LOG's last N
    recorded runs (floors.apply_floors); with fewer, or with runs recorded
    under anything but `current` (what the dataset records under today), the
    update is refused."""
    import sys

    here = str(Path(__file__).parent)
    if here not in sys.path:
        sys.path.insert(0, here)
    from floors import apply_floors

    n = int(all_baselines[routing].get("runs") or 0)
    path = os.getenv(RUNS_LOG_ENV)
    lines = []
    if path and Path(path).exists():
        lines = [json.loads(ln) for ln in Path(path).read_text().splitlines() if ln.strip()]
    try:
        updated = apply_floors(all_baselines, lines, [name], n=n, routing=routing)
        recorded = updated[routing]["recorded_under"][name]
        if current is not None and recorded != current:
            raise ValueError(f"the runs were recorded under {recorded}, the dataset now records under {current}")
    except ValueError as exc:
        print(
            f"\nRefusing to update {name}: it routes ({routing}), so its floor is the "
            f"minimum of {n} recordings and {routing} names what they were recorded under. "
            f"Record it {n} times with {RUNS_LOG_ENV}=<log> (SAPLING_EVAL_MODE=record), "
            f"then update with the same {RUNS_LOG_ENV}. ({exc})",
            file=sys.stderr,
        )
        return False
    _write_baselines(updated)
    print(f"\nUpdated {name}'s floor and {routing} from {n} recorded runs in {path}.")
    return True


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
    or an evaluator raised on a case,
    a task's aggregate evaluator score regressed below its committed baseline
    in ``baselines.json``, or the dataset/an evaluator has NO committed baseline
    (fail closed — an ungated dataset must not read as PASS in CI). Sub-1.0
    scores alone are NOT failures — the harness measures accuracy, it doesn't
    assume perfection. With ``update=True`` the
    current scores are written back as the new baseline (unless the run had
    failures). This function never calls ``sys.exit`` so callers can aggregate
    across datasets.
    """
    import asyncio
    import sys

    dataset = make_dataset()
    with hermetic_budget(), usage_log(getattr(dataset, "name", None) or "unknown"):
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
            f"\n{len(report.failures)} case(s) raised during evaluation:",
            file=sys.stderr,
        )
        for failure in report.failures:
            print(f"  - {failure.name}: {failure.error_message}", file=sys.stderr)
        ok = False
    crashed = _evaluator_failures(report)
    if crashed:
        # D3: an evaluator that raised scored nothing on that case; the run is
        # a failed run (never a baseline, never a passing routing run).
        print(f"\n{len(crashed)} evaluator failure(s):", file=sys.stderr)
        for line in crashed:
            print(f"  - {line}", file=sys.stderr)
        ok = False

    _log_run(
        name,
        scores,
        raised=bool(report.failures or crashed),
        recorded_under=_recorded_under_of(run_fn),
    )

    all_baselines = _load_baselines()

    if update:
        # Never persist baselines from a partially-broken run — that would bake
        # a crash's degraded scores in as the new "expected".
        if not ok:
            print(
                f"\nRefusing to update {name} baselines: a case or an evaluator raised.",
                file=sys.stderr,
            )
            return False
        routing = _routing_block_of(all_baselines, name)
        if routing is not None:
            return _update_routed(all_baselines, name, routing, _recorded_under_of(run_fn))
        all_baselines[name] = {ev: round(scores[ev], 6) for ev in scores}
        _write_baselines(all_baselines)
        print(f"\nUpdated baselines for {name} in {BASELINES_PATH.name}.")
        return True

    baseline = all_baselines.get(name)
    if baseline is None:
        # Fail closed: this function is CI's regression gate (evals.yml). A
        # dataset with no committed baseline has ZERO protection — reporting
        # PASS here would read as "covered" while gating nothing (a rename in
        # `Dataset(name=...)` not mirrored in baselines.json hits this too).
        print(
            f"\nNo committed baseline for {name}; run with "
            "SAPLING_EVAL_UPDATE_BASELINES=1 to record one.",
            file=sys.stderr,
        )
        ok = False
    else:
        regressions: list[str] = []
        for ev_name, base in baseline.items():
            got = scores.get(ev_name)
            if got is None:
                regressions.append(f"{ev_name}: missing (baseline {base:.3f})")
            elif got < base - BASELINE_TOLERANCE:
                regressions.append(f"{ev_name}: {got:.3f} < baseline {base:.3f}")
        # Same fail-closed logic per evaluator: one added to a dataset but not
        # committed to the baseline would otherwise never be gated at all.
        unbaselined = sorted(set(scores) - set(baseline))
        for ev_name in unbaselined:
            regressions.append(
                f"{ev_name}: no committed baseline (scored {scores[ev_name]:.3f}) — "
                "refresh baselines.json with SAPLING_EVAL_UPDATE_BASELINES=1"
            )
        if regressions:
            print(
                f"\n{len(regressions)} baseline gap(s)/regression(s) in {name}:",
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
    identity: dict | None = None,
):
    """Drive an agent through record/replay/live modes.

    `agent` is a Pydantic AI Agent; `output_model` is its `output_type` so we
    can hydrate replayed JSON back into the typed object that evaluators
    expect. With `identity` (`recorded_under(...)`) the cassette stores what it
    was recorded under and replay raises StaleRecordingError on a difference.
    """
    if MODE == "replay":
        if identity is not None:
            return output_model.model_validate(load_recording(dataset, case_name, identity))
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
        if identity is not None:
            save_recording(dataset, case_name, output, identity)
        else:
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
    # 429/503 for both providers; 529 is Anthropic's `overloaded_error`.
    if status in (429, 503, 529):
        return True
    text = str(exc).upper()
    return (
        "UNAVAILABLE" in text or "503" in text or "RESOURCE_EXHAUSTED" in text
        or "OVERLOADED" in text
    )
