"""PKG-06b — AI budget and usage (spec §3.5, §6, §13 A20/A21). llm_usage rows
come from a fake table and the clock is fixed: no DB, no LLM, no network."""

from __future__ import annotations

import itertools
import pathlib
import re
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

import config
from learning import params
from services import ai_budget, events_service, llm_pricing

BACKEND = pathlib.Path(__file__).resolve().parents[1]
MIG_DIR = BACKEND / "db" / "migrations"
UID = "user_andres"
NOW = datetime(2026, 9, 26, 15, 0, 0, tzinfo=timezone.utc)
_ids = itertools.count()


def _usage_sink(monkeypatch) -> list:
    rows: list = []
    monkeypatch.setattr(
        events_service,
        "table",
        lambda name: SimpleNamespace(insert=lambda r: rows.append((name, r)) or r),
    )
    return rows


# ── A21: migration, pricing, usage capture ───────────────────────────────────


def test_llm_usage_tokens_migration_is_the_spec_ddl():
    hits = sorted(MIG_DIR.glob("*_learning_llm_usage_tokens.sql"))
    assert len(hits) == 1, f"expected exactly one llm_usage_tokens migration, got {hits}"
    assert re.fullmatch(r"\d{14}_learning_llm_usage_tokens\.sql", hits[0].name), hits[0].name
    sql = hits[0].read_text()
    assert "ALTER TABLE llm_usage" in sql
    for column in ("cached_tokens", "thinking_tokens"):
        assert re.search(rf"ADD COLUMN IF NOT EXISTS {column} int\b", sql), column
    assert "NOT NULL" not in sql, "historical rows and unrecognised usage shapes stay NULL"


def test_cost_bills_cached_input_at_the_cached_rate():
    # flash per 1K: input 0.0003, cached 0.00003, output 0.0025 → (600×0.0003 + 400×0.00003 + 1000×0.0025)/1000
    assert llm_pricing.cost_usd("gemini-2.5-flash", 1000, 1000, cached_tokens=400) == pytest.approx(
        0.002692
    )
    # pro: (2000×0.00125 + 8000×0.000125 + 2000×0.010)/1000
    assert llm_pricing.cost_usd(
        "gemini-2.5-pro", 10_000, 2_000, cached_tokens=8_000
    ) == pytest.approx(0.0235)
    assert llm_pricing.cost_usd("gemini-2.5-flash", 1000, 1000) == pytest.approx(
        0.0028
    )  # no cache: unchanged


def test_cached_rates_are_ten_percent_of_input_and_clamped():
    cost = llm_pricing.cost_usd
    for model in ("gemini-2.5-flash-lite", "gemini-2.5-flash", "gemini-2.5-pro"):
        assert llm_pricing.CACHED_INPUT_PRICING[model] == pytest.approx(
            llm_pricing.MODEL_PRICING[model][0] * 0.1
        )
        assert cost(model, 1234, 567) == cost(model, 1234, 567, cached_tokens=0)
    assert cost("gemini-2.5-flash", 100, 0, cached_tokens=500) == cost(
        "gemini-2.5-flash", 100, 0, cached_tokens=100
    )
    # a model with no cached rate bills cached input at its full input rate (the no-cache upper bound)
    assert cost("gemini-2.0-flash", 1000, 10, cached_tokens=400) == cost(
        "gemini-2.0-flash", 1000, 10
    )


def test_record_agent_usage_captures_cached_and_thinking_tokens(monkeypatch):
    from pydantic_ai.usage import RunUsage
    from agents.usage import record_agent_usage

    rows = _usage_sink(monkeypatch)
    run_usage = RunUsage(
        input_tokens=1000,
        output_tokens=600,
        cache_read_tokens=400,
        details={"cached_content_tokens": 400, "thoughts_tokens": 500},
    )
    result = SimpleNamespace(
        usage=lambda: run_usage,
        all_messages=lambda: [],
        response=SimpleNamespace(model_name="gemini-2.5-flash"),
    )
    assert record_agent_usage(result, feature="learn_loop", task="grader", user_id=UID) is result
    events_service.flush_now()
    row = rows[0][1][0]
    assert (row["cached_tokens"], row["thinking_tokens"]) == (400, 500)
    assert row["cost_usd"] == pytest.approx(
        llm_pricing.cost_usd("gemini-2.5-flash", 1000, 600, cached_tokens=400)
    )


