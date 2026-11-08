"""Surface-varied isomorphs: the descriptor and the cue-familiarity dial
(learning-loop spec §13 A140; learning/surface.py)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from learning import params
from learning.checks import CheckItemDraft
from learning.surface import (
    Surface,
    SurfacedCheckItemDraft,
    VariedCheckItemDraft,
    VariedCheckItemsOutput,
    clip_context,
    familiarity,
    familiarity_by_hash,
    from_varied,
    surface,
    surface_of,
)


def _varied(**over) -> dict:
    base = {
        "concept": "Load Factor",
        "format": "free",
        "difficulty": 2,
        "surface_representation": "applied",
        "surface_context": "Library checkout queue",
        "prompt": "A table holds 4 entries in 5 buckets. What is its load factor?",
        "reference_answer": "Entries over buckets: 4/5. Final answer: 0.8.",
        "final_answer": "0.8",
        "rubric": ["Divides entries by buckets.", "States 0.8."],
        "wrong_keys": ["buckets_over_entries"],
        "wrong_texts": ["Divides buckets by entries."],
        "canonical_answer": "0.8",
        "tolerance": "",
        "chunk_ids": [],
    }
    base.update(over)
    return base


def test_the_varied_draft_is_the_plain_draft_without_answer_kind_and_stepwise():
    plain = set(CheckItemDraft.model_fields)
    varied = set(VariedCheckItemDraft.model_fields)
    assert plain - varied == {"answer_kind", "stepwise"}
    assert varied - plain == {"surface_representation", "surface_context"}
    # every shared field keeps the plain drafter's own description
    for name in plain & varied:
        assert (
            VariedCheckItemDraft.model_fields[name].description
            == CheckItemDraft.model_fields[name].description
        ), name


def test_the_surface_comes_right_after_the_difficulty_so_it_steers_the_question():
    order = list(
        VariedCheckItemsOutput.model_json_schema()["$defs"]["VariedCheckItemDraft"]["properties"]
    )
    i = order.index("difficulty")
    assert order[i + 1 : i + 3] == ["surface_representation", "surface_context"]
    assert order.index("prompt") > i + 2


def test_the_representation_is_the_closed_enum_of_params():
    schema = VariedCheckItemsOutput.model_json_schema()["$defs"]["VariedCheckItemDraft"]
    assert (
        tuple(schema["properties"]["surface_representation"]["enum"])
        == params.SURFACE_REPRESENTATIONS
    )
    with pytest.raises(ValidationError):
        VariedCheckItemDraft.model_validate(_varied(surface_representation="cartoon"))


def test_the_varied_output_fits_the_schema_budget_exactly_as_the_plain_one():
    """#153: the plain check_items output is exactly 20 properties (root 1,
    draft 15, option 4); the varied one trades two derived fields for two
    surface fields, so it is too."""
    schema = VariedCheckItemsOutput.model_json_schema()
    draft = schema["$defs"]["VariedCheckItemDraft"]["properties"]
    option = schema["$defs"]["OptionDraft"]["properties"]
    assert len(schema["properties"]) + len(draft) + len(option) == 20


def test_from_varied_reads_the_answer_kind_off_the_canonical_value():
    numeric = from_varied(VariedCheckItemDraft.model_validate(_varied()))
    assert isinstance(numeric, SurfacedCheckItemDraft) and isinstance(numeric, CheckItemDraft)
    assert numeric.answer_kind == "numeric" and numeric.canonical_answer == "0.8"
    free = from_varied(VariedCheckItemDraft.model_validate(_varied(canonical_answer="")))
    assert free.answer_kind == "free"
    # a canonical that is no number is no numeric answer (validate_draft's reading)
    word = from_varied(VariedCheckItemDraft.model_validate(_varied(canonical_answer="Paris")))
    assert word.answer_kind == "free"


def test_from_varied_reads_stepwise_off_the_numbered_lines():
    steps = "1. Count the entries.\n2. Count the buckets.\n3. Divide. Final answer: 0.8."
    assert from_varied(
        VariedCheckItemDraft.model_validate(_varied(reference_answer=steps))
    ).stepwise
    assert not from_varied(VariedCheckItemDraft.model_validate(_varied())).stepwise


def test_from_varied_keeps_the_surface_and_clips_the_context():
    draft = from_varied(
        VariedCheckItemDraft.model_validate(
            _varied(surface_context="  a   very long library checkout queue  label ")
        )
    )
    assert draft.surface_representation == "applied"
    assert draft.surface_context == "a very long library"
    assert len(draft.surface_context.split()) == params.SURFACE_CONTEXT_MAX_WORDS
    assert clip_context("   ") is None


def test_a_surfaced_draft_survives_the_repair_copy():
    from learning.checks import repair_draft

    draft = from_varied(VariedCheckItemDraft.model_validate(_varied()))
    fixed, _ = repair_draft(draft)
    assert isinstance(fixed, SurfacedCheckItemDraft)
    assert (fixed.surface_representation, fixed.surface_context) == (
        "applied",
        "Library checkout queue",
    )


def test_a_surface_is_a_known_representation_and_a_named_context():
    assert surface("numeric", "  Phone   Contacts. ") == Surface("numeric", "phone contacts")
    assert surface("cartoon", "x") is None
    assert surface("verbal", "") is None and surface("verbal", None) is None

    class Item:
        surface_representation = "visual"
        surface_context = "Bar Chart"

    assert surface_of(Item()) == Surface("visual", "bar chart")
    assert surface_of(object()) is None


def test_familiarity_counts_the_components_met():
    met = [Surface("applied", "library"), Surface("numeric", "phone contacts")]
    assert familiarity(Surface("visual", "bar chart"), met) == 0
    assert familiarity(Surface("applied", "bar chart"), met) == 1
    assert familiarity(Surface("visual", "library"), met) == 1
    assert familiarity(Surface("applied", "library"), met) == 2
    assert familiarity(None, met) == params.SURFACE_FAMILIARITY_UNKNOWN == 1
    assert familiarity(Surface("applied", "library"), []) == 0


def test_familiarity_by_hash_reads_only_the_met_items_descriptors():
    surfaces = {
        "seen": Surface("applied", "library"),
        "legacy-seen": None,  # met, but says nothing
        "new": Surface("visual", "bar chart"),
        "same-rep": Surface("applied", "garage"),
        "repeat": Surface("applied", "library"),
        "legacy": None,
    }
    ranks = familiarity_by_hash(surfaces, {"seen", "legacy-seen"})
    assert ranks == {
        "seen": 2,
        "legacy-seen": 1,
        "new": 0,
        "same-rep": 1,
        "repeat": 2,
        "legacy": 1,
    }
    # nothing met: every described item is new, every legacy one the middle
    assert familiarity_by_hash(surfaces, set())["repeat"] == 0
    assert familiarity_by_hash({"a": None, "b": None}, {"a"}) == {"a": 1, "b": 1}
