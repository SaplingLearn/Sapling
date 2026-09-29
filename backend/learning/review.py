"""The daily review queue (learning-loop PKG-12; spec §3.2, §5, §6; §13 A16,
A20, A22, A23, A33, A38).

Due flashcards (facts) and due concepts (each mapped to one check item) are
merged, ordered by the DASH rule (`fsrs.order_due`: |R − REVIEW_ORDER_THRESHOLD|
ascending) and cut at the daily budget. A concept's item never comes from the
student's seen/revealed sets or the concept's post-test reserve (A23); when that
leaves nothing, only revealed items and the reserve are excluded; still nothing
→ the concept is counted `unservable`. At the tutor hard budget level the route
passes `pause_novice=True` and novice-band concepts are held back (`paused`);
flashcards and develop/profic concepts keep being served (A20).

Grading has ONE path per kind. A check item goes through PKG-05's
`grade_answer` (A16, invariant 19) and its one Evidence dict is persisted,
unchanged, by ONE `apply_graph_update` call carrying the review's retention
target; an `unavailable` or `refused` (A33) outcome writes nothing for either
outcome (invariant 28). A flashcard goes through PKG-11's
`flashcard_fsrs_update` (the same helper `rate_card` uses).

Successive relearning (spec §3.2 `SR_INITIAL_CRITERION`, `SR_RELEARN_SESSIONS`)
lives in the review session's `sessions.loop_state` (a `sessions` row with
mode 'review', one per user, course and UTC day): `loop_state["sr"][key]` holds
the session counters (`correct`/`target`/`served`) and HANDOFF-02's
`fsrs.SuccessiveRelearning` machine (`relearning`), seeded from the stage
derived off `learner_state.streak_unassisted` / the card's `reps`. Every
loop_state write goes through `loop_state_store.update_loop_state` (A38
06(q) compare-and-set): each mutation re-applies this call's own delta to the
freshly loaded state, and a `LoopStateConflict` propagates (the route answers
409), never a silent loss.

A served item is opened for answering in loop_state["open"][key]; an answer
first takes a claim on it (`claim_item`, PKG-07's grading-claim discipline,
§13 A52), so a double submit is graded and written at most once.

Imported only by routes/learn_loop.py (the /review/* routes), behind the loop gate.
"""

from __future__ import annotations

import copy
import logging
import math
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, Field

from agents.tools.check import CheckAnswer, grade_answer  # PKG-05 — the ONLY grading path
from db.connection import table
from learning import fsrs, loop_state_store
from learning.bkt import band, decayed_p
from learning.checks import is_servable, posttest_reserve_hash, select_item
from learning.flashcard_fsrs import flashcard_fsrs_update, fsrs_rating_for  # PKG-11
from learning.loop_state_store import update_loop_state
from learning.misconceptions import recheck_after_release  # PKG-10 (A76)
from learning.params import (
    FSRS_S0_GOOD,
    LOOP_GRADING_CLAIM_STALE_S,
    REVIEW_DAILY_BUDGET_MIN,
    REVIEW_DIFFICULTY_BY_BAND,
    REVIEW_FORMAT_BY_BAND,
    REVIEW_SECONDS_PER_CHECK,
    REVIEW_SECONDS_PER_FLASHCARD,
    SR_INITIAL_CRITERION,
    SR_RELEARN_SESSION_TARGET,
    SR_RELEARN_SESSIONS,
)
from services.academics import resolve_offering, user_offering_ids_for_course
from services.achievement_service import check_achievements
from services.check_item_service import list_items
from services.encryption import decrypt_if_present
from services.events_service import log_event
from services.exam_proximity import days_until_next_exam
from services.graph_service import _normalize_concept, apply_graph_update
from services.session_modes import REVIEW_MODE
from services.timestamps import parse_ts

logger = logging.getLogger("sapling.learning.review")

Kind = Literal["flashcard", "check"]
Stage = Literal["acquire", "relearn", "done"]

_ONE_DAY = timedelta(days=1)
_DAILY_BUDGET_S = int(timedelta(minutes=REVIEW_DAILY_BUDGET_MIN).total_seconds())
_REVIEW_TOPIC = "Daily review"
_REVIEW_MODE = REVIEW_MODE
_FLASHCARD_KEY_PREFIX = "fc:"
_KINDS: tuple[Kind, ...] = ("flashcard", "check")
_CARD_COLUMNS = "id,topic,offering_id,fsrs_d,fsrs_s,due_at,reps,lapses,last_rating,last_reviewed_at"
#: What a served / graded card needs besides the queue's columns: the text
#: (serve) and the counter flashcard_fsrs_update advances (grade).
_CARD_ROW_COLUMNS = _CARD_COLUMNS + ",times_reviewed,front,back"
_CONCEPT_COLUMNS = "node_id,p_known,streak_unassisted,fsrs_d,fsrs_s,fsrs_last_review_at,fsrs_due_at"
_PHASE_TO_STAGE: dict[str, Stage] = {
    fsrs.SR_ACQUISITION: "acquire",
    fsrs.SR_RELEARN: "relearn",
    fsrs.SR_DONE: "done",
}


# ── A23 readers (PKG-07) ──────────────────────────────────────────────────────


def seen_hashes(user_id: str) -> set[str]:
    """The student's seen check items (A23). ONE definition: PKG-07's
    `loop_state_store.seen_hashes` (read once per queue build, only when a
    concept is due)."""
    return set(loop_state_store.seen_hashes(user_id))


