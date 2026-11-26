"""PKG-14 review fix round (A92): a legacy turn records llm_usage.session_id only
for the caller's own session, so cost cannot be moved onto another student's
session in the per-session report."""

from unittest.mock import MagicMock

import pytest

from routes import learn
from tests.split_patches import patch_tutor


def _sessions(rows):
    t = MagicMock()
    t.select.return_value = rows
    return MagicMock(return_value=t)


@pytest.fixture(autouse=True)
def _no_pending():
    saved = dict(learn.PENDING_SESSIONS)
    learn.PENDING_SESSIONS.clear()
    yield
    learn.PENDING_SESSIONS.clear()
    learn.PENDING_SESSIONS.update(saved)


def test_own_session_is_recorded():
    with patch_tutor("table", _sessions([{"user_id": "u-a"}])):
        assert learn._usage_session_id("s-1", "u-a") == "s-1"


def test_someone_elses_session_records_null():
    with patch_tutor("table", _sessions([{"user_id": "u-b"}])):
        assert learn._usage_session_id("s-1", "u-a") is None


def test_missing_session_records_null():
    with patch_tutor("table", _sessions([])):
        assert learn._usage_session_id("s-404", "u-a") is None


def test_no_session_id_records_null_without_a_read():
    tbl = _sessions([{"user_id": "u-a"}])
    with patch_tutor("table", tbl):
        assert learn._usage_session_id(None, "u-a") is None
        assert learn._usage_session_id("", "u-a") is None
    tbl.assert_not_called()


def test_pending_session_counts_only_for_its_user_without_a_read():
    learn.PENDING_SESSIONS["s-p"] = {"user_id": "u-a"}
    tbl = _sessions([])
    with patch_tutor("table", tbl):
        assert learn._usage_session_id("s-p", "u-a") == "s-p"
        assert learn._usage_session_id("s-p", "u-b") is None
    tbl.assert_not_called()


def test_a_failed_read_records_null_and_never_raises():
    t = MagicMock()
    t.select.side_effect = RuntimeError("db down")
    with patch_tutor("table", MagicMock(return_value=t)):
        assert learn._usage_session_id("s-1", "u-a") is None


def test_a_continuation_records_against_the_turns_resolved_session_without_a_second_read(monkeypatch):
    """A textless turn's continuation reuses the id the turn already resolved:
    no second ownership read, and the same llm_usage.session_id."""
    import asyncio
    from contextlib import nullcontext
    from unittest.mock import AsyncMock

    from services.tutor import run

    def no_read(*_a, **_k):
        raise AssertionError("the continuation re-read session ownership")

    recorded = {}
    monkeypatch.setattr(run, "_usage_session_id", no_read)
    monkeypatch.setattr(run, "record_agent_usage", lambda result, **kw: recorded.update(kw) or result)
    monkeypatch.setattr(run, "_new_run_text", lambda result: "rescued")
    agent = MagicMock()
    agent.override.return_value = nullcontext()
    agent.run = AsyncMock(return_value=MagicMock())
    first = MagicMock()
    first.all_messages.return_value = []
    deps = MagicMock(session_id="s-1", user_id="u-a")

    out = asyncio.run(run._continuation_text(
        agent, first, {"deps": deps}, request_id="r-1", usage_session_id="s-1",
    ))
    assert out == "rescued"
    assert recorded["session_id"] == "s-1" and recorded["request_id"] == "r-1"
