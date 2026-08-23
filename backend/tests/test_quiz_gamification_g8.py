"""G8 (Workstream G, epic #537): the submit response carries the XP line.

Before this, `POST /api/quiz/submit` paid XP and bumped the streak and told
the client neither. The results screen's only way to render
"+30 XP · 4-day streak" was to read `GET /api/gamification/me` before the
session and again after the submit and subtract
(`frontend/src/lib/quiz/useGamificationDelta.ts`) — two extra requests whose
race or failure showed a blank where the student's reward should be.

Submit now returns a `gamification` block: `xp_awarded` plus the same hero-card
snapshot `/api/gamification/me` serves, taken after the award. The tests below
pin the three things that make that block worth trusting:

  * it is there, with the numbers the award and the snapshot actually produced;
  * it is byte-for-byte what `/api/gamification/me` would return a moment later
    (the point of both callers sharing `services/gamification_service.py`);
  * neither failure mode invents a number — a failed award reports `null`, a
    failed snapshot read reports a `null` block, and neither fails the submit.
"""
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from main import app
from services.xp_service import XpAward

client = TestClient(app)


QUESTIONS = [
    {
        "id": 1,
        "question": "Q1?",
        "options": [
            {"label": "A", "text": "a1", "correct": False},
            {"label": "B", "text": "b1", "correct": True},
        ],
        "explanation": "B is right.",
        "concept_tested": "Loops",
        "difficulty": "medium",
    },
]

#: The post-award state the gamification tables are stubbed to report.
USER_ROW = {
    "total_xp": 130,
    "level": 3,
    "streak_count": 4,
    "longest_streak": 9,
    "daily_goal_xp": 50,
}


def _attempt_row(**overrides) -> dict:
    row = {
        "id": "quiz1",
        "user_id": "user_andres",
        "concept_node_id": "node1",
        "difficulty": "medium",
        "questions_json": QUESTIONS,
        "score": None,
        "total": None,
        "completed_at": None,
        "abandoned_at": None,
        "mastery_before": None,
        "mastery_after": None,
        "created_at": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
    }
    row.update(overrides)
    return row


def _quiz_tables(name):
    """routes.quiz's own reads — the attempt and its concept node."""
    mock = MagicMock()
    if name == "quiz_attempts":
        mock.select.return_value = [_attempt_row()]
        mock.update.return_value = [{"id": "quiz1"}]
    elif name == "graph_nodes":
        mock.select.return_value = [{
            "mastery_score": 0.5,
            "concept_name": "Loops",
            "course_id": "course1",
        }]
    else:
        mock.select.return_value = []
        mock.update.return_value = []
    return mock


def _gamification_tables(user_row=None, today_events=None):
    """The four tables the hero-card snapshot reads."""
    rows = USER_ROW if user_row is None else user_row
    events = [{"amount": 30, "created_at": datetime.now(timezone.utc).isoformat()}] \
        if today_events is None else today_events

    def factory(name):
        mock = MagicMock()
        if name == "users":
            mock.select.return_value = [rows]
        elif name == "user_achievements":
            mock.select.return_value = [{"achievement_id": "a1"}]
        elif name == "achievements":
            mock.select.return_value = [{"id": "a1"}, {"id": "a2"}, {"id": "a3"}]
        elif name == "xp_events":
            mock.select_with_count.return_value = (events, len(events))
        else:
            mock.select.return_value = []
            mock.select_with_count.return_value = ([], 0)
        return mock
    return factory


#: Sentinel for `_submit(award=...)`: leave the real `award_xp_safe` in place.
REAL_AWARD = object()

DEFAULT_AWARD = XpAward(awarded=30, total_xp=130, level=3, leveled_up=False)


def _submit(award=DEFAULT_AWARD, gamification_factory=None):
    """POST /api/quiz/submit with every collaborator stubbed but the block."""
    with ExitStack() as stack:
        enter = stack.enter_context
        enter(patch("routes.quiz.table", side_effect=_quiz_tables))
        enter(patch("routes.quiz.apply_graph_update"))
        enter(patch("routes.quiz.get_quiz_context", return_value={}))
        enter(patch(
            "routes.quiz.quiz_context_agent.run",
            new=AsyncMock(return_value=SimpleNamespace(
                output=SimpleNamespace(model_dump=lambda: {})
            )),
        ))
        enter(patch("routes.quiz.save_quiz_context"))
        enter(patch(
            "services.gamification_service.table",
            side_effect=gamification_factory or _gamification_tables(),
        ))
        if award is not REAL_AWARD:
            enter(patch("routes.quiz.award_xp_safe", return_value=award))
        return client.post("/api/quiz/submit", json={
            "quiz_id": "quiz1",
            "answers": [{"question_id": 1, "selected_label": "B"}],
        })


