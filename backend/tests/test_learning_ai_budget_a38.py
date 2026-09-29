"""PKG-a38 lane C — owner decisions on HANDOFF-06b (OWNER-DECISIONS-A38.md "AI budget"):
the daily tutor-call COUNT cap (new), the session-capped flag (j), the soft scope that caused
the downgrade (k) and the server-minted usage-cache key (g). No DB, no LLM, no network: the
store is a fake table + rpc and the clock is fixed."""

from __future__ import annotations

import itertools
import logging
import pathlib
import re
from datetime import datetime, timedelta, timezone

import pytest

import config
from services import ai_budget

BACKEND = pathlib.Path(__file__).resolve().parents[1]
MIG_DIR = BACKEND / "db" / "migrations"
UID = "user_a38"
NOW = datetime(2026, 9, 29, 15, 0, 0, tzinfo=timezone.utc)
_ids = itertools.count()
_TUTOR_TABLE = "ai_tutor_daily_calls"
_TUTOR_RPC = "ai_budget_bump_tutor_calls"


def _row(*, cost=0.0, tokens=0, task="loop_tutor", ago_s=3600, user=UID):
    return {
        "id": f"row-{next(_ids)}",
        "user_id": user,
        "cost_usd": cost,
        "total_tokens": tokens,
        "task": task,
        "created_at": (NOW - timedelta(seconds=ago_s)).isoformat(),
    }


class _Store:
    """Fake PostgREST: llm_usage for page_all, ai_tutor_daily_calls for the count read, and
    the atomic increment RPC. ``fail`` = the tutor-call store is down (read and rpc raise)."""

    def __init__(self, usage_rows=(), *, fail=False):
        self.usage_rows = list(usage_rows)
        self.calls: dict[tuple[str, str], int] = {}
        self.fail = fail
        self.tables: list[str] = []
        self.rpcs: list[tuple[str, dict]] = []

    # table("llm_usage") → page_all → select_with_count
    def _usage_table(self):
        store = self

        class _T:
            def select_with_count(self, columns, filters=None, order=None, limit=None, offset=None):
                since = datetime.fromisoformat(
                    filters["created_at"].removeprefix("gte.").replace("Z", "+00:00")
                )
                user = filters.get("user_id", "eq.").removeprefix("eq.")
                hits = [
                    r
                    for r in store.usage_rows
                    if datetime.fromisoformat(r["created_at"]) >= since
                    and (not user or r["user_id"] == user)
                ]
                return hits[(offset or 0) : (offset or 0) + limit], len(hits)

        return _T()

    def _calls_table(self):
        store = self

        class _T:
            def select(self, columns="*", filters=None, order=None, limit=None, offset=None):
                if store.fail:
                    raise RuntimeError("pg down")
                key = (filters["user_id"].removeprefix("eq."), filters["day"].removeprefix("eq."))
                return [{"calls": store.calls[key]}] if key in store.calls else []

        return _T()

    def table(self, name):
        self.tables.append(name)
        if name == "llm_usage":
            return self._usage_table()
        if name == _TUTOR_TABLE:
            return self._calls_table()
        raise AssertionError(f"unexpected table {name}")

    def rpc(self, name, params):
        self.rpcs.append((name, params))
        if self.fail:
            raise RuntimeError("pg down")
        assert name == _TUTOR_RPC, name
        key = (params["p_user_id"], params["p_day"])
        self.calls[key] = self.calls.get(key, 0) + 1
        return self.calls[key]


@pytest.fixture
def store(monkeypatch):
    monkeypatch.setattr(ai_budget, "_utcnow", lambda: NOW)
    monkeypatch.setattr(config, "PLATFORM_DAILY_BUDGET_USD", None)

    def install(usage_rows=(), *, fail=False) -> _Store:
        fake = _Store(usage_rows, fail=fail)
        monkeypatch.setattr(ai_budget, "table", fake.table)
        monkeypatch.setattr(ai_budget, "rpc", fake.rpc)
        return fake

    return install


@pytest.fixture
def events(monkeypatch):
    calls: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        ai_budget, "log_event", lambda event_type, **kw: calls.append((event_type, kw))
    )
    return calls


# ── C1: the daily tutor-call count cap ───────────────────────────────────────


def test_tutor_call_cap_default_is_in_config_and_env_overridable():
    src = (BACKEND / "config.py").read_text()
    assert re.search(
        r'^STUDENT_DAILY_TUTOR_CALLS = int\(os\.getenv\("STUDENT_DAILY_TUTOR_CALLS", "200"\)\)',
        src,
        re.M,
    )
    assert isinstance(config.STUDENT_DAILY_TUTOR_CALLS, int)
    assert "daily_tutor_calls" in ai_budget._HARD_ORDER


