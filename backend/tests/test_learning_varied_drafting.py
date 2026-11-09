"""Surface-varied drafting (learning-loop spec §13 A140, flag `varied_isomorphs`).

- Flag off is byte-identical: every check-item drafting request — the plain
  drafter, the A37 top-up, the A119 alignment check, the A124 blind solve and
  key match — sends exactly what f9eca612 sent (system prompt, instructions,
  message, output tool and schema, prompt version), captured by running each
  agent in function mode; the service never reaches a varied agent, and the
  stored row names no new column.
- Flag on: the varied drafter and top-up send their own prompt (the plain
  fragments plus the surface rules), the varied schema and the concepts' stored
  surfaces; the service stores each item's descriptor (the context encrypted).
"""

from __future__ import annotations

import hashlib
import json
from unittest.mock import MagicMock, patch

import pytest
from pydantic_ai.messages import ModelResponse, ToolCallPart

from tests.test_learning_check_items import _CHUNK, _cached_tables, _draft, _drafts_for

PASSAGES = [
    {"id": "chunk-1", "text": "A load factor is entries over buckets."},
    {"id": None, "text": "Tables resize."},
]

# Captured at f9eca612 (the agents and CheckItemDraft are unchanged since: the
# A140 refactor composes the same prompts from named fragments) by running each
# agent in function mode on the inputs below. sha256 of json.dumps(the system
# prompt parts) / of json.dumps(the user prompt parts) / of the output tool's
# JSON schema (sort_keys). Change these only with a recorded eval behind it.
_TOOL = ("final_result", "The final response which ends this conversation")
PRE_A140 = {
    "check_items": {
        "system": "9668310f405f86c28a1a8ad6591a740d72070d11b97733f50f9f6832c76d19a4",
        "user": "828c7358638b7e890087874a94b5ccf342b18b42478a49c6eba8fa65cac828af",
        "schema": "168ef05c76b2138ce56f6ebab644b613d47afc8468a44c8ba6781ccc55e415e5",
        "prompt_version": "4710781c2f16",
    },
    "check_items_topup": {
        "system": "42547b3f8c933e62bea5574c2c170aece95cd30024ff0d7d85a8a2ba1696eb6e",
        "user": "c3384efdae8741475aa89ce1db8177ee0688eb4177cbb4bc243b74edff078542",
        "schema": "168ef05c76b2138ce56f6ebab644b613d47afc8468a44c8ba6781ccc55e415e5",
        "prompt_version": "8c4d6fdcc602",
    },
    "check_items_verify": {
        "system": "a1853cf6aa0ba74064a21b7c691ba64da9076ce30523b1a4538895f1af02dadf",
        "user": "d581cf756ace469105e0089672102866a0ca8b4544073f2ba3608b569dea66bd",
        "schema": "60b1c7d2019f640767ded2d79de686acec2fb62f9497e6794f885f1746521cda",
        "prompt_version": "d9233c2230b2",
    },
    "check_items_solve": {
        "system": "411b9013431b19f0fa069f4b0a8e81b02c7e897e23f1f0d24989e55fbd1dd15d",
        "user": "9a78c780e3fe8951f9e3196f6caa595fd36bfd806fa9c0705bdf4f2af9deb4fe",
        "schema": "88bcd538d6e8fb4348c07645deab0992a775c4d41e2d1d58454ed505bffde569",
        "prompt_version": "19ee320924d8",
    },
    "check_items_key_match": {
        "system": "238f35a6e120f54092a374c059440ca2653150f6dc572fe079a9c234746cd3fb",
        "user": "1eedd0a1010f69a06a90de9868146febb8973fe2c17473fbebdb9e8cc6de7ec2",
        "schema": "bebc60b6f6577a5c6da770dc1923c44ffd3d912e08a1ede7347068761b925779",
        "prompt_version": "efd254b879eb",
    },
}


