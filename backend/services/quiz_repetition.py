"""Recently-asked questions for one (student, concept) — E6's read side.

Past `quiz_attempts.questions_json` was never re-read by anything. The
consequence is the plainest kind of bad: a student could be served the same
question on their second, third and fourth quiz of a concept, and no part of
the system was capable of noticing, because nothing had ever looked.

This is the look. It returns the identities and stems of the questions this
student has recently been served on this concept, so generation can be told
not to repeat them.

Two deliberate choices worth stating:

* **Not filtered to completed attempts.** `read_recent_quiz_attempts` filters
  on `completed_at IS NOT NULL` because it needs a score. This does not: a
  student who generated a quiz and abandoned it still SAW those questions,
  so re-serving them is still a repeat.
* **Fetched raw, not precomputed.** The audit's end-state is for these
  identities to live in the `quiz_context` digest, refreshed by the existing
  post-submit background task, so the generate path pays one decrypt instead
  of N. That refactor belongs with the digest schema work (#554); this reads
  the attempts directly and is bounded hard (a handful of rows, capped
  output) to keep the request-path cost small in the meantime.

Contract: best-effort. Every failure degrades to "no known repeats", which
is exactly the behaviour that existed before this module. Repetition
avoidance must never be able to break quiz generation.
"""

from __future__ import annotations

import logging
from typing import NamedTuple

from db.connection import table
from services.encryption import decrypt_json_column
from services.quiz_identity import normalize_text, wire_question_hash

logger = logging.getLogger(__name__)

# How many recently-asked questions generation is told about. This text goes
# INTO the prompt, so it is a budget line, not just a query cap: ~15 stems is
# a few hundred tokens, small beside the course-material block it competes
# with, and long enough to cover several quizzes on one concept.
RECENT_QUESTION_LIMIT = 15

# How many past attempts to scan to fill that list. At the 10-question cap
# (services/quiz_config.QUIZ_MAX_QUESTIONS) two attempts can already satisfy
# the limit; 6 covers short quizzes and heavy repetition without turning a
# generate into a large decrypt job.
_ATTEMPT_SCAN_LIMIT = 6


class RecentQuestion(NamedTuple):
    """One previously-served item."""

    #: Stable cross-attempt identity (services/quiz_identity.py).
    question_hash: str
    #: The readable stem, for the prompt. "Do not repeat <hash>" is
    #: unactionable for a model; it needs to see the question.
    stem: str


def recent_question_identities(
    user_id: str,
    concept_node_id: str,
    limit: int = RECENT_QUESTION_LIMIT,
) -> list[RecentQuestion]:
    """Return up to `limit` recently-served questions, newest first.

    Deduplicated by identity: an item asked three times appears once, or a
    heavily-repeated question would crowd out the rest of the list it is
    meant to be competing with.
    """
    if not user_id or not concept_node_id:
        return []
    try:
        rows = table("quiz_attempts").select(
            "id,questions_json,created_at",
            filters={
                "user_id": f"eq.{user_id}",
                "concept_node_id": f"eq.{concept_node_id}",
            },
            # `id` breaks ties so two attempts sharing a created_at have a
            # defined order — same idiom as the attempt-history paging.
            order="created_at.desc,id.desc",
            limit=_ATTEMPT_SCAN_LIMIT,
        ) or []
    except Exception:
        # No user id in the message (Engineering Style Guide: never log user
        # ids). The concept node is what identifies WHICH read failed; the
        # request-scoped log/trace context already ties the line back to the
        # caller, so the id added nothing but a privacy liability.
        logger.warning(
            "quiz repetition: attempt read failed concept=%s; "
            "generating without a do-not-repeat list",
            concept_node_id, exc_info=True,
        )
        return []

    out: list[RecentQuestion] = []
    seen: set[str] = set()
    for row in rows:
        if len(out) >= limit:
            break
        try:
            questions = decrypt_json_column(row.get("questions_json"))
        except Exception:
            # One unreadable blob (a key rotation, an out-of-band edit) must
            # not cost us the other attempts' history.
            logger.warning(
                "quiz repetition: attempt %s did not decrypt; skipping",
                row.get("id"),
            )
            continue
        if not isinstance(questions, list):
            continue
        for q in questions:
            if len(out) >= limit:
                break
            qhash = wire_question_hash(q)
            if not qhash or qhash in seen:
                continue
            stem = str((q or {}).get("question") or "").strip()
            if not stem or not normalize_text(stem):
                continue
            seen.add(qhash)
            out.append(RecentQuestion(question_hash=qhash, stem=stem))
    return out
