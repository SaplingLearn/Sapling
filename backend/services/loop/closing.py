"""The session close (PKG-09, spec §9): POST /close, the legacy end-session
delegate, the close record and the served close text.
"""
from __future__ import annotations

import asyncio
import copy
import logging
import re
import uuid
from services.loop.errors import HTTPException
from starlette.requests import Request
from agents._run import run_agent_sync
from agents.session_close import run_session_close, shape_close
from db.connection import pg_quote_value, table
from learning.void_store import voided_by_node, voided_event_ids
from learning.ladder import Rung
from learning.leak import detect_leak
from learning.misconceptions import is_key, open_for
from learning.params import CLOSE_RUN_TIMEOUT_S
from learning.session_close import (
    CLOSE_FALLBACK_DETAILS,
    CloseRecord,
    build_close,
    fallback_close,
    session_probe_hashes,
    store_close,
)
from models import CloseBody, EndSessionBody
from services.tutor_sessions import PENDING_SESSIONS, claim_pending
from services import ai_budget, events_service
from services.ai_budget import AIBudgetExceeded
from services.auth_guard import get_session_user_id, guard_off_loop
from services.encryption import decrypt_if_present, decrypt_json_column
from services.check_item_service import get_check_item
from services.request_context import current_request_id
from services.session_modes import NOT_REVIEW

from services.loop.state import (
    _CLOSE_IN_PROGRESS,
    _close_phase,
    _CLOSE_STORE_FAILED,
    _gate,
    _GRADING_IN_FLIGHT,
    _grading_in_flight,
    _live,
    _loop_phase,
    _now_s,
    _request_id,
    _update_loop_state,
)
from services.loop.served import _item_check_kwargs
from services.loop.guard import option_text

#: Every module of the package logs as the route always did (the ops-log
#: mirror and the tests key on this logger name).
logger = logging.getLogger("routes.learn_loop")


# ── The served session close (PKG-09; spec §13 A25, A51) ─────────────────


def close_states_answer(text: str, item) -> bool:
    """Strict leak check of close text against one item the session posed but
    never released: in served mode (the item as posed is the provenance, as
    PKG-07's served_model_text reads it) AND with no provenance at all — a close
    is no tutor turn, so an answer in any position (a number word such as
    "came out to twelve", an option's text) is a leak. Fails closed: an item
    the check cannot read (no final answer) is a leak."""
    kwargs = _item_check_kwargs(
        reference=item.reference_answer,
        final_answer=item.final_answer,
        canonical_answer=item.canonical_answer,
        correct_option=item.correct_option,
        option_text=option_text(item),
    )
    try:
        return any(
            detect_leak(emitted=text, rung=Rung.H0, given=given, **kwargs).leaked
            for given in (item.prompt, None)
        )
    except (ValueError, TypeError):
        return True


def served_close(output, draft, unreleased_items) -> CloseRecord:
    """What the student is served (and `sessions.close_json` stores) for the
    close agent's `output` — the path the session_close eval gates:
    `agents.session_close.shape_close`, then the deterministic close when any
    served text states the answer of an unreleased item (never masked in
    place, A51 N1), itself leak-checked (`_served_fallback`)."""
    items = list(unreleased_items)
    record = shape_close(output, draft)
    if not record.model_written:
        return _served_fallback(draft, items)
    if any(close_states_answer(_close_text(record), i) for i in items):
        logger.warning("session close stated an unreleased item's answer; storing fallback close")
        return _served_fallback(draft, items)
    return record


def _unreleased_items(doc: dict | None) -> list:
    """The items the session posed (PKG-07's steps) whose answer the student
    has not been shown: never graded and not revealed by a hint payload. The
    probe's items never reach the transcript, so the close cannot see them."""
    if not doc:
        return []
    revealed = set(doc.get("revealed") or [])
    out = []
    for qh, entry in (doc.get("steps") or {}).items():
        if not isinstance(entry, dict) or qh in revealed or entry.get("graded_at") is not None:
            continue
        if entry.get("check_item_id"):
            item = get_check_item(entry["check_item_id"])
            if item is not None:
                out.append(item)
    return out