def revealed_hashes(user_id: str) -> set[str]:
    """The student's revealed check items (A23): PKG-07's
    `loop_state_store.revealed_hashes` (see seen_hashes)."""
    return set(loop_state_store.revealed_hashes(user_id))


# ── models ────────────────────────────────────────────────────────────────────


class ReviewItem(BaseModel):
    kind: Kind
    id: str  # check item id / flashcard id
    node_id: str | None = None  # checks: the student's graph_nodes.id (A2)
    course_id: str | None = None
    question_hash: str | None = None
    due_at: datetime | None = None
    last_review_at: datetime | None = None
    r: float
    stability: float
    format: Literal["free", "mc_reason"] | None = None
    difficulty: int | None = None
    cost_s: int
    sr_stage: Stage
    sr_target: int
    sr_count: int = 0  # the derivation's input: streak_unassisted / reps (0 after a lapse)
    concept_name: str | None = None
    topic: str | None = None


class ReviewOutcome(BaseModel):
    correct: bool | None = None
    hint: str | None = None
    next_due_at: str | None = None
    rating: int | None = None
    sr: dict = Field(default_factory=dict)
    unavailable: bool = False
    refused: bool = False  # A33: ask for the answer in the student's own words


# ── retention, SR stage, session ──────────────────────────────────────────────


def retention_target(n_scheduled_concepts: int, exam_within_days: int | None) -> float:
    """Spec §3.2 / A7: exam window beats large set beats the default. PKG-02's
    `fsrs.retention_target` owns the rule; this is the review-facing name."""
    return fsrs.retention_target(n_scheduled_concepts, exam_within_days)


def sr_stage_for_concept(streak_unassisted: int) -> tuple[Stage, int]:
    """(stage, this session's target) derived from learner_state.streak_unassisted."""
    if streak_unassisted < SR_INITIAL_CRITERION:
        return "acquire", SR_INITIAL_CRITERION
    if streak_unassisted < SR_INITIAL_CRITERION + SR_RELEARN_SESSIONS:
        return "relearn", SR_RELEARN_SESSION_TARGET
    return "done", SR_RELEARN_SESSION_TARGET


def sr_stage_for_flashcard(reps: int, last_rating: int | None) -> tuple[Stage, int]:
    """(stage, target) from the card's reps; a lapse (legacy rating 1 = forgot)
    restarts acquisition. `reps` never decreases, so a lapse mid-relearn is
    visible only through `last_rating` (HANDOFF-12 Open question)."""
    if reps < SR_INITIAL_CRITERION or last_rating == fsrs.Rating.AGAIN:
        return "acquire", SR_INITIAL_CRITERION
    if reps < SR_INITIAL_CRITERION + SR_RELEARN_SESSIONS:
        return "relearn", SR_RELEARN_SESSION_TARGET
    return "done", SR_RELEARN_SESSION_TARGET


def review_session_id(user_id: str, course_id: str | None, now: datetime) -> str:
    """One review session per user, course and UTC day."""
    day = now.date().isoformat()
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"sapling:review:{user_id}:{course_id or '-'}:{day}"))


def _session_view(doc: dict | None = None) -> dict:
    """{"sr": …, "review": {"spent_s", "served_hashes", …}} off a stored loop_state."""
    doc = doc or {}
    review = dict(doc.get("review") or {})
    review.setdefault("spent_s", 0)
    review.setdefault("served_hashes", [])
    return {"sr": dict(doc.get("sr") or {}), "review": review}


def _read_session(sid: str, user_id: str) -> list[dict]:
    return (
        table("sessions").select(
            "id,user_id,loop_state", filters={"id": f"eq.{sid}", "user_id": f"eq.{user_id}"}
        )
        or []
    )


def load_or_create_review_session(
    user_id: str, course_id: str | None, now: datetime
) -> tuple[str, dict]:
    """(session id, {"sr": …, "review": …}) for today's review session.

    Insert-if-missing, never upsert (A11), mirroring routes/learn.py's lazy
    insert and its `session.started` event (topic as content=, never payload).
    A concurrent first poll that loses the insert re-reads the winner's row.
    """
    sid = review_session_id(user_id, course_id, now)
    rows = _read_session(sid, user_id)
    if not rows:
        data: dict[str, Any] = {"id": sid, "user_id": user_id}
        offering_id = resolve_offering(course_id) if course_id else None
        if offering_id:
            data["offering_id"] = offering_id
        data.update({"mode": _REVIEW_MODE, "topic": _REVIEW_TOPIC, "name": _REVIEW_TOPIC})
        try:
            table("sessions").insert(data)
        except Exception:
            rows = _read_session(sid, user_id)
            if not rows:
                raise
        else:
            log_event(  # never session.started: a review session is not a tutor session
                "review.session_started",
                category="usage",
                user_id=user_id,
                payload={"session_id": sid, "offering_id": offering_id},
            )
            return sid, _session_view()
    row = rows[0]
    if row.get("user_id") not in (None, user_id):
        raise PermissionError(f"review session {sid} belongs to another user")
    return sid, _session_view(row.get("loop_state"))


def peek_review_session(user_id: str, course_id: str | None, now: datetime) -> dict:
    """Today's review-session view WITHOUT creating the row (a read-only
    surface such as `/review/summary` never inserts a session)."""
    rows = _read_session(review_session_id(user_id, course_id, now), user_id)
    if not rows:
        return _session_view()
    if rows[0].get("user_id") not in (None, user_id):
        raise PermissionError("review session belongs to another user")
    return _session_view(rows[0].get("loop_state"))


