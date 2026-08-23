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

# ── The gamification world: the rows a submit MOVES ─────────────────────────
#
# A submit changes two of the numbers the hero card reports — `award_xp_safe`
# pays the XP, and the streak bump lives inside `apply_graph_update` — and the
# snapshot has to be read after both. A fixed `users` row cannot tell "read
# last" from "read first": every assertion below would pass with the block
# built at the top of the handler, which is precisely the regression G8's
# tests exist to catch. So the stubs are stateful and START pre-award; the
# post-award numbers are only reachable once the collaborators have fired.

PRE_AWARD_XP = 100
PRE_AWARD_LEVEL = 2
PRE_AWARD_STREAK = 3

QUIZ_XP = 30
POST_AWARD_XP = PRE_AWARD_XP + QUIZ_XP
POST_AWARD_LEVEL = 3
POST_AWARD_STREAK = 4

LONGEST_STREAK = 9
DAILY_GOAL_XP = 50


class GamificationWorld:
    """The `users` row and today's ledger, as one submit mutates them."""

    def __init__(self):
        self.total_xp = PRE_AWARD_XP
        self.level = PRE_AWARD_LEVEL
        self.streak = PRE_AWARD_STREAK
        self.today_xp = 0

    # — what the route's collaborators do to those numbers —

    def pay(self, amount: int, level: int | None = None) -> None:
        """What landing an `xp_events` row does to what /me reads."""
        self.total_xp += amount
        self.today_xp += amount
        if level is not None:
            self.level = level

    def award(self, result):
        """Stands in for `award_xp_safe`. `result` is the XpAward it hands
        back — or None for a write that raised, which moves nothing."""
        if result is not None and result.awarded:
            self.pay(result.awarded, result.level)
        return result

    def bump_streak(self, *_args, **_kwargs):
        """Stands in for `apply_graph_update`, which owns the streak. Returns
        the empty change list the route's `for change in applied or []` walks."""
        self.streak = POST_AWARD_STREAK
        return []

    # — the four tables the snapshot reads, resolved at CALL time —

    def tables(self, name):
        mock = MagicMock()
        if name == "users":
            mock.select.side_effect = lambda *a, **k: [{
                "total_xp": self.total_xp,
                "level": self.level,
                "streak_count": self.streak,
                "longest_streak": LONGEST_STREAK,
                "daily_goal_xp": DAILY_GOAL_XP,
            }]
        elif name == "user_achievements":
            mock.select.return_value = [{"achievement_id": "a1"}]
        elif name == "achievements":
            mock.select.return_value = [{"id": "a1"}, {"id": "a2"}, {"id": "a3"}]
        elif name == "xp_events":
            mock.select_with_count.side_effect = lambda *a, **k: (
                ([{"amount": self.today_xp,
                   "created_at": datetime.now(timezone.utc).isoformat()}], 1)
                if self.today_xp else ([], 0)
            )
        else:
            mock.select.return_value = []
            mock.select_with_count.return_value = ([], 0)
        return mock


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


#: Sentinel for `_submit(award=...)`: leave the real `award_xp_safe` in place.
REAL_AWARD = object()

DEFAULT_AWARD = XpAward(awarded=QUIZ_XP, total_xp=POST_AWARD_XP,
                        level=POST_AWARD_LEVEL, leveled_up=True)


def _submit(award=DEFAULT_AWARD, world=None):
    """POST /api/quiz/submit with every collaborator stubbed but the block.

    `award` is what the patched `award_xp_safe` returns (None = the write
    raised); pass REAL_AWARD to leave the real xp_service in place. Pass a
    `world` to inspect or pre-move it, or to read /me off the same state.
    """
    world = world or GamificationWorld()
    with ExitStack() as stack:
        enter = stack.enter_context
        enter(patch("routes.quiz.table", side_effect=_quiz_tables))
        enter(patch("routes.quiz.apply_graph_update", side_effect=world.bump_streak))
        enter(patch("routes.quiz.get_quiz_context", return_value={}))
        enter(patch(
            "routes.quiz.quiz_context_agent.run",
            new=AsyncMock(return_value=SimpleNamespace(
                output=SimpleNamespace(model_dump=lambda: {})
            )),
        ))
        enter(patch("routes.quiz.save_quiz_context"))
        enter(patch("services.gamification_service.table", side_effect=world.tables))
        if award is not REAL_AWARD:
            enter(patch("routes.quiz.award_xp_safe",
                        side_effect=lambda *a, **k: world.award(award)))
        return client.post("/api/quiz/submit", json={
            "quiz_id": "quiz1",
            "answers": [{"question_id": 1, "selected_label": "B"}],
        })


