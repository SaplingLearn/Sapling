"""Offline projection of the learning loop's model cost per session and per
student-month for each model mix (spec §13 A137), for the owner's
Haiku-vs-Sonnet decision before the A111 re-record.

    cd backend
    SAPLING_EVAL_MODE=replay GEMINI_API_KEY=dummy-not-used-in-replay \\
      ANTHROPIC_API_KEY=dummy-not-used-in-replay \\
      ENCRYPTION_KEY=0000000000000000000000000000000000000000000000000000000000000000 \\
      venv/bin/python scripts/project_loop_cost.py [--markdown] [--sessions-per-month 12]

Nothing is called: no model, no network, no database. The eval cassettes hold
each loop agent's recorded OUTPUT and the eval modules build each call's exact
INPUT, but no cassette records token counts, so tokens are estimated as
characters / 4 (CHARS_PER_TOKEN) of:

  • the static prefix of every agent (tool definitions + system prompt +
    output schema), read from the request the Anthropic SDK would send — its
    `create` is replaced by a function that raises the request back, and
    ANTHROPIC_BASE_URL points at a closed local port as a second guard;
  • each call's variable input, built by the eval modules' own builders
    (grade() replayed through the grader eval's cassettes, the loop tutor
    eval's assembled turn, the session-close eval's rendered draft, the
    decisions eval's messages, check_items' build_prompt);
  • each call's output, from the cassettes.

The production context the single-turn eval cases lack is added from the
session shape below (the learner brief, the trimmed history, the teach turns'
retrieved chunks), as is an assumed thinking allowance per Claude effort level
(cassettes record no thinking). Prices are services/llm_pricing.cost_usd's,
the table llm_usage is costed with; Claude cache reads and 5-minute writes use
its multipliers. Every † is an assumption to replace with measurement: after
the A111 re-record (which records usage) and on the admin cost-per-gain report
(GET /api/admin/analytics/learning-loop `cost_per_gain`).
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import importlib
import json
import math
import os
import statistics
import sys
from dataclasses import dataclass, field
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
EVALS = BACKEND / "tests" / "evals"
CHARS_PER_TOKEN = 4

# ── the session shape (†: assumptions, CLI-overridable where marked) ─────────
#: §3.5: an optimized 10-turn session makes ≈ 7 tutor model requests
#: (LOOP_SESSION_MAX_TUTOR_REQUESTS note); template turns are free
TUTOR_REQUESTS = 7
#: §3.5's modelled tier mix †
TIER_MIX = {"loop_tutor_lite": 0.25, "loop_tutor": 0.60, "loop_tutor_deep": 0.15}
#: † the share of tutor requests that are teach turns (the only turns that
#: retrieve, A18), each with LOOP_RAG_K_TEACH chunks of the chunker's prose
#: target (200 words ≈ 266 tokens)
TEACH_SHARE = 0.5
CHUNK_TOKENS = 266
#: † mean history messages per tutor request over a 7-request session (turn i
#: carries ≈ 2(i−1) messages, under the 10–19 trim)
MEAN_HISTORY_MESSAGES = 6
#: † graded answers per session: probe items and check-ins (PROBE_ITEMS_PER_SKILL_MIN 4)
GRADED_ANSWERS = 8
#: † the loop's typed decisions per graded answer (wrong-reason match, leak judge…)
DECISIONS_PER_ANSWER = 0.5
#: † concepts drafted per upload (CHECK_ITEM_MAX_CONCEPTS_PER_DOC) and uploads
#: per student-month (an upper bound: items are course assets every student shares)
UPLOAD_CONCEPTS = 10
UPLOADS_PER_STUDENT_MONTH = 1.0
#: † sessions per active student-month (CLI --sessions-per-month)
SESSIONS_PER_MONTH = 12
#: † thinking tokens per call by Claude effort (cassettes record none; adaptive
#: thinking bills as output). Gemini: the deep tier's thinking budget averages
#: 800 (§3.5); every other Gemini loop slot runs with thinking off.
CLAUDE_THINKING = {"low": 100, "medium": 400, "high": 1200}
GEMINI_PRO_THINKING = 800
#: Caching: by default one student alone (the first call of each prefix in a
#: session or an upload writes it, the rest read it); --steady-traffic: other
#: students keep every prefix warm, so every call reads.
STEADY_TRAFFIC = False

HAIKU, SONNET = "claude-haiku-5-5", "claude-sonnet-5-5"
TUTOR_SLOTS = tuple(TIER_MIX)


def mixes() -> dict[str, dict[str, str]]:
    """Each mix: slot → model. A22 and A124 hold in every mix: grader_second
    runs on another model than grader, check_items_solve on another than
    check_items (INDEPENDENT_SLOTS). The "Gemini partners" mixes keep those two
    cross-family partners where they are today (grader_second on
    gemini-2.5-flash, the drafter on gemini-2.5-flash-lite with the solve on
    Haiku); the "all Claude" mixes put the partner on the other Claude model."""
    from agents._providers import _DEFAULTS, EVIDENCE_SLOTS

    today = {slot: _DEFAULTS[slot] for slot in EVIDENCE_SLOTS}

    def claude(tutor: dict[str, str], rest: str, partners: str | None) -> dict[str, str]:
        mix = {slot: rest for slot in EVIDENCE_SLOTS}
        mix.update(tutor)
        if partners is None:  # keep today's cross-family partners
            for slot in ("grader_second", "check_items", "check_items_solve"):
                mix[slot] = today[slot]
        else:
            mix["grader_second"] = partners
            mix["check_items_solve"] = partners
        return mix

    haiku_tutor = {s: HAIKU for s in TUTOR_SLOTS}
    sonnet_deep = {"loop_tutor_lite": HAIKU, "loop_tutor": HAIKU, "loop_tutor_deep": SONNET}
    sonnet_tutor = {s: SONNET for s in TUTOR_SLOTS}
    return {
        "today (Gemini defaults)": today,
        "Haiku, Gemini partners": claude(haiku_tutor, HAIKU, None),
        "Haiku + Sonnet deep, Gemini partners": claude(sonnet_deep, HAIKU, None),
        "Sonnet tutor, Haiku rest, Gemini partners": claude(sonnet_tutor, HAIKU, None),
        "Haiku, all Claude (Sonnet partners)": claude(haiku_tutor, HAIKU, SONNET),
        "Sonnet tutor, Haiku rest, all Claude": claude(sonnet_tutor, HAIKU, SONNET),
        "Sonnet, all Claude (Haiku partners)": claude(sonnet_tutor, SONNET, HAIKU),
    }


# ── offline guards and the request capture ───────────────────────────────────


class _Sent(Exception):
    def __init__(self, kwargs: dict):
        super().__init__("captured")
        self.kwargs = kwargs


@contextlib.contextmanager
def _anthropic_capture():
    """Replace the Anthropic SDK's create with one that raises the request back."""
    from anthropic import NotGiven, Omit
    from anthropic.resources.beta.messages.messages import AsyncMessages

    async def capture(self, **kwargs):
        raise _Sent({k: v for k, v in kwargs.items() if not isinstance(v, (Omit, NotGiven))})

    saved = AsyncMessages.create
    AsyncMessages.create = capture
    try:
        yield
    finally:
        AsyncMessages.create = saved


