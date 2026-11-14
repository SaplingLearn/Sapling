"""What the writers read for one guide: its materials and their text, the
student's concepts and, with history on, their mastery and quiz mistakes.

A generation run and a block rewrite read the same things, so a block
written later is held to the same sources as the section around it.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass

from starlette.concurrency import run_in_threadpool

from agents.deps import SaplingDeps
from models.study_guide import Section
from services import academics
from services.request_context import current_request_id
from services.study_guides import materials, signals, verify, writer
from services.study_guides.errors import GuideInvalid
from services.study_guides.prompts import Brief
from services.study_guides.store import GuideRow

NO_SOURCES_DETAIL = "None of this guide's materials can be read."


@dataclass(frozen=True)
class Inputs:
    """What the writers read for one guide, and who they run for."""

    brief: Brief
    deps: SaplingDeps


async def amaterial_ids(guide: GuideRow) -> list[str]:
    """The documents the guide is made from, oldest first. A guide from
    before the redesign recorded none: it was made from all of the class's,
    and still is."""
    if guide.material_ids:
        return guide.material_ids
    return [m.id for m in await materials.alist_materials(guide.user_id, guide.offering_id)]


async def anew_lectures(guide: GuideRow) -> list[str]:
    """The class's lecture documents added since the guide was made."""
    lectures = await materials.alist_lecture_docs(guide.user_id)
    return materials.new_material_ids(
        lectures,
        offering_id=guide.offering_id,
        material_ids=guide.material_ids,
        since=guide.generated_at,
    )


async def aload_inputs(guide: GuideRow, material_ids: list[str]) -> Inputs:
    """The sources, the student's concepts and, with history on, their
    mastery and quiz mistakes. `GuideInvalid` when no source can be read.

    Past the source budget the last of `material_ids` are the ones read."""
    sources = await materials.aload_sources(guide.user_id, guide.offering_id, material_ids)
    if not sources:
        raise GuideInvalid(NO_SOURCES_DETAIL)
    # The graph is keyed on the abstract course. The lookup is cached, but its
    # first call per offering reads the database.
    course_id = await run_in_threadpool(academics.offering_course_id, guide.offering_id)
    scores = await signals.amastery(guide.user_id, course_id) if course_id else {}
    taught = [name for source in sources for name in source.concepts]
    history = guide.use_history and bool(scores)
    brief = Brief(
        scope_kind=guide.scope_kind,
        scope_label=guide.content.scope_label,
        goal=guide.goal,
        depth=guide.depth,
        sources=sources,
        concepts=list(scores),
        tiers=signals.tiers(scores) if history else {},
        mistakes=await signals.amistakes(guide.user_id, course_id, taught) if history else [],
    )
    deps = SaplingDeps(
        user_id=guide.user_id,
        course_id=course_id,
        supabase=None,
        # Captured here, in the request: a stream runs after its context.
        request_id=current_request_id() or str(uuid.uuid4()),
        feature=writer.FEATURE,
    )
    return Inputs(brief=brief, deps=deps)


def facts_for(brief: Brief, section: Section) -> verify.Facts:
    """What `verify` holds a section of this guide to."""
    return verify.Facts(
        sources={source.source.id: source.text for source in brief.sources},
        mistakes=brief.mistakes_for(section),
        concepts=brief.concepts,
    )
