"""One generation run of a guide, as a stream of events.

`aprepare_generation` does everything that can still be refused with an HTTP
status: it loads the guide, refuses one that another run is writing, reads
what the run needs and charges the hourly limit. `stream_generation` is the
run itself. It takes the guide's claim as its first act, so a stream that is
never started holds nothing. Then the outline, and the sections one at a
time, each checked (`verify`) and saved before its event is sent, so a cut
stream resumes at the next unwritten section. It never raises, and it always
gives the claim back.

Modes: `resume` writes whatever is not written yet (the outline first, when
the guide has no sections). `regenerate` plans and writes the whole guide
again. `update` folds in the lectures added since the guide was made: the
outline agent says which sections to keep as written, and only the rest are
written. The last two keep the version they replace.
"""
from __future__ import annotations

import logging
import re
import uuid
from collections.abc import AsyncIterator
from contextlib import aclosing
from dataclasses import dataclass
from datetime import datetime, timezone
from itertools import count
from typing import Any

import anyio
from starlette.concurrency import run_in_threadpool

from agents.deps import SaplingDeps
from agents.study_guide import MAX_OUTLINE_SECTIONS, OutlineSection
from models.study_guide import (
    QUIZ_HISTORY_SOURCE,
    Depth,
    GuideContent,
    Section,
    Source,
)
from services import academics, events_service
from services.agent_events import SaplingEvent
from services.llm_budget import budget_error_in
from services.request_context import current_request_id
from services.request_limits import RateLimitClaim, aclaim_rate_limit, refund_rate_limit
from services.study_guides import materials, plan, signals, store, verify, writer
from services.study_guides.detail import abuild_detail, reader_content, reader_section
from services.study_guides.errors import (
    GuideBusy,
    GuideGenerationFailed,
    GuideInvalid,
    GuideRateLimited,
)
from services.study_guides.prompts import Brief
from services.study_guides.store import GuideRow

logger = logging.getLogger(__name__)

MODES = ("resume", "update", "regenerate")
#: Generation runs one student may start in an hour.
STUDY_GUIDE_GENERATE_LIMIT = 20
RATE_WINDOW_S = 3600
#: How long a finished run waits on the write that gives its claim back.
RELEASE_TIMEOUT_S = 5.0

UNKNOWN_MODE_DETAIL = "Unknown generation mode."
ALREADY_WRITTEN_DETAIL = "This guide is already written."
NOTHING_NEW_DETAIL = "There is nothing new to add to this guide."
NO_SOURCES_DETAIL = "None of this guide's materials can be read."
RATE_LIMITED_DETAIL = "You have asked for a lot of writing this hour. Try again later."
BUSY_DETAIL = "Another tab is writing this guide."
OVERTAKEN_DETAIL = "Another request took over writing this guide."

_SECTION_NUMBER = re.compile(r"s(\d+)")


@dataclass(frozen=True)
class Inputs:
    """What the writers read for one guide, and who they run for."""

    brief: Brief
    deps: SaplingDeps


@dataclass(frozen=True)
class Charge:
    """One action counted against a student's hourly limit."""

    key: str
    hit: RateLimitClaim

    def refund(self) -> None:
        refund_rate_limit(self.key, self.hit.slot)


@dataclass(frozen=True)
class Generation:
    """One run that may start: the guide as it was loaded, and what the run
    reads."""

    guide: GuideRow
    mode: str
    charge: Charge
    inputs: Inputs
    #: The guide's materials after this run: on an update, with the new
    #: lectures that could be read.
    material_ids: list[str]
    #: The labels of the sources an update adds.
    new_labels: list[str]


@dataclass
class _Run:
    """A run in progress: the row as last saved, and the claim as last
    refreshed (None until the run has taken it)."""

    generation: Generation
    guide: GuideRow
    claim: str | None = None
    #: Sections this run wrote, and tried to.
    written: int = 0
    attempted: int = 0

    @property
    def content(self) -> GuideContent:
        return self.guide.content

    async def aclaim(self) -> bool:
        self.claim = await store.aclaim_generation(self.guide.user_id, self.guide.id)
        return self.claim is not None

    async def atouch(self) -> None:
        self.claim = await store.atouch_generation(self.guide.user_id, self.guide.id, self.claim)

    async def asave(self, content: GuideContent, **changes: Any) -> None:
        self.guide = await store.asave_content(self.guide, content, claim=self.claim, **changes)
        self.claim = self.guide.generating_at


# ── What a run reads ──────────────────────────────────────────────────────────


async def amaterial_ids(guide: GuideRow) -> list[str]:
    """The documents the guide is made from. A guide from before the redesign
    recorded none: it was made from all of the class's, and still is."""
    if guide.material_ids:
        return guide.material_ids
    return [m.id for m in await materials.alist_materials(guide.user_id, guide.offering_id)]