def _request(agent, task: str, **run) -> dict:
    from agents._providers import provider_model
    from agents.deps import SaplingDeps

    deps = SaplingDeps(user_id="u", course_id="c", supabase=None, request_id="r")
    try:
        asyncio.run(agent.run("x", deps=deps, model=provider_model(HAIKU, task=task), **run))
    except _Sent as sent:
        return sent.kwargs
    raise RuntimeError(f"no request captured for {task}")


def _prefix_tokens(kwargs: dict) -> int:
    system = kwargs.get("system") or ""
    text = system if isinstance(system, str) else "".join(b.get("text", "") for b in system)
    tools = kwargs.get("tools") or []
    schema = (kwargs.get("output_config") or {}).get("format")
    chars = len(text) + (len(json.dumps(tools)) if tools else 0) + (len(json.dumps(schema)) if schema else 0)
    return math.ceil(chars / CHARS_PER_TOKEN)


def _tokens(text: str) -> int:
    return math.ceil(len(text) / CHARS_PER_TOKEN)


def _eval(name: str):
    if str(EVALS) not in sys.path:
        sys.path.insert(0, str(EVALS))
    return importlib.import_module(name)


# ── measurement ──────────────────────────────────────────────────────────────


@dataclass
class Call:
    """One kind of model call: the static prefix and mean variable input /
    output tokens per call, and the mean calls per unit (a graded answer, a
    tutor request, a drafting batch)."""

    slot: str
    prefix: int
    input: float
    output: float
    per_unit: float = 1.0
    samples: int = 0
    notes: list[str] = field(default_factory=list)


