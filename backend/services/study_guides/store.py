"""The only code that reads or writes the ``study_guides`` table.

It turns rows into :class:`GuideRow`, owns the encryption of ``content``,
``previous_content`` and ``answers`` (``encrypt_json``; see the table's
migration, ``20261112094239_study_guides_durable.sql``), holds the generation
claim, and writes a check answer at most once per block.

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
)
from services.encryption import decrypt_json_column, encrypt_json
from services.study_guides.errors import GuideBusy, GuideNotFound
from services.study_guides.legacy import UNTITLED, content_from_topics

logger = logging.getLogger(__name__)

TABLE = "study_guides"

#: A generation claim older than this is treated as abandoned (the run that
#: took it crashed or was cut off without releasing it).
CLAIM_STALE_AFTER = timedelta(minutes=5)

#: Guides one list call returns. Every row carries its whole encrypted
#: content (the card's title and counts are inside it), so the read is bounded.
LIST_LIMIT = 200

GUIDE_NOT_FOUND_DETAIL = "Study guide not found."
GUIDE_BUSY_DETAIL = "This study guide is being changed. Try again."

#: Everything a ``GuideRow`` is built from. ``previous_content`` is written
#: here and never read back: nothing shows the previous version yet.
_COLUMNS = (
    "id,user_id,offering_id,exam_id,scope_kind,goal,depth,use_history,status,format,"
    "content,material_ids,read_sections,answers,feedback,saved_at,generating_at,"
    "generated_at,created_at,updated_at"
)

#: The plaintext columns ``asave_content`` may write beside the content.
_SAVE_COLUMNS = frozenset({"status", "generated_at", "material_ids", "read_sections"})


@dataclass(frozen=True)
class GuideRow:
    """One ``study_guides`` row, decrypted. ``content`` is always the current
    shape: a ``format`` 1 row is upgraded on read (``format`` still says what
    is stored). Timestamps are the ISO strings PostgREST returned."""

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


# ── Rows ─────────────────────────────────────────────────────────────────────


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _own(user_id: str, guide_id: str) -> dict[str, str]:
    return {"id": f"eq.{guide_id}", "user_id": f"eq.{user_id}"}


def _encrypt_content(content: GuideContent) -> str:
    return encrypt_json(content.model_dump(mode="json"))


def _encrypt_answers(answers: dict[str, CheckAnswer]) -> str:
    return encrypt_json({block_id: answer.model_dump() for block_id, answer in answers.items()})


def _content(raw: dict) -> GuideContent:
    """The row's content in the current shape. A row that does not decrypt or
    validate reads as an empty guide rather than failing the whole list."""
    try:
        stored = decrypt_json_column(raw.get("content")) or {}
        if raw.get("format") == GUIDE_FORMAT:
            return GuideContent.model_validate(stored)
        return content_from_topics(stored)
    except Exception as exc:
        logger.warning(
            "study guide %s: content could not be read (%s); showing it empty",
            raw.get("id"), type(exc).__name__,
        )
        return GuideContent(title=UNTITLED)


def _answers(raw: dict) -> dict[str, CheckAnswer]:
    try:
        stored = decrypt_json_column(raw.get("answers")) or {}
        return {block_id: CheckAnswer.model_validate(a) for block_id, a in stored.items()}
    except Exception as exc:
        logger.warning(
            "study guide %s: answers could not be read (%s); showing none",
            raw.get("id"), type(exc).__name__,
        )
        return {}


def _strings(value: Any) -> list[str]:
    return [v for v in value if isinstance(v, str)] if isinstance(value, list) else []


def _to_row(raw: dict) -> GuideRow:
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
        content=_content(raw),
        material_ids=_strings(raw.get("material_ids")),
        read_sections=_strings(raw.get("read_sections")),
        answers=_answers(raw),
        feedback=raw.get("feedback"),
        saved_at=raw.get("saved_at"),
        generating_at=raw.get("generating_at"),
        generated_at=raw.get("generated_at"),
        created_at=raw.get("created_at") or "",
        updated_at=raw.get("updated_at") or "",
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
    keep_previous: bool = False,
    reset_answers: bool = False,
    **columns: Any,
) -> GuideRow:
    """Write ``content`` and, in the same update, any of ``status``,
    ``generated_at`` (an ISO string), ``material_ids`` and ``read_sections``.

    ``keep_previous`` moves the content ``guide`` was loaded with into
    ``previous_content`` (Update and Regenerate keep one step back);
    ``reset_answers`` clears the check answers of a rewritten guide. Returns
    the row as written."""
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
    if reset_answers:
        patch["answers"] = None
    rows = await table(TABLE).aupdate(patch, filters=_own(guide.user_id, guide.id))
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


async def aclaim_generation(user_id: str, guide_id: str) -> bool:
    """Take the guide for one generation run. True when the claim was free
    (never taken, released, or older than ``CLAIM_STALE_AFTER``); False when
    another run holds it, or the guide is not the caller's.

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
            return True
    return False


async def atouch_generation(user_id: str, guide_id: str) -> None:
    """Refresh a held claim (the run's heartbeat, after each section). A claim
    that was released is not taken back."""
    await table(TABLE).aupdate(
        {"generating_at": _now().isoformat()},
        filters={**_own(user_id, guide_id), "generating_at": "not.is.null"},
        prefer_return_minimal=True,
    )


async def arelease_generation(user_id: str, guide_id: str) -> None:
    """Give the claim up when the run ends, however it ends."""
    await table(TABLE).aupdate(
        {"generating_at": None}, filters=_own(user_id, guide_id), prefer_return_minimal=True,
    )


# ── Check answers ────────────────────────────────────────────────────────────


async def arecord_answer(guide: GuideRow, block_id: str, answer: CheckAnswer) -> bool:
    """Store the student's answer to one check block unless it already has
    one. True when this call wrote it, False when the block was answered
    before (only the first answer counts toward mastery).

    The write is a compare-and-set on ``updated_at``, so a double click cannot
    record two first answers: the loser re-reads once and finds the block
    answered. A second lost race means the guide is being written right now:
    ``GuideBusy``."""
    for retry in (True, False):
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
    "CLAIM_STALE_AFTER",
    "LIST_LIMIT",
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
]
