"""One generation run of a guide, as a stream of events.

`aprepare_generation` does everything that can still be refused with an HTTP
status: it loads the guide, refuses one that another run is writing, reads
what the run needs and charges the hourly limit. The charge is kept only once
a model is asked for something; a run that ends before that (or a stream that
is never started: `asettle_charge`) gives it back. `stream_generation` is the
run itself. It takes the guide's claim as its first act, so a stream that is
never started holds nothing, and reads the guide again under the claim, so it
works from the row as it is and not as it was prepared. Then the outline, and
the sections one at a time, each checked (`verify`) and saved before its
event is sent, so a cut stream resumes at the next unwritten section. It
never raises, and it always gives the claim back: with its last save when it
finishes, so the guide is free before `done` is sent.

Modes: `resume` writes whatever is not written yet (the outline first, when
the guide has no sections). `update` and `regenerate` both read the lectures
added since the guide was made, beside the materials it already has.
`regenerate` plans and writes the whole guide again. `update` folds the new
lectures in: the outline agent says which sections to keep as written, and
only the rest are written.

An Update or Regenerate replaces a guide the student may be reading, so it
holds its outline in memory and saves nothing until its first section is
written. That first save is the one that keeps the previous version. A run
that fails before it leaves the guide exactly as it was.
"""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import aclosing
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import anyio

from models.study_guide import GuideContent, GuideStatus, Section
from services import events_service
from services.agent_events import SaplingEvent
from services.llm_budget import budget_error_in
from services.study_guides import limits, outline, store, verify, writer
from services.study_guides.detail import abuild_detail, reader_content, reader_section
from services.study_guides.errors import GuideBusy, GuideGenerationFailed, GuideInvalid
from services.study_guides.inputs import (
    Inputs,
    aload_inputs,
    amaterial_ids,
    anew_lectures,
    facts_for,
)
from services.study_guides.limits import Charge
from services.study_guides.store import GuideRow

logger = logging.getLogger(__name__)

MODES = ("resume", "update", "regenerate")
#: How long a finished run waits on the write that gives its claim back.
RELEASE_TIMEOUT_S = 5.0
#: How often the claim is refreshed while one call runs long. The outline's
#: run can retry its output twice, each request up to three slow attempts:
#: longer than `store.CLAIM_STALE_AFTER`, which this stays well inside.
HEARTBEAT_S = store.CLAIM_STALE_AFTER.total_seconds() / 3

UNKNOWN_MODE_DETAIL = "Unknown generation mode."
ALREADY_WRITTEN_DETAIL = "This guide is already written."
NOTHING_NEW_DETAIL = "There is nothing new to add to this guide."
BUSY_DETAIL = "Another tab is writing this guide."
OVERTAKEN_DETAIL = "Another request took over writing this guide."
#: The `data.code` of a stream that ends because another run holds the guide
#: or took it over. The stream is already a 200, so this is how the reader
#: knows to follow that run (as after a 409) rather than report a failure.
BUSY_CODE = "busy"
OVERTAKEN_CODE = "overtaken"


@dataclass(frozen=True)
class Generation:
    """One run that may start: the guide as it was loaded, and what the run
    reads."""

    guide: GuideRow
    mode: str
    charge: Charge
    inputs: Inputs
    #: The guide's materials after this run: its own and, on an update or a
    #: regenerate, the new lectures that could be read.
    material_ids: list[str]
    #: The labels of the sources new to the guide. Only an update's outline
    #: is told which they are: a regenerate keeps no section to set them
    #: against.
    new_labels: list[str]
    #: When an update or a regenerate listed the class's lectures (ISO),
    #: taken before the list was read: a lecture uploaded after it is new to
    #: the guide this run makes. None for a resume, which lists none.
    read_at: str | None = None


@dataclass
class _Run:
    """A run in progress: the row as last read or saved, the guide as the run
    has it, and the claim as last refreshed (None while the run holds none)."""

    generation: Generation
    guide: GuideRow
    content: GuideContent
    claim: str | None = None
    #: Whether the row holds this run's content. False until the guide is read
    #: again under the claim, and for an Update or Regenerate until its first
    #: section is written: the row is then still the guide as it was.
    on_row: bool = False
    #: Sections this run wrote, and tried to.
    written: int = 0
    attempted: int = 0

    async def aclaim(self) -> bool:
        self.claim = await store.aclaim_generation(self.guide.user_id, self.guide.id)
        return self.claim is not None

    async def atouch(self) -> None:
        self.claim = await store.atouch_generation(self.guide.user_id, self.guide.id, self.claim)

    async def asave(self, *, release: bool = False, **changes: Any) -> None:
        """Save the run's content. The first save of an Update or Regenerate
        is the one that replaces the guide, and carries what that takes."""
        if not self.on_row:
            changes = {**await _areplacement(self), **changes}
        self.guide = await store.asave_content(
            self.guide, self.content, claim=self.claim, release=release, **changes,
        )
        self.claim = self.guide.generating_at
        self.on_row = True

    async def arelease(self) -> None:
        claim, self.claim = self.claim, None
        await arelease_guide(self.guide.user_id, self.guide.id, claim)


