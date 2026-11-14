"""A pre-redesign guide's content as ``GuideContent``.

Before the redesign a guide was ``{exam, due_date, overview, topics[{name,
importance, concepts[]}]}``. Rows in that shape stay in ``study_guides`` with
``format = 1`` and are turned into the new shape when read
(``store._content``); the account seeder and the local rich seed write their
packs' overview and topics through the same function.

Each topic becomes one written section: its importance sentence, then its
concept bullets as a Markdown list. Nothing is known about which graph concept
a topic teaches, so every section is ``unexplored`` and gets an equal share.
"""
from __future__ import annotations

import re
from typing import Any, Mapping

from models.study_guide import GuideContent, Paragraph, ProseItem, Section

#: The title of a guide whose stored content names no exam.
UNTITLED = "Study guide"

_TITLE_MAX = 120
_DECK_MAX = 240
_TAKEAWAYS_MAX = 3
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _deck_and_takeaways(overview: str) -> tuple[str, list[str]]:
    """The overview's leading sentences that fit the deck, and the rest as
    takeaways, so a long overview is split at a sentence instead of clipped."""
    sentences = [s for s in _SENTENCE_END.split(overview) if s]
    deck = sentences[:1]
    for sentence in sentences[1:]:
        if len(" ".join([*deck, sentence])) > _DECK_MAX:
            break
        deck.append(sentence)
    return " ".join(deck), sentences[len(deck):][:_TAKEAWAYS_MAX]


def _weights(count: int) -> list[int]:
    """Equal shares of 100; the first sections take the remainder."""
    base, extra = divmod(100, count)
    return [base + (1 if i < extra else 0) for i in range(count)]


def _passage(section_id: str, importance: str, concepts: list[str]) -> list[ProseItem]:
    paragraphs = [
        Paragraph(text=text)
        for text in (importance, "\n".join(f"- {c}" for c in concepts))
        if text
    ]
    if not paragraphs:
        return []
    return [ProseItem(id=f"{section_id}-i1", paragraphs=paragraphs, summary=importance or None)]


def _section(number: int, weight: int, topic: Mapping[str, Any]) -> Section:
    section_id = f"s{number}"
    importance = _text(topic.get("importance"))
    concepts = topic.get("concepts")
    bullets = [_text(c) for c in concepts if _text(c)] if isinstance(concepts, list) else []
    return Section(
        id=section_id,
        title=(_text(topic.get("name")) or f"Topic {number}")[:_TITLE_MAX],
        weight=weight,
        one_line=importance,
        status="written",
        items=_passage(section_id, importance, bullets),
    )


def content_from_topics(legacy: Mapping[str, Any]) -> GuideContent:
    """``{exam, overview, topics}`` as format-2 content. Tolerant of a missing
    or malformed field: an old row was model output, stored as it came."""
    title = _text(legacy.get("exam"))
    deck, takeaways = _deck_and_takeaways(_text(legacy.get("overview")))
    raw_topics = legacy.get("topics")
    topics = [t for t in raw_topics if isinstance(t, Mapping)] if isinstance(raw_topics, list) else []
    weights = _weights(len(topics)) if topics else []
    return GuideContent(
        title=title[:_TITLE_MAX] or UNTITLED,
        deck=deck,
        takeaways=takeaways,
        sections=[
            _section(number, weight, topic)
            for number, (topic, weight) in enumerate(zip(topics, weights), start=1)
        ],
        scope_label=title[:200],
    )


__all__ = ["UNTITLED", "content_from_topics"]
