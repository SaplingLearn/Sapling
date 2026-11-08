"""scripts/backfill_achievement_xp.py — repays achievement XP the global
xp_events key denied (see test_xp_ledger_per_user_key.py)."""
import importlib
import sys
from unittest.mock import MagicMock

import pytest

from services.xp_service import XpAward


@pytest.fixture
def mod(monkeypatch):
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: False)
    sys.modules.pop("scripts.backfill_achievement_xp", None)
    module = importlib.import_module("scripts.backfill_achievement_xp")
    yield module
    sys.modules.pop("scripts.backfill_achievement_xp", None)


T0 = "2026-09-01T12:00:00+00:00"
LATER = "2026-09-05T12:00:00+00:00"
EARLIER = "2026-08-01T12:00:00+00:00"

BADGES = [
    {"id": "a1", "xp_reward": 50, "status": "live"},
    {"id": "free", "xp_reward": 0, "status": "live"},
    {"id": "wip", "xp_reward": 40, "status": "draft"},
]
# first: the one student the old key paid for a1.
PAYOUTS = [{"user_id": "first", "source_id": "a1", "created_at": T0}]


def _holding(user, badge="a1", earned_at=LATER):
    return {"user_id": user, "achievement_id": badge, "earned_at": earned_at}


class TestPlan:
    def test_a_later_earner_of_a_paid_badge_is_owed_its_reward(self, mod):
        owed, skipped = mod.plan([_holding("first", earned_at=T0), _holding("u2")],
                                 PAYOUTS, BADGES)
        assert owed == [("u2", "a1", 50)]
        assert skipped["already_paid"] == 1

    def test_a_holder_who_earned_before_anyone_was_paid_was_not_blocked(self, mod):
        """No other student held the key when this one earned it, so the key
        cannot be why they have no payout (the badge most likely paid 0 then):
        repaying them would be a retroactive payout of a later reward change."""
        owed, skipped = mod.plan([_holding("u2", earned_at=EARLIER)], PAYOUTS, BADGES)
        assert owed == []
        assert skipped["not_blocked_by_key"] == 1

    def test_a_payee_inside_the_heal_window_still_blocked_the_heal(self, mod):
        # u2 earned an hour before `first` was paid; u2's own award failed and
        # the heal within HEAL_WINDOW then collided with first's key.
        owed, _ = mod.plan([_holding("u2", earned_at="2026-09-01T11:00:00+00:00")],
                           PAYOUTS, BADGES)
        assert owed == [("u2", "a1", 50)]

    def test_draft_free_and_undated_badges_are_left_alone(self, mod):
        payouts = PAYOUTS + [
            {"user_id": "first", "source_id": "free", "created_at": T0},
            {"user_id": "first", "source_id": "wip", "created_at": T0},
        ]
        owed, skipped = mod.plan(
            [_holding("u2", "free"), _holding("u2", "wip"), _holding("u3", earned_at=None)],
            payouts, BADGES,
        )
        assert owed == []
        assert (skipped["badge_pays_nothing"], skipped["badge_not_live"],
                skipped["unknown_earned_at"]) == (1, 1, 1)


def _run(mod, monkeypatch, argv, *, award_result=None):
    tables = {
        "user_achievements": [_holding("first", earned_at=T0), _holding("u2"), _holding("u3")],
        "xp_events": PAYOUTS,
    }

    def _page_all(handle, *a, **k):
        return iter([dict(r) for r in handle.rows])

    def _table(name):
        m = MagicMock()
        m.rows = tables.get(name, [])
        m.select.return_value = BADGES
        return m

    award = MagicMock(return_value=award_result or XpAward(
        awarded=50, total_xp=50, level=1, leveled_up=False))
    monkeypatch.setattr(mod, "table", _table)
    monkeypatch.setattr(mod, "page_all", _page_all)
    monkeypatch.setattr(mod, "award_xp", award)
    return mod.main(argv), award


def test_dry_run_is_the_default_and_pays_nothing(mod, monkeypatch):
    summary, award = _run(mod, monkeypatch, [])
    assert (summary["owed"], summary["owed_xp"]) == (2, 100)
    award.assert_not_called()


def test_apply_pays_through_award_xp_with_the_shared_key_shape(mod, monkeypatch):
    summary, award = _run(mod, monkeypatch, ["--apply"])
    assert summary["repaid"] == 2 and summary["repaid_xp"] == 100
    assert [c.args for c in award.call_args_list] == [
        ("u2", "achievement_unlocked"), ("u3", "achievement_unlocked"),
    ]
    assert award.call_args.kwargs == {
        "source_type": "achievement", "source_id": "a1", "amount": 50,
    }


def test_apply_before_the_migration_stops_at_the_first_conflict(mod, monkeypatch):
    summary, award = _run(mod, monkeypatch, ["--apply"], award_result=XpAward(
        awarded=0, total_xp=0, level=1, leveled_up=False, duplicate=True))
    assert summary["blocked"] == 1 and summary["repaid"] == 0
    award.assert_called_once()