def _scheduled_concept_count(user_id: str, course_id: str | None) -> int:
    rows = table("learner_state").select(
        "node_id", filters={"user_id": f"eq.{user_id}", "fsrs_due_at": "not.is.null"}
    )
    node_ids = {r["node_id"] for r in rows or [] if r.get("node_id")}
    if not course_id or not node_ids:
        return len(node_ids)
    nodes = table("graph_nodes").select(
        "id", filters={"user_id": f"eq.{user_id}", "course_id": f"eq.{course_id}"}
    )
    return len(node_ids & {n["id"] for n in nodes or []})


def review_retention(user_id: str, course_id: str | None) -> float:
    """Rule 2: `retention_target` over the course's scheduled concepts and the
    days until its next exam (no exam lookup without a course)."""
    exam = days_until_next_exam(user_id, course_id) if course_id else None
    return retention_target(_scheduled_concept_count(user_id, course_id), exam)


# ── queue ─────────────────────────────────────────────────────────────────────


def sr_key(item: ReviewItem) -> str:
    """The item's key in loop_state["sr"] and loop_state["open"]: the student's
    node for a concept check, "fc:<card id>" for a flashcard."""
    return item.node_id if item.kind == "check" else _FLASHCARD_KEY_PREFIX + item.id


def _elapsed_days(last: datetime | None, now: datetime) -> float:
    return 0.0 if last is None else max(0.0, (now - last) / _ONE_DAY)


def _retrievability(stability: float, last: datetime | None, now: datetime) -> float:
    """fsrs.item_retrievability over the same mapping _order sorts on."""
    return fsrs.item_retrievability({"fsrs_s": stability, "fsrs_last_review_at": last}, now)


class InvalidStability(ValueError):
    """A stored `fsrs_s` that is not a finite positive number (0, negative, NaN,
    ±inf, non-numeric). The queue skips the row with a WARNING; the answer route
    answers 422. Migration 20260929111535_learning_fsrs_stability_positive
    forbids new ones."""


def _stability(raw: Any) -> float:
    """A row's FSRS stability. `None` (never scheduled) is FSRS_S0_GOOD; a finite
    positive number is itself; anything else raises InvalidStability — a stored 0
    never silently becomes S0."""
    if raw is None:
        return FSRS_S0_GOOD
    if isinstance(raw, bool):
        raise InvalidStability(f"fsrs_s={raw!r}")
    try:
        s = float(raw)
    except (TypeError, ValueError):
        raise InvalidStability(f"fsrs_s={raw!r}") from None
    if not math.isfinite(s) or s <= 0:
        raise InvalidStability(f"fsrs_s={raw!r}")
    return s


def _due_flashcards(user_id: str, course_id: str | None, now: datetime) -> list[ReviewItem]:
    """Cards due now: `due_at` null (never scheduled — it enters the pool at
    S0, elapsed 0) or `due_at <= now`, filtered in SQL. A row with an invalid
    stability is skipped and logged."""
    rows = (
        table("flashcards").select(
            _CARD_COLUMNS,
            filters={
                "user_id": f"eq.{user_id}",
                "or": f"(due_at.is.null,due_at.lte.{now.isoformat()})",
            },
        )
        or []
    )
    due = []
    for row in rows:
        due_at = parse_ts(row.get("due_at"))
        if due_at is None or due_at <= now:
            due.append(row)
    if course_id and due:  # get_flashcards' rule: term-less cards are never stranded
        offerings = set(user_offering_ids_for_course(user_id, course_id))
        due = [r for r in due if r.get("offering_id") is None or r["offering_id"] in offerings]
    items = []
    for row in due:
        try:
            items.append(item_for_card(row, course_id, now))
        except InvalidStability as exc:
            logger.warning("review: skipped flashcard %s (%s)", row.get("id"), exc)
    return items


def item_for_card(row: dict, course_id: str | None, now: datetime) -> ReviewItem:
    """The ReviewItem of one `flashcards` row — the queue's, and `/review/answer`'s
    (which re-loads the row by id: the client never supplies its state).
    InvalidStability on a bad `fsrs_s`."""
    last = parse_ts(row.get("last_reviewed_at"))
    stability = _stability(row.get("fsrs_s"))
    reps = row.get("reps") or 0
    last_rating = row.get("last_rating")
    stage, target = sr_stage_for_flashcard(reps, last_rating)
    return ReviewItem(
        kind="flashcard",
        id=row["id"],
        course_id=course_id,
        due_at=parse_ts(row.get("due_at")),
        last_review_at=last,
        r=_retrievability(stability, last, now),
        stability=stability,
        cost_s=REVIEW_SECONDS_PER_FLASHCARD,
        sr_stage=stage,
        sr_target=target,
        sr_count=0 if last_rating == fsrs.Rating.AGAIN else reps,
        topic=row.get("topic"),
    )


def load_card(user_id: str, card_id: str) -> dict | None:
    """The student's own `flashcards` row by id (both filters), or None."""
    rows = table("flashcards").select(
        _CARD_ROW_COLUMNS, filters={"id": f"eq.{card_id}", "user_id": f"eq.{user_id}"}
    )
    return rows[0] if rows else None


