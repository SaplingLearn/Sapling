"""
backend/services/quiz/attempts.py — moved from routes/quiz.py (#118).

Attempt lifecycle: the derived status, the owned-attempt load and its
refusals, the lazy abandon sweep, the attempt insert, and the /answer and
/abandon handler bodies (#542 D2, #541 C1, #537 G4, #760).

Function bodies are verbatim from the route; names (leading
underscores included) are unchanged, and routes/quiz.py re-exports them.
"""
import logging
from datetime import datetime, timedelta, timezone

from starlette.requests import Request

from db.connection import table
from models import AnswerQuestionBody
from services.auth_guard import require_self, guard_off_loop
from services.quiz.config import QUIZ_ATTEMPT_ABANDON_TTL_HOURS
from services.quiz.errors import QuizAPIError, QuizErrorCode
from services.encryption import encrypt_json, decrypt_json_column
from services.quiz.grading import WRITTEN_TYPES, grade_written
from services.timestamps import parse_ts
from services.quiz.wire import _strip_answer_key, _written_response_text
from learning import quiz_evidence
from learning.evidence import stated_confidence

# Log records keep the name they had in routes/quiz.py before the #118 split:
# the move must not change what an operator (or a caplog test) filters on.
logger = logging.getLogger("routes.quiz")


def _abandon_cutoff() -> datetime:
    return datetime.now(timezone.utc) - timedelta(
        hours=QUIZ_ATTEMPT_ABANDON_TTL_HOURS
    )


#: THE stored-timestamp parser, now in `services/timestamps.py` so a service
#: can use it without importing a route (see that module). Kept as a
#: module-level name because this file's readers — and their tests — refer to
#: it by this one.
_parse_ts = parse_ts


def _attempt_status(attempt: dict, last_activity_at=None) -> str:
    """#542 D2: status is DERIVED from the timestamps, never stored, so it
    can't drift. An in-progress row past the TTL reads as abandoned even
    before the lazy sweep has stamped abandoned_at.

    `last_activity_at` is the newest recorded answer (quiz_responses):
    a quiz generated days ago but answered minutes ago is being WORKED ON,
    not abandoned — keying the TTL on created_at alone would strand the
    responses already recorded against it.
    """
    if attempt.get("completed_at"):
        return "completed"
    if attempt.get("abandoned_at"):
        return "abandoned"
    cutoff = _abandon_cutoff()
    latest = max(
        (t for t in (_parse_ts(attempt.get("created_at")),
                     _parse_ts(last_activity_at)) if t is not None),
        default=None,
    )
    if latest is not None and latest < cutoff:
        return "abandoned"
    return "in_progress"


def _attempt_not_found() -> QuizAPIError:
    """The one 404 for "that attempt isn't there" — raised from the load
    preamble and from both lost-claim re-reads."""
    return QuizAPIError(
        status_code=404,
        code=QuizErrorCode.QUIZ_ATTEMPT_NOT_FOUND,
        message="We couldn't find that quiz.",
    )


def _already_completed() -> QuizAPIError:
    """The one 409 for "that attempt is already scored"."""
    return QuizAPIError(
        status_code=409,
        code=QuizErrorCode.QUIZ_ATTEMPT_ALREADY_COMPLETED,
        message="This quiz has already been submitted.",
    )


def _load_owned_attempt(attempt_id: str, request: Request, columns: str = "*") -> dict:
    """Read one attempt or 404, then refuse anyone but its owner.

    Verbatim in four routes before #537 G4's review (get_attempt,
    answer_question, submit_quiz, abandon_attempt). `columns` is a projection
    knob, not a policy one: `user_id` must be in it, because the ownership
    check is the whole point.
    """
    rows = table("quiz_attempts").select(columns, filters={"id": f"eq.{attempt_id}"})
    if not rows:
        raise _attempt_not_found()
    attempt = rows[0]
    require_self(attempt["user_id"], request)
    return attempt