def _count_to_cap(uid: str = UID) -> int:
    n = 0
    for _ in range(config.STUDENT_DAILY_TUTOR_CALLS):
        n = ai_budget.count_tutor_call(uid)
    return n


def test_count_tutor_call_increments_through_the_atomic_rpc(store):
    fake = store()
    assert [ai_budget.count_tutor_call(UID) for _ in range(3)] == [1, 2, 3]
    assert fake.rpcs[0] == (_TUTOR_RPC, {"p_user_id": UID, "p_day": "2026-09-29"})
    assert ai_budget.count_tutor_call("") == 0, "system actors carry no student budget"
    assert len(fake.rpcs) == 3


def test_cap_trips_on_call_count_while_llm_usage_costs_read_zero(store, events, monkeypatch):
    """The #689 failure: every llm_usage row priced at 0 blinds the $ and token caps."""
    monkeypatch.setattr(config, "STUDENT_DAILY_TUTOR_CALLS", 5)
    store([_row(cost=0.0, tokens=0) for _ in range(50)])
    for _ in range(4):
        ai_budget.count_tutor_call(UID)
    assert ai_budget.check(UID, "tutor", "develop").level == "normal"
    ai_budget.count_tutor_call(UID)
    d = ai_budget.check(UID, "tutor", "develop")
    assert (d.level, d.tier_ceiling, d.scope, d.pause_novice) == (
        "hard",
        "none",
        "daily_tutor_calls",
        True,
    )
    assert d.reset_at == datetime(2026, 9, 30, tzinfo=timezone.utc)
    assert ai_budget.check(UID, "tutor", "novice").scope == "daily_tutor_calls"
    assert [kw["payload"]["scope"] for _, kw in events] == ["daily_tutor_calls"]
    assert events[0][1]["payload"]["level"] == "hard"


def test_cap_trips_with_events_logging_disabled(store, monkeypatch):
    """EVENTS_LOGGING_ENABLED=false makes log_llm_usage a no-op: no llm_usage rows exist at all,
    so every $/token/rate cap is blind. The call counter does not go through events_service."""
    monkeypatch.setenv("EVENTS_LOGGING_ENABLED", "false")
    monkeypatch.setattr(config, "STUDENT_DAILY_TUTOR_CALLS", 3)
    store([])
    for _ in range(3):
        ai_budget.count_tutor_call(UID)
    d = ai_budget.check(UID, "tutor", "develop")
    assert (d.level, d.scope) == ("hard", "daily_tutor_calls")


def test_the_grader_path_is_unaffected_at_the_tutor_call_cap(store, monkeypatch):
    monkeypatch.setattr(config, "STUDENT_DAILY_TUTOR_CALLS", 2)
    fake = store([])
    ai_budget.count_tutor_call(UID)
    ai_budget.count_tutor_call(UID)
    assert ai_budget.check(UID, "tutor", "develop").level == "hard"
    fake.tables.clear()
    for kind in ("grader", "decision"):
        assert ai_budget.check(UID, kind) == ai_budget._NORMAL
    assert _TUTOR_TABLE not in fake.tables, "the grader path never reads the tutor counter"
    assert ai_budget.check(UID, "close").level == "normal", "the cap counts tutor calls only"


def test_a_failing_store_falls_back_to_the_in_process_counter(store, monkeypatch, caplog):
    monkeypatch.setattr(config, "STUDENT_DAILY_TUTOR_CALLS", 3)
    store([], fail=True)
    with caplog.at_level(logging.WARNING, logger="sapling.ai_budget"):
        assert [ai_budget.count_tutor_call(UID) for _ in range(2)] == [1, 2]
        assert ai_budget.check(UID, "tutor", "develop").level == "normal"
        ai_budget.count_tutor_call(UID)
        d = ai_budget.check(UID, "tutor", "develop")
    assert (d.level, d.scope) == ("hard", "daily_tutor_calls"), "the cap is never blind"
    messages = [r.getMessage() for r in caplog.records]
    assert any("tutor call counter" in m and "increment failed" in m for m in messages)
    assert any("tutor call counter" in m and "read failed" in m for m in messages)
    other = "someone_else"
    assert ai_budget.count_tutor_call(other) == 1, "the fallback is per user"