async def _akept_fresh[T](run: _Run, call: Callable[[], Awaitable[T]]) -> T:
    """`call()`, with the run's claim refreshed every `HEARTBEAT_S` while it
    runs, so a slow model call is not taken for an abandoned run. A refresh
    that finds the claim lost cancels the call (nothing more is paid for)
    and raises `ClaimLost`; anything `call` raises is raised as itself."""

    async def beat() -> None:
        while True:
            await anyio.sleep(HEARTBEAT_S)
            await run.atouch()

    try:
        async with anyio.create_task_group() as beats:
            beats.start_soon(beat)
            result = await call()
            beats.cancel_scope.cancel()
    except BaseExceptionGroup as group:
        lost = group.subgroup(store.ClaimLost)
        raise (lost or group).exceptions[0] from None
    return result


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


def _refuse(guide: GuideRow, mode: str) -> None:
    if guide.unreadable:
        raise GuideInvalid(store.GUIDE_UNREADABLE_DETAIL)
    if store.claim_is_held(guide):
        raise GuideBusy(BUSY_DETAIL)
    if mode == "resume" and guide.status == "ready" and not outline.unwritten(guide.content):
        raise GuideInvalid(ALREADY_WRITTEN_DETAIL)


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
    # A resume finishes the guide as it was planned. The other two date it
    # from this read, so they read every lecture that date stops counting as
    # new. Taken before the list is read: anything uploaded after it is not in it.
    read_at = None if mode == "resume" else datetime.now(timezone.utc).isoformat()
    new = [] if mode == "resume" else await anew_lectures(guide)
    own = [material_id for material_id in await amaterial_ids(guide) if material_id not in new]
    # The new lectures last: past the source budget the last ids are read.
    inputs = await aload_inputs(guide, [*own, *new])
    added = {f"document:{material_id}" for material_id in new}
    read = [source for source in inputs.brief.sources if source.source.id in added]
    if mode == "update" and not read:
        raise GuideInvalid(NOTHING_NEW_DETAIL)
    return Generation(
        guide=guide,
        mode=mode,
        charge=await limits.acharge(
            user_id, action="generate", limit=limits.STUDY_GUIDE_GENERATE_LIMIT,
        ),
        inputs=inputs,
        # A new lecture that could not be read is not recorded as a material.
        material_ids=[*own, *(source.source.id.removeprefix("document:") for source in read)],
        new_labels=[source.label for source in read],
        read_at=read_at,
    )


# ── Start ─────────────────────────────────────────────────────────────────────


def _written_meanwhile(run: _Run, prepared: GuideRow) -> bool:
    """Whether another run did this one's work between its prepare and its
    claim: it finished the guide, or left a resume nothing to write."""
    guide = run.guide
    if guide.generated_at != prepared.generated_at:
        return True
    resumed = run.generation.mode == "resume" and guide.status == "ready"
    return resumed and not outline.unwritten(guide.content)


async def _astart(run: _Run) -> SaplingEvent | None:
    """Take the claim, then read the guide again under it: a run prepared
    before another one finished must not write over that one's work from the
    row it loaded. Returns the event the stream ends with when there is
    nothing for this run to do, else None."""
    if not await run.aclaim():
        # The prepare's 409, as an event: the reader waits for that run.
        return _error(BUSY_DETAIL, retryable=True, status=409, code=BUSY_CODE)
    prepared = run.guide
    run.guide = await store.aload_guide(prepared.user_id, prepared.id)
    run.content = run.guide.content
    if run.guide.unreadable:
        return _error(store.GUIDE_UNREADABLE_DETAIL, retryable=False)
    if _written_meanwhile(run, prepared):
        # The other request did the work: this one ends with the guide as it is.
        await run.arelease()
        return await _adone(run)
    run.on_row = run.generation.mode == "resume"
    return None


# ── The outline ───────────────────────────────────────────────────────────────


async def _aplan(run: _Run) -> None:
    """Plan the guide again. A guide with nothing written has nothing to
    lose, so its outline is saved at once and a cut stream resumes from it.
    An Update or Regenerate holds its outline until a section is written."""
    generation = run.generation
    generation.charge.keep()
    # A resume plans only a guide with no outline yet: a first generation,
    # made from the materials chosen when the guide was created.
    read_at = generation.read_at or run.guide.created_at or None
    run.content = await _akept_fresh(run, lambda: outline.anew_content(
        run.guide, generation.inputs,
        updating=generation.mode == "update", new_labels=generation.new_labels,
        materials_read_at=read_at,
    ))
    if run.on_row:
        await run.asave(status="generating", material_ids=generation.material_ids)


