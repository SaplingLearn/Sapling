"""Real operational emitters reach the SDK exporter without exporting row bodies."""
from decimal import Decimal
import json
import logging
import queue

import logfire
from logfire.testing import SimpleSpanProcessor, TestExporter
import pytest

from agents import usage as agent_usage
from services import ai_budget, events_service, ops_logging
from services.logfire_scrubber import EXTRA_PATTERNS, scrub_value


@pytest.fixture
def exported(monkeypatch):
    exporter = TestExporter()
    logfire.configure(
        send_to_logfire=False, console=False,
        additional_span_processors=[SimpleSpanProcessor(exporter)],
        scrubbing=logfire.ScrubbingOptions(callback=scrub_value, extra_patterns=list(EXTRA_PATTERNS)),
    )
    actual_loggers = {events_service.logger.name, ai_budget.logger.name, agent_usage.logger.name}
    for name in actual_loggers | set(ops_logging._LOGGER_NAMES):
        logger = logging.getLogger(name)
        monkeypatch.setattr(logger, "handlers", [])
        monkeypatch.setattr(logger, "level", logging.WARNING)
        monkeypatch.setattr(logger, "propagate", False)
    ops_logging.install_accounting_logfire_bridge()
    return exporter


def only_signal(exporter, expected):
    spans = exporter.exported_spans_as_dict()
    signals = [span["attributes"] for span in spans if span.get("attributes", {}).get("sapling.signal")]
    assert len(signals) == 1 and signals[0]["sapling.signal"] == expected
    assert "PRIVATE_" not in json.dumps(spans)
    assert "student@example.invalid" not in json.dumps(spans)
    return signals[0]


def test_real_queue_overflow_exports_counts_without_the_dropped_row(exported, monkeypatch):
    bounded = queue.Queue(maxsize=1)
    bounded.put_nowait({"table": "events", "row": {"PRIVATE_EXISTING": "student@example.invalid"}})
    monkeypatch.setattr(events_service, "_queue", bounded)
    monkeypatch.setattr(events_service, "_dropped", 0)
    events_service._enqueue("llm_usage", {"PRIVATE_DROPPED_ROW": "student@example.invalid"})
    attrs = only_signal(exported, "events_queue_full")
    assert attrs["queue_capacity"] == attrs["dropped_count"] == 1
    assert events_service.dropped_count() == 1 and bounded.qsize() == 1


def test_real_per_row_delivery_failure_exports_aggregate_without_exception_or_rows(exported, monkeypatch):
    class UnavailableTable:
        def insert(self, _row):
            raise RuntimeError("PRIVATE_DATABASE_ERROR student@example.invalid")

    monkeypatch.setattr(events_service, "table", lambda _name: UnavailableTable())
    events_service._flush_rows_individually("llm_usage", [{"PRIVATE_ROW_BODY": "student@example.invalid"}])
    attrs = only_signal(exported, "events_flush_dropped")
    assert attrs["dropped_count"] == attrs["batch_count"] == 1
    assert attrs["table_name"] == "llm_usage"


def test_real_usage_build_failure_exports_fixed_signal_without_exception_stack(exported, monkeypatch):
    def unavailable(**_kwargs):
        raise RuntimeError("PRIVATE_USAGE_EXCEPTION student@example.invalid")

    monkeypatch.setattr(events_service, "_logging_enabled", lambda: True)
    monkeypatch.setattr(events_service, "build_llm_usage_row", unavailable)
    events_service.log_llm_usage(feature="PRIVATE_FEATURE", task="PRIVATE_TASK", model="synthetic-model", usage={})
    attrs = only_signal(exported, "usage_row_dropped")
    assert attrs["sapling.stage"] == "llm_usage_build" and "exception.stacktrace" not in attrs


def test_real_agent_usage_capture_failure_exports_metadata_and_returns_the_same_run(exported, monkeypatch):
    class Run:
        def usage(self):
            raise RuntimeError("PRIVATE_PROVIDER_USAGE student@example.invalid")

    monkeypatch.setattr(agent_usage, "_warn_zero_token_run", lambda *_a: None)
    monkeypatch.setattr(agent_usage, "_log_recovered_retries", lambda *_a: None)
    result = Run()
    assert agent_usage.record_agent_usage(result, feature="PRIVATE_FEATURE") is result
    attrs = only_signal(exported, "accounting_hook_failed")
    assert attrs["sapling.stage"] == "agent_usage_capture" and attrs["error.type"] == "RuntimeError"


def test_real_platform_spend_check_exports_amounts_and_does_not_change_admission(exported, monkeypatch):
    monkeypatch.setattr(ai_budget.config, "PLATFORM_DAILY_BUDGET_USD", Decimal("1.00"))
    monkeypatch.setattr(ai_budget.config, "PLATFORM_ALERT_FRACTION", Decimal("0.8"))
    monkeypatch.setattr(ai_budget, "table", lambda _name: object())
    monkeypatch.setattr(ai_budget, "page_all", lambda *_a, **_k: [{"cost_usd": "0.90", "PRIVATE_UNUSED": "student@example.invalid"}])
    observed = []
    monkeypatch.setattr(ai_budget, "_emit_capped", lambda *a, **k: observed.append((a, k)))
    assert ai_budget._check_platform() is None
    attrs = only_signal(exported, "platform_spend_alert")
    assert Decimal(attrs["spent_usd"]) == Decimal("0.90")
    assert Decimal(attrs["budget_usd"]) == 1 and Decimal(attrs["alert_fraction"]) == Decimal("0.8")
    assert len(observed) == 1 and observed[0][0] == (None, "platform", "soft")
