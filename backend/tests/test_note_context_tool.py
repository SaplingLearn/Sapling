"""Unit tests for agents/tools/note_context.py."""
from __future__ import annotations

import asyncio
from unittest.mock import patch

from agents.tools.note_context import (
    NoteContext,
    read_active_note,
)


def _run(coro):
    return asyncio.run(coro)


def test_read_active_note_returns_title_body_concepts():
    async def fake_get_note(note_id, user_id):
        return {"id": note_id, "user_id": user_id, "course_id": "c1",
                "title": "Photosynthesis", "body": "Light reactions...",
                "tags": ["lecture"],
                "last_summary": None, "last_summary_at": None,
                "created_at": "", "updated_at": ""}
    async def fake_list_linked(note_id, user_id):
        return [{"id": "g1", "concept_name": "Photosynthesis",
                 "mastery_tier": "learning", "mastery_score": 0.5,
                 "course_id": "c1"}]

    with patch("agents.tools.note_context.get_note", side_effect=fake_get_note), \
         patch("agents.tools.note_context.list_linked_concepts", side_effect=fake_list_linked):
        out = _run(read_active_note(note_id="n1", user_id="u1"))

    assert isinstance(out, NoteContext)
    assert out.title == "Photosynthesis"
    assert out.body == "Light reactions..."
    assert out.tags == ["lecture"]
    assert len(out.linked_concepts) == 1
    assert out.linked_concepts[0].concept_name == "Photosynthesis"


def test_read_active_note_missing_returns_empty_context():
    async def fake_get_note(note_id, user_id):
        return None
    with patch("agents.tools.note_context.get_note", side_effect=fake_get_note):
        out = _run(read_active_note(note_id="x", user_id="u1"))
    assert out.title == ""
    assert out.body == ""
    assert out.linked_concepts == []
