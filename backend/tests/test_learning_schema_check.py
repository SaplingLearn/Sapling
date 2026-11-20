"""Learning-loop spec §13 A138 review (item 1): the boot-time wave-4 schema
check. Warn only — it names what is missing and never blocks boot."""

from __future__ import annotations

import inspect
import logging
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import httpx


class _PgError(Exception):
    def __init__(self, code):
        super().__init__("Client error")
        self.response = SimpleNamespace(json=lambda: {"code": code})


def _tables(errors: dict):
    def table(name):
        t = MagicMock()
        if name in errors:
            t.select.side_effect = errors[name]
        else:
            t.select.return_value = []
        return t

    return table


def test_a_complete_schema_reports_nothing(caplog):
    from services import learning_schema_check as check

    with patch.object(check, "table", side_effect=_tables({})), caplog.at_level(logging.WARNING):
        assert check.check_learning_schema() == []
    assert not caplog.records


def test_a_missing_table_or_column_is_one_error_and_never_blocks_boot(caplog):
    from services import learning_schema_check as check

    errors = {"learning_prequestions": _PgError("PGRST205"), "node_mastery_events": _PgError("42703")}
    with patch.object(check, "table", side_effect=_tables(errors)), caplog.at_level(logging.WARNING):
        missing = check.check_learning_schema()
    assert missing == ["learning_prequestions", "node_mastery_events(id,multi_concept)"]
    (record,) = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert "learning_prequestions" in record.getMessage() and "db.migrate" in record.getMessage()


def test_an_unreachable_database_is_a_warning_and_no_claim(caplog):
    from services import learning_schema_check as check

    down = {"learning_prequestions": httpx.ConnectError("refused")}
    with patch.object(check, "table", side_effect=_tables(down)), caplog.at_level(logging.WARNING):
        assert check.check_learning_schema() == []
    assert [r.levelno for r in caplog.records] == [logging.WARNING]


def test_the_lifespan_runs_it_after_the_key_canary():
    import main

    source = inspect.getsource(main._lifespan)
    assert source.index("verify_encryption_key()") < source.index("check_learning_schema()")
