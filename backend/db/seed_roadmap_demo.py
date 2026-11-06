"""LOCAL-ONLY study-roadmap demo course — one course that exercises every
P1 feature of the roadmap page at once.

The rich seed's courses each show only a slice: MATH210 has one topic and
mostly unfiled concepts, CS101 has no `part_of` at all (the "not yet grouped"
flat list). Neither shows topic ORDERING, a prerequisite CYCLE, stale markers,
or what changes when you switch the exam the page is scored against. This adds
a course shaped to show all of it on one screen.

Run (from backend/, local stack up, backend/.env active):
    python -m db.seed_roadmap_demo

Idempotent: re-running rewrites nothing it already wrote. Namespaced `road-*`
so it cannot collide with the rich seed's `rich-*` ids, and layered ON TOP of
that seed (it reuses its user, school and term) rather than replacing it.

The per-test TRUNCATE in the E2E lane restores the rich baseline ONLY, so a
Playwright run drops this course — re-run this script afterwards.

What each feature needs, and where it comes from:

  topics + subtopics   `part_of` edges, source = child, target = parent
  topic ORDER          `prerequisite` / `builds_on` edges between topics
  in_cycle             a prerequisite cycle (Convergence <-> Taylor)
  mastery tiers        mastery_score; all four tiers present
  unfiled section      concepts with no `part_of` edge, ALONGSIDE real topics
  start here           the first topic that is not finished
  exam list            assignments with assignment_type='exam' AND a due_date
  exam SELECTION       two FUTURE exams, so switching actually changes things
  stale / freshness    quiz_responses(is_correct, answered_at, concept_node_id)

Freshness is EXAM-RELATIVE (services/roadmap.freshness): staleness is
days_cold / days_left, stale at >= 0.5. The dates below are chosen so that
"Continuity" is STALE against the near exam and FRESH against the far one —
the clearest demonstration that the same concept can be both at once.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import get_mastery_tier            # noqa: E402
from db import seed_helpers as h               # noqa: E402
from db.seed_local_rich import (               # noqa: E402
    SCHOOL_ID,
    TERM_FALL_2026,
    USER_ACTIVE,
)
from services.encryption import encrypt_if_present, encrypt_json  # noqa: E402


def _guard_local() -> None:
    if not h.local_app_env():
        sys.exit("REFUSING: demo seeding requires APP_ENV=local or APP_ENV=test.")
    if not h.local_supabase_url():
        url = (os.getenv("SUPABASE_URL") or "").strip()
        sys.exit(f"REFUSING: SUPABASE_URL {url!r} is not local.")


COURSE = "road-course-calc101"
OFFERING = "road-off-calc101-f26"
ENROLLMENT = "road-enr-active-calc101-f26"
CATEGORY = "road-cat-calc101-exams"

TODAY = datetime.now(timezone.utc).date()
# NEAR is what the page selects by itself: `_selected_exam` falls back to the
# next upcoming exam rather than to nothing.
EXAM_NEAR = TODAY + timedelta(days=21)
EXAM_FAR = TODAY + timedelta(days=75)
EXAM_PAST = TODAY - timedelta(days=42)


def _ts(days: int) -> str:
    """A UTC timestamp `days` before today."""
    return datetime.combine(
        TODAY - timedelta(days=days), datetime.min.time(), tzinfo=timezone.utc
    ).isoformat()


# (node_id, concept_name, mastery, days_since_last_CORRECT | None, times_studied)
#
# days_cold is the freshness lever. Against EXAM_NEAR (21 days out) the stale
# threshold is ~10 days cold; against EXAM_FAR (75 days) it is ~37. So:
#   3-6 days  -> fresh against both exams
#   14 days   -> STALE against the near exam, FRESH against the far one
#   40 days   -> stale against the near exam, borderline against the far
#   95 days   -> stale against both
#   None      -> never proved. freshness() returns (1.0, False) BY DESIGN:
#                mastery 0 already encodes the missing evidence, and
#                discounting it again would double-count the same absence.
_TOPICS: list[tuple[str, str, list[tuple[str, str, float, int | None, int]]]] = [
    (
        "road-topic-limits", "Limits and Continuity",
        [
            ("road-limits-epsilon", "Epsilon-Delta Definition", 0.93, 3, 7),
            ("road-limits-continuity", "Continuity", 0.80, 14, 5),
            ("road-limits-squeeze", "Squeeze Theorem", 0.66, 5, 4),
        ],
    ),
    (
        "road-topic-derivatives", "Derivatives",
        [
            ("road-deriv-power", "Power Rule", 0.88, 4, 9),
            ("road-deriv-chain", "Chain Rule", 0.31, 95, 6),
            ("road-deriv-implicit", "Implicit Differentiation", 0.0, None, 0),
        ],
    ),
    (
        "road-topic-integrals", "Integrals",
        [
            ("road-int-riemann", "Riemann Sums", 0.52, 6, 3),
            ("road-int-ftc", "Fundamental Theorem", 0.14, None, 1),
            ("road-int-parts", "Integration by Parts", 0.0, None, 0),
        ],
    ),
    (
        # The cycle lives inside this topic: Convergence and Taylor are each
        # other's prerequisite, which is exactly the contradiction `in_cycle`
        # exists to surface rather than silently invent an order for.
        "road-topic-series", "Sequences and Series",
        [
            ("road-series-convergence", "Convergence Tests", 0.48, 40, 2),
            ("road-series-taylor", "Taylor Series", 0.22, None, 1),
        ],
    ),
]

# No `part_of` edge -> these render in "Unfiled concepts" even though the
# course HAS topics. The rich seed can only show the unfiled-only shape.
_UNFILED: list[tuple[str, str, float, int | None, int]] = [
    ("road-unfiled-lhopital", "L’Hôpital’s Rule", 0.24, None, 2),
    ("road-unfiled-rates", "Related Rates", 0.0, None, 0),
]

# Topic order: Limits -> Derivatives -> Integrals -> Series.
_TOPIC_ORDER = [
    ("road-topic-limits", "road-topic-derivatives"),
    ("road-topic-derivatives", "road-topic-integrals"),
    ("road-topic-integrals", "road-topic-series"),
]

# Ordering INSIDE a topic, plus the deliberate cycle.
_SUBTOPIC_ORDER = [
    ("road-limits-epsilon", "road-limits-continuity", "prerequisite"),
    ("road-deriv-power", "road-deriv-chain", "prerequisite"),
    ("road-deriv-chain", "road-deriv-implicit", "builds_on"),
    ("road-int-riemann", "road-int-ftc", "prerequisite"),
    # The cycle.
    ("road-series-convergence", "road-series-taylor", "prerequisite"),
    ("road-series-taylor", "road-series-convergence", "prerequisite"),
]

# (id, title, due_date, points_possible, points_earned)
_EXAMS = [
    ("road-exam-midterm1", "Midterm 1", EXAM_PAST, 100, 71),
    ("road-exam-midterm2", "Midterm 2", EXAM_NEAR, 100, None),
    ("road-exam-final", "Final Exam", EXAM_FAR, 200, None),
]


def seed_course(writer=h) -> None:
    writer.upsert(
        "courses",
        {
            "id": COURSE,
            "school_id": SCHOOL_ID,
            "course_code": "CALC101",
            "course_name": "Calculus I (Study Plan Lab)",
            "department": "Mathematics",
            "credits": 4,
            "description": "A course shaped to exercise every part of the study plan.",
        },
        on_conflict="id",
    )
    writer.upsert(
        "course_offerings",
        {
            "id": OFFERING,
            "course_id": COURSE,
            "term_id": TERM_FALL_2026,
            "section": "",
            "instructor_name": "Dr. Katherine Johnson",
            "meeting_times": "MWF 08:00",
            "location": "Hall E",
        },
        on_conflict="course_id,term_id,section",
    )
    writer.upsert(
        "enrollments",
        {
            "id": ENROLLMENT,
            "user_id": USER_ACTIVE,
            "offering_id": OFFERING,
            "color": "#8A63D2",
            "nickname": "Calc I (lab)",
            "curve_mode": "raw",
        },
        on_conflict="user_id,offering_id",
    )


def seed_graph(writer=h) -> None:
    def node(node_id: str, name: str, mastery: float, studied: int, days: int | None) -> None:
        writer.upsert(
            "graph_nodes",
            {
                "id": node_id,
                "user_id": USER_ACTIVE,
                "course_id": COURSE,
                "concept_name": name,
                "subject": "Calculus",
                "mastery_score": mastery,
                "mastery_tier": get_mastery_tier(mastery),
                "times_studied": studied,
                "last_studied_at": _ts(days) if days is not None else None,
            },
            on_conflict="id",
        )

    def edge(source: str, target: str, rel: str, strength: float = 0.8) -> None:
        writer.upsert(
            "graph_edges",
            {
                "id": f"road-edge-{rel}-{source}-{target}",
                "user_id": USER_ACTIVE,
                "source_node_id": source,
                "target_node_id": target,
                "relationship_type": rel,
                "strength": strength,
            },
            on_conflict="id",
        )

    for topic_id, topic_name, subtopics in _TOPICS:
        # A topic node's own mastery is not what the grid shows — the topic
        # row rolls its children up — but it IS a real concept node that the
        # graph screens render, so give it an honest average.
        avg = round(sum(s[2] for s in subtopics) / len(subtopics), 2)
        node(topic_id, topic_name, avg, 0, None)
        for sub_id, sub_name, mastery, days_cold, studied in subtopics:
            node(sub_id, sub_name, mastery, studied, days_cold)
            # source = child, target = parent (§3.1).
            edge(sub_id, topic_id, "part_of", 0.9)

    for node_id, name, mastery, days_cold, studied in _UNFILED:
        node(node_id, name, mastery, studied, days_cold)

    for source, target in _TOPIC_ORDER:
        edge(source, target, "prerequisite", 0.85)
    for source, target, rel in _SUBTOPIC_ORDER:
        edge(source, target, rel, 0.7)


def seed_exams(writer=h) -> None:
    writer.upsert(
        "gradebook_categories",
        {
            "id": CATEGORY,
            "enrollment_id": ENROLLMENT,
            "name": "Exams",
            "weight": 0.6,
            "drop_lowest": 0,
        },
        on_conflict="id",
    )
    for exam_id, title, due, possible, earned in _EXAMS:
        writer.insert_if_absent(
            "assignments",
            exam_id,
            {
                "enrollment_id": ENROLLMENT,
                "category_id": CATEGORY,
                "title": title,
                "due_date": due.isoformat(),
                "assignment_type": "exam",
                "source": "manual",
                # 🔒 points (numeric semantics; decrypt_numeric at read)
                "points_possible": encrypt_if_present(str(possible)),
                "points_earned": encrypt_if_present(str(earned)) if earned is not None else None,
            },
        )


def seed_attribution(writer=h) -> None:
    """The per-question rows freshness reads (§3.7 / §3.13).

    One attempt, one response per concept ever answered correctly, each
    stamped with its own `answered_at`. The roadmap only ever asks
    `max(answered_at) WHERE is_correct AND concept_node_id = n`, so the
    attempt is scaffolding — the response rows are what matter.
    """
    attempt_id = "road-qa-calc101"
    proved = [
        (node_id, days)
        for _, _, subs in _TOPICS
        for node_id, _, _, days, _ in subs
        if days is not None
    ]

    writer.insert_if_absent(
        "quiz_attempts",
        attempt_id,
        {
            "user_id": USER_ACTIVE,
            "concept_node_id": _TOPICS[0][2][0][0],
            "score": len(proved),
            "total": len(proved),
            "difficulty": "medium",
            # 🔒 questions_json / answers_json
            "questions_json": encrypt_json(
                [{"question": f"Demo question {i + 1}"} for i in range(len(proved))]
            ),
            "answers_json": encrypt_json([0] * len(proved)),
            "completed_at": _ts(3),
        },
    )

    for index, (node_id, days_cold) in enumerate(proved):
        writer.insert_by_keys(
            "quiz_responses",
            {
                "id": f"road-qr-{node_id}",
                "attempt_id": attempt_id,
                "question_index": index,
                "selected_index": 0,
                "is_correct": True,
                "concept_node_id": node_id,
                "answered_at": _ts(days_cold),
            },
            keys="id",
        )


def main() -> None:
    _guard_local()
    seed_course()
    seed_graph()
    seed_exams()
    seed_attribution()
    h.print_summary(
        [
            "courses", "course_offerings", "enrollments", "graph_nodes",
            "graph_edges", "gradebook_categories", "assignments",
            "quiz_attempts", "quiz_responses",
        ],
        "Seed summary (study-plan demo course):",
    )
    print()
    print(f"  Study plan: /roadmap/{COURSE}")
    print(f"  Auto-selected exam: Midterm 2  ({EXAM_NEAR.isoformat()}, 21 days out)")
    print(f"  Switch to:          Final Exam ({EXAM_FAR.isoformat()}, 75 days out)")
    print("  Continuity should flip from 'needs review' to fresh when you do.")


if __name__ == "__main__":
    main()
