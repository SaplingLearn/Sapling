"""Opt-in disposable-stack persistence, isolation and cascade checks."""
import pytest
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel

from agents.topic_checklist import topic_checklist_agent
from services.encryption import decrypt_json
from services.topic_checklist_service import topic_key
from tests.integration.conftest import USER_ACTIVE, _client_for

pytestmark = pytest.mark.integration


def test_checklist_is_encrypted_persistent_and_enrollment_scoped(db_conn, seeded_user):
    def handler(messages, info):
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, {"topics": [{
            "name": "Recursion", "description": "Base cases and recursive calls.", "importance": 0.9,
            "source_ids": ["concept:rich-node-cs-recursion"],
        }]})])

    path = f"/api/topic-checklist/{USER_ACTIVE}/courses/rich-course-cs101"
    client = _client_for(USER_ACTIVE)
    with topic_checklist_agent.override(model=FunctionModel(handler)):
        response = client.post(path + "/refresh", params={"semester": "Spring 2026"})
    assert response.status_code == 200, response.text
    topic = response.json()["topics"][0]
    assert topic["name"] == "Recursion" and topic["status"] == "needs_review"
    cache = db_conn.execute("SELECT * FROM topic_checklists").fetchone()
    assert cache["enrollment_id"] == "rich-enr-active-cs101-s26"
    assert "Recursion" not in cache["content"]
    assert decrypt_json(cache["content"])["topics"][0]["name"] == "Recursion"

    mutation = client.patch(path + f"/topics/{topic_key('Recursion')}", json={"checked": True}, params={"semester": "Spring 2026"})
    assert mutation.status_code == 200 and mutation.json()["topics"][0]["checked"]
    assert client.get(path, params={"semester": "Spring 2026"}).json()["topics"][0]["checked"]
    assert client.get(path, params={"semester": "Fall 2025"}).json()["topics"] == []
    assert _client_for(seeded_user()).get(path).status_code == 403

    db_conn.execute("DELETE FROM enrollments WHERE id = %s", (cache["enrollment_id"],))
    assert db_conn.execute("SELECT count(*) AS n FROM topic_checklists").fetchone()["n"] == 0
    assert db_conn.execute("SELECT count(*) AS n FROM topic_checklist_progress").fetchone()["n"] == 0
