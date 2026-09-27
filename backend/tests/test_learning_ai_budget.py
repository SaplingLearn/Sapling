"""PKG-06b — AI budget and usage (spec §3.5, §6, §13 A20/A21). llm_usage rows
come from a fake table and the clock is fixed: no DB, no LLM, no network."""

from __future__ import annotations

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
