"""Whether a tutor start's topic is a note's title (docs/safety/crisis-support.md).

Send to tutor (routes/notes.py) opens /learn with the note's title as the
topic, and the frontend names the note (`from_note_id`) when the student
starts on that topic unchanged. Such a topic is material the student STORED,
not something they typed now, so a crisis match in it shows the card beside
the session (`crisis_support.alongside`) instead of blocking the start; the
student already got the card beside Send to tutor itself.

The id is only a claim. It counts only when it names one of the student's own
notes and the topic is exactly what Send to tutor derives from that note's
title (`notes_service.tutor_topic`); anything else is screened as typed.
"""
from __future__ import annotations

import logging

from models import StartSessionBody
from services.notes_service import get_note, tutor_topic

logger = logging.getLogger(__name__)


async def topic_is_note_title(body: StartSessionBody) -> bool:
    """True when `body.topic` is the tutor topic of the student's own note
    `body.from_note_id`. Read only after the crisis screen matched the topic
    (which authenticated the caller as `body.user_id`), so an ordinary start
    never pays for the read. Every doubt is False (no id, another student's or
    a deleted note, an edited topic, a failed read): the topic then blocks as
    typed, never the other way round."""
    if not body.from_note_id:
        return False
    try:
        note = await get_note(note_id=body.from_note_id, user_id=body.user_id)
    except Exception:  # noqa: BLE001 — a failed read means "not shown to be the note's"
        logger.warning("crisis support: a tutor start's note could not be read; its topic is screened as typed")
        return False
    return bool(note) and body.topic.strip() == tutor_topic(note)
