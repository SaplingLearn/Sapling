"""The class's quiz history: attempts with their questions and answers, the
per-answer responses, and the digest each concept's quizzes left behind.

Questions are made from the concept's flashcards: the front is the question,
the back is the right answer and three other backs of the same deck are the
wrong ones. Stored in the quiz wire shape (``services/quiz/wire.py``), so an
unfinished attempt can be resumed.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from db.local_study_data import clock
from db.local_study_data.placement import Placement
from db.local_study_data.spec import Quiz

_LABELS = "ABCD"
#: ``services.quiz.distractors.DIGEST_SCHEMA_VERSION``, which every digest
#: the app writes carries.
DIGEST_SCHEMA_VERSION = 2
#: How far one quiz moves mastery: this much per point of score above or
#: below half marks.
_DELTA_PER_SCORE = 0.16
#: Questions answered before an unfinished attempt was left.
_ANSWERED = {"open": 3, "abandoned": 1}
#: An unfinished attempt on screen now was started this long ago.
_OPEN_MINUTES_AGO = 14


@dataclass(frozen=True)
class Taken:
    """One attempt, placed in time and in its concept's history."""

    quiz: Quiz
    attempt_id: str
    #: How many quizzes the concept had before this one.
    turn: int
    started_at: datetime
    #: None for an attempt that was never finished.
    done_at: datetime | None = None
    before: float | None = None
    after: float | None = None


# ── When, and what it did to mastery ──────────────────────────────────────────


def _finished_at(place: Placement, quiz: Quiz) -> datetime:
    return clock.moment(place.now, quiz.days_ago, quiz.hour, minutes_before_now=quiz.minutes_ago)


def _started_at(place: Placement, quiz: Quiz) -> datetime:
    if quiz.state == "done":
        return _finished_at(place, quiz) - timedelta(minutes=quiz.minutes)
    return clock.moment(place.now, quiz.days_ago, quiz.hour, minutes_before_now=_OPEN_MINUTES_AGO)


def _mastery_path(score: float, quizzes: list[Quiz]) -> list[tuple[float, float]]:
    """(before, after) for a concept's finished quizzes, oldest first. Walked
    back from today's score, so the last quiz ends exactly on it."""
    path: list[tuple[float, float]] = []
    after = score
    for quiz in reversed(quizzes):
        delta = (quiz.correct / quiz.total - 0.5) * _DELTA_PER_SCORE
        before = round(min(1.0, max(0.0, after - delta)), 4)
        path.append((before, after))
        after = before
    return path[::-1]


def _oldest_first(quizzes: list[Quiz]) -> list[Quiz]:
    return sorted(quizzes, key=lambda quiz: -quiz.days_ago)


def _placed(place: Placement, number: int, quiz: Quiz) -> Taken:
    """One of the class's quizzes, among the others on its concept."""
    history = _oldest_first([q for q in place.data.quizzes if q.concept == quiz.concept])
    finished = [q for q in history if q.state == "done"]
    done = quiz.state == "done"
    score = place.data.concept(quiz.concept).score
    before, after = _mastery_path(score, finished)[finished.index(quiz)] if done else (None, None)
    return Taken(
        quiz=quiz,
        attempt_id=f"{place.prefix}-qa-{number:02d}",
        turn=history.index(quiz),
        started_at=_started_at(place, quiz),
        done_at=_finished_at(place, quiz) if done else None,
        before=before,
        after=after,
    )


def taken(place: Placement) -> list[Taken]:
    """Every attempt of the class, in the order the class lists them."""
    return [_placed(place, number, quiz) for number, quiz in enumerate(place.data.quizzes, start=1)]


def completed(place: Placement) -> list[Taken]:
    return [attempt for attempt in taken(place) if attempt.done_at is not None]


# ── Questions and answers ─────────────────────────────────────────────────────


def _question(place: Placement, attempt: Taken, position: int) -> dict:
    """Question ``position`` of an attempt, in the stored wire shape."""
    quiz = attempt.quiz
    cards = place.data.cards[quiz.concept]
    at = (attempt.turn + position) % len(cards)
    front, back = cards[at]
    options = [cards[(at + step) % len(cards)][1] for step in (1, 2, 3)]
    options.insert((attempt.turn + position) % len(_LABELS), back)
    return {
        "id": position + 1,
        "question": front,
        "options": [
            {"label": label, "text": text, "correct": text == back}
            for label, text in zip(_LABELS, options)
        ],
        "explanation": back,
        "concept_tested": place.data.concept(quiz.concept).name,
        "difficulty": quiz.difficulty,
    }