def item_for_check(user_id: str, check_item, node_id: str, now: datetime) -> ReviewItem:
    """The ReviewItem of a check item answered on `/review/answer`: its SR stage
    and R come from the student's `learner_state` row for `node_id` (resolved
    server-side, A2), never from the client. One read. InvalidStability on a
    bad `fsrs_s`."""
    rows = table("learner_state").select(
        _CONCEPT_COLUMNS, filters={"user_id": f"eq.{user_id}", "node_id": f"eq.{node_id}"}
    )
    row = rows[0] if rows else {}
    last = parse_ts(row.get("fsrs_last_review_at"))
    stability = _stability(row.get("fsrs_s"))
    streak = row.get("streak_unassisted") or 0
    stage, target = sr_stage_for_concept(streak)
    return ReviewItem(
        kind="check",
        id=check_item.id,
        node_id=node_id,
        course_id=check_item.course_id,
        question_hash=check_item.question_hash,
        due_at=parse_ts(row.get("fsrs_due_at")),
        last_review_at=last,
        r=_retrievability(stability, last, now),
        stability=stability,
        format=check_item.format,
        difficulty=check_item.difficulty,
        cost_s=REVIEW_SECONDS_PER_CHECK,
        sr_stage=stage,
        sr_target=target,
        sr_count=streak,
    )


def _formats_for(band_name: str) -> list[str]:
    """The band's format, then the other REVIEW_FORMAT_BY_BAND value (rule 1)."""
    primary = REVIEW_FORMAT_BY_BAND[band_name]
    return [primary, *sorted(set(REVIEW_FORMAT_BY_BAND.values()) - {primary})]


def _pick_item(pool, band_name: str, strict: set[str], fallback: set[str]):
    """Rule 1 / A23: the strict exclusions in every format first; only when
    that finds nothing, the fallback exclusions. select_item itself falls back
    to the nearest difficulty and never returns an item without a final answer
    (A34)."""
    difficulty = REVIEW_DIFFICULTY_BY_BAND[band_name]
    for exclude in (strict, fallback):
        for fmt in _formats_for(band_name):
            item = select_item(pool, format=fmt, difficulty=difficulty, exclude_hashes=exclude)
            if item is not None:
                return item
    return None


@dataclass
class _Concept:
    """A due concept before its check item is chosen (the item read is deferred
    until the concept is inside the budget)."""

    row: dict
    node: dict
    last_review_at: datetime | None
    stability: float
    band: str


def _pause_check(pause_novice: bool | Callable[[], bool]) -> Callable[[], bool]:
    """`pause_novice` as a once-evaluated thunk: the route passes a callable, so
    the tutor-budget read happens only when a novice concept is actually due."""
    if not callable(pause_novice):
        return lambda: bool(pause_novice)
    cache: list[bool] = []

    def read() -> bool:
        if not cache:
            cache.append(bool(pause_novice()))
        return cache[0]

    return read


def _due_concepts(
    user_id: str,
    course_id: str | None,
    now: datetime,
    *,
    pause: Callable[[], bool],
    stats: dict,
) -> list[_Concept]:
    rows = table("learner_state").select(
        _CONCEPT_COLUMNS,
        filters={"user_id": f"eq.{user_id}", "fsrs_due_at": f"lte.{now.isoformat()}"},
    )
    rows = [r for r in rows or [] if r.get("fsrs_due_at") is not None]
    if not rows:
        return []
    ids = ",".join(r["node_id"] for r in rows)
    nodes = table("graph_nodes").select(
        "id,course_id,concept_name", filters={"user_id": f"eq.{user_id}", "id": f"in.({ids})"}
    )
    by_id = {
        n["id"]: n for n in nodes or [] if course_id is None or n.get("course_id") == course_id
    }
    concepts = []
    for row in rows:
        node = by_id.get(row["node_id"])
        if node is None:
            continue
        try:
            stability = _stability(row.get("fsrs_s"))
        except InvalidStability as exc:
            logger.warning("review: skipped concept node=%s (%s)", node["id"], exc)
            continue
        last = parse_ts(row.get("fsrs_last_review_at"))
        band_name = band(decayed_p(row.get("p_known") or 0.0, _elapsed_days(last, now), stability))
        if band_name == "novice" and pause():  # A20: before any item read
            stats["paused"] += 1
            logger.info("review: paused novice concept node=%s (tutor hard level)", node["id"])
            continue
        concepts.append(_Concept(row, node, last, stability, band_name))
    return concepts


def open_item_ids(loop_state: dict | None, now: datetime) -> dict[str, str]:
    """{key: item_id} of every served item still awaiting its answer: never
    graded, and not left under a claim older than LOOP_GRADING_CLAIM_STALE_S. The
    queue re-serves exactly these (a refresh never shops for another item)."""
    now_s = now.timestamp()
    out = {}
    for key, entry in ((loop_state or {}).get("open") or {}).items():
        if not isinstance(entry, dict) or entry.get("graded_at") is not None:
            continue
        if entry.get("claim") and not _live_claim(entry, now_s):
            continue
        if entry.get("item_id"):
            out[key] = entry["item_id"]
    return out


def is_open(loop_state: dict | None, item: ReviewItem, now: datetime) -> bool:
    """`item` is the one this session served for its key and it awaits its answer
    (re-serving it writes nothing and emits nothing)."""
    return open_item_ids(loop_state, now).get(sr_key(item)) == item.id


