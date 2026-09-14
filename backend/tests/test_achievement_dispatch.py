"""Every live trigger_type has a call site that fires it.

`check_achievements(user_id, event_type)` only evaluates triggers whose
`trigger_type` equals `event_type`. A trigger type that `_get_user_stat` can
evaluate but that nothing ever *dispatches* is therefore a live, visible,
permanently unearnable badge — and worse than merely unearnable, because
routes/profile.py's progress bars call `_get_user_stat` read-only, so the user
watches a bar fill to 100/100 next to a badge that stays locked forever.

Eighteen of the thirty badges 0044 makes live were in exactly that state. The
existing tests didn't catch it because they asserted `_get_user_stat` returned
the right *number*, never that anything called `check_achievements` with the
matching event type. These tests assert the call site exists: drive the real
route/service and assert the dispatch happened.

`test_every_live_trigger_type_has_a_dispatch_site` is the backstop — it reads
the trigger types out of migration 0044 and fails if a new one is added without
a call site, so this cannot silently regress again.
"""
import re
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def _tables(handles, default_rows=None):
    """Dispatch on table name; unknown tables get an empty-select MagicMock."""
    def _get(name):
        if name in handles:
            return handles[name]
        m = MagicMock()
        m.select.return_value = default_rows if default_rows is not None else []
        m.select_with_count.return_value = ([], 0)
        return m
    return _get


def _fired(mock) -> set[str]:
    """Event types passed to a patched check_achievements."""
    return {c.args[1] for c in mock.call_args_list if len(c.args) > 1}


# ── services/xp_service.py::award_xp → level, xp_in_day ──────────────────────

class TestAwardXpDispatch:
    def _xp_tables(self, total_xp=0, level=1):
        handles = {"xp_rules": MagicMock(), "xp_events": MagicMock(),
                   "users": MagicMock()}
        handles["xp_rules"].select.return_value = [
            {"key": "quiz_completed", "amount": 30, "enabled": True}
        ]
        handles["xp_events"].insert.side_effect = lambda data: [data]
        handles["xp_events"].select_with_count.return_value = (
            [{"amount": total_xp + 30}], 1,
        )
        handles["users"].select.return_value = [{"total_xp": total_xp, "level": level}]
        handles["users"].update.return_value = []
        return _tables(handles), handles

    def test_fires_xp_in_day_on_every_award(self):
        tbl, _ = self._xp_tables()
        with patch("services.xp_service.table", side_effect=tbl), \
             patch("services.xp_service.level_for_xp", return_value=1), \
             patch("services.achievement_service.check_achievements") as check:
            from services.xp_service import award_xp
            award_xp("u1", "quiz_completed", source_type="quiz", source_id="q1")
        assert "xp_in_day" in _fired(check)

    def test_fires_level_only_on_a_level_up(self):
        tbl, _ = self._xp_tables()
        with patch("services.xp_service.table", side_effect=tbl), \
             patch("services.xp_service.level_for_xp", return_value=2), \
             patch("services.achievement_service.check_achievements") as check:
            from services.xp_service import award_xp
            award_xp("u1", "quiz_completed", source_type="quiz", source_id="q1")
        assert _fired(check) == {"level", "xp_in_day"}

    def test_does_not_fire_level_without_a_level_up(self):
        tbl, _ = self._xp_tables()
        with patch("services.xp_service.table", side_effect=tbl), \
             patch("services.xp_service.level_for_xp", return_value=1), \
             patch("services.achievement_service.check_achievements") as check:
            from services.xp_service import award_xp
            award_xp("u1", "quiz_completed", source_type="quiz", source_id="q1")
        assert "level" not in _fired(check)

    def test_a_badge_payout_cannot_recurse(self):
        """check_achievements pays xp_reward through award_xp_safe, which
        re-enters award_xp. Without a guard, a level-up badge that pays enough
        XP to level you up again recurses without bound. The inner award must
        skip its own dispatch — depth 1, always."""
        tbl, _ = self._xp_tables()
        depth = {"max": 0, "now": 0}

        def _reentrant(user_id, event_type, _data=None):
            depth["now"] += 1
            depth["max"] = max(depth["max"], depth["now"])
            try:
                from services.xp_service import award_xp_safe
                award_xp_safe(user_id, "achievement_unlocked", amount=500,
                              source_type="achievement", source_id="a1")
            finally:
                depth["now"] -= 1
            return []

        with patch("services.xp_service.table", side_effect=tbl), \
             patch("services.xp_service.level_for_xp", return_value=2), \
             patch("services.achievement_service.check_achievements",
                   side_effect=_reentrant):
            from services.xp_service import award_xp
            award_xp("u1", "quiz_completed", source_type="quiz", source_id="q1")

        assert depth["max"] == 1

    def test_a_broken_dispatch_does_not_fail_the_award(self):
        tbl, _ = self._xp_tables()
        with patch("services.xp_service.table", side_effect=tbl), \
             patch("services.xp_service.level_for_xp", return_value=1), \
             patch("services.achievement_service.check_achievements",
                   side_effect=RuntimeError("boom")):
            from services.xp_service import award_xp
            result = award_xp("u1", "quiz_completed", source_type="quiz", source_id="q1")
        assert result.awarded == 30

    def test_the_guard_is_released_after_a_failed_dispatch(self):
        """A dispatch that raises must still clear the re-entrancy flag, or
        every later award on that thread silently stops dispatching."""
        tbl, _ = self._xp_tables()
        with patch("services.xp_service.table", side_effect=tbl), \
             patch("services.xp_service.level_for_xp", return_value=1), \
             patch("services.achievement_service.check_achievements",
                   side_effect=RuntimeError("boom")):
            from services.xp_service import award_xp
            award_xp("u1", "quiz_completed", source_type="quiz", source_id="q1")
        with patch("services.xp_service.table", side_effect=tbl), \
             patch("services.xp_service.level_for_xp", return_value=1), \
             patch("services.achievement_service.check_achievements") as check:
            from services.xp_service import award_xp
            award_xp("u1", "quiz_completed", source_type="quiz", source_id="q2")
        assert "xp_in_day" in _fired(check)


