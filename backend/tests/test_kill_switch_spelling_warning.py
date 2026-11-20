"""PKG-14 review fix round: an unrecognised LEARNING_LOOP_ENABLED value keeps the
§7 parse (unset/empty/anything not false/0/off/no means ON) but logs a WARNING."""

import importlib
import logging

import pytest

import config


@pytest.fixture
def reload_config(monkeypatch):
    def _reload(value):
        if value is None:
            monkeypatch.delenv("LEARNING_LOOP_ENABLED", raising=False)
        else:
            monkeypatch.setenv("LEARNING_LOOP_ENABLED", value)
        return importlib.reload(config)

    yield _reload
    monkeypatch.delenv("LEARNING_LOOP_ENABLED", raising=False)
    importlib.reload(config)


@pytest.mark.parametrize("value", ["disabled", "n", "enable", "flase"])
def test_unknown_spelling_is_on_and_warns(reload_config, caplog, value):
    with caplog.at_level(logging.WARNING, logger="config"):
        cfg = reload_config(value)
    assert cfg.LEARNING_LOOP_ENABLED is True
    assert any("not a recognised spelling" in r.getMessage() for r in caplog.records)


@pytest.mark.parametrize(
    "value,expected",
    [(None, True), ("", True), ("true", True), (" On ", True), ("YES", True), ("1", True),
     ("false", False), (" OFF ", False), ("No", False), ("0", False)],
)
def test_known_spellings_do_not_warn(reload_config, caplog, value, expected):
    with caplog.at_level(logging.WARNING, logger="config"):
        cfg = reload_config(value)
    assert cfg.LEARNING_LOOP_ENABLED is expected
    assert not any("not a recognised spelling" in r.getMessage() for r in caplog.records)
