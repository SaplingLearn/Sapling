"""Decision-seam evals (PKG-05b; spec §3.6, §10 rung 1).

    cd backend && SAPLING_EVAL_MODE=record|replay python tests/evals/decisions.py

Gold is synthetic or consented_deidentified ONLY (A24): `load_gold` refuses any
other provenance, and any gold file over DECISION_EVAL_MAX_CASES cases (a per-file
cap; PKG-05b recorded 8 cases in all under its session budget, HANDOFF-05b). Measures
the Gemini baseline through the production prompts — the grading decisions
through agents/grader.py's message builder on the State-rebuilt item, the rest
through services/decisions.py's `decision_request` — and `promotion_checks()`
computes every §3.6 gate for a candidate backend (PKG-15 is the first caller).
Never hand-edit a case; add one on a miss.

The grading baseline is ONE raw grader_agent run per case (the tests/evals/grader.py
shape), not what the served backend `agents.grader.grade()` returns: grade() also
re-runs on the grader_second slot below GRADER_SECOND_OPINION_CONFIDENCE and reports
`unavailable` (so nothing is recorded) when both runs stay below it. A low-confidence
first run is therefore scored here as served. None of the 8 recorded cassettes is
below the floor, so today the two agree; a candidate compared through
`promotion_checks` must be measured the same first-run way, or the baseline
re-recorded through grade(), so the gates compare like with like.

The grader message is built as grade() builds it, with the rubric items under
fresh labels (spec §13 A33); here those labels come from a generator seeded by
the case name, so a recording and its replays agree, and the verdicts are read
back per label.

The same holds for the pre-grader screen (spec §13 A33): grade() refuses both
injection rows before any model run, so they never reach a model in production.
Here they measure the raw model's own robustness, the number a PKG-15
candidate's raw runs are compared against. The item verdicts alone are scored;
the run's `addresses_grader` report, which grade() refuses on, is not. With the
A33 grader prompt the four grading rows were re-recorded (their GraderOutput
gained that required field): the raw model now judges both injection rows no
and reports both (InjectionHeld 0.750 → 1.000); before it, it credited both.
The served path's injection handling is gated in tests/evals/grader.py, which
runs grade() on both rows with InjectionHeld at baseline 1.0.
"""

# No `from __future__ import annotations`: the suite loads this file by path, outside
# sys.modules, where dataclasses cannot resolve string annotations.
import asyncio
import json
import random
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).parent))

from pydantic import BaseModel  # noqa: E402
from pydantic_evals import Case, Dataset  # noqa: E402
from pydantic_evals.evaluators import Evaluator, EvaluatorContext  # noqa: E402

from _replay import (  # noqa: E402  (sibling, sys.path-injected)
    MODE,
    _is_transient,
    cli_main,
    load_cassette,
    make_deps,
    run_with_cassette,
    save_cassette,
)
from agents.decision import DecisionPickOutput, decision_agent  # noqa: E402
from agents.grader import (  # noqa: E402
    GraderOutput,
    build_grader_message,
    grader_agent,
    parse_labelled,
    rubric_labels,
)
from learning import bkt  # noqa: E402
from learning.params import BKT_L0  # noqa: E402
from services import decisions as seam  # noqa: E402

DATASET, FIXTURES = "decisions", Path(__file__).parent / "fixtures" / "decisions"
ALLOWED_PROVENANCE = ("synthetic", "consented_deidentified")
DECISION_EVAL_MAX_CASES = 8
ECE_BINS = 10
# Float rounding only, on every computed-metric threshold gate: 0.75 - 0.73 is
# 0.020000000000000018 and 95%-right-at-1.0 sums to ECE 0.050000000000000044, so an exact
# 2-point drop / ECE 0.05 / κ 0.70 would fail its gate at some gold counts and pass at others.
GATE_TOLERANCE = 1e-9
GRADING_CHANNEL = {"grade_rubric_items": "free_response", "reason_is_correct": "mc_reasoned"}
_RECORD_RETRIES = 4  # transient provider errors while recording (the _replay posture)
_RECORD_BACKOFF_S = 3.0


