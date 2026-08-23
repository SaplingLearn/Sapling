"""Cheap personalization signals the quiz generator never asked for (#556, H4).

Each of these was already sitting in a table the request path touches, and
none of it reached the prompt:

  * `graph_nodes.times_studied` — in the row `generate_quiz` ALREADY reads,
    just not selected. Zero extra queries.
  * learning velocity — the 14-day computation already exists in
    `graph_service._compute_velocity`; this reuses it rather than writing a
    second one (see #557 for how two copies of one number ends).
  * an in-flight attempt on this concept — trivially available since #542
    added derived status.

The two the first pass deferred now land as well, at the granularity the data
actually supports rather than the one the issue's wording implied:

  * flashcard review state — **COURSE-level, not concept-level.** `flashcards`
    carries no concept link, and `topic` is free text that every writer sets
    to the COURSE name (`routes/flashcards.py` stores `body.topic`; its only
    caller, `Study.tsx`, passes `course.course_name`, and filters its own list
    by that same name). A concept-name match is therefore a permanent zero.
    What IS honest is "how many cards does this student have for this course,
    how many have they reviewed, and how long since the last review" — so
    that is what this reads. The field names, the F6 dimension names and the
    prompt line all say COURSE out loud; a line the model read as
    concept-level would be a lie about the student, which is precisely why
    this half was deferred rather than shipped as specified.
  * tutor recency — days since the last tutor turn that touched THIS concept,
    plus how many tutor sessions this course has had in the last 14 days.
    `messages` has no `user_id` (it is session-scoped), so this is one bounded
    owner-scoped `sessions` read followed by one `messages` read over the ids
    it returned, matching the concept inside `graph_update_json`.

Both of the new ones key on the OFFERING (`flashcards.offering_id`,
`sessions.offering_id`) while the route holds the abstract `course_id`;
`services/academics.py` bridges the two. Passing a course id where an offering
id was expected is exactly how the misconceptions tool read a foreign keyspace
for months (#553), which is why that resolution is one `CourseScope` shared by
both signals rather than an inline filter repeated per signal — and why the
quiz route can resolve it ONCE and inject it, since two of its other
concurrent legs already ask the identical (uncached) question.

Per the issue, these land BEHIND the F6 measurement: every signal records its
own prompt dimension, so `llm_usage.prompt_tokens` can be attributed and the
question "is this worth its tokens?" is answerable with data rather than
taste. That is the point of landing them together.

Contract: never raises, and every read is owner-scoped and bounded. This runs
on the generation request path as one leg of the existing gather; a signal
nobody strictly needs must never be able to fail a quiz.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, NamedTuple

from db.connection import table
from services.academics import user_offering_ids_for_course
from services.tool_signals import Expect, report_empty_result

logger = logging.getLogger(__name__)

#: Cap on the mastery events read for the velocity computation. `_compute_velocity`
#: only looks 14 days back, so an unbounded read is pure transfer cost.
_EVENT_SCAN_LIMIT = 60

#: Cap on the flashcard read, which is already narrowed to ONE course by the
#: `or=` tree in `_flashcards`. The card COUNT is exact regardless (it comes
#: from Content-Range); the cap only bounds how many rows have to cross the
#: wire to tally reviews.
_FLASHCARD_SCAN_LIMIT = 200

#: How far back "recently tutored" looks, matching the velocity window so the
#: two signals in this block describe the same stretch of time.
_TUTOR_WINDOW_DAYS = 14
#: Most recent sessions in that window scanned for concept touches, and the
#: message cap across them. Both are bounds, not filters: the session COUNT is
#: exact regardless (`select_with_count`), and a concept not found inside the
#: scan reports unknown rather than "not recently tutored".
_TUTOR_SESSION_SCAN = 5
_TUTOR_MESSAGE_SCAN = 120


class CourseScope(NamedTuple):
    """How this student's course-keyed rows can be found.

    Two keys because neither alone finds the collection: imported flashcards
    carry an `offering_id`, AI-generated ones never do and take the course
    NAME as their topic.

    `offering_ids=None` means the resolution itself could not be done, and is
    distinct from `[]` — "resolved, and this student has no offering of this
    course", which is a fact and a suspicious one (see `_report_dark_scope`).

    Public because the caller can supply it: `user_offering_ids_for_course` is
    two uncached reads and the `courses` row is a third, all of which the quiz
    generation path already needs elsewhere. Resolving once and passing it in
    is the difference between three reads and six.
    """

    offering_ids: list[str] | None = None
    course_name: str | None = None


class _Flashcards(NamedTuple):
    cards: int | None = None
    reviewed: int | None = None
    last_review_days: int | None = None


class _Tutor(NamedTuple):
    sessions_14d: int | None = None
    concept_days_since: int | None = None


class QuizSignals(NamedTuple):
    """What else we know about this student and this concept.

    Every field is optional in the "we couldn't tell" sense: `None` means the
    read failed or was skipped, and is deliberately distinct from a zero,
    which is a fact about the student.
    """

    times_studied: int | None = None
    velocity_per_day: float | None = None
    in_flight_attempts: int | None = None
    #: COURSE-scoped, never concept-scoped — the name is load-bearing, see the
    #: module docstring.
    flashcards_course_cards: int | None = None
    flashcards_course_reviewed: int | None = None
    flashcards_course_last_review_days: int | None = None
    tutor_course_sessions_14d: int | None = None
    tutor_concept_days_since: int | None = None

    def as_dimensions(self) -> dict[str, Any]:
        """F6: what this block contributed, for token attribution.

        One dimension per FIELD, so the morning can price each signal on its
        own and drop the ones that don't earn their tokens — a signal that
        reaches the prompt without a dimension is one whose cost nobody can
        attribute, which is the thing this issue asked to avoid.
        """
        return {
            "signal_times_studied": self.times_studied,
            "signal_velocity": self.velocity_per_day,
            "signal_in_flight": self.in_flight_attempts,
            "signal_flashcards_course_cards": self.flashcards_course_cards,
            "signal_flashcards_course_reviewed": self.flashcards_course_reviewed,
            "signal_flashcards_course_last_review_days": (
                self.flashcards_course_last_review_days
            ),
            "signal_tutor_course_sessions_14d": self.tutor_course_sessions_14d,
            "signal_tutor_concept_days_since": self.tutor_concept_days_since,
        }


def gather_signals(
    user_id: str,
    concept_node_id: str,
    *,
    times_studied: Any = None,
    course_id: str | None = None,
    concept_name: str = "",
    scope: CourseScope | None = None,
) -> QuizSignals:
    """Collect the cheap signals for one (student, concept).

    `times_studied` is passed IN rather than re-read: `generate_quiz` already
    fetches that row to resolve the concept name and course, so selecting one
    more column costs nothing and a second read would cost a round-trip to
    learn something we were already told. `course_id` and `concept_name` come
    from that same row for the same reason.

    `scope` is the same idea one level up: its three reads are ones the quiz
    route already makes in concurrent legs (see `CourseScope`). Omit it and
    this resolves the scope itself, so every other caller keeps working.

    The `plausible=True` in `_report_dark_scope` rests on a precondition the
    quiz route holds and any future caller must too: it reached here by way of
    an owner-scoped `graph_nodes` read that produced this `course_id`, so the
    student demonstrably has graph data in this course. It is a fact, not a
    guess.

    Without a `course_id` the two course-keyed signals are SKIPPED rather than
    guessed at: there is no other key that finds this student's flashcards or
    tutor sessions, and a graph node with no course really does leave them
    unknowable.
    """
    flashcards = _Flashcards()
    tutor = _Tutor()
    if course_id:
        if scope is None:
            scope = _course_scope(user_id, course_id)
        if scope.offering_ids == []:
            # Resolved, and found none — a fact, and a suspicious one. `None`
            # (couldn't resolve) is a different situation and stays quiet.
            _report_dark_scope(user_id, course_id)
        if scope.offering_ids is not None:
            # BOTH signals need the offering leg, even the flashcard one that
            # can also match on the course name: with the offerings unknown,
            # a topic-only match would silently omit every imported deck and
            # report the remainder as though it were the whole collection.
            # A partial count presented as a fact is worse than no count.
            flashcards = _flashcards(user_id, scope)
            tutor = _tutor_recency(user_id, scope, concept_name)

    return QuizSignals(
        times_studied=_coerce_int(times_studied),
        velocity_per_day=_velocity(concept_node_id),
        in_flight_attempts=_in_flight(user_id, concept_node_id),
        flashcards_course_cards=flashcards.cards,
        flashcards_course_reviewed=flashcards.reviewed,
        flashcards_course_last_review_days=flashcards.last_review_days,
        tutor_course_sessions_14d=tutor.sessions_14d,
        tutor_concept_days_since=tutor.concept_days_since,
    )


def _coerce_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _velocity(concept_node_id: str) -> float | None:
    """Mastery gained per day over the last 14 days, via graph_service's own
    computation — imported, not re-derived."""
    if not concept_node_id:
        return None
    try:
        from services.graph_service import _compute_velocity

        rows = table("node_mastery_events").select(
            "delta,created_at",
            filters={"node_id": f"eq.{concept_node_id}"},
            # desc + limit so the cap keeps the NEWEST events; asc + limit
            # would keep the oldest, which is the opposite of what a 14-day
            # window wants.
            order="created_at.desc",
            limit=_EVENT_SCAN_LIMIT,
        ) or []
        # ...then REVERSED, because `_compute_velocity` derives its window
        # from `recent[0]` as the OLDEST recent event — `get_graph` feeds it
        # `created_at.asc` for exactly that reason. Handing it newest-first
        # collapses `days` to 1 and inflates the result by up to 14x, so the
        # Tree and the quiz prompt would report different velocities for the
        # same concept. That is the "two copies of one number" failure this
        # module cites #557 for, reintroduced through the argument instead of
        # the algorithm.
        return _compute_velocity(list(reversed(rows)))
    except Exception:
        logger.debug("quiz signals: velocity read failed", exc_info=True)
        return None


def _in_flight(user_id: str, concept_node_id: str) -> int | None:
    """Attempts on this concept the student started and has not finished.

    Owner-scoped, and it applies #542's TTL rather than only checking the two
    NULL stamps. `_attempt_status` treats an in-progress row past the TTL as
    abandoned EVEN BEFORE the lazy sweep stamps `abandoned_at` — and the sweep
    runs on the history/list reads, not on generation. So a NULL-only check
    would tell the model about attempts the rest of the app already calls
    abandoned: a student who generated three quizzes last week and never
    opened their history would be told they have three in flight.
    """
    if not user_id or not concept_node_id:
        return None
    try:
        from routes.quiz import _abandon_cutoff

        _rows, total = table("quiz_attempts").select_with_count(
            "id",
            filters={
                "user_id": f"eq.{user_id}",
                "concept_node_id": f"eq.{concept_node_id}",
                "completed_at": "is.null",
                "abandoned_at": "is.null",
                "created_at": f"gte.{_abandon_cutoff().isoformat()}",
            },
            limit=1,
        )
        # The exact count, not `len(rows)` under a cap: a saturated page would
        # report "20" as though it were a fact about the student.
        return total
    except Exception:
        logger.debug("quiz signals: in-flight read failed", exc_info=True)
        return None



def _days_since(stamp: Any) -> int | None:
    """Whole days since a stored timestamp, or None if it can't be read.

    Parsing goes through `routes.quiz._parse_ts` rather than a second
    `fromisoformat` here: it already documents the trap (a naive value from an
    out-of-band write compares against an aware `now()` with a TypeError that
    an `except ValueError` does not catch) and already resolves it by assuming
    UTC. Two copies of that rule is how one of them ends up without the fix.
    """
    from routes.quiz import _parse_ts

    parsed = _parse_ts(stamp)
    if parsed is None:
        return None
    elapsed = (datetime.now(timezone.utc) - parsed).total_seconds()
    # Clamped: clock skew on a just-written row would otherwise produce "-1
    # days ago", which reads as a data bug in the prompt.
    return max(0, int(elapsed // 86400))


def offering_scope(user_id: str, course_id: str | None) -> list[str] | None:
    """This student's offerings of `course_id`, or None if we couldn't tell.

    A never-raising wrapper so the quiz route can resolve the scope ONCE, up
    front, and hand the same answer to every leg that needs it — the signals
    here and `exam_proximity`, which asks the identical uncached question.
    """
    if not course_id:
        return None
    try:
        return list(user_offering_ids_for_course(user_id, course_id) or [])
    except Exception:
        logger.debug("quiz signals: offering resolution failed", exc_info=True)
        return None


def _course_scope(user_id: str, course_id: str) -> CourseScope:
    """Resolve the scope ourselves, for callers that don't supply one."""
    course_name = None
    try:
        rows = table("courses").select(
            "course_name", filters={"id": f"eq.{course_id}"}, limit=1,
        ) or []
        course_name = (rows[0].get("course_name") if rows else None) or None
    except Exception:
        logger.debug("quiz signals: course name read failed", exc_info=True)

    return CourseScope(
        offering_ids=offering_scope(user_id, course_id), course_name=course_name,
    )


