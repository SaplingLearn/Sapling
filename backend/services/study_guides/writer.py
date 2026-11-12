"""Runs the three study-guide agents and turns what they write into the
contract's shapes.

Every run is awaited on the caller's loop, has its usage recorded here, and
fails in one of two ways: a refusal by the daily LLM budget is raised as
itself (`llm_budget.reraise_budget_refusal`), anything else is
`GuideGenerationFailed`.

A section comes back as text. `markup` parses it; a block that does not
validate gets one rewrite by the block agent and is dropped if that fails too.
"""
from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from pydantic_ai.usage import UsageLimits

from agents.deps import SaplingDeps
from agents.study_guide import (
    GuideOutline,
    study_guide_block_agent,
    study_guide_outline_agent,
    study_guide_section_agent,
)
from agents.usage import record_agent_usage
from models.study_guide import BLOCK_TYPES, Block, GuideContent, Item, Section
from services.llm_budget import reraise_budget_refusal
from services.study_guides import markup, prompts
from services.study_guides.errors import GuideGenerationFailed
from services.study_guides.markup import RejectedBlock
from services.study_guides.prompts import Brief

logger = logging.getLogger(__name__)

FEATURE = "study_guide"
FAILED_DETAIL = "The guide could not be written. Try again."

#: The agents have no tools, and only the outline retries its output (twice).
#: There is no token cap: the sources alone can fill most of a worker's.
_LIMITS = UsageLimits(request_limit=3, tool_calls_limit=0)


async def _arun(agent, message: str, deps: SaplingDeps):
    """One agent run's output, with its usage recorded."""
    try:
        result = await agent.run(message, deps=deps, usage_limits=_LIMITS)
    except Exception as exc:
        reraise_budget_refusal(exc)
        logger.warning("study guide: a model run failed (%s)", type(exc).__name__)
        raise GuideGenerationFailed(FAILED_DETAIL) from exc
    record_agent_usage(
        result, feature=FEATURE, task="study_guide",
        user_id=deps.user_id, request_id=deps.request_id,
    )
    return result.output


async def awrite_outline(
    brief: Brief,
    *,
    low: int,
    high: int,
    deps: SaplingDeps,
    current: list[Section] | None = None,
    new_labels: list[str] | None = None,
) -> GuideOutline:
    """The guide's outline, with `low` to `high` sections. On an update,
    `current` is the sections that can be kept and `new_labels` the sources
    added since they were written."""
    message = prompts.outline_message(
        brief, low=low, high=high, current=current, new_labels=new_labels,
    )
    return await _arun(study_guide_outline_agent, message, deps)


async def arewrite_block(
    brief: Brief,
    content: GuideContent,
    section: Section,
    *,
    block_id: str,
    block_type: str,
    block_text: str,
    why: str,
    deps: SaplingDeps,
) -> Block | None:
    """One block of `section` written again, under the same id. None when the
    reply is not a valid block of the same type."""
    message = prompts.block_message(brief, content, section, block_text=block_text, why=why)
    reply = await _arun(study_guide_block_agent, message, deps)
    block = markup.parse_block(reply, block_id=block_id, sources=brief.labels())
    if block is None or block.type != block_type:
        logger.warning("study guide: the rewrite of a %s block was not usable", block_type)
        return None
    return block


async def _arescued(
    brief: Brief, content: GuideContent, section: Section, rejected: RejectedBlock,
    deps: SaplingDeps,
) -> Block | None:
    """A rejected block after its one rewrite, or None to drop it."""
    try:
        return await arewrite_block(
            brief, content, section,
            block_id=rejected.id, block_type=rejected.type, block_text=rejected.text,
            why=prompts.REWRITE_REJECTED, deps=deps,
        )
    except GuideGenerationFailed:
        return None


async def awrite_section(
    brief: Brief,
    content: GuideContent,
    section: Section,
    *,
    deps: SaplingDeps,
    beat: Callable[[], Awaitable[None]],
) -> list[Item]:
    """One section of `content` as items, not yet checked by `verify`.
    `GuideGenerationFailed` when nothing usable came back.

    `beat` is awaited before each rewrite of a rejected block: every rewrite
    is another slow model call, and the caller has a claim to keep fresh.
    What it raises ends the section."""
    reply = await _arun(
        study_guide_section_agent, prompts.section_message(brief, content, section), deps,
    )
    parsed = markup.parse_section(reply, section_id=section.id, sources=brief.labels())
    items = parsed.items
    for rejected in parsed.rejected:
        # A block whose type could not be read is dropped unasked: there is
        # no type to ask the rewriter for.
        if rejected.type not in BLOCK_TYPES:
            continue
        await beat()
        block = await _arescued(brief, content, section, rejected, deps)
        if block is not None:
            items = markup.put_back(items, block)
    if not items:
        raise GuideGenerationFailed(FAILED_DETAIL)
    return items
