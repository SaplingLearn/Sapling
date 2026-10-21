"""Opt-in real PostgREST/SQL checks for encrypted plans and enrollment cascades."""
from datetime import date, timedelta

import pytest
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel

from agents.assessment_guide import assessment_guide_agent
from services.encryption import decrypt_json
from tests.integration.conftest import USER_ACTIVE, _client_for

pytestmark = pytest.mark.integration


def test_plan_storage_conflicts_live_mastery_and_enrollment_cascade(db_conn, seeded_user):
    def handler(messages, info):
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, {"overview": "Prepare for recursion.", "topics": [{
            "name": "Recursion", "description": "Base cases and recursive calls.", "importance": .9,
            "source_ids": ["assessment-coverage"], "study_points": ["Explain base cases."],
        }]})])

    client = _client_for(USER_ACTIVE)
    path = f"/api/topic-checklist/{USER_ACTIVE}/courses/rich-course-cs101/plans"
    params = {"semester": "Spring 2026"}
    today = date.today()
    with assessment_guide_agent.override(model=FunctionModel(handler)):
        response = client.post(path, params=params, json={
            "title": "Recursion midterm", "coverage": "Recursion", "start_date": today.isoformat(),
            "assessment_date": (today + timedelta(days=10)).isoformat(), "timezone": "UTC",
        })
    assert response.status_code == 201, response.text
    plan = response.json()
    row = db_conn.execute("SELECT * FROM assessment_study_plans WHERE id = %s", (plan["id"],)).fetchone()
    assert row["enrollment_id"] == "rich-enr-active-cs101-s26"
    assert "Recursion" not in row["content"]
    assert decrypt_json(row["content"])["title"] == "Recursion midterm"
    assert client.get(path, params={"semester": "Fall 2025"}).json()["plans"] == []
    assert _client_for(seeded_user()).get(path).status_code == 403

    edit = {"version": 1, "session": {"id": plan["sessions"][0]["id"], "completed": True}}
    assert client.patch(path + f"/{plan['id']}", params=params, json=edit).status_code == 200
    assert client.patch(path + f"/{plan['id']}", params=params, json=edit).status_code == 409
    assert client.get(path, params=params).json()["plans"][0]["mastered_count"] == 0
    db_conn.execute("UPDATE graph_nodes SET mastery_score = .99 WHERE id = 'rich-node-cs-recursion'")
    assert client.get(path, params=params).json()["plans"][0]["mastered_count"] == 1

    db_conn.execute("DELETE FROM enrollments WHERE id = %s", (row["enrollment_id"],))
    assert db_conn.execute("SELECT count(*) AS n FROM assessment_study_plans").fetchone()["n"] == 0
