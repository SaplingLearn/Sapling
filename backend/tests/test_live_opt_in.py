"""A plain `pytest tests/` never makes a billable model call.

tests/conftest.py's `pytest_collection_modifyitems` skips every `live_llm`
test that may call a model unless a RUN_LIVE_<LANE>=1 opt-in is set. These
tests pin the rule (tests/live_opt_in.py) and check it held for the items this
session collected.
"""
import os

import pytest

from tests.live_opt_in import billable, live_opt_in


@pytest.mark.parametrize(
    ("environ", "expected"),
    [
        ({}, False),
        # A key is not consent: config.py loads backend/.env into the environment.
        ({"GEMINI_API_KEY": "a-real-looking-key", "ANTHROPIC_API_KEY": "sk-ant-x"}, False),
        ({"RUN_LIVE_OCR": "1"}, True),
        ({"RUN_LIVE_OCR_PIPELINE": "1"}, True),
        ({"RUN_LIVE_OCR": "0"}, False),
        ({"RUN_LIVE_OCR": "true"}, False),
        # The other opt-in lanes talk to a database, not a model.
        ({"RUN_INTEGRATION": "1", "RUN_STAGING_E2E": "1"}, False),
    ],
)
def test_only_a_named_live_lane_opts_in(environ, expected):
    assert live_opt_in(environ) is expected


def test_an_offline_live_marker_is_not_billable():
    assert billable(pytest.mark.live_llm.mark) is True
    assert billable(pytest.mark.live_llm(offline=True).mark) is False
    assert billable(None) is False


def test_every_billable_live_test_collected_here_is_skipped(request):
    if live_opt_in(os.environ):
        pytest.skip("a RUN_LIVE_<LANE>=1 lane is opted in for this run")
    unskipped = [
        item.nodeid
        for item in request.session.items
        if billable(item.get_closest_marker("live_llm"))
        and not any(mark.name == "skip" for mark in item.iter_markers())
    ]
    assert unskipped == []


def test_the_ocr_pipeline_live_tests_need_their_own_opt_in():
    """The one live file that used to run on a key alone (GEMINI_API_KEY)."""
    import tests.test_ocr_pipeline as ocr

    for name in ("test_agent_parse", "test_save_to_db", "test_full_pipeline"):
        func = getattr(ocr, name, None)
        if func is None:
            continue
        marks = {mark.name: mark for mark in getattr(func, "pytestmark", [])}
        assert "live_llm" in marks, name
        skipif = marks.get("skipif")
        assert skipif is not None, name
        assert "RUN_LIVE_OCR_PIPELINE" in skipif.kwargs.get("reason", ""), name