async def _aload_owned_attempt(attempt_id: str, request: Request, columns: str = "*") -> dict:
    """`_load_owned_attempt` on the async seam (#117), for `async def` routes."""
    rows = await table("quiz_attempts").aselect(columns, filters={"id": f"eq.{attempt_id}"})
    if not rows:
        raise _attempt_not_found()
    await guard_off_loop(require_self, rows[0]["user_id"], request)
    return rows[0]


def _refuse_if_completed(attempt: dict) -> None:
    """409 on an attempt that has already been scored — the mirror of
    `_refuse_if_abandoned`, and the same shape everywhere it is used."""
    if attempt.get("completed_at"):
        raise _already_completed()


def _refuse_if_abandoned(attempt: dict) -> None:
    """409 on an attempt that is closed — swept as stale (#542 D2) or
    discarded on purpose (#537 G4).

    Checks the STAMP, not the derived TTL: a student mid-quiz whose
    attempt merely crossed the age cutoff keeps working (their answers
    refresh the activity clock — see _attempt_status), but once the stamp is
    on the row the attempt is closed.

    The sentence covers BOTH ways a row gets that stamp, because nothing here
    can tell them apart — `abandoned_at` records when the row closed, not who
    closed it. The client's own copy for this code
    (`lib/quiz/errors.ts::QUIZ_ERROR_COPY`) says the same thing.
    """
    if attempt.get("abandoned_at"):
        raise QuizAPIError(
            status_code=409,
            code=QuizErrorCode.QUIZ_ATTEMPT_ABANDONED,
            message="This quiz was discarded or expired. Start a new one when you're ready.",
        )


def _recent_activity(attempt_ids: set[str]) -> dict[str, str]:
    """Newest answer time per attempt, among answers inside the abandon window.

    The `last_activity_at` half of `_attempt_status`, read in bulk. Only
    answers newer than the cutoff can change a derived status (an answer is
    never older than its attempt's `created_at`), so filtering on the cutoff
    keeps the read small without changing any answer. Raises on a failed read:
    callers decide whether "unknown" means skip (the sweep) or fall back.
    """
    if not attempt_ids:
        return {}
    rows = table("quiz_responses").select(
        "attempt_id,answered_at", filters=_activity_filters(attempt_ids),
    ) or []
    return _latest_answers(rows)


async def _arecent_activity(attempt_ids: set[str]) -> dict[str, str]:
    """`_recent_activity` on the async seam (#117), for `async def` readers."""
    if not attempt_ids:
        return {}
    rows = await table("quiz_responses").aselect(
        "attempt_id,answered_at", filters=_activity_filters(attempt_ids),
    ) or []
    return _latest_answers(rows)


def _activity_filters(attempt_ids: set[str]) -> dict:
    return {
        "attempt_id": f"in.({','.join(sorted(attempt_ids))})",
        "answered_at": f"gte.{_abandon_cutoff().isoformat()}",
    }


def _latest_answers(rows: list[dict]) -> dict[str, str]:
    latest: dict[str, str] = {}
    for r in rows:
        aid, ts = r.get("attempt_id"), r.get("answered_at")
        if not aid or not ts:
            continue
        prev = latest.get(aid)
        parsed, prev_parsed = _parse_ts(ts), _parse_ts(prev)
        if prev is None or (
            parsed is not None and (prev_parsed is None or parsed > prev_parsed)
        ):
            latest[aid] = ts
    return latest


