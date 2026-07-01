"""Tests for the #147 one-shot LLM → Pydantic AI agent migration.

Covers the study-group summary paths on /api/social/rooms/{id}/overview
(cache miss / cache hit / agent failure) and the StudyGuide typed output's
serialization back to the legacy JSON contract.
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from main import app

client = TestClient(app)

ROOM_ID = "room_1"


def _social_table_side_effect(name):
    m = MagicMock()
    if name == "room_members":
        # Same list serves both the membership gate and the member roster.
        m.select.return_value = [{"user_id": "u1"}]
    elif name == "rooms":
        m.select.return_value = [{"id": ROOM_ID, "name": "Calc Crew", "topic": "Calc"}]
    else:
        m.select.return_value = []
    return m


_GRAPH = {"nodes": [
    {"concept_name": "Limits", "mastery_tier": "mastered"},
    {"concept_name": "Series", "mastery_tier": "struggling"},
]}


class TestRoomOverviewSummary:
    def test_cache_miss_runs_agent_and_persists(self):
        agent_run = AsyncMock(
            return_value=SimpleNamespace(output=SimpleNamespace(summary="Strong together."))
        )
        save = MagicMock()
        with patch("routes.social.table", side_effect=_social_table_side_effect), \
             patch("routes.social.get_display_names", return_value={"u1": "Alice"}), \
             patch("routes.social.get_graph", return_value=_GRAPH), \
             patch("routes.social.get_cached_summary", return_value=None), \
             patch("routes.social.social_summary_agent.run", new=agent_run), \
             patch("routes.social.save_summary", new=save):
            r = client.get(f"/api/social/rooms/{ROOM_ID}/overview")
        assert r.status_code == 200
        assert r.json()["ai_summary"] == "Strong together."
        agent_run.assert_called_once()
        save.assert_called_once()

    def test_cache_hit_does_not_run_agent(self):
        agent_run = AsyncMock()
        with patch("routes.social.table", side_effect=_social_table_side_effect), \
             patch("routes.social.get_display_names", return_value={"u1": "Alice"}), \
             patch("routes.social.get_graph", return_value=_GRAPH), \
             patch("routes.social.get_cached_summary", return_value="cached summary"), \
             patch("routes.social.social_summary_agent.run", new=agent_run):
            r = client.get(f"/api/social/rooms/{ROOM_ID}/overview")
        assert r.status_code == 200
        assert r.json()["ai_summary"] == "cached summary"
        agent_run.assert_not_called()

    def test_agent_failure_falls_back_and_returns_200(self):
        boom = AsyncMock(side_effect=RuntimeError("gemini down"))
        with patch("routes.social.table", side_effect=_social_table_side_effect), \
             patch("routes.social.get_display_names", return_value={"u1": "Alice"}), \
             patch("routes.social.get_graph", return_value=_GRAPH), \
             patch("routes.social.get_cached_summary", return_value=None), \
             patch("routes.social.social_summary_agent.run", new=boom):
            r = client.get(f"/api/social/rooms/{ROOM_ID}/overview")
        assert r.status_code == 200
        assert r.json()["ai_summary"] == (
            "This study group has complementary strengths across multiple subjects."
        )


class TestStudyGuideOutputShape:
    def test_model_dumps_to_legacy_contract(self):
        from agents.study_guide import StudyGuide, Topic

        guide = StudyGuide(
            exam="Midterm",
            due_date="2026-05-01",
            overview="Covers chapters 1-5.",
            topics=[Topic(name="Limits", importance="Foundational.", concepts=["a", "b", "c"])],
        )
        d = guide.model_dump()
        assert set(d.keys()) == {"exam", "due_date", "overview", "topics"}
        assert d["topics"][0] == {
            "name": "Limits",
            "importance": "Foundational.",
            "concepts": ["a", "b", "c"],
        }