def test_the_fallback_counter_is_per_utc_day(store, monkeypatch):
    monkeypatch.setattr(config, "STUDENT_DAILY_TUTOR_CALLS", 2)
    store([], fail=True)
    _count_to_cap()
    assert ai_budget.check(UID, "tutor", "develop").level == "hard"
    monkeypatch.setattr(ai_budget, "_utcnow", lambda: NOW + timedelta(days=1))
    assert ai_budget.check(UID, "tutor", "develop").level == "normal"
    assert ai_budget.count_tutor_call(UID) == 1
    assert len(ai_budget._tutor_calls_local) == 1, "yesterday's keys are dropped"


def test_the_store_count_wins_when_other_workers_counted_more(store, monkeypatch):
    """Cross-worker: the store holds every worker's calls; this process saw none of them."""
    monkeypatch.setattr(config, "STUDENT_DAILY_TUTOR_CALLS", 10)
    fake = store([])
    fake.calls[(UID, "2026-09-29")] = 10
    assert ai_budget.check(UID, "tutor", "develop").scope == "daily_tutor_calls"
    assert ai_budget.count_tutor_call(UID) == 11


def test_a_store_that_lost_increments_never_undercounts_this_process(store, monkeypatch):
    monkeypatch.setattr(config, "STUDENT_DAILY_TUTOR_CALLS", 3)
    fake = store([], fail=True)
    _count_to_cap()  # all three increments failed; the store holds nothing
    fake.fail = False
    assert ai_budget.check(UID, "tutor", "develop").scope == "daily_tutor_calls"


def test_reset_for_tests_clears_the_fallback_counter(store):
    store([], fail=True)
    ai_budget.count_tutor_call(UID)
    ai_budget.reset_for_tests()
    assert ai_budget._tutor_calls_local == {}


def _calls_migration() -> tuple[str, str]:
    hits = sorted(MIG_DIR.glob("*_learning_ai_tutor_daily_calls.sql"))
    assert len(hits) == 1, f"expected exactly one tutor-calls migration, got {hits}"
    return hits[0].name, hits[0].read_text()


def _ddl(sql: str) -> str:
    return "\n".join(line for line in sql.splitlines() if not line.lstrip().startswith("--"))


def test_tutor_calls_migration_creates_the_counter_and_the_atomic_increment():
    name, sql = _calls_migration()
    assert re.fullmatch(r"\d{14}_learning_ai_tutor_daily_calls\.sql", name), name
    (prior,) = sorted(MIG_DIR.glob("*_learning_llm_usage_tokens.sql"))
    assert name > prior.name
    ddl = _ddl(sql)
    assert f"CREATE TABLE IF NOT EXISTS {_TUTOR_TABLE}" in ddl
    assert re.search(r"PRIMARY KEY \(user_id, day\)", ddl)
    assert re.search(rf"CREATE OR REPLACE FUNCTION {_TUTOR_RPC}\(p_user_id text, p_day date\)", ddl)
    assert "RETURNS integer" in ddl
    assert re.search(r"ON CONFLICT \(user_id, day\) DO UPDATE", ddl)
    assert re.search(rf"SET calls = {_TUTOR_TABLE}\.calls \+ 1", ddl)
    assert "RETURNING calls" in ddl


def test_tutor_calls_migration_is_backend_only():
    _, sql = _calls_migration()
    ddl = _ddl(sql)
    assert f"ALTER TABLE {_TUTOR_TABLE} ENABLE ROW LEVEL SECURITY" in ddl
    assert f"REVOKE ALL ON TABLE {_TUTOR_TABLE} FROM PUBLIC" in ddl
    assert f"REVOKE ALL ON FUNCTION {_TUTOR_RPC}(text, date) FROM PUBLIC" in ddl
    # Supabase roles are guarded (a plain Postgres has none), same idiom as canopy_active_users
    assert "ARRAY['anon', 'authenticated']" in ddl
    assert f"'REVOKE ALL ON TABLE {_TUTOR_TABLE} FROM %I'" in ddl
    assert f"'REVOKE ALL ON FUNCTION {_TUTOR_RPC}(text, date) FROM %I'" in ddl
    assert "GRANT EXECUTE ON FUNCTION" in ddl and "TO service_role" in ddl
    assert "NOTIFY pgrst, 'reload schema'" in ddl


def test_ai_budget_reaches_the_store_only_through_db_connection():
    src = (BACKEND / "services" / "ai_budget.py").read_text()
    assert "from db.connection import page_all, rpc, table" in src
    assert "import httpx" not in src



# ── C2 (06b j): the session-capped flag ──────────────────────────────────────


