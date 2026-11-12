"""Regenerate one block of a guide, leaving everything around it as it is.

The block agent writes a new version from what the section was written from.
It passes the same check as a generated block (`verify`) and takes the old
block's place under the old id. A check question is not regenerated: its id
carries the student's answer, and the first answer has moved their mastery.

The write holds the guide's generation claim, so a block cannot be changed
while the guide is being written, and a generation cannot start under it.
"""
from __future__ import annotations

from models.study_guide import Block, GuideContent, ProseItem, Section
from services import events_service
from services.study_guides import limits, prompts, store, verify, writer
from services.study_guides.errors import (
    GuideBusy,
    GuideGenerationFailed,
    GuideInvalid,
    GuideNotFound,
)
from services.study_guides.generation import arelease_guide
from services.study_guides.inputs import aload_inputs, amaterial_ids, facts_for
from services.study_guides.store import GuideRow

BLOCK_NOT_FOUND_DETAIL = "Block not found."
CHECK_DETAIL = "A check question cannot be regenerated."
BUSY_DETAIL = "This guide is being written. Try again when it is done."
NOT_REWRITTEN_DETAIL = "A new version of this block could not be written. Try again."


def _find(content: GuideContent, block_id: str) -> tuple[Section, Block]:
    """The block and its section. `GuideNotFound` for an id that is not a
    block of this guide; `GuideInvalid` for a check question."""
    for section in content.sections:
        for item in section.items:
            if item.id != block_id or isinstance(item, ProseItem):
                continue
            if item.type == "check":
                raise GuideInvalid(CHECK_DETAIL)
            return section, item
    raise GuideNotFound(BLOCK_NOT_FOUND_DETAIL)


def _with_block(content: GuideContent, section: Section, block: Block) -> GuideContent:
    items = [block if item.id == block.id else item for item in section.items]
    rewritten = section.model_copy(update={"items": items})
    sections = [rewritten if other.id == section.id else other for other in content.sections]
    return content.model_copy(update={"sections": sections})


async def _arewritten(guide: GuideRow, section: Section, block: Block) -> Block:
    """A new, checked version of `block`. `GuideGenerationFailed` when the
    rewrite is not a valid block of the same type, or does not pass the check."""
    inputs = await aload_inputs(guide, await amaterial_ids(guide))
    rewritten = await writer.arewrite_block(
        inputs.brief, guide.content, section,
        block_id=block.id,
        block_type=block.type,
        block_text=prompts.block_as_written(block, inputs.brief),
        why=prompts.REWRITE_ASKED,
        deps=inputs.deps,
    )
    checked = verify.check_block(rewritten, facts_for(inputs.brief, section)) if rewritten else None
    if checked is None:
        raise GuideGenerationFailed(NOT_REWRITTEN_DETAIL)
    return checked


async def aregenerate_block(user_id: str, guide_id: str, block_id: str) -> Block:
    """Write one block again and save it in place. Returns the new block.

    Raises `GuideNotFound` (the guide, or a block it does not have),
    `GuideInvalid` (a check question, a guide that cannot be read or has no
    readable material), `GuideRateLimited`, `GuideBusy` while the guide is
    being written, and `GuideGenerationFailed` when no valid new version came
    back. A refusal by the daily LLM budget is raised as itself."""
    guide = await store.aload_guide(user_id, guide_id)
    if guide.unreadable:
        raise GuideInvalid(store.GUIDE_UNREADABLE_DETAIL)
    _find(guide.content, block_id)
    charge = await limits.acharge(user_id, action="block", limit=limits.STUDY_GUIDE_BLOCK_LIMIT)
    claim = await store.aclaim_generation(user_id, guide_id)
    if claim is None:
        charge.refund()
        raise GuideBusy(BUSY_DETAIL)
    try:
        # Read again under the claim: nothing else writes the content now.
        guide = await store.aload_guide(user_id, guide_id)
        section, block = _find(guide.content, block_id)
        rewritten = await _arewritten(guide, section, block)
        saved = await store.asave_content(
            guide, _with_block(guide.content, section, rewritten), claim=claim,
        )
        claim = saved.generating_at
    except store.ClaimLost as lost:
        raise GuideBusy(BUSY_DETAIL) from lost
    finally:
        await arelease_guide(user_id, guide_id, claim)
    events_service.log_event(
        "study_guide.block_regenerated",
        category="usage",
        user_id=user_id,
        payload={"guide_id": guide_id, "block_type": rewritten.type},
    )
    return rewritten