# ── services/graph_service.py::apply_graph_update ────────────────────────────

class TestGraphDispatch:
    def test_fires_the_graph_trigger_types(self):
        handles = {"graph_nodes": MagicMock(), "node_mastery_events": MagicMock(),
                   "graph_edges": MagicMock()}
        handles["graph_nodes"].select.return_value = []
        handles["graph_nodes"].insert.return_value = [
            {"id": "n1", "concept_name": "Gradient Descent", "mastery_score": 0.1,
             "course_id": "c1"}
        ]
        with patch("services.graph_service.table", side_effect=_tables(handles)), \
             patch("services.graph_service.touch_streak_safe"), \
             patch("services.achievement_service.check_achievements") as check:
            from services.graph_service import apply_graph_update
            apply_graph_update("u1", {
                "new_nodes": [{"concept_name": "Gradient Descent",
                               "mastery_score": 0.1}],
            }, course_id="c1")
        assert _fired(check) >= {"concepts_mastered", "graph_nodes_count",
                                 "courses_with_mastery"}

    def test_a_broken_dispatch_does_not_fail_the_graph_write(self):
        handles = {"graph_nodes": MagicMock()}
        handles["graph_nodes"].select.return_value = []
        handles["graph_nodes"].insert.return_value = [
            {"id": "n1", "concept_name": "X", "mastery_score": 0.1, "course_id": "c1"}
        ]
        with patch("services.graph_service.table", side_effect=_tables(handles)), \
             patch("services.graph_service.touch_streak_safe"), \
             patch("services.achievement_service.check_achievements",
                   side_effect=RuntimeError("boom")):
            from services.graph_service import apply_graph_update
            apply_graph_update("u1", {"new_nodes": [{"concept_name": "X"}]},
                               course_id="c1")


# ── routes/flashcards.py::rate_card → flashcards_reviewed ────────────────────

class TestFlashcardReviewDispatch:
    def test_rating_a_card_fires_flashcards_reviewed(self):
        handles = {"flashcards": MagicMock()}
        handles["flashcards"].select.return_value = [{"id": "f1", "times_reviewed": 3}]
        with patch("routes.flashcards.table", side_effect=_tables(handles)), \
             patch("routes.flashcards.check_achievements") as check:
            r = client.post("/api/flashcards/rate", json={
                "user_id": "u1", "card_id": "f1", "rating": 3,
            })
        assert r.status_code == 200
        assert "flashcards_reviewed" in _fired(check)

    def test_a_broken_dispatch_does_not_fail_the_rating(self):
        handles = {"flashcards": MagicMock()}
        handles["flashcards"].select.return_value = [{"id": "f1", "times_reviewed": 3}]
        with patch("routes.flashcards.table", side_effect=_tables(handles)), \
             patch("routes.flashcards.check_achievements",
                   side_effect=RuntimeError("boom")):
            r = client.post("/api/flashcards/rate", json={
                "user_id": "u1", "card_id": "f1", "rating": 3,
            })
        assert r.status_code == 200


# ── routes/learn.py::end_session → session_* + goal_streak ───────────────────