def measure_prefixes() -> dict[str, int]:
    from agents.check_items import check_items_agent
    from agents.check_items_solve import check_items_solve_agent
    from agents.check_items_verify import check_items_verify_agent
    from agents.grader import SpanVerdicts, Withdrawals, grader_agent
    from agents.learning_decision import learning_decision_agent
    from agents.loop_tutor import loop_tutor_agent
    from agents.session_close import session_close_agent

    with _anthropic_capture():
        return {
            "grade": _prefix_tokens(_request(grader_agent, "grader")),
            "span": _prefix_tokens(_request(grader_agent, "grader_second", output_type=SpanVerdicts)),
            "context": _prefix_tokens(_request(grader_agent, "grader_second", output_type=Withdrawals)),
            "check_items": _prefix_tokens(_request(check_items_agent, "check_items")),
            "verify": _prefix_tokens(_request(check_items_verify_agent, "check_items_verify")),
            "solve": _prefix_tokens(_request(check_items_solve_agent, "check_items_solve")),
            "decision": _prefix_tokens(_request(learning_decision_agent, "learning_decision")),
            "close": _prefix_tokens(_request(session_close_agent, "session_close")),
            "tutor": _prefix_tokens(_request(loop_tutor_agent, "loop_tutor")),
        }


def measure_grading(prefixes: dict[str, int]) -> list[Call]:
    """grade() replayed per eval case (one case = one graded answer) through the
    grader eval's cassettes, every model call it makes measured."""
    from _replay import hermetic_budget

    import agents.grader as grader

    ev = _eval("grader")
    replay = ev._cassette_run_once  # the eval's _install() puts this in place per case
    original = grader._run_once
    seen: dict[str, list[tuple[int, int]]] = {"grade": [], "second": [], "span": [], "context": []}

    async def measured(message, deps, *, second_opinion=False, output_type=None):
        out = await replay(message, deps, second_opinion=second_opinion, output_type=output_type)
        kind = {ev.SpanVerdicts: "span", ev.Withdrawals: "context"}.get(
            output_type, "second" if second_opinion else "grade"
        )
        seen[kind].append((_tokens(message), _tokens(out.model_dump_json())))
        return out

    ev._cassette_run_once = measured
    try:
        with hermetic_budget():
            for case in ev.CASES:
                asyncio.run(ev._run(case.inputs))
    finally:
        ev._cassette_run_once = replay
        grader._run_once = original
    answers = len(ev.CASES)
    calls = []
    for kind, slot, prefix in (
        ("grade", "grader", prefixes["grade"]),
        ("second", "grader_second", prefixes["grade"]),
        ("span", "grader_second", prefixes["span"]),
        ("context", "grader_second", prefixes["context"]),
    ):
        rows = seen[kind]
        if rows:
            calls.append(Call(
                slot, prefix,
                statistics.mean(r[0] for r in rows), statistics.mean(r[1] for r in rows),
                per_unit=len(rows) / answers, samples=len(rows), notes=[kind],
            ))
    return calls


