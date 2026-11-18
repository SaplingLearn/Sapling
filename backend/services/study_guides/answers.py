"""Grade the answer to a check-yourself question and, the first time the
question is answered, move the student's mastery of its concept.

Every answer is graded and explained. Only the first one is stored and
counted: ``store.arecord_answer`` decides which that is, so a double click
cannot move mastery twice.

The count is graded evidence, as a quiz question's is (learning-loop PKG-14b:
evidence is the only mastery write): one ``mc`` Evidence on the concept's
node through ``graph_service.apply_graph_update``, built the way
``services/quiz/submission.py::_quiz_evidence`` builds one, and the graph runs
BKT on it. Never a flat delta.

It obeys the quiz's evidence rules too (spec §13 A8), applied by the quiz's
own code (``services/question_evidence.py``): a question counts at most once
per student per rolling 24 h, quiz and guide alike (A94/A100's claim), and
carries the help ledger's floor (A99). A guide's Regenerate clears its stored
answers, so the claim is what keeps a regenerated question from counting
again at full weight.
"""
from __future__ import annotations

import logging
from typing import Callable

from starlette.concurrency import run_in_threadpool

from learning.bkt import tier_for, tier_for_stored
from models.study_guide import AnswerResult, CheckAnswer, CheckBlock, MasteryChange
from services import academics, events_service, graph_service
from services.question_evidence import guard_question_evidence
from services.quiz import question_hash
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


def _evidence(node_id: str, block: CheckBlock, correct: bool) -> dict:
    """One graded check question as evidence, exactly as the quiz grades a
    question (``_quiz_evidence``): the "mc" channel, no check item, no
    session, and the item's identity (``question_hash``) from its stem and
    options, so it shares the quiz's namespace."""
    return {
        "node_id": node_id,
        "channel": "mc",
        "correct": correct,
        "question_hash": question_hash(block.question, [option.text for option in block.options]),
        "check_item_id": None,
        "session_id": None,
    }


def _claimant(guide: GuideRow, block: CheckBlock) -> str:
    """Who claims a question's evidence window (`quiz_evidence_claims.attempt_id`,
    as a quiz names its attempt): this guide's block."""
    return f"study_guide:{guide.id}:{block.id}"


def _write_evidence(user_id: str, evidence: dict, course_id: str, defer: Defer | None) -> list:
    """The one graph write: the graded evidence, through the single writer
    (sanctioned in tests/test_learning_evidence_apply.py)."""
    return graph_service.apply_graph_update(
        user_id, {"evidence": [evidence]}, course_id=course_id, defer=defer,
    )


async def _amove_mastery(
    guide: GuideRow, block: CheckBlock, correct: bool, defer: Defer | None,
) -> MasteryChange | None:
    """Move mastery of the block's concept and say what changed. None when
    the block names no concept or the student's tree does not have it."""
    course_id = await run_in_threadpool(academics.offering_course_id, guide.offering_id)
    if not block.concept or not course_id:
        return None
    node = await signals.aconcept_node(guide.user_id, course_id, block.concept)
    if node is None:
        return None
    # A8: the quiz's rules first — the 24 h per-question claim, then the help floor
    kept = await run_in_threadpool(
        guard_question_evidence, guide.user_id, _claimant(guide, block),
        [_evidence(node["id"], block, correct)],
    )
    if not kept:  # counted within the window already (a quiz, another guide, a Regenerate)
        return None
    changes = await run_in_threadpool(_write_evidence, guide.user_id, kept[0], course_id, defer)
    if not changes:
        return None
    change = changes[0]
    # "Before" is the tier the student was shown (the node's stored mastery),
    # not the estimate's starting point: a node with no learner_state yet
    # starts the update at the prior, which can sit in another tier than the
    # map showed a moment ago.
    shown = node.get("mastery_score")
    return MasteryChange(
        concept=change["concept"],
        # "Before" may be the node's STORED score, so a drifted old row is
        # classified, never a 500 after the evidence commit. "After" is the
        # belief the write just computed: checked strictly, so a real
        # out-of-range computation still surfaces.
        before=tier_for_stored(change["before"] if shown is None else shown),
        after=tier_for(change["after"]),
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