class _Selector:
    """Chooses a due concept's check item (rule 1, A23) — or re-uses the item the
    session already opened for it, while that item is still neither seen (evidence
    from another surface: a review's own answer closes its open entry) nor revealed
    (a wrong attempt in the tutor loop, an H4 sibling). The seen/revealed reads
    happen once, on the first concept that needs an item."""

    def __init__(self, user_id: str, served_today: set[str], opened: dict[str, str]):
        self.user_id, self.served_today, self.opened = user_id, served_today, opened
        self.history: dict[str, set[str]] = {}

    def item(self, c: _Concept, now: datetime) -> ReviewItem | None:
        node = c.node
        pool = list_items(node["course_id"], _normalize_concept(node.get("concept_name") or ""))
        if not self.history:
            self.history["seen"] = set(seen_hashes(self.user_id))
            self.history["revealed"] = set(revealed_hashes(self.user_id))
        answered_elsewhere = self.history["seen"] | self.history["revealed"]
        chosen = None
        open_id = self.opened.get(node["id"])
        if open_id is not None:
            chosen = next(
                (
                    i
                    for i in pool
                    if i.id == open_id
                    and is_servable(i)
                    and i.question_hash not in answered_elsewhere
                ),
                None,
            )
        if chosen is None:
            reserve = posttest_reserve_hash(pool)
            fallback = self.history["revealed"] | ({reserve} if reserve is not None else set())
            strict = self.served_today | self.history["seen"] | fallback
            chosen = _pick_item(pool, c.band, strict, fallback)
        if chosen is None:
            return None
        streak = c.row.get("streak_unassisted") or 0
        stage, target = sr_stage_for_concept(streak)
        return ReviewItem(
            kind="check",
            id=chosen.id,
            node_id=node["id"],
            course_id=node.get("course_id"),
            question_hash=chosen.question_hash,
            due_at=parse_ts(c.row.get("fsrs_due_at")),
            last_review_at=c.last_review_at,
            r=_retrievability(c.stability, c.last_review_at, now),
            stability=c.stability,
            format=chosen.format,
            difficulty=chosen.difficulty,
            cost_s=REVIEW_SECONDS_PER_CHECK,
            sr_stage=stage,
            sr_target=target,
            sr_count=streak,
            concept_name=node.get("concept_name"),
        )


def _order(entries: list, now: datetime) -> list:
    """fsrs.order_due sorts mappings; wrap each entry (a ReviewItem or a _Concept)
    in the mapping its R comes from."""
    rows = [
        {"fsrs_s": e.stability, "fsrs_last_review_at": e.last_review_at, "entry": e}
        for e in entries
    ]
    return [row["entry"] for row in fsrs.order_due(rows, now)]


def remaining_budget_s(loop_state: dict | None) -> int:
    """REVIEW_DAILY_BUDGET_MIN in seconds minus what this session spent."""
    spent = ((loop_state or {}).get("review") or {}).get("spent_s") or 0
    return _DAILY_BUDGET_S - spent


def _target_met(entry: dict | None) -> bool:
    return bool(entry) and entry.get("correct", 0) >= entry.get("target", SR_INITIAL_CRITERION)


def due_queue_with_stats(
    user_id: str,
    course_id: str | None,
    now: datetime,
    *,
    loop_state: dict | None = None,
    pause_novice: bool | Callable[[], bool] = False,
) -> tuple[list[ReviewItem], dict]:
    """Rule 1. Returns (the ordered, budgeted queue, stats).

    Due cards and due concepts are merged in DASH order and walked once: the
    queue is the longest prefix whose summed `cost_s` fits the remaining daily
    budget (fsrs.budget_select prices every item at one cost; the queue mixes
    checks and cards, so it sums each item's own cost — Deviation). It stops at
    the first item that does not fit, so a cheaper later item never jumps the
    order; a concept's check item is read only while the concept is inside the
    budget, and a concept whose key has an open item re-uses it.

    stats = {"due": {"flashcard": n, "check": n}, "in_budget": n, "unservable": n,
    "paused": n}: `due` counts everything due this session (a concept past the
    budget is counted without its item read — its servability is unknown),
    `in_budget` the queue, `unservable` the concepts examined that had no
    servable item, `paused` the novice concepts held back (A20)."""
    state = loop_state or {}
    sr = state.get("sr") or {}
    served_today = set((state.get("review") or {}).get("served_hashes") or [])
    stats: dict[str, Any] = {"unservable": 0, "paused": 0}
    cards = [
        c for c in _due_flashcards(user_id, course_id, now) if not _target_met(sr.get(sr_key(c)))
    ]
    concepts = [
        c
        for c in _due_concepts(
            user_id, course_id, now, pause=_pause_check(pause_novice), stats=stats
        )
        if not _target_met(sr.get(c.node["id"]))
    ]
    selector = _Selector(user_id, served_today, open_item_ids(state, now))
    remaining = remaining_budget_s(state)
    queue: list[ReviewItem] = []
    due = dict.fromkeys(_KINDS, 0)
    spent, full = 0, False
    for entry in _order(cards + concepts, now):
        cost = REVIEW_SECONDS_PER_CHECK if isinstance(entry, _Concept) else entry.cost_s
        full = full or spent + cost > remaining
        if isinstance(entry, _Concept):
            if full:  # past the budget: counted, never read
                due["check"] += 1
                continue
            item = selector.item(entry, now)
            if item is None:
                stats["unservable"] += 1
                logger.info(
                    "review: unservable concept node=%s (no servable item left)",
                    entry.node["id"],
                )
                continue
        else:
            item = entry
        due[item.kind] += 1
        if not full:
            queue.append(item)
            spent += item.cost_s
    stats["due"] = due
    stats["in_budget"] = len(queue)
    return queue, stats


def due_queue(
    user_id: str,
    course_id: str | None,
    now: datetime,
    *,
    loop_state: dict | None = None,
    pause_novice: bool | Callable[[], bool] = False,
) -> list[ReviewItem]:
    return due_queue_with_stats(
        user_id, course_id, now, loop_state=loop_state, pause_novice=pause_novice
    )[0]