class TestEndSessionDispatch:
    def test_fires_the_session_trigger_types(self):
        handles = {"sessions": MagicMock(), "messages": MagicMock()}
        handles["sessions"].select.return_value = [{
            "user_id": "u1",
            "started_at": "2026-07-31T10:00:00+00:00",
        }]
        handles["messages"].select.return_value = []
        with patch("routes.learn.table", side_effect=_tables(handles)), \
             patch("routes.learn.award_xp_safe"), \
             patch("routes.learn.touch_streak_safe"), \
             patch("services.achievement_service.check_achievements",
                   return_value=[]) as check:
            r = client.post("/api/learn/end-session",
                            json={"user_id": "u1", "session_id": "s1"})
        assert r.status_code == 200
        assert _fired(check) >= {
            "login_streak", "session_count", "session_minutes",
            "session_before_hour", "session_after_midnight", "goal_streak",
        }


# ── routes/social.py message post → room_replies, rooms_active ───────────────

class TestRoomMessageDispatch:
    def test_posting_fires_the_room_message_trigger_types(self):
        handles = {"room_members": MagicMock(), "room_messages": MagicMock()}
        handles["room_members"].select.return_value = [{"user_id": "u1"}]
        handles["room_messages"].insert.return_value = [{"id": "m1", "text": None}]
        with patch("routes.social.table", side_effect=_tables(handles)), \
             patch("services.achievement_service.check_achievements",
                   return_value=[]) as check:
            r = client.post("/api/social/rooms/r1/messages", json={
                "user_id": "u1", "user_name": "A", "text": "hi",
            })
        assert r.status_code == 200
        assert _fired(check) >= {"post_count", "room_replies", "rooms_active"}


# ── routes/social.py room join/create → owned_room_members ───────────────────

class TestOwnedRoomMembersDispatch:
    def test_joining_fires_for_the_room_owner_not_the_joiner(self):
        """`owned_room_members` is the ROOM CREATOR's stat (Grovekeeper: build
        a room five people join). Firing it for the joiner would evaluate the
        wrong user's rooms and the owner would never be granted."""
        handles = {"rooms": MagicMock(), "room_members": MagicMock()}
        handles["rooms"].select.return_value = [{
            "id": "r1", "name": "R", "topic": None, "course": None,
            "owner_id": "owner1", "created_by": "owner1", "invite_code": "ABC123",
            "created_at": None, "updated_at": None, "is_public": False,
        }]
        handles["room_members"].select.return_value = []
        with patch("routes.social.table", side_effect=_tables(handles)), \
             patch("routes.social._touch_room"), \
             patch("routes.social.invalidate_summary"), \
             patch("services.achievement_service.check_achievements",
                   return_value=[]) as check:
            r = client.post("/api/social/rooms/join", json={
                "user_id": "u1", "invite_code": "ABC123",
            })
        assert r.status_code == 200
        owned = [c for c in check.call_args_list
                 if len(c.args) > 1 and c.args[1] == "owned_room_members"]
        assert owned, "join never dispatched owned_room_members"
        assert owned[0].args[0] == "owner1"

    def test_public_join_fires_for_the_room_owner_not_the_joiner(self):
        """#405's public rooms are an invite-less second way in. It has to
        dispatch what the invite-code path dispatches, or `room-leader`
        (Grovekeeper) only advances for owners whose members happened to arrive
        by invite code — the same badge, earnable or not depending on which
        join button the fifth member pressed."""
        handles = {"rooms": MagicMock(), "room_members": MagicMock()}
        handles["rooms"].select.return_value = [{
            "id": "r1", "is_public": True, "created_by": "owner1",
        }]
        handles["room_members"].select.return_value = []
        with patch("routes.social.table", side_effect=_tables(handles)), \
             patch("routes.social._touch_room"), \
             patch("routes.social.invalidate_summary"), \
             patch("services.achievement_service.check_achievements",
                   return_value=[]) as check:
            r = client.post("/api/social/public-rooms/r1/join",
                            json={"user_id": "u1"})
        assert r.status_code == 200
        joined = [c for c in check.call_args_list
                  if len(c.args) > 1 and c.args[1] == "rooms_joined"]
        assert joined, "public join never dispatched rooms_joined"
        assert joined[0].args[0] == "u1"
        owned = [c for c in check.call_args_list
                 if len(c.args) > 1 and c.args[1] == "owned_room_members"]
        assert owned, "public join never dispatched owned_room_members"
        assert owned[0].args[0] == "owner1"

    def test_a_broken_dispatch_does_not_fail_the_public_join(self):
        handles = {"rooms": MagicMock(), "room_members": MagicMock()}
        handles["rooms"].select.return_value = [{
            "id": "r1", "is_public": True, "created_by": "owner1",
        }]
        handles["room_members"].select.return_value = []
        with patch("routes.social.table", side_effect=_tables(handles)), \
             patch("routes.social._touch_room"), \
             patch("routes.social.invalidate_summary"), \
             patch("services.achievement_service.check_achievements",
                   side_effect=RuntimeError("boom")):
            r = client.post("/api/social/public-rooms/r1/join",
                            json={"user_id": "u1"})
        assert r.status_code == 200

    def test_creating_a_room_fires_for_the_creator(self):
        handles = {"rooms": MagicMock(), "room_members": MagicMock()}
        with patch("routes.social.table", side_effect=_tables(handles)), \
             patch("routes.social.invalidate_summary"), \
             patch("services.achievement_service.check_achievements",
                   return_value=[]) as check:
            r = client.post("/api/social/rooms/create", json={
                "user_id": "u1", "room_name": "R",
            })
        assert r.status_code == 200
        assert "owned_room_members" in _fired(check)