def test_every_llm_usage_row_carries_both_token_keys(monkeypatch):
    from pydantic_ai.usage import RunUsage
    from agents.usage import _cache_and_thinking

    rows = _usage_sink(monkeypatch)
    events_service.log_llm_usage(
        feature="quiz",
        task="quiz",
        model="gemini-2.5-flash",
        usage={"prompt_tokens": 10, "completion_tokens": 5},
    )
    events_service.flush_now()
    row = rows[0][1][0]
    assert (
        row["cached_tokens"] is None and row["thinking_tokens"] is None
    )  # uniform keys for bulk inserts
    assert _cache_and_thinking(RunUsage(input_tokens=5, output_tokens=5)) == (
        0,
        0,
    )  # Gemini omits zero counts
    assert _cache_and_thinking(SimpleNamespace(input_tokens=5)) == (
        None,
        None,
    )  # no such fields at all


# ── constants (spec §3.5) ────────────────────────────────────────────────────

_CONFIG_DEFAULTS = {
    "STUDENT_DAILY_BUDGET_USD": "0.20",
    "BUDGET_NOVICE_MULTIPLIER": "2.5",
    "STUDENT_SOFT_FRACTION": "0.8",
    "STUDENT_MONTHLY_BUDGET_USD": "2.00",
    "STUDENT_DAILY_TOKENS": "400000",
    "STUDENT_DAILY_GRADES": "300",
    "LEARN_RATE_LIMIT_PER_MIN": "20",
    "PLATFORM_ALERT_FRACTION": "0.8",
    "PLATFORM_CHECK_INTERVAL_S": "300",
}


def test_budget_defaults_in_config_match_spec():
    # Parsed from source: a developer's .env may override the live values, never the defaults.
    src = (BACKEND / "config.py").read_text()
    for name, default in _CONFIG_DEFAULTS.items():
        assert re.search(
            rf'^{name}\b.*os\.getenv\("{name}", "{re.escape(default)}"\)', src, re.M
        ), name
    assert re.search(r'os\.getenv\("PLATFORM_DAILY_BUDGET_USD", ""\)', src), (
        "platform budget is owner-set"
    )
    assert isinstance(config.STUDENT_DAILY_TOKENS, int) and isinstance(
        config.STUDENT_DAILY_GRADES, int
    )
    assert config.PLATFORM_DAILY_BUDGET_USD is None or isinstance(
        config.PLATFORM_DAILY_BUDGET_USD, float
    )


def test_session_caps_in_params_match_spec():
    assert (
        params.LOOP_SESSION_MAX_TUTOR_REQUESTS,
        params.LOOP_SESSION_MAX_DEEP_REQUESTS,
        params.LOOP_SESSION_MAX_DEEP_REQUESTS_NOVICE,
    ) == (40, 6, 12)


# ── ai.budget_capped (spec §6) ───────────────────────────────────────────────


@pytest.fixture
def events(monkeypatch):
    calls: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        ai_budget, "log_event", lambda event_type, **kw: calls.append((event_type, kw))
    )
    return calls


def test_budget_capped_is_in_the_taxonomy():
    assert "ai.budget_capped" in events_service.EVENT_TAXONOMY
    assert ai_budget.BUDGET_CAPPED_EVENT == "ai.budget_capped"


def test_emit_capped_once_per_user_scope_level_and_utc_day(events, monkeypatch):
    monkeypatch.setattr(ai_budget, "_utcnow", lambda: NOW)
    for _ in range(3):
        ai_budget._emit_capped(
            UID, "daily_usd", "hard", band="develop", spent_usd=0.25, cap_usd=0.2
        )
    ai_budget._emit_capped(UID, "daily_usd", "soft", band="develop", spent_usd=0.17, cap_usd=0.2)
    assert [kw["payload"]["level"] for _, kw in events] == ["hard", "soft"]
    event_type, kw = events[0]
    assert (event_type, kw["category"], kw["user_id"]) == ("ai.budget_capped", "usage", UID)
    assert kw["payload"] == {
        "user_id": UID,
        "scope": "daily_usd",
        "band": "develop",
        "level": "hard",
        "spent_usd": 0.25,
        "cap_usd": 0.2,
    }
    monkeypatch.setattr(ai_budget, "_utcnow", lambda: NOW + timedelta(days=1))
    ai_budget._emit_capped(UID, "daily_usd", "hard", band="develop")
    assert len(events) == 3, "a new UTC day re-arms the event"
    assert "spent_usd" not in events[2][1]["payload"], "None values are omitted, never zeroed"


def test_ai_budget_runs_no_model_and_lives_outside_learning():
    path = BACKEND / "services" / "ai_budget.py"
    roots = {
        m.group(1).split(".")[0]
        for m in re.finditer(r"^\s*(?:from|import)\s+([\w.]+)", path.read_text(), re.M)
    }
    assert not roots & {"agents", "pydantic_ai", "google"}, roots
    assert not (BACKEND / "learning" / "ai_budget.py").exists()