class TestTheBlockIsThere:
    def test_submit_returns_the_xp_and_the_hero_card_inline(self):
        r = _submit()

        assert r.status_code == 200, r.text
        block = r.json()["gamification"]
        assert block["xp_awarded"] == 30
        # Everything the results screen reads off /me today.
        assert block["total_xp"] == 130
        assert block["streak"] == 4
        # …and the rest of the card, so a later pass never needs a second call.
        assert block["level"] == 3
        assert block["longest_streak"] == 9
        assert block["today_xp"] == 30
        assert block["earned_count"] == 1
        assert block["total_count"] == 3

    def test_the_existing_response_fields_are_untouched(self):
        """G8 is additive. A client that has not migrated must not notice."""
        body = _submit().json()
        assert body["score"] == 1
        assert body["total"] == 1
        assert body["mastery_before"] == 0.5
        assert body["mastery_after"] is not None
        assert len(body["results"]) == 1

    def test_xp_awarded_is_what_the_ledger_actually_paid(self):
        """Not a constant, and not the rule's advertised amount either — the
        value `award_xp` reports having written. Driven through the real
        xp_service so a rewiring that returns, say, the rule row instead of
        the award is caught here rather than in production."""
        ledger: list[dict] = []

        def xp_tables(name):
            mock = MagicMock()
            if name == "xp_rules":
                mock.select.return_value = [
                    {"key": "quiz_completed", "amount": 25, "enabled": True}
                ]
            elif name == "xp_events":
                mock.insert.side_effect = lambda payload: ledger.append(payload)
                mock.select_with_count.return_value = (
                    [{"amount": 105}, {"amount": 25}], 2
                )
            elif name == "users":
                mock.select.return_value = [{"total_xp": 105, "level": 1}]
                mock.update.return_value = []
            else:
                mock.select.return_value = []
                mock.select_with_count.return_value = ([], 0)
            return mock

        with patch("services.xp_service.table", side_effect=xp_tables):
            r = _submit(award=REAL_AWARD)

        assert r.status_code == 200, r.text
        assert [e["amount"] for e in ledger] == [25]
        assert r.json()["gamification"]["xp_awarded"] == 25


class TestItAgreesWithTheEndpoint:
    def test_the_block_is_what_gamification_me_returns_right_after(self):
        """The reason both callers go through
        `services/gamification_service.py`: a second hand-rolled payload drifts
        the moment either side gains a field. Compared key-by-key against the
        live endpoint rather than against a fixture, so a field added to one
        and not the other fails here."""
        factory = _gamification_tables()
        with patch("services.gamification_service.table", side_effect=factory):
            me = client.get("/api/gamification/me?user_id=user_andres").json()

        block = _submit(gamification_factory=factory).json()["gamification"]

        assert set(block) == set(me) | {"xp_awarded"}
        assert {k: v for k, v in block.items() if k != "xp_awarded"} == me


class TestNeitherFailureInventsANumber:
    def test_a_failed_xp_award_reports_null_not_a_plausible_number(self):
        """`award_xp_safe` returns None when the ledger write raised. Reporting
        the rule's amount anyway would show the student XP they were never
        paid; the client's rule (R-9) is to omit the line, and `null` is what
        tells it to."""
        r = _submit(award=None)

        assert r.status_code == 200, r.text
        block = r.json()["gamification"]
        assert block["xp_awarded"] is None
        # The rest of the card is still true and still worth sending.
        assert block["total_xp"] == 130
        assert block["streak"] == 4

    def test_a_duplicate_award_reports_the_zero_it_paid(self):
        """The idempotent replay path pays nothing. Zero is the honest
        answer — distinct from `null`, which means "we don't know"."""
        award = XpAward(awarded=0, total_xp=130, level=3, leveled_up=False,
                        duplicate=True)
        assert _submit(award=award).json()["gamification"]["xp_awarded"] == 0

    def test_a_failed_snapshot_read_nulls_the_block_and_still_returns_200(self):
        """Display data must never fail the action that earned it — the same
        rule `award_xp_safe` follows. The client falls back to its own /me
        read, which is exactly today's behaviour."""
        with patch("routes.quiz.me_snapshot", side_effect=RuntimeError("pg down")):
            r = _submit()

        assert r.status_code == 200, r.text
        body = r.json()
        assert body["gamification"] is None
        assert body["score"] == 1, "the submit itself must still be scored"
