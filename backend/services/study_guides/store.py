"""The only code that reads or writes the ``study_guides`` table.

It turns rows into :class:`GuideRow`, owns the encryption of ``content``,
``previous_content`` and ``answers`` (``encrypt_json``; see the table's
migration, ``20261112094239_study_guides_durable.sql``), holds the generation
claim, and writes a check answer at most once per block.

The claim is owned. Taking it returns a token (the ``generating_at`` stamp it
wrote), and a run's touch, saves and release only act on a row that still
holds that token. A run that was overtaken gets ``ClaimLost`` and must stop.

Every read and write is filtered by ``user_id`` as well as ``id``, so another
student's guide answers exactly like one that does not exist
(``GuideNotFound``).
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from db.connection import table
from models.study_guide import (
    GUIDE_FORMAT,
    CheckAnswer,
    Depth,
    Feedback,
    Goal,
    GuideContent,
    GuideStatus,
    ScopeKind,
    parse_items,
)
from services.encryption import decrypt_json_column, encrypt_json
from services.study_guides.errors import GuideBusy, GuideInvalid, GuideNotFound
from services.study_guides.legacy import UNTITLED, content_from_topics

logger = logging.getLogger(__name__)

TABLE = "study_guides"

#: A generation claim older than this is treated as abandoned (the run that
#: took it crashed or was cut off without releasing it). A run refreshes its
#: claim between model calls, and one call on the ``study_guide`` slot can
#: take three attempts of 240 seconds, so the window is longer than that.
CLAIM_STALE_AFTER = timedelta(minutes=15)

#: Guides one list call returns. Every row carries its whole encrypted
#: content (the card's title and counts are inside it), so the read is bounded.
LIST_LIMIT = 200

GUIDE_NOT_FOUND_DETAIL = "Study guide not found."
GUIDE_BUSY_DETAIL = "This study guide is being changed. Try again."
GUIDE_UNREADABLE_DETAIL = "This guide cannot be read, so it was left as it is."
ANSWERS_UNREADABLE_DETAIL = "Your answers on this guide cannot be read, so they were left as they are."

#: Everything a ``GuideRow`` is built from. ``previous_content`` is written
#: here and never read back: nothing shows the previous version yet.
_COLUMNS = (
    "id,user_id,offering_id,exam_id,scope_kind,goal,depth,use_history,status,format,"
    "content,material_ids,read_sections,answers,feedback,saved_at,generating_at,"
    "generated_at,created_at,updated_at"
)

#: The plaintext columns ``asave_content`` may write beside the content.
_SAVE_COLUMNS = frozenset({"status", "generated_at", "material_ids", "read_sections"})


class ClaimLost(Exception):
    """The run's claim token is no longer on the row: the run went silent for
    longer than ``CLAIM_STALE_AFTER`` and another one took the guide (or the
    guide is gone). The run must stop without writing anything more."""


@dataclass(frozen=True)
class GuideRow:
    """One ``study_guides`` row, decrypted. ``content`` is always the current
    shape: a ``format`` 1 row is upgraded on read (``format`` still says what
    is stored). Timestamps are the ISO strings PostgREST returned.

    ``unreadable`` is True when the stored content could not be decrypted or
    read. ``content`` is then an empty placeholder, and the row is never
    written over (``asave_content`` refuses). ``answers_unreadable`` is the
    same for the stored check answers: ``answers`` is then empty, and no
    answer is recorded over them (``arecord_answer`` refuses)."""

    id: str
    user_id: str
    offering_id: str
    exam_id: str | None
    scope_kind: ScopeKind
    goal: Goal
    depth: Depth
    use_history: bool
    status: GuideStatus
    format: int
    content: GuideContent
    material_ids: list[str]
    read_sections: list[str]
    answers: dict[str, CheckAnswer]
    feedback: Feedback | None
    saved_at: str | None
    generating_at: str | None
    generated_at: str | None
    created_at: str
    updated_at: str
    unreadable: bool = False
    answers_unreadable: bool = False


# ── Rows ─────────────────────────────────────────────────────────────────────


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _own(user_id: str, guide_id: str) -> dict[str, str]:
    return {"id": f"eq.{guide_id}", "user_id": f"eq.{user_id}"}


def _encrypt_content(content: GuideContent) -> str:
    return encrypt_json(content.model_dump(mode="json"))


def _encrypt_answers(answers: dict[str, CheckAnswer]) -> str:
    return encrypt_json({block_id: answer.model_dump() for block_id, answer in answers.items()})


def _sound_section(section: Any) -> Any:
    """A stored section with only the items that still validate, so one item
    the contract has moved away from does not cost the guide its other items
    (``parse_items`` warns about each one it drops)."""
    if not isinstance(section, dict) or not isinstance(section.get("items"), list):
        return section
    valid, _ = parse_items(section["items"])
    return {**section, "items": valid}


def _stored_content(stored: dict) -> GuideContent:
    sections = stored.get("sections")
    if isinstance(sections, list):
        stored = {**stored, "sections": [_sound_section(s) for s in sections]}
    return GuideContent.model_validate(stored)


def _content(raw: dict) -> tuple[GuideContent, bool]:
    """``(the row's content in the current shape, whether it is unreadable)``.
    A row that does not decrypt or validate is still listed, as an empty
    placeholder marked unreadable, rather than failing the whole list."""
    try:
        stored = decrypt_json_column(raw.get("content")) or {}
        if raw.get("format") == GUIDE_FORMAT:
            return _stored_content(stored), False
        return content_from_topics(stored), False
    except Exception as exc:
        logger.warning(
            "study guide %s: content could not be read (%s); showing it empty",
            raw.get("id"), type(exc).__name__,
        )
        return GuideContent(title=UNTITLED), True


def _answers(raw: dict) -> tuple[dict[str, CheckAnswer], bool]:
    """``(the row's check answers, whether they are unreadable)``."""
    try:
        stored = decrypt_json_column(raw.get("answers")) or {}
        return {block_id: CheckAnswer.model_validate(a) for block_id, a in stored.items()}, False
    except Exception as exc:
        logger.warning(
            "study guide %s: answers could not be read (%s); showing none",
            raw.get("id"), type(exc).__name__,
        )
        return {}, True


def _strings(value: Any) -> list[str]:
    return [v for v in value if isinstance(v, str)] if isinstance(value, list) else []


def _to_row(raw: dict) -> GuideRow:
    content, unreadable = _content(raw)
    answers, answers_unreadable = _answers(raw)
    return GuideRow(
        id=raw["id"],
        user_id=raw["user_id"],
        offering_id=raw["offering_id"],
        exam_id=raw.get("exam_id"),
        scope_kind=raw.get("scope_kind") or "exam",
        goal=raw.get("goal") or "exam_prep",
        depth=raw.get("depth") or "standard",
        use_history=raw.get("use_history") is not False,
        status=raw.get("status") or "ready",
        format=raw.get("format") or 1,
        content=content,
        material_ids=_strings(raw.get("material_ids")),
        read_sections=_strings(raw.get("read_sections")),
        answers=answers,
        feedback=raw.get("feedback"),
        saved_at=raw.get("saved_at"),
        generating_at=raw.get("generating_at"),
        generated_at=raw.get("generated_at"),
        created_at=raw.get("created_at") or "",
        updated_at=raw.get("updated_at") or "",
        unreadable=unreadable,
        answers_unreadable=answers_unreadable,
    )


def _written(rows: list | None) -> GuideRow:
    """The row an update returned, or ``GuideNotFound`` when it matched none
    (the guide was deleted, or was never the caller's)."""
    if not rows:
        raise GuideNotFound(GUIDE_NOT_FOUND_DETAIL)
    return _to_row(rows[0])


# ── Reads ────────────────────────────────────────────────────────────────────


async def aload_guide(user_id: str, guide_id: str) -> GuideRow:
    """One of the user's guides. Raises ``GuideNotFound`` when it is missing
    or belongs to someone else."""
    rows = await table(TABLE).aselect(_COLUMNS, filters=_own(user_id, guide_id), limit=1)
    return _written(rows)


async def alist_guides(user_id: str) -> list[GuideRow]:
    """The user's guides, newest first."""
    rows = await table(TABLE).aselect(
        _COLUMNS,
        filters={"user_id": f"eq.{user_id}"},
        order="created_at.desc,id.desc",
        limit=LIST_LIMIT,
    )
    return [_to_row(r) for r in rows or []]


# ── Writes ───────────────────────────────────────────────────────────────────


async def ainsert_guide(
    *,
    user_id: str,
    offering_id: str,
    scope_kind: ScopeKind,
    exam_id: str | None,
    goal: Goal,
    depth: Depth,
    use_history: bool,
    material_ids: list[str],
    content: GuideContent,
) -> str:
    """Insert a new guide that is still to be written (``status`` is
    ``generating``, ``generated_at`` NULL) and return its id."""
    guide_id = str(uuid.uuid4())
    await table(TABLE).ainsert({
        "id": guide_id,
        "user_id": user_id,
        "offering_id": offering_id,
        "exam_id": exam_id,
        "scope_kind": scope_kind,
        "goal": goal,
        "depth": depth,
        "use_history": use_history,
        "status": "generating",
        "format": GUIDE_FORMAT,
        "content": _encrypt_content(content),
        "material_ids": list(material_ids),
        # Sent as NULL on purpose: the column's default is now().
        "generated_at": None,
    })
    return guide_id


async def asave_content(
    guide: GuideRow,
    content: GuideContent,
    *,
    claim: str | None = None,
    release: bool = False,
    keep_previous: bool = False,
    answers: dict[str, CheckAnswer] | None = None,
    **columns: Any,
) -> GuideRow:
    """Write ``content`` and, in the same update, any of ``status``,
    ``generated_at`` (an ISO string), ``material_ids`` and ``read_sections``.

    With ``claim`` (a run's token) the write only lands while the row still
    holds that claim, and refreshes it: the returned row's ``generating_at``
    is the run's new token. ``ClaimLost`` when the token is gone. With
    ``release`` as well, the same write gives the claim up instead (a run's
    last save), so the guide is free the moment it is finished.

    ``keep_previous`` moves the content ``guide`` was loaded with into
    ``previous_content`` (Update and Regenerate keep one step back).
    ``answers`` replaces the check answers: the ones that survive an Update,
    or none after a Regenerate. Left as None, the answers are not touched.

    An unreadable row is never written over (``GuideInvalid``): its stored
    content may only need the right key to read again. Returns the row as
    written."""
    if guide.unreadable:
        raise GuideInvalid(GUIDE_UNREADABLE_DETAIL)
    unknown = sorted(set(columns) - _SAVE_COLUMNS)
    if unknown:
        raise TypeError(f"asave_content cannot write {', '.join(unknown)}")
    patch: dict[str, Any] = {
        **columns,
        "content": _encrypt_content(content),
        "format": GUIDE_FORMAT,
    }
    if keep_previous:
        patch["previous_content"] = _encrypt_content(guide.content)
    if answers is not None:
        patch["answers"] = _encrypt_answers(answers) if answers else None
    filters = _own(guide.user_id, guide.id)
    if claim is not None:
        patch["generating_at"] = None if release else _now().isoformat()
        filters = _held(guide.user_id, guide.id, claim)
    rows = await table(TABLE).aupdate(patch, filters=filters)
    if claim is not None and not rows:
        raise ClaimLost(guide.id)
    return _written(rows)


async def apatch_state(
    user_id: str,
    guide_id: str,
    *,
    read_sections: list[str] | None = None,
    saved: bool | None = None,
    feedback: Feedback | None = None,
) -> GuideRow:
    """Change the reader's small state; an argument left as None is left
    alone. ``saved`` True stamps ``saved_at`` with now, False clears it."""
    patch: dict[str, Any] = {}
    if read_sections is not None:
        patch["read_sections"] = list(read_sections)
    if saved is not None:
        patch["saved_at"] = _now().isoformat() if saved else None
    if feedback is not None:
        patch["feedback"] = feedback
    if not patch:
        return await aload_guide(user_id, guide_id)
    rows = await table(TABLE).aupdate(patch, filters=_own(user_id, guide_id))
    return _written(rows)


# ── The generation claim ─────────────────────────────────────────────────────


def _held(user_id: str, guide_id: str, claim: str) -> dict[str, str]:
    """Filters for the caller's guide while it still holds ``claim``."""
    return {**_own(user_id, guide_id), "generating_at": f"eq.{claim}"}


def _token(rows: list | None) -> str | None:
    """The claim token on the row an update returned, or None when the update
    matched no row."""
    return rows[0]["generating_at"] if rows else None


def claim_is_held(guide: GuideRow) -> bool:
    """Whether a run held the guide when it was loaded: it has a claim that is
    not stale. Good for refusing a request early; only ``aclaim_generation``
    decides who writes."""
    if not guide.generating_at:
        return False
    return datetime.fromisoformat(guide.generating_at) > _now() - CLAIM_STALE_AFTER


async def aclaim_generation(user_id: str, guide_id: str) -> str | None:
    """Take the guide for one run that writes its content. Returns the claim
    token when the claim was free (never taken, released, or older than
    ``CLAIM_STALE_AFTER``); None when another run holds it, or the guide is
    not the caller's.

    Each attempt is one conditional UPDATE, so of two requests racing for a
    free claim only one matches the row."""
    now = _now()
    stale_before = (now - CLAIM_STALE_AFTER).isoformat()
    for free in ("is.null", f"lt.{stale_before}"):
        rows = await table(TABLE).aupdate(
            {"generating_at": now.isoformat()},
            filters={**_own(user_id, guide_id), "generating_at": free},
        )
        if rows:
            return _token(rows)
    return None


async def atouch_generation(user_id: str, guide_id: str, claim: str) -> str:
    """Refresh a held claim (the run's heartbeat) and return the new token.
    ``ClaimLost`` when ``claim`` is no longer on the row: the claim is not
    taken back from whoever holds it now."""
    rows = await table(TABLE).aupdate(
        {"generating_at": _now().isoformat()}, filters=_held(user_id, guide_id, claim),
    )
    token = _token(rows)
    if token is None:
        raise ClaimLost(guide_id)
    return token


async def arelease_generation(user_id: str, guide_id: str, claim: str) -> None:
    """Give the claim up when the run ends, however it ends. A run that was
    overtaken releases nothing: the claim on the row is not its own."""
    await table(TABLE).aupdate(
        {"generating_at": None},
        filters=_held(user_id, guide_id, claim),
        prefer_return_minimal=True,
    )


# ── Check answers ────────────────────────────────────────────────────────────


async def arecord_answer(guide: GuideRow, block_id: str, answer: CheckAnswer) -> bool:
    """Store the student's answer to one check block unless it already has
    one. True when this call wrote it, False when the block was answered
    before (only the first answer counts toward mastery).

    The write is a compare-and-set on ``updated_at``, so a double click cannot
    record two first answers: the loser re-reads once and finds the block
    answered. A second lost race means the guide is being written right now:
    ``GuideBusy``.

    Stored answers that cannot be read are never written over
    (``GuideInvalid``): the write replaces the whole column, so it would keep
    only this one answer."""
    for retry in (True, False):
        if guide.answers_unreadable:
            raise GuideInvalid(ANSWERS_UNREADABLE_DETAIL)
        if block_id in guide.answers:
            return False
        rows = await table(TABLE).aupdate(
            {"answers": _encrypt_answers({**guide.answers, block_id: answer})},
            filters={**_own(guide.user_id, guide.id), "updated_at": f"eq.{guide.updated_at}"},
        )
        if rows:
            return True
        if retry:
            guide = await aload_guide(guide.user_id, guide.id)
    raise GuideBusy(GUIDE_BUSY_DETAIL)


__all__ = [
    "ANSWERS_UNREADABLE_DETAIL",
    "CLAIM_STALE_AFTER",
    "GUIDE_UNREADABLE_DETAIL",
    "LIST_LIMIT",
    "ClaimLost",
    "GuideRow",
    "aclaim_generation",
    "ainsert_guide",
    "alist_guides",
    "aload_guide",
    "apatch_state",
    "arecord_answer",
    "arelease_generation",
    "asave_content",
    "atouch_generation",
    "claim_is_held",
]
