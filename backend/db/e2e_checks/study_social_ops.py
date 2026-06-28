"""Study + social + ops journey for the staging HTTP e2e suite.

Covers:
  - POST /api/notes  (offering-keyed note via abstract course_id)
  - GET  /api/social/students
  - POST /api/feedback  (text PK + FK)
"""
from __future__ import annotations

from db.e2e_staging_http import client, check, USER_ID, OFFERING_ID, COURSE_ID
from db.connection import table


def run() -> None:
    # ── 1. POST /api/notes ────────────────────────────────────────────────────
    # Route: routes/notes.py @router.post("") mounted at /api/notes.
    # Body: CreateNoteBody {user_id, course_id, title, body, tags}.
    # The handler calls resolve_offering(body.course_id, create=True) to map the
    # abstract course id → the current-term offering; the fixture seeds COURSE_ID
    # as the abstract id whose current-term offering IS OFFERING_ID.
    # Response: the decrypted note dict directly (not wrapped), top-level "id".
    r = client.post(
        "/api/notes",
        json={
            "user_id": USER_ID,
            "course_id": COURSE_ID,
            "title": "N1",
            "body": "b",
        },
    )
    body = r.json() if r.status_code in (200, 201) else {}
    note_id = body.get("id")
    check(
        "POST /api/notes (offering-keyed)",
        r.status_code in (200, 201) and bool(note_id),
        r.text[:120],
    )

    # Verify the note was stored against OFFERING_ID (not the abstract course id).
    if note_id:
        stored = table("notes").select("offering_id", filters={"id": f"eq.{note_id}"})
        actual_offering = stored[0]["offering_id"] if stored else None
        check(
            "note.offering_id == OFFERING_ID",
            actual_offering == OFFERING_ID,
            f"got {actual_offering!r}",
        )

    # ── 2. GET /api/social/students ───────────────────────────────────────────
    # Route: routes/social.py @router.get("/students") mounted at /api/social.
    r = client.get("/api/social/students")
    check(
        "GET /api/social/students",
        r.status_code == 200,
        f"got {r.status_code}",
    )

    # ── 3. POST /api/feedback ─────────────────────────────────────────────────
    # Route: routes/feedback.py @router.post("/feedback") mounted at /api
    # (prefix "/api"), so full path is POST /api/feedback.
    # Body: SubmitFeedbackBody {user_id, type, rating, selected_options,
    #                           comment?, session_id?, topic?}.
    r = client.post(
        "/api/feedback",
        json={
            "user_id": USER_ID,
            "type": "global",
            "rating": 5,
            "selected_options": [],
            "comment": "e2e",
        },
    )
    check(
        "POST /api/feedback (text PK + FK)",
        r.status_code in (200, 201),
        f"got {r.status_code} {r.text[:100]}",
    )
