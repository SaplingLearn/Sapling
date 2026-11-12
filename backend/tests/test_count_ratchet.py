"""scripts/_count_ratchet.py: the rule behind type_ratchet.py and lint_ratchet.py.

The two scripts gate CI, so a refactor that quietly turned the comparison into
a no-op would let every new type error and blind ``except`` through. These pin
the rule on synthetic counts (no pyright or ruff run needed).
"""

import json
from collections import Counter

import pytest

from scripts import _count_ratchet as ratchet


@pytest.fixture
def baseline(tmp_path):
    path = tmp_path / "baseline.json"
    path.write_text(json.dumps({"a.py::BLE001": 2, "b.py::B904": 1}))
    return path


def _run(path, counts, *, shrink=False):
    return ratchet.run(
        "ratchet", path, Counter(counts), lambda key: [f"{key} detail"],
        shrink=shrink, what="violations",
    )


def test_matching_counts_pass(baseline):
    assert _run(baseline, {"a.py::BLE001": 2, "b.py::B904": 1}) == 0


def test_one_more_in_a_baselined_file_fails(baseline, capsys):
    """The case a per-file ignore cannot catch: the file already has some."""
    assert _run(baseline, {"a.py::BLE001": 3, "b.py::B904": 1}) == 1
    out = capsys.readouterr().out
    assert "a.py::BLE001: 3 (baseline 2)" in out
    assert "a.py::BLE001 detail" in out


def test_a_key_that_is_not_listed_fails(baseline):
    assert _run(baseline, {"a.py::BLE001": 2, "b.py::B904": 1, "new.py::BLE001": 1}) == 1
    assert _run(baseline, {"a.py::BLE001": 2, "b.py::B904": 1, "a.py::B904": 1}) == 1


def test_a_lower_count_only_warns(baseline, capsys):
    assert _run(baseline, {"a.py::BLE001": 1}) == 0
    out = capsys.readouterr().out
    assert "a.py::BLE001 is down to 1 (baseline 2)" in out
    assert "b.py::B904 is down to 0 (baseline 1)" in out
    assert json.loads(baseline.read_text()) == {"a.py::BLE001": 2, "b.py::B904": 1}


def test_shrink_lowers_and_drops_entries(baseline):
    assert _run(baseline, {"a.py::BLE001": 1}, shrink=True) == 0
    assert json.loads(baseline.read_text()) == {"a.py::BLE001": 1}


def test_shrink_never_raises_an_entry(baseline):
    before = baseline.read_text()
    assert _run(baseline, {"a.py::BLE001": 3}, shrink=True) == 1
    assert baseline.read_text() == before


def test_shrink_writes_the_first_baseline(tmp_path):
    path = tmp_path / "baseline.json"
    assert _run(path, {"b.py::B904": 1, "a.py::BLE001": 2}, shrink=True) == 0
    assert list(json.loads(path.read_text()).items()) == [("a.py::BLE001", 2), ("b.py::B904", 1)]
