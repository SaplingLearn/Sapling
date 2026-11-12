"""A guide as its card on the Study Guides home: the title, where its space
goes, four counts, and how many lectures arrived since it was made.

The card is built from the stored row. The class's name and term and the
lecture documents are read once for the whole list, never per guide.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from starlette.concurrency import run_in_threadpool

from db.connection import pg_quote_value, table
from models.study_guide import (
    GuideCard,
    GuideContent,
    GuideCounts,
    GuideStatus,
    SectionBar,
)
from services import academics
from services.study_guides import materials, store
from services.study_guides.store import GuideRow

WORDS_PER_MINUTE = 200
#: Time a block takes on top of its words: stepping through a worked example,
#: reading a chart, answering a question.
MINUTES_PER_BLOCK = 0.5


@dataclass(frozen=True)
class GuideClass:
    """The class a guide belongs to, as the HTTP boundary names it."""

    course_id: str
    course_name: str
    semester: str | None


# ── Counts ───────────────────────────────────────────────────────────────────


def _words(value: Any) -> int:
    """Words in every string of a dumped item, however deep."""
    if isinstance(value, str):
        return len(value.split())
    if isinstance(value, dict):
        return sum(_words(v) for v in value.values())
    if isinstance(value, list):
        return sum(_words(v) for v in value)
    return 0


def reading_minutes(content: GuideContent) -> int:
    """How long the guide takes to read: its words at ``WORDS_PER_MINUTE``
    plus ``MINUTES_PER_BLOCK`` for each block, and never under a minute."""
    items = [item for section in content.sections for item in section.items]
    words = sum(_words(item.model_dump(exclude={"id", "type"})) for item in items)
    blocks = sum(item.type != "prose" for item in items)
    return max(1, round(words / WORDS_PER_MINUTE + blocks * MINUTES_PER_BLOCK))


def counts(content: GuideContent) -> GuideCounts:
    items = [item for section in content.sections for item in section.items]
    return GuideCounts(
        sections=len(content.sections),
        blocks=sum(item.type != "prose" for item in items),
        practice=sum(item.type == "check" for item in items),
        minutes=reading_minutes(content),
    )


# ── One card ─────────────────────────────────────────────────────────────────


def _status(guide: GuideRow) -> GuideStatus:
    """A guide whose content could not be read is shown as failed, so the
    reader says so instead of drawing an empty guide."""
    return "failed" if getattr(guide, "unreadable", False) else guide.status


def card(guide: GuideRow, guide_class: GuideClass, lecture_docs: list[dict]) -> GuideCard:
    """One guide's card. ``lecture_docs`` is ``materials.alist_lecture_docs``
    for the guide's owner."""
    content = guide.content
    new = materials.new_material_ids(
        lecture_docs,
        offering_id=guide.offering_id,
        material_ids=guide.material_ids,
        since=guide.generated_at,
    )
    return GuideCard(
        id=guide.id,
        title=content.title,
        course_id=guide_class.course_id,
        course_name=guide_class.course_name,
        semester=guide_class.semester,
        scope_kind=guide.scope_kind,
        scope_label=content.scope_label,
        goal=guide.goal,
        depth=guide.depth,
        status=_status(guide),
        generated_at=guide.generated_at,
        created_at=guide.created_at,
        saved_at=guide.saved_at,
        new_materials=len(new),
        bars=[SectionBar(title=s.title, tier=s.tier, weight=s.weight) for s in content.sections],
        counts=counts(content),
    )


# ── The classes behind a list of guides ──────────────────────────────────────


def _course_and_term(offering_id: str) -> tuple[str, str | None]:
    """An offering's abstract course id and term label. Both lookups are
    cached per process in ``academics``."""
    course_id = academics.offering_course_id(offering_id) or ""
    return course_id, (academics.term_for_offering(offering_id) or {}).get("label")


async def acourse_names(course_ids: set[str]) -> dict[str, str]:
    """Course name per abstract course id, in one read."""
    ids = sorted(course_id for course_id in course_ids if course_id)
    if not ids:
        return {}
    rows = await table("courses").aselect(
        "id,course_name",
        filters={"id": f"in.({','.join(pg_quote_value(i) for i in ids)})"},
    ) or []
    return {row["id"]: row.get("course_name") or "" for row in rows}


async def _aclasses(offering_ids: set[str]) -> dict[str, GuideClass]:
    """The class of each offering: one lookup per distinct offering and one
    read for every course name."""
    resolved = {
        offering_id: await run_in_threadpool(_course_and_term, offering_id)
        for offering_id in sorted(offering_ids)
    }
    names = await acourse_names({course_id for course_id, _ in resolved.values()})
    return {
        offering_id: GuideClass(
            course_id=course_id, course_name=names.get(course_id, ""), semester=semester,
        )
        for offering_id, (course_id, semester) in resolved.items()
    }


# ── Entry points ─────────────────────────────────────────────────────────────


async def acards(user_id: str, guides: list[GuideRow]) -> list[GuideCard]:
    """Cards for some of the user's guides, in the order given."""
    if not guides:
        return []
    lecture_docs = await materials.alist_lecture_docs(user_id)
    classes = await _aclasses({guide.offering_id for guide in guides})
    return [card(guide, classes[guide.offering_id], lecture_docs) for guide in guides]


async def alist_cards(user_id: str) -> list[GuideCard]:
    """Every guide the user has, newest first."""
    return await acards(user_id, await store.alist_guides(user_id))