def _close_misconception_keys(user_id: str, evidence: list[dict]) -> list[str]:
    """PKG-10: the student's OPEN misconception keys on the concepts this
    session's evidence rows touched (`open_for`; identifier-shaped keys only,
    count descending). No evidence → no read, []. Never raises."""
    node_ids = sorted({e.get("node_id") for e in evidence or [] if e.get("node_id")})
    keys = [r["wrong_key"] for r in open_for(user_id, node_ids) if is_key(r.get("wrong_key"))]
    return list(dict.fromkeys(keys))  # one key open on two nodes is listed once


def _stored_close(row: dict) -> dict:
    record = decrypt_json_column(row.get("close_json")) or {}
    return {
        "close": record,
        "model_written": bool(record.get("model_written")),
        "close_phase": row.get("close_phase"),
    }


class _AlreadyClosed(Exception):
    """The document says `phase: close`: another close finished first."""


def _claim_close(session_id: str, claim: str, now: float) -> dict:
    """Take the session's close claim by compare-and-set (A38 06(q)); 409 while
    another close holds a live one, or while a check is being graded (its
    evidence is not written yet); `_AlreadyClosed` when a close already
    finished. Returns the document as claimed (claim keys stripped), so the
    phase and the unreleased items are read from the same state the claim saw."""
    out: dict = {}

    def take(doc: dict) -> None:
        if _loop_phase(doc) == "close":
            raise _AlreadyClosed()
        if doc.get("close_claim") != claim and _live(doc, "close_claim", now):
            raise HTTPException(status_code=409, detail=_CLOSE_IN_PROGRESS)
        if _grading_in_flight(doc, now):
            raise HTTPException(status_code=409, detail=_GRADING_IN_FLIGHT)
        out["doc"] = copy.deepcopy(
            {k: v for k, v in doc.items() if k not in ("close_claim", "close_claim_at")}
        )
        doc["close_claim"], doc["close_claim_at"] = claim, now

    _update_loop_state(session_id, take)
    return out.get("doc", {})


def _finish_close(session_id: str, claim: str, *, closed: bool) -> None:
    """Release the claim; a stored close also moves the phase to `close`.
    Best effort after the store: `close_json` is the record of truth."""

    def finish(doc: dict) -> None:
        if doc.get("close_claim") == claim:
            doc.pop("close_claim", None)
            doc.pop("close_claim_at", None)
        if closed:
            doc["phase"] = "close"

    try:
        _update_loop_state(session_id, finish)
    except Exception as exc:
        logger.warning("session close: loop state not updated (%s)", type(exc).__name__)


def _session_record(session_id: str) -> tuple[list[dict], list[dict]]:
    """The decrypted transcript and this session's evidence journal rows.
    Spec §13 A123: a concept graded in this session against an item staff
    retired since is left out of the close altogether — its void rows are no
    evidence, and the recorded p_before → p_after of its other rows ran
    through the void ones, so they no longer describe a valid trajectory."""
    msgs = table("messages").select(
        "role,content", filters={"session_id": f"eq.{session_id}"}, order="created_at.asc"
    )
    transcript = [
        {"role": m.get("role"), "content": decrypt_if_present(m.get("content"))}
        for m in msgs or []
    ]
    evidence = list(
        table("node_mastery_events").select(
            # A117: the columns learning.probe.is_probe_row binds a row's planning
            # envelope to, so the close counts check-in answers apart; A123: the
            # row id the void filter below reads
            "id,node_id,p_before,p_after,correct,channel,session_id,question_hash,"
            "check_item_id,assisted,max_rung,reason,planning_observation",
            filters={"session_id": f"eq.{session_id}", "event_type": "eq.evidence"},
            order="created_at.asc,evidence_seq.asc",
        )
        or []
    )
    voided = voided_event_ids(session_id=session_id) if evidence else set()
    void_nodes = {e.get("node_id") for e in evidence if e.get("id") in voided}
    return transcript, [e for e in evidence if e.get("node_id") not in void_nodes]


