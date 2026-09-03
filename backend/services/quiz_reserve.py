"""Re-serving the questions a student actually missed (G5, #537).

What this is for
----------------
"Practise the ones you missed" used to be a lie of omission. The route had
no way to name a past question, so the button generated a fresh quiz on the
same concept and the client labelled it honestly ("Focused on what you
missed" — contract R-5). The one item the student demonstrably could not
answer was the one item they never saw again.

E5 (`services/quiz_identity.py`) closed the gap it needed: every stored
question now carries a `question_hash`, a stable identity that survives the
attempt it was written for. So the missed items can be *found* in the source
attempt and handed straight back — the same stem, the same options, the same
explanation, no model call, no paraphrase.

The two halves
--------------
* `missed_question_hashes` — which items this attempt got wrong, read off
  the normalised `quiz_responses` rows the /answer route writes.
* `recover_questions` — those items, copied verbatim out of the source
  attempt's decrypted `questions_json`.

Both are best-effort in the same sense the repetition guard is: every
failure degrades to "nothing to re-serve", which is precisely the behaviour
that existed before this module — the caller generates instead. Re-serving
must never be able to break quiz generation.

What this module deliberately does NOT decide
---------------------------------------------
Whether a recovered question is still *servable* (two-plus options, exactly
one correct) is the route's wire-format contract, enforced there by
`_validate_wire_question`. Duplicating that judgement here would give the
codebase two answers to one question.
"""

from __future__ import annotations

import copy
import logging
from typing import NamedTuple

from db.connection import table
from services.quiz_identity import wire_question_hash

logger = logging.getLogger(__name__)


class MissedQuestions(NamedTuple):
    """What one attempt's recorded answers say about which items were missed.

    Two facts, not one, because an empty `hashes` has two opposite causes and
    the caller has to tell them apart:

    * the student answered everything correctly — nothing to practise, nothing
      wrong;
    * nothing was ever recorded (an attempt graded only through /submit, which
      the pre-#537 client did for every quiz) — so we cannot say what was
      missed even though something was.

    `graded` separates them. Without it the route's silent-empty signal fires
    on a perfect score, which is the loudest possible way to say nothing.
    """

    #: Identities of the items graded wrong, in the order they were asked.
    hashes: list[str]
    #: Whether the attempt had ANY graded response row at all.
    graded: bool


def missed_question_hashes(attempt_id: str, questions: list[dict]) -> MissedQuestions:
    """Which questions `attempt_id` got WRONG, in asked order.

    Reads `quiz_responses` — the per-answer rows POST /attempts/{id}/answer
    writes — rather than the attempt's `answers_json`, because `is_correct`
    is already graded there and stored in plaintext.

    The read is deliberately UNFILTERED on `is_correct`: the wrong rows are
    what we want, but whether there were any rows at all is the other half of
    the answer (see `MissedQuestions`), and one read of at most a quiz's worth
    of rows is cheaper than two.

    An attempt graded ONLY through /submit has no response rows, so it yields
    nothing here and `graded` is False. That is the honest answer: without
    them we cannot say which items were missed, and the caller falls back to
    generating. The route reports that case through
    `tool_signals.report_empty_result` so a re-serve that silently degrades to
    generation is countable rather than invisible.
    """
    if not attempt_id or not questions:
        return MissedQuestions(hashes=[], graded=False)
    try:
        rows = table("quiz_responses").select(
            "question_index,is_correct",
            filters={"attempt_id": f"eq.{attempt_id}"},
        ) or []
    except Exception:
        # No user id in the message (Engineering Style Guide) — the attempt
        # is what identifies WHICH read failed. `graded=False` is "we don't
        # know", which is also what it has to mean: a failed read must not
        # manufacture a discrepancy any more than it should hide one.
        logger.warning(
            "quiz reserve: response read failed for attempt %s; nothing to "
            "re-serve", attempt_id, exc_info=True,
        )
        return MissedQuestions(hashes=[], graded=False)

    indexes = []
    for row in rows:
        index = row.get("question_index")
        if not isinstance(index, int) or not 0 <= index < len(questions):
            # A row pointing past the stored questions is a shape we can't
            # resolve (a hand-edited row, a truncated re-write). Skipping it
            # costs one item; index-erroring would cost the whole practice.
            continue
        if row.get("is_correct"):
            continue
        indexes.append(index)

    out: list[str] = []
    seen: set[str] = set()
    # Sorted HERE, not with an `order=` on the query: the order a practice
    # quiz asks its questions in is a property of this function, and pushing
    # it into PostgREST would leave that property untestable without a live
    # database. It is the order the student sat them in — "practise the ones
    # you missed" reading back-to-front is a small, avoidable oddity.
    for index in sorted(indexes):
        qhash = wire_question_hash(questions[index])
        if not qhash or qhash in seen:
            continue
        seen.add(qhash)
        out.append(qhash)
    return MissedQuestions(hashes=out, graded=bool(rows))


def recover_questions(questions: list[dict], hashes: list[str]) -> list[dict]:
    """The stored questions matching `hashes`, verbatim, in that order.

    "Verbatim" is the whole point: the copy keeps its `question_hash` (so E5
    identity holds across attempts — item statistics can still see one item
    asked twice) and its `provenance` (the prompt version, model and chunks
    that wrote it are still the truthful account of where it came from).

    Copies, not aliases: the caller renumbers `id`, which is a position
    WITHIN an attempt, not part of the item.

    A hash the source attempt never held simply matches nothing. Unknown
    hashes are therefore "not recoverable" rather than an error — which is
    also what validates a client-supplied list against the source attempt,
    since only that attempt's own items can be found here.
    """
    if not questions or not hashes:
        return []
    by_hash: dict[str, dict] = {}
    for question in questions:
        qhash = wire_question_hash(question)
        # First occurrence wins — a duplicate item inside one attempt is
        # still one item, and it should be re-served once.
        if qhash and qhash not in by_hash:
            by_hash[qhash] = question

    out: list[dict] = []
    taken: set[str] = set()
    for qhash in hashes:
        if not isinstance(qhash, str):
            continue
        qhash = qhash.strip()
        found = by_hash.get(qhash)
        if found is None or qhash in taken:
            continue
        taken.add(qhash)
        out.append(copy.deepcopy(found))
    return out
