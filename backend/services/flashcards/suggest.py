"""Sort a student's concepts into a flashcard set from a sentence.

The Flashcards home lets a student describe a set in their own words ("the
pointer stuff and recursion for the midterm") instead of ticking tiles. This
picks which of their tracked concepts belong.

The sorting is a typed decision (ADR 0027): one yes/no per concept, asked
through :mod:`services.decisions`, which degrades to "no" for every concept
and never raises. The first-party ``decision`` agent answers by default; Jev
(TypeSafe, a third party) answers only for a student the ``decision_router``
flag has opted in, so that flag and its kill switch govern every place a
student's words can reach Jev. A concept
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
from services.flashcards.sets import CONCEPT_NAME_MAX, NAME_MAX
from services.prompt_safety import neutralize_delimiters
from services.request_context import current_request_id
from services.request_limits import acheck_rate_limit

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


def _label(concept_name: str) -> str:
    """A concept name as it is quoted inside a question's instructions.

    Concept names are student-derived (extracted from uploads, or typed), so
    they are untrusted at the prompt boundary (services/prompt_safety.py: short
    scalar fields are neutralised, not enveloped). Kept on one line, without
    the quote that would end the label, and no longer than a set's own concept
    names. The student's description never enters the instructions: it rides
    in the decision's ``state``, which the seam judges as data."""
    text = " ".join(neutralize_delimiters(concept_name).split()).replace('"', "'")
    return text[:CONCEPT_NAME_MAX]


def _question(index: int, concept_name: str) -> decisions.YesNo:
    return decisions.YesNo(
        key=f"c{index}",
        instructions=(
            f'Should the concept "{_label(concept_name)}" be included in the flashcard set '
            "the student asked for in `student_request`? `concepts` lists every candidate "
            "with the student's mastery of it (unexplored, struggling, learning or mastered)."
        ),
        default=False,
        when_yes=(
            "The concept is part of, or clearly needed for, what the student described. A "
            "request about their own progress (what they are struggling with, what they have "
            "not started, just the basics) is answered from the concept's mastery."
        ),
        when_no="The concept is unrelated to what the student described.",
    )


def _state(description: str, candidates: list[dict]) -> dict:
    """What the decision judges: the student's words, and each candidate with
    its mastery tier, so "what I'm struggling with" has something to go on."""
    return {
        "student_request": description,
        "concepts": [
            {"name": r["concept_name"], "mastery": r.get("mastery_tier") or "unexplored"}
            for r in candidates
        ],
    }


async def _decision_backend(user_id: str) -> str:
    """Jev only when the ``decision_router`` flag puts this student on it;
    otherwise (flag off, or unreadable) the first-party ``decision`` agent."""
    try:
        primary, _shadow = await decisions.router_backends_off_loop(user_id)
    except Exception as exc:
        logger.warning("flashcard set suggest: decision_router unreadable (%s); not using Jev",
                       type(exc).__name__)
        return decisions.FLASH_LITE
    return decisions.JEV if primary == decisions.JEV else decisions.FLASH_LITE


async def _decide_chunk(
    description: str, candidates: list[dict], offset: int, user_id: str,
    request_id: str | None, backend: str,
) -> decisions.DecisionResult:
    questions = [_question(offset + i, r["concept_name"]) for i, r in enumerate(candidates)]
    state = _state(description, candidates)
    try:
        return await asyncio.wait_for(
            decisions.decide(
                state, questions, feature=FEATURE, user_id=user_id,
                request_id=request_id, backend=backend,
            ),
            timeout=decisions.worst_case_s() + 1.0,
        )
    except Exception as exc:  # decide() never raises; this is the backstop.
        logger.warning("flashcard set suggest: decision failed (%s); using defaults", type(exc).__name__)
        return decisions.defaults_result(questions, reason="suggest_error", requested=backend)


def _clean_description(description: str | None) -> str:
    text = " ".join((description or "").split())
    if not DESCRIPTION_MIN <= len(text) <= DESCRIPTION_MAX:
        raise FlashcardSetInvalid(
            f"description must be {DESCRIPTION_MIN} to {DESCRIPTION_MAX} characters."
        )
    return text


async def _candidates(user_id: str, course_id: str | None) -> list[dict]:
    """The student's own concepts (``{concept_name, course_id,
    mastery_tier}``), most recently studied first, at most ``MAX_CANDIDATES``."""
    filters = {"user_id": f"eq.{user_id}", "mastery_tier": "neq.subject_root"}
    if course_id:
        filters["course_id"] = f"eq.{course_id}"
    rows = await table("graph_nodes").aselect(
        "concept_name,course_id,mastery_tier", filters=filters,
        order="last_studied_at.desc.nullslast,concept_name", limit=MAX_CANDIDATES,
    ) or []
    return [r for r in rows if (r.get("concept_name") or "").strip()]


async def _claim_rate_slot(user_id: str) -> None:
    retry = await acheck_rate_limit(
        f"flashcard-set-suggest:{user_id}", limit=RATE_LIMIT, window_sec=RATE_WINDOW_S,
    )
    if retry is not None:
        raise FlashcardSetRateLimited(
            "Please wait a moment before describing another set.", retry_after=retry,
        )


async def _ask(text: str, candidates: list[dict], user_id: str) -> list[decisions.DecisionResult]:
    """One decision per ``CHUNK`` of candidates, run concurrently; question
    keys (``c<index>``) count across chunks."""
    request_id = current_request_id()
    backend = await _decision_backend(user_id)
    return await asyncio.gather(*(
        _decide_chunk(text, candidates[start:start + CHUNK], start, user_id, request_id, backend)
        for start in range(0, len(candidates), CHUNK)
    ))


def _picked(text: str, candidates: list[dict], answers: dict[str, decisions.Answer]) -> list[dict]:
    """The candidates the description names or the model said yes to."""
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
    return picked


def _backend(results: list[decisions.DecisionResult]) -> str:
    """Who actually answered: jev | flash_lite | function | none (mixed when
    chunks fell back differently)."""
    backends = {r.backend for r in results}
    if len(backends) == 1:
        return backends.pop()
    return "mixed" if backends else "none"


async def suggest_flashcard_set(
    user_id: str, description: str, course_id: str | None = None,
) -> dict:
    """Which of the student's concepts a described set should hold.

    ``course_id`` narrows the candidates to one course; without it every
    course's concepts are considered. Returns ``{"name", "concepts": [{"name",
    "course_id", "source", "confidence"}], "considered", "backend"}`` where
    ``source`` is ``named`` (the description says it) or ``model``.

    Raises ``FlashcardSetInvalid`` (the description's length) or
    ``FlashcardSetRateLimited``. The limiter guards the model: a student with
    no concepts yet is answered (with nothing) without spending a slot.
    """
    text = _clean_description(description)
    candidates = await _candidates(user_id, course_id)
    results: list[decisions.DecisionResult] = []
    if candidates:
        await _claim_rate_slot(user_id)
        results = await _ask(text, candidates, user_id)
    answers: dict[str, decisions.Answer] = {}
    for result in results:
        answers.update(result.answers)
    return {
        "name": suggested_name(text),
        "concepts": _picked(text, candidates, answers),
        "considered": len(candidates),
        "backend": _backend(results),
    }
