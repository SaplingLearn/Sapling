"""Real in-memory SDK export and strict accounting-only bridge contracts."""

from __future__ import annotations

import ast
from decimal import Decimal
import json
import logging
from pathlib import Path

import logfire
import pytest
from logfire.testing import SimpleSpanProcessor, TestExporter

from services import ops_logging
from services.logfire_scrubber import EXTRA_PATTERNS, scrub_value


@pytest.fixture
def exporter():
    value = TestExporter()
    logfire.configure(
        send_to_logfire=False,
        console=False,
        additional_span_processors=[SimpleSpanProcessor(value)],
        scrubbing=logfire.ScrubbingOptions(
            callback=scrub_value, extra_patterns=list(EXTRA_PATTERNS)
        ),
    )
    return value


def record(
    name="sapling.agents.usage",
    stage="agent_usage_capture",
    *,
    level=logging.WARNING,
    args=("RuntimeError",),
):
    return logging.LogRecord(
        name,
        level,
        __file__,
        1,
        f"Usage accounting hook failed (stage={stage}, error_type=%s)",
        args,
        None,
    )


@pytest.mark.parametrize(
    "name,stage",
    [(name, stage) for name, stages in ops_logging._STAGES.items() for stage in stages],
)
def test_each_actual_accounting_site_exports_only_fixed_metadata(exporter, name, stage):
    handler = ops_logging.AccountingLogfireHandler()
    row = record(name, stage)
    row.exc_info = (RuntimeError, RuntimeError("PRIVATE_EXCEPTION_MODEL_PROSE"), None)
    row.stack_info = "PRIVATE_STACK_PAYLOAD"
    row.private_extra = {"PRIVATE_LEARNER_KEY": "student@example.invalid"}
    handler.handle(row)
    spans = exporter.exported_spans_as_dict()
    assert len(spans) == 1
    attrs = spans[0]["attributes"]
    assert attrs["sapling.signal"] == "accounting_hook_failed"
    assert attrs["sapling.stage"] == stage and attrs["error.type"] == "RuntimeError"
    assert attrs["logger.name"] == name and attrs["logfire.level_num"] == 13
    assert attrs["logfire.msg"] == "Sapling usage accounting hook failed"
    assert not spans[0].get("events")
    blob = json.dumps(spans)
    assert "PRIVATE_" not in blob and "student@example.invalid" not in blob


@pytest.mark.parametrize(
    "damage",
    [
        "unknown_logger",
        "wrong_logger_stage",
        "unknown_stage",
        "rendered_message",
        "object_message",
        "mapping_args",
        "zero_args",
        "two_args",
        "error_level",
        "info_level",
    ],
)
def test_unknown_or_malformed_records_are_not_exported(exporter, damage):
    row = record()
    if damage == "unknown_logger":
        row.name = "arbitrary.student.logger"
    elif damage == "wrong_logger_stage":
        row.name = "services.chat_stream"
    elif damage == "unknown_stage":
        row.msg = "Usage accounting hook failed (stage=unknown, error_type=%s)"
    elif damage == "rendered_message":
        row.msg = (
            "Usage accounting hook failed (stage=agent_usage_capture, error_type=RuntimeError)"
        )
    elif damage == "object_message":
        row.msg = {"PRIVATE_PAYLOAD": True}
    elif damage == "mapping_args":
        row.args = {"PRIVATE_PAYLOAD": "x"}
    elif damage == "zero_args":
        row.args = ()
    elif damage == "two_args":
        row.args = ("RuntimeError", "PRIVATE_PAYLOAD")
    elif damage == "error_level":
        row.levelno = logging.ERROR
    else:
        row.levelno = logging.INFO
    ops_logging.AccountingLogfireHandler().handle(row)
    assert exporter.exported_spans_as_dict() == []


@pytest.mark.parametrize(
    "supplied",
    [
        "student@example.invalid",
        "PRIVATE_NATIVE_LOOKING_CLASS",
        "x" * 1000,
        None,
        {"private": "value"},
    ],
)
def test_unrecognized_error_type_is_fixed_other_error_not_user_data(exporter, supplied):
    row = record()
    row.args = (supplied,)  # LogRecord otherwise unwraps a single mapping argument.
    ops_logging.AccountingLogfireHandler().handle(row)
    spans = exporter.exported_spans_as_dict()
    assert len(spans) == 1 and spans[0]["attributes"]["error.type"] == "OtherError"
    assert "PRIVATE_" not in json.dumps(spans) and "student@example.invalid" not in json.dumps(
        spans
    )