def measure_tutor(prefixes: dict[str, int]) -> dict[str, Call]:
    """Per tier slot: the eval's assembled single-turn message plus the
    production context it lacks (the brief, the history, the teach turns'
    chunks), and the recorded output of every attempt, per recorded request."""
    from learning.params import LEARNER_BRIEF_MAX_CHARS, LOOP_RAG_K_TEACH

    from _replay import load_cassette

    ev = _eval("loop_tutor")
    out: dict[str, Call] = {}
    message_tokens = []
    for slot in TUTOR_SLOTS:
        ins, outs, requests = [], [], []
        for case in ev.CASES:
            body = load_cassette(slot, case.name)
            if body is None:
                continue
            rec = ev.LoopRecording.model_validate(body)
            ins.append(_tokens(ev._assembled(case.inputs, False)))
            attempts = rec.attempts or [json.dumps(rec.output)]
            outs.append(sum(_tokens(a) for a in attempts) / max(rec.requests, 1))
            requests.append(rec.requests)
            message_tokens.append(_tokens(json.dumps(rec.output)))
            message_tokens.append(_tokens(case.inputs[3]))
        context = (
            _tokens("x" * LEARNER_BRIEF_MAX_CHARS)
            + MEAN_HISTORY_MESSAGES * statistics.mean(message_tokens)
            + TEACH_SHARE * LOOP_RAG_K_TEACH * CHUNK_TOKENS
        )
        out[slot] = Call(
            slot, prefixes["tutor"], statistics.mean(ins) + context, statistics.mean(outs),
            per_unit=statistics.mean(requests), samples=len(ins),
            notes=[f"+{context:.0f} context tokens (brief, history, chunks)"],
        )
    return out


def measure_decisions(prefixes: dict[str, int]) -> Call:
    from _replay import hermetic_budget

    ev = _eval("decisions")
    replay = ev._decision_cassette
    seen = []

    async def measured(case_name, message, output_type):
        out = await replay(case_name, message, output_type)
        seen.append((_tokens(message), _tokens(out.model_dump_json())))
        return out

    ev._decision_cassette = measured
    try:
        with hermetic_budget():
            for case in ev.CASES:
                asyncio.run(ev._run(case.inputs))
    finally:
        ev._decision_cassette = replay
    return Call(
        "learning_decision", prefixes["decision"],
        statistics.mean(s[0] for s in seen), statistics.mean(s[1] for s in seen),
        per_unit=DECISIONS_PER_ANSWER, samples=len(seen),
    )


def measure_close(prefixes: dict[str, int]) -> Call:
    from _replay import load_cassette

    ev = _eval("session_close")
    ins, outs = [], []
    for name, case in ev._cases():
        body = load_cassette(ev.DATASET, name)
        if body is None:
            continue
        rec = ev.CloseRecording.model_validate(body)
        ins.append(_tokens(ev.render_draft(case.draft, nonce=ev.EVAL_NONCE)))
        outs.append(_tokens(rec.output.model_dump_json()))
    return Call("session_close", prefixes["close"], statistics.mean(ins), statistics.mean(outs), samples=len(ins))


