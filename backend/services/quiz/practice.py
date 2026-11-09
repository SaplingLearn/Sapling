"""
backend/services/quiz/practice.py — moved from routes/quiz.py (#118).

G5 (#537): re-serve the questions a student missed on a finished attempt.

Function bodies are verbatim from the route; names (leading
underscores included) are unchanged, and routes/quiz.py re-exports them.
"""
import logging
from typing import NamedTuple

from starlette.concurrency import run_in_threadpool

from db.connection import table
from models import GenerateQuizBody
from services.quiz.errors import QuizAPIError, QuizErrorCode
from services.encryption import decrypt_json_column
from services.quiz.reserve import (
    MissedQuestions,
    missed_question_hashes,
    recover_questions,
)
from services.tool_signals import Expect, report_empty_result_async
from services.quiz.wire import _is_wire_question, _validate_wire_question

# Log records keep the name they had in routes/quiz.py before the #118 split:
# the move must not change what an operator (or a caplog test) filters on.
logger = logging.getLogger("routes.quiz")


class ReservedMisses(NamedTuple):
    """What a source attempt can hand back verbatim (G5, #537)."""

    #: The attempt the client asked to practise from.
    attempt_id: str
    #: Its missed questions, ready to serve — deep copies that still carry
    #: their E5 `question_hash` and the provenance of the run that wrote them.
    questions: list[dict]


def _missed_something(attempt: dict, found: MissedQuestions) -> bool:
    """Did this attempt miss anything at all? (G5's F5 guard.)

    The question the silent-empty signal actually needs, and the one the
    `HAS_ATTEMPTS` probe cannot answer: it asks "has this student completed an
    attempt", which is true by construction for a source attempt, so every
    zero-recovery would report a discrepancy — including the commonest and
    most correct zero of all, a student who got everything right.

    Three cases, in the order they resolve:

    * wrong answers were recorded AND at least one mapped to a stored item →
      yes. Recovering none of them is then a real discrepancy: the item was
      named and still could not be served, which today means a stored
      question that no longer passes the wire-format check;
    * answers were recorded and none of them produced a missed item → NO,
      silence. Read that as "everything was right", which is what it means
      in every case but the two named below;
    * nothing was recorded at all → fall back to the attempt's own score,
      the only remaining evidence. `score < total` means the student missed
      something we cannot name, which is exactly the pre-#537 degradation
      (an attempt graded only through /submit) worth counting.

    KNOWN GAP (deliberate, N1 in the PR). Two shapes are silent that should
    not be, and both land in the second case above. `missed_question_hashes`
    skips a wrong row whose `question_index` is out of range, and one whose
    stored question yields no `wire_question_hash` at all — so the row exists
    and is wrong, but produces no hash. That leaves `hashes` empty with
    `graded` True, which resolves as "everything was right", and `graded`
    short-circuits before the score fallback could catch it. A wrong-row
    COUNT on `MissedQuestions` instead of a bool would close it: "N wrong
    rows, none of them mappable" is a discrepancy, and it is exactly the one
    this function cannot currently see.
    """
    if found.hashes:
        return True
    if found.graded:
        return False
    score, total = attempt.get("score"), attempt.get("total")
    if not isinstance(score, (int, float)) or not isinstance(total, (int, float)):
        # An unscored or unreadable attempt tells us nothing. "Can't tell" is
        # silence, the same rule tool_signals' own probe follows.
        return False
    return score < total


