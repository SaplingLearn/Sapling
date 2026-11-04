"""The typed decision seam (#640, ADR 0027) — one interface, three backends.

Typed state in, typed answers out. A caller describes a handful of small
judgments as questions:

    YesNo(key, instructions, default=...)             -> bool
    Choice(key, instructions, options=..., default=...) -> one option key
    Score(key, instructions, levels=..., default=...)   -> one ordered level

and :func:`decide` returns one :class:`Answer` per key, each with a
confidence in [0, 1] (0 = no idea, 1 = certain — TypeSafe's convention, which
every backend is normalised to).

Backends — the caller names them (``decide(..., backend=, shadow=)``); the
one caller today, the tutor router, gets them from the ``decision_router``
feature flag through :func:`router_backends` (ADR 0029):

    off         the default. :func:`decide` does no work and answers every key
                with its safe default. Nothing about production cost or
                behaviour changes until an admin turns the flag on.
    flash_lite  the `decision` Pydantic AI agent (agents/decision.py) on the
                `decision` model slot — gemini-2.5-flash-lite unless
                SAPLING_MODEL_DECISION overrides it.
    jev         TypeSafe's Jev over HTTP (services/typesafe_client.py). On a
                missing key, a timeout, any HTTP/transport error or a
                malformed body it degrades to flash_lite, and from there to
                safe defaults. A state that cannot fit Jev's 32k budget even
                after truncation goes to flash_lite only if it fits that
                agent's own token budget; otherwise straight to defaults.
    function    under SAPLING_MODEL_MODE=function every non-off backend runs
                as this: the same agent on the FunctionModel, answered by the
                handler registered for task "decision"
                (agents/function_handlers_e2e.py). Jev and Gemini are never
                dialled in function mode. Outside function mode `function`
                means `off` (warned once) — never a live model.

A ``shadow`` backend (the flag's ``jev_shadow`` variant: flash_lite next to a
Jev primary) runs alongside the primary and records both, with per-key
agreement, on the one ``decision.made`` event — the #642 shadow-mode
acceptance. The shadow never falls back (that would just re-run the primary)
and never feeds the answer.

Contract, in the order it matters:

1. **Never raises.** Every failure — config, network, model, validation, a
   bug in this module — ends in safe defaults. A decision exists to make a
   request cheaper or safer; it must not be able to fail one.
2. **Below the confidence floor, the default wins.** Per key. The raw answer
   is still recorded on the event, because "what would it have said" is the
   data an accuracy review needs.
3. **Every call is observable.** One ``decision.made`` event per call with
   backend, fallback reason, latency, model, and each key's raw value,
   applied value and confidence; token usage goes to ``llm_usage`` with the
   real provider (``typesafe`` for Jev) so cost rollups stay honest.

What this module does NOT do: act on answers. Callers decide what an answer
means; the tutor router (services/tutor_router.py) currently only logs.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import time
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from services import events_service, typesafe_client

logger = logging.getLogger("sapling.decisions")

# ── Configuration ───────────────────────────────────────────────────────────

FLOOR_ENV = "SAPLING_DECISIONS_CONFIDENCE_FLOOR"
TIMEOUT_ENV = "SAPLING_DECISIONS_TIMEOUT_MS"
JEV_TIMEOUT_ENV = "SAPLING_DECISIONS_JEV_TIMEOUT_MS"

OFF, FLASH_LITE, JEV, FUNCTION = "off", "flash_lite", "jev", "function"
#: `function` only EXISTS under SAPLING_MODEL_MODE=function (the scripted
#: FunctionModel). In any other mode it resolves to `off` with a one-time
#: warning — never to a live model.
_BACKENDS = (OFF, FLASH_LITE, JEV, FUNCTION)

#: TypeSafe's own "solid default" floor (docs.typesafe.ai/confidence).
DEFAULT_CONFIDENCE_FLOOR = 0.5
#: flash_lite / function agent budget. Generous: the only caller today is
#: fire-and-forget, and a slow answer is still a data point.
DEFAULT_TIMEOUT_MS = 4000
#: Jev answers well under a second; past this, the fallback is the faster path.
DEFAULT_JEV_TIMEOUT_MS = 1500
#: Headroom under Jev's 32k state+longest-question budget for the request
#: envelope and our estimate's error.
_JEV_BUDGET_MARGIN = 1_000

_warned: set[str] = set()


def _warn_once(key: str, msg: str, *args: Any) -> None:
    if key not in _warned:
        _warned.add(key)
        logger.warning(msg, *args)


def _read_float(env: str, default: float) -> float:
    try:
        value = float(os.getenv(env) or default)
    except ValueError:
        return default
    return value if math.isfinite(value) else default


def _model_mode() -> str:
    from agents._providers import model_mode

    return model_mode()


def _effective(backend: str | None, *, role: str) -> str:
    """The backend that will actually run for a requested name.

    Function mode never dials a live model: every non-off backend becomes
    `function` (and a shadow is dropped — a second scripted answer compares
    nothing). Outside function mode `function` is `off`, and an unknown name
    is `off` too, each warned once."""
    name = (backend or OFF).strip().lower()
    if name not in _BACKENDS:
        _warn_once(f"{role}={name}", "decision %s %r is not one of %s; treating it as 'off'",
                   role, name, _BACKENDS)
        return OFF
    if name == OFF:
        return OFF
    if _model_mode() == "function":
        return FUNCTION if role == "backend" else OFF
    if name == FUNCTION:
        _warn_once(f"{role}=function",
                   "decision %s 'function' only applies under SAPLING_MODEL_MODE=function; "
                   "treating it as 'off'", role)
        return OFF
    return name


#: decision_router flag variant -> (primary, shadow) backends (#620/#672).
_FLAG_BACKENDS = {
    "off": (OFF, OFF),
    "jev": (JEV, OFF),
    "jev_shadow": (JEV, FLASH_LITE),
}


class FlagUnreadable(RuntimeError):
    """The decision_router flag could not be resolved: the flag store is
    unreadable. Distinct from "off" so the router can record the gap."""


ROUTER_FLAG = "decision_router"


def _backends_for(resolution: Any) -> tuple[str, str]:
    from services.feature_flags import STORE_UNREADABLE

    if resolution.step == "fail_closed" and resolution.detail == STORE_UNREADABLE:
        raise FlagUnreadable(STORE_UNREADABLE)
    primary, shadow = _FLAG_BACKENDS.get(resolution.variant, (OFF, OFF))
    return _effective(primary, role="backend"), _effective(shadow, role="shadow")


def router_backends(user_id: str | None) -> tuple[str, str]:
    """The tutor router's (primary, shadow) backends for this student.

    The `decision_router` feature flag decides (ADR 0029; its generic
    ``SAPLING_FLAG_DECISION_ROUTER`` env override is the kill switch). Under
    SAPLING_MODEL_MODE=function an on variant runs the scripted `function`
    backend with no shadow, so the E2E lane exercises the seam without ever
    dialling Jev or Gemini. May read the flag store (bounded — see
    feature_flags.STORE_TIMEOUT_S) on a cold cache: call it off the event
    loop, or try :func:`router_backends_cached` first. Raises
    :class:`FlagUnreadable` when the store cannot be read.
    """
    from services.feature_flags import explain

    return _backends_for(explain(ROUTER_FLAG, user_id))


def router_backends_cached(user_id: str | None) -> tuple[str, str] | None:
    """:func:`router_backends` without I/O — safe on the event loop — or None
    when the flag cache is cold for this student. Raises
    :class:`FlagUnreadable` inside the store's unreadable window."""
    from services.feature_flags import cached_explain

    resolution = cached_explain(ROUTER_FLAG, user_id)
    return None if resolution is None else _backends_for(resolution)


