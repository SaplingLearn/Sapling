"""The typed decision seam (learning loop PKG-05b; spec §3.6, §6, §8.24–25, §13 A24).

Every closed question the learning loop asks a model goes through one typed
function here: a text-only State goes in (no identifiers, invariant 25; decrypted
item text lives in memory only and is never logged), and out comes a typed
answer carrying its provenance (`Verdict.backend`), or None when no backend
answered — in which case the caller records nothing, for either outcome
(invariant 28).

Backends:
- `gemini` (the default): grading delegates to agents/grader.py's `grade()`
  (no second prompt stack, ADR 0024); every other decision runs
  agents/decision.py's `decision_agent`.
- `function`: `SAPLING_MODEL_MODE=function` (the E2E lane) — the same agents on
  the FunctionModel seam; the env selection is ignored and Jev is never built.
- `deterministic`: code-computed (`deterministic_yes_no`); no model, no
  llm_usage row.
- `jev`: absent until PKG-15. A `jev` selection is served by Gemini with a
  `decision.fallback{reason: jev_absent}` event; `shadow_jev` is a no-op.

Selection (`select_backend`): function mode → `function`; else env
`DECISION_BACKEND_<NAME>` ∈ {gemini (default), jev, shadow_jev} (an unknown value
→ gemini + WARNING), and `JEV_ENABLED` false (the default) overrides every one of
them to gemini.

The seam reads no learning-loop gate: its only caller, grade_answer, returns
before any seam call when `deps.learning_loop` is False. Nothing under
backend/learning/ imports this module (spec §12: no LLM inside learning/).
"""

from __future__ import annotations

import logging
import os
import re
import time
from dataclasses import dataclass
from typing import Literal, get_args

from pydantic import BaseModel, ConfigDict
from pydantic_ai.usage import RunUsage

from agents import GRADER_LIMITS, grader
from agents._providers import model_mode
from agents.decision import (
    QUESTION_ITEM_ANSWERABLE,
    QUESTION_JUDGE_LEAK,
    QUESTION_MATCH_WRONG_REASON,
    DecisionPickOutput,
    DecisionYesNoOutput,
    build_decision_message,
    decision_agent,
)
from agents.grader import GradeResult
from agents.usage import record_agent_usage
from learning.checks import RubricItem, WrongReason
from learning.evidence import GraderBackend
from services import events_service

logger = logging.getLogger("sapling.decisions")


def parse_jev_enabled(raw: str | None) -> bool:
    """Fail closed: only `true` (any case, surrounding whitespace ignored) enables Jev."""
    return (raw or "").strip().lower() == "true"


# ── §3.6 settings (read here or by tests/evals/decisions.py; Jev's by PKG-15) ──
# † = no validated cut-point (HANDOFF-05b "Constants chosen").
JEV_ENABLED = parse_jev_enabled(os.getenv("JEV_ENABLED"))
JEV_MODEL = "jev-1.13.0"  # pinned; never an alias
JEV_SDK_VERSION = "typesafe-sdk==0.7.2"  # a string only: nothing installs it before PKG-15
JEV_TIMEOUT_MS = 800  # †
JEV_MAX_RETRIES = 1
JEV_CIRCUIT_FAILS = 5  # †
JEV_CIRCUIT_COOLDOWN_S = 300  # †
JEV_STATE_MAX_TOKENS = 28_000  # † oversize states go to Gemini, never truncated
DECISION_PROMOTE_MIN_GOLD = 200  # † gold labels per decision
DECISION_PROMOTE_MAX_ACC_DROP = 0.02  # † accuracy vs the Gemini backend, same gold
GRADER_PROMOTE_MIN_KAPPA = 0.70  # † kappa with gold (grading decisions)
DECISION_PROMOTE_MAX_ECE = 0.05  # † calibration
SHARE_FALSE_POSITIVE_MAX = 0.01  # † shareability false-share rate (#641)
GRADER_BKT_REPLAY_MAX_DELTA = 0.02  # † mean |Δp_known| replaying verdicts through bkt.update
DECISION_SHADOW_MIN_DAYS = 7
DECISION_SHADOW_MIN_N = 1000  # †
DECISION_SHADOW_MIN_AGREEMENT = 0.90  # †
DECISION_P95_MS = 300  # † measured from Sapling's host
DECISION_MAX_ERROR_RATE = 0.005  # †

