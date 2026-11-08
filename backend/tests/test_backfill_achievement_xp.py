"""scripts/backfill_achievement_xp.py — repays achievement XP the global
xp_events key denied (see test_xp_ledger_per_user_key.py)."""
import importlib
import sys
from datetime import datetime, timezone
from unittest.mock import MagicMock

import httpx
import pytest


@pytest.fixture
def mod(monkeypatch):
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: False)
    sys.modules.pop("scripts.backfill_achievement_xp", None)
    module = importlib.import_module("scripts.backfill_achievement_xp")
    yield module
    sys.modules.pop("scripts.backfill_achievement_xp", None)


def _dt(s):
    return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)


XP_LIVE = _dt("2026-08-01T00:00:00")
T0 = "2026-09-01T12:00:00+00:00"       # `first` was paid for a1
LATER = "2026-09-05T12:00:00+00:00"
PRE_XP = "2026-07-01T12:00:00+00:00"   # before any XP existed

BADGES = [
    {"id": "a1", "xp_reward": 50, "status": "live"},
    {"id": "free", "xp_reward": 0, "status": "live"},
    {"id": "wip", "xp_reward": 40, "status": "draft"},
]
PAYOUTS = [{"user_id": "first", "source_id": "a1", "created_at": T0}]


def _holding(user, badge="a1", earned_at=LATER):
    return {"user_id": user, "achievement_id": badge, "earned_at": earned_at}


def _reward_change(badge, at):
    return {"target_id": badge, "payload": {"xp_reward": 50}, "created_at": at}


def _plan(mod, holdings, payouts=PAYOUTS, **kw):
    kw.setdefault("xp_live_since", XP_LIVE)
    return mod.plan(holdings, payouts, BADGES, **kw)


class TestWhoIsOwed:
    def test_a_later_earner_of_a_paid_badge_is_owed_its_reward(self, mod):
        owed, skipped, _ = _plan(mod, [_holding("first", earned_at=T0), _holding("u2")])
        assert owed == [("u2", "a1", 50, _dt("2026-09-05T12:00:00").isoformat())]
        assert skipped["already_paid"] == 1

    def test_owed_even_when_the_original_payee_was_deleted(self, mod):
        """xp_events cascades on user delete: the evidence must not need the
        payee's row. An unchanged, paying badge is evidence enough."""
        owed, _, _ = _plan(mod, [_holding("u2")], payouts=[])
        assert [o[:3] for o in owed] == [("u2", "a1", 50)]

    def test_a_holder_from_before_xp_existed_is_not_owed(self, mod):
        owed, skipped, _ = _plan(mod, [_holding("u2", earned_at=PRE_XP)])
        assert owed == []
        assert skipped["not_paying_when_earned"] == 1

    def test_a_reward_raised_after_the_grant_is_not_paid_retroactively(self, mod):
        """Earned while the badge paid 0, then an admin set xp_reward: legitimately
        unpaid. No other payout near the grant says otherwise."""
        owed, skipped, _ = _plan(
            mod, [_holding("u2", earned_at="2026-08-10T00:00:00+00:00")], payouts=[],
            audit_rows=[_reward_change("a1", "2026-08-20T00:00:00+00:00")],
        )
        assert owed == []
        assert skipped["not_paying_when_earned"] == 1

    def test_a_payout_near_the_grant_proves_the_badge_was_paying(self, mod):
        # Reward edited after u2 earned it, but `first` was paid within the
        # heal window of u2's grant: it was paying then, and the key blocked u2.
        owed, _, _ = _plan(
            mod, [_holding("u2", earned_at="2026-09-01T11:00:00+00:00")],
            audit_rows=[_reward_change("a1", "2026-10-01T00:00:00+00:00")],
        )
        assert [o[:3] for o in owed] == [("u2", "a1", 50)]

    def test_soft_deleted_accounts_are_not_paid(self, mod):
        owed, skipped, _ = _plan(mod, [_holding("gone")], deleted_users={"gone"})
        assert owed == []
        assert skipped["account_deleted"] == 1

    def test_draft_holders_are_listed_for_a_rerun_not_paid(self, mod):
        owed, skipped, draft_held = _plan(mod, [_holding("u2", "wip"), _holding("u3", "wip")])
        assert owed == []
        assert draft_held == {"wip": 2}
        assert skipped["badge_not_live"] == 2

    def test_free_and_undated_holdings_are_left_alone(self, mod):
        owed, skipped, _ = _plan(mod, [_holding("u2", "free"), _holding("u3", earned_at=None)])
        assert owed == []
        assert (skipped["badge_pays_nothing"], skipped["unknown_earned_at"]) == (1, 1)


class _World:
    """The tables main() reads, plus a ledger whose writes can be scripted."""

    def __init__(self, holdings, *, deleted=(), own_rows=(), insert_effects=None):
        self.holdings = holdings
        self.deleted = list(deleted)
        self.own_rows = set(own_rows)              # (user, badge) a concurrent writer holds
        self.insert_effects = dict(insert_effects or {})  # (user, badge) -> exception
        self.written = []

    def page_all(self, handle, *a, **k):
        return iter([dict(r) for r in handle.rows])

    def table(self, name):
        m = MagicMock()
        m.rows = {
            "user_achievements": self.holdings,
            "xp_events": PAYOUTS,
            "admin_audit_log": [],
            "users": [{"id": u} for u in self.deleted],
        }.get(name, [])
        if name == "achievements":
            m.select.return_value = BADGES
        elif name == "xp_events":
            def _select(columns, filters=None, **kw):
                if columns == "created_at":
                    return [{"created_at": XP_LIVE.isoformat()}]
                key = (filters["user_id"][3:], filters["source_id"][3:])
                return [{"id": "x"}] if key in self.own_rows else []
            m.select.side_effect = _select

            def _insert(row):
                key = (row["user_id"], row["source_id"])
                if key in self.insert_effects:
                    raise self.insert_effects[key]
                self.written.append(row)
                return [row]
            m.insert.side_effect = _insert
        return m