#: Env vars an earlier draft used to pick the backends. They do nothing now.
_REMOVED_ENV = ("SAPLING_DECISIONS_BACKEND", "SAPLING_DECISIONS_SHADOW")


def warn_removed_env() -> None:
    """Startup: a deployment that still sets the old backend env vars gets
    one WARNING per var naming the replacement, instead of silently running
    with the flag's default."""
    for name in _REMOVED_ENV:
        if (os.getenv(name) or "").strip():
            _warn_once(
                f"removed:{name}",
                "%s is set but no longer does anything: the tutor router's decision "
                "backends come from the `decision_router` feature flag (set it in "
                "/admin, or SAPLING_FLAG_DECISION_ROUTER=off|jev|jev_shadow)", name,
            )


def confidence_floor() -> float:
    return min(1.0, max(0.0, _read_float(FLOOR_ENV, DEFAULT_CONFIDENCE_FLOOR)))


def _timeout_s(env: str, default_ms: int) -> float:
    ms = _read_float(env, default_ms)
    return max(0.05, ms / 1000.0)


def agent_timeout_s() -> float:
    return _timeout_s(TIMEOUT_ENV, DEFAULT_TIMEOUT_MS)


def jev_timeout_s() -> float:
    return _timeout_s(JEV_TIMEOUT_ENV, DEFAULT_JEV_TIMEOUT_MS)


def worst_case_s() -> float:
    """Longest a :func:`decide` call can take: Jev, then its fallback."""
    return jev_timeout_s() + agent_timeout_s()


# ── Questions ───────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class YesNo:
    """A yes/no judgment (Jev's ``noul``). ``default`` is the safe answer."""

    key: str
    instructions: str
    default: bool
    when_yes: str | None = None
    when_no: str | None = None


@dataclass(frozen=True)
class Choice:
    """Pick one option. ``options`` is ``((key, description|None), ...)``.
    ``default`` may be None: "no opinion", for callers that keep their own
    behaviour when the seam can't answer."""

    key: str
    instructions: str
    options: tuple[tuple[str, str | None], ...]
    default: str | None


@dataclass(frozen=True)
class Score:
    """Rate on an ordered scale. ``levels`` is ``((key, description), ...)``
    from lowest to highest (Jev: 2–10 levels)."""

    key: str
    instructions: str
    levels: tuple[tuple[str, str], ...]
    default: str | None


Question = YesNo | Choice | Score


def _allowed(q: Question) -> tuple[str, ...]:
    if isinstance(q, YesNo):
        return ("yes", "no")
    if isinstance(q, Choice):
        return tuple(k for k, _ in q.options)
    return tuple(k for k, _ in q.levels)


