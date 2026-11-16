"""Shared fakes for the async DB seam (#117; docs/design/async-db-client.md §4.3).

* :func:`fake_table` -- a ``MagicMock(spec=SupabaseTable)`` whose ``a*`` twins
  delegate to their sync siblings, so existing setups
  (``m.select.return_value = [...]``) and assertions on ``.select`` keep
  working for a router converted to ``await table(...).aselect(...)``.
* :func:`with_async_twins` -- the same, for a test's existing ``factory(name)``
  that builds bare ``MagicMock`` handles (``patch("routes.x.table",
  side_effect=with_async_twins(factory))``).

The ``no_sync_db_on_loop`` fixture (tests/conftest.py) turns the runtime
``db.sync_on_loop`` warning into a raise; a converted router's test module
opts in, so a sync PostgREST call creeping back onto the loop fails CI.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from db.connection import SupabaseTable

#: (async twin, sync sibling) on the table handle.
TWINS = (
    ("aselect", "select"),
    ("aselect_with_count", "select_with_count"),
    ("ainsert", "insert"),
    ("aupdate", "update"),
    ("aupsert", "upsert"),
    ("adelete", "delete"),
)


def add_async_twins(mock):
    """Point each ``a*`` method of ``mock`` at its sync sibling. Returns it."""
    for twin, sync in TWINS:
        setattr(mock, twin, AsyncMock(
            side_effect=lambda *a, _s=sync, **k: getattr(mock, _s)(*a, **k)))
    return mock


def fake_table() -> MagicMock:
    return add_async_twins(MagicMock(spec=SupabaseTable))


def with_async_twins(factory):
    """Wrap a ``factory(name) -> MagicMock`` so every handle it returns also
    answers the ``a*`` twins (one wrapped handle per call, as before)."""
    def _wrapped(*args, **kwargs):
        return add_async_twins(factory(*args, **kwargs))
    return _wrapped