def questions(place: Placement, attempt: Taken) -> list[dict]:
    return [_question(place, attempt, position) for position in range(attempt.quiz.total)]


def _answered(quiz: Quiz) -> int:
    return quiz.total if quiz.state == "done" else _ANSWERED[quiz.state]


def _missed(attempt: Taken) -> set[int]:
    """The positions answered wrong. Which ones moves with the attempt's
    turn, so a concept's quizzes do not all miss the same question."""
    answered = _answered(attempt.quiz)
    wrong = answered - min(attempt.quiz.correct, answered)
    return {(attempt.turn + step) % answered for step in range(wrong)}


def _picked(question: dict, right: bool) -> int:
    """The index of the option chosen: the right one, or the one after it."""
    correct = next(i for i, option in enumerate(question["options"]) if option["correct"])
    return correct if right else (correct + 1) % len(question["options"])


def _picks(place: Placement, attempt: Taken) -> list[tuple[dict, int, bool]]:
    """(question, chosen option index, whether it was right) per answer."""
    missed = _missed(attempt)
    asked = questions(place, attempt)[: _answered(attempt.quiz)]
    return [
        (question, _picked(question, position not in missed), position not in missed)
        for position, question in enumerate(asked)
    ]


def _answers(place: Placement, attempt: Taken) -> list[dict] | None:
    """``answers_json`` as a submit stores it; None until the attempt is scored."""
    if attempt.done_at is None:
        return None
    return [
        {"question_id": question["id"], "selected_label": question["options"][chosen]["label"]}
        for question, chosen, _ in _picks(place, attempt)
    ]


# ── Rows ──────────────────────────────────────────────────────────────────────


def _abandoned_at(attempt: Taken) -> str | None:
    if attempt.quiz.state != "abandoned":
        return None
    return clock.utc(attempt.started_at + timedelta(hours=25))


def attempts(place: Placement) -> list[dict]:
    rows = []
    for attempt in taken(place):
        quiz, done = attempt.quiz, attempt.done_at is not None
        rows.append({
            "id": attempt.attempt_id,
            "user_id": place.owner_id,
            "concept_node_id": place.node_id(quiz.concept),
            "score": quiz.correct if done else None,
            "total": quiz.total if done else None,
            "difficulty": quiz.difficulty,
            "questions_json": questions(place, attempt),
            "answers_json": _answers(place, attempt),
            "created_at": clock.utc(attempt.started_at),
            "completed_at": clock.utc(attempt.done_at) if done else None,
            "abandoned_at": _abandoned_at(attempt),
            "mastery_before": attempt.before,
            "mastery_after": attempt.after,
        })
    return rows


def _answer_times(place: Placement, attempt: Taken, count: int) -> list[datetime]:
    """When each answer was given: spread evenly over the attempt, and never
    in the future."""
    end = attempt.done_at or attempt.started_at + timedelta(minutes=2 * count + 1)
    step = (min(end, place.now) - attempt.started_at) / (count + 1)
    return [attempt.started_at + step * (position + 1) for position in range(count)]


def responses(place: Placement) -> list[dict]:
    """One ``quiz_responses`` row per answer given."""
    rows = []
    for attempt in taken(place):
        picks = _picks(place, attempt)
        times = _answer_times(place, attempt, len(picks))
        for position, ((_, chosen, right), at) in enumerate(zip(picks, times)):
            rows.append({
                "attempt_id": attempt.attempt_id,
                "question_index": position,
                "selected_index": chosen,
                "is_correct": right,
                "time_ms": 18000 + 6000 * ((position * 3 + attempt.turn) % 5),
                "answered_at": clock.utc(at),
            })
    return rows


def _last_quiz_at(place: Placement, concept_key: str) -> datetime:
    done = [a.done_at for a in completed(place) if a.quiz.concept == concept_key]
    return max(done, default=place.now)


def digests(place: Placement) -> list[dict]:
    """``quiz_context`` rows: what the quizzes on a concept recorded."""
    return [{
        "user_id": place.owner_id,
        "concept_node_id": place.node_id(digest.concept),
        "context_json": {
            "weak_areas": list(digest.weak_areas),
            "common_mistakes": list(digest.common_mistakes),
            "questions_seen_summary": digest.seen,
            "recommended_difficulty": digest.difficulty,
            "notes": "",
            "schema_version": DIGEST_SCHEMA_VERSION,
        },
        "updated_at": clock.utc(_last_quiz_at(place, digest.concept)),
    } for digest in place.data.digests]