# ── vocabulary ────────────────────────────────────────────────────────────────
Backend = Literal["deterministic", "gemini", "jev", "function"]
DecisionName = Literal[
    "grade_rubric_items",
    "reason_is_correct",
    "match_wrong_reason",
    "item_answerable",
    "judge_leak",
    "numeric_gate",
]
DECISION_NAMES: tuple[str, ...] = get_args(DecisionName)
BACKEND_CHOICES = ("gemini", "jev", "shadow_jev")
NO_MATCH = "none"  # A24: match_wrong_reason's "no listed key"; the seam never invents one (A22)
P_YES_UNCLEAR = 0.5  # an `unclear` answer claims neither side
EVENT_ENUM_MAX_CHARS = 64  # a sha256 hex id (PKG-06's bound on event enum values)
_ENUM_VALUE = re.compile(rf"[A-Za-z0-9_.:-]{{0,{EVENT_ENUM_MAX_CHARS}}}")
_MS_PER_S = 1000
_FALLBACK_TO_NONE = "none"  # decision.fallback to_backend when no backend answered
# A decision run degrades on exactly what grade() degrades on (UsageLimitExceeded,
# UnexpectedModelBehavior, ModelAPIError ⊃ ModelHTTPError, httpx.TransportError): one
# tuple, so a provider outage is an honest None on every decision, never a route 500.
_DECISION_FAILURES = grader._GRADER_FAILURES