class TestTheBlockIsThere:
    def test_submit_returns_the_xp_and_the_hero_card_inline(self):
        r = _submit()

        assert r.status_code == 200, r.text
        block = r.json()["gamification"]
        assert block["xp_awarded"] == QUIZ_XP
        # Everything the results screen reads off /me today.
        assert block["total_xp"] == POST_AWARD_XP
        assert block["streak"] == POST_AWARD_STREAK
        # …and the rest of the card, so a later pass never needs a second call.
        assert block["level"] == POST_AWARD_LEVEL
        assert block["longest_streak"] == LONGEST_STREAK
        assert block["today_xp"] == QUIZ_XP
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
        rule_amount = 25
        ledger: list[dict] = []
        world = GamificationWorld()

        def xp_tables(name):
            mock = MagicMock()
            if name == "xp_rules":
                mock.select.return_value = [
                    {"key": "quiz_completed", "amount": rule_amount, "enabled": True}
                ]
            elif name == "xp_events":
                # The ledger write is what moves the hero card, so it moves the
                # world too — otherwise the snapshot reads a state the award
                # never reached and the ordering proof evaporates.
                def _insert(payload):
                    ledger.append(payload)
                    world.pay(payload["amount"])
                mock.insert.side_effect = _insert
                mock.select_with_count.return_value = (
                    [{"amount": PRE_AWARD_XP}, {"amount": rule_amount}], 2
                )
            elif name == "users":
                mock.select.return_value = [
                    {"total_xp": PRE_AWARD_XP, "level": PRE_AWARD_LEVEL}
                ]
                mock.update.return_value = []
            else:
                mock.select.return_value = []
                mock.select_with_count.return_value = ([], 0)
            return mock

        with patch("services.xp_service.table", side_effect=xp_tables):
            r = _submit(award=REAL_AWARD, world=world)

        assert r.status_code == 200, r.text
        assert [e["amount"] for e in ledger] == [rule_amount]
        block = r.json()["gamification"]
        assert block["xp_awarded"] == rule_amount
        # The snapshot saw the ledger write, not the state before it.
        assert block["total_xp"] == PRE_AWARD_XP + rule_amount


class TestTheSnapshotIsTakenLast:
    def test_the_card_reflects_the_award_and_the_streak_bump_this_submit_made(self):
        """The ordering guarantee — the property the whole block is for.

        `apply_graph_update` bumps the streak and `award_xp_safe` pays the XP;
        the snapshot must be read after BOTH, or the student is shown the
        numbers they walked in with. Move either call below
        `_gamification_block` in `routes/quiz.py` and this goes red.
        """
        world = GamificationWorld()
        assert (world.total_xp, world.streak) == (PRE_AWARD_XP, PRE_AWARD_STREAK), (
            "the stub must start PRE-award or this test proves nothing"
        )

        block = _submit(world=world).json()["gamification"]

        assert block["total_xp"] == POST_AWARD_XP, (
            "the snapshot was taken before award_xp_safe paid"
        )
        assert block["streak"] == POST_AWARD_STREAK, (
            "the snapshot was taken before apply_graph_update bumped the streak"
        )


class TestItAgreesWithTheEndpoint:
    def test_the_block_is_what_gamification_me_returns_right_after(self):
        """The reason both callers go through
        `services/gamification_service.py`: a second hand-rolled payload drifts
        the moment either side gains a field. Compared key-by-key against the
        live endpoint rather than against a fixture, so a field added to one
        and not the other fails here."""
        world = GamificationWorld()
        block = _submit(world=world).json()["gamification"]

        # After the submit, off the same rows the submit left behind — the
        # second read a client does today, and it must find the same card.
        with patch("services.gamification_service.table", side_effect=world.tables):
            me = client.get("/api/gamification/me?user_id=user_andres").json()

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
        # The rest of the card is still true and still worth sending — and
        # `total_xp` is the PRE-award number, because the write never landed.
        assert block["total_xp"] == PRE_AWARD_XP
        assert block["streak"] == POST_AWARD_STREAK

    def test_a_duplicate_award_reports_the_zero_it_paid(self):
        """The idempotent replay path pays nothing. Zero is the honest
        answer — distinct from `null`, which means "we don't know"."""
        award = XpAward(awarded=0, total_xp=PRE_AWARD_XP, level=PRE_AWARD_LEVEL,
                        leveled_up=False, duplicate=True)
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