# ── check(): the degradation ladder (spec §3.5) ──────────────────────────────


class _UsageTable:
    """Fake llm_usage for page_all: honours the user_id and created_at filters."""

    def __init__(self, rows, raises=None):
        self.rows, self.raises, self.reads = rows, raises, 0

    def select_with_count(self, columns, filters=None, order=None, limit=None, offset=None):
        if self.raises:
            raise self.raises
        self.reads += 1
        since = datetime.fromisoformat(
            filters["created_at"].removeprefix("gte.").replace("Z", "+00:00")
        )
        user = filters.get("user_id", "eq.").removeprefix("eq.")
        hits = [
            r
            for r in self.rows
            if datetime.fromisoformat(r["created_at"]) >= since
            and (not user or r["user_id"] == user)
        ]
        return hits[(offset or 0) : (offset or 0) + limit], len(hits)


def _row(*, cost=0.0, tokens=0, task="loop_tutor", ago_s=3600, user=UID):
    return {
        "id": f"row-{next(_ids)}",
        "user_id": user,
        "cost_usd": cost,
        "total_tokens": tokens,
        "task": task,
        "created_at": (NOW - timedelta(seconds=ago_s)).isoformat(),
    }


@pytest.fixture
def usage(monkeypatch):
    monkeypatch.setattr(ai_budget, "_utcnow", lambda: NOW)
    monkeypatch.setattr(config, "PLATFORM_DAILY_BUDGET_USD", None)

    def install(rows, raises=None):
        fake = _UsageTable(list(rows), raises)
        monkeypatch.setattr(ai_budget, "table", lambda name: fake)
        return fake

    return install


def _develop_cap() -> float:
    return config.STUDENT_DAILY_BUDGET_USD


def _novice_cap() -> float:
    return config.STUDENT_DAILY_BUDGET_USD * config.BUDGET_NOVICE_MULTIPLIER


def _lt(d) -> tuple:
    return (d.level, d.tier_ceiling)


def test_below_the_soft_level_is_normal(usage, events):
    from learning import policy

    assert ai_budget.Tier is policy.Tier and ai_budget.BudgetLevel is policy.BudgetLevel
    usage([_row(cost=_develop_cap() * config.STUDENT_SOFT_FRACTION / 2)])
    d = ai_budget.check(UID, "tutor", "develop")
    assert (d.level, d.tier_ceiling, d.scope, d.pause_novice) == ("normal", "deep", None, False)
    assert events == []


@pytest.mark.parametrize("scope", ["daily_usd", "daily_tokens", "session_deep"])
def test_develop_soft_level_turns_deep_into_standard(usage, events, scope):
    rows, kw = [], {}
    if scope == "daily_usd":
        rows = [_row(cost=_develop_cap() * config.STUDENT_SOFT_FRACTION)]
    elif scope == "daily_tokens":
        rows = [_row(tokens=int(config.STUDENT_DAILY_TOKENS * config.STUDENT_SOFT_FRACTION))]
    else:
        kw = {"session_deep_requests": params.LOOP_SESSION_MAX_DEEP_REQUESTS}
    usage(rows)
    d = ai_budget.check(UID, "tutor", "develop", **kw)
    assert (d.level, d.tier_ceiling, d.scope, d.pause_novice) == ("soft", "standard", scope, False)
    assert [(e, k["payload"]["scope"], k["payload"]["level"]) for e, k in events] == [
        ("ai.budget_capped", scope, "soft")
    ]


@pytest.mark.parametrize(
    "scope", ["daily_usd", "monthly_usd", "daily_tokens", "session_requests", "rate_limit"]
)
def test_hard_level_pauses_the_tutor_and_novice_concepts(usage, events, scope):
    rows, kw = [], {}
    if scope == "daily_usd":
        rows = [_row(cost=_develop_cap())]
    elif scope == "monthly_usd":
        rows = [
            _row(cost=config.STUDENT_MONTHLY_BUDGET_USD, ago_s=3 * 86_400)
        ]  # earlier this month, not today
    elif scope == "daily_tokens":
        rows = [_row(tokens=config.STUDENT_DAILY_TOKENS)]
    elif scope == "rate_limit":
        rows = [_row(ago_s=5) for _ in range(config.LEARN_RATE_LIMIT_PER_MIN)]
    else:
        kw = {"session_tutor_requests": params.LOOP_SESSION_MAX_TUTOR_REQUESTS}
    usage(rows)
    for _ in range(3):
        d = ai_budget.check(UID, "tutor", "develop", **kw)
    # a rate-limit-only hard level pauses tutor turns but never novice concepts (spec §3.5)
    assert (d.level, d.tier_ceiling, d.scope, d.pause_novice) == (
        "hard",
        "none",
        scope,
        scope != "rate_limit",
    )
    assert len(events) == 1, "once per (user, scope, level, UTC day)"
    payload = events[0][1]["payload"]
    assert (payload["scope"], payload["level"], payload["band"]) == (scope, "hard", "develop")
    if scope == "daily_usd":
        assert payload["spent_usd"] == pytest.approx(_develop_cap()) and payload[
            "cap_usd"
        ] == pytest.approx(_develop_cap())