def _sha(value) -> str:
    raw = value if isinstance(value, str) else json.dumps(value, sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()


def _plain_requests():
    from agents.check_items import build_prompt, check_items_agent
    from agents.check_items_key_match import (
        MatchItem,
        build_match_prompt,
        check_items_key_match_agent,
    )
    from agents.check_items_solve import SolveItem, build_solve_prompt, check_items_solve_agent
    from agents.check_items_topup import build_topup_prompt, check_items_topup_agent
    from agents.check_items_verify import VerifyItem, build_verify_prompt, check_items_verify_agent

    return {
        "check_items": (
            check_items_agent,
            "check_items",
            build_prompt(["Load Factor", "Hash Table"], PASSAGES),
        ),
        "check_items_topup": (
            check_items_topup_agent,
            "check_items",
            build_topup_prompt(
                "Load Factor", PASSAGES, difficulties=[2, 3], drop_reasons=["option_count: 3"]
            ),
        ),
        "check_items_verify": (
            check_items_verify_agent,
            "check_items_verify",
            build_verify_prompt(
                ["Load Factor", "Hash Table"],
                [
                    VerifyItem(
                        "1",
                        "free",
                        "What is a load factor?",
                        None,
                        (),
                        ("Says entries over buckets.", "Gives 0.8."),
                    )
                ],
            ),
        ),
        "check_items_solve": (
            check_items_solve_agent,
            "check_items_solve",
            build_solve_prompt(PASSAGES, [SolveItem("1", "free", "What is a load factor?", (), "free")]),
        ),
        "check_items_key_match": (
            check_items_key_match_agent,
            "check_items_solve",
            build_match_prompt([MatchItem("1", "What is a load factor?", "entries over buckets", "n/m")]),
        ),
    }


def _capture(monkeypatch, agent, task, message) -> dict:
    """Run the real agent in function mode and capture what it sends the model."""
    from agents._providers import clear_function_handlers, model_for, register_function_handler
    from agents.deps import SaplingDeps

    monkeypatch.setenv("SAPLING_MODEL_MODE", "function")
    seen: dict = {}

    class _Captured(Exception):
        pass

    def handler(messages, info):
        parts = [p for m in messages for p in getattr(m, "parts", [])]
        tool = info.output_tools[0]
        seen.update(
            system=[p.content for p in parts if p.part_kind == "system-prompt"],
            user=[p.content for p in parts if p.part_kind == "user-prompt"],
            instructions=info.instructions,
            tool=(tool.name, tool.description),
            schema=tool.parameters_json_schema,
        )
        raise _Captured

    clear_function_handlers()
    register_function_handler(task, handler)
    try:
        with agent.override(model=model_for(task)):
            with pytest.raises(_Captured):
                agent.run_sync(
                    message,
                    deps=SaplingDeps(user_id="u", course_id="c", supabase=None, request_id="r"),
                )
    finally:
        clear_function_handlers()
    return seen


@pytest.mark.parametrize("name", sorted(PRE_A140))
def test_flag_off_requests_are_byte_identical_to_f9eca612(monkeypatch, name):
    agent, task, message = _plain_requests()[name]
    seen = _capture(monkeypatch, agent, task, message)
    pin = PRE_A140[name]
    assert _sha(seen["system"]) == pin["system"]
    assert seen["instructions"] is None
    assert _sha(seen["user"]) == pin["user"]
    assert seen["tool"] == _TOOL
    assert _sha(seen["schema"]) == pin["schema"]
    assert agent._metadata["prompt_version"] == pin["prompt_version"]


def test_the_plain_prompts_are_their_fragments_byte_for_byte():
    from agents import check_items as ci
    from agents import check_items_topup as tu

    assert ci._PROMPT_HASH == PRE_A140["check_items"]["prompt_version"]
    assert tu._PROMPT_HASH == PRE_A140["check_items_topup"]["prompt_version"]


# ── the varied requests (flag on) ────────────────────────────────────────────


def test_the_varied_drafter_sends_its_own_prompt_schema_and_the_stored_surfaces(monkeypatch):
    from agents import check_items as ci
    from agents.check_items_varied import (
        SURFACE_RULES,
        build_varied_prompt,
        check_items_varied_agent,
    )

    used = {"Load Factor": [("applied", "library  checkout")]}
    seen = _capture(
        monkeypatch,
        check_items_varied_agent,
        "check_items",
        build_varied_prompt(["Load Factor", "Hash Table"], PASSAGES, used),
    )
    (system,) = seen["system"]
    assert SURFACE_RULES in system and system.startswith(ci._INTRO)
    assert "`answer_kind`" not in system and "`stepwise`" not in system
    assert ci._FORMATS in system and ci._ITEM_FIELDS in system and ci._UNTRUSTED in system
    draft = seen["schema"]["$defs"]["VariedCheckItemDraft"]["properties"]
    assert {"surface_representation", "surface_context"} <= set(draft)
    assert not {"answer_kind", "stepwise"} & set(draft)
    (user,) = seen["user"]
    plain = ci.build_prompt(["Load Factor", "Hash Table"], PASSAGES)
    assert user.startswith(ci.concepts_section(["Load Factor", "Hash Table"]))
    assert user.endswith(ci.passages_section(PASSAGES))
    assert "- Load Factor: applied / library checkout\n" in user
    assert user != plain
    # nothing stored yet: the plain message exactly
    assert build_varied_prompt(["Load Factor"], PASSAGES, {}) == ci.build_prompt(
        ["Load Factor"], PASSAGES
    )
    assert check_items_varied_agent._metadata["prompt_version"] != ci._PROMPT_HASH


def test_the_varied_top_up_sends_the_plain_request_and_the_concepts_surfaces(monkeypatch):
    from agents.check_items_topup import build_topup_prompt
    from agents.check_items_varied import SURFACE_RULES
    from agents.check_items_varied_topup import (
        build_varied_topup_prompt,
        check_items_varied_topup_agent,
    )

    message = build_varied_topup_prompt(
        "Load Factor",
        PASSAGES,
        difficulties=[2],
        drop_reasons=["x"],
        used=[("numeric", "phone contacts")],
    )
    seen = _capture(monkeypatch, check_items_varied_topup_agent, "check_items", message)
    assert SURFACE_RULES in seen["system"][0]
    plain = build_topup_prompt("Load Factor", PASSAGES, difficulties=[2], drop_reasons=["x"])
    head = plain.split("Passages (", 1)[0]
    assert seen["user"][0].startswith(head)
    assert "- Load Factor: numeric / phone contacts\n" in seen["user"][0]
    assert "VariedCheckItemDraft" in seen["schema"]["$defs"]


# ── the service ─────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _checks_pass(monkeypatch):
    """The A119 and A124 checks pass every draft as drafted (they are their
    own modules' tests), and every source stays live."""
    from tests.alignment_fakes import install_passthrough

    install_passthrough(monkeypatch)
    with patch("services.check_item_service._withdrawn_sources", return_value=[]):
        yield


@pytest.fixture
def loop_on(monkeypatch):
    import config
    from services import check_item_service as svc

    monkeypatch.setattr(config, "LEARNING_LOOP_ENABLED", True)
    monkeypatch.setattr(svc, "CHECK_ITEM_MC_MIN_PER_CONCEPT", 0)  # no top-up here


def _varied_for(*concepts):
    from learning.surface import VariedCheckItemsOutput

    plain = _drafts_for(*concepts).items
    items = []
    for n, d in enumerate(plain):
        data = d.model_dump(exclude={"answer_kind", "stepwise"})
        data.update(surface_representation=("applied", "numeric")[n % 2], surface_context=f"scene {n}")
        items.append(data)
    return VariedCheckItemsOutput.model_validate({"items": items})


def test_flag_off_drafts_with_the_plain_drafter_and_stores_no_surface(loop_on):
    from services import check_item_service as svc

    factory, mocks = _cached_tables({"check_items": []})

    async def plain(names, passages, *, deps, flex):
        return _drafts_for(*names)

    varied = MagicMock()
    with (
        patch("services.check_item_service.table", side_effect=factory),
        patch("services.check_item_service.draft_items", side_effect=plain) as d,
        patch("services.check_item_service.draft_items_varied", varied),
        patch("services.check_item_service.log_event"),
    ):
        out = svc.generate_for_concepts(
            user_id="u1", course_id="course-1", concept_names=["Learning Rate"],
            chunks=[_CHUNK], flex=True,
        )
    assert out.items_created == 2
    assert d.call_count == 1
    varied.assert_not_called()
    rows = [r for c in mocks["check_items"].upsert.call_args_list for r in c[0][0]]
    assert rows and all(
        not {"surface_representation", "surface_context", "apex_key", "component_keys"} & set(r)
        for r in rows
    )


def test_varied_drafts_with_the_varied_drafter_and_stores_each_descriptor(loop_on):
    from services import check_item_service as svc
    from services.encryption import decrypt_if_present, encrypt_if_present

    stored_surface = {
        "concept_key": "learning rate",
        "surface_representation": "verbal",
        "surface_context": encrypt_if_present("Old  Lecture"),
    }
    factory, mocks = _cached_tables({"check_items": [stored_surface]})
    calls = []

    async def varied(names, passages, *, used, deps, flex):
        calls.append((list(names), used))
        return _varied_for(*names)

    plain = MagicMock()
    with (
        patch("services.check_item_service.table", side_effect=factory),
        patch("services.check_item_service.draft_items", plain),
        patch("services.check_item_service.draft_items_varied", side_effect=varied),
        patch("services.check_item_service.count_items", return_value=0),
        patch("services.check_item_service.log_event"),
    ):
        out = svc.generate_for_concepts(
            user_id="u1", course_id="course-1", concept_names=["Learning Rate"],
            chunks=[_CHUNK], flex=True, varied=True,
        )
    plain.assert_not_called()
    assert calls == [(["Learning Rate"], {"Learning Rate": [("verbal", "Old Lecture")]})]
    assert out.items_created == 2
    rows = [r for c in mocks["check_items"].upsert.call_args_list for r in c[0][0]]
    assert [r["surface_representation"] for r in rows] == ["applied", "numeric"]
    assert [decrypt_if_present(r["surface_context"]) for r in rows] == ["scene 0", "scene 1"]
    assert all(r["surface_context"] != "scene 0" for r in rows)  # stored encrypted
    assert all(r["answer_kind"] == "free" and r["stepwise"] is False for r in rows)


def test_a_varied_top_up_runs_the_varied_top_up(monkeypatch):
    import config
    from services import check_item_service as svc
    from tests.test_learning_check_items import _mc_draft

    monkeypatch.setattr(config, "LEARNING_LOOP_ENABLED", True)
    factory, mocks = _cached_tables({"check_items": []})

    async def varied(names, passages, *, used, deps, flex):
        return _varied_for(*names)  # two free/teachback items: below the mc_reason floor

    topups = []

    async def varied_topup(name, passages, *, difficulties, drop_reasons, used, deps, flex):
        from learning.surface import VariedCheckItemsOutput

        topups.append((name, difficulties, used))
        drafts = [
            _mc_draft(difficulty=d, prompt=f"Which quantity does the rate scale at level {d}?")
            for d in difficulties
        ]
        items = []
        for d in drafts:
            data = d.model_dump(exclude={"answer_kind", "stepwise"})
            data.update(surface_representation="visual", surface_context=f"chart {d.difficulty}")
            items.append(data)
        return VariedCheckItemsOutput.model_validate({"items": items})

    plain_topup = MagicMock()
    with (
        patch("services.check_item_service.table", side_effect=factory),
        patch("services.check_item_service.draft_items_varied", side_effect=varied),
        patch("services.check_item_service.draft_mc_topup_varied", side_effect=varied_topup),
        patch("services.check_item_service.draft_mc_topup", plain_topup),
        patch("services.check_item_service.count_items", return_value=0),
        patch("services.check_item_service.log_event"),
    ):
        svc.generate_for_concepts(
            user_id="u1", course_id="course-1", concept_names=["Learning Rate"],
            chunks=[_CHUNK], flex=True, varied=True,
        )
    plain_topup.assert_not_called()
    assert topups and topups[0][0] == "Learning Rate"
    rows = [r for c in mocks["check_items"].upsert.call_args_list for r in c[0][0]]
    assert {r["surface_representation"] for r in rows if r["format"] == "mc_reason"} == {"visual"}


def test_the_drafting_version_is_unchanged_off_and_covers_the_varied_prompts_on():
    from agents import (
        check_items,
        check_items_key_match,
        check_items_solve,
        check_items_topup,
        check_items_varied,
        check_items_varied_topup,
        check_items_verify,
    )
    from agents._providers import model_name_for
    from services.check_item_service import _drafting_version, _source_fingerprint

    plain = "|".join(
        (
            check_items._PROMPT_HASH,
            check_items_topup._PROMPT_HASH,
            model_name_for("check_items"),
            check_items_verify._PROMPT_HASH,
            model_name_for("check_items_verify"),
            check_items_solve._PROMPT_HASH,
            check_items_key_match._PROMPT_HASH,
            model_name_for("check_items_solve"),
        )
    )
    assert _drafting_version() == plain  # f9eca612's composition
    assert _drafting_version(varied=True) == "|".join(
        (plain, check_items_varied._PROMPT_HASH, check_items_varied_topup._PROMPT_HASH)
    )
    ranked = [{"id": "c1", "chunk_text": "t"}]
    assert _source_fingerprint(ranked) != _source_fingerprint(ranked, varied=True)


def test_used_surfaces_reads_decrypts_and_lists_each_once():
    from services.check_item_service import used_surfaces
    from services.encryption import encrypt_if_present

    rows = [
        {"concept_key": "a", "surface_representation": "applied", "surface_context": encrypt_if_present("Bus  stop")},
        {"concept_key": "a", "surface_representation": "applied", "surface_context": encrypt_if_present("Bus stop")},
        {"concept_key": "a", "surface_representation": "cartoon", "surface_context": encrypt_if_present("x")},
        {"concept_key": "b", "surface_representation": "numeric", "surface_context": encrypt_if_present("Scores")},
    ]
    factory, mocks = _cached_tables({"check_items": rows})
    with patch("services.check_item_service.table", side_effect=factory):
        assert used_surfaces("c", ["a", "b", "a"]) == {
            "a": [("applied", "Bus stop")],
            "b": [("numeric", "Scores")],
        }
    _, kwargs = mocks["check_items"].select.call_args
    assert kwargs["filters"]["surface_representation"] == "not.is.null"
    broken = MagicMock(side_effect=RuntimeError("down"))
    with patch("services.check_item_service.table", broken):
        assert used_surfaces("c", ["a"]) == {}
    assert used_surfaces("c", []) == {}


def test_drafting_flags_are_off_without_a_student_and_read_once_with_one():
    from services.check_item_service import DraftingFlags, drafting_flags

    with patch("services.feature_flags.flag_on") as flag_on:
        assert drafting_flags(None) == DraftingFlags(False, False)
        flag_on.assert_not_called()
        flag_on.side_effect = lambda key, user: key == "varied_isomorphs"
        assert drafting_flags("u1") == DraftingFlags(varied=True, multi_concept=False)
        assert [c.args for c in flag_on.call_args_list] == [
            ("varied_isomorphs", "u1"),
            ("multi_concept_items", "u1"),
        ]


def test_the_flags_are_server_only_and_off_unconfigured(monkeypatch):
    from services import feature_flags as ff
    from tests.test_feature_flags import _tables

    for key in ("varied_isomorphs", "multi_concept_items"):
        monkeypatch.delenv(f"SAPLING_FLAG_{key.upper()}", raising=False)
        fd = ff.REGISTRY[key]
        assert fd.variants == ("off", "on") and not fd.client_visible
        with patch("services.feature_flags.table", side_effect=_tables()):
            assert ff.flag_on(key, "u1") is False


@pytest.mark.parametrize("flags_on", [False, True])
def test_the_upload_hook_passes_the_flags_only_when_one_is_on(monkeypatch, flags_on):
    from services.documents import post_roll as documents  # spec §13 A149: the chain lives here
    from services.check_item_service import DraftingFlags

    flags = DraftingFlags(varied=flags_on, multi_concept=False)
    monkeypatch.setattr(documents, "drafting_flags", lambda user_id: flags)
    monkeypatch.setattr(documents, "mark_drafting", lambda *a, **k: None)
    monkeypatch.setattr(documents, "index_document", lambda doc_id: None)
    monkeypatch.setattr(documents, "model_mode", lambda: "function")
    gen = MagicMock()
    monkeypatch.setattr(documents, "generate_for_document", gen)
    documents._index_then_check_items("doc-1", "u1", "course-1", ["Learning Rate"])
    expected = {"user_id": "u1", "course_id": "course-1", "concept_names": ["Learning Rate"], "flex": True}
    if flags_on:
        expected["flags"] = flags
    gen.assert_called_once_with("doc-1", **expected)


def test_a_plain_draft_names_no_new_column_and_a_varied_one_both():
    from learning.surface import SurfacedCheckItemDraft
    from services.check_item_service import _build_row
    from services.encryption import decrypt_if_present

    plain = _build_row("c", "learning rate", None, _draft(), allowed={"c1"}, source_docs=[])
    assert not {"surface_representation", "surface_context", "apex_key", "component_keys"} & set(plain)
    surfaced = SurfacedCheckItemDraft(
        **_draft().model_dump(), surface_representation="numeric", surface_context="Phone contacts"
    )
    row = _build_row("c", "learning rate", None, surfaced, allowed={"c1"}, source_docs=[])
    assert row["surface_representation"] == "numeric"
    assert decrypt_if_present(row["surface_context"]) == "Phone contacts"
    # a descriptor is whole or absent (the migration's CHECK)
    half = SurfacedCheckItemDraft(**_draft().model_dump(), surface_representation="numeric")
    row = _build_row("c", "learning rate", None, half, allowed={"c1"}, source_docs=[])
    assert row["surface_representation"] is None and row["surface_context"] is None


def test_the_e2e_handler_answers_the_plain_and_the_varied_drafter(monkeypatch):
    """The function-mode check_items handler: the plain schema gets the old
    payload exactly; the varied schema the same items, each on its own surface."""
    from agents import function_handlers_e2e as fh

    class Tool:
        name = "final_result"

        def __init__(self, defs):
            self.parameters_json_schema = {"$defs": defs}

    class Info:
        def __init__(self, defs):
            self.output_tools = [Tool(defs)]

    plain = fh._check_items_handler([], Info({"CheckItemDraft": {}}))
    assert isinstance(plain, ModelResponse) and isinstance(plain.parts[0], ToolCallPart)
    assert plain.parts[0].args == {"items": fh.E2E_CHECK_ITEMS}
    varied = fh._check_items_handler([], Info({"VariedCheckItemDraft": {}})).parts[0].args["items"]
    assert len(varied) == len(fh.E2E_CHECK_ITEMS)
    for concept in {i["concept"] for i in varied}:
        mine = [(i["surface_representation"], i["surface_context"]) for i in varied if i["concept"] == concept]
        assert len({r for r, _ in mine}) == len(mine) and len({c for _, c in mine}) == len(mine)
    assert all("answer_kind" not in i and "stepwise" not in i for i in varied)


def test_an_alignment_re_tag_carries_the_surface_descriptor():
    """The A119 backfill re-keys an item it re-tags: the moved row keeps the
    A140 descriptor as stored (the context still ciphertext), and the backfill
    reads it."""
    from learning.item_alignment import CONCEPT_RETAGGED, Alignment
    from services import check_item_service as svc
    from services.encryption import decrypt_if_present, encrypt_if_present
    from tests.test_learning_check_items import _item
    from tests.test_learning_item_keys import _row

    assert {"surface_representation", "surface_context"} <= set(svc._ALIGN_COLUMNS.split(","))
    item = _item(concept_key="recursion")
    context = encrypt_if_present("e2e step sizes")
    row = _row(item) | {
        "key_checked_at": "2026-11-08T01:00:00+00:00",
        "aligned_at": None,
        "surface_representation": "numeric",
        "surface_context": context,
    }
    retag = Alignment((0,), "base case", (CONCEPT_RETAGGED,))
    factory, mocks = _cached_tables({})
    with patch("services.check_item_service.table", side_effect=factory):
        svc.apply_item_alignment(row, item, retag, at="2026-11-08T02:00:00+00:00")
    ((moved,),) = mocks["check_items"].upsert.call_args[0][:1]
    assert moved["concept_key"] == "base case" and moved["id"] != item.id
    assert moved["surface_representation"] == "numeric"
    assert moved["surface_context"] == context  # copied untouched
    assert decrypt_if_present(moved["surface_context"]) == "e2e step sizes"
    # an item drafted before A140 moves without one, as before
    bare = _row(item) | {"key_checked_at": None, "aligned_at": None}
    factory, mocks = _cached_tables({})
    with patch("services.check_item_service.table", side_effect=factory):
        svc.apply_item_alignment(bare, item, retag, at="2026-11-08T02:00:00+00:00")
    ((moved,),) = mocks["check_items"].upsert.call_args[0][:1]
    assert "surface_representation" not in moved and "surface_context" not in moved
