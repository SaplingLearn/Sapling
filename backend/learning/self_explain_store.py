"""Self-explanation prompts' store (spec §13 A139): `learning_self_explanations`,
one row per SERVED prompt (migration 20261108184825). Written 'open' when the
turn carrying the prompt is served, then closed 'replied' (the reply ENCRYPTED,
its length in plaintext) or 'skipped'. A prompt the student moved past stays
'open': never replied. Its only reader is the admin learning-loop report
(learning/self_explain_report.py through routes/admin_analytics.py) — never a
grading, selection or learner-model path: the reply is diagnostic only."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from db.connection import table
from services.encryption import encrypt_if_present

logger = logging.getLogger(__name__)

TABLE = "learning_self_explanations"
#: The admin report's columns (never reply_text: the report needs its length only).
REPORT_COLUMNS = "id,user_id,session_id,course_id,node_id,question_hash,juncture,rung,prompted_at,status,reply_chars"


def _base_row(prompt: dict, *, user_id: str, session_id: str, course_id: str | None) -> dict:
    return {
        "id": prompt["id"],
        "user_id": user_id,
        "session_id": session_id,
        "course_id": course_id or None,
        "node_id": prompt["node_id"],
        "question_hash": prompt.get("question_hash"),
        "juncture": prompt["juncture"],
        "rung": prompt.get("rung"),
        "prompted_at": datetime.fromtimestamp(float(prompt["prompted_at"]), tz=timezone.utc).isoformat(),
    }


def record_prompt(prompt: dict, *, user_id: str, session_id: str, course_id: str | None) -> None:
    """The served prompt, 'open'. Never raises: a failed write logs a WARNING
    and the reply (or skip) writes the whole row instead."""
    try:
        table(TABLE).insert_ignore_duplicates(
            {**_base_row(prompt, user_id=user_id, session_id=session_id, course_id=course_id), "status": "open"},
            on_conflict="id",
        )
    except Exception as exc:
        logger.warning("self-explanation prompt row not written: %s", type(exc).__name__)


def close_prompt(
    prompt: dict,
    *,
    user_id: str,
    session_id: str,
    course_id: str | None,
    reply: str | None,
    closed_at: datetime,
) -> None:
    """Close the prompt: 'replied' with the reply (encrypted, its length in
    characters) or 'skipped'. One upsert of the whole row, so a prompt whose
    serve-time write failed is recorded too. Raises on a failed write (the
    route then answers 503 and the prompt stays open for a retry)."""
    text = (reply or "").strip()
    table(TABLE).upsert(
        {
            **_base_row(prompt, user_id=user_id, session_id=session_id, course_id=course_id),
            "status": "replied" if text else "skipped",
            "closed_at": closed_at.isoformat(),
            "reply_text": encrypt_if_present(text) if text else None,
            "reply_chars": len(text) if text else None,
        },
        on_conflict="id",
    )