def test_reset_at_reports_the_scope_that_lasts_longest(usage):
    usage([_row(cost=config.STUDENT_MONTHLY_BUDGET_USD)])  # today: daily AND monthly
    d = ai_budget.check(UID, "tutor", "develop")
    assert (d.scope, d.reset_at) == ("monthly_usd", datetime(2026, 10, 1, tzinfo=timezone.utc))
    usage([_row(cost=_develop_cap())])
    d = ai_budget.check(UID, "tutor", "develop")
    assert (d.scope, d.reset_at) == ("daily_usd", datetime(2026, 9, 27, tzinfo=timezone.utc))
    assert ai_budget._next_month(datetime(2026, 12, 15, tzinfo=timezone.utc)) == datetime(
        2027, 1, 1, tzinfo=timezone.utc
    )


def test_novice_band_rules(usage):
    usage(
        [_row(cost=_develop_cap())]
    )  # a develop turn is hard here; a novice turn runs to the novice allowance
    assert ai_budget.check(UID, "tutor", "develop").level == "hard"
    assert _lt(ai_budget.check(UID, "tutor", "novice")) == ("normal", "deep")
    usage(
        [_row(cost=_novice_cap() * config.STUDENT_SOFT_FRACTION)]
    )  # the $-soft level never downgrades novice deep
    assert _lt(ai_budget.check(UID, "tutor", "novice")) == ("soft", "deep")
    usage(
        []
    )  # only the novice deep-request cap does; the develop cap does not apply to novice turns
    novice = params.LOOP_SESSION_MAX_DEEP_REQUESTS_NOVICE
    assert _lt(
        ai_budget.check(
            UID, "tutor", "novice", session_deep_requests=params.LOOP_SESSION_MAX_DEEP_REQUESTS
        )
    ) == ("normal", "deep")
    assert _lt(ai_budget.check(UID, "tutor", "novice", session_deep_requests=novice)) == (
        "soft",
        "standard",
    )
    usage([_row(cost=_novice_cap())])  # novice-band concepts pause at the novice hard level
    d = ai_budget.check(UID, "tutor", "novice")
    assert (d.level, d.tier_ceiling, d.pause_novice) == ("hard", "none", True)


def test_arm_sessions_are_not_downgraded_but_pause_at_hard(usage, events):
    usage([_row(cost=_develop_cap() * config.STUDENT_SOFT_FRACTION)])
    assert _lt(ai_budget.check(UID, "tutor", "develop", arm_session=True)) == ("normal", "deep")
    assert events[-1][1]["payload"]["level"] == "soft", (
        "the cap hit is still recorded (spec §10 covariate)"
    )
    d = ai_budget.check(
        UID,
        "tutor",
        "develop",
        arm_session=True,
        session_tutor_requests=params.LOOP_SESSION_MAX_TUTOR_REQUESTS,
    )
    assert _lt(d) == ("hard", "none")


def test_grader_cap_counts_grader_second_opinion_and_decision_rows(usage, events):
    per_task = config.STUDENT_DAILY_GRADES // 3
    rows = [_row(task=t) for t in ("grader", "grader_second", "decision") for _ in range(per_task)]
    rows += [_row(task="grader") for _ in range(config.STUDENT_DAILY_GRADES - len(rows))]
    rows += [_row(task="loop_tutor") for _ in range(5)]  # tutor rows never count as grades
    usage(rows)
    d = ai_budget.check(UID, "grader")
    assert (d.level, d.scope, d.pause_novice) == ("hard", "daily_grades", False)
    assert events[-1][1]["payload"] == {
        "user_id": UID,
        "scope": "daily_grades",
        "level": "grader_cap",
        "spent_usd": 0.0,
    }
    assert ai_budget.check(UID, "decision").level == "hard"