def log_served(
    user_id: str, queue: list[ReviewItem], *, retention: float, request_id: str | None
) -> None:
    """`review.served` once per kind present in a built queue (spec §6)."""
    for kind in _KINDS:
        n = sum(i.kind == kind for i in queue)
        if n:
            log_event(
                "review.served",
                category="usage",
                user_id=user_id,
                request_id=request_id,
                payload={
                    "kind": kind,
                    "n": n,
                    "budget_min": REVIEW_DAILY_BUDGET_MIN,
                    "retention_target": retention,
                },
            )


def summary(
    user_id: str,
    course_id: str | None,
    now: datetime,
    *,
    loop_state: dict | None,
    pause_novice: bool | Callable[[], bool] = False,
    retention: float | None = None,
) -> dict:
    """The `/review/summary` body (`paused` = novice concepts held back at the
    tutor hard level; `due` everything due today, `in_budget` what today's
    remaining budget covers)."""
    _, stats = due_queue_with_stats(
        user_id, course_id, now, loop_state=loop_state, pause_novice=pause_novice
    )
    if retention is None:
        retention = review_retention(user_id, course_id)
    return {
        "due": stats["due"],
        "in_budget": stats["in_budget"],
        "unservable": stats["unservable"],
        "paused": stats["paused"],
        "budget_min": REVIEW_DAILY_BUDGET_MIN,
        "remaining_budget_s": remaining_budget_s(loop_state),
        "retention_target": retention,
    }


# ── loop_state deltas (applied in memory AND re-applied by the CAS store) ─────


def _seed_relearning(item: ReviewItem) -> fsrs.SuccessiveRelearning:
    """HANDOFF-02's machine for an item first touched this session, seeded
    from the derived stage: acquisition restarts per session (the criterion is
    met within one session); a relearn item has `sr_count − SR_INITIAL_CRITERION`
    later sessions done; done absorbs."""
    if item.sr_stage == "acquire":
        return fsrs.SuccessiveRelearning()
    if item.sr_stage == "relearn":
        # sessions done so far, below SR_RELEARN_SESSIONS (the last one completes it)
        done = min(max(item.sr_count - SR_INITIAL_CRITERION, 0), SR_RELEARN_SESSIONS - 1)
        phase = fsrs.SR_RELEARN
    else:
        done, phase = SR_RELEARN_SESSIONS, fsrs.SR_DONE
    return fsrs.SuccessiveRelearning(
        phase=phase, correct_in_acquisition=SR_INITIAL_CRITERION, relearn_sessions_done=done
    )


def _entry(doc: dict, item: ReviewItem) -> dict:
    """loop_state["sr"][key], created on first touch; tolerates a partial entry."""
    entry = doc.setdefault("sr", {}).setdefault(sr_key(item), {})
    entry.setdefault("correct", 0)
    entry.setdefault("target", item.sr_target)
    entry.setdefault("served", 0)
    entry.setdefault("stage", item.sr_stage)
    entry.setdefault("relearning", _seed_relearning(item).as_dict())
    return entry


def _sr_view(entry: dict) -> dict:
    return {"stage": entry["stage"], "correct": entry["correct"], "target": entry["target"]}


def _apply_serve(doc: dict, item: ReviewItem, now_s: float | None = None) -> dict:
    entry = _entry(doc, item)
    entry["served"] += 1
    if item.kind == "check" and item.question_hash:
        hashes = doc.setdefault("review", {}).setdefault("served_hashes", [])
        if item.question_hash not in hashes:
            hashes.append(item.question_hash)
    if now_s is not None:
        _open_item(doc, item, now_s)
    return entry


# ── answer claims (PKG-07's grading-claim discipline, spec §13 A52) ───────────
# loop_state["open"][key] = {"item_id", "served_at"[, "claim", "claim_at"][, "graded_at"]}
# (Unix seconds). serve opens the key for the item it served; /review/answer claims
# it by compare-and-set BEFORE grading. A claim is never re-taken: the grade, the ONE
# evidence (or flashcard) write and its record run under it; a path that writes
# nothing releases it; after the write only the record closes it (graded_at), so a
# double submit — sequential or concurrent — never writes twice (409), and a lost
# record keeps the item claimed. Only a later serve reopens the key, and it leaves
# a live claim (younger than LOOP_GRADING_CLAIM_STALE_S) alone.

_NOT_SERVED = "not_served"
_ALREADY_GRADED = "already_graded"