def _report_dark_scope(user_id: str, course_id: str) -> None:
    """F5: this student has graph nodes in this course but no offering of it.

    Everything keyed on the offering — both signals here, and the class
    misconceptions on the same key — is therefore silently dark for them,
    which is the #553 keyspace shape rather than "this student has nothing
    yet".

    `plausible=True` rather than letting the helper probe: the caller reached
    this module by way of a `graph_nodes` row it read for this exact user and
    course, so a `HAS_GRAPH` probe scoped to that course can only return what
    the route already saw. Running it would be a guaranteed-True round trip on
    the request path, once per generation, forever. The expectation still
    ships in the event — it is what a rollup reads to know WHY this was
    unexpected.
    """
    report_empty_result(
        "quiz_signals.offerings_for_course",
        user_id=user_id,
        count=0,
        expect=Expect.HAS_GRAPH,
        feature="quiz",
        plausible=True,
        payload={"course_id": course_id},
    )


def _pg_quote(value: str) -> str:
    """Double-quote a value for a PostgREST logic tree.

    Inside `or=(…)` a bare value ends at the first comma or paren, so a course
    named "Ethics, Law and Society" would parse as two broken operands.
    Quoting fixes that; `"` and `\\` inside the value are backslash-escaped,
    as PostgREST's grammar specifies.
    """
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