async def _reserved_misses(body: GenerateQuizBody) -> ReservedMisses | None:
    """Recover the questions this student missed on `body.source_attempt_id`.

    None when the request named no source attempt — the ordinary generate.

    Raises for a source attempt that is missing, someone else's, or not
    finished. Everything below that degrades to an EMPTY recovery rather
    than an error: a re-serve that can't find its items is a quiz to
    generate, not a request to fail.
    """
    if not body.source_attempt_id:
        return None
    rows = await table("quiz_attempts").aselect(
        # score/total are plaintext scalars (#521) and ride along for free:
        # they are the only evidence that a pre-#537 attempt with no recorded
        # responses missed anything at all (see _missed_something).
        # concept_node_id rides along for the same-concept check below.
        "id,user_id,concept_node_id,completed_at,questions_json,score,total",
        filters={"id": f"eq.{body.source_attempt_id}"},
    )
    if not rows:
        raise QuizAPIError(
            status_code=404,
            code=QuizErrorCode.QUIZ_ATTEMPT_NOT_FOUND,
            message="We couldn't find the quiz you wanted to practise from.",
        )
    attempt = rows[0]
    # `require_self(body.user_id, request)` at the top of generate_quiz has
    # already proved body.user_id IS the signed-in user, so this comparison is
    # the same ownership check the sibling attempt routes make with
    # `require_self(attempt["user_id"], request)` — written out so it can carry
    # a precise envelope code instead of the guard's bare "Forbidden".
    if attempt.get("user_id") != body.user_id:
        raise QuizAPIError(
            status_code=403,
            code=QuizErrorCode.QUIZ_NOT_AUTHORIZED,
            message="That quiz isn't yours.",
        )
    if not attempt.get("completed_at"):
        # 400 + QUIZ_VALIDATION_ERROR is the closest state the envelope
        # supports. Nothing in the enum means "that attempt is still in
        # progress", and both near neighbours would mislead a client that maps
        # codes to copy: ALREADY_COMPLETED is the inverse state, NOT_RESUMABLE
        # is about resuming — which this is not. "Practise the ones you
        # missed" is only reachable from a results screen, so an unfinished
        # source is a malformed request, not a state to work around.
        raise QuizAPIError(
            status_code=400,
            code=QuizErrorCode.QUIZ_VALIDATION_ERROR,
            message=(
                "That quiz isn't finished yet, so there's nothing to "
                "practise from."
            ),
        )

    if attempt.get("concept_node_id") != body.concept_node_id:
        # The re-served items are copied into an attempt row stamped with THIS
        # request's concept, and /submit applies mastery to the row's concept
        # (`attempt["concept_node_id"]`) — so a source from another node would
        # pay Recursion answers into Binary Trees, write node_mastery_events
        # on the wrong node, and feed E6's per-concept guard foreign items.
        # Every sibling route re-derives concept from its own attempt; this is
        # the one place two attempts' concepts meet, so it is checked here.
        # Not reachable from the shipped client (PRACTISE_MISSED names the
        # attempt just finished, which is by construction the same concept) —
        # which is exactly why it needs a guard rather than an assumption.
        raise QuizAPIError(
            status_code=400,
            code=QuizErrorCode.QUIZ_VALIDATION_ERROR,
            message=(
                "That quiz was on a different concept, so its questions "
                "can't be practised here."
            ),
        )

    try:
        stored = decrypt_json_column(attempt.get("questions_json")) or []
    except Exception:
        logger.warning(
            "quiz: source attempt %s did not decrypt; generating instead of "
            "re-serving", body.source_attempt_id, exc_info=True,
        )
        stored = []
    # Deliberately NOT compacted to dicts. `quiz_responses.question_index` was
    # written against this array as stored, so dropping an element would shift
    # every index past it — silently re-serving a question the student got
    # RIGHT while the missed one goes missing. Both readers below tolerate a
    # non-dict element in place (`wire_question_hash` returns None for one),
    # so position is preserved and the odd element is simply unrecoverable.

    # An explicit list overrides the derivation; an empty one does not, so a
    # client that sends `[]` still gets its misses looked up.
    if body.missed_question_hashes:
        hashes = list(body.missed_question_hashes)
        # The caller asserted these items were missed, so recovering none of
        # them is a discrepancy whoever sent the list wants to know about.
        missed_something = True
    else:
        found = await run_in_threadpool(
            missed_question_hashes, body.source_attempt_id, stored)
        hashes = found.hashes
        missed_something = _missed_something(attempt, found)
    # Only questions in the CURRENT wire shape can be re-served: the client
    # projection, /answer and /submit all read that shape, and an unrecognised
    # stored row has no safe keyless projection at all (the same rule the
    # resume path applies in get_attempt).
    recovered = [
        q for q in recover_questions(stored, hashes)
        if _is_wire_question(q) and _validate_wire_question(q)
    ][:body.num_questions]
    for question in recovered:
        # Make the stored row self-describing: this item was re-served, not
        # written by a model for this attempt. The ORIGINAL provenance stays
        # — it is still the truthful account of where the item came from —
        # and this records where it came back from. Internal either way:
        # `_INTERNAL_QUESTION_KEYS` strips provenance from every client
        # payload, and `question_hash` is computed over stem + options, so
        # nothing here touches the item's identity.
        provenance = question.get("provenance")
        question["provenance"] = {
            **(provenance if isinstance(provenance, dict) else {}),
            "reserved_from": body.source_attempt_id,
        }

    if not recovered and missed_something:
        # F5: nothing recovered from an attempt that DID miss something is the
        # silent-empty shape this seam exists for — the feature has quietly
        # degraded to plain generation and nothing else would say so. The
        # commonest cause is a legitimate one (an attempt graded only through
        # /submit records no `quiz_responses` rows), which is exactly why it
        # needs counting rather than guessing.
        #
        # `missed_something` is the whole guard: the probe below can only ask
        # "did this student complete this attempt", which is true by
        # construction here, so without it a perfect score would report a
        # discrepancy on every practice request — alarm fatigue in the one
        # place F5 exists to avoid it.
        await report_empty_result_async(
            "quiz_reserve.missed_questions",
            user_id=body.user_id,
            count=0,
            expect=Expect.HAS_ATTEMPTS,
            # A fact, not a guess — the same move #592 made with `has_graph`.
            # We read this very row above and proved it owned and completed,
            # which is the entire question HAS_ATTEMPTS' probe would ask. Left
            # unset it is a guaranteed-True Supabase round trip on the request
            # path, once per degraded practice.
            plausible=True,
            feature="quiz",
            scope={"id": f"eq.{body.source_attempt_id}"},
            payload={"source_attempt_id": body.source_attempt_id},
        )
    return ReservedMisses(attempt_id=body.source_attempt_id, questions=recovered)


def _renumber(questions: list[dict]) -> list[dict]:
    """Give every question its 1-based position in THIS attempt.

    `id` addresses a question inside one attempt and nothing wider: /answer
    validates the client's `question_id` against
    `questions[question_index]["id"]`, and /submit keys its answer map on it.
    So a re-served question keeps its identity (`question_hash`, which is the
    item) and takes a new id (which is only where it sits) — carrying the
    source attempt's ids over would 400 the first answer.
    """
    for position, question in enumerate(questions, start=1):
        question["id"] = position
    return questions