class ReviewClaimRefused(Exception):
    """The answer may not be graded: `reason` is "not_served" (the item is not the
    one this session served for its key) or "already_graded" (graded, or another
    request holds its claim). The route answers 409."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _live_claim(entry: dict, now_s: float) -> bool:
    return bool(entry.get("claim")) and (
        now_s - float(entry.get("claim_at") or 0) <= LOOP_GRADING_CLAIM_STALE_S
    )


def _open_item(doc: dict, item: ReviewItem, now_s: float) -> None:
    opened = doc.setdefault("open", {})
    current = opened.get(sr_key(item))
    if isinstance(current, dict) and _live_claim(current, now_s):
        return  # grading in flight: the served item stays the answerable one
    opened[sr_key(item)] = {"item_id": item.id, "served_at": now_s}


def claim_item(session_id: str, key: str, item_id: str, claim: str, now: datetime) -> None:
    """Take the answer claim on `key` for `item_id` (one compare-and-set write), or
    raise ReviewClaimRefused and write nothing."""
    now_s = now.timestamp()

    def take(doc: dict) -> None:
        entry = (doc.get("open") or {}).get(key)
        if not isinstance(entry, dict) or entry.get("item_id") != item_id:
            raise ReviewClaimRefused(_NOT_SERVED)
        if entry.get("graded_at") is not None or entry.get("claim"):
            raise ReviewClaimRefused(_ALREADY_GRADED)
        entry["claim"], entry["claim_at"] = claim, now_s

    _persist_loop_state(session_id, take)


def _release_claim(session_id: str, key: str, claim: str) -> None:
    def release(doc: dict) -> None:
        entry = (doc.get("open") or {}).get(key)
        if isinstance(entry, dict) and entry.get("claim") == claim:
            entry.pop("claim", None)
            entry.pop("claim_at", None)

    try:
        _persist_loop_state(session_id, release)
    except Exception:  # the claim goes stale; a later serve reopens the key
        logger.warning("review: answer claim on %s not released", key, exc_info=True)


def _apply_grade(
    doc: dict,
    item: ReviewItem,
    *,
    correct: bool,
    session_id: str,
    retention: float,
    claim: str | None = None,
    now_s: float | None = None,
) -> dict | None:
    """The record of one graded answer. With a `claim`, only while that claim
    holds the item's open entry (else nothing), and it closes the entry."""
    if claim is not None:
        opened = (doc.get("open") or {}).get(sr_key(item))
        if not isinstance(opened, dict) or opened.get("claim") != claim:
            return None
        opened.pop("claim", None)
        opened.pop("claim_at", None)
        opened["graded_at"] = now_s
    entry = _entry(doc, item)
    machine = fsrs.SuccessiveRelearning.from_dict(entry["relearning"])
    if correct:
        entry["correct"] += 1
        machine = machine.advance(True, session_id=session_id)
    else:
        # The session's consecutive count restarts. The item is NOT re-served in
        # this session unless FSRS makes it due again before the day ends (a
        # lapse's short interval can): within-session relearning is not
        # scheduled here (HANDOFF-12 Known gaps).
        entry["correct"] = 0
        if machine.phase == fsrs.SR_ACQUISITION:  # the session criterion is consecutive
            machine = fsrs.SuccessiveRelearning()
    entry["relearning"] = machine.as_dict()
    entry["stage"] = _PHASE_TO_STAGE[machine.phase]
    review = doc.setdefault("review", {})
    review["spent_s"] = (review.get("spent_s") or 0) + item.cost_s
    review["retention"] = retention
    return entry


def _persist_loop_state(session_id: str, apply: Callable[[dict], Any]) -> Any:
    """Re-apply this call's delta to the freshly loaded sessions.loop_state
    (its "sr"/"review" keys ride in LoopState.extra) under compare-and-set.
    Returns what `apply` returned on the SAVED application (None when the row is
    missing). LoopStateConflict propagates."""
    result: list[Any] = [None]

    def mutate(state) -> None:
        result[0] = apply(state.extra)

    if update_loop_state(session_id, mutate) is None:
        logger.warning("review: sessions row %s missing; loop_state not saved", session_id)
        return None
    return result[0]


# ── serve / grade ─────────────────────────────────────────────────────────────


def serve(
    item: ReviewItem,
    *,
    check_item=None,
    card_row: dict | None = None,
    loop_state: dict,
    session_id: str | None = None,
    now: datetime | None = None,
) -> dict:
    """Rule 5: the client payload. A check never carries the reference, final
    answer, rubric, common wrong answers, correct option, canonical answer or
    any option's wrong_key; an mc_reason check carries its STORED options
    (letter + text, stored order; A22). With `session_id` the served counter
    and served hash are persisted too; with `now` the item is opened for
    answering (`claim_item`) — unless it is already the open item for its key
    (`is_open`): a re-serve writes nothing and changes no counter."""
    now_s = now.timestamp() if now is not None else None
    if now is not None and is_open(loop_state, item, now):
        entry = _entry(copy.deepcopy(loop_state), item)
    else:
        entry = _apply_serve(loop_state, item, now_s)
        if session_id is not None:
            _persist_loop_state(session_id, lambda doc: _apply_serve(doc, item, now_s))
    sr = _sr_view(entry)
    if item.kind == "flashcard":
        row = card_row or {}
        return {
            "kind": "flashcard",
            "id": item.id,
            "topic": item.topic,
            "cost_s": item.cost_s,
            "sr": sr,
            "front": decrypt_if_present(row.get("front")),
            "back": decrypt_if_present(row.get("back")),
        }
    payload = {
        "kind": "check",
        "id": item.id,
        "node_id": item.node_id,
        "concept_name": item.concept_name,
        "format": item.format,
        "difficulty": item.difficulty,
        "cost_s": item.cost_s,
        "sr": sr,
        "prompt": check_item.prompt if check_item is not None else None,
    }
    if item.format == "mc_reason" and check_item is not None and check_item.options:
        payload["options"] = [{"letter": o.letter, "text": o.text} for o in check_item.options]
    return payload


def _next_due_for_concept(user_id: str, node_id: str) -> str | None:
    rows = table("learner_state").select(
        "node_id,fsrs_due_at", filters={"user_id": f"eq.{user_id}", "node_id": f"eq.{node_id}"}
    )
    return rows[0].get("fsrs_due_at") if rows else None


