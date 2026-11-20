"""Every eval-gated flag names a recording the harness can make (#866 Z25).

The flag descriptions and docs/learning-loop/flag-rollout.md wait on
recordings: `varied_isomorphs` on "the varied check_items eval dataset",
`multi_concept_items` on "the multi-concept eval dataset",
`upload_prereq_edges` on the concept-extraction eval with relations on, and
`segment_prequestion` / `self_explanation_prompts` on "that path recorded live
in the loop_tutor evals" — and no eval could drive any of them. For
`loop_tutor_v2` the harness existed, but its variant was fixed at import, so
run_all.py and CI only ever replayed the default. Each flag now has a dataset
built with production's own helpers, named in its description, and a recorded
flag dataset (or v2 namespace) joins the default replay.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from agents.loop_tutor import PREQUESTION_LINE, SELF_EXPLAIN_ACK_LINE
from services.feature_flags import REGISTRY

EVALS = Path(__file__).parent / "evals"


@pytest.fixture(scope="module")
def ev():
    sys.path.insert(0, str(EVALS))
    try:
        import check_item_gates
        import concept_extraction
        import loop_tutor
        import misconception_confront

        yield SimpleNamespace(
            gates=check_item_gates, ce=concept_extraction, lt=loop_tutor, mc=misconception_confront
        )
    finally:
        sys.path.remove(str(EVALS))


def _description(key: str) -> str:
    return REGISTRY[key].description


def test_a_recorded_v2_namespace_joins_the_default_replay(ev):
    lt, mc = ev.lt, ev.mc
    assert not any(name.endswith("__v2") for name in lt.replay_variants(recorded=lambda s: False))
    v2 = {n for n in lt.replay_variants(recorded=lambda s: s.endswith("__v2")) if n.endswith("__v2")}
    assert v2 == {lt.variant_namespace(slot, True) for slot in ("loop_tutor_lite", "loop_tutor", "loop_tutor_deep")}
    assert {n for n in mc.replay_variants(recorded=lambda slot: True) if n.endswith("__v2")} == {
        mc.dataset_name(slot, True) for slot in mc.CONFRONT_SLOTS
    }
    assert set(mc.replay_variants(recorded=lambda slot: False)) == {
        mc.dataset_name(slot, False) for slot in mc.CONFRONT_SLOTS
    }


def test_the_prequestion_and_self_explanation_paths_have_their_own_datasets(ev):
    lt = ev.lt
    flags = lt.flag_variants(False)
    assert set(flags) == {lt.flags_namespace(s, False) for s in ("loop_tutor_lite", "loop_tutor", "loop_tutor_deep")}
    by_name = {c.name: c for c in lt.FLAG_CASES}
    pq = lt._assembled(by_name["teach_explains_prequestion"].inputs)
    assert PREQUESTION_LINE in pq and "[PREQUESTION ANSWER]" in pq
    se = lt._assembled(by_name["teach_acknowledges_self_explanation"].inputs)
    assert SELF_EXPLAIN_ACK_LINE in se
    for case in lt.FLAG_CASES:  # the turn reads the history the route sends
        assert len(lt._history(case.inputs)) == len(case.metadata["history"]) == 2
        assert lt._assembled(case.inputs, v2=True)  # a v2 teach case has its plan focus
    # never routing: the flag cases are not in a routing dataset
    assert not {c.name for c in lt.FLAG_CASES} & {c.name for c in lt.CASES}
    # replayed once recorded, in both variants
    assert set(flags) <= set(lt.replay_variants(recorded=lambda s: True))
    assert not set(flags) & set(lt.replay_variants(recorded=lambda s: False))
    for key in ("segment_prequestion", "self_explanation_prompts"):
        assert "<slot>__flags" in _description(key), key


def test_the_varied_and_combination_drafters_have_datasets(ev):
    g = ev.gates
    kinds = {name: {c.metadata["kind"] for c in make().cases} for name, (make, _) in g.ALL_VARIANTS.items()}
    assert kinds["check_items_varied"] == {"varied", "varied_topup"}
    assert kinds["check_items_combo"] == {"combo", "combo_verify"}
    assert set(g.ONCE_RECORDED) == {"check_items_varied", "check_items_combo"}
    assert not set(g.ONCE_RECORDED) & set(g.replay_variants(recorded=lambda n: False))
    assert set(g.ONCE_RECORDED) <= set(g.replay_variants(recorded=lambda n: True))
    assert "check_items_varied eval dataset" in _description("varied_isomorphs")
    assert "check_items_combo eval dataset" in _description("multi_concept_items")


def test_the_relations_variant_runs_production_extraction_arguments(ev):
    from agents.concept_extraction import _PREREQ_PROMPT_HASH, ConceptList, extraction_run_args

    ce = ev.ce
    for case in ce.RELATION_CASES:
        args = ce._relations_args(case.inputs)
        assert args["output_type"] is ConceptList and args["instructions"]
        assert args == extraction_run_args(
            ce.wrap_document_input(case.inputs), prerequisites=True,
            existing_concepts=case.metadata["existing"],
        )
        assert ce.relations_identity(case.inputs)["prompt_hash"] == _PREREQ_PROMPT_HASH
    assert set(ce.replay_variants(recorded=lambda n: False)) == {"concept_extraction"}
    assert ce.RELATIONS_DATASET in ce.replay_variants(recorded=lambda n: True)


def test_the_relations_evaluators_score_the_edges_code_would_write(ev):
    from agents.concept_extraction import Concept, ConceptList, PrerequisiteRelation

    ce = ev.ce
    case = ce.RELATION_CASES[1]  # Mean -> Variance -> Standard Deviation

    def out(*edges):
        return ConceptList(
            concepts=[Concept(name="Variance", description="d", importance=0.9),
                      Concept(name="Standard Deviation", description="d", importance=0.8)],
            prerequisites=[PrerequisiteRelation(prerequisite=a, dependent=b) for a, b in edges],
        )

    def ctx(output):
        return SimpleNamespace(inputs=case.inputs, output=output, metadata=case.metadata)

    right = out(("Mean", "Variance"), ("Variance", "Standard Deviation"))
    assert ce.ExpectedEdgesWritten().evaluate(ctx(right)) == 1.0
    assert ce.NoReversedEdge().evaluate(ctx(right)) == 1.0
    assert ce.RelationsKept().evaluate(ctx(right)) == 1.0
    backwards = out(("Variance", "Mean"))
    assert ce.NoReversedEdge().evaluate(ctx(backwards)) == 0.0
    assert ce.ExpectedEdgesWritten().evaluate(ctx(backwards)) == 0.0
    unknown = out(("Mean", "Variance"), ("Median", "Variance"))
    assert ce.RelationsKept().evaluate(ctx(unknown)) == 0.5