def _measured_before(user_id: str, session_id: str, evidence: list[dict]) -> set[str]:
    """Spec §13 A117: the nodes of this session's evidence that the journal
    measured BEFORE this session did — the node's first evidence row (journal
    order, owner-scoped) belongs to another session or to none (a quiz, a
    post-test). They report their change from the estimate before the session;
    every other node was first measured here and starts at that measurement,
    never at the BKT prior. Propagation is never journaled, so it measures
    nothing. Spec §13 A123: nor does a void row (graded against an item staff
    retired), so the node's first VALID row decides. The student's void ids
    are read once, by node, and each node's are left out of its read before
    the limit. One limit-1 read per node (idx_node_mastery_events_node); a
    failed read propagates (the close is retried, like the evidence read)."""
    out: set[str] = set()
    nodes = list(dict.fromkeys(e.get("node_id") for e in evidence or [] if e.get("node_id")))
    voided = voided_by_node(user_id) if nodes else {}
    for node_id in nodes:
        filters = {
            "graph_nodes.user_id": f"eq.{user_id}",
            "node_id": f"eq.{node_id}",
            "event_type": "eq.evidence",
        }
        if voided.get(node_id):
            filters["id"] = f"not.in.({','.join(pg_quote_value(v) for v in sorted(voided[node_id]))})"
        first = table("node_mastery_events").select(
            "session_id,graph_nodes!inner(user_id)",
            filters=filters,
            order="created_at.asc,evidence_seq.asc",
            limit=1,
        )
        if first and first[0].get("session_id") != session_id:
            out.add(node_id)
    return out


def _concept_names(user_id: str, node_ids: list[str]) -> dict[str, str]:
    ids = list(dict.fromkeys(n for n in node_ids if n))
    if not ids:
        return {}
    rows = table("graph_nodes").select(
        "id,concept_name", filters={"user_id": f"eq.{user_id}", "id": f"in.({','.join(ids)})"}
    )
    return {r["id"]: r["concept_name"] for r in rows or [] if r.get("id") and r.get("concept_name")}


def _close_text(record: CloseRecord) -> str:
    return "\n".join((record.summary, record.self_eval, record.if_then))


def _served_fallback(draft, items: list) -> CloseRecord:
    """The deterministic close as served (review MINOR 3): it prints concept
    names and numbers, so it passes the same leak check as a model close —
    named, then with the names withheld, then with no names or numbers."""
    record = fallback_close(draft)
    named_ok = not any(
        _name_in_answer(draft.concept_names.get(c.node_id, ""), i)
        for c in draft.concepts
        for i in items
    )
    for detail in CLOSE_FALLBACK_DETAILS:
        record = fallback_close(draft, detail=detail)
        if detail == "named" and not named_ok:
            continue
        if not any(close_states_answer(_close_text(record), i) for i in items):
            return record
    return record


_WORD = re.compile(r"[^\W_]+")


def _name_in_answer(name: str, item) -> bool:
    """Review round 2: a concept name whose words all appear in an unreleased
    item's final (or canonical) answer states it ("Base Case" for "a base
    case") — the bare name is no sentence the text check reads as an answer."""
    words = set(_WORD.findall((name or "").casefold()))
    answer = " ".join(filter(None, (item.final_answer, item.canonical_answer))).casefold()
    return bool(words) and words <= set(_WORD.findall(answer))


async def _model_close(
    draft, *, user_id: str, request_id: str, session_id: str | None = None
) -> object | None:
    """One close run under CLOSE_RUN_TIMEOUT_S (a timed-out run is the
    unavailable agent: the deterministic close is stored)."""
    try:
        return await asyncio.wait_for(
            run_session_close(draft, user_id=user_id, request_id=request_id, session_id=session_id),
            CLOSE_RUN_TIMEOUT_S,
        )
    except TimeoutError:
        logger.warning("session_close timed out; storing fallback close")
        return None


