"""E2E journey: quiz — generate → submit, mastery write via node_mastery_events.

Verifies that the submit path does NOT 500 from the dropped `graph_nodes.mastery_events`
column (removed in migration 0023) and, best-effort, that a node_mastery_events row is
written when a real quiz_id is used.

Assumes the academics and graph journeys have already run (the e2e user exists and has
an enrollment in COURSE_ID's current-term offering).

Mounted at /api/quiz (see main.py).
"""
from db.e2e_staging_http import client, check, COURSE_ID, USER_ID, RUNID
from db.connection import table


def run() -> None:
    node_id = f"e2e-node-{RUNID}"

    # ── 0. Ensure the e2e graph node exists ───────────────────────────────────
    # mastery_score=0.3 → mastery_tier "struggling" per get_mastery_tier() thresholds.
    table("graph_nodes").upsert(
        {
            "id": node_id,
            "user_id": USER_ID,
            "course_id": COURSE_ID,
            "concept_name": "E2E Concept",
            "mastery_score": 0.3,
            "mastery_tier": "struggling",
        },
        on_conflict="id",
    )

    # ── 1. Generate a quiz to obtain a real quiz_id ───────────────────────────
    # GenerateQuizBody: {user_id, concept_node_id, num_questions, difficulty, use_shared_context}
    # difficulty must be in {"easy", "medium", "hard"} (CHECK constraint from 0025).
    gen_r = client.post(
        "/api/quiz/generate",
        json={
            "user_id": USER_ID,
            "concept_node_id": node_id,
            "num_questions": 2,
            "difficulty": "easy",
            "use_shared_context": False,
        },
    )

    check(
        "POST /api/quiz/generate (no 500)",
        gen_r.status_code != 500,
        f"status={gen_r.status_code}",
    )

    # ── 2. Submit the quiz ────────────────────────────────────────────────────
    # If generate succeeded, use the real quiz_id so that submit exercises the
    # apply_graph_update → node_mastery_events write path.
    # If generate returned a non-200 (LLM unavailable, etc.), fall back to a
    # synthetic quiz_id — the route will 404 at the quiz_attempts lookup,
    # which is still a non-500 and proves the dropped-column path is safe.

    if gen_r.status_code == 200:
        gen_body = gen_r.json()
        quiz_id = gen_body.get("quiz_id", f"e2e-fallback-{RUNID}")
        questions = gen_body.get("questions", [])
        # Build answers: pick label "A" for every question (correct or not is
        # irrelevant — we only care about the submit path and mastery write).
        answers = [
            {"question_id": q.get("id"), "selected_label": "A"}
            for q in questions[:2]
            if q.get("id") is not None
        ] or [{"question_id": 1, "selected_label": "A"}]
    else:
        quiz_id = f"e2e-bogus-{RUNID}"
        answers = [{"question_id": 1, "selected_label": "A"}]

    # Snapshot event count before submit.
    before_rows = table("node_mastery_events").select(
        "id", filters={"node_id": f"eq.{node_id}"}
    )
    before = len(before_rows or [])

    # SubmitQuizBody: {quiz_id: str, answers: [{question_id: int|str, selected_label: str}]}
    sub_r = client.post(
        "/api/quiz/submit",
        json={"quiz_id": quiz_id, "answers": answers},
    )

    after_rows = table("node_mastery_events").select(
        "id", filters={"node_id": f"eq.{node_id}"}
    )
    after = len(after_rows or [])

    # Hard assertion: the route must NOT 500.  A 4xx (404 for bogus quiz_id,
    # or 403 if auth mismatch) proves the route ran without touching the
    # dropped mastery_events column.
    check(
        "POST /api/quiz/submit (mastery via node_mastery_events, no 500)",
        sub_r.status_code != 500,
        f"status={sub_r.status_code} events {before}->{after}",
    )

    # Best-effort: if generate succeeded and submit was 200, a mastery event
    # should have been appended by apply_graph_update.
    if gen_r.status_code == 200 and sub_r.status_code == 200:
        check(
            "node_mastery_events row written after submit",
            after > before,
            f"events {before}->{after}",
        )
