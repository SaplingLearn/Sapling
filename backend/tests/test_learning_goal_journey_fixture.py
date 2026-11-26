"""Optional browser assets: the seeder refuses any non-local target."""

from types import SimpleNamespace

import pytest

from scripts import seed_learning_goal_journey as fixture
from db.e2e_handler_constants import read_constants
from services.encryption import bind, encrypt_if_present, encrypt_json


@pytest.fixture
def assets(monkeypatch):
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("SUPABASE_URL", "http://127.0.0.1:54321")
    final, prompt, reference = read_constants(
        "E2E_LOOP_FINAL_ANSWER", "E2E_LOOP_PROBE_PROMPT", "E2E_LOOP_REFERENCE"
    )
    templates = {}
    for slug in fixture.SLUGS:
        for difficulty in fixture.DIAGNOSTIC_COUNTS:
            tid = f"rich-check-{slug}-free-d{difficulty}"

            def seal(column, value, tid=tid):  # finding M13: bound to the template's own row
                return encrypt_if_present(value, bind=bind("check_items", column, tid))

            templates[tid] = {
                "id": tid,
                "course_id": fixture.COURSE_CS,
                "concept_key": slug,
                "document_id": "reviewed-course-document",
                "format": "free",
                "difficulty": difficulty,
                "prompt": seal("prompt", f"{prompt} [{slug}, free, difficulty {difficulty}]"),
                "reference_answer": seal("reference_answer", reference),
                "final_answer": seal("final_answer", final),
                "rubric_json": encrypt_json(
                    [{"id": "r1", "text": "States the seeded final answer."}],
                    bind=bind("check_items", "rubric_json", tid),
                ),
                "common_wrong_json": encrypt_json(
                    [{"key": "wrong", "text": "Gives a different answer."}],
                    bind=bind("check_items", "common_wrong_json", tid),
                ),
                "source_chunk_ids": [f"course-chunk-{slug}"],
                "source_document_ids": ["reviewed-course-document"],
                "question_hash": "replaced",
                "graded": False,
            }
    sessions, writes, deletes, reads, events = [], [], [], [], []
    graph_nodes = [{"id": f"rich-node-loop-{slug}"} for slug in ("binary", "bitwise", "twos")]

    class Table:
        def __init__(self, name):
            self.name = name

        def select(self, *_args, filters=None, **_kwargs):
            reads.append((self.name, filters))
            if self.name == "node_mastery_events":
                # Actual migration schema has node_id and no user_id column.
                assert set(filters) == {"node_id"}
                return events
            if self.name == "sessions":
                return sessions
            if self.name == "graph_nodes":
                assert filters["user_id"] == f"eq.{fixture.USER_LOOP}"
                assert filters["course_id"] == f"eq.{fixture.COURSE_CS}"
                name = filters.get("concept_name")
                return [
                    row
                    for row in graph_nodes
                    if not name or f"eq.{row.get('concept_name')}" == name
                ]
            return []

        def delete(self, filters):
            deletes.append((self.name, filters))

    monkeypatch.setattr(fixture, "table", Table)
    monkeypatch.setattr(fixture, "_template", lambda item_id: templates[item_id])
    monkeypatch.setattr(fixture.h, "upsert", lambda name, row, **_kw: writes.append((name, row)))
    return SimpleNamespace(
        templates=templates,
        sessions=sessions,
        writes=writes,
        deletes=deletes,
        reads=reads,
        events=events,
        graph_nodes=graph_nodes,
    )


@pytest.mark.parametrize(
    "url", ["https://prod.example", "http://127.0.0.1.evil.test", "http://evil.test/localhost"]
)
def test_fixture_refuses_remote_even_if_local_appears_in_url(assets, monkeypatch, url):
    monkeypatch.setenv("SUPABASE_URL", url)
    with pytest.raises(RuntimeError, match="loopback"):
        fixture.seed_goal_continuation_items("diagnostic")
    assert not assets.writes and not assets.deletes


def test_readiness_refuses_production_environment_even_with_local_url(assets, monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    with pytest.raises(RuntimeError, match="local/test"):
        fixture.seed_goal_continuation_items("readiness")
    assert not assets.writes and not assets.deletes