def _reread_close(session_id: str) -> dict:
    rows = table("sessions").select(
        "id,close_json,close_phase", filters={"id": f"eq.{session_id}", **NOT_REVIEW}, limit=1
    )
    if rows and rows[0].get("close_json") is not None:
        return _stored_close(rows[0])
    raise HTTPException(status_code=409, detail=_CLOSE_IN_PROGRESS)


async def close_session(
    session_id: str,
    user_id: str,
    *,
    request_id: str | None = None,
    rate_limit: str | None = None,
) -> dict:
    """Close a loop session (Behaviour 10). A pending (never-materialised)
    session has no transcript or evidence: its deterministic close is stored
    on the row the A11 helper creates, and its phase set to `close`. A
    materialised one is claimed, read, closed — the model only when it has
    evidence (A25; `run_session_close` itself returns None at the hard budget
    level), under CLOSE_RUN_TIMEOUT_S and past the inline A20 check
    (`rate_limit="raise"`: the 429; `"fallback"`: the deterministic close) —
    then stored ONCE (the write is conditional on `close_json IS NULL`), the
    phase moved to `close`, and `learn.session_closed` emitted. A close that
    finds the session already closed returns the stored close: no model call,
    no write, no event."""
    request_id = request_id or current_request_id() or str(uuid.uuid4())
    pending = await asyncio.to_thread(claim_pending, session_id, user_id)  # 404 if foreign
    claim = ""
    if pending is not None:
        phase = "close"
        record = fallback_close(build_close([], [], [], measured_before=()))
        row_defaults = {
            "mode": pending.get("mode"),
            "topic": pending.get("topic"),
            "offering_id": pending.get("offering_id"),
        }
    else:
        rows = await asyncio.to_thread(  # #117: off the event loop
            table("sessions").select,
            "id,user_id,loop_state,close_json,close_phase",
            # PKG-12: a review session is not a tutor session — never closed (404)
            filters={"id": f"eq.{session_id}", **NOT_REVIEW},
            limit=1,
        )
        if not rows:
            raise HTTPException(status_code=404, detail="Session not found")
        if rows[0].get("user_id") != user_id:
            raise HTTPException(status_code=404, detail="Session not found")
        if rows[0].get("close_json") is not None:
            return _stored_close(rows[0])
        had_state = bool(rows[0].get("loop_state"))
        claim = uuid.uuid4().hex
        try:
            doc = await asyncio.to_thread(_claim_close, session_id, claim, _now_s())  # #117
        except _AlreadyClosed:
            return await asyncio.to_thread(_reread_close, session_id)
        phase = _close_phase(doc) if had_state else "close"
        row_defaults = None
        try:
            transcript, evidence = await asyncio.to_thread(_session_record, session_id)  # #117
            keys = await asyncio.to_thread(_close_misconception_keys, user_id, evidence)
            # A117: honest baselines, and check-in answers counted apart
            # (the probe history is the claimed document's)
            measured = await asyncio.to_thread(_measured_before, user_id, session_id, evidence)
            names = await asyncio.to_thread(
                _concept_names, user_id, [e.get("node_id") for e in evidence]
            )
            draft = build_close(
                transcript,
                evidence,
                keys,
                measured_before=measured,
                probe_hashes=session_probe_hashes(doc),
                concept_names=names,
            )
            items = await asyncio.to_thread(_unreleased_items, doc)
            out = None
            if evidence:  # A25: no model without graded evidence
                limited = False
                if rate_limit:
                    try:
                        # A20 inline: a model may run (#117: the read, off the event loop)
                        await asyncio.to_thread(ai_budget.enforce_rate_limit_for, user_id)
                    except AIBudgetExceeded:
                        if rate_limit == "raise":
                            raise
                        limited = True
                if not limited:
                    out = await _model_close(
                        draft, user_id=user_id, request_id=request_id, session_id=session_id
                    )
            record = (
                served_close(out, draft, items)
                if out is not None
                else _served_fallback(draft, items)
            )
        except BaseException:
            await asyncio.to_thread(_finish_close, session_id, claim, closed=False)
            raise
    try:
        stored = await asyncio.to_thread(  # #117: off the event loop
            store_close, session_id, user_id, record, phase, row_defaults=row_defaults
        )
    except Exception as exc:
        if claim:
            await asyncio.to_thread(_finish_close, session_id, claim, closed=False)
        logger.warning("session close not stored (%s)", type(exc).__name__)
        raise HTTPException(status_code=502, detail=_CLOSE_STORE_FAILED) from None
    await asyncio.to_thread(_finish_close, session_id, claim, closed=True)  # a pending session's phase too
    if not stored:  # another close's write landed first: serve it, emit nothing
        return await asyncio.to_thread(_reread_close, session_id)
    events_service.log_event(
        "learn.session_closed",
        category="usage",
        user_id=user_id,
        request_id=request_id,
        payload={
            "session_id": session_id,
            "concepts": len(record.concepts),
            "misconceptions": len(record.misconceptions),
            "has_if_then": bool(record.if_then),
            "model_written": record.model_written,
        },
    )
    return {"close": record.model_dump(), "model_written": record.model_written, "close_phase": phase}


