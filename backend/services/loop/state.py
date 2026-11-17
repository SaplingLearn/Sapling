"""The request's loop state: the route-entry gate (require_self + the loop
gate, A38 00), the session's scope and arm, the budget pause, the PKG-06 loop
state document (read, compare-and-set update), its phase and the guards a
handler checks before it writes (open, teaching, closing, grading in flight).
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from collections.abc import Callable
from services.loop.errors import HTTPException
from starlette.requests import Request
from db.connection import table
from learning import grade_checkpoint
from learning import prequestion as prequestion_rules
from learning.checks import CheckItem
from learning.gate import learning_loop_for_request
from learning.loop_state_store import (
    LoopStateConflict,
    LoopSessionClosed,
    load_loop_state,
    update_loop_state,
)
from learning.params import CLOSE_PHASES, LOOP_GRADING_CLAIM_STALE_S
from learning.policy import LoopState, StepState
from services.academics import offering_course_id
from services.agent_events import SaplingEvent
from services.auth_guard import require_self
from services.request_context import current_request_id
from services.session_modes import NOT_REVIEW

from services.loop.constants import (
    _BUDGET_DETAIL,
    _FEEDBACK_PENDING,
    _NOT_ENABLED,
    _STATE_CONFLICT,
)
from services.loop.flags import _ANSWER_CLAIM

#: Every module of the package logs as the route always did (the ops-log
#: mirror and the tests key on this logger name).
logger = logging.getLogger("routes.learn_loop")


def _gate(user_id: str, request: Request) -> bool:
    """require_self, then the learning-loop gate, read ONCE per request (A38 00):
    a delegating legacy route has already read it and carries the result on
    `request.state.learning_loop` (routes/learn.py), so a delegated request
    costs one `user_settings` read, not two. Returns the gate for
    `SaplingDeps.learning_loop`; False is the spec §7 404."""
    loop_on = _gate_value(user_id, request)
    if not loop_on:
        raise HTTPException(status_code=404, detail=_NOT_ENABLED)
    return loop_on


def _gate_value(user_id: str, request: Request) -> bool:
    """require_self, then the gate's value (read once per request, A38 00)."""
    require_self(user_id, request)
    carried = getattr(request.state, "learning_loop", None)
    return carried if isinstance(carried, bool) else learning_loop_for_request(user_id)


def _now_s() -> float:
    return datetime.now(timezone.utc).timestamp()


def _loop_arm(user_id: str) -> str | None:
    """The student's within-student arm label (`user_settings.loop_arm`, PKG-14;
    set by the series owner in SQL, in no settings API field — A31's reason).
    Only a non-empty string is an arm; a missing row, a non-string value or a
    read error is no arm (variant A everywhere, no budget exemption), so the
    plumbing can never turn a student into an arm session by accident."""
    try:
        rows = table("user_settings").select("loop_arm", filters={"user_id": f"eq.{user_id}"})
    except Exception as exc:  # the arm is plumbing: a failed read is "no experiment"
        logger.warning("loop_arm read failed for %s: %s", user_id, type(exc).__name__)
        return None
    raw = rows[0].get("loop_arm") if rows and isinstance(rows[0], dict) else None
    return raw if isinstance(raw, str) and raw else None


def _arm_for(user_id: str, request: Request) -> str | None:
    """`_loop_arm`, read ONCE per request (carried on `request.state`)."""
    cache = getattr(request.state, "loop_arm", None)
    if isinstance(cache, tuple) and len(cache) == 2 and cache[0] == user_id:
        return cache[1]
    arm = _loop_arm(user_id)
    request.state.loop_arm = (user_id, arm)
    return arm


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", None) or current_request_id() or str(uuid.uuid4())


