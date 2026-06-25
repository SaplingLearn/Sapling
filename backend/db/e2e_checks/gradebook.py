"""
backend/db/e2e_checks/gradebook.py

Gradebook journey for the staging HTTP E2E suite.

Flow:
  1. Resolve the current term label from `terms`.
  2. POST /api/gradebook/courses/{COURSE_ID}/categories  — create a "Homework" category.
  3. POST /api/gradebook/assignments                     — create HW1 (encrypted points).
  4. GET  /api/gradebook/gpa   ?user_id=…&semester=…    — semester-scoped GPA.
  5. GET  /api/gradebook/summary ?user_id=…&semester=…  — per-course summary for the term.

Prerequisites (academics journey must run first):
  - The user is enrolled in COURSE_ID's current-term offering.
  - That enrollment drives category / assignment creation (route resolves
    (course_id, semester) -> enrollment_id internally).
"""
from __future__ import annotations

from db.e2e_staging_http import client, check, COURSE_ID, USER_ID, current_term_id
from db.connection import table


def run() -> None:
    # ── 0. Resolve the current term label ────────────────────────────────────
    term_label = ""
    tid = current_term_id()
    if tid:
        rows = table("terms").select("label", filters={"id": f"eq.{tid}"})
        if rows:
            term_label = rows[0]["label"]

    check(
        "gradebook: current term label resolved",
        bool(term_label),
        f"label={term_label!r}",
    )

    # ── 1. POST /api/gradebook/courses/{COURSE_ID}/categories ─────────────────
    # Body: CreateCategoryBody = {user_id, semester?, name, weight, drop_lowest?}
    # Response: {"category": {...}}
    r = client.post(
        f"/api/gradebook/courses/{COURSE_ID}/categories",
        json={
            "user_id": USER_ID,
            "semester": term_label,
            "name": "Homework",
            "weight": 100,
        },
    )
    check(
        "POST /api/gradebook/courses/{course_id}/categories",
        r.status_code in (200, 201),
        f"got {r.status_code} {r.text[:120]}",
    )

    category_id: str | None = None
    if r.status_code in (200, 201):
        data = r.json()
        cat = data.get("category") or {}
        category_id = cat.get("id")
        check(
            "gradebook category: response has id",
            bool(category_id),
            f"category={cat}",
        )

    # ── 2. POST /api/gradebook/assignments ────────────────────────────────────
    # Body: CreateAssignmentBody = {user_id, course_id, semester?, title,
    #   category_id?, points_possible, points_earned, due_date?,
    #   assignment_type?, notes?}
    # assignment_type CHECK: 'homework'|'exam'|'reading'|'project'|'quiz'|'other'
    # points_possible / points_earned are encrypted TEXT in the DB.
    # Response: {"assignment": {...}} with decrypted numeric values.
    assignment_body: dict = {
        "user_id": USER_ID,
        "course_id": COURSE_ID,
        "semester": term_label,
        "title": "HW1",
        "points_possible": 100,
        "points_earned": 90,
        "assignment_type": "homework",
    }
    if category_id:
        assignment_body["category_id"] = category_id

    r = client.post("/api/gradebook/assignments", json=assignment_body)
    check(
        "POST /api/gradebook/assignments (encrypted points)",
        r.status_code in (200, 201),
        f"got {r.status_code} {r.text[:120]}",
    )

    if r.status_code in (200, 201):
        data = r.json()
        a = data.get("assignment") or {}
        check(
            "gradebook assignment: points_possible decrypted correctly",
            a.get("points_possible") == 100,
            f"points_possible={a.get('points_possible')}",
        )
        check(
            "gradebook assignment: points_earned decrypted correctly",
            a.get("points_earned") == 90,
            f"points_earned={a.get('points_earned')}",
        )

    # ── 3. GET /api/gradebook/gpa ─────────────────────────────────────────────
    # Query params: user_id, semester (term label -> semester-scoped GPA)
    # Response: {"gpa": float|None, "courses": [...], "semester": str,
    #            "scope": "semester"|"cumulative"}
    r = client.get(
        "/api/gradebook/gpa",
        params={"user_id": USER_ID, "semester": term_label},
    )
    check(
        "GET /api/gradebook/gpa (semester-aware)",
        r.status_code == 200,
        f"got {r.status_code} {r.text[:120]}",
    )

    if r.status_code == 200:
        data = r.json()
        check(
            "gradebook gpa: scope is 'semester'",
            data.get("scope") == "semester",
            f"scope={data.get('scope')}",
        )
        check(
            "gradebook gpa: response contains 'courses' list",
            isinstance(data.get("courses"), list),
            f"courses type={type(data.get('courses')).__name__}",
        )

    # ── 4. GET /api/gradebook/summary ─────────────────────────────────────────
    # Query params: user_id, semester (required — returns enrolled courses for that term)
    # Response: {"courses": [...], "gpa": float|None, "semester": str}
    r = client.get(
        "/api/gradebook/summary",
        params={"user_id": USER_ID, "semester": term_label},
    )
    check(
        "GET /api/gradebook/summary (semester-aware)",
        r.status_code == 200,
        f"got {r.status_code} {r.text[:120]}",
    )

    if r.status_code == 200:
        data = r.json()
        check(
            "gradebook summary: response contains 'courses' list",
            isinstance(data.get("courses"), list),
            f"courses type={type(data.get('courses')).__name__}",
        )
        check(
            "gradebook summary: semester echoed back",
            data.get("semester") == term_label,
            f"semester={data.get('semester')!r}",
        )
