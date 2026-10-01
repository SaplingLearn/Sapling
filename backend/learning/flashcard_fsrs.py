"""The flashcard FSRS rating path (PKG-11; moved here and given a retention
target by PKG-12's reopen).

`flashcard_fsrs_update` is the one place a self-rated flashcard's FSRS state
moves: `routes/flashcards.py::rate_card` (loop path) and `learning/review.py`
(the daily review queue) both call it, so both surfaces run the same FSRS
update. They differ in the retention target only: `rate_card` schedules at
`FSRS_RETENTION_DEFAULT`, the review queue at its own target
(`review.retention_target`: higher in an exam window, lower for a large set),
so the same rating can yield a different `due_at` in the two surfaces. Pure: no db, no clock — the caller passes `now` and
writes the returned columns itself.

ADAPTER around learning.fsrs.next_state/interval (HANDOFF-02:
`next_state(d, s, rating, days_since, *, same_day, mc_unassisted)`) — if
PKG-02's signature changes, change THIS function only. A first rating passes
`None, None` and PKG-02 seeds D0(G)/S0(G). A review less than one day after
the last takes FSRS's same-day branch, the rule PKG-03's
graph_service._fsrs_after uses. A flashcard is never an MC check, so the MC
stability cap never applies. Errors propagate: the caller has not written the
legacy columns yet, so the card stays unchanged.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from learning.fsrs import Rating, interval, next_state
from learning.params import FLASHCARD_RATING_TO_FSRS, FSRS_RETENTION_DEFAULT
from services.timestamps import parse_ts

_ONE_DAY = timedelta(days=1)

#: Every column `flashcard_fsrs_update` returns (the legacy three + FSRS five).
FLASHCARD_FSRS_COLUMNS = (
    "fsrs_d",
    "fsrs_s",
    "due_at",
    "reps",
    "lapses",
    "times_reviewed",
    "last_rating",
    "last_reviewed_at",
)


def fsrs_rating_for(rating: int) -> int:
    """The FSRS grade for a legacy 1/2/3 self-rating (params.FLASHCARD_RATING_TO_FSRS,
    §13 A6). Anything else — 4, 0, a bool, a string — raises ValueError."""
    if isinstance(rating, bool) or not isinstance(rating, int):
        raise ValueError(f"flashcard rating must be one of 1, 2, 3, got {rating!r}")
    fsrs_rating = FLASHCARD_RATING_TO_FSRS.get(rating)
    if fsrs_rating is None:
        raise ValueError(f"flashcard rating must be one of 1, 2, 3, got {rating!r}")
    return fsrs_rating


def flashcard_fsrs_update(
    card_row: dict,
    rating: int,
    *,
    now: datetime,
    retention: float = FSRS_RETENTION_DEFAULT,
) -> dict:
    """The columns one self-rating writes: `fsrs_d, fsrs_s, due_at (ISO), reps,
    lapses, times_reviewed, last_rating, last_reviewed_at (ISO)`.

    `card_row` needs `last_reviewed_at, fsrs_d, fsrs_s, reps, lapses,
    times_reviewed` (missing counters count as 0). `rating` is the legacy 1/2/3
    (`last_rating` stores it as given); `due_at` is `now + interval(retention, S')`.
    """
    fsrs_rating = fsrs_rating_for(rating)
    last = parse_ts(card_row.get("last_reviewed_at"))
    days_since, same_day = 0.0, False
    if last is not None:
        days_since = max(0.0, (now - last) / _ONE_DAY)
        same_day = now - last < _ONE_DAY
    d_new, s_new = next_state(
        card_row.get("fsrs_d"), card_row.get("fsrs_s"), fsrs_rating, days_since, same_day=same_day
    )
    due_at = now + timedelta(days=interval(retention, s_new))
    return {
        "fsrs_d": d_new,
        "fsrs_s": s_new,
        "due_at": due_at.isoformat(),
        "reps": (card_row.get("reps") or 0) + 1,
        "lapses": (card_row.get("lapses") or 0) + (1 if fsrs_rating == Rating.AGAIN else 0),
        "times_reviewed": (card_row.get("times_reviewed") or 0) + 1,
        "last_rating": rating,
        "last_reviewed_at": now.isoformat(),
    }
