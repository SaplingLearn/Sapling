"""Sort a student's concepts into a flashcard set from a sentence.

The Flashcards home lets a student describe a set in their own words ("the
pointer stuff and recursion for the midterm") instead of ticking tiles. This
picks which of their tracked concepts belong.

The sorting is a typed decision (ADR 0027): one yes/no per concept, asked of
Jev through :mod:`services.decisions`, which degrades to the ``decision``
agent and from there to "no" for every concept, and never raises. A concept
the description NAMES outright is included whatever the model says (or fails
to say), so the feature still does the obvious thing with no model at all.

The answer is a SUGGESTION: the client ticks these concepts and the student
adjusts before saving. Nothing is stored here.
"""
from __future__ import annotations

import asyncio
import logging
import re

from db.connection import table
from services import decisions
from services.flashcards.errors import FlashcardSetInvalid, FlashcardSetRateLimited
from services.request_context import current_request_id
from services.request_limits import acheck_rate_limit
from services.flashcards.sets import NAME_MAX

logger = logging.getLogger("sapling.flashcards.suggest")

FEATURE = "flashcard_set_suggest"
DESCRIPTION_MIN = 3
DESCRIPTION_MAX = 300
#: Concepts considered per request (newest-studied first past this).
MAX_CANDIDATES = 120
#: Yes/no questions per decision call; chunks run concurrently.
CHUNK = 30
#: Each request is a model call (or several): a student gets this many a minute.
RATE_LIMIT, RATE_WINDOW_S = 10, 60


def _norm(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text.lower()).split())


def named_in(description: str, concept_name: str) -> bool:
    """The description spells this concept out (whole words, any case)."""
    name = _norm(concept_name)
    return bool(name) and re.search(rf"(?:^| ){re.escape(name)}(?: |$)", _norm(description)) is not None


def suggested_name(description: str) -> str:
    """A set name from the description: its text, capitalised, cut at a word."""
    text = " ".join(description.split()).rstrip(".!?")
    if len(text) > NAME_MAX:
        text = text[:NAME_MAX].rsplit(" ", 1)[0].rstrip(",;:") or text[:NAME_MAX]
    return text[:1].upper() + text[1:]


def _question(index: int, concept_name: str) -> decisions.YesNo:
    return decisions.YesNo(
        key=f"c{index}",
        instructions=(
            f'Should the concept "{concept_name}" be included in the flashcard set '
            "the student asked for in `student_request`?"
        ),
        default=False,
        when_yes="The concept is part of, or clearly needed for, what the student described.",
        when_no="The concept is unrelated to what the student described.",
    )


async def _decide_chunk(
    description: str, names: list[str], offset: int, user_id: str, request_id: str | None,
) -> decisions.DecisionResult:
    questions = [_question(offset + i, name) for i, name in enumerate(names)]
    state = {"student_request": description, "concepts": names}
    try:
        return await asyncio.wait_for(
            decisions.decide(
                state, questions, feature=FEATURE, user_id=user_id,
                request_id=request_id, backend=decisions.JEV,
            ),
            timeout=decisions.worst_case_s() + 1.0,
        )
    except Exception as exc:  # decide() never raises; this is the backstop.
        logger.warning("flashcard set suggest: decision failed (%s); using defaults", type(exc).__name__)
        return decisions.defaults_result(questions, reason="suggest_error", requested=decisions.JEV)


async def suggest_flashcard_set(
    user_id: str, description: str, course_id: str | None = None,
) -> dict:
    """Which of the student's concepts a described set should hold.

    ``course_id`` narrows the candidates to one course; without it every
    course's concepts are considered. Returns ``{"name", "concepts": [{"name",
    "course_id", "source", "confidence"}], "considered", "backend"}`` where
    ``source`` is ``named`` (the description says it) or ``model``.
    """
    text = " ".join((description or "").split())
    if not DESCRIPTION_MIN <= len(text) <= DESCRIPTION_MAX:
        raise FlashcardSetInvalid(
            f"description must be {DESCRIPTION_MIN} to {DESCRIPTION_MAX} characters."
        )
    if await acheck_rate_limit(
        f"flashcard-set-suggest:{user_id}", limit=RATE_LIMIT, window_sec=RATE_WINDOW_S,
    ) is not None:
        raise FlashcardSetRateLimited("Please wait a moment before describing another set.")
    request_id = current_request_id()
    filters = {"user_id": f"eq.{user_id}", "mastery_tier": "neq.subject_root"}
    if course_id:
        filters["course_id"] = f"eq.{course_id}"
    rows = await table("graph_nodes").aselect(
        "concept_name,course_id", filters=filters,
        order="last_studied_at.desc.nullslast,concept_name", limit=MAX_CANDIDATES,
    ) or []
    candidates = [r for r in rows if (r.get("concept_name") or "").strip()]
    names = [r["concept_name"] for r in candidates]

    chunks = [names[i:i + CHUNK] for i in range(0, len(names), CHUNK)]
    results = await asyncio.gather(*(
        _decide_chunk(text, chunk, i * CHUNK, user_id, request_id)
        for i, chunk in enumerate(chunks)
    ))
    answers: dict[str, decisions.Answer] = {}
    for result in results:
        answers.update(result.answers)

    picked = []
    for index, row in enumerate(candidates):
        answer = answers.get(f"c{index}")
        named = named_in(text, row["concept_name"])
        if not named and not (answer and answer.value is True):
            continue
        picked.append({
            "name": row["concept_name"],
            "course_id": row.get("course_id"),
            "source": "named" if named else "model",
            "confidence": 1.0 if named else round(float(answer.confidence), 3),
        })
    backends = {r.backend for r in results}
    return {
        "name": suggested_name(text),
        "concepts": picked,
        "considered": len(candidates),
        # Who actually answered: jev | flash_lite | function | none (mixed when
        # chunks fell back differently).
        "backend": backends.pop() if len(backends) == 1 else ("mixed" if backends else "none"),
    }
