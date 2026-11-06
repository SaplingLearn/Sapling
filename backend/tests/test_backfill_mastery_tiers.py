"""scripts/backfill_mastery_tiers.py — recomputes stale stored tiers (#766)."""
import importlib
import sys
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def mod(monkeypatch):
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: False)
    sys.modules.pop("scripts.backfill_mastery_tiers", None)
    module = importlib.import_module("scripts.backfill_mastery_tiers")
    yield module
    sys.modules.pop("scripts.backfill_mastery_tiers", None)


ROWS = [
    {"id": "ok", "mastery_score": 0.8, "mastery_tier": "mastered"},
    {"id": "stale", "mastery_score": 0.8, "mastery_tier": "learning"},
    {"id": "root", "mastery_score": 0.0, "mastery_tier": "subject_root"},
]


def _run(mod, monkeypatch, argv):
    tbl = MagicMock()
    monkeypatch.setattr(mod, "table", lambda name: tbl)
    monkeypatch.setattr(mod, "page_all", lambda *a, **k: iter([dict(r) for r in ROWS]))
    return mod.main(argv), tbl


def test_only_stale_rows_are_reported(mod):
    assert [(r["id"], want) for r, want in mod.stale_rows(ROWS)] == [
        ("stale", "mastered"), ("root", "unexplored"),
    ]


def test_dry_run_is_the_default_and_writes_nothing(mod, monkeypatch):
    summary, tbl = _run(mod, monkeypatch, [])
    assert summary == {"learning->mastered": 1, "subject_root->unexplored": 1}
    tbl.update.assert_not_called()


def test_apply_writes_conditionally_on_the_score_it_read(mod, monkeypatch):
    _, tbl = _run(mod, monkeypatch, ["--apply"])
    assert tbl.update.call_count == 2
    first = tbl.update.call_args_list[0]
    assert first.args[0] == {"mastery_tier": "mastered"}
    # A mastery write between the read and this write wins: it recomputed
    # the tier itself, and this one no longer matches its score.
    assert first.kwargs["filters"] == {"id": "eq.stale", "mastery_score": "eq.0.8"}