def _raising_app(decision_for):
    from fastapi import FastAPI

    app = FastAPI()
    app.add_exception_handler(ai_budget.AIBudgetExceeded, ai_budget.budget_exceeded_handler)

    @app.post("/turn")
    def turn():
        raise ai_budget.AIBudgetExceeded(decision_for())

    return app


def test_session_capped_is_set_whenever_the_session_counter_is_at_its_cap(store):
    from learning import params

    at_cap = {"session_tutor_requests": params.LOOP_SESSION_MAX_TUTOR_REQUESTS}
    # alone: the reported scope is the session's
    store([])
    d = ai_budget.check(UID, "tutor", "develop", **at_cap)
    assert (d.scope, d.session_capped) == ("session_requests", True)
    # beside a timed scope that is reported instead (06b j keeps the rule): still flagged, so
    # the banner says "for this session" whatever reset_at says
    store([_row(ago_s=5) for _ in range(config.LEARN_RATE_LIMIT_PER_MIN)])
    d = ai_budget.check(UID, "tutor", "develop", **at_cap)
    assert (d.scope, d.session_capped) == ("rate_limit", True)
    store([_row(cost=config.STUDENT_DAILY_BUDGET_USD)])
    d = ai_budget.check(UID, "tutor", "develop", **at_cap)
    assert (d.scope, d.session_capped) == ("daily_usd", True)
    # not at the cap: never flagged
    d = ai_budget.check(UID, "tutor", "develop")
    assert (d.scope, d.session_capped) == ("daily_usd", False)
    assert ai_budget._NORMAL.session_capped is False


def test_the_429_body_carries_session_capped(store):
    from fastapi.testclient import TestClient
    from learning import params

    store([_row(ago_s=5) for _ in range(config.LEARN_RATE_LIMIT_PER_MIN)])
    capped = TestClient(
        _raising_app(
            lambda: ai_budget.check(
                UID,
                "tutor",
                "develop",
                session_tutor_requests=params.LOOP_SESSION_MAX_TUTOR_REQUESTS,
            )
        )
    ).post("/turn")
    assert capped.status_code == 429
    assert (capped.json()["scope"], capped.json()["session_capped"]) == ("rate_limit", True)
    plain = TestClient(_raising_app(lambda: ai_budget.check(UID, "tutor", "develop"))).post("/turn")
    assert (plain.json()["scope"], plain.json()["session_capped"]) == ("rate_limit", False)


# ── C3 (06b k): the soft scope is the one that caused the downgrade ──────────


def test_a_novice_downgrade_reports_session_deep_not_daily_usd(store, events):
    """A novice turn at BOTH the $-soft level and the novice deep cap is downgraded by the deep
    cap alone (the $-soft level never downgrades novice turns), so the decision names it."""
    from learning import params

    novice_cap = config.STUDENT_DAILY_BUDGET_USD * config.BUDGET_NOVICE_MULTIPLIER
    store([_row(cost=novice_cap * config.STUDENT_SOFT_FRACTION)])
    d = ai_budget.check(
        UID, "tutor", "novice", session_deep_requests=params.LOOP_SESSION_MAX_DEEP_REQUESTS_NOVICE
    )
    assert (d.level, d.tier_ceiling, d.scope, d.reset_at) == (
        "soft",
        "standard",
        "session_deep",
        None,
    )
    assert {kw["payload"]["scope"] for _, kw in events} == {"daily_usd", "session_deep"}


def test_soft_scopes_that_do_cause_the_downgrade_are_unchanged(store):
    from learning import params

    # novice at the $-soft level only: no downgrade, the $ scope is reported (as before)
    novice_cap = config.STUDENT_DAILY_BUDGET_USD * config.BUDGET_NOVICE_MULTIPLIER
    store([_row(cost=novice_cap * config.STUDENT_SOFT_FRACTION)])
    d = ai_budget.check(UID, "tutor", "novice")
    assert (d.tier_ceiling, d.scope) == ("deep", "daily_usd")
    # develop: the $-soft level itself downgrades, so the first trigger stays the report
    store([_row(cost=config.STUDENT_DAILY_BUDGET_USD * config.STUDENT_SOFT_FRACTION)])
    d = ai_budget.check(
        UID, "tutor", "develop", session_deep_requests=params.LOOP_SESSION_MAX_DEEP_REQUESTS
    )
    assert (d.tier_ceiling, d.scope, d.reset_at) == (
        "standard",
        "daily_usd",
        datetime(2026, 9, 30, tzinfo=timezone.utc),
    )