# ── routes/gradebook.py grade writes → course_grade_a ────────────────────────

class TestGradebookDispatch:
    def _enrollment(self):
        return {"id": "e1", "user_id": "u1", "course_id": "c1", "term_id": "t1"}

    def test_recording_a_grade_fires_course_grade_a(self):
        handles = {"assignments": MagicMock()}
        handles["assignments"].insert.return_value = [{"id": "a1"}]
        with patch("routes.gradebook.table", side_effect=_tables(handles)), \
             patch("routes.gradebook._resolve_enrollment",
                   return_value=self._enrollment()), \
             patch("routes.gradebook.check_achievements", return_value=[]) as check:
            r = client.post("/api/gradebook/assignments", json={
                "user_id": "u1", "course_id": "c1", "title": "Midterm",
                "points_possible": 100, "points_earned": 95,
            })
        assert r.status_code == 200
        assert "course_grade_a" in _fired(check)

    def test_a_broken_dispatch_does_not_fail_the_grade_write(self):
        handles = {"assignments": MagicMock()}
        handles["assignments"].insert.return_value = [{"id": "a1"}]
        with patch("routes.gradebook.table", side_effect=_tables(handles)), \
             patch("routes.gradebook._resolve_enrollment",
                   return_value=self._enrollment()), \
             patch("routes.gradebook.check_achievements",
                   side_effect=RuntimeError("boom")):
            r = client.post("/api/gradebook/assignments", json={
                "user_id": "u1", "course_id": "c1", "title": "Midterm",
                "points_possible": 100, "points_earned": 95,
            })
        assert r.status_code == 200


# ── the backstop ─────────────────────────────────────────────────────────────

_MIGRATION = (
    Path(__file__).resolve().parent.parent
    / "db" / "migrations" / "20260731194102_achievement_catalog.sql"
)

# Fired somewhere other than a `check_achievements(...)` literal: account_age_days
# has no trigger in 0044 and manual_admin_grant is dispatched by the admin grant
# endpoint, which is a deliberate human action rather than a product event.
_NOT_EVENT_DISPATCHED = {"manual_admin_grant"}


def _trigger_types_in_migration() -> set[str]:
    sql = _MIGRATION.read_text(encoding="utf-8")
    body = sql.split("AS t(slug, trigger_type, trigger_threshold)")[0]
    return set(re.findall(r"\(\s*'[a-z0-9-]+'\s*,\s*'([a-z_]+)'\s*,\s*\d+\s*\)", body))


def _dispatched_event_types() -> set[str]:
    """Every string literal handed to a check_achievements(...) call site."""
    root = Path(__file__).resolve().parent.parent
    found: set[str] = set()
    for sub in ("routes", "services"):
        for path in (root / sub).glob("*.py"):
            src = path.read_text(encoding="utf-8")
            found |= set(re.findall(
                r"check_achievements\(\s*[^,]+,\s*[\"']([a-z_]+)[\"']", src))
    return found


class TestEveryTriggerTypeIsDispatched:
    def test_the_migration_parses(self):
        """Guard the guard: a regex that silently matches nothing would make
        the backstop below vacuously true."""
        types = _trigger_types_in_migration()
        assert len(types) >= 15
        assert "flashcards_reviewed" in types
        assert "goal_streak" in types

    def test_every_live_trigger_type_has_a_dispatch_site(self):
        """A live trigger type with no call site is a badge nothing can ever
        award — and profile.py still renders its progress bar filling up, so
        the user sees 100/100 next to a permanently locked badge."""
        needed = _trigger_types_in_migration() - _NOT_EVENT_DISPATCHED
        missing = sorted(needed - _dispatched_event_types())
        assert not missing, (
            f"live trigger types nothing ever fires: {missing} — "
            "add a check_achievements call site, or the badges are unearnable"
        )