def _sweep_abandoned(user_id: str, *, active_attempt_ids: set[str] | None = None) -> None:
    """Stamp abandoned_at on this user's stale in-progress attempts (#542
    D2). Conditional-update filters arbitrate — same idiom as the submit
    claim — and it runs lazily on the read paths, so no scheduler is
    needed. Best-effort: a failure never breaks the read.

    #760: "stale" is `_attempt_status`'s rule, not `created_at` alone. An
    attempt generated more than a TTL ago but ANSWERED inside it is being
    worked on; stamping it (as opening history used to) made the student's
    next answer and submit 409. Candidates old by `created_at` are checked
    against their recent responses and the live ones are exempted. If that
    activity read fails, nothing is swept — a later read will try again,
    whereas a wrong stamp cannot be taken back.

    `active_attempt_ids` are attempts the caller already knows are live.
    """
    filters = {
        "user_id": f"eq.{user_id}",
        "completed_at": "is.null",
        "abandoned_at": "is.null",
        "created_at": f"lt.{_abandon_cutoff().isoformat()}",
    }
    try:
        candidates = table("quiz_attempts").select("id", filters=filters) or []
        stale = {r["id"] for r in candidates if r.get("id")}
        stale -= active_attempt_ids or set()
        if stale:
            stale -= set(_recent_activity(stale))
        if not stale:
            return
        filters["id"] = f"in.({','.join(sorted(stale))})"
        table("quiz_attempts").update(
            {"abandoned_at": datetime.now(timezone.utc).isoformat()},
            filters=filters,
            # The sweep is a side effect of a READ; without this PostgREST's
            # global Prefer: return=representation drags every swept row
            # back in full — including the encrypted questions_json /
            # answers_json blobs — on each history page load.
            prefer_return_minimal=True,
        )
    except Exception:
        logger.exception("quiz: abandon sweep failed user=%s", user_id)


def _insert_attempt(attempt_row: dict) -> None:
    """Write the attempt, surviving a schema that predates `exam_days_away`.

    The omit-when-None rule alone does NOT make a pre-migration environment
    safe, and the failure is nastier than it looks: it strikes exactly the
    students the feature is FOR (the ones with a dated upcoming exam), so it
    presents as a random partial outage rather than an obvious missing
    migration. And it strikes late — the agent has already run and been
    billed — so an unhandled 400 here loses the generated quiz, writes no
    attempt row, emits no `quiz.generation_failed`, and never refunds the
    rate-limit slot.
    #
    Ordering is still the rule (migration before code, as with
    20260814051517). This is the seatbelt for the window where PostgREST has
    not yet reloaded its schema cache, not a licence to deploy first.
    """
    try:
        table("quiz_attempts").insert(attempt_row)
        return
    except Exception:
        if "exam_days_away" not in attempt_row:
            raise
    retry = {k: v for k, v in attempt_row.items() if k != "exam_days_away"}
    logger.warning(
        "quiz: attempt insert failed with exam_days_away present; retrying "
        "without it (is 20260822090747 applied?) quiz_id=%s",
        attempt_row.get("id"),
    )
    table("quiz_attempts").insert(retry)