async def close(body: CloseBody, request: Request) -> dict:
    """POST /api/learn/loop/close (spec §9): require_self + the gate's 404; the
    A20 rate limit is checked inline, only when this close would run the model
    (spec §9: "inline where only some bodies run one"), so a gate-off student
    gets the 404 and a zero-evidence close always works."""
    if not body.user_id:
        body.user_id = await guard_off_loop(get_session_user_id, request)
    await guard_off_loop(_gate, body.user_id, request)
    return await close_session(
        body.session_id, body.user_id, request_id=_request_id(request), rate_limit="raise"
    )


def end_session(body: EndSessionBody, request: Request) -> None:
    """The legacy end_session's loop delegate (PKG-07's pass-through, filled by
    PKG-09): a materialised session with loop state gets its real close first
    (A20 inline check: rate-limited, the deterministic close; the run bounded by
    CLOSE_RUN_TIMEOUT_S); the legacy body then runs unchanged (ended_at, XP,
    the `summary_json` `flashcards._get_session_summary` reads, achievements).
    A pending session keeps the legacy early return. A check still being
    graded — a live grading claim, or a saved grade checkpoint (ADR 0038) —
    propagates the close's 409, and a close that was not acknowledged is a
    503: either way the legacy handler never sets ended_at over an unsettled
    grade (spec §13 A142 corrects A60, which said the session ended without a
    close). Nobody is stuck: a claim with no checkpoint goes stale after
    LOOP_GRADING_CLAIM_STALE_S, and a checkpoint is finished by the student's
    explicit retry (`pending_grade`), after which the end goes through.
    The legacy handler is sync (a worker thread), so the async close runs
    through the sanctioned `run_agent_sync` seam. Always returns None."""
    if body.session_id in PENDING_SESSIONS:
        return None
    try:
        rows = table("sessions").select(
            "loop_state", filters={"id": f"eq.{body.session_id}", **NOT_REVIEW}, limit=1
        )
        if rows and rows[0].get("loop_state"):
            run_agent_sync(
                close_session(
                    body.session_id,
                    body.user_id,
                    request_id=_request_id(request),
                    rate_limit="fallback",  # A20 inline: rate-limited → the deterministic close
                )
            )
    except HTTPException:
        raise
    except Exception:
        logger.warning("loop session close was not acknowledged; end deferred")
        raise HTTPException(status_code=503, detail="Session close unavailable; retry ending the session") from None
    return None