async def _areplacement(run: _Run) -> dict[str, Any]:
    """What the save that replaces a guide changes besides its content: the
    materials it is now made from, the previous version (kept only when it
    was a finished guide with something to read, so a half-written one never
    takes the place of the last good version), and the read marks and check
    answers, which go with the sections they were on."""
    loaded, generation = run.guide, run.generation
    changes: dict[str, Any] = {
        "material_ids": generation.material_ids,
        "keep_previous": loaded.status == "ready" and bool(outline.written(loaded.content)),
    }
    if generation.mode == "regenerate":
        return {**changes, "answers": {}, "read_sections": []}
    # Read again now, so what the student did while the run was writing is
    # not lost.
    fresh = await store.aload_guide(loaded.user_id, loaded.id)
    return {**changes, **outline.kept_state(fresh, run.content.sections)}


# ── One section ───────────────────────────────────────────────────────────────


def _with_section(content: GuideContent, section: Section) -> GuideContent:
    sections = [section if other.id == section.id else other for other in content.sections]
    return content.model_copy(update={"sections": sections})


def _status_while_writing(run: _Run) -> GuideStatus:
    """A finished guide whose missing sections are being filled in stays
    `ready`: the student can read it throughout. Any other is `generating`."""
    return "ready" if run.on_row and run.guide.status == "ready" else "generating"


async def _awrite(run: _Run, section: Section) -> Section:
    """Write, check and save one section. A section the writer fails on, or
    that has nothing left after the check, is `failed`. An Update or
    Regenerate that has written nothing yet saves nothing for a failed one:
    the guide it would replace is still the better read."""
    inputs = run.generation.inputs
    # Before the model is paid for: an overtaken run stops here.
    await run.atouch()
    run.attempted += 1
    run.generation.charge.keep()
    try:
        items = await writer.awrite_section(
            inputs.brief, run.content, section, deps=inputs.deps, beat=run.atouch,
        )
    except GuideGenerationFailed:
        items = []
    checked = verify.check_section(
        section.model_copy(update={"items": items}), facts_for(inputs.brief, section),
    )
    written = checked.model_copy(update={"status": "written" if checked.items else "failed"})
    run.content = _with_section(run.content, written)
    if written.status == "written":
        run.written += 1
    if run.on_row or written.status == "written":
        await run.asave(status=_status_while_writing(run))
    return written


def _refuse_nothing_to_read(run: _Run, todo: list[Section]) -> None:
    """`GuideGenerationFailed` when the run has no guide to leave: none of
    its sections is written, or it set out to replace a guide and wrote
    nothing. A guide with something to read is finished, failed sections
    and all."""
    replaced_nothing = bool(todo) and not run.on_row
    if replaced_nothing or not outline.written(run.content):
        raise GuideGenerationFailed(writer.FAILED_DETAIL)


def _made_at(run: _Run) -> str:
    """When the materials the guide is now made from were chosen or read.
    Content planned before that was kept falls back to the guide's previous
    date, or its creation: an earlier date counts a lecture as new that is
    not, a later one would hide one that is."""
    guide = run.guide
    return (
        run.content.materials_read_at
        or guide.generated_at
        or guide.created_at
        or datetime.now(timezone.utc).isoformat()
    )


async def _afinish(run: _Run, *, planned: bool) -> None:
    """The run's last save: the guide is ready and the claim is given up in
    the same write."""
    changes: dict[str, Any] = {"status": "ready"}
    # `generated_at` is when the guide's materials were read: the lectures
    # uploaded after it are the new ones, so it is never the finish time (a
    # lecture uploaded while the run wrote was not read). A run that planned
    # the guide dates it, and so does a resume that makes it ready (it was
    # `generating` or `failed`: a first generation, an Update or a Regenerate
    # that was cut short), from the read its outline was planned on. A
    # resume that only fills in sections of a guide that stayed `ready` read
    # nothing new, so it leaves the date alone.
    if planned or run.guide.status != "ready":
        changes["generated_at"] = _made_at(run)
    await run.asave(release=True, **changes)


# ── Events ────────────────────────────────────────────────────────────────────


def _status(step: str, message: str, number: int, total: int) -> SaplingEvent:
    return SaplingEvent(
        type="status", step=step, message=message, data={"step": number, "total": total},
    )


def _error(
    message: str, *, retryable: bool, status: int | None = None, code: str | None = None,
) -> SaplingEvent:
    """An `error` event. `status` is the HTTP status the request would have
    been answered with had the stream not opened yet (409: another run holds
    the guide), so the reader can treat the two the same. `code` names what
    went wrong (`busy`, `overtaken`) when another run holds the guide."""
    data: dict[str, Any] = {"retryable": retryable}
    if status is not None:
        data["status"] = status
    if code:
        data["code"] = code
    return SaplingEvent(type="error", step="error", message=message, data=data)


