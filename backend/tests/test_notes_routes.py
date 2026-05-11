"""Route tests for /api/notes.

Uses the autouse `_bypass_session_auth` fixture from conftest.py — every
test exercises route logic via the TestClient with `user_id` resolved
from query/path/body to "user_andres" by default.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from main import app


@pytest.fixture
def client():
    return TestClient(app)


class TestListNotes:
    def test_returns_notes_for_user(self, client):
        notes = [
            {"id": "n1", "user_id": "u1", "course_id": "c1",
             "title": "A", "body": "", "tags": [],
             "last_summary": None, "last_summary_at": None,
             "created_at": "2026-05-11T00:00:00Z",
             "updated_at": "2026-05-11T00:00:00Z"},
        ]
        async def fake_list(user_id, course_id=None):
            assert user_id == "u1"
            assert course_id is None
            return notes
        with patch("routes.notes.list_notes", side_effect=fake_list):
            r = client.get("/api/notes/user/u1")
        assert r.status_code == 200
        assert r.json() == {"notes": notes}

    def test_course_filter_passes_through(self, client):
        async def fake_list(user_id, course_id=None):
            assert course_id == "c2"
            return []
        with patch("routes.notes.list_notes", side_effect=fake_list):
            r = client.get("/api/notes/user/u1?course_id=c2")
        assert r.status_code == 200


class TestCreateNote:
    def test_creates_with_required_fields(self, client):
        async def fake_create(user_id, course_id, title, body, tags):
            return {"id": "n1", "user_id": user_id, "course_id": course_id,
                    "title": title, "body": body, "tags": tags,
                    "last_summary": None, "last_summary_at": None,
                    "created_at": "2026-05-11T00:00:00Z",
                    "updated_at": "2026-05-11T00:00:00Z"}
        with patch("routes.notes.create_note", side_effect=fake_create):
            r = client.post(
                "/api/notes",
                json={"user_id": "u1", "course_id": "c1",
                      "title": "T", "body": "B", "tags": ["a"]},
            )
        assert r.status_code == 200
        assert r.json()["id"] == "n1"

    def test_missing_course_id_returns_422(self, client):
        r = client.post(
            "/api/notes",
            json={"user_id": "u1", "title": "T"},
        )
        assert r.status_code == 422


class TestGetNote:
    def test_returns_note_when_owned(self, client):
        async def fake_get(note_id, user_id):
            return {"id": note_id, "user_id": user_id, "course_id": "c1",
                    "title": "T", "body": "B", "tags": [],
                    "last_summary": None, "last_summary_at": None,
                    "created_at": "2026-05-11T00:00:00Z",
                    "updated_at": "2026-05-11T00:00:00Z"}
        with patch("routes.notes.get_note", side_effect=fake_get):
            r = client.get("/api/notes/n1?user_id=u1")
        assert r.status_code == 200
        assert r.json()["id"] == "n1"

    def test_returns_404_when_missing(self, client):
        async def fake_get(note_id, user_id):
            return None
        with patch("routes.notes.get_note", side_effect=fake_get):
            r = client.get("/api/notes/missing?user_id=u1")
        assert r.status_code == 404


class TestUpdateNote:
    def test_patches_title_only(self, client):
        captured = {}
        async def fake_update(note_id, user_id, patch):
            captured["patch"] = patch
            return {"id": note_id, "user_id": user_id, "course_id": "c1",
                    "title": patch.get("title", ""), "body": "", "tags": [],
                    "last_summary": None, "last_summary_at": None,
                    "created_at": "2026-05-11T00:00:00Z",
                    "updated_at": "2026-05-11T00:00:00Z"}
        with patch("routes.notes.update_note", side_effect=fake_update):
            r = client.patch(
                "/api/notes/n1",
                json={"user_id": "u1", "title": "New"},
            )
        assert r.status_code == 200
        assert captured["patch"] == {"title": "New"}

    def test_missing_returns_404(self, client):
        async def fake_update(note_id, user_id, patch):
            return None
        with patch("routes.notes.update_note", side_effect=fake_update):
            r = client.patch(
                "/api/notes/missing",
                json={"user_id": "u1", "title": "x"},
            )
        assert r.status_code == 404


class TestDeleteNote:
    def test_deletes(self, client):
        called = {}
        async def fake_delete(note_id, user_id):
            called["args"] = (note_id, user_id)
        with patch("routes.notes.delete_note", side_effect=fake_delete):
            r = client.delete("/api/notes/n1?user_id=u1")
        assert r.status_code == 200
        assert r.json() == {"deleted": True}
        assert called["args"] == ("n1", "u1")


class TestLinkConceptRoute:
    def test_list_linked(self, client):
        async def fake_list(note_id, user_id):
            return [{"id": "g1", "concept_name": "X",
                     "mastery_tier": "learning",
                     "mastery_score": 0.5, "course_id": "c1"}]
        with patch("routes.notes.list_linked_concepts", side_effect=fake_list):
            r = client.get("/api/notes/n1/concepts?user_id=u1")
        assert r.status_code == 200
        assert r.json() == {"concepts": [{
            "id": "g1", "concept_name": "X",
            "mastery_tier": "learning",
            "mastery_score": 0.5, "course_id": "c1",
        }]}

    def test_link(self, client):
        async def fake_link(note_id, user_id, concept_node_id):
            return True
        with patch("routes.notes.link_concept", side_effect=fake_link):
            r = client.post(
                "/api/notes/n1/concepts",
                json={"user_id": "u1", "concept_node_id": "g1"},
            )
        assert r.status_code == 200
        assert r.json() == {"linked": True}

    def test_unlink(self, client):
        async def fake_unlink(note_id, user_id, concept_node_id):
            return True
        with patch("routes.notes.unlink_concept", side_effect=fake_unlink):
            r = client.delete(
                "/api/notes/n1/concepts/g1?user_id=u1"
            )
        assert r.status_code == 200
        assert r.json() == {"unlinked": True}
