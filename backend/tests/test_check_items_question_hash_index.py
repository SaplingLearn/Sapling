"""PR #866 Z36: the reads of check_items by question_hash alone have an index.

`items_by_hash` (the served-text scan set, posed_items: every loop turn and
every guarded notes/flashcards request with an open pose) and `item_rows_for`
filter check_items on `question_hash IN (...)` with no course. An index whose
leading column is anything else cannot serve that filter, so without one led
by question_hash each such read scans every course's bank."""

from __future__ import annotations

from db.migration_units import MIGRATION_UNITS
import re
from unittest.mock import MagicMock, patch

MIGRATIONS = MIGRATION_UNITS

_INDEX = re.compile(
    r"CREATE\s+(?:UNIQUE\s+)?INDEX\s+(?:CONCURRENTLY\s+)?(?:IF\s+NOT\s+EXISTS\s+)?(\w+)\s+"
    r"ON\s+(?:public\.)?check_items\s*(?:USING\s+\w+\s*)?\(\s*(\w+)",
    re.I,
)


def _check_items_indexes() -> dict[str, str]:
    """index name -> its leading column, over every migration."""
    out: dict[str, str] = {}
    for path in sorted(MIGRATIONS.glob("*.sql")):
        for name, first in _INDEX.findall(path.read_text()):
            out[name] = first
    return out


def test_an_index_leads_with_question_hash():
    leading = _check_items_indexes()
    assert "question_hash" in leading.values(), leading


def test_the_migration_is_idempotent_and_bounds_its_lock_wait():
    (path,) = MIGRATIONS.glob("*_learning_check_items_question_hash.sql")
    sql = path.read_text()
    assert re.search(r"CREATE INDEX IF NOT EXISTS check_items_question_hash_idx", sql)
    assert "SET LOCAL lock_timeout" in sql


def test_the_hash_reads_filter_on_question_hash_alone():
    """What the index is for: items_by_hash names no course."""
    from services import check_item_service as svc

    handle = MagicMock()
    handle.select.return_value = []
    with patch.object(svc, "table", return_value=handle):
        svc.items_by_hash(["h1", "h2"])
    filters = handle.select.call_args.kwargs["filters"]
    assert list(filters) == ["question_hash"]