def measure_drafting(prefixes: dict[str, int]) -> list[Call]:
    """Per drafting call (CHECK_ITEM_CONCEPTS_PER_CALL concepts): the drafter,
    then the alignment check and the blind solve over its items. The two
    checks have no eval dataset: their input is estimated from the drafter's
    (the items, and the solve's passages) and their output as a short verdict
    per item †."""
    from agents.check_items import CheckItemsOutput, build_prompt
    from learning.params import CHECK_ITEM_CONCEPTS_PER_CALL

    from _replay import load_cassette

    ev = _eval("check_items")
    ins, outs, items = [], [], []
    for case in ev.CASES:
        body = load_cassette("check_items", case.name)
        if body is None:
            continue
        concept, chunks = case.inputs
        passages = [{"id": cid, "text": text} for cid, text in chunks]
        ins.append(_tokens(build_prompt([concept], passages)))
        output = CheckItemsOutput.model_validate(body)
        outs.append(_tokens(output.model_dump_json()))
        items.append(len(output.items))
    # the eval drafts one concept per call; production batches three
    k = CHECK_ITEM_CONCEPTS_PER_CALL
    draft_in = statistics.mean(ins) * k
    draft_out = statistics.mean(outs) * k
    per_item_verdict = 40  # † tokens per item of a verdict list
    n_items = statistics.mean(items) * k
    return [
        Call("check_items", prefixes["check_items"], draft_in, draft_out, samples=len(ins)),
        Call("check_items_verify", prefixes["verify"], draft_out, n_items * per_item_verdict),
        Call("check_items_solve", prefixes["solve"], draft_in, n_items * per_item_verdict),
    ]


# ── pricing ──────────────────────────────────────────────────────────────────


def _effort(slot: str) -> str:
    from agents._providers import _ANTHROPIC_EFFORT

    return _ANTHROPIC_EFFORT.get(slot, "medium")


def _thinking(slot: str, model: str) -> int:
    if model.startswith("claude-"):
        return CLAUDE_THINKING[_effort(slot)]
    return GEMINI_PRO_THINKING if model == "gemini-2.5-pro" else 0


def call_cost(call: Call, model: str, *, cached: bool, calls: float) -> tuple[float, float]:
    """(dollars, of which thinking) for `calls` calls of `call` on `model`. With
    caching (a claude-* slot A137 caches), the first call writes the static
    prefix (1.25×) and the rest read it (0.1×): one student alone, the
    conservative case; steady traffic from many students reads every time."""
    from agents._providers import _ANTHROPIC_CACHED_PREFIX_TASKS
    from services.llm_pricing import cost_usd

    if calls <= 0:
        return 0.0, 0.0
    think = _thinking(call.slot, model)
    prompt = call.prefix + call.input
    completion = call.output + think
    caches = cached and model.startswith("claude-") and call.slot in _ANTHROPIC_CACHED_PREFIX_TASKS
    total = 0.0
    for index, weight in ((0, min(calls, 1.0)), (1, max(calls - 1.0, 0.0))):
        if weight <= 0:
            continue
        first = index == 0 and not STEADY_TRAFFIC
        write = call.prefix if caches and first else 0
        read = call.prefix if caches and not first else 0
        usd = cost_usd(model, round(prompt), round(completion), cache_read_tokens=read, cache_write_tokens=write)
        total += weight * float(usd or 0.0)
    think_usd = calls * float(cost_usd(model, 0, think) or 0.0)
    return total, think_usd


@dataclass
class Projection:
    mix: str
    cached: bool
    tutor: float
    grading: float
    other: float  # decisions + close
    drafting_per_upload: float
    thinking: float

    @property
    def session(self) -> float:
        return self.tutor + self.grading + self.other

    def month(self, sessions: float) -> float:
        return self.session * sessions + self.drafting_per_upload * UPLOADS_PER_STUDENT_MONTH


def project(measured: dict, mix: dict[str, str], name: str, cached: bool) -> Projection:
    tutor = grading = other = drafting = thinking = 0.0
    for slot, call in measured["tutor"].items():
        usd, think = call_cost(call, mix[slot], cached=cached, calls=TUTOR_REQUESTS * TIER_MIX[slot] * call.per_unit)
        tutor += usd
        thinking += think
    for call in measured["grading"]:
        usd, think = call_cost(call, mix[call.slot], cached=cached, calls=GRADED_ANSWERS * call.per_unit)
        grading += usd
        thinking += think
    decision = measured["decision"]
    for call, calls in ((decision, GRADED_ANSWERS * decision.per_unit), (measured["close"], 1.0)):
        usd, think = call_cost(call, mix[call.slot], cached=cached, calls=calls)
        other += usd
        thinking += think
    batches = math.ceil(UPLOAD_CONCEPTS / 3)
    for call in measured["drafting"]:
        usd, _think = call_cost(call, mix[call.slot], cached=cached, calls=batches)
        drafting += usd
    return Projection(name, cached, tutor, grading, other, drafting, thinking)