async def aload_inputs(guide: GuideRow, material_ids: list[str]) -> Inputs:
    """The sources, the student's concepts and, with history on, their
    mastery and quiz mistakes. `GuideInvalid` when no source can be read."""
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
        # Captured here, in the request: the stream runs after its context.
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


# ── The hourly limit and the claim ────────────────────────────────────────────


async def acharge(user_id: str, *, action: str, limit: int) -> Charge:
    """Count one `action` against the student's hourly limit.
    `GuideRateLimited` past it."""
    key = f"study-guide-{action}:{user_id}"
    hit = await aclaim_rate_limit(key, limit=limit, window_sec=RATE_WINDOW_S)
    if hit.retry_after is not None:
        raise GuideRateLimited(RATE_LIMITED_DETAIL)
    return Charge(key=key, hit=hit)


async def arelease_guide(user_id: str, guide_id: str, claim: str) -> None:
    """Give the claim back. Never raises.

    Shielded: a run usually ends early because its request was cancelled, and
    a cancelled scope would cancel this write as well, leaving the guide
    claimed until the claim goes stale."""
    with anyio.move_on_after(RELEASE_TIMEOUT_S, shield=True):
        try:
            await store.arelease_generation(user_id, guide_id, claim)
        except Exception:
            logger.warning("study guide %s: the claim was not released", guide_id, exc_info=True)


# ── Prepare ───────────────────────────────────────────────────────────────────


def _unwritten(content: GuideContent) -> list[Section]:
    return [section for section in content.sections if section.status != "written"]


def _refuse(guide: GuideRow, mode: str) -> None:
    if guide.unreadable:
        raise GuideInvalid(store.GUIDE_UNREADABLE_DETAIL)
    if store.claim_is_held(guide):
        raise GuideBusy(BUSY_DETAIL)
    if mode == "resume" and guide.status == "ready" and not _unwritten(guide.content):
        raise GuideInvalid(ALREADY_WRITTEN_DETAIL)


async def _anew_lectures(guide: GuideRow) -> list[str]:
    """The class's lecture documents added since the guide was made."""
    lectures = await materials.alist_lecture_docs(guide.user_id)
    return materials.new_material_ids(
        lectures,
        offering_id=guide.offering_id,
        material_ids=guide.material_ids,
        since=guide.generated_at,
    )


async def aprepare_generation(user_id: str, guide_id: str, mode: str) -> Generation:
    """Everything a run needs, counted against the student's hourly limit.

    Raises `GuideNotFound`; `GuideBusy` while another run holds the guide;
    `GuideInvalid` (an unknown mode, a guide that is already written or
    cannot be read, an update with nothing new, no readable material);
    `GuideRateLimited`. Nothing is held yet: `stream_generation` takes the
    claim when it starts."""
    if mode not in MODES:
        raise GuideInvalid(UNKNOWN_MODE_DETAIL)
    guide = await store.aload_guide(user_id, guide_id)
    _refuse(guide, mode)
    own = await amaterial_ids(guide)
    new = await _anew_lectures(guide) if mode == "update" else []
    inputs = await aload_inputs(guide, list(dict.fromkeys([*own, *new])))
    added = {f"document:{material_id}" for material_id in new}
    read = [source for source in inputs.brief.sources if source.source.id in added]
    if mode == "update" and not read:
        raise GuideInvalid(NOTHING_NEW_DETAIL)
    return Generation(
        guide=guide,
        mode=mode,
        charge=await acharge(user_id, action="generate", limit=STUDY_GUIDE_GENERATE_LIMIT),
        inputs=inputs,
        # A new lecture that could not be read yet stays new for a later update.
        material_ids=list(dict.fromkeys(
            [*own, *(source.source.id.removeprefix("document:") for source in read)],
        )),
        new_labels=[source.label for source in read],
    )


# ── The outline ───────────────────────────────────────────────────────────────


def section_range(depth: Depth, concepts: int, *, room_for: int = 0) -> tuple[int, int]:
    """`(fewest, most)` sections the outline may plan: up to the depth's
    count, and no more than the materials have concepts to teach (when they
    name any). An update needs `room_for` the sections it could keep plus one
    per new lecture."""
    most = min(plan.SECTION_COUNT[depth], concepts or MAX_OUTLINE_SECTIONS)
    most = min(max(most, room_for), MAX_OUTLINE_SECTIONS)
    return max(1, most - 2), most


def _keepable(run: _Run) -> list[Section]:
    """The sections an update may keep as written. No other mode keeps any."""
    if run.generation.mode != "update":
        return []
    return [section for section in run.content.sections if section.status == "written"]