def _record(
    user_id: str,
    item: ReviewItem,
    *,
    correct: bool,
    rating: int,
    session_id: str,
    loop_state: dict,
    request_id: str | None,
    retention: float,
    claim: str | None = None,
    now: datetime | None = None,
) -> dict:
    """Both kinds, after the grade is written: SR + budget, persisted (under the
    answer claim, which this write closes), then `review.graded` — only when the
    record was saved (a claim no longer held, or a missing row, records nothing
    and emits nothing)."""
    entry = _apply_grade(
        loop_state, item, correct=correct, session_id=session_id, retention=retention
    )
    now_s = now.timestamp() if now is not None else None
    saved = _persist_loop_state(
        session_id,
        lambda doc: _apply_grade(
            doc,
            item,
            correct=correct,
            session_id=session_id,
            retention=retention,
            claim=claim,
            now_s=now_s,
        ),
    )
    if saved is None:
        logger.warning("review: record of %s not saved (claim lost or row missing)", item.id)
        return _sr_view(entry)
    log_event(
        "review.graded",
        category="usage",
        user_id=user_id,
        request_id=request_id,
        payload={"kind": item.kind, "correct": correct, "rating": rating},
    )
    return _sr_view(entry)


def _write_flashcard(
    user_id: str,
    item: ReviewItem,
    *,
    rating: int | None,
    now: datetime,
    retention: float,
    card_row: dict | None,
) -> tuple[int, dict]:
    """A self-rated card (legacy 1 forgot / 2 hard / 3 easy) through PKG-11's
    flashcard_fsrs_update at the review's retention target: (FSRS rating, the
    written columns). Never a model call and never graph evidence. A rating
    outside the map raises ValueError before any write (the route answers 422)."""
    fsrs_rating = fsrs_rating_for(rating)
    if card_row is None:
        raise ValueError("a flashcard review needs the card's flashcards row")
    cols = flashcard_fsrs_update(card_row, rating, now=now, retention=retention)
    table("flashcards").update(cols, filters={"id": f"eq.{item.id}", "user_id": f"eq.{user_id}"})
    return fsrs_rating, cols


async def grade_review(
    user_id: str,
    item: ReviewItem,
    *,
    answer: str | None,
    rating: int | None,
    session_id: str,
    loop_state: dict,
    now: datetime,
    request_id: str | None,
    retention: float,
    check_item=None,
    card_row: dict | None = None,
    selected_option: str | None = None,
    reason: str | None = None,
    deps=None,
    claim: str | None = None,
) -> ReviewOutcome:
    """Rule 6. A check item is graded by grade_answer ONCE (unassisted:
    max_rung 0; a re-check only when it is the next graded item on its concept
    after a release — misconceptions.recheck_after_release, spec §13 A76) and its Evidence persisted by ONE
    apply_graph_update call; unavailable/refused writes nothing. A flashcard
    goes through flashcard_fsrs_update.

    `claim` (the route's, from `claim_item`): every path that writes nothing —
    unavailable, refused, an error before the write — releases it; after the
    write only the record closes it."""
    written = False
    try:
        if item.kind == "flashcard":
            fsrs_rating, cols = _write_flashcard(
                user_id, item, rating=rating, now=now, retention=retention, card_row=card_row
            )
            written = True
            correct = fsrs_rating != fsrs.Rating.AGAIN  # legacy 1 = forgot
            rating_out, hint, next_due = fsrs_rating, None, cols["due_at"]
        else:
            if check_item is None or deps is None:
                raise ValueError(
                    "a check review needs the decrypted check_item and the route's deps"
                )
            outcome = await grade_answer(
                check_item,
                CheckAnswer(
                    question_hash=check_item.question_hash,
                    answer_text=answer or "",
                    selected_option=selected_option,
                    reason=reason,
                ),
                deps=deps,
                node_id=item.node_id,
                # spec §13 A76 (fix round 3): a due item right after a release on
                # its concept (a wrong loop answer this morning) is the re-check
                same_session_recheck=recheck_after_release(
                    user_id, item.node_id, loop_state, now=now, item=check_item
                ),
            )
            if outcome.refused is not None or outcome.unavailable:
                # A33 (refused: never graded, never a skip) and invariant 28
                # (unavailable: nothing for EITHER outcome) — nothing is written.
                if claim is not None:
                    _release_claim(session_id, sr_key(item), claim)
                return ReviewOutcome(unavailable=True, refused=outcome.refused is not None)
            # The one write. deps.pending_evidence is discarded, never flushed:
            # the retention target rides on this call only.
            apply_graph_update(
                user_id,
                {"evidence": [outcome.evidence]},
                course_id=item.course_id,
                retention=retention,
            )
            written = True
            correct = bool(outcome.correct)
            hint = outcome.feedback_hint
            if not correct:  # spec §3.3: corrective feedback WITH the answer
                hint = f"{outcome.feedback_hint}\n\nAnswer: {check_item.reference_answer}"
            rating_out = fsrs.rating_for(outcome.evidence["channel"], correct, 0)
            next_due = _next_due_for_concept(user_id, item.node_id)
    except BaseException:
        if claim is not None and not written:  # nothing written: the student may answer again
            _release_claim(session_id, sr_key(item), claim)
        raise
    sr = _record(
        user_id,
        item,
        correct=correct,
        rating=rating_out,
        session_id=session_id,
        loop_state=loop_state,
        request_id=request_id,
        retention=retention,
        claim=claim,
        now=now,
    )
    if item.kind == "flashcard":  # the same achievement rate_card dispatches
        try:
            check_achievements(user_id, "flashcards_reviewed", {})
        except Exception:
            logger.exception(
                "review: achievement dispatch failed user=%s card=%s", user_id, item.id
            )
    return ReviewOutcome(correct=correct, hint=hint, next_due_at=next_due, rating=rating_out, sr=sr)
