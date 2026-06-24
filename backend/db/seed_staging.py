"""Idempotent STAGING demo seed for the DB modular redesign (#258).

⚠️  STAGING ONLY — FAKE DATA. Never run against production.

This lays a small, self-contained demo dataset on top of the *new*
(post-0019–0027) schema so the live staging app renders the knowledge graph,
gradebook, and courses-with-term against a real database. Migrations 0019–0027
must already be applied and the canonical ``terms`` (fall-2025 / spring-2026 /
summer-2026 / fall-2026) already seeded (0019); this seed only *reads* those
terms and adds demo rows around them. It never touches, duplicates, or depends
on the real course catalog.

Idempotent: every row uses a deterministic ``seed-…`` id and is written via
upsert-on-UNIQUE or insert-if-absent, so re-running adds nothing and never errors.

Safety: all DB access goes through ``db/connection.py::table()`` (configured via
env only — no hardcoded URLs/keys, no secrets printed). 🔒 columns are written
through ``services.encryption.encrypt_if_present`` so they land encrypted with
whatever ``ENCRYPTION_KEY`` the staging env provides.

Run (from ``backend/`` with staging env loaded):

    python -m db.seed_staging
"""
from __future__ import annotations

import os
import sys
from collections import defaultdict

# Allow ``python db/seed_staging.py`` as well as ``python -m db.seed_staging``.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import get_mastery_tier  # noqa: E402  (tier ↔ score stay consistent)
from db.connection import table  # noqa: E402  (module-level; patched in tests)
from services.encryption import encrypt_if_present  # noqa: E402

# ─── Deterministic ids (everything namespaced `seed-…`) ──────────────────────

SCHOOL_ID = "seed-school-demo"

# Abstract courses (catalog) keyed on the demo school.
COURSE_CS = "seed-course-cs101"
COURSE_MATH = "seed-course-math210"
COURSE_BIO = "seed-course-bio110"

# Canonical terms seeded by 0019 — referenced by id, never written here.
TERM_FALL_2025 = "fall-2025"
TERM_SPRING_2026 = "spring-2026"

# Offerings (course taught in a term). CS101 is offered in BOTH terms so that
# graph mastery (keyed on the abstract course) is cumulative across terms.
OFF_CS_FALL = "seed-off-cs101-fall2025"
OFF_CS_SPRING = "seed-off-cs101-spring2026"
OFF_MATH = "seed-off-math210-spring2026"
OFF_BIO = "seed-off-bio110-fall2025"

USER_ID = "seed-user-demo"

# Enrollments (demo user → offering). CS101 in both terms.
ENR_CS_FALL = "seed-enr-cs101-fall2025"
ENR_CS_SPRING = "seed-enr-cs101-spring2026"
ENR_MATH = "seed-enr-math210-spring2026"
ENR_BIO = "seed-enr-bio110-fall2025"


# ─── Idempotency helpers ─────────────────────────────────────────────────────

_counts: dict[str, dict[str, int]] = defaultdict(lambda: {"created": 0, "skipped": 0})


def _record(table_name: str, created: bool) -> None:
    _counts[table_name]["created" if created else "skipped"] += 1


def _upsert(table_name: str, row: dict, on_conflict: str) -> None:
    """Upsert a single row on its natural UNIQUE key.

    merge-duplicates makes a re-run a no-op (same content, same key). We still
    track created-vs-skipped via a pre-check on the conflict key for an honest
    summary, but the write itself is the source of truth for idempotency.
    """
    exists = _exists_by(table_name, {k: row[k] for k in on_conflict.split(",")})
    table(table_name).upsert(row, on_conflict=on_conflict)
    _record(table_name, created=not exists)


def _insert_if_absent(table_name: str, row_id: str, row: dict) -> None:
    """Insert a row keyed on a deterministic id, only if that id is absent.

    For tables with no natural UNIQUE (enrollments, gradebook_categories,
    assignments, documents, notes, node_mastery_events) this is what keeps a
    re-run from duplicating — especially the append-only node_mastery_events.
    """
    if _exists_by(table_name, {"id": row_id}):
        _record(table_name, created=False)
        return
    table(table_name).insert({"id": row_id, **row})
    _record(table_name, created=True)