def _range(run: _Run) -> tuple[int, int]:
    generation = run.generation
    taught = {
        signals.concept_key(name)
        for source in generation.inputs.brief.sources for name in source.concepts
    }
    keepable = _keepable(run)
    room_for = len(keepable) + len(generation.new_labels) if keepable else 0
    return section_range(run.guide.depth, len(taught), room_for=room_for)


def _first_free_number(sections: list[Section]) -> int:
    used = [int(m.group(1)) for s in sections if (m := _SECTION_NUMBER.fullmatch(s.id))]
    return max(used, default=0) + 1


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
    use_history: bool,
) -> list[Section]:
    """The outline as the guide's sections. The server decides ids, tiers and
    weights. A section the outline keeps (`keep_id` names a written section
    of `current`, once) stays exactly as it is; every other one is new,
    `queued`, and numbered after every id `current` uses, so nothing the
    student did on an old section can land on a new one."""
    kept = {section.id: section for section in current if section.status == "written"}
    numbers = count(_first_free_number(current))
    sections = [
        kept.pop(planned.keep_id, None) or _new_section(f"s{next(numbers)}", planned, brief)
        for planned in outline
    ]
    shares = plan.weights([section.tier for section in sections], use_history=use_history)
    return [
        section.model_copy(update={"weight": share}) for section, share in zip(sections, shares)
    ]


def _guide_sources(brief: Brief) -> list[Source]:
    sources = [source.source for source in brief.sources]
    if brief.mistakes:
        sources.append(Source(id=QUIZ_HISTORY_SOURCE, name="Your quiz history", kind="Sapling"))
    return sources


async def _akept_state(run: _Run, sections: list[Section]) -> dict[str, Any]:
    """The read marks and check answers that survive an update: those on the
    sections it keeps. Read again now, so what the student did while the
    outline was being planned is not lost."""
    fresh = await store.aload_guide(run.guide.user_id, run.guide.id)
    kept = [section for section in sections if section.status == "written"]
    kept_ids = {section.id for section in kept}
    checks = {item.id for section in kept for item in section.items if item.type == "check"}
    return {
        "read_sections": [section_id for section_id in fresh.read_sections if section_id in kept_ids],
        "answers": {
            block_id: answer for block_id, answer in fresh.answers.items() if block_id in checks
        },
    }


async def _aplan(run: _Run, fewest: int, most: int) -> None:
    """Write the outline and save the guide with it: every section present,
    `queued` unless it is kept."""
    generation = run.generation
    brief = generation.inputs.brief
    updating = generation.mode == "update"
    outline = await writer.awrite_outline(
        brief, low=fewest, high=most, deps=generation.inputs.deps,
        current=_keepable(run), new_labels=generation.new_labels,
    )
    sections = planned_sections(
        outline.sections[:most], run.content.sections if updating else [], brief,
        use_history=run.guide.use_history,
    )
    content = GuideContent(
        # An update keeps the name the student knows the guide by.
        title=run.content.title if updating else outline.title,
        deck=outline.deck,
        takeaways=outline.takeaways,
        sections=sections,
        sources=_guide_sources(brief),
        scope_label=run.content.scope_label,
    )
    changes: dict[str, Any] = {}
    if generation.mode == "regenerate":
        changes = {"keep_previous": True, "answers": {}, "read_sections": []}
    elif updating:
        changes = {"keep_previous": True, **await _akept_state(run, sections)}
    await run.asave(
        content, status="generating", material_ids=generation.material_ids, **changes,
    )


# ── One section ───────────────────────────────────────────────────────────────


def _with_section(content: GuideContent, section: Section) -> GuideContent:
    sections = [section if other.id == section.id else other for other in content.sections]
    return content.model_copy(update={"sections": sections})


async def _awrite(run: _Run, section: Section) -> Section:
    """Write, check and save one section. A section the writer fails on, or
    that has nothing left after the check, is saved as `failed`."""
    inputs = run.generation.inputs
    # Before the model is paid for: an overtaken run stops here.
    await run.atouch()
    run.attempted += 1
    try:
        items = await writer.awrite_section(inputs.brief, run.content, section, deps=inputs.deps)
    except GuideGenerationFailed:
        items = []
    checked = verify.check_section(
        section.model_copy(update={"items": items}), facts_for(inputs.brief, section),
    )
    written = checked.model_copy(update={"status": "written" if checked.items else "failed"})
    await run.asave(_with_section(run.content, written), status="generating")
    if written.status == "written":
        run.written += 1
    return written


# ── Events ────────────────────────────────────────────────────────────────────


def _status(step: str, message: str, number: int, total: int) -> SaplingEvent:
    return SaplingEvent(
        type="status", step=step, message=message, data={"step": number, "total": total},
    )


def _error(message: str, *, retryable: bool) -> SaplingEvent:
    return SaplingEvent(type="error", step="error", message=message, data={"retryable": retryable})


