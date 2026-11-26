"""REGISTRY declares each flag key once (D2).

`crisis_support` was declared twice; the old dict comprehension kept the
second copy, whose description named fewer surfaces than the first, and no
test noticed. Construction now raises on a repeated key, and this file pins
both that and the source itself (an AST read, so a duplicate fails here even
if someone swaps the constructor back)."""

from __future__ import annotations

import ast
from collections import Counter
from pathlib import Path

import pytest

from services import feature_flags
from services.feature_flags import FlagDef, _registry

_SOURCE = Path(feature_flags.__file__)


def test_registry_construction_raises_on_a_repeated_key():
    one = FlagDef("dup_probe", ("off", "on"), "first", False)
    two = FlagDef("dup_probe", ("off", "on"), "second", False)
    with pytest.raises(ValueError, match="dup_probe"):
        _registry(one, two)


def test_registry_construction_keeps_every_distinct_key():
    defs = [FlagDef(f"k{i}", ("off", "on"), "d", False) for i in range(3)]
    assert list(_registry(*defs)) == ["k0", "k1", "k2"]


def test_no_flag_key_is_declared_twice_in_the_source():
    tree = ast.parse(_SOURCE.read_text())
    keys = [
        node.args[0].value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and getattr(node.func, "id", None) == "FlagDef"
        and node.args
        and isinstance(node.args[0], ast.Constant)
    ]
    assert keys, "no literal FlagDef keys found: the parse is broken"
    dupes = sorted(k for k, n in Counter(keys).items() if n > 1)
    assert dupes == []


def test_crisis_support_names_every_surface_family():
    text = feature_flags.REGISTRY["crisis_support"].description
    for surface in ("tutor", "learning-loop", "notes", "flashcard"):
        assert surface in text, surface