def _exists_by(table_name: str, eq_filters: dict) -> bool:
    filters = {col: f"eq.{val}" for col, val in eq_filters.items()}
    rows = table(table_name).select("id", filters=filters, limit=1) or []
    return len(rows) > 0


# ─── Seed steps ──────────────────────────────────────────────────────────────


def seed_school() -> None:
    _upsert(
        "schools",
        {"id": SCHOOL_ID, "name": "Sapling Demo University", "slug": "sapling-demo"},
        on_conflict="slug",
    )


def seed_courses() -> None:
    courses = [
        (COURSE_CS, "CS101", "Intro to Computer Science", "Computer Science", 3,
         "Foundations of programming and computational thinking."),
        (COURSE_MATH, "MATH210", "Linear Algebra", "Mathematics", 4,
         "Vectors, matrices, and linear transformations."),
        (COURSE_BIO, "BIO110", "Cell Biology", "Biology", 3,
         "Structure and function of the living cell."),
    ]
    for cid, code, name, dept, credits, desc in courses:
        _upsert(
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


def seed_offerings() -> None:
    # CS101 in TWO terms (multi-term), MATH210 + BIO110 once each.
    # section is "" (not NULL) so the (course_id, term_id, section) UNIQUE is a
    # stable conflict target for upsert idempotency.
    offerings = [
        (OFF_CS_FALL, COURSE_CS, TERM_FALL_2025, "Dr. Ada Lovelace", "MWF 09:00", "Hall A"),
        (OFF_CS_SPRING, COURSE_CS, TERM_SPRING_2026, "Dr. Ada Lovelace", "MWF 11:00", "Hall A"),
        (OFF_MATH, COURSE_MATH, TERM_SPRING_2026, "Dr. Emmy Noether", "TTh 10:00", "Hall B"),
        (OFF_BIO, COURSE_BIO, TERM_FALL_2025, "Dr. Rosalind Franklin", "TTh 13:00", "Lab 2"),
    ]
    for oid, cid, term_id, instructor, meeting, location in offerings:
        _upsert(
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


def seed_user() -> None:
    # Slim users row (profile fields live in user_profiles after the 0024 split).
    # email is encrypted on staging.
    _upsert(
        "users",
        {
            "id": USER_ID,
            "email": encrypt_if_present("demo.student@staging.saplinglearn.com"),
            "onboarding_completed": True,
            "streak_count": 4,
            "is_approved": True,
            "auth_provider": "google",
        },
        on_conflict="id",
    )
    # 🔒 name fields via encrypt_if_present.
    _upsert(
        "user_profiles",
        {
            "user_id": USER_ID,
            "name": encrypt_if_present("Demo Student"),
            "first_name": encrypt_if_present("Demo"),
            "last_name": encrypt_if_present("Student"),
            "username": "demo-student",
            "year": "Sophomore",
            "majors": ["Computer Science"],
            "minors": ["Mathematics"],
            "learning_style": "visual",
        },
        on_conflict="user_id",
    )


def seed_enrollments() -> None:
    # Demo user enrolled in all 4 offerings, incl. CS101 in BOTH terms.
    # curve_mode ∈ {raw, curved} (0021); one curved to exercise the policy.
    enrollments = [
        (ENR_CS_FALL, OFF_CS_FALL, "#4f86f7", "Intro CS", "raw"),
        (ENR_CS_SPRING, OFF_CS_SPRING, "#4f86f7", "Intro CS (S26)", "raw"),
        (ENR_MATH, OFF_MATH, "#f7724f", "Lin Alg", "curved"),
        (ENR_BIO, OFF_BIO, "#5fbf6b", "Cell Bio", "raw"),
    ]
    for eid, off_id, color, nickname, curve_mode in enrollments:
        row = {
            "user_id": USER_ID,
            "offering_id": off_id,
            "color": color,
            "nickname": nickname,
            "curve_mode": curve_mode,
        }
        if curve_mode == "curved":
            row["curve_avg_target"] = 0.85
            row["curve_sd_delta"] = 0.05
        _insert_if_absent("enrollments", eid, row)


# Graph: keyed on the ABSTRACT course_id (mastery is cumulative across terms).
# (course_id, concept_name, mastery_score) — tier derived from score.
_GRAPH_NODES = {
    COURSE_CS: [
        ("seed-node-cs-variables", "Variables and Types", 0.9),     # mastered
        ("seed-node-cs-functions", "Functions", 0.6),               # learning
        ("seed-node-cs-recursion", "Recursion", 0.2),               # struggling
    ],
    COURSE_MATH: [
        ("seed-node-math-vectors", "Vectors", 0.8),                 # mastered
        ("seed-node-math-matrices", "Matrices", 0.5),               # learning
        ("seed-node-math-eigen", "Eigenvalues", 0.0),               # unexplored
    ],
    COURSE_BIO: [
        ("seed-node-bio-membrane", "Cell Membrane", 0.7),           # learning
        ("seed-node-bio-mitochondria", "Mitochondria", 0.55),       # learning
        ("seed-node-bio-dna", "DNA Replication", 0.15),             # struggling
    ],
}

# Within-course edges. relationship_type ∈
# {related, prerequisite, builds_on, part_of} (0023).
_GRAPH_EDGES = [
    ("seed-node-cs-variables", "seed-node-cs-functions", "prerequisite", 0.9),
    ("seed-node-cs-functions", "seed-node-cs-recursion", "builds_on", 0.8),
    ("seed-node-math-vectors", "seed-node-math-matrices", "builds_on", 0.7),
    ("seed-node-bio-membrane", "seed-node-bio-mitochondria", "related", 0.5),
]

# Append-only mastery events (0023). (node_id, event_id, delta, reason).
_MASTERY_EVENTS = [
    ("seed-node-cs-variables", "seed-evt-cs-variables-1", 0.4, "quiz: intro types"),
    ("seed-node-cs-variables", "seed-evt-cs-variables-2", 0.5, "lecture review"),
    ("seed-node-cs-functions", "seed-evt-cs-functions-1", 0.3, "homework 2"),
    ("seed-node-math-vectors", "seed-evt-math-vectors-1", 0.4, "problem set 1"),
    ("seed-node-bio-membrane", "seed-evt-bio-membrane-1", 0.35, "reading quiz"),
    ("seed-node-bio-dna", "seed-evt-bio-dna-1", 0.15, "first pass"),
]


def seed_graph() -> None:
    for course_id, nodes in _GRAPH_NODES.items():
        for node_id, concept, score in nodes:
            subject = concept.split()[0]
            _upsert(
                "graph_nodes",
                {
                    "id": node_id,
                    "user_id": USER_ID,
                    "course_id": course_id,
                    "concept_name": concept,
                    "subject": subject,
                    "mastery_score": score,
                    "mastery_tier": get_mastery_tier(score),
                },
                on_conflict="user_id,course_id,concept_name",
            )

    for src_id, tgt_id, rel_type, strength in _GRAPH_EDGES:
        edge_id = f"seed-edge-{src_id.removeprefix('seed-node-')}-{tgt_id.removeprefix('seed-node-')}"
        _upsert(
            "graph_edges",
            {
                "id": edge_id,
                "user_id": USER_ID,
                "source_node_id": src_id,
                "target_node_id": tgt_id,
                "relationship_type": rel_type,
                "strength": strength,
            },
            on_conflict="user_id,source_node_id,target_node_id,relationship_type",
        )

    for node_id, event_id, delta, reason in _MASTERY_EVENTS:
        _insert_if_absent(
            "node_mastery_events",
            event_id,
            {"node_id": node_id, "delta": delta, "reason": reason},
        )


# Gradebook: one category per enrollment; one drops its lowest.
# (enrollment_id, category_id, name, weight, drop_lowest)
_CATEGORIES = [
    (ENR_CS_FALL, "seed-cat-cs-fall-hw", "Homework", 0.4, 1),
    (ENR_CS_SPRING, "seed-cat-cs-spring-hw", "Homework", 0.4, 0),
    (ENR_MATH, "seed-cat-math-exams", "Exams", 0.6, 0),
    (ENR_BIO, "seed-cat-bio-labs", "Labs", 0.5, 0),
]

# Assignments: on enrollment + category. source ∈ {manual, syllabus};
# assignment_type ∈ {homework, exam, reading, project, quiz, other}.
# (assignment_id, enrollment_id, category_id, title, due_date, type, source, possible, earned)
_ASSIGNMENTS = [
    ("seed-asg-cs-fall-hw1", ENR_CS_FALL, "seed-cat-cs-fall-hw",
     "Homework 1: Variables", "2025-09-08", "homework", "syllabus", "100", "92"),
    ("seed-asg-cs-fall-hw2", ENR_CS_FALL, "seed-cat-cs-fall-hw",
     "Homework 2: Functions", "2025-09-22", "homework", "manual", "100", "78"),
    ("seed-asg-cs-spring-hw1", ENR_CS_SPRING, "seed-cat-cs-spring-hw",
     "Homework 1: Recursion", "2026-01-26", "homework", "manual", "100", None),
    ("seed-asg-math-mid", ENR_MATH, "seed-cat-math-exams",
     "Midterm Exam", "2026-03-02", "exam", "syllabus", "100", "88"),
    ("seed-asg-bio-lab1", ENR_BIO, "seed-cat-bio-labs",
     "Lab 1: Microscopy", "2025-09-15", "project", "manual", "50", "47"),
    ("seed-asg-bio-reading", ENR_BIO, "seed-cat-bio-labs",
     "Chapter 3 Reading Quiz", "2025-09-19", "reading", "manual", "20", "16"),
]


def seed_gradebook() -> None:
    for enr_id, cat_id, name, weight, drop_lowest in _CATEGORIES:
        _insert_if_absent(
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
        _insert_if_absent(
            "assignments",
            asg_id,
            {
                "enrollment_id": enr_id,
                "category_id": cat_id,
                "title": title,
                "due_date": due,
                "assignment_type": atype,
                "source": source,
                # 🔒 points (numeric semantics; decrypt_numeric at read).
                "points_possible": encrypt_if_present(possible),
                "points_earned": encrypt_if_present(earned),
            },
        )


def seed_study() -> None:
    # A document + a note on the CS101 fall-2025 offering so study endpoints
    # have data. category ∈ {syllabus, lecture_notes, slides, reading,
    # assignment, study_guide, other} (0025).
    _insert_if_absent(
        "documents",
        "seed-doc-cs-fall-syllabus",
        {
            "user_id": USER_ID,
            "offering_id": OFF_CS_FALL,
            "file_name": "cs101-syllabus.pdf",
            "category": "syllabus",
            # 🔒 summary / concept_notes.
            "summary": encrypt_if_present(
                "CS101 syllabus: weekly homework, one midterm, final project."
            ),
            "concept_notes": encrypt_if_present(
                "Covers variables, functions, recursion."
            ),
        },
    )
    _insert_if_absent(
        "notes",
        "seed-note-cs-fall-week1",
        {
            "user_id": USER_ID,
            "offering_id": OFF_CS_FALL,
            # 🔒 title / body.
            "title": encrypt_if_present("Week 1 — Variables"),
            "body": encrypt_if_present(
                "A variable binds a name to a value. Types: int, str, bool, float."
            ),
            "tags": ["week1", "basics"],
        },
    )


# ─── Entry point ─────────────────────────────────────────────────────────────


def _print_summary() -> None:
    print("\nSeed summary (staging demo data):")
    order = [
        "schools", "courses", "course_offerings", "users", "user_profiles",
        "enrollments", "graph_nodes", "graph_edges", "node_mastery_events",
        "gradebook_categories", "assignments", "documents", "notes",
    ]
    total_created = 0
    for name in order:
        c = _counts.get(name, {"created": 0, "skipped": 0})
        total_created += c["created"]
        print(f"  {name:22s} created={c['created']:<3d} skipped(exists)={c['skipped']}")
    print(f"  {'TOTAL created':22s} {total_created}")
    if total_created == 0:
        print("  (all rows already present — re-run was a no-op)")


def main() -> None:
    """Seed the staging demo dataset. Idempotent; safe to re-run."""
    _counts.clear()  # fresh per-run summary (also keeps re-runs in one process honest)
    seed_school()
    seed_courses()
    seed_offerings()
    seed_user()
    seed_enrollments()
    seed_graph()
    seed_gradebook()
    seed_study()
    _print_summary()


if __name__ == "__main__":
    main()
