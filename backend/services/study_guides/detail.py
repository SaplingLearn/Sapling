"""A guide as the reader renders it: its card, its content, the reader's
state, and the student's mastery of every concept it mentions as it is now.

The answer to a check question is withheld until the student has answered it.
The stored content always has it.
"""
from __future__ import annotations

from typing import Mapping

from models.study_guide import CheckAnswer, GuideContent, GuideDetail, Item, Section, Tier
from services.study_guides import cards, scopes, signals, store
from services.study_guides.errors import StudyGuideError
from services.study_guides.scopes import Scope
from services.study_guides.store import GuideRow

_WITHHELD = {"correct_id": None, "explain_correct": None, "explain_incorrect": None}


# ── Check answers ────────────────────────────────────────────────────────────


def reader_item(item: Item, answers: Mapping[str, CheckAnswer]) -> Item:
    """The item as the reader may see it: a check block the student has not
    answered comes without its answer and explanations."""
    if item.type == "check" and item.id not in answers:
        return item.model_copy(update=_WITHHELD)
    return item


def reader_section(section: Section, answers: Mapping[str, CheckAnswer]) -> Section:
    return section.model_copy(
        update={"items": [reader_item(item, answers) for item in section.items]},
    )


def reader_content(content: GuideContent, answers: Mapping[str, CheckAnswer]) -> GuideContent:
    return content.model_copy(
        update={"sections": [reader_section(section, answers) for section in content.sections]},
    )


# ── Scope and mastery, as they are now ───────────────────────────────────────


async def _ascope(guide: GuideRow) -> Scope:
    """What the guide is for, read live so a renamed or rescheduled exam
    shows as it is now. When the exam or assignment has been deleted the guide
    still opens, under the label it was made with and with no date."""
    try:
        return await scopes.ascope_of(
            guide.user_id, guide.offering_id, guide.scope_kind, guide.exam_id,
        )
    except StudyGuideError:
        return Scope(
            kind=guide.scope_kind, id=guide.exam_id,
            title=guide.content.scope_label, due_date=None,
        )


def mentioned_concepts(content: GuideContent) -> list[str]:
    """Every concept name the guide shows mastery for: each section's
    concept, concept-map nodes and check questions. No repeats."""
    names: dict[str, None] = {}
    for section in content.sections:
        found = [section.concept]
        for item in section.items:
            if item.type == "concept_map":
                found += [node.concept for node in item.nodes]
            elif item.type == "check":
                found.append(item.concept)
        names.update(dict.fromkeys(name for name in found if name))
    return list(names)


async def _amastery(guide: GuideRow, course_id: str) -> dict[str, Tier]:
    """Live tier per mentioned concept, under the name the guide uses. A
    concept the student's tree does not have (any more) is left out."""
    mentioned = mentioned_concepts(guide.content)
    if not mentioned or not course_id:
        return {}
    live = signals.tiers(await signals.amastery(guide.user_id, course_id))
    by_key = {signals.concept_key(name): tier for name, tier in live.items()}
    return {
        name: by_key[signals.concept_key(name)]
        for name in mentioned if signals.concept_key(name) in by_key
    }


# ── Entry points ─────────────────────────────────────────────────────────────


async def abuild_detail(guide: GuideRow) -> GuideDetail:
    card = (await cards.acards(guide.user_id, [guide]))[0]
    scope = await _ascope(guide)
    fields = card.model_dump()
    # An empty live title (an untitled assignment) keeps the stored label.
    fields["scope_label"] = scope.title or card.scope_label
    return GuideDetail(
        **fields,
        content=reader_content(guide.content, guide.answers),
        scope_id=guide.exam_id,
        due_date=scope.due_date,
        use_history=guide.use_history,
        read_sections=guide.read_sections,
        answers=guide.answers,
        feedback=guide.feedback,
        mastery=await _amastery(guide, card.course_id),
    )


async def aget_detail(user_id: str, guide_id: str) -> GuideDetail:
    """One of the user's guides. ``GuideNotFound`` when it is missing or
    belongs to someone else."""
    return await abuild_detail(await store.aload_guide(user_id, guide_id))
