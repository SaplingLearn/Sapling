"""Academics journey: semesters list + abstract-catalog search + enroll-resolves-to-offering."""
from db.e2e_staging_http import client, check, COURSE_ID, OFFERING_ID, USER_ID, current_term_id
from db.connection import table


def run() -> None:
    # ── 1. GET /api/semesters ────────────────────────────────────────────────
    tid = current_term_id()
    r = client.get("/api/semesters")
    sems = r.json().get("semesters", []) if r.status_code == 200 else []
    check(
        "GET /api/semesters",
        r.status_code == 200 and any(t["id"] == tid for t in sems),
        f"{len(sems)} terms",
    )

    # ── 2. GET /api/onboarding/courses (abstract catalog search) ────────────
    r = client.get("/api/onboarding/courses", params={"q": "E2E"})
    found = [
        c
        for c in (r.json().get("courses", []) if r.status_code == 200 else [])
        if c["id"] == COURSE_ID
    ]
    check(
        "GET /api/onboarding/courses (abstract search)",
        r.status_code == 200 and bool(found),
        f"found={[c['id'] for c in found]}",
    )

    # ── 3. POST /api/onboarding/profile -> enrollment resolves to OFFERING_ID ─
    # OnboardingBody requires: user_id, first_name, last_name, year,
    # majors (min_length=1), minors, course_ids (min_length=1), learning_style.
    r = client.post(
        "/api/onboarding/profile",
        json={
            "user_id": USER_ID,
            "first_name": "E2E",
            "last_name": "User",
            "year": "Sophomore",
            "majors": ["CS"],
            "minors": [],
            "course_ids": [COURSE_ID],
            "learning_style": "visual",
        },
    )
    # The fixture seeds OFFERING_ID = the current-term offering for COURSE_ID, so
    # resolve_offering() must return OFFERING_ID and create an enrollment for it.
    enr = table("enrollments").select("offering_id", filters={"user_id": f"eq.{USER_ID}"}) or []
    check(
        "POST /api/onboarding/profile -> enrolled into offering",
        r.status_code == 200 and any(e["offering_id"] == OFFERING_ID for e in enr),
        f"status={r.status_code} offerings={[e['offering_id'] for e in enr]}",
    )