def test_installation_is_idempotent_and_keeps_stderr_handlers(monkeypatch, exporter):
    loggers = [logging.getLogger(name) for name in ops_logging._LOGGER_NAMES]
    root_handlers = list(logging.getLogger().handlers)
    for logger in loggers:
        monkeypatch.setattr(logger, "handlers", [])
    calls = []

    class LocalHandler(logging.Handler):
        def emit(self, row):
            calls.append(row)

    local = LocalHandler()
    target = logging.getLogger("sapling.agents.usage")
    target.addHandler(local)
    ops_logging.install_accounting_logfire_bridge()
    ops_logging.install_accounting_logfire_bridge()
    for logger in loggers:
        assert (
            sum(isinstance(h, ops_logging.AccountingLogfireHandler) for h in logger.handlers) == 1
        )
    assert local in target.handlers and logging.getLogger().handlers == root_handlers
    target.warning(
        "Usage accounting hook failed (stage=agent_usage_capture, error_type=%s)", "ValueError"
    )
    assert len(calls) == len(exporter.exported_spans_as_dict()) == 1


def test_export_failure_does_not_change_caller_or_local_delivery(monkeypatch):
    def unavailable(*_args, **_kwargs):
        raise RuntimeError("PRIVATE_EXPORT_FAILURE")

    monkeypatch.setattr(logfire, "log", unavailable)
    logger = logging.getLogger("sapling.agents.usage")
    monkeypatch.setattr(logger, "handlers", [])
    rows = []

    class LocalHandler(logging.Handler):
        def emit(self, row):
            rows.append(row)

    logger.addHandler(ops_logging.AccountingLogfireHandler())
    logger.addHandler(LocalHandler())
    logger.warning(
        "Usage accounting hook failed (stage=agent_usage_capture, error_type=%s)", "RuntimeError"
    )
    assert len(rows) == 1


def test_allowlist_matches_exact_existing_sites_and_main_installs_bridge():
    root = Path(__file__).resolve().parents[1]
    found = {}
    for name in ops_logging._STAGES:
        module = {
            "sapling.agents.usage": "agents.usage",
            "services.chat_stream": "services.chat_stream",
            "routes.learn_loop": "routes.learn_loop",
        }[name]
        source = root / (module.replace(".", "/") + ".py")
        tree = ast.parse(source.read_text())
        assert _logger_name(tree, module) == name
        for node in ast.walk(tree):
            if (
                not isinstance(node, ast.Call)
                or not isinstance(node.func, ast.Attribute)
                or node.func.attr != "warning"
                or not node.args
            ):
                continue
            template = node.args[0]
            if (
                isinstance(template, ast.Constant)
                and isinstance(template.value, str)
                and template.value.startswith("Usage accounting hook failed")
            ):
                found[(name, template.value)] = True
    assert set(found) == set(ops_logging._RECORDS)
    main = ast.parse((root / "main.py").read_text())
    assert (
        sum(
            isinstance(n, ast.Call)
            and isinstance(n.func, ast.Name)
            and n.func.id == "install_accounting_logfire_bridge"
            for n in ast.walk(main)
        )
        == 1
    )


def test_railway_deploy_intent_has_explicit_health_and_teardown_settings():
    path = Path(__file__).resolve().parents[1] / "railway.json"
    value = json.loads(path.read_text())
    assert value["$schema"] == "https://railway.com/railway.schema.json"
    assert value["deploy"] == {
        "healthcheckPath": "/api/health",
        "healthcheckTimeout": 120,
        "overlapSeconds": 30,
        "drainingSeconds": 120,
        "restartPolicyType": "ON_FAILURE",
        "restartPolicyMaxRetries": 10,
    }
    assert "build" not in value  # no accidental source/builder override


@pytest.mark.parametrize(
    "name,level,template,args,signal",
    [
        ("sapling.events", logging.WARNING, ops_logging._QUEUE, (20000, 1), "events_queue_full"),
        (
            "sapling.events",
            logging.WARNING,
            ops_logging._DROPPED,
            (2, 5, "llm_usage"),
            "events_flush_dropped",
        ),
        ("sapling.events", logging.ERROR, ops_logging._LOST_USAGE, (), "usage_row_dropped"),
        (
            "sapling.ai_budget",
            logging.WARNING,
            ops_logging._PLATFORM,
            (Decimal(".1234567890"), 0.8, Decimal(".2")),
            "platform_spend_alert",
        ),
    ],
)
def test_queue_usage_loss_and_platform_signals_export_no_original_record_payload(
    exporter, name, level, template, args, signal
):
    row = logging.LogRecord(name, level, __file__, 1, template, args, None)
    row.exc_info = (RuntimeError, RuntimeError("PRIVATE_DATABASE_ERROR"), None)
    row.private_extra = "PRIVATE_RECORD_EXTRA"
    ops_logging.AccountingLogfireHandler().handle(row)
    spans = exporter.exported_spans_as_dict()
    assert len(spans) == 1
    attrs = spans[0]["attributes"]
    assert attrs["sapling.signal"] == signal
    assert attrs["logfire.level_num"] == (17 if level == logging.ERROR else 13)
    assert not spans[0].get("events") and "PRIVATE_" not in json.dumps(spans)
    if signal == "platform_spend_alert":
        assert (
            attrs["spent_usd"] == "0.1234567890"
            and attrs["alert_fraction"] == "0.8"
            and attrs["budget_usd"] == "0.2"
        )


