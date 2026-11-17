"""sec2 M11(c): a flag-store outage must not silently switch off the crisis card.

`crisis_support` reads its flag with `feature_flags.last_known_flag_on`: while
the store is unreadable it answers from the last snapshot the process read,
instead of failing closed. It never turns on a flag the last good read had
off, and a process that never read the store answers off, so the default
(off, pending the owner's copy review) is unchanged.
"""

from __future__ import annotations

from unittest.mock import patch

from services import crisis_support
from services import feature_flags as ff
from tests.test_feature_flags import _tables

KEY = "crisis_support"


def _row(default: str) -> dict:
    return {"key": KEY, "default_variant": default, "rollout_percent": 0,
            "rollout_variant": None, "updated_at": None, "updated_by": None}


def _read_then_expire(default: str) -> None:
    with patch("services.feature_flags.table", side_effect=_tables(flags=[_row(default)])):
        assert ff.flag_on(KEY, "u1") is (default == "on")
    stamp, snap = ff._snapshot
    ff._snapshot = (stamp - 10_000.0, snap)  # well past the TTL


def test_the_default_is_still_off():
    assert ff.REGISTRY[KEY].variants[0] == "off"
    with patch("services.feature_flags.table", side_effect=_tables()):
        assert ff.last_known_flag_on(KEY, "u1") is False  # no stored config


def test_an_outage_keeps_an_on_flag_on():
    _read_then_expire("on")
    with patch("services.feature_flags.table", side_effect=_tables(fail=True)):
        assert ff.flag_on(KEY, "u1") is False  # the plain read fails closed
        assert ff.last_known_flag_on(KEY, "u1") is True


def test_an_outage_never_turns_an_off_flag_on():
    _read_then_expire("off")
    with patch("services.feature_flags.table", side_effect=_tables(fail=True)):
        assert ff.last_known_flag_on(KEY, "u1") is False


def test_a_process_that_never_read_the_store_answers_off():
    ff.clear_feature_flags_cache()
    ff._snapshot = None
    with patch("services.feature_flags.table", side_effect=_tables(fail=True)):
        assert ff.last_known_flag_on(KEY, "u1") is False


def test_a_readable_store_answers_as_flag_on_does():
    with patch("services.feature_flags.table", side_effect=_tables(flags=[_row("on")])):
        assert ff.last_known_flag_on(KEY, "u1") is True
    ff.clear_feature_flags_cache()
    with patch("services.feature_flags.table", side_effect=_tables(flags=[_row("off")])):
        assert ff.last_known_flag_on(KEY, "u1") is False
    assert ff.last_known_flag_on("no_such_flag", "u1") is False


def test_crisis_support_reads_its_flag_this_way():
    assert crisis_support.flag_on is ff.last_known_flag_on
