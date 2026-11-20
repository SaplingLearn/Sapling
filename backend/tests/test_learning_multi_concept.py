"""Multi-concept items: identity, combinations, the gate and the session dial
(learning-loop spec §13 A141; learning/multi_concept.py)."""

from __future__ import annotations

import pytest

from learning import params
from learning.multi_concept import (
    SEP,
    STEP_KEY,
    ComponentState,
    combinations,
    combo_key,
    components_of,
    dial_open,
    evidence_key,
    gate_open,
    graded_on,
    is_multi_concept,
    label,
    posed_on,
)
from services.graph_service import _normalize_concept


def test_the_key_puts_the_apex_first_and_sorts_the_prerequisites():
    assert combo_key(["load factor", "hash table", "array"]) == SEP.join(
        ["load factor", "array", "hash table"]
    )
    assert components_of(combo_key(["b", "a"])) == ("b", "a")


@pytest.mark.parametrize(
    "bad",
    [["only"], ["a", "b", "c", "d"], ["a", "a"], ["a", ""], ["a", f"b{SEP}c"]],
)
def test_a_combination_is_two_or_three_distinct_keys(bad):
    with pytest.raises(ValueError):
        combo_key(bad)


def test_no_concept_key_is_ever_a_combination_key():
    """graph_service._normalize_concept collapses the separator as whitespace,
    so no per-concept read can meet a multi-concept item."""
    assert SEP not in _normalize_concept(f"Load{SEP}Factor")
    assert components_of(_normalize_concept(f"Load{SEP}Factor")) is None
    assert components_of("load factor") is None
    assert components_of(None) is None
    assert components_of(f"a{SEP}") is None and components_of(f"a{SEP}a") is None


def test_an_items_evidence_goes_to_its_apex():
    class Item:
        concept_key = combo_key(["load factor", "hash table"])

    class Single:
        concept_key = "load factor"

    assert is_multi_concept(Item()) and not is_multi_concept(Single())
    assert evidence_key(Item()) == "load factor"
    assert evidence_key(Single()) == "load factor"


def test_the_label_joins_the_names():
    assert label(["Load  Factor", "Hash Table"]) == "Load Factor + Hash Table"


def test_combinations_take_pairs_before_triples_per_apex_and_cap():
    parents = {"d": ["b", "a", "c"], "e": ["a"], "a": []}
    combos = combinations(["d", "e", "a"], parents, per_apex=3, limit=6)
    # d: its pairs in key order first, then one triple; e: its one pair; a: none
    assert combos == [("d", "a"), ("d", "b"), ("d", "c"), ("e", "a")]
    assert combinations(["d"], {"d": ["a", "b"]}, per_apex=3, limit=6) == [
        ("d", "a"),
        ("d", "b"),
        ("d", "a", "b"),
    ]
    assert combinations(["d", "e"], parents, per_apex=3, limit=2) == [("d", "a"), ("d", "b")]
    # an apex is never its own parent; a repeat counts once
    assert combinations(["d", "d"], {"d": ["d", "a"]}) == [("d", "a")]
    assert len(combinations(["d"], {"d": list("abcdefgh")})) == params.MULTI_CONCEPT_COMBOS_PER_APEX


def test_the_gate_wants_every_component_proficient_and_confirmed():
    ok = ComponentState(params.MULTI_CONCEPT_GATE_P, params.MULTI_CONCEPT_GATE_MIN_STRONG)
    assert gate_open({"a": ok, "b": ok}, ["a", "b"])
    low = ComponentState(params.MULTI_CONCEPT_GATE_P - 1e-9, 5)
    unconfirmed = ComponentState(0.99, params.MULTI_CONCEPT_GATE_MIN_STRONG - 1)
    assert not gate_open({"a": ok, "b": low}, ["a", "b"])
    assert not gate_open({"a": ok, "b": unconfirmed}, ["a", "b"])
    assert not gate_open({"a": ok}, ["a", "b"])  # no state: not proficient
    assert not gate_open({"a": ok, "b": None}, ["a", "b"])


def test_the_gate_is_the_proficient_cut_not_the_profic_band():
    """At the profic band's floor the conjunctive success expectation of two
    components falls below the practice band; at BKT_PROFICIENT it does not."""
    g, s = params.CHANNELS["free_response"]["G"], params.CHANNELS["free_response"]["S"]

    def expected(p, k):
        both = p**k
        return both * (1 - s) + (1 - both) * g

    assert params.MULTI_CONCEPT_GATE_P == params.BKT_PROFICIENT
    for k in (2, 3):
        assert expected(params.MULTI_CONCEPT_GATE_P, k) >= params.PRACTICE_TARGET_LO
        assert expected(params.BAND_DEVELOP_MAX, k) < params.PRACTICE_TARGET_LO


def test_the_dial_opens_after_a_graded_check_at_the_top_once_a_session():
    steps = {"q1": {"node_id": "n", "graded_at": 1.0}}
    assert dial_open(steps, "n", at_top=True, goal=False)
    assert not dial_open(steps, "n", at_top=False, goal=False)  # an easier step pending
    assert not dial_open(steps, "n", at_top=True, goal=True)  # goal sessions: never
    assert not dial_open({}, "n", at_top=True, goal=False)  # nothing graded on it yet
    assert not dial_open({"q1": {"node_id": "m", "graded_at": 1.0}}, "n", at_top=True, goal=False)
    posed = {**steps, "q2": {"node_id": "n", STEP_KEY: True}}
    assert posed_on(posed, "n") == 1 and graded_on(posed, "n") == 1
    assert not dial_open(posed, "n", at_top=True, goal=False)  # once a session
