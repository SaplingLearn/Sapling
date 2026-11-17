"""POST /step/attempt and POST /hint: the genuine-attempt signals (A134) and
the hint ladder's gates.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import re
from dataclasses import dataclass
from services.loop.errors import HTTPException
from starlette.requests import Request
import config
from learning import answer_guard, arms, gates, ladder, policy, zpd_events
from learning.ladder import Rung
from learning.help_ledger import record_help
from learning.params import HELP_NOVELTY_DIGESTS_MAX
from learning.policy import StepState
from models import LoopAttemptBody, LoopHintBody
from services.encryption import derive_key
from services.check_item_service import get_check_item

from services.loop.flags import _help_gate_strict_on
from services.loop.state import (
    _arm_for,
    _gate,
    _item_like,
    _load_loop_state,
    _now_s,
    _request_id,
    _require_open,
    _require_teaching,
    _session_scope,
    _step_state,
    _steps,
    _update_loop_state,
)
from services.loop.learner import (
    _band_ceiling_delta,
    _band_for,
    _band_of,
    _ceiling_for,
    _genuine,
    _learner_state,
    _learner_view,
    _node_for_item,
    _prereq_proficient,
    _seconds_since,
)
from services.loop.reveals import _ledger
from services.loop.cursor import _h6_ok
from services.loop.claims import _on_step, _record_attempt

#: Every module of the package logs as the route always did (the ops-log
#: mirror and the tests key on this logger name).
logger = logging.getLogger("routes.learn_loop")


# ── Attempt / hint / action / openers / end-session ───────────────────────


def _addresses_grader(text: str, check) -> bool:
    """A33 / Behaviour 12: text the answer guard refuses is never an attempt.
    The screen reads the item's rubric ids and its own text (so "R1: yes" about
    the item's own resistor stays an attempt); the bare screen when the item
    is gone."""
    terms = answer_guard.item_terms(_item_like(check)) if check is not None else {}
    return answer_guard.screen(text, **terms).refusal is not None


def _attempt_hash(text: str) -> str:
    """A normalised digest of an attempt (lowercase alphanumeric words), so a
    repeat with other spacing or punctuation is the same attempt. The text
    itself is never stored."""
    words = " ".join(re.findall(r"[a-z0-9]+", (text or "").lower()))
    return hashlib.sha256(words.encode("utf-8")).hexdigest()[:16]


# ── Spec §13 A133/A134: one attempt's structured signals ────────────────────

#: steps[qh] key (spec §13 A134): keyed digests of the answer tokens the
#: student's COUNTED attempts on the item held — the strict rule's novelty
#: memory, kept whichever rule is in force so the zpd.attempt measurement
#: (A133) sees repeats under either. A digest is HMAC-SHA256 under a key
#: derived from ENCRYPTION_KEY, over the item's hash and the token: neither a
#: token nor the attempt text is stored, and the same word on two items does
#: not match.
_ATTEMPT_TOKENS = "attempt_tokens"


_ATTEMPT_TOKEN_KEY = derive_key("learning/attempt-tokens")


#: hex characters kept per digest (48 bits: a new token's chance of matching
#: one of a step's HELP_NOVELTY_DIGESTS_MAX digests is about 1 in 10^12)
_ATTEMPT_TOKEN_HEX = 12


def _token_digest(question_hash: str, value: str) -> str:
    mac = hmac.new(_ATTEMPT_TOKEN_KEY, f"{question_hash}\x1f{value}".encode("utf-8"), hashlib.sha256)
    return mac.hexdigest()[:_ATTEMPT_TOKEN_HEX]


def _help_anchor(entry: dict) -> float | None:
    """When the student last got help on the item: the last rung shown, else
    the pose (the M1 rung anchor; spec §13 A134 measures time alone from it)."""
    return entry.get("last_rung_at") if entry.get("last_rung_at") is not None else entry.get("first_shown_at")


@dataclass(frozen=True)
class _AttemptSignals:
    """Spec §13 A134: what one attempt shows, measured on the attempt — never
    its length, never the item's key. `standard` is the §3.3 rule's verdict
    (A120's hedge tolerance included), `strict` the strict rule's."""

    alone_s: float  # since the latest help on the item (the last rung shown, else the pose)
    required_s: float  # the band's independent-time gate (variant, A5 time scale)
    novel: bool
    digests: frozenset[str]
    standard: bool
    strict: bool


def _attempt_signals(
    text: str, qh: str, entry: dict, check, *, standard: bool, band: str, variant: str, now: float
) -> _AttemptSignals:
    """The strict rule's inputs and verdict for one attempt on the step
    `entry` (gates.attempt_novelty and gates.strict_genuine_attempt): time
    alone since the latest help, novelty against the earlier counted attempts
    and the item's stem. Computed whichever rule is in force."""
    alone_s = _seconds_since(_help_anchor(entry), now)
    novel, digests = gates.attempt_novelty(
        text,
        stem=getattr(check, "prompt", None),
        seen=entry.get(_ATTEMPT_TOKENS) or (),
        digest=lambda value: _token_digest(qh, value),
    )
    scale = config.LEARNING_GATE_TIME_SCALE
    return _AttemptSignals(
        alone_s=alone_s,
        required_s=gates.independent_time_required(band, time_scale=scale, variant=variant),
        novel=novel,
        digests=digests,
        standard=standard,
        strict=gates.strict_genuine_attempt(
            standard, alone_s, novel, band, time_scale=scale, variant=variant
        ),
    )


def _remember_attempt_tokens(entry: dict, digests: frozenset[str]) -> None:
    """Add a counted attempt's token digests to the step's novelty memory,
    oldest kept first, at most HELP_NOVELTY_DIGESTS_MAX (past it a later
    attempt is compared with what is kept: the check errs toward counting)."""
    kept = list(entry.get(_ATTEMPT_TOKENS) or [])
    have = set(kept)
    for d in sorted(digests - have):
        if len(kept) >= HELP_NOVELTY_DIGESTS_MAX:
            break
        kept.append(d)
    entry[_ATTEMPT_TOKENS] = kept


def _ms_of(seconds: float) -> int:
    return int(round(max(0.0, seconds) * 1000))


# crisis support: a crisis attempt stops the hint flow — nothing counts toward a hint
def step_attempt(body: LoopAttemptBody, request: Request) -> dict:
    """Records a genuine attempt for hint unlocking only (spec §3.3). The text
    is judged by gates.is_genuine_attempt and the A33 screen, and never stored,
    never graded. M1 (review round 3): at most ONE attempt counts per rung
    anchor (since the last rung unlock, else the pose), and only one that
    differs from every earlier attempt on the item (`attempt_hashes`), so
    spamming the route cannot open the next rung; the route is rate-limited.

    Spec §13 A134: with the `help_gate_strict` flag on, an attempt counts only
    by the strict rule (gates.strict_genuine_attempt: the band's independent
    time alone since the latest help, and something no counted attempt on the
    item said, not a paste of the stem). Off, the response and every step key
    the §3.3 rule writes are exactly as before A134. Either way the step keeps
    the counted attempts' token digests (`attempt_tokens`) and one zpd.attempt
    records the attempt's signals (spec §13 A133)."""
    _gate(body.user_id, request)
    _session_scope(body.session_id, body.user_id)
    state = _load_loop_state(body.session_id)
    _require_open(state)
    qh = body.question_hash
    entry = _steps(state).get(qh)
    if not isinstance(entry, dict):
        raise HTTPException(status_code=404, detail="No such check item in this session")
    check = get_check_item(entry["check_item_id"]) if entry.get("check_item_id") else None
    node_id = _node_for_item(body.user_id, check) if check else None
    band, _ = _band_for(body.user_id, node_id)
    variant = arms.variant_for(body.user_id, node_id or "", _arm_for(body.user_id, request))
    now = _now_s()
    independent_s = _seconds_since(entry.get("first_shown_at"), now)
    standard = bool(
        _genuine(body.attempt_text, independent_s, band, variant)
    ) and not _addresses_grader(body.attempt_text, check)
    strict_on = _help_gate_strict_on(body.user_id)

    def signals_of(e: dict) -> _AttemptSignals:
        return _attempt_signals(
            body.attempt_text, qh, e, check, standard=standard, band=band, variant=variant, now=now
        )

    signals = signals_of(entry)
    genuine = signals.strict if strict_on else standard
    digest = _attempt_hash(body.attempt_text)
    counted: dict = {}

    def record(e: dict) -> None:
        counted.clear()
        anchor = (
            e.get("last_rung_at") if e.get("last_rung_at") is not None else e.get("first_shown_at")
        )
        if any(float(t) > float(anchor or 0) for t in e.get("attempted_at") or []):
            return  # this rung anchor already has its attempt
        if digest in (e.get("attempt_hashes") or []):
            return  # the same attempt again is no new work
        fresh = signals_of(e)
        if strict_on and not fresh.strict:
            return  # A134: re-judged on the fresh document (a rung granted, an attempt counted meanwhile)
        _record_attempt(e, now, failed=True)  # the step stays open: a failed genuine attempt
        e["attempt_hashes"] = [*(e.get("attempt_hashes") or []), digest]
        _remember_attempt_tokens(e, fresh.digests)  # A134's novelty memory (either rule)
        counted["yes"] = True

    rung = int(entry.get("rung") or 0)
    if genuine:
        state = _update_loop_state(body.session_id, _on_step(qh, record))
        entry = _steps(state).get(qh) or entry
    zpd_events.emit_zpd_attempt(
        user_id=body.user_id,
        request_id=_request_id(request),
        session_id=body.session_id,
        question_hash=qh,
        concept_id=node_id,
        band=band,
        gate="strict" if strict_on else "standard",
        rung=Rung(min(max(rung, int(Rung.H0)), int(Rung.H6))),
        since_pose_ms=_ms_of(independent_s),
        alone_ms=_ms_of(signals.alone_s),
        gate_ms=_ms_of(signals.required_s),
        novel=signals.novel,
        standard=standard,
        strict=signals.strict,
        counted=bool(counted),
    )
    return {
        "genuine": genuine,
        "counted": bool(counted),
        "attempts": len(entry.get("attempted_at") or []),
        "independent_s": independent_s,
    }


def _mark_earnest_blocked(session_id: str, qh: str, step: StepState, entry: dict) -> None:
    """Spec §10's earnest-revise signal (spec §13 A109): /hint denied a rung
    because the ceiling (or the H6 gate) held, on a step with a genuine attempt
    (`attempted_at` holds genuine attempts only). Never for `no_genuine_attempt`
    or `dwell` — the dwell clock lifts with the same attempt, so it is not the
    ceiling holding. Stored on the step's loop_state entry (a StepState.extra
    key) by the compare-and-set write, so the feedback turn's zpd.step carries
    it. Written once per step. A measurement: a failed write is logged and the
    deny is served unchanged."""
    if not step.attempted_at or entry.get("earnest_blocked") is True:
        return

    def mark(e: dict) -> None:
        if e.get("graded_at") is None and e.get("attempted_at"):
            e["earnest_blocked"] = True

    try:
        _update_loop_state(session_id, _on_step(qh, mark))
    except Exception:
        logger.warning("earnest_blocked not recorded for %s", qh, exc_info=True)


def _rung_gate_denial(step: StepState, now: float) -> dict | None:
    """gates.rung_unlock's denial for /hint — "dwell" when a genuine attempt
    came since the rung anchor, else "no_genuine_attempt" — or None (open)."""
    if gates.rung_unlock(step, now, time_scale=config.LEARNING_GATE_TIME_SCALE):
        return None
    anchor = step.last_rung_at if step.last_rung_at is not None else step.first_shown_at
    attempted = any(t > anchor for t in step.attempted_at)
    return {"denied": "dwell" if attempted else "no_genuine_attempt"}


def _hint_gate_denial(
    body: LoopHintBody, request: Request, entry: dict, step: StepState, now: float
) -> dict | None:
    """`_rung_gate_denial`, worded for the strict rule (spec §13 A134). With
    the `help_gate_strict` flag on, a step with no counted attempt since the
    rung anchor whose time alone with that help is still short of the band's
    independent-time gate answers "dwell" (LoopLearn: "Stay with this step a
    little longer before the next hint.") — the time is what is missing, not
    the attempt. Flag off: exactly `_rung_gate_denial`, and nothing more is read."""
    denied = _rung_gate_denial(step, now)
    if denied != {"denied": "no_genuine_attempt"} or not _help_gate_strict_on(body.user_id):
        return denied
    check = get_check_item(entry["check_item_id"]) if entry.get("check_item_id") else None
    node_id = _node_for_item(body.user_id, check) if check else None
    band, _ = _band_for(body.user_id, node_id)
    variant = arms.variant_for(body.user_id, node_id or "", _arm_for(body.user_id, request))
    required = gates.independent_time_required(
        band, time_scale=config.LEARNING_GATE_TIME_SCALE, variant=variant
    )
    if _seconds_since(_help_anchor(entry), now) < required:
        return {"denied": "dwell"}
    return denied


def hint(body: LoopHintBody, request: Request) -> dict:
    """Moves the active item's rung up one, behind the dwell / attempt gate, the
    ceiling and — at H6 — the item predicates (A32). The hint TEXT is the next
    `[ACTION: hint]` turn's (PKG-13), deterministic when a leak-clean payload
    exists. No model call. Spec §13 A122: on an item that opens on the worked
    example (`worked_first`, set at activation), the first hint unlocks H4
    with no attempt and no dwell before it while policy.worked_example_rung
    grants it — the example comes FIRST; every later rung keeps the gate."""
    _gate(body.user_id, request)
    _session_scope(body.session_id, body.user_id)
    state = _load_loop_state(body.session_id)
    _require_teaching(state)
    qh = body.question_hash
    entry = _steps(state).get(qh)
    if not isinstance(entry, dict) or state.get("current") != qh:
        return {"denied": "no_active_item"}
    step = _step_state(state, qh)
    now = _now_s()
    may_jump = entry.get("worked_first") is True and step.rung < Rung.H4
    if not may_jump and (denied := _hint_gate_denial(body, request, entry, step, now)):
        return denied
    check = get_check_item(entry["check_item_id"]) if entry.get("check_item_id") else None
    node_id = _node_for_item(body.user_id, check) if check else None
    learner = _learner_state(body.user_id, node_id)
    band, _ = _band_of(learner)
    prereq = _prereq_proficient(body.user_id, node_id) if node_id else True
    view = _learner_view(learner, band=band, prereq_proficient=prereq)
    delta = _band_ceiling_delta(state, node_id)  # spec §13 A122: the band's ceiling only
    jump = policy.worked_example_rung(view, step, worked_first=may_jump, band_delta=delta)
    if jump is None and may_jump and (denied := _hint_gate_denial(body, request, entry, step, now)):
        return denied  # the learner left the worked-example row: the ordinary gate
    # an empty message: showed_work comes from the step alone — the floor-at-H3 rule
    # is applied by the turn that carried the work, never by a hint request
    ceiling, _ = _ceiling_for(
        step=step, learner=view, message="", independent_s=0.0, band_delta=delta
    )
    next_rung = int(jump) if jump is not None else int(step.rung) + 1
    if next_rung > int(ceiling):
        _mark_earnest_blocked(body.session_id, qh, step, entry)
        return {"denied": "ceiling"}
    if next_rung == int(Rung.H6) and not _h6_ok(state, qh, entry, check):
        _mark_earnest_blocked(body.session_id, qh, step, entry)
        return {"denied": "h6_gate"}
    accepted: dict = {}

    def unlock(e: dict) -> None:
        accepted.clear()
        if int(e.get("rung") or 0) >= next_rung:
            return  # a concurrent request already moved it this far
        e["rung"], e["last_rung_at"] = next_rung, now
        e["rungs"] = [*(e.get("rungs") or []), {"rung": next_rung, "at": now}]
        if e.get("offered"):
            e["offered"] = False
            accepted["offer"] = True

    _update_loop_state(body.session_id, _on_step(qh, unlock))
    # A93: the rung is granted now — recorded in the help ledger before its text is served
    _ledger(record_help, body.user_id, qh, next_rung, source="loop", session_id=body.session_id)
    if accepted.get("offer"):
        zpd_events.emit_zpd_offer(
            user_id=body.user_id, request_id=_request_id(request), accepted=True, band=band
        )
    return {"rung": next_rung, "intent": ladder.intent(Rung(next_rung))}