def measure() -> dict:
    prefixes = measure_prefixes()
    return {
        "prefixes": prefixes,
        "grading": measure_grading(prefixes),
        "tutor": measure_tutor(prefixes),
        "decision": measure_decisions(prefixes),
        "close": measure_close(prefixes),
        "drafting": measure_drafting(prefixes),
    }


def _guard() -> None:
    if os.getenv("SAPLING_EVAL_MODE", "replay").lower() != "replay":
        raise SystemExit("refusing: SAPLING_EVAL_MODE must be replay (this script makes no model call)")
    os.environ["SAPLING_EVAL_MODE"] = "replay"
    os.environ["ANTHROPIC_BASE_URL"] = "http://127.0.0.1:9"  # a closed port: nothing can connect


def main(argv: list[str] | None = None) -> int:
    global SESSIONS_PER_MONTH, STEADY_TRAFFIC
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--sessions-per-month", type=float, default=SESSIONS_PER_MONTH)
    ap.add_argument(
        "--steady-traffic", action="store_true",
        help="cached rows: every call reads the prefix (others keep it warm)",
    )
    ap.add_argument("--markdown", action="store_true", help="print Markdown tables")
    args = ap.parse_args(argv)
    SESSIONS_PER_MONTH = args.sessions_per_month
    STEADY_TRAFFIC = args.steady_traffic
    _guard()
    sys.path.insert(0, str(BACKEND))
    sys.path.insert(0, str(EVALS))
    from learning.params import LOOP_COST_TARGET_USD_PER_STUDENT_MONTH as target

    measured = measure()
    rows = [
        project(measured, mix, name, cached)
        for name, mix in mixes().items()
        for cached in ((False,) if name.startswith("today") else (False, True))
    ]
    sep = " | " if args.markdown else "  "
    head = ["mix", "caching", "tutor", "grading", "decisions+close", "per session",
            "of which thinking", "drafting per upload", "per student-month", "× target"]
    lines = [sep.join(head)]
    if args.markdown:
        lines = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    for r in rows:
        month = r.month(SESSIONS_PER_MONTH)
        cells = [r.mix, "on" if r.cached else "off", f"${r.tutor:.4f}", f"${r.grading:.4f}",
                 f"${r.other:.4f}", f"${r.session:.4f}", f"${r.thinking:.4f}",
                 f"${r.drafting_per_upload:.4f}", f"${month:.3f}", f"{month / target:.1f}×"]
        lines.append(("| " + " | ".join(cells) + " |") if args.markdown else sep.join(cells))
    print("\n".join(lines))
    print()
    print(f"session: {TUTOR_REQUESTS} tutor requests (tiers {TIER_MIX}), {GRADED_ANSWERS} graded "
          f"answers, {GRADED_ANSWERS * DECISIONS_PER_ANSWER:g} decisions, 1 close; "
          f"{SESSIONS_PER_MONTH:g} sessions and {UPLOADS_PER_STUDENT_MONTH:g} upload "
          f"({UPLOAD_CONCEPTS} concepts) per student-month; target ${target}/student-month; "
          f"caching: {'steady traffic (every call reads)' if STEADY_TRAFFIC else 'one student (first call writes)'}")
    print("static prefixes (tokens, chars/4):", json.dumps(measured["prefixes"], sort_keys=True))
    for call in [*measured["grading"], *measured["tutor"].values(), measured["decision"],
                 measured["close"], *measured["drafting"]]:
        print(f"  {call.slot:20} prefix {call.prefix:5} input {call.input:7.0f} output {call.output:6.0f} "
              f"per unit {call.per_unit:4.2f} (n={call.samples}) {' '.join(call.notes)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