def _canonical(q: Question, value: str) -> str:
    """Map a backend's spelling of an answer onto the question's own key.

    Models echo option keys with drifted case and stray whitespace
    ('Medium', ' hard '); an exact-match check would throw those away as
    `invalid` and the key would silently default. Matching is trimmed and
    case-insensitive, and returns the CANONICAL allowed key ('medium'), so
    the value a caller compares against is always one it declared. No match
    returns the trimmed value unchanged — `_resolve` then marks it invalid.
    """
    trimmed = value.strip()
    folded = trimmed.casefold()
    for key in _allowed(q):
        if key.strip().casefold() == folded:
            return key
    return trimmed


# ── Answers ─────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Answer:
    """One key's answer.

    ``value`` is what the caller should use: the backend's answer when it was
    confident enough, else the question's default. ``raw`` is what the backend
    actually said (None if it said nothing usable) — kept for accuracy review.
    """

    key: str
    value: bool | str | None
    confidence: float
    raw: bool | str | None = None
    defaulted: bool = False
    #: below_floor | missing | invalid | no_backend — why the default applied.
    default_reason: str | None = None
    #: P(yes) for a YesNo; None otherwise.
    probability: float | None = None
    #: Per-option / per-level distribution when the backend reports one.
    probabilities: dict[str, float] | None = None


@dataclass(frozen=True)
class DecisionResult:
    answers: dict[str, Answer]
    #: jev | flash_lite | function | none — who ACTUALLY answered.
    backend: str
    #: The backend that was tried first.
    requested: str
    latency_ms: int
    #: Why `backend` differs from `requested` (e.g. jev_timeout), or why
    #: nothing answered.
    fallback_reason: str | None = None
    model: str | None = None

    def value(self, key: str) -> Any:
        return self.answers[key].value

    def event_answers(self) -> dict:
        return {
            k: {
                "value": a.value,
                "raw": _event_raw(a),
                "confidence": round(a.confidence, 4),
                **({"defaulted": a.default_reason} if a.defaulted else {}),
            }
            for k, a in self.answers.items()
        }


#: What an out-of-set answer shows on the event. The Answer keeps the real
#: string (callers and tests can read it); the event does not, because an
#: off-list value is free model text — it can echo the student's message —
#: and the payload contract is enums/bools/floats only, never state text.
INVALID_RAW = "<invalid>"


def _event_raw(a: "Answer") -> Any:
    return INVALID_RAW if a.default_reason == "invalid" else a.raw


# Backend-level raw answer: (value in the question's allowed set, confidence,
# P(yes) or None, distribution or None).
_Raw = tuple[str, float, "float | None", "dict[str, float] | None"]


