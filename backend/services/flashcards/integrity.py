"""The learning loop's integrity guard around the flashcard generators
(spec §13 A125; moved out of routes/flashcards.py with the #118 layout,
spec §13 A149).

Every generator hands the flashcard model text the student sent with the
request (a topic, pasted notes, a paragraph, card texts, a photographed page),
and every card it returns is a question with its answer. The integrity guard
(services/integrity_guard.py) therefore runs around each: text quoting one of
the student's posed checks never reaches the model (the route answers 409),
and a card stating one's key is withheld. A library document is the student's
stored course material, not request text (the loop treats course material as
open-book), so the library_doc source is not guarded.

The route evaluates the learning-loop gate (owner decision 00) and maps a
refusal to its 409; nothing here imports fastapi.
"""
from __future__ import annotations

import re

from services import integrity_guard
from services.request_context import current_request_id

_CLOZE_BLANK = re.compile(r"\{\{.*?\}\}")


def open_card_guard(user_id: str, texts, *, active: bool) -> integrity_guard.Guard:
    """One read of the student's posed items and the pre-call check of the
    text they sent (`guard.refused` when it quotes one). `active` is the
    route-entry gate: off with the loop."""
    return integrity_guard.open_guard(
        user_id,
        surface="flashcards",
        texts=list(texts),
        active=active,
        request_id=current_request_id(),
    )


def _card_text(card: dict) -> str:
    """A card as the student reads it: a cloze front gets its blank filled
    with the back (so a cloze of the student's own sentence reads as that
    sentence — the served scan's provenance rule then sees the copy)."""
    front, back = str(card.get("front") or ""), str(card.get("back") or "")
    if _CLOZE_BLANK.search(front):
        return _CLOZE_BLANK.sub(lambda _m: back, front, count=1)
    return f"{front}\n{back}"


def screen_cards(guard: integrity_guard.Guard, cards: list) -> tuple[list, int]:
    """The cards the guard lets through and how many it withheld (each stating
    a posed check's key; help is recorded on those checks)."""
    keep = guard.screen_each([_card_text(c) for c in cards])
    kept = [c for c, ok in zip(cards, keep) if ok]
    return kept, len(cards) - len(kept)


def cleanup_withheld(guard: integrity_guard.Guard, cleaned: list) -> int:
    """How many cleaned cards state a posed check's key (0: serve the
    cleanup)."""
    return guard.screen_each([_card_text(c) for c in cleaned]).count(False)
