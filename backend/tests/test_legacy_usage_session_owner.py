"""PKG-14 review fix round (A92): a legacy turn records llm_usage.session_id only
for the caller's own session, so cost cannot be moved onto another student's
session in the per-session report."""

from unittest.mock import MagicMock, patch

import pytest

from routes import learn


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
    with patch("routes.learn.table", _sessions([{"user_id": "u-a"}])):
        assert learn._usage_session_id("s-1", "u-a") == "s-1"


def test_someone_elses_session_records_null():
    with patch("routes.learn.table", _sessions([{"user_id": "u-b"}])):
        assert learn._usage_session_id("s-1", "u-a") is None


def test_missing_session_records_null():
    with patch("routes.learn.table", _sessions([])):
        assert learn._usage_session_id("s-404", "u-a") is None


def test_no_session_id_records_null_without_a_read():
    tbl = _sessions([{"user_id": "u-a"}])
    with patch("routes.learn.table", tbl):
        assert learn._usage_session_id(None, "u-a") is None
        assert learn._usage_session_id("", "u-a") is None
    tbl.assert_not_called()


def test_pending_session_counts_only_for_its_user_without_a_read():
    learn.PENDING_SESSIONS["s-p"] = {"user_id": "u-a"}
    tbl = _sessions([])
    with patch("routes.learn.table", tbl):
        assert learn._usage_session_id("s-p", "u-a") == "s-p"
        assert learn._usage_session_id("s-p", "u-b") is None
    tbl.assert_not_called()


def test_a_failed_read_records_null_and_never_raises():
    t = MagicMock()
    t.select.side_effect = RuntimeError("db down")
    with patch("routes.learn.table", MagicMock(return_value=t)):
        assert learn._usage_session_id("s-1", "u-a") is None


def test_every_body_sourced_legacy_usage_site_goes_through_the_owner_check():
    import inspect

    src = inspect.getsource(learn)
    # /chat (JSON via _chat_via_agent), /chat/stream, /action and the continuation run
    assert src.count("session_id=_usage_session_id(") == 4