async def answer_question(attempt_id: str, body: AnswerQuestionBody, request: Request):
    """#541 C1: grade one question server-side and record the response.

    Idempotent on (attempt_id, question_index): re-answering returns the
    FIRST recorded response (`recorded: false` marks the replay) rather
    than overwriting — no revision, decided for the #537 revamp flow.
    """
    attempt = await _aload_owned_attempt(attempt_id, request)
    _refuse_if_completed(attempt)
    _refuse_if_abandoned(attempt)

    questions = decrypt_json_column(attempt["questions_json"]) or []
    if body.question_index >= len(questions):
        raise QuizAPIError(
            status_code=400,
            code=QuizErrorCode.QUIZ_QUESTION_INVALID,
            message="That question isn't part of this quiz.",
        )
    question = questions[body.question_index]
    options = question.get("options", [])
    written = question.get("type") in WRITTEN_TYPES
    if (written and body.answer_text is None) or (not written and body.selected_index is None):
        raise QuizAPIError(status_code=400, code=QuizErrorCode.QUIZ_QUESTION_INVALID,
                           message="Use the answer format shown for this question.")
    if not written and body.selected_index >= len(options):
        raise QuizAPIError(
            status_code=400,
            code=QuizErrorCode.QUIZ_QUESTION_INVALID,
            message="That answer choice isn't part of this question.",
        )
    # Wire ids are 1-based, question_index is 0-based. When the client sends
    # both, they must agree — otherwise passing the displayed id as the index
    # silently grades the NEXT question and idempotency locks that in.
    if body.question_id is not None and body.question_id != question.get("id"):
        raise QuizAPIError(
            status_code=400,
            code=QuizErrorCode.QUIZ_QUESTION_INVALID,
            message="That answer doesn't match the question it was sent for.",
        )

    # The correct option is a property of the question, not of the answer —
    # resolve it once. -1 means a malformed item with no correct option,
    # which must never grade correct (same rule as submit's #129 fix).
    correct_index = next(
        (i for i, o in enumerate(options) if o.get("correct")), -1
    )

    def _is_correct(selected_index: int | None, answer_text: str | None = None) -> bool:
        if written:
            return grade_written(question, answer_text or "")
        return correct_index >= 0 and correct_index == selected_index

    recorded = True
    response_row = None
    this_answer = {
        "attempt_id": f"eq.{attempt_id}",
        "question_index": f"eq.{body.question_index}",
    }
    existing = await table("quiz_responses").aselect("*", filters=this_answer)
    if existing:
        recorded = False
        response_row = existing[0]
    else:
        row = {
            "attempt_id": attempt_id,
            "question_index": body.question_index,
            "selected_index": body.selected_index,
            "is_correct": _is_correct(body.selected_index, body.answer_text),
            "time_ms": body.time_ms,
            # Learning-loop spec §13 A132: the stated label's
            # STUDENT_CONFIDENCE_LEVELS value, or None for a skip; an idk
            # written answer states none (A127 (c)). Submit carries it onto
            # the question's evidence.
            "confidence": stated_confidence(
                body.confidence,
                idk=written and quiz_evidence.is_idk_answer(body.answer_text),
            ),
        }
        if written:
            row["answer_text"] = encrypt_json({"text": body.answer_text})
        # ACCEPTED RISK (#597, #537 G4): this is the one quiz write path still
        # guarded by a PRE-READ alone. Submit and abandon both arbitrate with a
        # conditional claim on `quiz_attempts`; an INSERT into `quiz_responses`
        # conditioned on another table's state has no atomic PostgREST form, so
        # a Discard landing between the refusals above and this line records a
        # graded response against a closed attempt.
        #
        # Inert rather than harmful: an abandoned attempt can never be
        # submitted (submit's claim filters on `abandoned_at IS NULL`), so the
        # orphan pays out no mastery, no XP and no achievement. It costs a
        # stray row on a resume payload nobody can resume. Closing it properly
        # needs a trigger or an RPC — i.e. a migration — which is what #597 is
        # for.
        try:
            await table("quiz_responses").ainsert(row)
            response_row = row
        except Exception:
            # Lost a race with a concurrent answer for the same index — the
            # UNIQUE arbitrates; return whatever won.
            recorded = False
            raced = await table("quiz_responses").aselect("*", filters=this_answer)
            if not raced:
                raise
            response_row = raced[0]

    next_index = body.question_index + 1
    next_question = (
        _strip_answer_key([questions[next_index]])[0]
        if next_index < len(questions)
        else None
    )
    return {
        # Echo both addressing schemes so a client that mixed them up sees
        # it immediately rather than discovering it at submit time.
        "question_index": body.question_index,
        "question_id": question.get("id"),
        "is_correct": _is_correct(response_row["selected_index"],
                                  _written_response_text(response_row)),
        "correct_answer": question.get("correct_answer") if written else None,
        **({"answer_text": _written_response_text(response_row)} if written else {}),
        "correct_index": correct_index,
        "explanation": question.get("explanation", ""),
        "next_question": next_question,
        "recorded": recorded,
    }


