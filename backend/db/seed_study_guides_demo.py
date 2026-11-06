"""LOCAL-ONLY study-guide fixture: real-looking guides on the CURRENT term.

The rich seed ships exactly one study guide (CS101, Fall 2025), which is enough
to prove the cache path and nothing else: the Study screen filters by the active
semester, so on any date past that term the guide shelf reads empty until you go
hunting in the term selector.

This fills the CURRENT term instead. For each target user it:

  1. enrolls them in the Fall 2026 offering of BIO110, CS101 and MATH210
     (those offerings already exist; ENG150 is already a Fall 2026 enrollment),
  2. gives every Fall 2026 enrollment two exams — a midterm just past and a
     final ahead — so the study-guide exam picker has something to pick, and
  3. writes a cached study guide for each of those exams.

Run (from backend/, local stack up, backend/.env active):
    python -m db.seed_study_guides_demo
    python -m db.seed_study_guides_demo --user user_1019...   # one account

Idempotent and namespaced `sg-*`, so it cannot collide with the rich seed's
`rich-*` ids or the roadmap demo's `road-*` ones, and re-running rewrites
nothing it already wrote.

Why the guides are WRITTEN rather than generated: `GET /study-guide/{u}/guide`
returns a cache hit on (user, offering, exam) before it ever reaches the
study_guide agent. Seeding the cache means the shelf is populated with no model
call, no API key, and no per-run variation — the same reason the rich seed
caches its one guide.

The exams carry no category and no points on purpose. They exist for the exam
picker and the calendar; attaching them to a gradebook category would change
the weighting of courses this fixture is not about.
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db import seed_helpers as h                        # noqa: E402
from db.connection import table                         # noqa: E402
from services.encryption import encrypt_json            # noqa: E402

TERM = "fall-2026"

#: Accounts to populate: the test-login fixture user and any real local Google
#: account the seed watcher has already cloned the rich dataset onto.
DEFAULT_USERS = ["rich-user-active"]

#: Anchor every date off a fixed "today" at run time. The midterm sits just
#: behind it (a guide you can still open and review) and the final ahead of it
#: (the one the shelf should be steering you toward).
_NOW = datetime.now(timezone.utc)


def _d(days: int) -> str:
    return (_NOW + timedelta(days=days)).date().isoformat()


# (course_id, course_code, [(exam_key, exam_title, days_from_now, guide)])
_COURSES = [
    (
        "rich-course-bio110", "BIO110",
        [
            ("mid", "Midterm Exam", -12, {
                "overview": (
                    "Covers the cell's boundary and its power supply: membrane "
                    "structure and transport, then respiration and photosynthesis. "
                    "Most marks are lost on transport direction, so practise "
                    "predicting which way a solute moves before you memorise names."
                ),
                "topics": [
                    {"name": "Cell Membrane",
                     "importance": "Every transport question starts from the bilayer's selective permeability.",
                     "concepts": ["Phospholipid bilayer", "Fluid mosaic model", "Selective permeability", "Membrane proteins"]},
                    {"name": "Transport",
                     "importance": "The exam's hardest items ask which direction a solute moves and what it costs.",
                     "concepts": ["Passive diffusion", "Osmosis", "Active transport", "Concentration gradient"]},
                    {"name": "Mitochondria",
                     "importance": "Respiration is the worked example for coupling a gradient to ATP.",
                     "concepts": ["ATP synthesis", "Electron transport chain", "Cristae"]},
                ],
            }),
            ("final", "Final Exam", 38, {
                "overview": (
                    "Cumulative, weighted toward the second half: the cell cycle, "
                    "division and inheritance. Bring the membrane material with you "
                    "— the final reuses it inside questions about signalling."
                ),
                "topics": [
                    {"name": "Cell Cycle",
                     "importance": "The spine of the second half; checkpoints recur in several questions.",
                     "concepts": ["Interphase", "Checkpoints", "G1/S transition"]},
                    {"name": "Mitosis and Meiosis",
                     "importance": "Told apart by chromosome number and crossing over, which is exactly what is tested.",
                     "concepts": ["Prophase", "Metaphase", "Crossing over", "Haploid vs diploid"]},
                    {"name": "Photosynthesis",
                     "importance": "Paired with respiration as the other half of the energy story.",
                     "concepts": ["Light reactions", "Calvin cycle", "Chloroplast"]},
                ],
            }),
        ],
    ),
    (
        "rich-course-cs101", "CS101",
        [
            ("mid", "Midterm Exam", -9, {
                "overview": (
                    "Variables, control flow and functions, with recursion as the "
                    "step up. Expect to trace code by hand rather than write much "
                    "of it — the marks are in predicting state, not in syntax."
                ),
                "topics": [
                    {"name": "Variables and Types",
                     "importance": "Every trace question depends on knowing what a name is bound to and when.",
                     "concepts": ["Assignment", "Scope", "Mutability", "Type coercion"]},
                    {"name": "Control Flow",
                     "importance": "Loop and branch tracing is the most common question form on this paper.",
                     "concepts": ["Conditionals", "Loops", "Break and continue", "Nested loops"]},
                    {"name": "Recursion",
                     "importance": "The hardest midterm items are recursive traces with a base case to find.",
                     "concepts": ["Base case", "Call stack", "Recursive step"]},
                ],
            }),
            ("final", "Final Exam", 45, {
                "overview": (
                    "Cumulative, with data structures and complexity added. The new "
                    "material is mostly about choosing the right structure and "
                    "justifying the choice in big-O terms."
                ),
                "topics": [
                    {"name": "Data Structures",
                     "importance": "Choosing between list, dict and set is asked directly and assumed everywhere else.",
                     "concepts": ["Lists", "Dictionaries", "Sets", "Tuples"]},
                    {"name": "Algorithms",
                     "importance": "Sorting and searching are the worked examples complexity is measured on.",
                     "concepts": ["Linear search", "Binary search", "Sorting", "Big-O notation"]},
                    {"name": "Pointers and Memory",
                     "importance": "Explains aliasing bugs, which the final likes to hide inside a trace.",
                     "concepts": ["References", "Aliasing", "Garbage collection"]},
                ],
            }),
        ],
    ),
    (
        "rich-course-math210", "MATH210",
        [
            ("mid", "Midterm Exam", -5, {
                "overview": (
                    "Vector spaces through linear transformations. Independence and "
                    "basis carry most of the marks, and nearly every proof reduces "
                    "to showing a set spans or is independent."
                ),
                "topics": [
                    {"name": "Vector Spaces",
                     "importance": "The definitions every later proof is written in terms of.",
                     "concepts": ["Axioms", "Subspaces", "Span", "Linear combination"]},
                    {"name": "Linear Independence",
                     "importance": "Half the midterm is one independence or basis argument in disguise.",
                     "concepts": ["Independence", "Basis", "Dimension"]},
                    {"name": "Matrices",
                     "importance": "Row reduction is the computational tool the rest of the paper assumes.",
                     "concepts": ["Row reduction", "Rank", "Matrix multiplication"]},
                ],
            }),
            ("final", "Final Exam", 52, {
                "overview": (
                    "Determinants, eigenvalues and diagonalisation, resting on the "
                    "midterm's material. If you can find a basis reliably, the new "
                    "half is mostly bookkeeping."
                ),
                "topics": [
                    {"name": "Determinants",
                     "importance": "The invertibility test the eigenvalue work is built on.",
                     "concepts": ["Cofactor expansion", "Properties", "Invertibility"]},
                    {"name": "Eigenvalues",
                     "importance": "The final's longest questions are eigen-decompositions worked end to end.",
                     "concepts": ["Characteristic polynomial", "Eigenvectors", "Diagonalisation"]},
                    {"name": "Linear Transformations",
                     "importance": "Ties the matrix picture back to the vector-space one.",
                     "concepts": ["Kernel", "Image", "Rank-nullity"]},
                ],
            }),
        ],
    ),
    (
        "rich-course-eng150", "ENG150",
        [
            ("mid", "Midterm Exam", -3, {
                "overview": (
                    "A sit-down rhetorical analysis. You are marked on the argument "
                    "you make about a text's moves, not on summarising it — bring a "
                    "thesis and defend it with evidence."
                ),
                "topics": [
                    {"name": "Rhetorical Analysis",
                     "importance": "The whole paper is one analysis; everything else supports it.",
                     "concepts": ["Ethos", "Pathos", "Logos", "Audience"]},
                    {"name": "Thesis and Structure",
                     "importance": "An arguable thesis is the single biggest swing in the mark scheme.",
                     "concepts": ["Arguable claim", "Topic sentences", "Transitions"]},
                    {"name": "Evidence",
                     "importance": "Quotations have to be integrated and read, not dropped in.",
                     "concepts": ["Quotation", "Paraphrase", "Citation"]},
                ],
            }),
            ("final", "Final Exam", 41, {
                "overview": (
                    "Reflective and cumulative: you argue for the choices you made "
                    "across the term's essays. Revision vocabulary matters as much "
                    "as the writing itself."
                ),
                "topics": [
                    {"name": "Revision",
                     "importance": "The final asks you to justify changes, so you need the language for them.",
                     "concepts": ["Global revision", "Line editing", "Peer feedback"]},
                    {"name": "Argument",
                     "importance": "Counter-argument handling separates the top band from the middle.",
                     "concepts": ["Counter-argument", "Concession", "Warrant"]},
                    {"name": "Style",
                     "importance": "Sentence-level control is explicitly on the rubric.",
                     "concepts": ["Concision", "Voice", "Register"]},
                ],
            }),
        ],
    ),
]


def _guard_local() -> None:
    if not h.local_app_env():
        sys.exit("REFUSING: demo seeding requires APP_ENV=local or APP_ENV=test.")
    if not h.local_supabase_url():
        url = (os.getenv("SUPABASE_URL") or "").strip()
        sys.exit(f"REFUSING: SUPABASE_URL {url!r} is not local.")


def _offering_for(course_id: str) -> str | None:
    """The course's Fall 2026 offering id, or None if it has none."""
    rows = table("course_offerings").select(
        "id",
        filters={"course_id": f"eq.{course_id}", "term_id": f"eq.{TERM}"},
        order="id",
        limit=1,
    )
    return rows[0]["id"] if rows else None


