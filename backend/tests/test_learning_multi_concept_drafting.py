"""Multi-concept drafting (learning-loop spec §13 A141, flag `multi_concept_items`).

The combination drafter and its alignment check (requests and the rules that
apply their answers), the service's combination run (the uploader's graph,
the combinations, the skips, the write under the combination's key with its
apex and components), and that with the flag off nothing of it runs.
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from learning import params
from learning.item_alignment import (
    NOT_COMBINED,
    REASON_CODES,
    RUBRIC_UNASKED_DROPPED,
    UNASKED_RUBRIC,
    UNVERIFIED,
    ComponentVerdict,
    align_components,
    collect_components,
    component_ids,
)
from learning.multi_concept import SEP, combo_key
from tests.test_learning_check_items import _cached_tables, _draft, _mc_draft
from tests.test_learning_varied_drafting import PASSAGES, _capture

APEX, PRE = "learning rate", "gradient descent"
LABEL = "Learning Rate + Gradient Descent"
KEY = combo_key([APEX, PRE])


# ── the requests ─────────────────────────────────────────────────────────────


def test_the_combination_drafter_sends_its_own_prompt_the_labels_and_the_recorded_schema(monkeypatch):
    from agents import check_items as ci
    from agents.check_items_combo import (
        COMBINATIONS_HEADER,
        build_combo_prompt,
        check_items_combo_agent,
    )

    seen = _capture(
        monkeypatch, check_items_combo_agent, "check_items", build_combo_prompt([LABEL], PASSAGES)
    )
    (system,) = seen["system"]
    assert "using EVERY concept of the combination together" in system
    assert f"at difficulty {params.MULTI_CONCEPT_DIFFICULTY}" in system
    assert ci._FORMATS in system and ci._ITEM_FIELDS in system and ci._UNTRUSTED in system
    (user,) = seen["user"]
    assert user == f"{COMBINATIONS_HEADER}- {LABEL}\n\n" + ci.passages_section(PASSAGES)
    plain = _capture(monkeypatch, ci.check_items_agent, "check_items", ci.build_prompt(["X"], PASSAGES))
    assert seen["schema"] == plain["schema"]  # the plain drafter's schema, recorded live
    assert check_items_combo_agent._metadata["prompt_version"] != ci._PROMPT_HASH


def test_the_combination_check_asks_each_criterion_and_each_component(monkeypatch):
    from agents.check_items_combo_verify import (
        ComboVerifyItem,
        build_combo_verify_prompt,
        check_items_combo_verify_agent,
    )
    from agents.check_items_verify import CRITERIA_RULES, VerifyItem

    item = ComboVerifyItem(
        VerifyItem("1", "free", "Pick a rate for this descent.", None, (), ("Uses the gradient.", "Sizes the step.")),
        ("Learning Rate", "Gradient Descent"),
    )
    seen = _capture(
        monkeypatch, check_items_combo_verify_agent, "check_items_verify", build_combo_verify_prompt([item])
    )
    assert CRITERIA_RULES in seen["system"][0]
    assert "(b) For EVERY component of EVERY item decide `required`" in seen["system"][0]
    (user,) = seen["user"]
    assert "ITEM 1\n" in user and "CRITERION c2: Sizes the step." in user
    assert "COMPONENT k1: Learning Rate\nCOMPONENT k2: Gradient Descent" in user
    assert set(seen["schema"]["properties"]) == {"criteria", "components"}


# ── the rules (learning/item_alignment.py) ───────────────────────────────────


def test_component_ids_and_the_reason_code():
    assert component_ids(3) == ["k1", "k2", "k3"]
    assert REASON_CODES[NOT_COMBINED] == "not_combined"


def test_collect_components_drops_a_conflicted_or_half_answered_item():
    got = collect_components(
        [("1", "c1", True), ("2", "c1", True), ("2", "c1", False), ("3", "c1", True)],
        [("1", "K1", True), ("2", "k1", True), ("4", "k1", True)],
    )
    assert got == {"1": ComponentVerdict({"c1": True}, {"k1": True})}


@pytest.mark.parametrize(
    ("asked", "required", "expect"),
    [
        ({"c1": True, "c2": True}, {"k1": True, "k2": True}, ((0, 1), (), None)),
        ({"c1": True, "c2": False}, {"k1": True, "k2": True}, ((0,), (RUBRIC_UNASKED_DROPPED,), None)),
        ({"c1": False, "c2": False}, {"k1": True, "k2": True}, ((), (), UNASKED_RUBRIC)),
        ({"c1": True, "c2": True}, {"k1": True, "k2": False}, ((0, 1), (), NOT_COMBINED)),
        ({"c1": True}, {"k1": True, "k2": True}, ((), (), UNVERIFIED)),
        ({"c1": True, "c2": True}, {"k1": True}, ((), (), UNVERIFIED)),
    ],
)
def test_align_components_keeps_a_combination_only_when_every_component_is_needed(asked, required, expect):
    keep, flags, reject = expect
    out = align_components(2, 2, KEY, ComponentVerdict(asked, required))
    assert (out.keep, out.flags, out.reject) == (keep, flags, reject)
    assert out.concept_key == KEY  # never re-tagged
    assert align_components(2, 2, KEY, None).unverified


# ── the service ──────────────────────────────────────────────────────────────


@pytest.fixture
def svc(monkeypatch):
    import config
    from services import check_item_service as service
    from tests.key_check_fakes import install_key_passthrough

    monkeypatch.setattr(config, "LEARNING_LOOP_ENABLED", True)
    install_key_passthrough(monkeypatch)
    with patch("services.check_item_service._withdrawn_sources", return_value=[]):
        yield service


_GRAPH = {
    "graph_nodes": [
        {"id": "n-lr", "concept_name": "Learning Rate"},
        {"id": "n-gd", "concept_name": "Gradient Descent"},
        {"id": "n-x", "concept_name": "Momentum"},
    ],
    "graph_edges": [
        {"source_node_id": "n-gd", "target_node_id": "n-lr"},  # gradient descent → learning rate
    ],
    "check_items": [],
}
_CHUNKS = [
    {"id": "c1", "chunk_index": 0, "chunk_text": "gradient descent steps scaled by the learning rate", "doc_id": "doc-1"}
]


def _combo_drafts(label=LABEL, difficulty=params.MULTI_CONCEPT_DIFFICULTY):
    from agents.check_items import CheckItemsOutput

    return CheckItemsOutput(
        items=[
            _draft(concept=label, difficulty=difficulty, prompt="Pick a learning rate for this descent run."),
            _draft(concept=label, format="teachback", difficulty=difficulty, prompt="Teach how the rate sizes each descent step."),
            _mc_draft(concept=label, difficulty=difficulty, prompt="Which step size fits this descent run? Pick one and give your reason."),
        ]
    )


async def _all_needed(items, *, deps, flex):
    from agents.check_items_combo_verify import ComponentCheck, ComponentChecks
    from agents.check_items_verify import CriterionCheck
    from learning.item_alignment import component_ids, criterion_ids

    return ComponentChecks(
        criteria=[
            CriterionCheck(item=e.item.id, criterion=cid, why="asked", asked=True)
            for e in items
            for cid in criterion_ids(len(e.item.criteria))
        ],
        components=[
            ComponentCheck(item=e.item.id, component=kid, why="used", required=True)
            for e in items
            for kid in component_ids(len(e.components))
        ],
    )


def test_the_combination_run_drafts_checks_and_stores_under_the_combination(svc):
    factory, mocks = _cached_tables(_GRAPH)
    calls, checked = [], []

    async def draft(labels, passages, *, deps, flex):
        calls.append(list(labels))
        assert passages and deps.user_id == "u1" and deps.course_id == "course-1"
        return _combo_drafts()

    async def verify(items, *, deps, flex):
        checked.extend((e.item.format, e.components) for e in items)
        return await _all_needed(items, deps=deps, flex=flex)

    with (
        patch("services.check_item_service.table", side_effect=factory),
        patch("services.check_item_service.draft_combo_items", side_effect=draft),
        patch("services.check_item_service.verify_combo_items", side_effect=verify),
        patch("services.check_item_service.count_items", return_value=0),
        patch("services.check_item_service.log_event"),
    ):
        out = svc.generate_combos_for_document(
            user_id="u1",
            course_id="course-1",
            concept_names=["Learning Rate", "Gradient Descent", "Momentum"],
            chunks=_CHUNKS,
            flex=True,
            document_id="doc-1",
        )
    assert calls == [[LABEL]]  # the one apex with a prerequisite, its one pair
    assert checked == [(f, ("Learning Rate", "Gradient Descent")) for f in params.CHECK_ITEM_FORMATS]
    assert out.items_created == 3 and out.concepts_attempted == 1 and out.unavailable == 0
    rows = [r for c in mocks["check_items"].upsert.call_args_list for r in c[0][0]]
    assert {r["concept_key"] for r in rows} == {KEY} and SEP in KEY
    assert all(r["apex_key"] == APEX and r["component_keys"] == [APEX, PRE] for r in rows)
    assert all(r["difficulty"] == params.MULTI_CONCEPT_DIFFICULTY for r in rows)
    assert sorted(r["format"] for r in rows) == sorted(params.CHECK_ITEM_FORMATS)
    assert all(r["canonical_verified"] is True for r in rows)  # the A124 solve ran (passthrough)


def test_a_full_or_ungrounded_combination_makes_no_call(svc):
    factory, _ = _cached_tables(_GRAPH)
    draft = MagicMock()
    with (
        patch("services.check_item_service.table", side_effect=factory),
        patch("services.check_item_service.draft_combo_items", draft),
        patch("services.check_item_service.count_items", return_value=params.MULTI_CONCEPT_ITEMS_PER_COMBO),
    ):
        out = svc.generate_combos_for_document(
            user_id="u1", course_id="course-1", concept_names=["Learning Rate"], chunks=_CHUNKS, flex=True
        )
    assert out.concepts_skipped == 1 and not draft.called
    unrelated = [{"id": "c9", "chunk_index": 0, "chunk_text": "momentum only", "doc_id": "doc-1"}]
    with (
        patch("services.check_item_service.table", side_effect=factory),
        patch("services.check_item_service.draft_combo_items", draft),
        patch("services.check_item_service.count_items", return_value=0),
    ):
        out = svc.generate_combos_for_document(
            user_id="u1", course_id="course-1", concept_names=["Learning Rate"], chunks=unrelated, flex=True
        )
    assert out.concepts_unmatched == 1 and not draft.called


def test_drafts_off_the_combinations_or_their_difficulty_are_dropped(svc):
    factory, mocks = _cached_tables(_GRAPH)

    async def draft(labels, passages, *, deps, flex):
        drafts = _combo_drafts()
        drafts.items.append(_draft(concept="Momentum + Other", difficulty=3, prompt="Something else entirely?"))
        drafts.items[0] = drafts.items[0].model_copy(update={"difficulty": 2})
        return drafts

    with (
        patch("services.check_item_service.table", side_effect=factory),
        patch("services.check_item_service.draft_combo_items", side_effect=draft),
        patch("services.check_item_service.verify_combo_items", side_effect=_all_needed),
        patch("services.check_item_service.count_items", return_value=0),
        patch("services.check_item_service.log_event"),
    ):
        out = svc.generate_combos_for_document(
            user_id="u1", course_id="course-1", concept_names=["Learning Rate"], chunks=_CHUNKS, flex=True
        )
    rows = [r for c in mocks["check_items"].upsert.call_args_list for r in c[0][0]]
    assert out.items_created == 2 and {r["concept_key"] for r in rows} == {KEY}


def test_an_unavailable_combination_check_fails_closed(svc):
    from agents.check_items import CheckItemsUnavailable

    factory, mocks = _cached_tables(_GRAPH)

    async def draft(labels, passages, *, deps, flex):
        return _combo_drafts()

    async def down(items, *, deps, flex):
        return CheckItemsUnavailable(reason="ModelHTTPError")

    events = MagicMock()
    with (
        patch("services.check_item_service.table", side_effect=factory),
        patch("services.check_item_service.draft_combo_items", side_effect=draft),
        patch("services.check_item_service.verify_combo_items", side_effect=down),
        patch("services.check_item_service.count_items", return_value=0),
        patch("services.check_item_service.log_event", events),
    ):
        out = svc.generate_combos_for_document(
            user_id="u1", course_id="course-1", concept_names=["Learning Rate"], chunks=_CHUNKS, flex=True
        )
    assert out.items_created == 0 and out.unavailable == 1
    assert "check_items" not in mocks or not mocks["check_items"].upsert.called
    assert events.call_args.kwargs["payload"]["reason"] == "VerifyUnavailable"


def test_a_combination_the_question_does_not_need_is_rejected(svc):
    from agents.check_items_combo_verify import ComponentCheck, ComponentChecks
    from agents.check_items_verify import CriterionCheck
    from learning.item_alignment import component_ids, criterion_ids

    factory, mocks = _cached_tables(_GRAPH)

    async def draft(labels, passages, *, deps, flex):
        return _combo_drafts()

    async def one_unneeded(items, *, deps, flex):
        return ComponentChecks(
            criteria=[
                CriterionCheck(item=e.item.id, criterion=cid, why="asked", asked=True)
                for e in items
                for cid in criterion_ids(len(e.item.criteria))
            ],
            components=[
                ComponentCheck(item=e.item.id, component=kid, why="x", required=not (e.item.id == "1" and kid == "k2"))
                for e in items
                for kid in component_ids(len(e.components))
            ],
        )

    with (
        patch("services.check_item_service.table", side_effect=factory),
        patch("services.check_item_service.draft_combo_items", side_effect=draft),
        patch("services.check_item_service.verify_combo_items", side_effect=one_unneeded),
        patch("services.check_item_service.count_items", return_value=0),
        patch("services.check_item_service.log_event"),
    ):
        out = svc.generate_combos_for_document(
            user_id="u1", course_id="course-1", concept_names=["Learning Rate"], chunks=_CHUNKS, flex=True
        )
    assert out.items_created == 2  # the first draft did not need gradient descent


def test_a_validation_failure_of_several_combinations_reruns_each_alone(svc):
    from agents.check_items import CheckItemsUnavailable

    graph = {
        **_GRAPH,
        "graph_edges": [
            {"source_node_id": "n-gd", "target_node_id": "n-lr"},
            {"source_node_id": "n-x", "target_node_id": "n-lr"},
        ],
    }
    factory, _ = _cached_tables(graph)
    chunks = [{**_CHUNKS[0], "chunk_text": _CHUNKS[0]["chunk_text"] + " with momentum"}]
    calls = []

    async def draft(labels, passages, *, deps, flex):
        calls.append(list(labels))
        if len(labels) > 1:
            return CheckItemsUnavailable(reason="UnexpectedModelBehavior")
        return _combo_drafts(labels[0])

    with (
        patch("services.check_item_service.table", side_effect=factory),
        patch("services.check_item_service.draft_combo_items", side_effect=draft),
        patch("services.check_item_service.verify_combo_items", side_effect=_all_needed),
        patch("services.check_item_service.count_items", return_value=0),
        patch("services.check_item_service.log_event"),
    ):
        out = svc.generate_combos_for_document(
            user_id="u1", course_id="course-1", concept_names=["Learning Rate"], chunks=chunks, flex=True
        )
    pairs = ["Learning Rate + Gradient Descent", "Learning Rate + Momentum"]
    triple = "Learning Rate + Gradient Descent + Momentum"
    assert calls[0] == [*pairs, triple]
    assert sorted(map(tuple, calls[1:])) == sorted([(p,) for p in [*pairs, triple]])
    assert out.concepts_attempted == 3 and out.items_created == 9


def test_with_the_flag_off_no_combination_is_ever_drafted(monkeypatch):
    import config
    from services import check_item_service as service

    monkeypatch.setattr(config, "LEARNING_LOOP_ENABLED", True)
    factory, _ = _cached_tables({"documents": [{"id": "doc-1", "shareability": "course_material"}]})
    combos = MagicMock()
    concepts = MagicMock(return_value=service.GenerationOutcome(2, 1, 0, 0, 0))
    with (
        patch("services.check_item_service.table", side_effect=factory),
        patch("services.check_item_service.source_chunks", return_value=_CHUNKS),
        patch("services.check_item_service.generate_for_concepts", concepts),
        patch("services.check_item_service.generate_combos_for_document", combos),
        patch("services.check_item_service.mark_drafting"),
    ):
        off = service.generate_for_document(
            "doc-1", user_id="u1", course_id="course-1", concept_names=["Learning Rate"], flex=True
        )
        assert off == (2, 1, 0, 0, 0) and not combos.called
        assert concepts.call_args.kwargs["varied"] is False
        combos.return_value = service.GenerationOutcome(3, 1, 0, 1, 0)
        on = service.generate_for_document(
            "doc-1", user_id="u1", course_id="course-1", concept_names=["Learning Rate"], flex=True,
            flags=service.DraftingFlags(multi_concept=True),
        )
    assert on == (5, 2, 0, 1, 0)
    assert combos.call_args.kwargs["concept_names"] == ["Learning Rate"]


def test_the_uploader_graph_is_keys_and_direct_prerequisites(svc):
    factory, _ = _cached_tables(_GRAPH)
    with patch("services.check_item_service.table", side_effect=factory):
        names, parents = svc._uploader_graph("u1", "course-1")
    assert names == {"learning rate": "Learning Rate", "gradient descent": "Gradient Descent", "momentum": "Momentum"}
    assert parents == {"learning rate": {"gradient descent"}}


# ── function mode ────────────────────────────────────────────────────────────


def test_the_e2e_handlers_answer_the_combination_drafter_and_its_check(monkeypatch):
    """The check_items handler drafts one item per format for each listed
    combination; the check_items_verify handler needs every component of a
    marked item. Run through the real agents and their real schemas."""
    from agents import function_handlers_e2e as fh
    from agents._providers import clear_function_handlers, model_for, register_function_handler
    from agents.check_items_combo import build_combo_prompt, check_items_combo_agent
    from agents.check_items_combo_verify import (
        ComboVerifyItem,
        build_combo_verify_prompt,
        check_items_combo_verify_agent,
        component_verdicts,
    )
    from agents.check_items_verify import VerifyItem
    from agents.deps import SaplingDeps

    monkeypatch.setenv("SAPLING_MODEL_MODE", "function")
    deps = SaplingDeps(user_id="u", course_id="c", supabase=None, request_id="r")
    clear_function_handlers()
    register_function_handler("check_items", fh._check_items_handler)
    register_function_handler("check_items_verify", fh._verify_handler)
    try:
        with check_items_combo_agent.override(model=model_for("check_items")):
            out = check_items_combo_agent.run_sync(build_combo_prompt([LABEL], PASSAGES), deps=deps).output
        items = out.items
        assert [(i.concept, i.format, i.difficulty) for i in items] == [
            (LABEL, f, params.MULTI_CONCEPT_DIFFICULTY) for f in params.CHECK_ITEM_FORMATS
        ]
        subject = ComboVerifyItem(
            VerifyItem("1", "free", items[0].prompt, None, (), tuple(items[0].rubric)),
            ("Learning Rate", "Gradient Descent"),
        )
        with check_items_combo_verify_agent.override(model=model_for("check_items_verify")):
            checks = check_items_combo_verify_agent.run_sync(
                build_combo_verify_prompt([subject]), deps=deps
            ).output
        verdict = component_verdicts(checks)["1"]
        assert verdict.required == {"k1": True, "k2": True} and all(verdict.asked.values())
    finally:
        clear_function_handlers()
    # the plain request still gets the plain payload exactly
    assert fh._combination_labels("Concepts (write items for each; ...)\n- A\n\n") == []


def test_asyncio_free_run_of_the_drafter_entry_point(monkeypatch):
    """draft_combo_items rides run_drafting under its own feature."""
    from agents import check_items_combo

    seen = {}

    async def fake_run(agent, prompt, *, deps, flex, feature, task="check_items"):
        seen.update(agent=agent, feature=feature, task=task, prompt=prompt)
        return "out"

    monkeypatch.setattr(check_items_combo, "run_drafting", fake_run)
    out = asyncio.run(check_items_combo.draft_combo_items([LABEL], PASSAGES, deps=None, flex=True))
    assert out == "out" and seen["feature"] == "check_items_combo" and seen["task"] == "check_items"
    assert seen["agent"] is check_items_combo.check_items_combo_agent