async def abandon_attempt(attempt_id: str, request: Request):
    """#537 G4: close an unfinished attempt ON PURPOSE.

    Before this route, quiz home's "Discard" was a localStorage flag
    (`lib/quiz/session.ts::dismissAttempt`): the row stayed in_progress until
    D2's 24h sweep found it, so the resume strip came back on the student's
    phone, in a second tab, and in this browser the moment the key was
    cleared. Nothing new is stored — the client writes the same `abandoned_at`
    stamp `_sweep_abandoned` writes; it is just allowed to say "now".

    Idempotent by design: a second abandon is a 200 no-op carrying the stamp
    already on the row. The client fires this and forgets it, so a retry after
    a dropped response must not surface as an error. A COMPLETED attempt 409s
    instead — the score, mastery and XP are already paid out, and there is
    nothing here that could take them back.
    """
    attempt = await _aload_owned_attempt(
        attempt_id,
        request,
        # Not "*": the decision needs the owner and three timestamps, and
        # there is no reason to drag the encrypted questions_json blob across
        # the wire to write one column.
        columns="id,user_id,created_at,completed_at,abandoned_at",
    )
    _refuse_if_completed(attempt)

    abandoned_at = attempt.get("abandoned_at")
    if not abandoned_at:
        now = datetime.now(timezone.utc).isoformat()
        # The same conditional claim submit uses: the FILTERS arbitrate, so a
        # concurrent submit and abandon cannot both win the row. The read
        # above is only the fast path.
        #
        # NOT `prefer_return_minimal`: the returned rows ARE the arbitration
        # (`[]` means someone else won), and minimal mode returns `[]`
        # unconditionally (db/connection.py) — every discard would read as
        # lost.
        #
        # What the stamp means: `abandoned_at` records when the row was
        # CLOSED, not when it went quiet. Discarding an attempt that was
        # already dead by the TTL therefore writes the moment of the click.
        # Nothing consumes the column as an elapsed time today — the derived
        # status only asks whether it is set — and a consumer that wants "when
        # did this go quiet" wants `created_at` plus the last response, which
        # is what `_attempt_status` already computes.
        claimed = await table("quiz_attempts").aupdate(
            {"abandoned_at": now},
            filters={
                "id": f"eq.{attempt_id}",
                "completed_at": "is.null",
                "abandoned_at": "is.null",
            },
        )
        if claimed:
            # `now` is the value this request WROTE, so preferring the echoed
            # column and falling back to it is the same timestamp either way.
            abandoned_at = claimed[0].get("abandoned_at") or now
        else:
            # Losing the claim is not an error on its own — it means the row
            # moved between the read and the write. Re-read to find out which
            # way: a submit that got there first must 409 rather than be
            # reported back as a successful discard.
            current_rows = await table("quiz_attempts").aselect(
                "completed_at,abandoned_at",
                filters={"id": f"eq.{attempt_id}"},
            )
            if not current_rows:
                # Deleted under us. There is no stamp to report and no row to
                # report it for — the same 404 the top of the route gives.
                raise _attempt_not_found()
            current = current_rows[0]
            _refuse_if_completed(current)
            # A concurrent abandon (or the sweep) won; its stamp is the
            # answer. No `or now` fallback: this request wrote NOTHING, so
            # substituting its own clock would invent a stamp for a row whose
            # real state we just failed to explain. If the row somehow reads
            # open here, that is what the response says (`abandoned_at: null`,
            # status `in_progress`) — the honest answer to "we did not close
            # it", rather than a fabricated success.
            abandoned_at = current.get("abandoned_at")

    return {
        "quiz_id": attempt_id,
        # DERIVED like every other status the quiz routes report, never the
        # literal "abandoned" — this endpoint must not be the one place that
        # can disagree with the read paths.
        "status": _attempt_status({**attempt, "abandoned_at": abandoned_at}),
        "abandoned_at": abandoned_at,
    }