def _reading(sources: int) -> str:
    return f"Reading your {sources} material{'' if sources == 1 else 's'}"


def _writing(content: GuideContent, section: Section, *, outline_ready: bool) -> str:
    number = 1 + [other.id for other in content.sections].index(section.id)
    place = f"section {number} of {len(content.sections)}"
    return f"Outline ready. Writing {place}" if outline_ready else f"Writing {place}: {section.title}"


def _log_generated(run: _Run) -> None:
    guide, brief = run.guide, run.generation.inputs.brief
    events_service.log_event(
        "study_guide.generated",
        category="usage",
        user_id=guide.user_id,
        request_id=run.generation.inputs.deps.request_id,
        payload={
            "guide_id": guide.id,
            "mode": run.generation.mode,
            "scope_kind": guide.scope_kind,
            "goal": guide.goal,
            "depth": guide.depth,
            "use_history": guide.use_history,
            "sources": len(brief.sources),
            "sections": len(guide.content.sections),
            "sections_written": run.written,
            "sections_failed": run.attempted - run.written,
        },
    )


async def _aevents(run: _Run) -> AsyncIterator[SaplingEvent]:
    generation = run.generation
    planning = generation.mode != "resume" or not run.content.sections
    fewest, most = _range(run)
    before = 2 if planning else 1
    total = before + (most if planning else len(_unwritten(run.content))) + 1
    yield _status("read", _reading(len(generation.inputs.brief.sources)), 1, total)

    if planning:
        yield _status("outline", "Planning the outline", 2, total)
        await _aplan(run, fewest, most)
        yield SaplingEvent(
            type="progress", step="outline", message="Outline ready",
            data={"content": reader_content(run.content, run.guide.answers).model_dump(mode="json")},
        )

    todo = _unwritten(run.content)
    total = before + len(todo) + 1
    for number, section in enumerate(todo, start=1):
        label = _writing(run.content, section, outline_ready=planning and number == 1)
        yield _status("section", label, before + number, total)
        written = await _awrite(run, section)
        yield SaplingEvent(
            type="progress", step="section", message=written.title,
            data={"section": reader_section(written, run.guide.answers).model_dump(mode="json")},
        )
    if todo and not run.written:
        raise GuideGenerationFailed(writer.FAILED_DETAIL)

    yield _status("check", "Checking citations and blocks", total, total)
    await run.asave(
        run.content, status="ready", generated_at=datetime.now(timezone.utc).isoformat(),
    )
    detail = await abuild_detail(run.guide)
    _log_generated(run)
    yield SaplingEvent(
        type="done", step="done", message="Guide ready",
        data={"guide": detail.model_dump(mode="json")},
    )


async def _afailed(run: _Run, exc: Exception) -> SaplingEvent:
    """The `error` event a failed run ends with. A guide the run had already
    started on (or that was never written) is saved as `failed`; one whose
    outline could not be planned again is left as it was."""
    refusal = budget_error_in(exc)
    if refusal is None and not isinstance(exc, GuideGenerationFailed):
        logger.error("study guide %s: generation failed", run.guide.id, exc_info=exc)
    if run.claim and run.guide.status == "generating":
        try:
            await run.asave(run.content, status="failed")
        except Exception as save_error:
            logger.warning(
                "study guide %s: could not be marked failed (%s)",
                run.guide.id, type(save_error).__name__,
            )
    if refusal is not None:
        return _error(refusal.detail, retryable=False)
    return _error(writer.FAILED_DETAIL, retryable=True)


async def stream_generation(generation: Generation) -> AsyncIterator[SaplingEvent]:
    """The run as events: `status` before each step, `progress` with the
    outline and then with each section once it is saved, and `done` with the
    finished guide. A failure is an `error` event, never an exception.

    The guide's claim is taken here, not in `aprepare_generation`, so a
    stream nobody iterates holds nothing. It is given back when the stream
    ends, is closed or is cancelled. A stream that finds the guide claimed
    (another request got there since this one was prepared) ends with one
    `error` event and gives its charge back."""
    run = _Run(generation=generation, guide=generation.guide)
    try:
        if not await run.aclaim():
            generation.charge.refund()
            yield _error(BUSY_DETAIL, retryable=True)
            return
        async with aclosing(_aevents(run)) as events:
            async for event in events:
                yield event
    except store.ClaimLost:
        # Nothing more is written: the guide is another run's now.
        logger.info("study guide %s: the run was overtaken and stopped", run.guide.id)
        yield _error(OVERTAKEN_DETAIL, retryable=True)
    except Exception as exc:
        yield await _afailed(run, exc)
    finally:
        if run.claim:
            await arelease_guide(run.guide.user_id, run.guide.id, run.claim)
