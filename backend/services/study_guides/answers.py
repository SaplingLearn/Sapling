"""Grade the answer to a check-yourself question and, the first time the
question is answered, move the student's mastery of its concept.

Every answer is graded and explained. Only the first one is stored and
counted: ``store.arecord_answer`` decides which that is, so a double click
cannot move mastery twice.
"""
from __future__ import annotations

import logging
from typing import Callable

from starlette.concurrency import run_in_threadpool

from config import get_mastery_tier
from models.study_guide import AnswerResult, CheckAnswer, CheckBlock, MasteryChange
from services import academics, events_service, graph_service
from services.quiz import mastery_after
from services.study_guides import signals, store
from services.study_guides.errors import GuideInvalid, GuideNotFound
from services.study_guides.store import GuideRow

logger = logging.getLogger(__name__)

QUESTION_NOT_FOUND_DETAIL = "That question is not in this guide."
OPTION_INVALID_DETAIL = "That is not one of the question's answers."

#: Where ``apply_graph_update`` runs the class-aggregate refresh a mastery
#: write triggers (the route passes ``background_tasks.add_task``).
Defer = Callable[[Callable[[], None]], object]


def _check_block(guide: GuideRow, block_id: str) -> CheckBlock:
    """The guide's check block with that id. One stored without an answer
    cannot be graded, so it is not found either."""
    for section in guide.content.sections:
        for item in section.items:
            if item.id == block_id and item.type == "check" and item.correct_id:
                return item
    raise GuideNotFound(QUESTION_NOT_FOUND_DETAIL)


async def _atree_concept(user_id: str, course_id: str, concept: str) -> tuple[str, float] | None:
    """The concept as the student's tree spells it, with its mastery score.
    None when the tree does not have it."""
    scores = await signals.amastery(user_id, course_id)
    wanted = signals.concept_key(concept)
    return next(
        ((name, score) for name, score in scores.items() if signals.concept_key(name) == wanted),
        None,
    )


def _graph_update(name: str, before: float, correct: bool) -> dict:
    """One graded question as a mastery update, by the quiz's own rule."""
    outcome = "correct" if correct else "incorrect"
    return {
        "updated_nodes": [{
            "concept_name": name,
            "mastery_delta": mastery_after(before, score=int(correct), total=1) - before,
            "reason": f"Study guide check: {outcome}",
            "event_type": f"guide_check_{outcome}",
        }]
    }


async def _amove_mastery(
    guide: GuideRow, block: CheckBlock, correct: bool, defer: Defer | None,
) -> MasteryChange | None:
    """Move mastery of the block's concept and say what changed. None when
    the block names no concept or the student's tree does not have it."""
    course_id = await run_in_threadpool(academics.offering_course_id, guide.offering_id)
    if not block.concept or not course_id:
        return None
    found = await _atree_concept(guide.user_id, course_id, block.concept)
    if found is None:
        return None
    name, before = found
    changes = await run_in_threadpool(
        graph_service.apply_graph_update,
        guide.user_id,
        _graph_update(name, before, correct),
        course_id=course_id,
        defer=defer,
    )
    if not changes:
        return None
    change = changes[0]
    return MasteryChange(
        concept=change["concept"],
        before=get_mastery_tier(change["before"]),
        after=get_mastery_tier(change["after"]),
    )


async def _acount(
    guide: GuideRow, block: CheckBlock, correct: bool, defer: Defer | None,
) -> MasteryChange | None:
    """The mastery move of a first answer. The answer is already stored, and
    a retry would not count, so a failure here is logged and the answer still
    stands: it must not turn a graded answer into an error."""
    try:
        return await _amove_mastery(guide, block, correct, defer)
    except Exception as exc:
        logger.warning(
            "study guide: mastery update failed after a check answer guide=%s block=%s (%s)",
            guide.id, block.id, type(exc).__name__,
        )
        return None


async def aanswer_check(
    user_id: str, guide_id: str, block_id: str, option_id: str, *, defer: Defer | None = None,
) -> AnswerResult:
    """Grade ``option_id`` on one check block of the user's guide.

    ``GuideNotFound`` when the guide is not the user's or the block is not a
    check block of it; ``GuideInvalid`` when the option is not one of the
    block's. ``counted`` is False for a repeat answer, which is graded and
    explained but neither stored nor counted toward mastery.
    """
    guide = await store.aload_guide(user_id, guide_id)
    block = _check_block(guide, block_id)
    if option_id not in {option.id for option in block.options}:
        raise GuideInvalid(OPTION_INVALID_DETAIL)
    correct = option_id == block.correct_id
    counted = await store.arecord_answer(
        guide, block_id, CheckAnswer(option_id=option_id, correct=correct),
    )
    change = await _acount(guide, block, correct, defer) if counted else None
    events_service.log_event(
        "study_guide.check_answered",
        category="usage",
        user_id=user_id,
        payload={
            "guide_id": guide_id, "block_id": block_id, "correct": correct, "counted": counted,
        },
    )
    return AnswerResult(
        correct=correct,
        correct_id=block.correct_id,
        explanation=(block.explain_correct if correct else block.explain_incorrect) or "",
        counted=counted,
        mastery=change,
    )
