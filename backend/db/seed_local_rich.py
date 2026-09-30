"""LOCAL-ONLY rich seed for E2E / manual testing (#363).

Broad, idempotent, self-contained dataset layered on the canonical terms
(fall-2025 / spring-2026 / fall-2026 — 0019 seeds these and
0032_retire_summer_2026 removes Summer). All ids namespaced
`rich-*`. 🔒 columns via services.encryption so they decrypt with the LOCAL
ENCRYPTION_KEY. Refuses to run against a non-local SUPABASE_URL.

Run (from backend/ with the local stack up and backend/.env active):
    python -m db.seed_local_rich
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from learning.bkt import tier_for            # noqa: E402  (PKG-14b)
from db import seed_helpers as h               # noqa: E402
from db.connection import table                # noqa: E402
from services.encryption import encrypt_if_present, encrypt_json  # noqa: E402


def _guard_local() -> None:
    url = (os.getenv("SUPABASE_URL") or "").strip()
    if "127.0.0.1" not in url and "localhost" not in url:
        sys.exit(f"REFUSING: SUPABASE_URL {url!r} is not local — seed_local_rich only writes to local.")


def _admin_role_id() -> str | None:
    rows = table("roles").select("id", filters={"slug": "eq.admin"}, limit=1) or []
    return rows[0]["id"] if rows else None


# ─── Deterministic ids (everything namespaced `rich-…`) ──────────────────────

SCHOOL_ID = "rich-school-demo"

COURSE_CS = "rich-course-cs101"
COURSE_MATH = "rich-course-math210"
COURSE_BIO = "rich-course-bio110"
COURSE_ENG = "rich-course-eng150"
COURSE_HIST = "rich-course-hist200"
COURSE_CHEM = "rich-course-chem121"

TERM_FALL_2025 = "fall-2025"
TERM_SPRING_2026 = "spring-2026"
# Fall 2026 absorbed the Summer 2026 window when 0032_retire_summer_2026
# deleted that term. There is deliberately no TERM_SUMMER_2026: seeding an
# offering against it fails the terms FK (PostgREST reports it as a 409).
TERM_FALL_2026 = "fall-2026"

OFF_CS_F25 = "rich-off-cs101-f25"
OFF_CS_S26 = "rich-off-cs101-s26"
OFF_ENG_SU26 = "rich-off-eng150-su26"
OFF_MATH_S26 = "rich-off-math210-s26"
OFF_BIO_F25 = "rich-off-bio110-f25"
OFF_HIST_F25 = "rich-off-hist200-f25"
OFF_CHEM_F25 = "rich-off-chem121-f25"
OFF_CHEM_S26 = "rich-off-chem121-s26"

USER_ACTIVE = "rich-user-active"
USER_SECOND = "rich-user-second"
USER_NEW = "rich-user-new"
USER_PENDING = "rich-user-pending"
USER_ADMIN = "rich-user-admin"

ENR_ACTIVE_CS_F25 = "rich-enr-active-cs101-f25"
ENR_ACTIVE_CS_S26 = "rich-enr-active-cs101-s26"
ENR_ACTIVE_MATH_S26 = "rich-enr-active-math210-s26"
ENR_ACTIVE_BIO_F25 = "rich-enr-active-bio110-f25"
ENR_ACTIVE_ENG_SU26 = "rich-enr-active-eng150-su26"
ENR_SECOND_CS_S26 = "rich-enr-second-cs101-s26"
ENR_SECOND_HIST_F25 = "rich-enr-second-hist200-f25"

# The abstract course's `course_code` (_COURSES below): the course key
# course_chunks rows carry (services/document_indexing.py::_course_code).
COURSE_CS_CODE = "CS101"

# Learning loop (PKG-13): the loop users (staff/QA toggle, build phase; spec
# §13 A14). The loop is dark behind LEARNING_LOOP_ENABLED during the build and
# user_settings.learning_loop_beta is a staff/QA toggle set by SQL or this seed
# (spec §7). Only these users carry it, so every legacy rich-* user's GATE stays
# off — the E2E lane runs with LEARNING_LOOP_ENABLED=true and relies on that split
# to keep the tutor/quiz/Learn paths of legacy users untouched. The flag's
# process-wide branches (upload check-item drafting, A35 course context) are on
# for everyone in the lane regardless (scripts/e2e-up.sh). PKG-14b rewrites this
# comment: after launch the gate ignores the toggle (spec §11.2).
USER_LOOP = "rich-user-loop"
USER_CAPPED = "rich-user-capped"
LOOP_USERS = (USER_LOOP, USER_CAPPED)
ENR_LOOP_CS_S26 = "rich-enr-loop-cs101-s26"
ENR_CAPPED_CS_S26 = "rich-enr-capped-cs101-s26"
SEED_LOOP_CONCEPTS = 3
SEED_LOOP_FORMATS = ("free", "teachback")  # † free-text formats: a journey answers every item by typing
SEED_LOOP_ITEMS_PER_CONCEPT = 6  # † = len(SEED_LOOP_FORMATS) × len(CHECK_ITEM_DIFFICULTIES); the test pins it
SEED_CAPPED_SPEND_FACTOR = 1.5  # † today's seeded spend = the novice daily allowance × this (spec §13 A26)
# (slug, concept_name, course-notes sentence) — a prerequisite chain in order.
# Each loop user gets its own graph_nodes rows (loop_node_id); check items are
# course assets keyed on (course_id, concept_key) and written once for both
# (spec §13 A2). Edges are oriented by
# learning.params.EDGE_PREREQ_SOURCE_IS_PREREQ at write time.
LOOP_NODES = [
    ("binary", "Binary Numbers", "A binary number writes a value in base two, one bit per place."),
    ("bitwise", "Bitwise Operators", "Bitwise operators combine two numbers bit by bit."),
    ("twos", "Two's Complement", "Two's complement stores a negative number by inverting and adding one."),
]
assert len(LOOP_NODES) == SEED_LOOP_CONCEPTS
# The shared course-material document the loop items are drafted from (spec §13
# A23: items come only from shared course material). Uploaded by the loop user,
# who consents (share_class_context), indexed into one course_chunks row per
# concept.
LOOP_DOC_ID = "rich-doc-loop-cs-notes"
LOOP_DOC_CATEGORY = "lecture_notes"
LOOP_DOC_SHAREABILITY_CONFIDENCE = 0.9  # † above chunk_visibility.MIN_SHARE_CONFIDENCE
# (card_id, front, back) — the capped user's one due flashcard; the budget-cap
# journey rates it on /study (review keeps working at the hard level, spec §3.5).
CAPPED_FLASHCARD = ("rich-fc-capped-1", "What is a bit?", "A binary digit: 0 or 1.")


def loop_node_id(user_id: str, slug: str) -> str:
    return f"rich-node-{'loop' if user_id == USER_LOOP else 'capped'}-{slug}"


# ─── Seed steps ──────────────────────────────────────────────────────────────


def seed_school() -> None:
    h.upsert(
        "schools",
        {"id": SCHOOL_ID, "name": "Rich Local University", "slug": "rich-local"},
        on_conflict="slug",
    )


_COURSES = [
    (COURSE_CS, "CS101", "Introduction to Computer Science", "Computer Science", 3,
     "Foundations of programming, control flow, and computational thinking."),
    (COURSE_MATH, "MATH210", "Linear Algebra", "Mathematics", 4,
     "Vectors, matrices, eigenvalues, and linear transformations."),
    (COURSE_BIO, "BIO110", "Cell Biology", "Biology", 3,
     "Structure and function of the living cell."),
    (COURSE_ENG, "ENG150", "College Writing", "English", 3,
     "Expository and argumentative writing for college-level work."),
    (COURSE_HIST, "HIST200", "World History Since 1500", "History", 3,
     "A survey of global history from 1500 to the present."),
    (COURSE_CHEM, "CHEM121", "General Chemistry I", "Chemistry", 4,
     "Atomic structure, bonding, stoichiometry, and reaction chemistry."),
]


def seed_courses() -> None:
    for cid, code, name, dept, credits, desc in _COURSES:
        h.upsert(
            "courses",
            {
                "id": cid,
                "school_id": SCHOOL_ID,
                "course_code": code,
                "course_name": name,
                "department": dept,
                "credits": credits,
                "description": desc,
            },
            on_conflict="school_id,course_code",
        )


# 8 offerings; CS101 in both fall-2025 and spring-2026, one summer offering
# (ENG150), the rest spread across fall/spring. Do NOT set course_code (0028).
_OFFERINGS = [
    (OFF_CS_F25, COURSE_CS, TERM_FALL_2025, "Dr. Ada Lovelace", "MWF 09:00", "Hall A"),
    (OFF_CS_S26, COURSE_CS, TERM_SPRING_2026, "Dr. Ada Lovelace", "MWF 11:00", "Hall A"),
    # Keeps its `su26` id: 0032 moved Summer offerings into Fall 2026, and the
    # ids are opaque keys, not claims about the term. Renaming them would break
    # an existing local database: this upsert conflicts on
    # (course_id, term_id, section), so a new id does not insert a second row —
    # it UPDATEs the existing one's `id`, and enrollments.offering_id references
    # it with no ON UPDATE clause (so NO ACTION). The rename fails on that FK.
    (OFF_ENG_SU26, COURSE_ENG, TERM_FALL_2026, "Prof. Maya Angelou", "MTWTh 10:00", "Hall C"),
    (OFF_MATH_S26, COURSE_MATH, TERM_SPRING_2026, "Dr. Emmy Noether", "TTh 10:00", "Hall B"),
    (OFF_BIO_F25, COURSE_BIO, TERM_FALL_2025, "Dr. Rosalind Franklin", "TTh 13:00", "Lab 2"),
    (OFF_HIST_F25, COURSE_HIST, TERM_FALL_2025, "Dr. Howard Zinn", "MWF 13:00", "Hall D"),
    (OFF_CHEM_F25, COURSE_CHEM, TERM_FALL_2025, "Dr. Marie Curie", "MWF 14:00", "Lab 1"),
    (OFF_CHEM_S26, COURSE_CHEM, TERM_SPRING_2026, "Dr. Marie Curie", "MWF 14:00", "Lab 1"),
]


def seed_offerings() -> None:
    for oid, cid, term_id, instructor, meeting, location in _OFFERINGS:
        h.upsert(
            "course_offerings",
            {
                "id": oid,
                "course_id": cid,
                "term_id": term_id,
                "section": "",
                "instructor_name": instructor,
                "meeting_times": meeting,
                "location": location,
            },
            on_conflict="course_id,term_id,section",
        )


# (id, email, onboarding_completed, is_approved, streak_count, profile)
# `profile` is None for no profile, or a dict of profile fields to write.
# "minimal" profiles only carry `name`; "full" profiles carry everything.
_USERS = [
    (USER_ACTIVE, "rich.active@richlocal.test", True, True, 12, {
        "name": "Rich Active", "first_name": "Rich", "last_name": "Active",
        "username": "rich-active", "year": "Junior",
        "majors": ["Computer Science"], "minors": ["Mathematics"],
    }),
    (USER_SECOND, "rich.second@richlocal.test", True, True, 5, {
        "name": "Sam Second", "first_name": "Sam", "last_name": "Second",
        "username": "rich-second", "year": "Senior",
        "majors": ["Biology"], "minors": [],
    }),
    (USER_NEW, "rich.new@richlocal.test", False, True, 0, {
        "name": "Newt Newman",
    }),
    (USER_PENDING, "rich.pending@richlocal.test", False, False, 0, {
        "name": "Penny Pending",
    }),
    (USER_LOOP, "rich.loop@richlocal.test", True, True, 3, {
        "name": "Lou Loop", "first_name": "Lou", "last_name": "Loop",
        "username": "rich-loop", "year": "Sophomore",
        "majors": ["Computer Science"], "minors": [],
    }),
    (USER_CAPPED, "rich.capped@richlocal.test", True, True, 1, {
        "name": "Casey Cap", "first_name": "Casey", "last_name": "Cap",
        "username": "rich-capped", "year": "Freshman",
        "majors": ["Computer Science"], "minors": [],
    }),
    (USER_ADMIN, "rich.admin@richlocal.test", True, True, 30, {
        "name": "Ada Admin", "first_name": "Ada", "last_name": "Admin",
        "username": "rich-admin", "year": "Staff",
        "majors": [], "minors": [],
    }),
]

# Profile fields that are 🔒 (column-encrypted) vs. plaintext.
_PROFILE_ENCRYPTED_FIELDS = ("name", "first_name", "last_name")
_PROFILE_PLAIN_FIELDS = ("username", "year", "majors", "minors")  # PKG-14b: no learning_style


def seed_users() -> None:
    for uid, email, onboarding_completed, is_approved, streak_count, profile in _USERS:
        h.upsert(
            "users",
            {
                "id": uid,
                "email": encrypt_if_present(email),
                "onboarding_completed": onboarding_completed,
                "streak_count": streak_count,
                "is_approved": is_approved,
                "auth_provider": "google",
            },
            on_conflict="id",
        )
        if profile:
            row = {"user_id": uid}
            for key in _PROFILE_ENCRYPTED_FIELDS:
                if key in profile:
                    row[key] = encrypt_if_present(profile[key])
            for key in _PROFILE_PLAIN_FIELDS:
                if key in profile:
                    row[key] = profile[key]
            h.upsert("user_profiles", row, on_conflict="user_id")

    rid = _admin_role_id()
    if rid:
        # user_roles has PK (user_id, role_id) and no `id` column — upsert on
        # the composite key rather than insert_if_absent (which assumes `id`).
        h.upsert(
            "user_roles",
            {"user_id": USER_ADMIN, "role_id": rid},
            on_conflict="user_id,role_id",
        )


# (id, user_id, offering_id, color, nickname, curve_mode, curve_avg_target, curve_sd_delta)
_ENROLLMENTS = [
    (ENR_ACTIVE_CS_F25, USER_ACTIVE, OFF_CS_F25, "#4f86f7", "Intro CS", "raw", None, None),
    (ENR_ACTIVE_CS_S26, USER_ACTIVE, OFF_CS_S26, "#4f86f7", "Intro CS (S26)", "raw", None, None),
    (ENR_ACTIVE_MATH_S26, USER_ACTIVE, OFF_MATH_S26, "#f7724f", "Lin Alg", "raw", None, None),
    (ENR_ACTIVE_BIO_F25, USER_ACTIVE, OFF_BIO_F25, "#5fbf6b", "Cell Bio", "raw", None, None),
    (ENR_ACTIVE_ENG_SU26, USER_ACTIVE, OFF_ENG_SU26, "#c084fc", "Writing", "curved", 0.85, 0.05),
    (ENR_SECOND_CS_S26, USER_SECOND, OFF_CS_S26, "#4f86f7", "Intro CS (S26)", "raw", None, None),
    (ENR_SECOND_HIST_F25, USER_SECOND, OFF_HIST_F25, "#eab308", "World History", "raw", None, None),
    (ENR_LOOP_CS_S26, USER_LOOP, OFF_CS_S26, "#4f86f7", "Intro CS (loop)", "raw", None, None),
    (ENR_CAPPED_CS_S26, USER_CAPPED, OFF_CS_S26, "#4f86f7", "Intro CS (capped)", "raw", None, None),
]


def seed_enrollments() -> None:
    for eid, uid, off_id, color, nickname, curve_mode, avg_target, sd_delta in _ENROLLMENTS:
        row = {
            "id": eid,
            "user_id": uid,
            "offering_id": off_id,
            "color": color,
            "nickname": nickname,
            "curve_mode": curve_mode,
        }
        if curve_mode == "curved":
            row["curve_avg_target"] = avg_target
            row["curve_sd_delta"] = sd_delta
        h.upsert("enrollments", row, on_conflict="user_id,offering_id")


# Graph nodes keyed on the ABSTRACT course_id (mastery is cumulative across
# terms). (node_id, concept_name, mastery_score) — tier derived from score.
_GRAPH_NODES = {
    COURSE_CS: [
        ("rich-node-cs-variables", "Variables and Types", 0.92),      # mastered
        ("rich-node-cs-controlflow", "Control Flow", 0.6),            # learning
        ("rich-node-cs-recursion", "Recursion", 0.25),                # struggling
        ("rich-node-cs-pointers", "Pointers and Memory", 0.05),       # unexplored
        ("rich-node-cs-algorithms", "Algorithms", 0.8),               # mastered
    ],
    COURSE_MATH: [
        ("rich-node-math-vectors", "Vectors", 0.85),                  # mastered
        ("rich-node-math-matrices", "Matrices", 0.5),                 # learning
        ("rich-node-math-eigenvalues", "Eigenvalues", 0.2),           # struggling
        ("rich-node-math-determinants", "Determinants", 0.0),         # unexplored
    ],
    COURSE_BIO: [
        ("rich-node-bio-membrane", "Cell Membrane", 0.78),            # mastered
        ("rich-node-bio-mitochondria", "Mitochondria", 0.55),         # learning
        ("rich-node-bio-dna", "DNA Replication", 0.15),               # struggling
        ("rich-node-bio-photosynthesis", "Photosynthesis", 0.05),     # unexplored
    ],
}

# (edge_id, source_node_id, target_node_id, relationship_type, strength) — all
# four relationship_types covered across courses.
_GRAPH_EDGES = [
    ("rich-edge-cs-variables-controlflow", "rich-node-cs-variables",
     "rich-node-cs-controlflow", "prerequisite", 0.9),
    ("rich-edge-cs-controlflow-recursion", "rich-node-cs-controlflow",
     "rich-node-cs-recursion", "builds_on", 0.8),
    ("rich-edge-cs-recursion-algorithms", "rich-node-cs-recursion",
     "rich-node-cs-algorithms", "related", 0.6),
    ("rich-edge-math-vectors-matrices", "rich-node-math-vectors",
     "rich-node-math-matrices", "part_of", 0.7),
    ("rich-edge-math-matrices-eigenvalues", "rich-node-math-matrices",
     "rich-node-math-eigenvalues", "prerequisite", 0.65),
    ("rich-edge-bio-membrane-mitochondria", "rich-node-bio-membrane",
     "rich-node-bio-mitochondria", "related", 0.5),
    ("rich-edge-bio-mitochondria-dna", "rich-node-bio-mitochondria",
     "rich-node-bio-dna", "builds_on", 0.55),
]

# Append-only mastery events. (node_id, event_id, delta, reason)
_MASTERY_EVENTS = [
    ("rich-node-cs-variables", "rich-evt-cs-variables-1", 0.5, "quiz: intro types"),
    ("rich-node-cs-variables", "rich-evt-cs-variables-2", 0.42, "lecture review"),
    ("rich-node-cs-controlflow", "rich-evt-cs-controlflow-1", 0.3, "homework 2"),
    ("rich-node-math-vectors", "rich-evt-math-vectors-1", 0.45, "problem set 1"),
    ("rich-node-bio-membrane", "rich-evt-bio-membrane-1", 0.4, "reading quiz"),
    ("rich-node-bio-dna", "rich-evt-bio-dna-1", 0.15, "first pass"),
]


def seed_graph() -> None:
    for course_id, nodes in _GRAPH_NODES.items():
        for node_id, concept, score in nodes:
            subject = concept.split()[0]
            h.upsert(
                "graph_nodes",
                {
                    "id": node_id,
                    "user_id": USER_ACTIVE,
                    "course_id": course_id,
                    "concept_name": concept,
                    "subject": subject,
                    "mastery_score": score,
                    "mastery_tier": tier_for(score),
                },
                on_conflict="user_id,course_id,concept_name",
            )

    for edge_id, src_id, tgt_id, rel_type, strength in _GRAPH_EDGES:
        h.upsert(
            "graph_edges",
            {
                "id": edge_id,
                "user_id": USER_ACTIVE,
                "source_node_id": src_id,
                "target_node_id": tgt_id,
                "relationship_type": rel_type,
                "strength": strength,
            },
            on_conflict="user_id,source_node_id,target_node_id,relationship_type",
        )

    for node_id, event_id, delta, reason in _MASTERY_EVENTS:
        h.insert_if_absent(
            "node_mastery_events",
            event_id,
            {"node_id": node_id, "delta": delta, "reason": reason},
        )


# (cat_id, enrollment_id, name, weight, drop_lowest)
_CATEGORIES = [
    ("rich-cat-cs-f25-hw", ENR_ACTIVE_CS_F25, "Homework", 0.4, 1),
    ("rich-cat-cs-f25-exams", ENR_ACTIVE_CS_F25, "Exams", 0.6, 0),
    ("rich-cat-cs-s26-hw", ENR_ACTIVE_CS_S26, "Homework", 0.5, 0),
    ("rich-cat-cs-s26-proj", ENR_ACTIVE_CS_S26, "Projects", 0.5, 0),
    ("rich-cat-math-s26-exams", ENR_ACTIVE_MATH_S26, "Exams", 0.7, 0),
    ("rich-cat-math-s26-hw", ENR_ACTIVE_MATH_S26, "Homework", 0.3, 0),
    ("rich-cat-bio-f25-labs", ENR_ACTIVE_BIO_F25, "Labs", 0.5, 1),
    ("rich-cat-bio-f25-exams", ENR_ACTIVE_BIO_F25, "Exams", 0.5, 0),
    ("rich-cat-eng-su26-proj", ENR_ACTIVE_ENG_SU26, "Projects", 1.0, 0),
]

# (asg_id, enrollment_id, category_id, title, due_date, assignment_type, source,
#  points_possible, points_earned). points_earned=None => ungraded.
_ASSIGNMENTS = [
    ("rich-asg-cs-f25-hw1", ENR_ACTIVE_CS_F25, "rich-cat-cs-f25-hw",
     "Homework 1: Variables", "2025-09-05", "homework", "syllabus", "100", "88"),
    ("rich-asg-cs-f25-hw2", ENR_ACTIVE_CS_F25, "rich-cat-cs-f25-hw",
     "Homework 2: Control Flow", "2025-09-19", "homework", "manual", "100", None),
    ("rich-asg-cs-f25-mid", ENR_ACTIVE_CS_F25, "rich-cat-cs-f25-exams",
     "Midterm Exam", "2025-10-15", "exam", "syllabus", "100", "91"),
    ("rich-asg-cs-s26-quiz1", ENR_ACTIVE_CS_S26, "rich-cat-cs-s26-hw",
     "Pop Quiz: Recursion", "2026-02-10", "quiz", "manual", "20", "18"),
    ("rich-asg-cs-s26-proj1", ENR_ACTIVE_CS_S26, "rich-cat-cs-s26-proj",
     "Final Project Proposal", "2026-08-01", "project", "manual", "50", None),
    ("rich-asg-math-s26-hw1", ENR_ACTIVE_MATH_S26, "rich-cat-math-s26-hw",
     "Problem Set 1", "2026-02-01", "homework", "manual", "40", "36"),
    ("rich-asg-math-s26-mid", ENR_ACTIVE_MATH_S26, "rich-cat-math-s26-exams",
     "Midterm Exam", "2026-03-02", "exam", "syllabus", "100", "79"),
    ("rich-asg-bio-f25-lab1", ENR_ACTIVE_BIO_F25, "rich-cat-bio-f25-labs",
     "Lab 1: Microscopy", "2025-09-15", "project", "manual", "50", "47"),
    ("rich-asg-bio-f25-reading", ENR_ACTIVE_BIO_F25, "rich-cat-bio-f25-labs",
     "Chapter 3 Reading Quiz", "2025-09-22", "reading", "manual", "20", "16"),
    ("rich-asg-eng-su26-essay", ENR_ACTIVE_ENG_SU26, "rich-cat-eng-su26-proj",
     "Essay Draft: Rhetorical Analysis", "2026-08-15", "other", "manual", "100", None),
    # Graded + past-due so the only curved enrollment (ENG150, curve_mode="curved")
    # has at least one gradable data point to exercise curve computation.
    ("rich-asg-eng-su26-journal1", ENR_ACTIVE_ENG_SU26, "rich-cat-eng-su26-proj",
     "Journal Entry 1: Reflection", "2026-06-20", "homework", "manual", "20", "18"),
]


def seed_gradebook() -> None:
    for cat_id, enr_id, name, weight, drop_lowest in _CATEGORIES:
        h.insert_if_absent(
            "gradebook_categories",
            cat_id,
            {
                "enrollment_id": enr_id,
                "name": name,
                "weight": weight,
                "drop_lowest": drop_lowest,
            },
        )

    for asg_id, enr_id, cat_id, title, due, atype, source, possible, earned in _ASSIGNMENTS:
        h.insert_if_absent(
            "assignments",
            asg_id,
            {
                "enrollment_id": enr_id,
                "category_id": cat_id,
                "title": title,
                "due_date": due,
                "assignment_type": atype,
                "source": source,
                # 🔒 points (numeric semantics; decrypt_numeric at read). None (ungraded)
                # stays None — encrypt_if_present(None) is a no-op.
                "points_possible": encrypt_if_present(str(possible)),
                "points_earned": encrypt_if_present(str(earned)) if earned is not None else None,
            },
        )


ROOM_STUDY = "rich-room-study-group"
ROOM_GENERAL = "rich-room-general"

_ROOMS = [
    (ROOM_STUDY, "CS101 Study Group", "RICH-CS101", USER_ACTIVE),
    (ROOM_GENERAL, "Rich Local Lounge", "RICH-LOUNGE", USER_SECOND),
]

# (room_id, user_id) — both active + second users in both rooms.
_ROOM_MEMBERS = [
    (ROOM_STUDY, USER_ACTIVE),
    (ROOM_STUDY, USER_SECOND),
    (ROOM_GENERAL, USER_ACTIVE),
    (ROOM_GENERAL, USER_SECOND),
]

# (message id — fixed UUID literal, room_id, user_id, user_name, text)
_ROOM_MESSAGES = [
    ("11111111-1111-4111-8111-000000000001", ROOM_STUDY, USER_ACTIVE, "Rich Active",
     "Anyone up for reviewing recursion before the midterm?"),
    ("11111111-1111-4111-8111-000000000002", ROOM_STUDY, USER_SECOND, "Sam Second",
     "I'm in — want to do it over the summer offering room?"),
    ("11111111-1111-4111-8111-000000000003", ROOM_STUDY, USER_ACTIVE, "Rich Active",
     "Let's meet Thursday at 6pm in Hall A."),
    ("11111111-1111-4111-8111-000000000004", ROOM_GENERAL, USER_SECOND, "Sam Second",
     "Welcome to the Rich Local Lounge!"),
    ("11111111-1111-4111-8111-000000000005", ROOM_GENERAL, USER_ACTIVE, "Rich Active",
     "Glad to be here."),
    ("11111111-1111-4111-8111-000000000006", ROOM_GENERAL, USER_SECOND, "Sam Second",
     "Anyone taking HIST200 this fall?"),
]


def seed_rooms() -> None:
    for room_id, name, invite_code, created_by in _ROOMS:
        h.upsert(
            "rooms",
            # owner_id mirrors create_room's semantics (#405): ownership starts
            # with the creator. 0038 makes it NOT NULL and SQL has no
            # cross-column default, so the seed must set it explicitly or a
            # from-empty replay fails on the INSERT.
            {"id": room_id, "name": name, "invite_code": invite_code,
             "created_by": created_by, "owner_id": created_by},
            on_conflict="invite_code",
        )

    for room_id, user_id in _ROOM_MEMBERS:
        h.upsert(
            "room_members",
            {"room_id": room_id, "user_id": user_id},
            on_conflict="room_id,user_id",
        )

    for msg_id, room_id, user_id, user_name, text in _ROOM_MESSAGES:
        h.insert_if_absent(
            "room_messages",
            msg_id,
            {
                "room_id": room_id,
                "user_id": user_id,
                "user_name": user_name,
                # 🔒 text
                "text": encrypt_if_present(text),
            },
        )


# (note_id, user_id, offering_id, title, body, tags)
_NOTES = [
    ("rich-note-cs-week1", USER_ACTIVE, OFF_CS_F25, "Week 1 — Variables",
     "A variable binds a name to a value. Types: int, str, bool, float.",
     ["week1", "basics"]),
    ("rich-note-math-vectors", USER_ACTIVE, OFF_MATH_S26, "Vectors Overview",
     "A vector has magnitude and direction; can be added componentwise.",
     ["vectors", "week2"]),
    ("rich-note-hist-timeline", USER_SECOND, OFF_HIST_F25, "1500-1600 Timeline",
     "Key events: printing press spread, age of exploration, Reformation.",
     ["timeline"]),
]

# (doc_id, user_id, offering_id, file_name, category, summary, concept_name,
#  concept_description, extracted_text)
_DOCUMENTS = [
    ("rich-doc-cs-syllabus", USER_ACTIVE, OFF_CS_F25, "cs101-syllabus.pdf", "syllabus",
     "CS101 syllabus: weekly homework, one midterm, final project.",
     "Variables", "Named storage locations for values.",
     "CS101 — Introduction to Computer Science. Weekly homework due Fridays..."),
    ("rich-doc-math-notes", USER_ACTIVE, OFF_MATH_S26, "linear-algebra-notes.pdf", "lecture_notes",
     "Lecture notes covering vectors, matrices, and linear transformations.",
     "Vectors", "Objects with magnitude and direction in a vector space.",
     "Lecture 1: Vectors are elements of a vector space over a field..."),
    ("rich-doc-bio-studyguide", USER_ACTIVE, OFF_BIO_F25, "cell-bio-study-guide.pdf", "study_guide",
     "Study guide for the cell biology midterm: membrane, mitochondria, DNA.",
     "Cell Membrane", "A selectively permeable barrier surrounding the cell.",
     "Study guide: the plasma membrane regulates what enters and exits the cell..."),
]


def seed_notes_documents() -> None:
    for note_id, user_id, off_id, title, body, tags in _NOTES:
        h.insert_if_absent(
            "notes",
            note_id,
            {
                "user_id": user_id,
                "offering_id": off_id,
                # 🔒 title / body
                "title": encrypt_if_present(title),
                "body": encrypt_if_present(body),
                "tags": tags,
            },
        )

    for doc_id, user_id, off_id, file_name, category, summary, c_name, c_desc, extracted in _DOCUMENTS:
        h.insert_if_absent(
            "documents",
            doc_id,
            {
                "user_id": user_id,
                "offering_id": off_id,
                "file_name": file_name,
                "category": category,
                # 🔒 summary / concept_notes / extracted_text
                "summary": encrypt_if_present(summary),
                "concept_notes": encrypt_json([{"name": c_name, "description": c_desc}]),
                "extracted_text": encrypt_if_present(extracted),
            },
        )


# (fc_id, user_id, offering_id, topic, front, back) — 🔒 front/back, grouped by topic.
_FLASHCARDS = [
    ("rich-fc-cs-1", USER_ACTIVE, OFF_CS_F25, "CS Basics",
     "What is a variable?", "A named storage location for a value."),
    ("rich-fc-cs-2", USER_ACTIVE, OFF_CS_F25, "CS Basics",
     "What is a function?", "A reusable block of code that performs a task."),
    ("rich-fc-cs-3", USER_ACTIVE, OFF_CS_F25, "CS Basics",
     "What is recursion?", "A function that calls itself to solve smaller subproblems."),
    ("rich-fc-math-1", USER_ACTIVE, OFF_MATH_S26, "Linear Algebra",
     "What is a vector?", "An element of a vector space with magnitude and direction."),
    ("rich-fc-math-2", USER_ACTIVE, OFF_MATH_S26, "Linear Algebra",
     "What is a matrix?", "A rectangular array of numbers representing a linear map."),
    ("rich-fc-math-3", USER_ACTIVE, OFF_MATH_S26, "Linear Algebra",
     "What is an eigenvalue?", "A scalar λ such that Av = λv for some nonzero vector v."),
]


def seed_flashcards() -> None:
    for fc_id, user_id, off_id, topic, front, back in _FLASHCARDS:
        h.insert_if_absent(
            "flashcards",
            fc_id,
            {
                "user_id": user_id,
                "offering_id": off_id,
                "topic": topic,
                # 🔒 front / back (#518)
                "front": encrypt_if_present(front),
                "back": encrypt_if_present(back),
            },
        )


# (guide_id, user_id, offering_id, exam_id, generated_at, content)
#
# A CACHED guide, so /study's "Recent guides" rail has an entry to open without
# any generation: the guide GET returns a cache hit on (user, offering, exam)
# before it ever reaches the study_guide agent, which has no function-mode
# handler. `exam_id` points at the real fall-2025 CS101 exam assignment so the
# exam picker can resolve the same row the rail entry opens.
_STUDY_GUIDES = [
    ("rich-guide-cs-f25-mid", USER_ACTIVE, OFF_CS_F25, "rich-asg-cs-f25-mid",
     "2026-03-01T12:00:00Z",
     {
         "exam": "Midterm Exam",
         "due_date": "2025-10-15",
         "overview": "Covers variables, control flow, and functions.",
         "topics": [
             {
                 "name": "Variables",
                 "importance": "Every later topic builds on binding names to values.",
                 "concepts": ["Assignment", "Scope"],
             },
             {
                 "name": "Recursion",
                 "importance": "The midterm's hardest questions are recursive traces.",
                 "concepts": ["Base case", "Call stack"],
             },
         ],
     }),
]


def seed_study_guides() -> None:
    for guide_id, user_id, off_id, exam_id, generated_at, content in _STUDY_GUIDES:
        h.insert_if_absent(
            "study_guides",
            guide_id,
            {
                "user_id": user_id,
                "offering_id": off_id,
                "exam_id": exam_id,
                "generated_at": generated_at,
                # 🔒 content (#518)
                "content": encrypt_json(content),
            },
        )


def seed_room_summaries() -> None:
    # #518: room_summaries.summary is 🔒. PK is room_id (no id column), so this
    # can't go through insert_if_absent.
    if not table("room_summaries").select("room_id", filters={"room_id": f"eq.{ROOM_STUDY}"}):
        table("room_summaries").insert({
            "room_id": ROOM_STUDY,
            "summary": encrypt_if_present("The group is reviewing recursion before the midterm."),
            "member_hash": "rich-member-hash-v1",
        })
        h.record("room_summaries", created=True)
    else:
        h.record("room_summaries", created=False)


# (qa_id, concept_node_id, difficulty, score, total, questions_json, answers_json, completed_at)
_QUIZ_ATTEMPTS = [
    ("rich-qa-cs-variables-1", "rich-node-cs-variables", "easy", 9, 10,
     [{"q": "What keyword declares a variable in Python?", "a": "="}],
     [{"q": "What keyword declares a variable in Python?", "given": "=", "correct": True}],
     "2026-05-01T12:00:00Z"),
    ("rich-qa-cs-recursion-1", "rich-node-cs-recursion", "medium", 6, 10,
     [{"q": "What must every recursive function have?", "a": "A base case"}],
     [{"q": "What must every recursive function have?", "given": "A base case", "correct": True}],
     "2026-05-01T12:00:00Z"),
    ("rich-qa-math-eigen-1", "rich-node-math-eigenvalues", "hard", None, None,
     [{"q": "What equation defines an eigenvalue?", "a": "Av = λv"}],
     None, None),
]


# ── offering_concept_stats (#553) ─────────────────────────────────────────
#
# Class-level aggregates, keyed on `course_offerings.id` — a DIFFERENT
# keyspace from the abstract `courses.id` the graph carries. #553 was the
# quiz's misconceptions tool filtering this table's `offering_id` with a
# course id, which matched nothing for every student indefinitely while
# looking exactly like a class that had no misconceptions yet.
#
# The rows are shaped so a test can tell a real fix from a coincidence:
#
#   * OFF_CS_F25 and OFF_CS_S26 are BOTH offerings of the same abstract CS
#     course, and the active user is enrolled in both — so a fix that
#     resolves only one "current" offering still loses half the rows.
#   * OFF_HIST_F25 belongs to a course the active user is NOT enrolled in.
#     Its misconception text must never reach them; that is the negative
#     half of the assertion, and it is what stops a fix from "working" by
#     simply dropping the offering filter altogether.
#   * One row carries an EMPTY array: the aggregation writes a stats row per
#     concept as soon as a class has activity and only fills the array when
#     it has something to say (0 of 72 rows on staging and 0 of 73 on prod
#     carried text on 2026-08-22). Seeding that state keeps the empty-vs-
#     absent distinction exercised.
#
# (stats_id, offering_id, concept_name, misconceptions)
_OFFERING_CONCEPT_STATS = [
    ("rich-ocs-cs-f25-recursion", OFF_CS_F25, "Recursion",
     ["Recursion always costs more memory than a loop",
      "A base case is optional if the input shrinks"]),
    ("rich-ocs-cs-f25-pointers", OFF_CS_F25, "Pointers and Memory",
     ["Freeing a pointer also clears the variable holding it"]),
    ("rich-ocs-cs-s26-controlflow", OFF_CS_S26, "Control Flow",
     ["`else if` evaluates every branch before choosing one"]),
    # Same class, no text yet — a stats row is not the same as a finding.
    ("rich-ocs-cs-s26-variables", OFF_CS_S26, "Variables and Types", []),
    # A class the active user is NOT in. Must never leak into their prompt.
    ("rich-ocs-hist-f25-sources", OFF_HIST_F25, "Primary Sources",
     ["A primary source is any source written by a historian"]),
]


def seed_offering_concept_stats() -> None:
    for stats_id, off_id, concept, misconceptions in _OFFERING_CONCEPT_STATS:
        h.insert_if_absent(
            "offering_concept_stats",
            stats_id,
            {
                "offering_id": off_id,
                "concept_name": concept,
                "student_count": 4,
                "avg_mastery_score": 0.55,
                "pct_mastered": 0.25,
                "pct_struggling": 0.5,
                "pct_unexplored": 0.25,
                "common_misconceptions": misconceptions,
                # No `effective_explanations` key — #572, see
                # services/course_context_service.py::_parse_quiz_context_to_arrays.
                "prerequisite_gaps": [],
            },
        )


def seed_quiz() -> None:
    for qa_id, node_id, difficulty, score, total, questions, answers, completed_at in _QUIZ_ATTEMPTS:
        h.insert_if_absent(
            "quiz_attempts",
            qa_id,
            {
                "user_id": USER_ACTIVE,
                "concept_node_id": node_id,
                "score": score,
                "total": total,
                "difficulty": difficulty,
                # 🔒 questions_json / answers_json
                "questions_json": encrypt_json(questions),
                "answers_json": encrypt_json(answers) if answers is not None else None,
                "completed_at": completed_at,
            },
        )

    # #521: quiz_context is 🔒 — one row so the roundtrip test has a baseline.
    h.insert_if_absent(
        "quiz_context",
        "rich-qc-cs-variables",
        {
            "user_id": USER_ACTIVE,
            "concept_node_id": "rich-node-cs-variables",
            "context_json": encrypt_json(
                {"misconceptions": ["confuses = with =="], "asked": 2}
            ),
        },
    )


# #520: feedback/issue_reports are 🔒 (comment/topic/description) — seed them
# encrypted so the roundtrip test + ciphertext oracle have baseline rows.
def seed_feedback() -> None:
    h.insert_if_absent(
        "feedback",
        "rich-fb-1",
        {
            "user_id": USER_ACTIVE,
            "type": "global",
            "rating": 4,
            "selected_options": ["tutor"],
            "comment": encrypt_if_present("The tutor cited the wrong lecture."),
            "topic": encrypt_if_present("chat"),
        },
    )
    h.insert_if_absent(
        "issue_reports",
        "rich-issue-1",
        {
            "user_id": USER_ACTIVE,
            "topic": encrypt_if_present("Upload stuck"),
            "description": encrypt_if_present("Syllabus upload spins forever."),
            "screenshot_urls": [],
        },
    )


SESS_CS_RECURSION = "rich-sess-cs-recursion"
SESS_MATH_VECTORS = "rich-sess-math-vectors"

_SESSIONS = [
    (SESS_CS_RECURSION, USER_ACTIVE, OFF_CS_F25, "socratic", "Recursion",
     "Understanding Recursion",
     {"bullets": ["Discussed base cases", "Practiced factorial and fibonacci"]}),
    (SESS_MATH_VECTORS, USER_ACTIVE, OFF_MATH_S26, "expository", "Vectors",
     "Vector Basics",
     {"bullets": ["Covered vector addition", "Covered the dot product"]}),
]

# (msg_id, session_id, role, content)
_MESSAGES = [
    ("rich-msg-cs-recursion-1", SESS_CS_RECURSION, "user", "Can you explain recursion?"),
    ("rich-msg-cs-recursion-2", SESS_CS_RECURSION, "assistant",
     "Sure! Recursion is when a function calls itself to solve a smaller version "
     "of the same problem."),
    ("rich-msg-cs-recursion-3", SESS_CS_RECURSION, "user", "What's a base case?"),
    ("rich-msg-cs-recursion-4", SESS_CS_RECURSION, "assistant",
     "The base case is the condition where the function stops calling itself."),
    ("rich-msg-math-vectors-1", SESS_MATH_VECTORS, "user", "What is a dot product?"),
    ("rich-msg-math-vectors-2", SESS_MATH_VECTORS, "assistant",
     "The dot product of two vectors is the sum of the products of their "
     "corresponding components."),
]


def seed_sessions() -> None:
    for sess_id, user_id, off_id, mode, topic, name, summary in _SESSIONS:
        h.insert_if_absent(
            "sessions",
            sess_id,
            {
                "user_id": user_id,
                "offering_id": off_id,
                "mode": mode,
                "topic": topic,
                "name": name,
                # 🔒 summary_json
                "summary_json": encrypt_json(summary),
            },
        )

    for msg_id, sess_id, role, content in _MESSAGES:
        h.insert_if_absent(
            "messages",
            msg_id,
            {
                "session_id": sess_id,
                "role": role,
                # 🔒 content
                "content": encrypt_if_present(content),
            },
        )


def _seed_embedding(text: str) -> list[float]:
    """A deterministic unit vector of the store's dimension for `text` — what
    the RETRIEVAL_DOCUMENT embedding stands in for on a local seed (no model
    call; a NULL embedding is a `ragstore` finding, #482)."""
    import hashlib
    import math

    from services.chunk_ids import EMBED_OUTPUT_DIM as _OUTPUT_DIM

    raw: list[float] = []
    counter = 0
    while len(raw) < _OUTPUT_DIM:
        digest = hashlib.sha256(f"{counter}::{text}".encode()).digest()
        raw.extend(b / 255.0 - 0.5 for b in digest)
        counter += 1
    raw = raw[:_OUTPUT_DIM]
    norm = math.sqrt(sum(v * v for v in raw))
    return [v / norm for v in raw]


def seed_learning_loop() -> None:
    """PKG-13: the loop users — the staff/QA toggle, a prerequisite chain each,
    an indexed shared course document, shared encrypted check items drafted from
    it, and the capped user's spend and due card. Imports are function-local:
    `learning.*`, the `config` budget names, the RAG helpers and the
    function-handler constants are only needed here. Nothing here imports the
    SDK (PKG-13 fix round): this runs in a fresh process before EVERY
    Playwright test, and agents.function_handlers_e2e / services.rag_service
    pull pydantic-ai and google-genai (~2.4 s a test) — the handler constants
    are read from the module's source (db.e2e_handler_constants) and the chunk
    id from services.chunk_ids (rag_service re-exports it)."""
    from datetime import datetime, timedelta, timezone

    import config
    from db.e2e_handler_constants import read_constants
    from learning.checks import question_hash
    from learning.params import CHECK_ITEM_DIFFICULTIES, EDGE_PREREQ_SOURCE_IS_PREREQ
    from services.chunk_ids import chunk_id
    from services.chunk_visibility import SHARED
    from services.graph_service import _normalize_concept

    E2E_LOOP_FINAL_ANSWER, E2E_LOOP_PROBE_PROMPT, E2E_LOOP_REFERENCE = read_constants(
        "E2E_LOOP_FINAL_ANSWER", "E2E_LOOP_PROBE_PROMPT", "E2E_LOOP_REFERENCE"
    )

    for uid in LOOP_USERS:
        # share_class_context: the uploader's consent the shared chunks rest on (#629).
        h.upsert(
            "user_settings",
            {"user_id": uid, "learning_loop_beta": True, "share_class_context": True},
            on_conflict="user_id",
        )
        for slug, concept, _ in LOOP_NODES:
            h.upsert(
                "graph_nodes",
                {
                    "id": loop_node_id(uid, slug),
                    "user_id": uid,
                    "course_id": COURSE_CS,
                    "concept_name": concept,
                    "subject": concept.split()[0],
                    "mastery_score": 0.0,
                    "mastery_tier": tier_for(0.0),
                },
                on_conflict="user_id,course_id,concept_name",
            )
        for (pre, _, _), (dep, _, _) in zip(LOOP_NODES, LOOP_NODES[1:]):
            pre_id, dep_id = loop_node_id(uid, pre), loop_node_id(uid, dep)
            src, tgt = (pre_id, dep_id) if EDGE_PREREQ_SOURCE_IS_PREREQ else (dep_id, pre_id)
            h.upsert(
                "graph_edges",
                {
                    "id": f"{pre_id.replace('rich-node-', 'rich-edge-')}-{dep}",
                    "user_id": uid,
                    "source_node_id": src,
                    "target_node_id": tgt,
                    "relationship_type": "prerequisite",
                    "strength": 0.9,
                },
                on_conflict="user_id,source_node_id,target_node_id,relationship_type",
            )

    # The shared course document and its index (spec §13 A23): course_material
    # above MIN_SHARE_CONFIDENCE, uploader consenting → shared chunks, exactly
    # the rows services/document_indexing.py writes — content-addressed ids over
    # the PLAINTEXT, 🔒 chunk_text encrypted after hashing (ADR 0025), an
    # embedding, and the contributor ledger row (#629).
    notes = " ".join(sentence for _, _, sentence in LOOP_NODES)
    chunk_ids: dict[str, str] = {}
    for i, (slug, concept, sentence) in enumerate(LOOP_NODES):
        text = f"{concept}. {sentence}"
        cid = chunk_id(COURSE_CS_CODE, text, visibility=SHARED)
        chunk_ids[slug] = cid
        h.upsert(
            "course_chunks",
            {
                "id": cid,
                "course_id": COURSE_CS_CODE,
                "doc_id": LOOP_DOC_ID,
                "uploader_id": USER_LOOP,
                "chunk_index": i,
                "chunk_text": encrypt_if_present(text),  # 🔒
                "chunk_hash": cid,
                "embedding": _seed_embedding(text),
                "category": LOOP_DOC_CATEGORY,
                "visibility": SHARED,
                "semester": "current",
                "section_id": None,
                "school": "",
            },
            on_conflict="id",
        )
        h.upsert(
            "course_chunk_contributors",
            {"chunk_id": cid, "user_id": USER_LOOP},
            on_conflict="chunk_id,user_id",
        )
    h.insert_if_absent(
        "documents",
        LOOP_DOC_ID,
        {
            "user_id": USER_LOOP,
            "offering_id": OFF_CS_S26,
            "file_name": "binary-and-bits-notes.pdf",
            "category": LOOP_DOC_CATEGORY,
            # 🔒 summary / concept_notes / extracted_text
            "summary": encrypt_if_present("Notes on binary numbers, bitwise operators and two's complement."),
            "concept_notes": encrypt_json(
                [{"name": concept, "description": sentence} for _, concept, sentence in LOOP_NODES]
            ),
            "extracted_text": encrypt_if_present(notes),
            "shareability": "course_material",
            "shareability_confidence": LOOP_DOC_SHAREABILITY_CONFIDENCE,
            "index_status": "indexed",
            "index_chunk_count": len(LOOP_NODES),
        },
    )

    # Check items are course assets (spec §13 A2): keyed on (course_id,
    # concept_key), written ONCE, served to both loop users through their nodes'
    # concept names. A34: the reference closes with the structured final answer.
    for slug, concept, _ in LOOP_NODES:
        concept_key = _normalize_concept(concept)
        for fmt in SEED_LOOP_FORMATS:
            for difficulty in CHECK_ITEM_DIFFICULTIES:
                prompt = f"{E2E_LOOP_PROBE_PROMPT} [{concept}, {fmt}, difficulty {difficulty}]"
                h.upsert(
                    "check_items",
                    {
                        "id": f"rich-check-{slug}-{fmt}-d{difficulty}",
                        "course_id": COURSE_CS,
                        "concept_key": concept_key,
                        "document_id": LOOP_DOC_ID,
                        "format": fmt,
                        "difficulty": difficulty,
                        "prompt": encrypt_if_present(prompt),  # 🔒
                        "reference_answer": encrypt_if_present(E2E_LOOP_REFERENCE),  # 🔒
                        "final_answer": encrypt_if_present(E2E_LOOP_FINAL_ANSWER),  # 🔒 A34
                        "rubric_json": encrypt_json([  # 🔒
                            {"id": "r1", "text": "States the seeded final answer."},
                            {"id": "r2", "text": f"Names {concept}."},
                        ]),
                        "common_wrong_json": encrypt_json([  # 🔒
                            {"key": "wrong_token", "text": "Gives a different answer."},
                        ]),
                        "source_chunk_ids": [chunk_ids[slug]],
                        "source_document_ids": [LOOP_DOC_ID],
                        "question_hash": question_hash(prompt),
                        "graded": False,
                    },
                    on_conflict="course_id,concept_key,question_hash",
                )

    # rich-user-capped (spec §13 A26): today's spend past the novice allowance,
    # so the §3.5 hard level applies in every band. ONE row — far below
    # LEARN_RATE_LIMIT_PER_MIN, so the journey hits the $ cap and not the rate
    # limit — on a tutor slot, so the grader cap is untouched. created_at is
    # stamped NOW on every run and the row is upserted (PKG-13 fix round): with
    # insert-if-absent a stack seeded once (make e2e-up, make explore, any run
    # without the per-test truncate) kept yesterday's timestamp after UTC
    # midnight, and the "capped" user was silently no longer capped.
    h.upsert(
        "llm_usage",
        {
            "id": "rich-usage-capped-1",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "user_id": USER_CAPPED,
            "feature": "learn_loop",
            "task": "loop_tutor",
            "model": "gemini-2.5-flash",
            "provider": "gemini",
            "cost_usd": round(
                config.STUDENT_DAILY_BUDGET_USD
                * config.BUDGET_NOVICE_MULTIPLIER
                * SEED_CAPPED_SPEND_FACTOR,
                6,
            ),
        },
        on_conflict="id",
    )
    card_id, front, back = CAPPED_FLASHCARD
    h.insert_if_absent(
        "flashcards",
        card_id,
        {
            "user_id": USER_CAPPED,
            "offering_id": OFF_CS_S26,
            "topic": LOOP_NODES[0][1],
            # 🔒 front / back (#518)
            "front": encrypt_if_present(front),
            "back": encrypt_if_present(back),
            "due_at": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),  # due (PKG-11)
        },
    )


_SUMMARY_ORDER = [
    "schools", "courses", "course_offerings", "users", "user_profiles", "user_roles",
    "user_settings",
    "enrollments", "graph_nodes", "graph_edges", "node_mastery_events",
    "gradebook_categories", "assignments", "rooms", "room_members", "room_messages",
    "room_summaries",
    "notes", "documents", "course_chunks", "course_chunk_contributors", "check_items",
    "flashcards", "study_guides", "quiz_attempts", "quiz_context",
    "sessions", "messages", "feedback", "issue_reports",
    "offering_concept_stats", "llm_usage",
]


def main() -> None:
    _guard_local()
    h.reset_counts()
    seed_school()
    seed_courses()
    seed_offerings()
    seed_users()
    seed_enrollments()
    seed_graph()
    seed_gradebook()
    seed_rooms()
    seed_notes_documents()
    seed_flashcards()
    seed_study_guides()
    seed_room_summaries()
    seed_quiz()
    seed_offering_concept_stats()
    seed_feedback()
    seed_sessions()
    seed_learning_loop()
    h.print_summary(_SUMMARY_ORDER, "Seed summary (rich local dataset):")


if __name__ == "__main__":
    main()