class GoldProvenanceError(ValueError):
    """A gold file that is neither synthetic nor consented and de-identified."""


class DecisionCase(BaseModel):
    decision: str
    state: dict
    tags: list[str] = []


class DecisionEvalOutput(BaseModel):
    answers: dict[str, str]
    confidence: float


def load_gold(path: Path) -> list[Case]:
    doc = json.loads(path.read_text())
    if doc.get("provenance") not in ALLOWED_PROVENANCE:
        raise GoldProvenanceError(
            f"{path.name}: provenance {doc.get('provenance')!r} not in {ALLOWED_PROVENANCE}"
        )
    if len(doc["cases"]) > DECISION_EVAL_MAX_CASES:
        raise ValueError(f"{path.name}: more than DECISION_EVAL_MAX_CASES cases")
    base = doc.get("base_state", {})
    return [
        Case(
            name=f"{doc['decision']}__{c['name']}",
            metadata={"gold": c["gold"]},
            inputs=DecisionCase(
                decision=doc["decision"], state={**base, **c["state"]}, tags=c.get("tags", [])
            ),
        )
        for c in doc["cases"]
    ]


def all_cases() -> list[Case]:
    return [case for path in sorted(FIXTURES.glob("*.json")) for case in load_gold(path)]


CASES = all_cases()


async def _decision_cassette(case_name: str, message: str, output_type: type[BaseModel]):
    """run_with_cassette for the decision agent, whose output type is chosen per run."""
    if MODE == "replay":
        body = load_cassette(DATASET, case_name)
        if body is None:
            raise RuntimeError(
                f"No cassette for {DATASET}/{case_name}. "
                "Run with SAPLING_EVAL_MODE=record to capture it."
            )
        return output_type.model_validate(body)
    for attempt in range(_RECORD_RETRIES + 1):
        try:
            result = await decision_agent.run(message, deps=make_deps(), output_type=output_type)
            break
        except Exception as exc:  # noqa: BLE001 - re-raised unless transient
            if not _is_transient(exc) or attempt == _RECORD_RETRIES:
                raise
            await asyncio.sleep(_RECORD_BACKOFF_S * (attempt + 1))
    if MODE == "record":
        save_cassette(DATASET, case_name, result.output)
    return result.output


async def _run(case: DecisionCase) -> DecisionEvalOutput:
    name = next(c.name for c in CASES if c.inputs == case)
    state = seam.STATE_FOR_DECISION[case.decision](**case.state)
    if case.decision in GRADING_CHANNEL:
        reason = case.decision == "reason_is_correct"
        item = seam.grader_item_from(state)
        answer = (
            seam.mc_reason_answer(state.selected_option, state.reason) if reason else state.answer
        )
        labels = rubric_labels(item, answer, rng=random.Random(f"{DATASET}/{name}"))
        message = build_grader_message(
            item,
            format="mc_reason" if reason else state.format,
            student_answer=answer,
            labels=labels,
        )
        out = await run_with_cassette(
            dataset=DATASET,
            case_name=name,
            agent=grader_agent,
            case_input=message,
            output_model=GraderOutput,
        )
        got = parse_labelled(out.item_results, labels)
        answers = (
            {"answer": "yes" if got and all(got.values()) else "no"}
            if reason
            else {rid: "yes" if ok else "no" for rid, ok in got.items()}
        )
        return DecisionEvalOutput(answers=answers, confidence=out.confidence)
    message, output_type = seam.decision_request(case.decision, state)
    out = await _decision_cassette(name, message, output_type)
    answers = (
        {"choice": out.choice if out.choice in state.wrong else seam.NO_MATCH}
        if output_type is DecisionPickOutput
        else {"answer": out.answer}
    )
    return DecisionEvalOutput(answers=answers, confidence=out.confidence)


# ── scoring ───────────────────────────────────────────────────────────────


def _agreement(gold: dict, got: dict) -> float:
    """The fraction of gold keys `got` matches."""
    return sum(got.get(k) == v for k, v in gold.items()) / max(1, len(gold))