async def _adone(run: _Run) -> SaplingEvent:
    """`done` with the finished guide. The guide is saved (by this run or by
    the one it found had done the work) before this is built, so a read that
    fails here must not report a failed run: a Retry of a Regenerate would
    pay for the whole guide again. `done` then carries no guide, and the
    reader loads it."""
    try:
        guide = (await abuild_detail(run.guide)).model_dump(mode="json")
    except Exception:
        logger.warning(
            "study guide %s: written, but could not be read back for `done`",
            run.guide.id, exc_info=True,
        )
        guide = None
    return SaplingEvent(type="done", step="done", message="Guide ready", data={"guide": guide})


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
    _, most = outline.plan_range(
        run.guide, updating=generation.mode == "update", new_labels=generation.new_labels,
    )
    before = 2 if planning else 1
    total = before + (most if planning else len(outline.unwritten(run.content))) + 1
    yield _status("read", _reading(len(generation.inputs.brief.sources)), 1, total)

    if planning:
        yield _status("outline", "Planning the outline", 2, total)
        await _aplan(run)
        yield SaplingEvent(
            type="progress", step="outline", message="Outline ready",
            data={"content": reader_content(run.content, run.guide.answers).model_dump(mode="json")},
        )

    todo = outline.unwritten(run.content)
    total = before + len(todo) + 1
    for number, section in enumerate(todo, start=1):
        label = _writing(run.content, section, outline_ready=planning and number == 1)
        yield _status("section", label, before + number, total)
        written = await _awrite(run, section)
        yield SaplingEvent(
            type="progress", step="section", message=written.title,
            data={"section": reader_section(written, run.guide.answers).model_dump(mode="json")},
        )
    _refuse_nothing_to_read(run, todo)

    # Saved before the last status goes out: a reader that leaves now (the
    # stream is closed at this `yield`) still finds the guide ready, rather
    # than `generating` with every section written.
    await _afinish(run, planned=planning)
    yield _status("check", "Checking citations and blocks", total, total)
    _log_generated(run)
    yield await _adone(run)


async def _afailed(run: _Run, exc: Exception) -> SaplingEvent:
    """The `error` event a failed run ends with. A guide the run was writing
    is saved as `failed`. One it had not replaced yet, or that the student
    could read all along, is left as it is."""
    refusal = budget_error_in(exc)
    if refusal is None and not isinstance(exc, GuideGenerationFailed):
        logger.error("study guide %s: generation failed", run.guide.id, exc_info=exc)
    if run.claim and run.on_row and run.guide.status == "generating":
        try:
            await run.asave(status="failed")
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
    outline and then with each section, and `done` with the finished guide.
    A failure is an `error` event, never an exception.

    Each event's `data`, in `services.agent_events`'s envelope: `status`
    `{step, total}` (its label is the `message`); `progress` `{content}`
    (step `outline`) or `{section}` (step `section`); `done` `{guide}`, the
    reader's detail, or null when the saved guide could not be read back;
    `error` `{retryable}`, plus `code` (`busy`, `overtaken`) when another run
    has the guide, and `status` 409 when it took the claim first.

    The guide's claim is taken here, not in `aprepare_generation`, so a
    stream nobody iterates holds nothing. A finished run gives it back with
    its last save, before `done`; any other way the stream ends, is closed or
    is cancelled gives it back on the way out. A stream that cannot start
    (the guide is claimed, can no longer be read, or was written by another
    request since this one was prepared) ends with one event.

    However it ends, a run that never asked a model for anything gives its
    charge back."""
    run = _Run(generation=generation, guide=generation.guide, content=generation.guide.content)
    try:
        ended = await _astart(run)
        if ended is not None:
            yield ended
            return
        async with aclosing(_aevents(run)) as events:
            async for event in events:
                yield event
    except store.ClaimLost:
        # Nothing more is written: the guide is another run's now.
        logger.info("study guide %s: the run was overtaken and stopped", run.guide.id)
        yield _error(OVERTAKEN_DETAIL, retryable=True, code=OVERTAKEN_CODE)
    except Exception as exc:
        yield await _afailed(run, exc)
    finally:
        # Before the release, which awaits: a cancelled run must not lose it.
        generation.charge.refund()
        if run.claim:
            await run.arelease()


async def asettle_charge(generation: Generation) -> None:
    """Give the run's charge back unless a model was asked for something.

    The route calls it once the response is over, for the stream that never
    started: a client gone before the first event is iterated leaves
    `stream_generation` unstarted, and its own refund never runs. Safe to call
    after a stream that did run: the charge is settled once."""
    generation.charge.refund()