def test_grading_below_the_grade_cap_survives_the_tutor_hard_level(usage):
    usage(
        [_row(cost=config.STUDENT_MONTHLY_BUDGET_USD)]
        + [_row(task="grader") for _ in range(config.STUDENT_DAILY_GRADES - 1)]
    )
    assert ai_budget.check(UID, "tutor", "develop").level == "hard"
    assert ai_budget.check(UID, "grader").level == "normal"
    assert ai_budget.check(UID, "decision").level == "normal"


def test_close_is_hard_on_spend_only_and_kinds_are_closed(usage):
    usage([_row(cost=_develop_cap() * config.STUDENT_SOFT_FRACTION)])
    assert ai_budget.check(UID, "close").level == "normal"  # no soft level for the close
    usage([_row(cost=_develop_cap())])
    assert ai_budget.check(UID, "close").level == "hard"
    assert (
        ai_budget.check(UID, "close", "novice").level == "normal"
    )  # band-aware: the novice allowance
    usage([_row(ago_s=5) for _ in range(config.LEARN_RATE_LIMIT_PER_MIN)])
    assert ai_budget.check(UID, "close").level == "normal"  # the rate limit belongs to the routes
    assert ai_budget.check("", "grader").level == "normal"  # system actors carry no student budget
    for bad in ((UID, "tutor"), (UID, "chat")):  # tutor without a band; unknown kind
        with pytest.raises(ValueError):
            ai_budget.check(*bad)


def test_one_usage_read_per_request(usage):
    from services import request_context

    fake = usage([_row(task="grader")])
    token = request_context._REQUEST_ID_CTX.set("req-budget-0001")
    try:
        for kind, band in (("grader", None), ("tutor", "develop"), ("close", None)):
            ai_budget.check(UID, kind, band)
    finally:
        request_context._REQUEST_ID_CTX.reset(token)
    assert fake.reads == 1
    ai_budget.check(UID, "grader")  # outside a request: no cache
    assert fake.reads == 2


def test_usage_read_failure_fails_open_but_session_caps_hold(usage, caplog):
    usage([], raises=RuntimeError("pg down"))
    with caplog.at_level("WARNING"):
        assert ai_budget.check(UID, "tutor", "develop").level == "normal"
        assert ai_budget.check(UID, "grader").level == "normal"
    assert any("llm_usage read failed" in r.getMessage() for r in caplog.records)
    d = ai_budget.check(
        UID, "tutor", "develop", session_tutor_requests=params.LOOP_SESSION_MAX_TUTOR_REQUESTS
    )
    assert (d.level, d.scope) == ("hard", "session_requests")


def test_platform_alert_is_alert_only_and_fires_once(usage, events, monkeypatch, caplog):
    monkeypatch.setattr(config, "PLATFORM_DAILY_BUDGET_USD", 10.0)
    monkeypatch.setattr(ai_budget, "_spawn", lambda fn: fn())
    fake = usage([_row(cost=10.0 * config.PLATFORM_ALERT_FRACTION, user="someone_else")])
    with caplog.at_level("WARNING"):
        assert ai_budget.check(UID, "grader").level == "normal"  # never blocks a request
    platform = [kw for _, kw in events if kw["payload"]["scope"] == "platform"]
    assert (
        len(platform) == 1
        and platform[0]["user_id"] is None
        and platform[0]["payload"]["level"] == "soft"
    )
    assert any("platform spend" in r.getMessage() for r in caplog.records)
    reads = fake.reads
    ai_budget.check(UID, "grader")  # inside PLATFORM_CHECK_INTERVAL_S: only the per-user read
    assert fake.reads == reads + 1


def test_rate_limit_beside_another_hard_trigger_still_pauses_novice_concepts(usage):
    # "except when the rate limit is the only trigger" (spec §3.5 hard row)
    usage(
        [_row(cost=_develop_cap(), ago_s=5)]
        + [_row(ago_s=5) for _ in range(config.LEARN_RATE_LIMIT_PER_MIN)]
    )
    d = ai_budget.check(UID, "tutor", "develop")
    assert (d.level, d.scope, d.pause_novice) == ("hard", "daily_usd", True)


def test_unknown_band_is_a_programming_error(usage):
    usage([])
    with pytest.raises(ValueError):
        ai_budget.check(
            UID, "tutor", "beginner"
        )  # would otherwise get the develop allowance silently


def test_the_usage_read_pages_past_max_rows(usage):
    from db.connection import MAX_ROWS

    rows = [_row() for _ in range(MAX_ROWS)] + [_row(tokens=config.STUDENT_DAILY_TOKENS)]
    fake = usage(rows)  # the capping row sits past the first page: an unpaged read would miss it
    d = ai_budget.check(UID, "tutor", "develop")
    assert (d.level, d.scope) == ("hard", "daily_tokens")
    assert fake.reads == 2