class _BackendFailed(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


# ── Resolution: raw backend answers → typed Answers ────────────────────────


def _clamp(x: Any, lo: float, hi: float) -> float | None:
    """``x`` as a float clamped into [lo, hi]; None if it is not a finite
    number (None, a string, NaN, ±inf)."""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(v):
        return None
    return min(hi, max(lo, v))


def _default_answer(q: Question, reason: str, raw: _Raw | None = None) -> Answer:
    if raw is None:
        raw_value = None
    elif reason == "invalid":
        # Outside the allowed set: keep EXACTLY what the backend said (typing
        # it would turn a YesNo "maybe" into False — a fabricated "no").
        raw_value = raw[0]
    else:
        raw_value = _typed(q, raw[0])
    return Answer(
        key=q.key,
        value=q.default,
        confidence=raw[1] if raw else 0.0,
        raw=raw_value,
        defaulted=True,
        default_reason=reason,
        probability=raw[2] if raw else None,
        probabilities=raw[3] if raw else None,
    )


def _typed(q: Question, value: str) -> bool | str:
    return (value == "yes") if isinstance(q, YesNo) else value


def _resolve(
    questions: Sequence[Question], raws: Mapping[str, _Raw | None], floor: float
) -> dict[str, Answer]:
    out: dict[str, Answer] = {}
    for q in questions:
        raw = raws.get(q.key)
        if raw is None:
            out[q.key] = _default_answer(q, "missing")
        elif raw[0] not in _allowed(q):
            out[q.key] = _default_answer(q, "invalid", raw)
        elif raw[1] < floor:
            out[q.key] = _default_answer(q, "below_floor", raw)
        else:
            out[q.key] = Answer(
                key=q.key,
                value=_typed(q, raw[0]),
                confidence=raw[1],
                raw=_typed(q, raw[0]),
                probability=raw[2],
                probabilities=raw[3],
            )
    return out


def _all_defaults(questions: Sequence[Question], reason: str) -> dict[str, Answer]:
    return {q.key: _default_answer(q, reason) for q in questions}


# ── Backend: the decision agent (flash_lite / function) ────────────────────


class _Prompt:
    """The decision agent's prompt for one :func:`decide` call, serialised at
    most once however many times the budget check and the agent ask for it
    (the shadow pre-check, the Jev fallback check and the run itself)."""

    __slots__ = ("_state", "_questions", "_text")

    def __init__(self, state: Any, questions: Sequence[Question]) -> None:
        self._state = state
        self._questions = questions
        self._text: str | None = None

    @property
    def text(self) -> str:
        if self._text is None:
            self._text = _agent_prompt(self._state, self._questions)
        return self._text


def _agent_prompt(state: Any, questions: Sequence[Question]) -> str:
    specs: list[dict] = []
    for q in questions:
        if isinstance(q, YesNo):
            spec: dict = {"key": q.key, "type": "yes_no", "instructions": q.instructions}
            if q.when_yes:
                spec["when_yes"] = q.when_yes
            if q.when_no:
                spec["when_no"] = q.when_no
        elif isinstance(q, Choice):
            spec = {
                "key": q.key, "type": "choice", "instructions": q.instructions,
                "options": {k: d for k, d in q.options},
            }
        else:
            spec = {
                "key": q.key, "type": "score", "instructions": q.instructions,
                "levels": {k: d for k, d in q.levels},
            }
        specs.append(spec)
    return json.dumps({"state": state, "questions": specs}, ensure_ascii=False, default=str)


async def _run_agent(
    prompt: _Prompt,
    questions: Sequence[Question],
    *,
    feature: str,
    user_id: str | None,
    request_id: str | None,
) -> tuple[dict[str, _Raw], str | None]:
    from agents import WORKER_LIMITS
    from agents.decision import decision_agent
    from agents.usage import record_agent_usage, served_model_name

    try:
        result = await asyncio.wait_for(
            decision_agent.run(prompt.text, usage_limits=WORKER_LIMITS),
            timeout=agent_timeout_s(),
        )
    except asyncio.TimeoutError as exc:
        raise _BackendFailed("agent_timeout") from exc
    except Exception as exc:
        # UnregisteredHandlerError (function mode with no handler), the
        # hermetic transport guard, Gemini errors, validation exhaustion...
        # all the same to the caller: this backend produced nothing.
        # Type name only at WARNING (no traceback: the E2E logscan oracle
        # treats tracebacks as findings, and this failure is handled); the
        # full chain is at DEBUG.
        logger.warning("decision agent failed (%s); using defaults", type(exc).__name__)
        logger.debug("decision agent failure detail", exc_info=True)
        raise _BackendFailed(f"agent_{type(exc).__name__}") from exc
    # request_id is explicit: the tutor router runs as a detached task (on the
    # streamed path, scheduled from inside the SSE generator), outside the
    # request contextvar, so the implicit lookup would leave the row orphaned
    # from its turn.
    record_agent_usage(result, feature=feature, task="decision", user_id=user_id,
                       request_id=request_id)

    by_key = {q.key: q for q in questions}
    raws: dict[str, _Raw] = {}
    for item in result.output.answers:
        q = by_key.get(item.key)
        if q is None or item.key in raws:
            continue  # unknown key, or a duplicate: first answer wins
        value = _canonical(q, item.value)
        conf = _clamp(item.confidence, 0.0, 1.0) or 0.0
        p_yes = None
        if isinstance(q, YesNo) and value in ("yes", "no"):
            # Map "yes, 0.6 confident" onto P(yes) so the two backends'
            # YesNo answers are comparable: confidence = |2p - 1|.
            p_yes = 0.5 + conf / 2 if value == "yes" else 0.5 - conf / 2
        raws[item.key] = (value, conf, p_yes, None)
    return raws, served_model_name(result, "decision")


#: Output-side reserve per decision-agent request: a five-key answer list is
#: a few hundred tokens; this is generous.
_AGENT_OUTPUT_RESERVE = 1_000


def _agent_budget_fits(prompt: _Prompt) -> bool:
    """Whether the decision agent can answer ``state`` inside WORKER_LIMITS.

    The threshold: the prompt, estimated with Jev's pessimistic ~3
    chars/token (Gemini's tokenizer runs nearer 4), plus an output reserve,
    must fit the total-token limit ``request_limit`` times over — the worst
    case, since each output-validation retry re-sends the whole prompt. A
    state over Jev's 32k budget is roughly 3x past that today, so this
    normally says no; it exists so a fallback is attempted only when it can
    succeed, and stays right if either budget changes.
    """
    from agents import WORKER_LIMITS

    limit = WORKER_LIMITS.total_tokens_limit
    if limit is None:
        return True
    requests = WORKER_LIMITS.request_limit or 1
    prompt_tokens = typesafe_client.tokens_for_chars(len(prompt.text))
    return (prompt_tokens + _AGENT_OUTPUT_RESERVE) * requests <= limit


# ── Backend: Jev ────────────────────────────────────────────────────────────


def _jev_question(q: Question) -> dict:
    if isinstance(q, YesNo):
        spec: dict = {"type": "noul", "instructions": q.instructions}
        if q.when_yes or q.when_no:
            spec["criteria"] = {"true": q.when_yes or "Yes.", "false": q.when_no or "No."}
        return spec
    if isinstance(q, Choice):
        # A Choice's criteria map IS its option list (Jev has no separate
        # options field), so an option can't be omitted. The docs accept a
        # null description, but a null is one schema-validator bug away from a
        # 422 that takes every key down with it; the option's own key is a
        # valid, harmless rubric. Never send null.
        return {"type": "choice", "instructions": q.instructions,
                "criteria": {k: (d if d is not None else k) for k, d in q.options}}
    return {"type": "score", "instructions": q.instructions,
            "criteria": [d for _, d in q.levels]}


def _fit_state(state: Any, truncatable: Sequence[str], question_tokens: int) -> Any:
    """Return a state that fits Jev's budget, or raise _BackendFailed.

    Only keys named in ``truncatable`` whose values are lists are trimmed,
    oldest (front) item first, each key exhausted before the next — e.g. a
    conversation tail. If that is not enough, the state is NOT clipped
    further: silently cutting the text being judged would change the
    judgment. It fails instead, and the seam falls back to flash_lite only
    when the state fits that agent's own token budget
    (:func:`_agent_budget_fits`) — at today's limits it does not, and the
    answer is the safe defaults.

    Linear: every item is serialized once. ``json.dumps`` output is
    context-free (no indent), so a list's serialized length is exactly
    ``2 + sum(item lengths) + 2 * (n - 1)`` (brackets and ", " separators),
    and dropping the front item of a list with ``n`` items shortens the whole
    document by its length plus 2 (plus 0 when it was the last one). A
    running total therefore tracks the size of every trimmed candidate
    without re-serializing it.
    """
    budget = typesafe_client.STATE_TOKEN_BUDGET - question_tokens - _JEV_BUDGET_MARGIN

    def dumps(v: Any) -> str:
        return json.dumps(v, ensure_ascii=False, default=str)

    def fits(chars: int) -> bool:
        return typesafe_client.tokens_for_chars(chars) <= budget

    lists = {
        key: state[key] for key in truncatable
        if isinstance(state, dict) and isinstance(state.get(key), list) and state[key]
    }
    if not lists:
        if fits(len(dumps(state))):
            return state
        raise _BackendFailed("jev_state_over_budget")

    # The document with every trimmable list emptied, plus each list's items.
    sizes = {key: [len(dumps(item)) for item in items] for key, items in lists.items()}
    total = len(dumps({**state, **{key: [] for key in lists}}))
    for key, item_sizes in sizes.items():
        total += sum(item_sizes) + 2 * (len(item_sizes) - 1)
    if fits(total):
        return state

    drop = {key: 0 for key in lists}
    for key in truncatable:
        if key not in sizes:
            continue
        item_sizes = sizes[key]
        while drop[key] < len(item_sizes) and not fits(total):
            remaining = len(item_sizes) - drop[key]
            total -= item_sizes[drop[key]] + (2 if remaining > 1 else 0)
            drop[key] += 1
        if fits(total):
            return {**state, **{k: lists[k][n:] for k, n in drop.items()}}
    raise _BackendFailed("jev_state_over_budget")


def _parse_jev_answer(q: Question, ans: Any) -> _Raw | None:
    if not isinstance(ans, dict):
        return None
    if isinstance(q, YesNo):
        p = _clamp(ans.get("noul"), 0.0, 1.0)
        if p is None:
            return None
        # Jev returns no confidence for noul; derive the same statistic it
        # uses for a two-option choice: (2 * max(p, 1-p) - 1) = |2p - 1|.
        return ("yes" if p >= 0.5 else "no", abs(2 * p - 1), p, None)
    probs_raw = ans.get("probabilities")
    probs: dict[str, float] | None = None
    if isinstance(probs_raw, dict):
        probs = {str(k): v for k, v in ((k, _clamp(v, 0.0, 1.0)) for k, v in probs_raw.items())
                 if v is not None}
    conf = _clamp(ans.get("confidence"), 0.0, 1.0)
    if conf is None:
        return None
    if isinstance(q, Choice):
        choice = ans.get("choice")
        if not isinstance(choice, str):
            return None
        return (_canonical(q, choice), conf, None, probs)
    # Score: the level is the distribution's mode; `score` (the expected
    # level, which can land between levels) is the fallback when the
    # distribution is missing or has no usable level. Map level indexes back
    # to OUR level keys. A key that is not a level index of THIS question
    # ("7" on a 3-level scale, "-1", "high") is ignored — one bad key must
    # not discard a valid distribution or a valid `score`.
    keys = [k for k, _ in q.levels]
    by_index: dict[int, float] = {}
    for k, v in (probs or {}).items():
        try:
            i = int(k)
        except ValueError:
            continue
        if 0 <= i < len(keys) and str(i) == k.strip():
            by_index[i] = v
    if by_index:
        index = max(by_index, key=lambda i: by_index[i])
    else:
        s = _clamp(ans.get("score"), 0.0, len(keys) - 1)
        if s is None:
            return None
        # Half-up, consistently: Python's round() is banker's rounding (0.5
        # -> 0 but 1.5 -> 2), and floor(s + 0.5) is not float-safe (the sum
        # 0.49999999999999994 + 0.5 rounds to 1.0). Compare the fractional
        # part instead. s is clamped to [0, n-1], so the index stays in range.
        whole = math.floor(s)
        index = whole + (1 if s - whole >= 0.5 else 0)
    named = {keys[i]: v for i, v in sorted(by_index.items())} or None
    return (keys[index], conf, None, named)


async def _run_jev(
    state: Any,
    questions: Sequence[Question],
    *,
    truncatable: Sequence[str],
    feature: str,
    user_id: str | None,
    request_id: str | None,
) -> tuple[dict[str, _Raw], str | None]:
    if _model_mode() != "real":
        # The #439 rule, applied to our other model vendor: nothing below the
        # model seam dials a real model outside real mode. (Function mode never
        # gets here — _effective() maps it to `function` — so this is the
        # belt-and-braces for any future non-real mode.)
        raise _BackendFailed("jev_model_mode")
    wire = {q.key: _jev_question(q) for q in questions}
    longest = max(
        (typesafe_client.estimate_tokens(json.dumps(v, ensure_ascii=False)) for v in wire.values()),
        default=0,
    )
    fitted = _fit_state(state, truncatable, longest)
    try:
        data = await typesafe_client.evaluate(fitted, wire, timeout_s=jev_timeout_s())
    except typesafe_client.JevError as exc:
        if exc.kind == "no_key":
            _warn_once("jev_no_key", "decision backend is jev but %s is unset; using the fallback",
                       typesafe_client.API_KEY_ENV)
        raise _BackendFailed(f"jev_{exc.kind}") from exc
    model = data.get("model") if isinstance(data.get("model"), str) else typesafe_client.model_name()
    usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
    # Output tokens are free on Jev; llm_pricing prices them at 0 so this row
    # costs exactly the input side. provider="typesafe" keeps Jev out of the
    # Gemini rollups. Jev's usage dict has no request count: this answered
    # call is one (and arms log_llm_usage's #689 zero-token check).
    events_service.log_llm_usage(
        feature=feature, task="decision", model=model, usage=usage,
        provider="typesafe", user_id=user_id, request_id=request_id, requests=1,
    )
    answers = data["answers"]
    raws: dict[str, _Raw] = {}
    for q in questions:
        parsed = _parse_jev_answer(q, answers.get(q.key))
        if parsed is not None:
            raws[q.key] = parsed
    if questions and not raws:
        # A 200 that answered nothing we can read (a renamed field, a new
        # answer shape) is a backend failure, not "Jev said the defaults":
        # all-defaults attributed to jev would poison the accuracy review.
        # One bad key still defaults only that key (see _resolve).
        raise _BackendFailed("jev_bad_answers")
    return raws, model


# ── The seam ────────────────────────────────────────────────────────────────


async def _answer_with(
    backend: str,
    state: Any,
    questions: Sequence[Question],
    *,
    truncatable: Sequence[str],
    feature: str,
    user_id: str | None,
    request_id: str | None,
    allow_fallback: bool,
    prompt: _Prompt | None = None,
) -> DecisionResult:
    """Run one backend (with Jev → flash_lite fallback when allowed) and
    resolve its answers. Never raises."""
    started = time.monotonic()
    floor = confidence_floor()
    fallback_reason: str | None = None
    served = backend
    if prompt is None:
        prompt = _Prompt(state, questions)

    def done(answers: dict[str, Answer], model: str | None) -> DecisionResult:
        return DecisionResult(
            answers=answers, backend=served, requested=backend,
            latency_ms=int((time.monotonic() - started) * 1000),
            fallback_reason=fallback_reason, model=model,
        )

    try:
        if backend == OFF:
            served = "none"
            return done(_all_defaults(questions, "no_backend"), None)
        if backend == JEV:
            jev_raws: dict[str, _Raw] | None = None
            try:
                jev_raws, model = await _run_jev(
                    state, questions, truncatable=truncatable, feature=feature,
                    user_id=user_id, request_id=request_id,
                )
            except _BackendFailed as exc:
                fallback_reason = exc.reason
            except Exception as exc:
                # Anything else inside the Jev path (a parser bug, an answer
                # shape nobody anticipated) is still just "Jev produced
                # nothing" — degrade like any other Jev failure rather than
                # jumping straight to all-defaults. Type name only at WARNING:
                # the E2E logscan oracle treats tracebacks as findings.
                logger.warning("jev backend failed unexpectedly (%s); using the fallback",
                               type(exc).__name__)
                logger.debug("jev failure detail", exc_info=True)
                fallback_reason = f"jev_unexpected_{type(exc).__name__}"
            if jev_raws is not None:
                return done(_resolve(questions, jev_raws, floor), model)
            if not allow_fallback or (
                fallback_reason == "jev_state_over_budget"
                and not _agent_budget_fits(prompt)
            ):
                # No fallback wanted — or none that could succeed: a state
                # too big for Jev is, at today's limits, too big for the
                # decision agent's WORKER_LIMITS too, and running it would
                # only bill a UsageLimitExceeded. Safe defaults, same reason.
                served = "none"
                return done(_all_defaults(questions, "no_backend"), None)
            served = FLASH_LITE
        # flash_lite and function share the agent path; the mode picks the model.
        raws, model = await _run_agent(prompt, questions, feature=feature, user_id=user_id,
                                       request_id=request_id)
        return done(_resolve(questions, raws, floor), model)
    except _BackendFailed as exc:
        fallback_reason = f"{fallback_reason}+{exc.reason}" if fallback_reason else exc.reason
        served = "none"
        return done(_all_defaults(questions, "no_backend"), None)
    except Exception as exc:  # a bug here must not fail the caller either
        logger.exception("decision seam failed unexpectedly")
        fallback_reason = f"seam_{type(exc).__name__}"
        served = "none"
        return done(_all_defaults(questions, "no_backend"), None)


#: The shadow's `fallback_reason` when the primary degraded onto the shadow's
#: own backend: the shadow's answer SERVED the turn, so there is no second
#: opinion to compare and `agree` is None — not a self-comparison at 100%.
SHADOW_SAME_AS_SERVED = "shadow_same_as_served"
#: The shadow's `fallback_reason` when it was a flash_lite shadow whose
#: prompt cannot fit the decision agent's WORKER_LIMITS: running it would only
#: bill a UsageLimitExceeded, so it is skipped and `agree` is None.
SHADOW_OVER_BUDGET = "shadow_over_budget"
_SHADOW_SKIPPED = (SHADOW_SAME_AS_SERVED, SHADOW_OVER_BUDGET)


def _skipped_shadow(questions: Sequence[Question], shadow_name: str,
                    reason: str) -> DecisionResult:
    return DecisionResult(
        answers=_all_defaults(questions, "no_backend"), backend="none",
        requested=shadow_name, latency_ms=0, fallback_reason=reason,
    )


async def _primary_with_shadow(
    primary_backend: str,
    shadow_name: str,
    state: Any,
    questions: Sequence[Question],
    common: Mapping[str, Any],
) -> tuple[DecisionResult, DecisionResult]:
    """Run the primary and the shadow concurrently, without ever running the
    same backend twice for one decision.

    The only primary that can degrade is Jev, and it degrades to flash_lite.
    When the shadow IS flash_lite, running the primary's own fallback would
    bill Gemini twice for the same prompt and then compare the fallback with
    itself (agreement: 100%, meaning nothing). So the Jev primary runs with
    its fallback disabled, and if it fails, the shadow's flash_lite result —
    already in flight, the exact call the fallback would have made — becomes
    the primary's answer, and the shadow is recorded as
    ``shadow_same_as_served`` with no agreement.
    """
    if shadow_name == FLASH_LITE and not _agent_budget_fits(common["prompt"]):
        # A doomed shadow (the #672 over-budget case: a state too big for Jev
        # is too big for the agent too). The primary runs alone and with its
        # own fallback rules, which send it to defaults for the same reason.
        primary = await _answer_with(primary_backend, state, questions,
                                     allow_fallback=True, **common)
        return primary, _skipped_shadow(questions, shadow_name, SHADOW_OVER_BUDGET)

    shadow_task = asyncio.ensure_future(
        _answer_with(shadow_name, state, questions, allow_fallback=False, **common)
    )
    shares_fallback = primary_backend == JEV and shadow_name == FLASH_LITE
    started = time.monotonic()
    try:
        primary = await _answer_with(primary_backend, state, questions,
                                     allow_fallback=not shares_fallback, **common)
    except BaseException:  # cancellation: don't strand the shadow's model call
        shadow_task.cancel()
        raise
    shadow = await shadow_task
    if not shares_fallback or primary.backend != "none":
        return primary, shadow
    # Jev failed: serve the flash_lite answer the fallback would have produced.
    reason = primary.fallback_reason or "jev_failed"
    if shadow.fallback_reason:
        reason = f"{reason}+{shadow.fallback_reason}"
    served = DecisionResult(
        answers=shadow.answers, backend=shadow.backend, requested=JEV,
        latency_ms=int((time.monotonic() - started) * 1000),
        fallback_reason=reason, model=shadow.model,
    )
    return served, _skipped_shadow(questions, shadow_name, SHADOW_SAME_AS_SERVED)


def _agreement(primary: DecisionResult, shadow: DecisionResult) -> dict[str, bool | None] | None:
    """Per key: do the two backends' RAW answers agree? None when either said
    nothing usable (agreement with a default is not agreement), and None
    outright when the shadow's answer is the one that served."""
    if shadow.fallback_reason in _SHADOW_SKIPPED:
        return None
    out: dict[str, bool | None] = {}
    for key, a in primary.answers.items():
        b = shadow.answers.get(key)
        if b is None or a.raw is None or b.raw is None:
            out[key] = None
        elif a.default_reason == "invalid" or b.default_reason == "invalid":
            # An off-list answer is a wrong answer, not a missing one: it
            # disagrees — even with another off-list answer that happens to
            # use the same words.
            out[key] = False
        else:
            out[key] = a.raw == b.raw
    return out


def emit(
    result: DecisionResult,
    *,
    feature: str,
    user_id: str | None,
    request_id: str | None,
    shadow: DecisionResult | None = None,
    extra: Mapping[str, Any] | None = None,
) -> None:
    """Record one ``decision.made`` event. Never raises. Payload carries
    enums/bools/floats only — never state text.

    ``extra`` is the caller's context (session_id, mode, ...). It can ADD
    keys, never replace the seam's own: a caller extra named ``backend`` or
    ``answers`` would otherwise rewrite who answered and what — exactly the
    fields an accuracy review trusts. Colliding extras are dropped (warned
    once per key)."""
    try:
        core: dict[str, Any] = {
            "feature": feature,
            "backend": result.backend,
            "requested": result.requested,
            "fallback_reason": result.fallback_reason,
            "model": result.model,
            "latency_ms": result.latency_ms,
            "floor": confidence_floor(),
            "answers": result.event_answers(),
        }
        if shadow is not None:
            core["shadow"] = {
                "backend": shadow.backend,
                "requested": shadow.requested,
                "fallback_reason": shadow.fallback_reason,
                "model": shadow.model,
                "latency_ms": shadow.latency_ms,
                "answers": shadow.event_answers(),
                "agree": _agreement(result, shadow),
            }
        for key in sorted(set(extra or ()) & set(core)):
            _warn_once(f"decision_extra:{key}",
                       "decision event extra %r collides with a core field; dropped", key)
        payload = {**(extra or {}), **core}
        events_service.log_event(
            "decision.made", category=events_service.SYSTEM_CATEGORY, user_id=user_id,
            request_id=request_id, payload=payload,
        )
        _span(payload)
    except Exception:
        logger.debug("decision event emission failed", exc_info=True)


def _span(payload: dict) -> None:
    """Mirror the decision onto a Logfire span (no-op when unconfigured).
    Attributes are the same enum/float fields as the event — no state."""
    try:
        import logfire

        attrs = {
            f"decision.{k}": payload[k]
            for k in ("feature", "backend", "requested", "fallback_reason", "model", "latency_ms")
        }
        for key, ans in payload["answers"].items():
            attrs[f"decision.answer.{key}"] = ans["value"]
            attrs[f"decision.confidence.{key}"] = ans["confidence"]
        if "shadow" in payload:
            attrs["decision.shadow.backend"] = payload["shadow"]["backend"]
            for key, agree in (payload["shadow"]["agree"] or {}).items():
                attrs[f"decision.shadow.agree.{key}"] = agree
        logfire.info("decision made", **attrs)
    except Exception:
        # The span is a convenience mirror of the event already emitted; a
        # Logfire problem must never fail (or log noise into) a decision.
        pass


async def decide(
    state: Any,
    questions: Sequence[Question],
    *,
    feature: str,
    user_id: str | None = None,
    request_id: str | None = None,
    truncatable: Sequence[str] = (),
    event_extra: Mapping[str, Any] | None = None,
    backend: str = OFF,
    shadow: str = OFF,
) -> DecisionResult:
    """Answer ``questions`` about ``state``. Never raises; see the module doc.

    ``state`` must be JSON-serialisable (a string, object or array — Jev's
    three accepted shapes). ``truncatable`` names top-level list-valued keys
    that may lose their OLDEST items to fit Jev's 32k budget.

    ``backend``/``shadow`` name the backends (the tutor router resolves them
    per student with :func:`router_backends`); both default to off. Function
    mode runs any non-off backend as `function` with no shadow, and a shadow
    equal to the primary is dropped (comparing a backend with itself is not a
    shadow run).

    With a shadow configured, both backends run concurrently and this awaits
    both — latency is the slower of the two. A primary that degrades onto the
    shadow's backend reuses the shadow's answer instead of running that
    backend a second time (see :func:`_primary_with_shadow`). That is fine for today's only
    caller (fire-and-forget); a future blocking caller on a hot path should
    run with the shadow off.

    Emits exactly one ``decision.made`` event (``event_extra`` is merged into
    its payload) unless the backend is off.
    """
    primary_backend = _effective(backend, role="backend")
    if primary_backend == OFF:
        return DecisionResult(
            answers=_all_defaults(questions, "no_backend"),
            backend="none", requested=OFF, latency_ms=0,
        )
    common = dict(truncatable=truncatable, feature=feature, user_id=user_id,
                  request_id=request_id, prompt=_Prompt(state, questions))
    shadow_name = _effective(shadow, role="shadow")
    if shadow_name == primary_backend:
        shadow_name = OFF
    try:
        if shadow_name == OFF:
            result = await _answer_with(primary_backend, state, questions,
                                        allow_fallback=True, **common)
            shadow = None
        else:
            result, shadow = await _primary_with_shadow(
                primary_backend, shadow_name, state, questions, common,
            )
    except Exception as exc:  # pragma: no cover - _answer_with never raises
        logger.exception("decision seam failed unexpectedly")
        result = DecisionResult(
            answers=_all_defaults(questions, "no_backend"), backend="none",
            requested=primary_backend, latency_ms=0,
            fallback_reason=f"seam_{type(exc).__name__}",
        )
        shadow = None
    emit(result, feature=feature, user_id=user_id, request_id=request_id,
         shadow=shadow, extra=event_extra)
    return result


def defaults_result(
    questions: Sequence[Question], *, reason: str, requested: str = OFF,
    latency_ms: int = 0,
) -> DecisionResult:
    """An all-defaults result, for callers whose own guard (e.g. a timeout
    around :func:`decide`) fired before the seam could answer."""
    return DecisionResult(
        answers=_all_defaults(questions, "no_backend"),
        backend="none",
        requested=requested,
        latency_ms=latency_ms,
        fallback_reason=reason,
    )
