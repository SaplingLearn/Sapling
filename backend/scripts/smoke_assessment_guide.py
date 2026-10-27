"""Non-destructive local-storage smoke check; no Docker reset or paid AI calls.

Run from backend/: python -m scripts.smoke_assessment_guide
Uses the existing rich seed account by default. Deletes only its own temporary
document and plan, leaving all existing accounts, mastery and materials intact.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

from dotenv import load_dotenv


def verify_anthropic_receipt(user_id: str, enrollment_id: str) -> None:
    """Exercise the SQL settlement contract inside a fully rolled-back transaction."""
    import hashlib
    import psycopg
    from psycopg.types.json import Jsonb
    from uuid import NAMESPACE_URL, uuid5
    from pydantic_ai.messages import ModelResponse, TextPart
    from pydantic_ai.usage import RequestUsage, RunUsage
    import config
    from services import checklist_budget
    from services.usage_receipts import prepare_checklist_usage_receipt

    operation = uuid4()
    receipt_id = str(uuid5(NAMESPACE_URL, f"sapling:checklist-receipt:{operation}"))
    with psycopg.connect(os.environ["SUPABASE_DB_URL"]) as conn:
        admitted, = conn.execute("SELECT checklist_budget_admit(%s,%s,%s,%s,%s,%s,%s,%s,%s)", (
            user_id, enrollment_id, hashlib.sha256(str(operation).encode()).hexdigest(), operation,
            receipt_id, checklist_budget.POLICY, str(config.STUDENT_DAILY_BUDGET_USD),
            str(config.STUDENT_MONTHLY_BUDGET_USD), config.STUDENT_DAILY_TOKENS,
        )).fetchone()
        assert admitted["status"] == "admitted", admitted["status"]
        started, = conn.execute("SELECT checklist_budget_start(%s,%s,%s)", (
            user_id, operation, admitted["reservation"]["fence"],
        )).fetchone()
        reservation = checklist_budget.Reservation.from_row(started["reservation"])
        response = ModelResponse(parts=[TextPart("Synthetic receipt test")],
            model_name="claude-haiku-5-5", provider_name="anthropic",
            usage=RequestUsage(input_tokens=1000, output_tokens=500,
                details={"input_tokens": 1000, "output_tokens": 500}))
        aggregate = RunUsage(requests=1)
        aggregate.incr(response.usage)
        receipt = prepare_checklist_usage_receipt(operation_id=operation, user_id=user_id,
            approved_model="claude-haiku-5-5", responses=(response,), dispatched_requests=1,
            usage=aggregate, completed=True, dispatched_at=reservation.dispatch_at)
        params = (user_id, operation, reservation.fence, "settle", Jsonb(receipt.to_row()), receipt.fingerprint)
        for _ in range(2):
            settled, = conn.execute("SELECT checklist_budget_reconcile(%s,%s,%s,%s,%s,%s)", params).fetchone()
            assert settled["status"] == "settled", settled["status"]
        assert conn.execute("SELECT count(*) FROM llm_usage WHERE id=%s", (receipt.receipt_id,)).fetchone()[0] == 1
        # No synthetic usage, reservation, or accounting changes survive this check.
        conn.rollback()


def main() -> None:
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    for key in ("SUPABASE_URL", "SUPABASE_DB_URL"):
        if urlparse(os.environ.get(key, "")).hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise SystemExit(f"Refusing smoke check: {key} must point to loopback.")
    if os.environ.get("APP_ENV") not in {"local", "test"}:
        raise SystemExit("Refusing smoke check: APP_ENV must be local or test.")

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user-id", default="rich-user-active")
    parser.add_argument("--course-id", default="rich-course-cs101")
    parser.add_argument("--semester", default="Spring 2026")
    args = parser.parse_args()

    # This diagnostic is explicitly non-billable even without an API key.
    os.environ["SAPLING_MODEL_MODE"] = "function"
    import psycopg
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from pydantic_ai.messages import ModelResponse, ToolCallPart
    from pydantic_ai.models.function import FunctionModel

    from agents.topic_checklist_model import wrap_topic_checklist_model
    from agents.assessment_guide import assessment_guide_agent
    from db.connection import table
    from routes.topic_checklist import router
    from services.encryption import decrypt_json, encrypt_if_present
    from services.session_tokens import SESSION_COOKIE_NAME, mint_session
    from services.topic_checklist_service import resolve_scope

    scope = resolve_scope(args.user_id, args.course_id, args.semester)
    verify_anthropic_receipt(args.user_id, scope["enrollment_id"])
    document_id = str(uuid4())
    plan_id = None
    app = FastAPI()
    app.include_router(router, prefix="/api/topic-checklist")
    path = f"/api/topic-checklist/{args.user_id}/courses/{args.course_id}/plans"
    params = {"semester": args.semester}
    calls = []

    def model(messages, info):
        calls.append(True)
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, {
            "overview": "Review recursion from the attached undated notes.",
            "topics": [{"name": "Recursion", "description": "Base cases and recursive calls.",
                        "importance": .9, "source_ids": [f"document:{document_id}"],
                        "study_points": ["Explain why a recursive function needs a base case."]}],
        })])

    try:
        table("documents").insert({
            "id": document_id, "user_id": args.user_id, "offering_id": scope["offering_id"],
            "file_name": "Temporary undated study-guide smoke notes.txt", "category": "lecture_notes",
            "extracted_text": encrypt_if_present("Recursion needs a base case and a recursive call."),
        })
        with TestClient(app) as client, assessment_guide_agent.override(model=wrap_topic_checklist_model(FunctionModel(model))):
            client.cookies.set(SESSION_COOKIE_NAME, mint_session(args.user_id))
            sources = client.get(path + "/sources", params=params)
            assert sources.status_code == 200, sources.text
            assert any(d["id"] == document_id for d in sources.json()["documents"])
            today = datetime.now(timezone.utc).date()
            exam = today + timedelta(days=10)
            response = client.post(path, params=params, json={
                "title": "Temporary local guide smoke check", "document_ids": [document_id],
                "start_date": today.isoformat(), "assessment_date": exam.isoformat(),
                "timezone": "UTC", "study_days": list(range(7)),
            })
            assert response.status_code == 201, response.text
            plan = response.json()
            plan_id = plan["id"]
            assert len(calls) == 1
            assert plan["automatic_time"] is True
            assert 25 <= plan["minutes_per_day"] <= 120
            assert plan["guide_overview"] and plan["topics"][0]["study_points"]
            assert all(s["scheduled_date"] < exam.isoformat() for s in plan["sessions"])
            alternate = "Fall 2025" if args.semester != "Fall 2025" else "Spring 2026"
            other_term = client.get(path, params={"semester": alternate})
            assert other_term.status_code in {200, 404}, other_term.text
            if other_term.status_code == 200:
                assert all(p["id"] != plan_id for p in other_term.json()["plans"])

            with psycopg.connect(os.environ["SUPABASE_DB_URL"]) as conn:
                ciphertext, = conn.execute("SELECT content FROM assessment_study_plans WHERE id = %s", (plan_id,)).fetchone()
                assert "Recursion" not in ciphertext
                assert decrypt_json(ciphertext)["guide_overview"] == plan["guide_overview"]

            url = path + "/" + plan_id
            patch = {"version": plan["version"], "session": {"id": plan["sessions"][0]["id"], "completed": True}}
            response = client.patch(url, params=params, json=patch)
            assert response.status_code == 200, response.text
            assert response.json()["mastered_count"] == plan["mastered_count"]
            assert client.patch(url, params=params, json=patch).status_code == 409
            saved = next(p for p in client.get(path, params=params).json()["plans"] if p["id"] == plan_id)
            assert saved["sessions"][0]["completed"]
            response = client.patch(url, params=params, json={
                "version": saved["version"], "session": {
                    "id": saved["sessions"][0]["id"], "scheduled_date": (today + timedelta(days=1)).isoformat(),
                },
            })
            assert response.status_code == 200, response.text
            assert len(calls) == 1, "Editing sessions must not regenerate the guide."
            assert client.delete(url, params=params).status_code == 200
            assert client.patch(url, params=params, json=patch).status_code == 404
        print("PASS: undated document + manual date, guide/schedule, encrypted SQL storage,")
        print("completion/reload, rescheduling, unchanged mastery, stale-write rejection and delete.")
        print("Anthropic receipt SQL and idempotent settlement passed in a rolled-back transaction.")
    finally:
        if plan_id:
            table("assessment_study_plans").delete({"id": f"eq.{plan_id}", "enrollment_id": f"eq.{scope['enrollment_id']}"})
        table("documents").delete({"id": f"eq.{document_id}", "user_id": f"eq.{args.user_id}"})


if __name__ == "__main__":
    main()