def _enrollment_for(user_id: str, offering_id: str, short: str) -> str:
    """The user's enrollment on that offering, creating one if absent.

    Reuses an existing enrollment rather than adding a second: `enrollments`
    is UNIQUE on (user_id, offering_id), and ENG150 is already a Fall 2026
    enrollment from the rich seed.
    """
    rows = table("enrollments").select(
        "id",
        filters={"user_id": f"eq.{user_id}", "offering_id": f"eq.{offering_id}"},
        limit=1,
    )
    if rows:
        return rows[0]["id"]
    enr_id = f"sg-enr-{short}-{user_id[:24]}"
    h.insert_if_absent("enrollments", enr_id, {
        "user_id": user_id,
        "offering_id": offering_id,
    })
    return enr_id


def seed_for(user_id: str) -> None:
    print(f"\n  user {user_id}")
    for course_id, code, exams in _COURSES:
        offering_id = _offering_for(course_id)
        if not offering_id:
            print(f"    {code}: no {TERM} offering — skipped")
            continue
        enr_id = _enrollment_for(user_id, offering_id, code.lower())
        for key, title, days, guide in exams:
            due = _d(days)
            exam_id = f"sg-exam-{code.lower()}-{key}-{user_id[:24]}"
            h.insert_if_absent("assignments", exam_id, {
                "enrollment_id": enr_id,
                "title": title,
                "due_date": due,
                "assignment_type": "exam",
                "source": "syllabus",
            })
            # 🔒 content (#518): the JSON pair, same as the rich seed's guide.
            h.insert_if_absent("study_guides", f"sg-guide-{code.lower()}-{key}-{user_id[:24]}", {
                "user_id": user_id,
                "offering_id": offering_id,
                "exam_id": exam_id,
                "generated_at": _NOW.isoformat(),
                "content": encrypt_json({
                    "exam": title,
                    "due_date": due,
                    "overview": guide["overview"],
                    "topics": guide["topics"],
                }),
            })
        print(f"    {code}: {len(exams)} exam(s) + {len(exams)} guide(s)  [{offering_id[:18]}]")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--user", action="append", dest="users",
        help="Account to populate; repeatable. Defaults to the rich fixture user "
             "plus every local user_* Google account already in the database.",
    )
    args = ap.parse_args()

    _guard_local()

    users = args.users
    if not users:
        users = list(DEFAULT_USERS)
        # A developer signing in with Google locally gets a `user_<id>` row the
        # seed watcher has already cloned the rich dataset onto; it is the
        # account they will actually be looking at, so populate it too.
        for row in table("users").select("id", filters={"id": "like.user\\_%"}) or []:
            if row["id"] not in users:
                users.append(row["id"])

    for user_id in users:
        seed_for(user_id)

    h.print_summary(
        ["enrollments", "assignments", "study_guides"],
        "\nSeed summary (study guides, current term):",
    )
    print("\n  Term: Fall 2026 — open /study and pick a course.")


if __name__ == "__main__":
    main()