def _conflict():
    return httpx.HTTPStatusError(
        "duplicate key", request=MagicMock(), response=MagicMock(status_code=409))


def _run(mod, monkeypatch, argv, world):
    import services.xp_service as xp
    monkeypatch.setattr(mod, "table", world.table)
    monkeypatch.setattr(mod, "page_all", world.page_all)
    monkeypatch.setattr(xp, "table", world.table)   # record_ledger_row's write
    settle = MagicMock(return_value=(0, 1, False))
    monkeypatch.setattr(mod, "settle_ledger_writes", settle)
    award = MagicMock()
    monkeypatch.setattr(xp, "award_xp", award)
    summary = mod.main(argv)
    award.assert_not_called()                       # never the today-dated path
    return summary, settle


THREE = [_holding("u2"), _holding("u3"), _holding("u2", "a1x")]


def test_dry_run_is_the_default_and_writes_nothing(mod, monkeypatch):
    world = _World([_holding("u2"), _holding("u3")])
    summary, settle = _run(mod, monkeypatch, [], world)
    assert (summary["owed"], summary["owed_xp"], summary["owed_students"]) == (2, 100, 2)
    assert world.written == []
    settle.assert_not_called()
    assert mod.exit_code(summary) == 0


def test_dry_run_is_not_a_flag_any_more(mod):
    with pytest.raises(SystemExit):
        mod.main(["--dry-run"])


def test_apply_back_dates_each_row_and_settles_each_student_once(mod, monkeypatch):
    """Repaying several badges must not land them all on today (golden-hour,
    daily goal, streaks): each row is dated at its grant."""
    BADGES.append({"id": "a1x", "xp_reward": 20, "status": "live"})
    try:
        world = _World(THREE)
        summary, settle = _run(mod, monkeypatch, ["--apply"], world)
    finally:
        BADGES.pop()
    assert summary["repaid"] == 3 and summary["repaid_xp"] == 120
    assert {(r["user_id"], r["source_id"], r["created_at"]) for r in world.written} == {
        ("u2", "a1", _dt("2026-09-05T12:00:00").isoformat()),
        ("u3", "a1", _dt("2026-09-05T12:00:00").isoformat()),
        ("u2", "a1x", _dt("2026-09-05T12:00:00").isoformat()),
    }
    assert all(r["idempotency_key"] == f"achievement_unlocked:achievement:{r['source_id']}"
               for r in world.written)
    assert sorted(c.args[0] for c in settle.call_args_list) == ["u2", "u3"]


def test_a_conflict_on_the_students_own_row_counts_as_paid_and_continues(mod, monkeypatch):
    world = _World([_holding("u2"), _holding("u3")],
                   own_rows={("u2", "a1")}, insert_effects={("u2", "a1"): _conflict()})
    summary, settle = _run(mod, monkeypatch, ["--apply"], world)
    assert summary["already_paid_concurrently"] == 1
    assert summary["repaid"] == 1 and summary["stopped"] == 0
    assert [c.args[0] for c in settle.call_args_list] == ["u3"]
    assert mod.exit_code(summary) == 0


def test_a_conflict_with_another_students_row_stops_the_run(mod, monkeypatch):
    world = _World([_holding("u2"), _holding("u3")],
                   insert_effects={("u2", "a1"): _conflict()})
    summary, settle = _run(mod, monkeypatch, ["--apply"], world)
    assert summary["stopped"] == 1 and summary["repaid"] == 0
    assert world.written == []
    assert mod.exit_code(summary) == 1


def test_a_failure_for_one_student_is_recorded_and_the_run_goes_on(mod, monkeypatch, capsys):
    boom = httpx.HTTPStatusError(
        "server error", request=MagicMock(), response=MagicMock(status_code=503))
    world = _World([_holding("u2"), _holding("u3")], insert_effects={("u2", "a1"): boom})
    summary, _ = _run(mod, monkeypatch, ["--apply"], world)
    assert summary["failed_students"] == 1 and summary["repaid"] == 1
    out = capsys.readouterr()
    assert "failed_students: 1" in out.out and "u2" in out.err
    assert mod.exit_code(summary) == 1


def test_soft_deleted_accounts_are_read_and_excluded(mod, monkeypatch):
    world = _World([_holding("u2"), _holding("gone")], deleted=["gone"])
    summary, _ = _run(mod, monkeypatch, ["--apply"], world)
    assert [r["user_id"] for r in world.written] == ["u2"]
    assert summary["account_deleted"] == 1


def test_draft_holders_are_printed(mod, monkeypatch, capsys):
    world = _World([_holding("u2", "wip")])
    _run(mod, monkeypatch, [], world)
    assert "wip: 1" in capsys.readouterr().out
