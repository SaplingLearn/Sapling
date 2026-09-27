"""Isolated OpenTelemetry log export for purpose-written PostHog records."""

from __future__ import annotations

import logging

from config import POSTHOG_HOST, POSTHOG_PROJECT_TOKEN


_LOGGER_NAME = "sapling.posthog_logs"
_logger = logging.getLogger(_LOGGER_NAME)
_logger.setLevel(logging.INFO)
_logger.propagate = False
_logger_provider = None
_log_handler = None


def initialize_posthog_log_capture() -> None:
    """Export only this module's explicit operational log lines to PostHog."""
    global _log_handler, _logger_provider

    if _logger_provider is not None or not POSTHOG_PROJECT_TOKEN or not POSTHOG_HOST:
        return

    from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
    from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
    from opentelemetry.sdk._logs.export import BatchLogRecordProcessor

    logger_provider = LoggerProvider()
    exporter = OTLPLogExporter(
        endpoint=f"{POSTHOG_HOST.rstrip('/')}/i/v1/logs",
        headers={"Authorization": f"Bearer {POSTHOG_PROJECT_TOKEN}"},
    )
    logger_provider.add_log_record_processor(BatchLogRecordProcessor(exporter))
    _log_handler = LoggingHandler(logger_provider=logger_provider)
    _logger.addHandler(_log_handler)
    _logger_provider = logger_provider
    _logger.info("PostHog log capture initialized")


def log_backend_ready() -> None:
    """Record that the FastAPI application completed its resource startup."""
    if _logger_provider is not None:
        _logger.info("Sapling backend startup completed")


def shutdown_posthog_log_capture() -> None:
    """Export the final lifecycle line and drain only this logger's provider."""
    global _log_handler, _logger_provider

    if _logger_provider is None:
        return

    _logger.info("Sapling backend shutdown started")
    if _log_handler is not None:
        _logger.removeHandler(_log_handler)
        _log_handler = None
    _logger_provider.shutdown()
    _logger_provider = None