@pytest.mark.parametrize(
    "name,level,template,args",
    [
        (
            "sapling.events",
            logging.DEBUG,
            "events row insert failed for table %r; row dropped",
            ("llm_usage",),
        ),
        ("sapling.events", logging.ERROR, ops_logging._QUEUE, (20000, 1)),
        ("sapling.events", logging.WARNING, ops_logging._QUEUE, (True, 1)),
        ("sapling.events", logging.WARNING, ops_logging._QUEUE, (20000, "PRIVATE_COUNT")),
        ("sapling.events", logging.WARNING, ops_logging._DROPPED, (5, 2, "llm_usage")),
        ("sapling.events", logging.WARNING, ops_logging._DROPPED, (1, 2, "PRIVATE_TABLE")),
        ("sapling.events", logging.WARNING, ops_logging._LOST_USAGE, ()),
        ("sapling.events", logging.ERROR, ops_logging._LOST_USAGE, ("PRIVATE_EXCEPTION",)),
        (
            "sapling.ai_budget",
            logging.WARNING,
            "ai_budget: platform spend read failed: %s",
            ("PRIVATE_ERROR",),
        ),
        ("sapling.ai_budget", logging.ERROR, ops_logging._PLATFORM, (1, 0.8, 2)),
        ("sapling.ai_budget", logging.WARNING, ops_logging._PLATFORM, (float("nan"), 0.8, 2)),
        ("sapling.ai_budget", logging.WARNING, ops_logging._PLATFORM, (float("inf"), 0.8, 2)),
        ("sapling.ai_budget", logging.WARNING, ops_logging._PLATFORM, (-1, 0.8, 2)),
        ("sapling.ai_budget", logging.WARNING, ops_logging._PLATFORM, (True, 0.8, 2)),
        ("sapling.ai_budget", logging.WARNING, ops_logging._PLATFORM, ("PRIVATE_PROSE", 0.8, 2)),
        (
            "sapling.ai_budget",
            logging.WARNING,
            ops_logging._PLATFORM,
            (Decimal("1e100000"), 0.8, 2),
        ),
        ("arbitrary.logger", logging.WARNING, ops_logging._PLATFORM, (1, 0.8, 2)),
    ],
)
def test_unstructured_debug_wrong_severity_counts_or_platform_values_never_export(
    exporter, name, level, template, args
):
    row = logging.LogRecord(name, level, __file__, 1, template, args, None)
    ops_logging.AccountingLogfireHandler().handle(row)
    assert exporter.exported_spans_as_dict() == []


def test_finite_operational_templates_are_exact_existing_source_calls():
    root = Path(__file__).resolve().parents[1]
    expected = {
        "services/events_service.py": {
            ops_logging._QUEUE: "warning",
            ops_logging._DROPPED: "warning",
            ops_logging._LOST_USAGE: "exception",
        },
        "services/ai_budget.py": {ops_logging._PLATFORM: "warning"},
    }
    for file, templates in expected.items():
        tree = ast.parse((root / file).read_text())
        expected_logger = "sapling.events" if "events_service" in file else "sapling.ai_budget"
        assert _logger_name(tree, file[:-3].replace("/", ".")) == expected_logger
        assert expected_logger in ops_logging._LOGGER_NAMES
        found = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.args:
                value = node.args[0]
                if isinstance(value, ast.Constant) and value.value in templates:
                    found[value.value] = node.func.attr
        assert found == templates


def _logger_name(tree, module):
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or not any(
            isinstance(target, ast.Name) and target.id == "logger" for target in node.targets
        ):
            continue
        value = node.value
        if (
            isinstance(value, ast.Call)
            and isinstance(value.func, ast.Attribute)
            and value.func.attr == "getLogger"
            and value.args
        ):
            argument = value.args[0]
            if isinstance(argument, ast.Constant):
                return argument.value
            if isinstance(argument, ast.Name) and argument.id == "__name__":
                return module
    raise AssertionError("actual logger declaration not recognized")
