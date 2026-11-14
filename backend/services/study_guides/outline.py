"""A guide's outline as its content: how many sections it may have, which
written ones an update keeps, and each section's id, tier and share.

The outline agent plans titles and main ideas from the source text. The
server decides everything else: a section's id, the mastery tier of the
concept it teaches, and its share of the guide.
"""
from __future__ import annotations

import re
from itertools import count
from typing import Any

from agents.study_guide import MAX_OUTLINE_SECTIONS, OutlineSection
from models.study_guide import (
    QUIZ_HISTORY_SOURCE,
    Depth,
    GuideContent,
    Section,
    Source,
)
from services.study_guides import plan, verify, writer
from services.study_guides.inputs import Inputs
from services.study_guides.prompts import Brief
from services.study_guides.store import GuideRow

_SECTION_NUMBER = re.compile(r"s(\d+)")


def written(content: GuideContent) -> list[Section]:
    return [section for section in content.sections if section.status == "written"]


def unwritten(content: GuideContent) -> list[Section]:
    return [section for section in content.sections if section.status != "written"]


# ── How many sections ─────────────────────────────────────────────────────────


def section_range(depth: Depth, *, room_for: int = 0) -> tuple[int, int]:
    """`(fewest, most)` sections the outline may plan: up to the depth's
    count. An update needs `room_for` the sections it could keep plus one per
    new lecture."""
    most = min(max(plan.SECTION_COUNT[depth], room_for), MAX_OUTLINE_SECTIONS)
    return max(1, most - 2), most


def _keepable(guide: GuideRow, updating: bool) -> list[Section]:
    """The sections an update may keep as written. No other run keeps any."""
    return written(guide.content) if updating else []


def plan_range(guide: GuideRow, *, updating: bool, new_labels: list[str]) -> tuple[int, int]:
    """The section range the guide's next outline is asked for."""
    keepable = _keepable(guide, updating)
    room_for = len(keepable) + len(new_labels) if keepable else 0
    return section_range(guide.depth, room_for=room_for)


# ── The outline as sections ───────────────────────────────────────────────────


def _highest_number(sections: list[Section]) -> int:
    used = [int(m.group(1)) for s in sections if (m := _SECTION_NUMBER.fullmatch(s.id))]
    return max(used, default=0)


def last_number(content: GuideContent) -> int:
    """The highest section number the guide has ever used: its stored mark,
    or a higher id among its sections (content from before the mark)."""
    return max(content.last_section_number, _highest_number(content.sections))


def _new_section(section_id: str, planned: OutlineSection, brief: Brief) -> Section:
    concept = verify.tree_name(planned.concept, brief.concepts)
    return Section(
        id=section_id,
        title=planned.title,
        concept=concept,
        tier=brief.tiers.get(concept, "unexplored"),
        one_line=planned.one_line,
    )


def planned_sections(
    outline: list[OutlineSection],
    current: list[Section],
    brief: Brief,
    *,
    updating: bool,
    use_history: bool,
    used: int = 0,
) -> list[Section]:
    """The outline as the guide's sections. The server decides ids, tiers and
    weights. On an update, a section the outline keeps (`keep_id` names a
    written section of `current`, once) stays exactly as it is. Every other
    one is new, `queued`, and numbered after every id `current` uses and
    after `used`, the highest number the guide used before (its sections
    dropped by an earlier update included). A regenerate keeps none, and
    numbers the same way: an id is never used again, so an answer or a read
    mark sent for an old section (by a tab still showing it) cannot land on
    a new one."""
    keepable = [section for section in current if updating and section.status == "written"]
    kept = {section.id: section for section in keepable}
    numbers = count(max(used, _highest_number(current)) + 1)
    sections = [
        kept.pop(planned.keep_id, None) or _new_section(f"s{next(numbers)}", planned, brief)
        for planned in outline
    ]
    shares = plan.weights([section.tier for section in sections], use_history=use_history)
    return [
        section.model_copy(update={"weight": share}) for section, share in zip(sections, shares)
    ]


def guide_sources(brief: Brief, listed: list[Source]) -> list[Source]:
    """What the guide lists as its sources: what the run read, the quiz
    history when there are mistakes to cite, and whatever the guide `listed`
    before (a section an update keeps may cite a document the run had no room
    to read)."""
    sources = [source.source for source in brief.sources]
    if brief.mistakes:
        sources.append(Source(id=QUIZ_HISTORY_SOURCE, name="Your quiz history", kind="Sapling"))
    read = {source.id for source in sources}
    return [*sources, *(source for source in listed if source.id not in read)]


async def anew_content(
    guide: GuideRow, inputs: Inputs, *, updating: bool, new_labels: list[str],
    materials_read_at: str | None,
) -> GuideContent:
    """The guide's content as the outline agent plans it now: every section
    present, `queued` unless an update keeps it. `materials_read_at` is when
    the materials it is planned from were chosen or read. Nothing is saved
    here."""
    brief, current = inputs.brief, guide.content
    fewest, most = plan_range(guide, updating=updating, new_labels=new_labels)
    planned = await writer.awrite_outline(
        brief, low=fewest, high=most, deps=inputs.deps,
        current=_keepable(guide, updating), new_labels=new_labels,
    )
    used = last_number(current)
    sections = planned_sections(
        planned.sections[:most], current.sections, brief,
        updating=updating, use_history=guide.use_history, used=used,
    )
    return GuideContent(
        # An update keeps the name the student knows the guide by.
        title=current.title if updating else planned.title,
        deck=planned.deck,
        takeaways=planned.takeaways,
        sections=sections,
        sources=guide_sources(brief, current.sources if updating else []),
        scope_label=current.scope_label,
        last_section_number=max(used, _highest_number(sections)),
        materials_read_at=materials_read_at,
    )


def kept_state(guide: GuideRow, sections: list[Section]) -> dict[str, Any]:
    """The read marks and check answers of `guide` that survive an update to
    `sections`: those on the sections it keeps."""
    had = {section.id for section in guide.content.sections}
    kept = [s for s in sections if s.status == "written" and s.id in had]
    kept_ids = {section.id for section in kept}
    checks = {item.id for section in kept for item in section.items if item.type == "check"}
    return {
        "read_sections": [section_id for section_id in guide.read_sections if section_id in kept_ids],
        "answers": {
            block_id: answer for block_id, answer in guide.answers.items() if block_id in checks
        },
    }