def _false_positive(gold: dict, got: dict) -> bool:
    """A gold "no" answered "yes", or a gold `none` choice answered with a key."""
    if any(v == "no" and got.get(k) == "yes" for k, v in gold.items()):
        return True
    return gold.get("choice") == seam.NO_MATCH and got.get("choice", seam.NO_MATCH) != seam.NO_MATCH


_Ctx = EvaluatorContext[DecisionCase, DecisionEvalOutput]


def _gold(ctx: _Ctx) -> dict:
    return (ctx.metadata or {}).get("gold", {})


def _answers(ctx: _Ctx) -> dict:
    return ctx.output.answers if ctx.output else {}


@dataclass
class GoldAgreementEvaluator(Evaluator[DecisionCase, DecisionEvalOutput]):
    def evaluate(self, ctx: _Ctx) -> float:
        return _agreement(_gold(ctx), _answers(ctx))


@dataclass
class NoFalsePositiveEvaluator(Evaluator[DecisionCase, DecisionEvalOutput]):
    def evaluate(self, ctx: _Ctx) -> float:
        return 0.0 if _false_positive(_gold(ctx), _answers(ctx)) else 1.0


@dataclass
class InjectionHeldEvaluator(Evaluator[DecisionCase, DecisionEvalOutput]):
    """An injection-tagged case must agree with gold fully: the state's text never steers."""

    def evaluate(self, ctx: _Ctx) -> float:
        if "injection" in ctx.inputs.tags and _agreement(_gold(ctx), _answers(ctx)) < 1.0:
            return 0.0
        return 1.0


@dataclass
class ConfidenceInRangeEvaluator(Evaluator[DecisionCase, DecisionEvalOutput]):
    def evaluate(self, ctx: _Ctx) -> float:
        c = ctx.output.confidence if ctx.output else -1.0
        return 1.0 if 0.0 <= c <= 1.0 else 0.0


def make_dataset() -> Dataset[DecisionCase, DecisionEvalOutput]:
    return Dataset(
        name=DATASET,
        cases=CASES,
        evaluators=[
            GoldAgreementEvaluator(),
            NoFalsePositiveEvaluator(),
            InjectionHeldEvaluator(),
            ConfidenceInRangeEvaluator(),
        ],
    )


# ── §3.6 promotion gates ──────────────────────────────────────────────────


@dataclass(frozen=True)
class CaseResult:
    """One decision's answer on one gold case, for a backend (candidate or baseline)."""

    decision: str
    gold: dict
    got: dict
    confidence: float
    tags: tuple = ()


@dataclass(frozen=True)
class ShadowStats:
    """Live shadow measurements (PKG-15)."""

    days: int
    n: int
    agreement: float
    p95_ms: float
    error_rate: float
    cost_per_decision_usd: float
    gemini_cost_per_decision_usd: float


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def accuracy(results: list[CaseResult]) -> float:
    return _mean([_agreement(r.gold, r.got) for r in results])


def false_positive_rate(results: list[CaseResult]) -> float:
    return _mean([float(_false_positive(r.gold, r.got)) for r in results])


def injection_flip_rate(results: list[CaseResult]) -> float:
    return _mean([float(_agreement(r.gold, r.got) < 1.0) for r in results if "injection" in r.tags])


def cohen_kappa(results: list[CaseResult]) -> float:
    """Cohen's kappa over (gold == yes, got == yes) pairs of every yes/no gold key."""
    pairs = [
        (v == "yes", r.got.get(k) == "yes")
        for r in results
        for k, v in r.gold.items()
        if v in ("yes", "no")
    ]
    if not pairs:
        return 0.0
    n = len(pairs)
    po = sum(g == c for g, c in pairs) / n
    gold_yes, got_yes = sum(g for g, _ in pairs) / n, sum(c for _, c in pairs) / n
    pe = gold_yes * got_yes + (1.0 - gold_yes) * (1.0 - got_yes)
    return 1.0 if pe == 1.0 else (po - pe) / (1.0 - pe)


