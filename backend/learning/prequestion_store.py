"""The segment prequestion's store (spec §13 A138): `learning_prequestions`,
one row per ANSWERED prequestion (migration 20261108184825). The guess is
encrypted JSON (`guess_json`, NULL exactly for "no idea"); everything else is
ids, the item's isomorph class and timestamps. Its other reader is A76's
re-check rule (learning/misconceptions.py::recheck_after_release): an answered
prequestion is a release of its item's answer for RECHECK_RELEASE_WINDOW_HOURS.

No PKG-06 import (it is reached from misconceptions.py, which may import only
`recent_evidence` from that layer). Reads never raise: a failed read answers
None, and the caller decides nothing from it (A76's own rule for its journal)."""

from __future__ import annotations

import logging
from datetime import datetime

from db.connection import table
from services.encryption import encrypt_json

logger = logging.getLogger(__name__)

_TABLE = "learning_prequestions"


def store_answer(
    *,
    user_id: str,
    session_id: str,
    course_id: str | None,
    node_id: str,
    item,
    no_idea: bool,
    guess: dict | None,
    posed_at: datetime,
) -> None:
    """Record the answered prequestion (raises on a failed write: the answer
    route then answers 503 and records nothing else). Idempotent per (student,
    session, concept): a retried request inserts nothing new."""
    row = {
        "user_id": user_id,
        "session_id": session_id,
        "course_id": course_id or None,
        "node_id": node_id,
        "check_item_id": getattr(item, "id", None),
        "question_hash": item.question_hash,
        "format": item.format,
        "difficulty": int(item.difficulty),
        "no_idea": bool(no_idea),
        "guess_json": None if no_idea else encrypt_json(guess or {}),
        "posed_at": posed_at.isoformat(),
    }
    table(_TABLE).insert_ignore_duplicates(row, on_conflict="user_id,session_id,node_id")


def _ts(value) -> datetime | None:
    try:
        ts = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return ts


def releases(user_id: str, node_id: str, *, since: datetime) -> list[dict] | None:
    """A76: the student's answered prequestions on `node_id` since `since`,
    oldest first, each {shape: (format, difficulty), at: datetime} — one
    owner-scoped indexed read. None when the read failed (never raises)."""
    try:
        rows = table(_TABLE).select(
            "format,difficulty,answered_at",
            filters={
                "user_id": f"eq.{user_id}",
                "node_id": f"eq.{node_id}",
                "answered_at": f"gte.{since.isoformat()}",
            },
            order="answered_at.asc",
        )
    except Exception as exc:
        logger.warning("prequestion releases read failed: %s", type(exc).__name__)
        return None
    out = []
    for row in rows or []:
        at = _ts(row.get("answered_at"))
        if at is not None:
            out.append({"shape": (row.get("format"), row.get("difficulty")), "at": at})
    return out


def evidence_since(user_id: str, node_id: str, at: datetime) -> bool | None:
    """A76's "next item" rule across sessions: whether the student has any
    evidence row on the node journaled after `at` (one owner-scoped read,
    limit 1). None when the read failed (never raises)."""
    try:
        rows = table("node_mastery_events").select(
            "id,graph_nodes!inner(user_id)",
            filters={
                "graph_nodes.user_id": f"eq.{user_id}",
                "node_id": f"eq.{node_id}",
                "event_type": "eq.evidence",
                "created_at": f"gt.{at.isoformat()}",
            },
            limit=1,
        )
    except Exception as exc:
        logger.warning("prequestion evidence-since read failed: %s", type(exc).__name__)
        return None
    return bool(rows)