# ── verdicts ──────────────────────────────────────────────────────────────────
class Verdict(BaseModel):
    """One answered decision and its provenance."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    backend: Backend
    confidence: float
    latency_ms: int
    fallback: bool = False


class YesNo(Verdict):
    value: bool
    p_yes: float


class Pick(Verdict):
    value: str
    probs: dict[str, float]


class RubricVerdict(Verdict):
    """Per-rubric-item yes/no plus the delegate's full GradeResult (grade_answer
    reads it; PKG-10 hands it back to match_wrong_reason as `prior`)."""

    items: dict[str, YesNo]
    result: GradeResult


class ReasonVerdict(YesNo):
    result: GradeResult


# ── states: text only, no identifiers (invariant 25) ─────────────────────────
class _State(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class GradeState(_State):
    """grade_rubric_items. `rubric` (id → text) and `wrong` (key → text) keep item order."""

    question: str
    reference: str
    rubric: dict[str, str]
    wrong: dict[str, str]
    answer: str
    format: str


class ReasonState(_State):
    """reason_is_correct (mc_reason). The option is compared by grade_answer, never here."""

    question: str
    reference: str
    rubric: dict[str, str]
    wrong: dict[str, str]
    selected_option: str
    correct_option: str
    reason: str


class WrongReasonState(_State):
    """match_wrong_reason (PKG-10 wires it)."""

    question: str
    answer: str
    wrong: dict[str, str]


class AnswerableState(_State):
    """item_answerable (unwired; PKG-04's answerable_hook stays None)."""

    passages: list[str]
    question: str
    reference: str


class LeakState(_State):
    """judge_leak (unwired; a caller may only block)."""

    reference: str
    emitted: str
    rung: int


class UploadState(_State):
    """State only: classify_upload belongs to #641."""

    excerpt: str
    course_title: str


class PassageState(_State):
    """State only: rerank belongs to #640."""

    query: str
    passage: str


class TurnState(_State):
    """State only: route_turn belongs to #640 (the legacy chat_tutor)."""

    message: str
    last_turns: list[str]


STATE_FOR_DECISION: dict[str, type[_State]] = {
    "grade_rubric_items": GradeState,
    "reason_is_correct": ReasonState,
    "match_wrong_reason": WrongReasonState,
    "item_answerable": AnswerableState,
    "judge_leak": LeakState,
}


# ── the grader delegate's input ───────────────────────────────────────────────
@dataclass(frozen=True)
class GraderItem:
    """What agents.grader.build_grader_message (and grade()) read, rebuilt from a
    State. `id` is a log label only. rubric / common_wrong are learning.checks
    models (the grader reads r.id / r.text / w.key / w.text, HANDOFF-05)."""

    id: str
    prompt: str
    reference_answer: str
    rubric: list[RubricItem]
    common_wrong: list[WrongReason]


def grader_item_from(state: GradeState | ReasonState, *, item_id: str = "-") -> GraderItem:
    return GraderItem(
        id=item_id,
        prompt=state.question,
        reference_answer=state.reference,
        rubric=[RubricItem(id=k, text=v) for k, v in state.rubric.items()],
        common_wrong=[WrongReason(key=k, text=v) for k, v in state.wrong.items()],
    )


def mc_reason_answer(selected_option: str, reason: str) -> str:
    """Byte-identical to the student_answer PKG-05's grade_answer built."""
    return f"Selected option: {selected_option}\nReason: {reason}"


# ── selection ─────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Selection:
    served: Backend
    requested: str
    fallback_reason: str | None = None
    shadow: bool = False


def select_backend(decision: str) -> Selection:
    if model_mode() == "function":
        return Selection(served="function", requested="function")
    env = f"DECISION_BACKEND_{decision.upper()}"
    requested = (os.getenv(env) or "gemini").strip().lower()
    if requested not in BACKEND_CHOICES:
        logger.warning("decisions: unknown %s=%r; serving gemini", env, requested)
        return Selection(served="gemini", requested="gemini")
    if not JEV_ENABLED or requested == "gemini":
        return Selection(served="gemini", requested=requested)
    if requested == "jev":
        return Selection(served="gemini", requested="jev", fallback_reason="jev_absent")
    return Selection(served="gemini", requested="shadow_jev", shadow=True)  # PKG-15 runs the shadow


# ── events (ids, enums and numbers only; never state text) ───────────────────
def _emit(event_type: str, category: str, deps, payload: dict) -> None:
    """Events never raise (log_event is a cannot-raise sink; this is the belt)."""
    try:
        events_service.log_event(
            event_type,
            category=category,
            user_id=deps.user_id,
            request_id=deps.request_id,
            payload=payload,
        )
    except Exception:  # pragma: no cover - log_event itself never raises
        logger.debug("decision event %s dropped", event_type, exc_info=True)


def _made(decision: str, verdict: Verdict, deps) -> None:
    _emit(
        "decision.made",
        "usage",
        deps,
        {
            "decision": decision,
            "backend": verdict.backend,
            "request_id": deps.request_id,
            "latency_ms": verdict.latency_ms,
            "confidence": verdict.confidence,
            "fallback": verdict.fallback,
        },
    )


def _fallback(decision: str, frm: str, to: str, reason: str, deps) -> None:
    _emit(
        "decision.fallback",
        "error",
        deps,
        {
            "decision": decision,
            "from_backend": frm,
            "to_backend": to,
            "reason": reason,
            "request_id": deps.request_id,
        },
    )


def _select(decision: str, deps) -> Selection:
    sel = select_backend(decision)
    if sel.fallback_reason is not None:
        _fallback(decision, sel.requested, sel.served, sel.fallback_reason, deps)
    return sel


def _unavailable(decision: str, sel: Selection, deps) -> None:
    """No backend answered († in the series every available backend failed)."""
    _fallback(decision, sel.served, _FALLBACK_TO_NONE, "both_failed", deps)
    return None


def _ms(t0: float) -> int:
    return round((time.monotonic() - t0) * _MS_PER_S)


def _yes_no(value: bool, conf: float, sel: Selection, ms: int) -> YesNo:
    return YesNo(
        backend=sel.served,
        confidence=conf,
        latency_ms=ms,
        fallback=sel.fallback_reason is not None,
        value=value,
        p_yes=conf if value else 1.0 - conf,
    )


# ── grading (delegates to agents.grader.grade, resolved at call time) ────────
async def grade_rubric_items(
    state: GradeState, *, deps, item_id: str = "-"
) -> RubricVerdict | None:
    """ONE agents.grader.grade() call; grade() writes its own llm_usage rows (none added here)."""
    sel, t0 = _select("grade_rubric_items", deps), time.monotonic()
    result = await grader.grade(
        grader_item_from(state, item_id=item_id),
        format=state.format,
        student_answer=state.answer,
        deps=deps,
    )
    if result.unavailable:
        return _unavailable("grade_rubric_items", sel, deps)
    ms = _ms(t0)
    verdict = RubricVerdict(
        backend=sel.served,
        confidence=result.confidence,
        latency_ms=ms,
        fallback=sel.fallback_reason is not None,
        result=result,
        items={
            rid: _yes_no(ok, result.confidence, sel, ms) for rid, ok in result.item_results.items()
        },
    )
    _made("grade_rubric_items", verdict, deps)
    return verdict


async def reason_is_correct(
    state: ReasonState, *, deps, item_id: str = "-"
) -> ReasonVerdict | None:
    """ONE grade() call as format mc_reason on the byte-identical PKG-05 answer.
    The option itself is compared by grade_answer, never here."""
    sel, t0 = _select("reason_is_correct", deps), time.monotonic()
    result = await grader.grade(
        grader_item_from(state, item_id=item_id),
        format="mc_reason",
        student_answer=mc_reason_answer(state.selected_option, state.reason),
        deps=deps,
    )
    if result.unavailable:
        return _unavailable("reason_is_correct", sel, deps)
    ms = _ms(t0)
    value = result.all_yes
    verdict = ReasonVerdict(
        backend=sel.served,
        confidence=result.confidence,
        latency_ms=ms,
        fallback=sel.fallback_reason is not None,
        value=value,
        p_yes=result.confidence if value else 1.0 - result.confidence,
        result=result,
    )
    _made("reason_is_correct", verdict, deps)
    return verdict


# ── decision-agent decisions ──────────────────────────────────────────────────
async def match_wrong_reason(
    state: WrongReasonState, *, deps, prior: GradeResult | None = None
) -> Pick | None:
    """A22: only a matched key may become a misconception record; with `prior` gemini reuses its key (no call)."""
    if prior is not None and prior.unavailable:
        return None  # the grade already reported the outage
    sel, t0 = _select("match_wrong_reason", deps), time.monotonic()
    if prior is not None:
        key, conf, ms = prior.matched_wrong_key, prior.confidence, 0
    else:
        out = await _run_decision("match_wrong_reason", state, deps)
        if out is None:
            return _unavailable("match_wrong_reason", sel, deps)
        key, conf, ms = out.choice, out.confidence, _ms(t0)
    key = key if key in state.wrong else NO_MATCH
    verdict = Pick(
        backend=sel.served,
        confidence=conf,
        latency_ms=ms,
        fallback=sel.fallback_reason is not None,
        value=key,
        probs={key: conf},
    )
    _made("match_wrong_reason", verdict, deps)
    return verdict


async def item_answerable(state: AnswerableState, *, deps) -> YesNo | None:
    """Unwired (PKG-04's answerable_hook stays None)."""
    return await _yes_no_decision("item_answerable", state, deps)


async def judge_leak(state: LeakState, *, deps) -> YesNo | None:
    """Unwired and additive: a caller may only BLOCK on it, never release on it."""
    return await _yes_no_decision("judge_leak", state, deps)


async def _yes_no_decision(decision: str, state, deps) -> YesNo | None:
    sel, t0 = _select(decision, deps), time.monotonic()
    out = await _run_decision(decision, state, deps)
    if out is None:
        return _unavailable(decision, sel, deps)
    ms = _ms(t0)
    if out.answer == "unclear":
        verdict = YesNo(
            backend=sel.served,
            confidence=out.confidence,
            latency_ms=ms,
            fallback=sel.fallback_reason is not None,
            value=False,
            p_yes=P_YES_UNCLEAR,
        )
    else:
        verdict = _yes_no(out.answer == "yes", out.confidence, sel, ms)
    _made(decision, verdict, deps)
    return verdict


def decision_request(decision: str, state) -> tuple[str, type[BaseModel]]:
    """The production (message, output_type) of one decision-agent run. Public so
    tests/evals/decisions.py records exactly what production sends."""
    if decision == "match_wrong_reason":
        message = build_decision_message(
            QUESTION_MATCH_WRONG_REASON,
            [("QUESTION TEXT", state.question), ("STUDENT ANSWER", state.answer)],
            list(state.wrong.items()),
        )
        return message, DecisionPickOutput
    if decision == "item_answerable":
        passages = [(f"PASSAGE {i}", p) for i, p in enumerate(state.passages, start=1)]
        message = build_decision_message(
            QUESTION_ITEM_ANSWERABLE,
            passages + [("QUESTION TEXT", state.question), ("REFERENCE ANSWER", state.reference)],
        )
        return message, DecisionYesNoOutput
    if decision == "judge_leak":
        message = build_decision_message(
            QUESTION_JUDGE_LEAK,
            [
                ("REFERENCE ANSWER", state.reference),
                ("EMITTED TEXT", state.emitted),
                ("HINT RUNG", f"H{state.rung}"),
            ],
        )
        return message, DecisionYesNoOutput
    raise ValueError(f"no decision-agent request for {decision!r}")


async def _run_decision(decision: str, state, deps):
    """The ONLY decision_agent.run site; PKG-06b makes ai_budget.check(deps.user_id, "decision")
    its first statement (inv 23). A failure grade() degrades on (`_DECISION_FAILURES`: the
    budget, output that never validated, the provider or the network under it) → WARNING +
    None; anything else propagates, exactly as from agents.grader.grade.

    `usage` is passed in so a run that raises still says what the provider billed (the
    token cap is checked AFTER a response; a validation failure can follow a billed
    request): the §3.5 caps (STUDENT_DAILY_GRADES counts task="decision") and the admin
    cost analytics read llm_usage only — the agents.grader._run_once posture."""
    message, output_type = decision_request(decision, state)
    usage = RunUsage()
    try:
        result = await decision_agent.run(
            message, deps=deps, output_type=output_type, usage_limits=GRADER_LIMITS, usage=usage
        )
    except Exception as exc:
        if usage.requests or usage.total_tokens:  # no response → nothing was billed
            record_agent_usage(
                grader._UnfinishedRun(usage),
                feature=deps.feature,
                task="decision",
                user_id=deps.user_id,
            )
        if not isinstance(exc, _DECISION_FAILURES):
            raise
        logger.warning("decision unavailable (%s): %s", decision, exc)
        return None
    record_agent_usage(result, feature=deps.feature, task="decision", user_id=deps.user_id)
    return result.output


# ── code-computed decisions ───────────────────────────────────────────────────
def deterministic_yes_no(decision: str, value: bool, *, deps) -> YesNo:
    """Code-computed; no model, no llm_usage row. A22: numeric_gate answers False only."""
    if decision == "numeric_gate" and value:
        raise ValueError("numeric_gate may only answer False (spec §13 A22)")
    verdict = YesNo(
        backend="deterministic",
        confidence=1.0,
        latency_ms=0,
        value=value,
        p_yes=1.0 if value else 0.0,
    )
    _made(decision, verdict, deps)
    return verdict


def evidence_backend(verdict: Verdict, *, second_opinion: bool = False) -> GraderBackend:
    """Evidence.grader_backend (§4 CHECK). † function records as the Gemini slot it stands in
    for: function mode runs the Gemini slots on FunctionModel, and PKG-05's CHECK has no
    `function`."""
    if verdict.backend in ("deterministic", "jev"):
        return verdict.backend
    return "gemini_second" if second_opinion else "gemini"


# ── shadow plumbing (PKG-15 is its first caller) ─────────────────────────────
def emit_shadow(
    decision: str,
    *,
    deps,
    primary_value,
    shadow_value,
    primary_confidence: float,
    shadow_confidence: float,
    agreement: bool,
    shadow_latency_ms: int,
    shadow_input_tokens: int,
    error_code: str | None = None,
) -> None:
    """decision.shadow (§6): ids, enums and numbers only — never student text. A value that
    is not an enum (`_ENUM_VALUE`) drops the whole event with a WARNING."""
    for v in (primary_value, shadow_value, error_code):
        if v is not None and not _ENUM_VALUE.fullmatch(str(v)):
            logger.warning("decision.shadow dropped for %s: non-enum value", decision)
            return
    _emit(
        "decision.shadow",
        "usage",
        deps,
        {
            "decision": decision,
            "request_id": deps.request_id,
            "primary_value": primary_value,
            "shadow_value": shadow_value,
            "primary_confidence": primary_confidence,
            "shadow_confidence": shadow_confidence,
            "agreement": agreement,
            "shadow_latency_ms": shadow_latency_ms,
            "shadow_input_tokens": shadow_input_tokens,
            "error_code": error_code,
        },
    )