#: LIKE's own metacharacters, plus its default escape character. Applied
#: BEFORE `_pg_quote`, which then doubles the backslashes this introduces for
#: PostgREST's grammar — the other order would emit a bare `\%` that PostgREST
#: unescapes to `%` and hands to LIKE as a live wildcard.
_LIKE_SPECIALS = str.maketrans({"\\": "\\\\", "%": "\\%", "_": "\\_"})


def _like_literal(value: str) -> str:
    """Escape a value so `ilike` matches it verbatim rather than as a pattern.

    `topic.ilike."Math_101"` would otherwise match "Math-101" and "Math 101"
    too (`_` is LIKE's any-single-character wildcard), and a course with a `%`
    in its name would match half the student's collection. Course names are
    catalog data, so this is defence rather than a live bug — with one gap it
    cannot close: PostgREST rewrites `*` to `%` in like/ilike values itself,
    before Postgres ever sees the pattern, and offers no escape for it.
    """
    return value.translate(_LIKE_SPECIALS)


def _flashcards(user_id: str, scope: CourseScope) -> _Flashcards:
    """This student's flashcards FOR THIS COURSE: how many, how many reviewed,
    and how long since the most recent review.

    Course-level on purpose (module docstring): there is no concept↔card link
    to read, so a concept-scoped version of this would return zero forever.

    The course filter is an `or=` logic tree because the two keys that reach a
    card are different (`offering_id` for imported decks, the course NAME in
    `topic` for generated ones, which carry no offering at all) and NOT
    exclusive — a card can match both, so two counted reads would double-count
    the overlap while a `user_id`-only scan would drag the student's whole
    collection across the wire and cap the count of a course with three cards
    behind a course with four hundred.

    `front`/`back` are column-encrypted and never selected: this signal has no
    use for the text.

    The caller guarantees `scope.offering_ids is not None`: a topic-only tree
    would silently omit every imported deck and report the remainder as the
    whole collection.
    """
    clauses = []
    if scope.offering_ids:
        clauses.append(f"offering_id.in.({','.join(scope.offering_ids)})")
    if scope.course_name:
        # `ilike` over an escaped literal is case-insensitive EQUALITY, which
        # is the drift worth tolerating: both writers store the same
        # `courses.course_name` string this scope was read from.
        clauses.append(
            f"topic.ilike.{_pg_quote(_like_literal(scope.course_name))}"
        )
    if not clauses:
        return _Flashcards()

    try:
        rows, total = table("flashcards").select_with_count(
            "times_reviewed,last_reviewed_at",
            filters={
                "user_id": f"eq.{user_id}",
                "or": f"({','.join(clauses)})",
            },
            # Newest review first, so a truncated page still holds the most
            # recent one and the recency answer survives the cap.
            order="last_reviewed_at.desc.nullslast",
            limit=_FLASHCARD_SCAN_LIMIT,
        )
    except Exception:
        logger.debug("quiz signals: flashcard read failed", exc_info=True)
        return _Flashcards()

    rows = rows or []
    if total > len(rows):
        # The count is exact whatever the cap does — it comes from
        # Content-Range, not from `len(rows)` — but "how many are reviewed"
        # would be capped, and the model would read the cap as a fact. That
        # one goes unknown; the other two do not have to.
        logger.debug(
            "quiz signals: flashcard scan truncated at %s of %s; the count "
            "stands, the reviewed tally does not", len(rows), total,
        )
        return _Flashcards(
            cards=total, last_review_days=_oldest_review(rows),
        )

    return _Flashcards(
        cards=total,
        reviewed=sum(
            1 for r in rows if (_coerce_int(r.get("times_reviewed")) or 0) > 0
        ),
        last_review_days=_oldest_review(rows),
    )


