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

from config import get_mastery_tier            # noqa: E402
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
        "learning_style": "visual",
    }),
    (USER_SECOND, "rich.second@richlocal.test", True, True, 5, {
        "name": "Sam Second", "first_name": "Sam", "last_name": "Second",
        "username": "rich-second", "year": "Senior",
        "majors": ["Biology"], "minors": [],
        "learning_style": "kinesthetic",
    }),
    (USER_NEW, "rich.new@richlocal.test", False, True, 0, {
        "name": "Newt Newman",
    }),
    (USER_PENDING, "rich.pending@richlocal.test", False, False, 0, {
        "name": "Penny Pending",
    }),
    (USER_ADMIN, "rich.admin@richlocal.test", True, True, 30, {
        "name": "Ada Admin", "first_name": "Ada", "last_name": "Admin",
        "username": "rich-admin", "year": "Staff",
        "majors": [], "minors": [],
        "learning_style": "reading_writing",
    }),
]

# Profile fields that are 🔒 (column-encrypted) vs. plaintext.
_PROFILE_ENCRYPTED_FIELDS = ("name", "first_name", "last_name")
_PROFILE_PLAIN_FIELDS = ("username", "year", "majors", "minors", "learning_style")


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
                    "mastery_tier": get_mastery_tier(score),
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


# (fc_id, user_id, offering_id, topic, front, back) — plaintext, grouped by topic.
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
                "front": front,
                "back": back,
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
                "content": content,
            },
        )


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


_SUMMARY_ORDER = [
    "schools", "courses", "course_offerings", "users", "user_profiles", "user_roles",
    "enrollments", "graph_nodes", "graph_edges", "node_mastery_events",
    "gradebook_categories", "assignments", "rooms", "room_members", "room_messages",
    "notes", "documents", "flashcards", "study_guides", "quiz_attempts", "quiz_context",
    "sessions", "messages", "feedback", "issue_reports",
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
    seed_quiz()
    seed_feedback()
    seed_sessions()
    h.print_summary(_SUMMARY_ORDER, "Seed summary (rich local dataset):")


if __name__ == "__main__":
    main()