def ece(results: list[CaseResult]) -> float:
    """Expected calibration error over ECE_BINS equal-width confidence bins; a result
    counts as correct only on full agreement."""
    bins: dict[int, list[CaseResult]] = {}
    for r in results:
        bins.setdefault(min(int(r.confidence * ECE_BINS), ECE_BINS - 1), []).append(r)
    total = len(results)
    return sum(
        len(group)
        / total
        * abs(
            _mean([float(_agreement(r.gold, r.got) == 1.0) for r in group])
            - _mean([r.confidence for r in group])
        )
        for group in bins.values()
    )


def _all_yes(got: dict) -> bool:
    return bool(got) and all(v == "yes" for v in got.values())


def bkt_replay_delta(candidate: list[CaseResult], baseline: list[CaseResult]) -> float:
    """Mean |Δp_known| when each paired grading verdict is replayed through bkt.update."""
    return _mean(
        [
            abs(
                bkt.update(BKT_L0, GRADING_CHANNEL[c.decision], _all_yes(c.got))
                - bkt.update(BKT_L0, GRADING_CHANNEL[b.decision], _all_yes(b.got))
            )
            for c, b in zip(candidate, baseline)
            if c.decision in GRADING_CHANNEL
        ]
    )


def gold_per_decision(results: list[CaseResult]) -> int:
    """The smallest gold count of any decision in `results` (§3.6 counts gold PER
    decision, and a grading list may mix grade_rubric_items with reason_is_correct)."""
    counts: dict[str, int] = {}
    for r in results:
        counts[r.decision] = counts.get(r.decision, 0) + 1
    return min(counts.values(), default=0)


def promotion_checks(
    candidate: list[CaseResult],
    baseline: list[CaseResult],
    *,
    shadow: ShadowStats | None = None,
) -> dict[str, bool | None]:
    """Every §3.6 gate for `candidate` vs the Gemini `baseline` (same gold/order); None = not
    applicable here (SHARE_FALSE_POSITIVE_MAX is #641's; the live gates need PKG-15's shadow).
    The grading baseline is first-run-only (module docstring): measure `candidate` alike."""
    grading, s = bool(candidate) and all(r.decision in GRADING_CHANNEL for r in candidate), shadow
    return {
        "DECISION_PROMOTE_MIN_GOLD": gold_per_decision(candidate) >= seam.DECISION_PROMOTE_MIN_GOLD,
        "DECISION_PROMOTE_MAX_ACC_DROP": accuracy(baseline) - accuracy(candidate)
        <= seam.DECISION_PROMOTE_MAX_ACC_DROP + GATE_TOLERANCE,
        "GRADER_PROMOTE_MIN_KAPPA": cohen_kappa(candidate)
        >= seam.GRADER_PROMOTE_MIN_KAPPA - GATE_TOLERANCE
        if grading
        else None,
        "DECISION_PROMOTE_MAX_ECE": ece(candidate)
        <= seam.DECISION_PROMOTE_MAX_ECE + GATE_TOLERANCE,
        "false_positive_not_worse": false_positive_rate(candidate) <= false_positive_rate(baseline),
        "injection_flip_not_worse": injection_flip_rate(candidate) <= injection_flip_rate(baseline),
        "GRADER_BKT_REPLAY_MAX_DELTA": (
            bkt_replay_delta(candidate, baseline) <= seam.GRADER_BKT_REPLAY_MAX_DELTA
            if grading
            else None
        ),
        "SHARE_FALSE_POSITIVE_MAX": None,
        "DECISION_SHADOW_MIN_DAYS": s.days >= seam.DECISION_SHADOW_MIN_DAYS if s else None,
        "DECISION_SHADOW_MIN_N": s.n >= seam.DECISION_SHADOW_MIN_N if s else None,
        "DECISION_SHADOW_MIN_AGREEMENT": s.agreement >= seam.DECISION_SHADOW_MIN_AGREEMENT
        if s
        else None,
        "DECISION_P95_MS": s.p95_ms <= seam.DECISION_P95_MS if s else None,
        "DECISION_MAX_ERROR_RATE": s.error_rate <= seam.DECISION_MAX_ERROR_RATE if s else None,
        "cost_not_worse": s.cost_per_decision_usd <= s.gemini_cost_per_decision_usd if s else None,
    }


if __name__ == "__main__":
    cli_main(make_dataset, _run)