def _session_scope(session_id: str, user_id: str) -> tuple[str, str]:
    """(offering_id, abstract course_id) of a materialised session the requesting
    student owns. The loop-state store keys on the session id alone, so this
    ownership check is the route's (HANDOFF-06 Known gaps): 404 when no row
    exists, 403 when it is another student's. One `sessions` read. A daily
    review session (mode 'review', PKG-12) is never a loop session: its
    phase-less document would read as probing (`_loop_phase`), so it is a 404
    here and every probe/plan/teach/check route refuses it (A73)."""
    rows = table("sessions").select(
        "user_id,offering_id", filters={"id": f"eq.{session_id}", **NOT_REVIEW}, limit=1
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Session not found")
    if rows[0].get("user_id") != user_id:
        raise HTTPException(status_code=404, detail="Session not found")
    offering_id = rows[0].get("offering_id") or ""
    return offering_id, (offering_course_id(offering_id) if offering_id else "")


class _BudgetPaused(HTTPException):
    """Hard budget level with nothing deterministic to serve. An HTTPException
    so routes.learn._agent_turn_or_http_error (which maps any other Exception
    to 502) passes it through; the route re-raises it as PKG-06b's
    AIBudgetExceeded, whose registered handler renders the spec §3.5 429."""

    def __init__(self, decision) -> None:
        super().__init__(status_code=429, detail=_BUDGET_DETAIL)
        self.decision = decision


def _budget_data(decision) -> dict:
    """The pause notice (JSON `budget`, SSE `budget` data): level and reset, plus
    the binding scope and `session_capped` for PKG-13's banner (A39, 06b(j)) —
    the same keys the 429 body carries."""
    reset = decision.reset_at
    return {
        "level": decision.level,
        "reset_at": reset.isoformat() if reset else None,
        "scope": decision.scope,
        "session_capped": bool(decision.session_capped),
    }


def _budget_event(decision) -> SaplingEvent:
    return SaplingEvent(
        type="budget", step="loop", message="Tutor chat paused.", data=_budget_data(decision)
    )


def _item_like(item):
    """PKG-05's grade_answer takes a learning.checks.CheckItem and PKG-06's
    deterministic_content an ItemLike (attribute access); the check-item
    service hands back decrypted CheckItem models. A dict is validated into
    CheckItem."""
    return CheckItem.model_validate(item) if isinstance(item, dict) else item


# ── Loop state: PKG-06's JSON document ─────────────────────────────────────


class _StateConflict(HTTPException):
    """update_loop_state lost the compare-and-set on every retry (A38 06(q)): a
    409 on a JSON route; inside a stream it is a terminal `error` event (the
    on_complete guard, or the deterministic path's). An HTTPException so
    routes.learn._agent_turn_or_http_error passes it through."""

    def __init__(self) -> None:
        super().__init__(status_code=409, detail=_STATE_CONFLICT)


def _load_loop_state(session_id: str) -> dict:
    """The session's loop state as PKG-06's JSON document (`LoopState.to_json()`).
    For reading only: every write is `_update_loop_state`."""
    return load_loop_state(session_id).state.to_json()


def _update_loop_state(session_id: str, mutate: Callable[[dict], None], *, require_open: bool = False, require_existing: bool = False) -> dict:
    """The ONE loop-state write (A38 06(q)): `update_loop_state` with `mutate`
    applied to the FRESH document (on a conflict it runs again on the newer
    one), re-validated by PKG-06's typed parser — a malformed PKG-06 field
    raises ValueError here instead of reaching the database. `mutate` changes
    the document in place and must have no side effects. Returns the document
    as mutated (saved, or — no sessions row, A11 — logged and not saved)."""
    last: dict = {}

    def apply(state: LoopState) -> LoopState:
        doc = state.to_json()
        mutate(doc)
        last["doc"] = doc
        return LoopState.from_json(doc)

    try:
        extra = {"require_open": True} if require_open else {}
        saved = update_loop_state(session_id, apply, **extra)
    except LoopSessionClosed as exc:
        raise HTTPException(status_code=409, detail=_SESSION_CLOSED) from exc
    except LoopStateConflict as exc:
        logger.warning("loop state for %s: compare-and-set exhausted", session_id)
        raise _StateConflict() from exc
    if saved is None:
        if require_existing:
            raise HTTPException(status_code=409, detail="Session unavailable; reload before retrying")
        logger.warning("loop state for %s not saved: no sessions row", session_id)
        return last.get("doc", {})
    return saved.state.to_json()


def _steps(state: dict) -> dict:
    return state.setdefault("steps", {})


def _step_state(state: dict, question_hash: str | None) -> StepState:
    """PKG-06's typed view of one per-item entry (a fresh step when absent)."""
    entry = (state.get("steps") or {}).get(question_hash) if question_hash else None
    if not isinstance(entry, dict):
        return StepState(question_hash=question_hash or "")
    return LoopState.from_json({"steps": {question_hash: entry}}).steps[question_hash]


def _phase_for(state: dict) -> str:
    active = state.get("current")
    entry = (state.get("steps") or {}).get(active) if active else None
    if not isinstance(entry, dict):
        return "teach"
    if entry.get("graded_at") is not None:
        return "teach" if entry.get("feedback_given") is True else "feedback"
    return "check"


def _pending_grade(state: dict) -> dict | None:
    """Public recovery identity only; encrypted answer/outcome never leaves storage."""
    if _loop_phase(state) == "probe":
        current = (state.get("probe") or {}).get("current")
        if isinstance(current, dict) and grade_checkpoint.KEY in current:
            return {"kind": "probe", "question_hash": current["question_hash"]}
    active = state.get("current")
    entry = (state.get("steps") or {}).get(active) if active else None
    if isinstance(entry, dict) and grade_checkpoint.KEY in entry:
        return {"kind": "check", "question_hash": active}
    return None


def _require_no_pending_feedback(state: dict) -> None:
    """A committed grade stays current until its feedback is actually served.

    Ordinary chat retries that feedback from its saved verdict; activating a
    new check must not abandon it or count it as delivered. Ending the session
    remains a separate, explicit early end.
    """
    active = state.get("current")
    entry = (state.get("steps") or {}).get(active) if active else None
    if (
        isinstance(entry, dict)
        and entry.get("graded_at") is not None
        and entry.get("feedback_given") is not True
    ):
        raise HTTPException(status_code=409, detail=_FEEDBACK_PENDING)


def _loop_phase(doc: dict) -> str:
    """The session's loop phase (PKG-08's top-level `phase`: probe → plan →
    teach). A document without the key is probing, unless its plan is already
    approved (a document /plan/approve wrote before the key existed)."""
    phase = doc.get("phase")
    if isinstance(phase, str) and phase:
        return phase
    plan = doc.get("plan") if isinstance(doc.get("plan"), dict) else {}
    return "teach" if plan.get("approved") else "probe"


_SESSION_CLOSED = "this session is closed"


#: PKG-08 reopen: the teaching routes' 409 while the probe or the plan is open.
#: A posed probe item lives under `probe.current`, not PKG-07's `current`, so a
#: teach turn then would run with no guarded item (it could hand out the answer).
_TEACHING_CLOSED = {
    "probe": "finish the probe first",
    "plan": "finish the plan first",
    # PKG-09 (spec §9): close is the last phase — no turn after the stored close.
    "close": _SESSION_CLOSED,
}


def _require_open(state: dict) -> None:
    """PKG-09: the answer routes (/check/answer, /step/attempt) of a closed or
    closing session — its close is stored (or being written); evidence after it
    would sit outside it."""
    _refuse_while_closing(state, _now_s())


def _require_teaching(state: dict) -> None:
    detail = _TEACHING_CLOSED.get(_loop_phase(state))
    if detail:
        raise HTTPException(status_code=409, detail=detail)
    _refuse_while_closing(state, _now_s())  # PKG-09: nor while a close is being written


def _teaching_open(session_id: str, user_id: str) -> None:
    """Ownership, then the phase: a teaching route runs only once the plan is
    approved (spec §9: probe → plan → teach). Reads only; writes nothing."""
    _session_scope(session_id, user_id)
    state = _load_loop_state(session_id)
    _require_teaching(state)
    if _pending_grade(state):
        raise HTTPException(status_code=409, detail="Finish checking the saved answer before continuing")


def _turn_phase(kind: str, state_phase: str) -> str:
    """The phase a turn of `kind` runs in, given the document's phase."""
    if kind == "feedback":
        return "feedback"
    if kind == "hint_request" or (kind == "action" and state_phase == "check"):
        return "hint"
    if kind in ("unavailable", "refused"):
        return "check"
    if kind == "opener":
        return "teach"
    return state_phase


def _ms(seconds: float) -> int:
    """Whole milliseconds, never negative (zpd.step's *_ms keys)."""
    return max(0, round(timedelta(seconds=seconds) / timedelta(milliseconds=1)))


# ── The session close (PKG-09; spec §4, §6, §9, §13 A11/A19/A20/A25) ────────
#
# One close per session, stored encrypted on `sessions.close_json` with the
# phase it stopped in (`close_phase`); `loop_state["phase"]` becomes "close".
# A close is claimed first (`close_claim` in loop_state, compare-and-set) so two
# concurrent closes never both run the model; a stored close is returned as is.

_CLOSE_IN_PROGRESS = "session close in progress"


_CLOSE_STORE_FAILED = "Could not store the session close."


_GRADING_IN_FLIGHT = "a check is being graded; close again in a moment"


def _live(entry: dict, key: str, now: float) -> bool:
    """`entry[key]` is a claim younger than LOOP_GRADING_CLAIM_STALE_S."""
    return bool(entry.get(key)) and now - float(entry.get(f"{key}_at") or 0) <= (
        LOOP_GRADING_CLAIM_STALE_S
    )


def _grading_in_flight(doc: dict, now: float) -> bool:
    """A check or probe item is being graded under a live claim (A52/A55c): its
    evidence is not written yet, so a close now would miss it."""
    entries = [e for e in (doc.get("steps") or {}).values() if isinstance(e, dict)]
    probe = doc.get("probe") if isinstance(doc.get("probe"), dict) else {}
    if isinstance(probe.get("current"), dict):
        entries.append(probe["current"])
    # spec §13 A138 (review fix): a prequestion guess being saved under its
    # claim — its row is the commit point, so a close now would strand it
    cards = [r for r in prequestion_rules.records(doc).values() if isinstance(r, dict)]
    return any(grade_checkpoint.KEY in e or _live(e, "grading_claim", now) for e in entries) or any(
        _live(r, _ANSWER_CLAIM, now) for r in cards
    )


def _refuse_while_closing(doc: dict, now: float) -> None:
    """Grading and closing exclude each other on the session document: a
    grading claim is refused while the session is closed or a live close claim
    holds it (the close refuses a live grading claim, `_claim_close`)."""
    if _loop_phase(doc) == "close":
        raise HTTPException(status_code=409, detail=_SESSION_CLOSED)
    if _live(doc, "close_claim", now):
        raise HTTPException(status_code=409, detail=_CLOSE_IN_PROGRESS)


def _closing(doc: dict, now: float) -> bool:
    """`_refuse_while_closing`'s condition, as a predicate."""
    return _loop_phase(doc) == "close" or _live(doc, "close_claim", now)


def _close_phase(doc: dict | None) -> str:
    """Where the session stopped (spec §9): PKG-08's probe/plan, or — once
    teaching — PKG-07's teach / check / feedback for the active item; a
    session with no loop state at all closes as `close`."""
    if not doc:
        return "close"
    phase = _loop_phase(doc)
    if phase == "teach":
        phase = _phase_for(doc)
    return phase if phase in CLOSE_PHASES else "close"