def _oldest_review(rows: list[dict]) -> int | None:
    """Days since the most recent review among these cards, or None if none
    has ever been reviewed — not 0, which would read as "reviewed today".

    `min` rather than "take the first row": the query asks for
    `last_reviewed_at.desc`, but relying on that makes the answer
    wrong-and-silent if the ordering is ever dropped or degraded in transport.
    It is computable here for nothing (`exam_proximity._resolve` makes the
    same call for the same reason).
    """
    ages = [
        d for d in (_days_since(r.get("last_reviewed_at")) for r in rows)
        if d is not None
    ]
    return min(ages) if ages else None


def _tutor_recency(user_id: str, scope: CourseScope, concept_name: str) -> _Tutor:
    """When the tutor last covered THIS concept, and how busy this course has
    been in the tutor lately.

    `messages` is session-scoped and carries no `user_id`, so ownership comes
    from the `sessions` read and the message read is bounded to the ids it
    returned. `content` is column-encrypted and never selected — the concept
    lives in the plaintext `graph_update_json` the tutor's graph tools write.
    """
    if not scope.offering_ids:
        # Sessions key on the offering only; without one there is no way to
        # tell this course's sessions from any other's.
        return _Tutor()

    cutoff = datetime.now(timezone.utc) - timedelta(days=_TUTOR_WINDOW_DAYS)
    try:
        sessions, total = table("sessions").select_with_count(
            "id,started_at",
            filters={
                "user_id": f"eq.{user_id}",
                "offering_id": f"in.({','.join(scope.offering_ids)})",
                "started_at": f"gte.{cutoff.isoformat()}",
            },
            order="started_at.desc",
            limit=_TUTOR_SESSION_SCAN,
        )
    except Exception:
        logger.debug("quiz signals: tutor session read failed", exc_info=True)
        return _Tutor()

    # `total` (the exact count) is what gets reported, not `len(sessions)`:
    # the cap bounds the concept scan below, and reporting it as the session
    # count would hand the model the cap as a fact about the student.
    sessions = sessions or []
    session_ids = [s["id"] for s in sessions if s.get("id")]
    key = _normalize(concept_name)
    if not session_ids or not key:
        return _Tutor(sessions_14d=total)

    try:
        messages = table("messages").select(
            "created_at,graph_update_json",
            filters={
                "session_id": f"in.({','.join(session_ids)})",
                "graph_update_json": "not.is.null",
            },
            order="created_at.desc",
            limit=_TUTOR_MESSAGE_SCAN,
        ) or []
    except Exception:
        # Two reads, two independent facts: losing the concept scan is no
        # reason to discard the count we already have.
        logger.debug("quiz signals: tutor message read failed", exc_info=True)
        return _Tutor(sessions_14d=total)

    for msg in messages:  # newest first — the first match is the most recent
        if _touches_concept(msg.get("graph_update_json"), key):
            return _Tutor(
                sessions_14d=total,
                concept_days_since=_days_since(msg.get("created_at")),
            )
    # Unknown, not "never": the scan is bounded to the most recent sessions in
    # a 14-day window, so a concept last tutored before that looks identical
    # to one never tutored at all.
    return _Tutor(sessions_14d=total)


