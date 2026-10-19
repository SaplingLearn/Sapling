"""Finite operational accounting signals, never a general stdlib log export.

Stderr delivery remains unchanged. Only exact controlled templates, severities
and argument shapes are mirrored as content-free Logfire events.
"""

from __future__ import annotations

import builtins
from decimal import Decimal, InvalidOperation
import logging
import re

import logfire

_STAGES = {
    "sapling.agents.usage": (
        "agent_usage_capture",
        "agent_zero_token_check",
        "agent_retry_observability",
    ),
    "services.chat_stream": ("legacy_stream_usage", "structured_stream_usage"),
    "routes.learn_loop": ("loop_continuation_usage",),
}
_RECORDS = {
    (name, f"Usage accounting hook failed (stage={stage}, error_type=%s)"): stage
    for name, stages in _STAGES.items()
    for stage in stages
}
_LOGGER_NAMES = frozenset(_STAGES) | {"sapling.events", "sapling.ai_budget"}
_ERROR_TYPES = frozenset(
    name
    for name, value in vars(builtins).items()
    if isinstance(value, type) and issubclass(value, BaseException)
) | {
    "HTTPError",
    "HTTPStatusError",
    "RequestError",
    "TransportError",
    "TimeoutException",
    "ConnectTimeout",
    "ReadTimeout",
    "WriteTimeout",
    "PoolTimeout",
    "ConnectError",
    "ReadError",
    "WriteError",
    "RemoteProtocolError",
    "LocalProtocolError",
    "ValidationError",
    "UnexpectedModelBehavior",
    "UsageLimitExceeded",
}
_QUEUE = "events queue full (max=%d); dropped %d event(s) so far"
_DROPPED = "events flush dropped %d of %d row(s) for table %r after per-row retry"
_LOST_USAGE = "log_llm_usage failed; row dropped"
_PLATFORM = "ai_budget: platform spend today is %s USD, at or above %s of the %s USD daily budget"
_TABLES = frozenset({"events", "llm_usage"})
_NUMBER = re.compile(r"[0-9]+(?:\.[0-9]+)?\Z")


def _count(value):
    return type(value) is int and 0 < value < 2**63


def _amount(value):
    if type(value) not in (Decimal, int, float, str):
        return None
    if type(value) is str and (len(value) > 80 or not _NUMBER.fullmatch(value)):
        return None
    try:
        amount = Decimal(str(value))
        if (
            not amount.is_finite()
            or amount < 0
            or amount.adjusted() > 15
            or amount.as_tuple().exponent < -12
        ):
            return None
        return format(amount, "f")
    except (InvalidOperation, ValueError):
        return None


def _signal(record):
    if (
        type(record.levelno) is not int
        or type(record.name) is not str
        or type(record.msg) is not str
        or type(record.args) is not tuple
    ):
        return None
    args = record.args
    stage = _RECORDS.get((record.name, record.msg))
    if stage is not None and record.levelno == logging.WARNING and len(args) == 1:
        error_type = args[0] if type(args[0]) is str and args[0] in _ERROR_TYPES else "OtherError"
        return "Sapling usage accounting hook failed", {
            "sapling.signal": "accounting_hook_failed",
            "sapling.stage": stage,
            "error.type": error_type,
        }
    if record.name == "sapling.events":
        if record.levelno == logging.ERROR and record.msg == _LOST_USAGE and not args:
            return "Sapling operational accounting signal", {
                "sapling.signal": "usage_row_dropped",
                "sapling.stage": "llm_usage_build",
            }
        if record.levelno != logging.WARNING:
            return None
        if record.msg == _QUEUE and len(args) == 2 and all(_count(v) for v in args):
            return "Sapling operational accounting signal", {
                "sapling.signal": "events_queue_full",
                "sapling.stage": "queue_admission",
                "queue_capacity": args[0],
                "dropped_count": args[1],
            }
        if (
            record.msg == _DROPPED
            and len(args) == 3
            and _count(args[0])
            and _count(args[1])
            and args[0] <= args[1]
            and type(args[2]) is str
            and args[2] in _TABLES
        ):
            return "Sapling operational accounting signal", {
                "sapling.signal": "events_flush_dropped",
                "sapling.stage": "queue_delivery",
                "dropped_count": args[0],
                "batch_count": args[1],
                "table_name": args[2],
            }
    if (
        record.name == "sapling.ai_budget"
        and record.levelno == logging.WARNING
        and record.msg == _PLATFORM
        and len(args) == 3
    ):
        values = [_amount(v) for v in args]
        if all(v is not None for v in values):
            return "Sapling operational accounting signal", {
                "sapling.signal": "platform_spend_alert",
                "sapling.stage": "platform_daily_spend",
                "spent_usd": values[0],
                "alert_fraction": values[1],
                "budget_usd": values[2],
            }
    return None


class AccountingLogfireHandler(logging.Handler):
    """Fixed events/finite metadata only, with no formatted message or exception."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            signal = _signal(record)
            if signal is None:
                return
            message, attributes = signal
            logfire.log(
                "error" if record.levelno == logging.ERROR else "warn",
                message,
                attributes={**attributes, "logger.name": record.name},
                exc_info=False,
            )
        except Exception:
            # Do not recursively log through this handler or change the caller.
            # The ordinary stderr handler still receives the original record.
            return


def install_accounting_logfire_bridge() -> None:
    """Idempotent per known logger; never attach a broad handler to root."""
    for name in _LOGGER_NAMES:
        logger = logging.getLogger(name)
        if not any(isinstance(h, AccountingLogfireHandler) for h in logger.handlers):
            logger.addHandler(AccountingLogfireHandler(level=logging.WARNING))
