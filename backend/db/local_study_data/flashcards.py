"""The class's flashcards and saved sets.

A deck is named for its concept: that is how the Study hub and the Flashcards
page count a concept's cards. A card stores only its latest review (how many
times, the last rating, when), so "review state" is those three columns; the
app keeps no due date.
"""
from __future__ import annotations

from datetime import timedelta

from config import get_mastery_tier
from db.local_study_data import clock
from db.local_study_data.placement import Placement

#: A card's review state: (times reviewed, last rating, days since). Ratings
#: are the review screen's: 1 forgot, 2 hard, 3 easy.
_NEW = (0, None, None)
#: The states a deck's cards cycle through, by how well its concept is known:
#: a mastered deck is all well-worn cards, a struggling one is recent misses
#: and cards not started.
_STATES = {
    "mastered": ((8, 3, 3), (7, 3, 9), (9, 3, 1), (6, 3, 20), (7, 3, 12)),
    "learning": ((5, 3, 2), (2, 2, 1), (3, 2, 4), _NEW, (4, 2, 15), (2, 3, 0)),
    "struggling": ((2, 1, 0), (1, 2, 1), (3, 1, 2), _NEW, (2, 2, 10), (1, 1, 0)),
    "unexplored": (_NEW,),
}
#: Every deck was made this many days ago.
_MADE_DAYS_AGO = 45


def _reviewed_at(place: Placement, days: int | None, number: int) -> str | None:
    if days is None:
        return None
    # Today's reviews happened a few minutes apart, a little while ago.
    return clock.utc(clock.moment(place.now, days, 21, minutes_before_now=20 + 3 * number))


def _deck(place: Placement, deck: int, concept_key: str) -> list[dict]:
    concept = place.data.concept(concept_key)
    states = _STATES[get_mastery_tier(concept.score)]
    made = clock.moment(place.now, _MADE_DAYS_AGO, 12) + timedelta(minutes=10 * deck)
    rows = []
    for number, (front, back) in enumerate(place.data.cards[concept_key]):
        times, rating, days = states[number % len(states)]
        rows.append({
            "id": f"{place.prefix}-fc-{concept_key}-{number + 1}",
            "user_id": place.owner_id,
            "offering_id": place.enrolled.offering_id,
            "topic": concept.name,
            "front": front,
            "back": back,
            "times_reviewed": times,
            "last_rating": rating,
            "last_reviewed_at": _reviewed_at(place, days, number),
            "created_at": clock.utc(made + timedelta(seconds=number)),
        })
    return rows


def cards(place: Placement) -> list[dict]:
    return [row for deck, key in enumerate(place.data.cards) for row in _deck(place, deck, key)]


def card_sets(place: Placement) -> list[dict]:
    rows = []
    for card_set in place.data.card_sets:
        saved = clock.utc(clock.moment(place.now, card_set.days_ago, 15, minutes_before_now=90))
        rows.append({
            "id": f"{place.prefix}-set-{card_set.key}",
            "user_id": place.owner_id,
            "course_id": place.data.course_id,
            "name": card_set.name,
            "concepts": [place.data.concept(key).name for key in card_set.concepts],
            "options": {"only_due": card_set.only_due, "shuffle": card_set.shuffle},
            "exam_id": place.assessment_id(card_set.exam) if card_set.exam else None,
            "created_at": saved,
            "updated_at": saved,
        })
    return rows