def _touches_concept(payload: Any, key: str) -> bool:
    """Whether one turn's `graph_update_json` names this concept.

    Shape comes from `chat_stream.merge_graph_updates`: `{"new_nodes": [...],
    "updated_nodes": [...]}`, each item a dict with `concept_name`. The column
    is JSONB, but `end_session`'s own reader tolerates a string shape, so this
    does too.
    """
    if not payload:
        return False
    try:
        if isinstance(payload, str):
            payload = json.loads(payload)
        if not isinstance(payload, dict):
            return False
        for bucket in ("updated_nodes", "new_nodes"):
            for item in payload.get(bucket) or []:
                if isinstance(item, dict) and _normalize(item.get("concept_name")) == key:
                    return True
    except Exception:
        logger.debug("quiz signals: unreadable graph_update_json", exc_info=True)
    return False


def _normalize(name: Any) -> str:
    """graph_service's own case/whitespace fold — imported, not re-derived, so
    a concept the tutor spelled differently still matches the one dedup keyed
    on (the mistake #557 records the cost of)."""
    from services.graph_service import _normalize_concept

    return _normalize_concept(str(name or ""))


def prompt_block(signals: QuizSignals) -> str:
    """One line per signal we actually have, or "" when we have nothing.

    Omission is deliberate: "times studied: unknown" spends tokens to say
    nothing, and a block of unknowns trains the model to ignore the block.
    """
    parts: list[str] = []
    if signals.times_studied is not None:
        parts.append(f"studied {signals.times_studied}x")
    if signals.velocity_per_day:
        # Falsy 0.0 is skipped on purpose: `_compute_velocity` returns 0.0
        # both for "no recent gain" and "not enough data", so reporting it
        # would assert stagnation we cannot distinguish from silence.
        parts.append(f"recent mastery gain ~{signals.velocity_per_day:.3f}/day")
    if signals.in_flight_attempts:
        parts.append(
            f"{signals.in_flight_attempts} unfinished attempt(s) on this concept"
        )
    if signals.flashcards_course_cards:
        # "for this COURSE, not this concept" is not padding. There is no
        # concept↔card link in the schema, so a model that read this as
        # concept-level would infer the student has drilled THIS concept when
        # the cards may be about anything in the course. A zero is skipped:
        # "0 flashcards" steers nothing and costs tokens.
        part = (
            f"{signals.flashcards_course_cards} flashcard(s) for this COURSE "
            f"(not this concept)"
        )
        if signals.flashcards_course_reviewed is not None:
            part += f", {signals.flashcards_course_reviewed} reviewed"
        days = signals.flashcards_course_last_review_days
        if days is not None:
            part += (
                ", last review today" if days == 0
                else f", last review {days}d ago"
            )
        parts.append(part)
    if signals.tutor_concept_days_since is not None:
        # Unlike the counts, a 0 here is the STRONGEST form of this signal —
        # they were tutored on exactly this concept today.
        days = signals.tutor_concept_days_since
        parts.append(
            "tutored on this concept today" if days == 0
            else "last tutored on this concept yesterday" if days == 1
            else f"last tutored on this concept {days} days ago"
        )
    if signals.tutor_course_sessions_14d:
        parts.append(
            f"{signals.tutor_course_sessions_14d} tutor session(s) in this "
            f"course in the last {_TUTOR_WINDOW_DAYS} days"
        )

    if not parts:
        return ""
    return " Student signals: " + "; ".join(parts) + "."
