"""PR #866 Z33: the alignment check (spec §13 A119) and the quiz's concept
check (A145) read a concept name that begins or ends with a quote mark, or
ends with a full stop, as that concept.

The verifier's answer was compared after its surrounding quotes and closing
full stop were stripped, while the item's own key (graph_service's normalizer)
keeps them, so a verifier that copied such a name verbatim named a concept
"outside the course's list": every draft of the concept was rejected
OUT_OF_SCOPE (and counted against it until the A41 ledger stalled it), and
the alignment backfill retired every stored item of it."""

from __future__ import annotations

import pytest

from learning import quiz_gates
from learning.item_alignment import (
    CONCEPT_RETAGGED,
    NO_CONCEPT,
    OUT_OF_SCOPE,
    Verdict,
    align,
    concept_key,
    names_concept,
)

NAMES = ["'this' keyword", '"Hello, World!" program', "Pointers vs. references."]


@pytest.mark.parametrize("name", NAMES)
def test_the_items_own_concept_named_verbatim_keeps_the_item(name):
    own = concept_key(name)
    out = align(2, own, Verdict({"c1": True, "c2": True}, name), {own: name})
    assert (out.reject, out.concept_key, out.flags) == (None, own, ())


@pytest.mark.parametrize("name", NAMES)
def test_a_listed_concept_named_verbatim_is_a_retag(name):
    target = concept_key(name)
    scope = {"recursion": "Recursion", target: name}
    out = align(1, "recursion", Verdict({"c1": True}, name), scope)
    assert (out.reject, out.concept_key) == (None, target)
    assert CONCEPT_RETAGGED in out.flags


def test_the_forgiving_spelling_still_names_a_concept_either_way():
    # the verifier quotes a plain name and closes it with a full stop
    out = align(1, "merge sort", Verdict({"c1": True}, '"Merge sort."'), {"merge sort": "Merge sort"})
    assert (out.reject, out.concept_key) == (None, "merge sort")
    # ...or drops the closing full stop a name has of its own
    own = concept_key("Pointers vs. references.")
    out = align(1, own, Verdict({"c1": True}, "Pointers vs. references"), {own: "x"})
    assert (out.reject, out.concept_key) == (None, own)
    assert names_concept("'this' keyword", concept_key("'this' keyword"))
    assert not names_concept("this keyword", concept_key("'this' keyword"))


def test_an_unlisted_concept_and_none_are_still_rejected():
    scope = {"recursion": "Recursion"}
    assert align(1, "recursion", Verdict({"c1": True}, "'this' keyword"), scope).reject == OUT_OF_SCOPE
    assert align(1, "recursion", Verdict({"c1": True}, "none."), scope).reject == NO_CONCEPT


@pytest.mark.parametrize("name", NAMES)
def test_the_quiz_concept_check_reads_such_a_name_as_its_concept(name):
    assert quiz_gates.alignment_of(name, name) == quiz_gates.ALIGNED
    assert quiz_gates.alignment_of("Recursion", name) == quiz_gates.MISALIGNED
    assert quiz_gates.alignment_of("none", name) == quiz_gates.MISALIGNED
