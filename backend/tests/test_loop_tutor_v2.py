"""Spec §13 A121: the `loop_tutor_v2` flag picks the loop tutor's variant.

Off — the default — the tutor's request must be BYTE-IDENTICAL to 7fa9cd0e's,
because every recorded loop eval (tutor cassettes AND the rung/confront
judgements keyed on the served text) was recorded against it, and the owner
has approved no live re-record. The digests below were captured from 7fa9cd0e
by running that agent in function mode (the same capture as `_capture`, run
against a `git archive` export of the commit). Change them only with a
recorded eval behind the change.

On: the unchanged system prompt plus V2_INSTRUCTIONS as run instructions,
the LoopTurnOutV2 schema with its own output template, and its own prompt
version (A118's pattern, `agents.loop_tutor.variant_run_args`), plus the
per-turn lines (the empty question, [ANSWER CHECK], [PLAN FOCUS] with its
plan_concept block); its eval lives in its own cassette namespace
(`LOOP_EVAL_VARIANT=v2`). Every tutor-prompt change that needs a live
re-record belongs to this variant.
"""

from __future__ import annotations

import hashlib
import json

import pytest
from pydantic import TypeAdapter
from pydantic_ai.messages import ModelResponse, TextPart

import agents.loop_tutor as lt
from agents._providers import clear_function_handlers, model_for, register_function_handler
from agents.deps import SaplingDeps
from learning.ladder import Rung
from learning.turn_shape import LoopTurnOut, LoopTurnOutV2, turn_limits
from tests import test_learn_loop_routes as _routes
from tests.test_learn_loop_routes import _json_agent, _plan_state, client
from tests.split_patches import patch_loop, setattr_loop
import services.loop.flags

gate_on, no_rate_limit, seams = _routes.gate_on, _routes.no_rate_limit, _routes.seams


def _sha(value) -> str:
    raw = value if isinstance(value, str) else json.dumps(value, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# ── 7fa9cd0e, captured in function mode ──────────────────────────────────────

PRE_A121_PROMPT_HASH = "10676b7d004e"  # agents.loop_tutor._PROMPT_HASH, the metadata prompt_version
PRE_A121_SYSTEM_PROMPT_SHA256 = "5af380aad03cd13076a0f5550ae9b6c6b866714f2998c31769f40be781623c4c"
PRE_A121_OUTPUT_TEMPLATE_SHA256 = "f7d3986addb6c3774c5644ec7ed3232159316e2e161601421ad337da22cd91c4"
#: The request's instructions as the model gets them: the system prompt plus
#: the prompted-output instruction built from the template and the schema.
PRE_A121_INSTRUCTIONS_SHA256 = "9685fd37914d7b6798c0584254747bb803fc2c19862f2e7a2a34ccc6c06c8fd5"
#: The output object: its JSON schema, title and description (the TypedDict's
#: docstring — pydantic-ai sends it).
PRE_A121_SCHEMA_SHA256 = "f6c4d36a213fbaeaa31c1ece8c3ed9cf1583ff5b9185763346782c12e51c89e4"
PRE_A121_OUTPUT_NAME = "LoopTurnOut"
PRE_A121_DESCRIPTION_SHA256 = "833c699b55f34ffdef90ceda0178d804ed41aec19ca218e24a3ade68bbbfe7cb"

_TURN = {"key_idea": "A base case stops recursion.", "body": "It ends the calls.", "question": "Which input stops it?"}
_NONCE = "c0ffee" * 4
_PROBLEMS = ["body_sentences:3>1", "question_shape:2 '?'", "invented_math:x^2"]

#: case -> (phase_prefix kwargs, its prefix sha256, the user message sha256, the
#: retry message sha256 for _PROBLEMS at the case's limits)
PRE_A121_CASES = {
    "teach_h3": (
        dict(phase="teach", band="develop", ceiling=Rung.H3),
        "2ac6f1bbbe858e54dcda34cf1cca9dc6bbf24bf1d808c54b812fcc7a37e6af33",
        "d7ca9b4e73ed6ce143219dc08a654ec601103246944aae87a21ec120b6a48b27",
        "5558a60dc0a69b2f51df6e3ca3f807cab72e1f9ca73c4afcb651916434d8b6ba",
    ),
    "teach_h1": (
        dict(phase="teach", band="profic", ceiling=Rung.H1),
        "c0ee0de45b3a1506f72ebc97d590343f158472f18a12a944767801a621602ed3",
        "63fe7e21ff2556f971e3b315889651a20f349d542068a4f3efa578f878c93a9f",
        "fa74b4b444265ca1b6558e9aa248c8ddbb30bb460b60aa4e3a4f70af90d0ff8a",
    ),
    "teach_h5": (
        dict(phase="teach", band="novice", ceiling=Rung.H5),
        "0a787b71cbc8b6e406f7030a770ed259fdd44e488568696e3eb28d4f80135bd5",
        "1c5f16b4bf0c1ddc597b311fc03af5e4260ce6094acac2da049275cfc49c0f77",
        "1c12f9d7fb452aa4a93fbf19ab59a0ef61b5f6a136ec3166548b5684ce250079",
    ),
    "hint_h1": (
        dict(phase="hint", band="develop", ceiling=Rung.H1, item_prompt="What stops f(0)?", item_format="free"),
        "a6c4e93d5566865861e9314e7593e825af431cb7ff86bceca8a6de75ae5a4e2e",
        "068b245d7671348bacac3773345129e5a2067d2fd3bdfc8945b5b04047fb47a7",
        "fa74b4b444265ca1b6558e9aa248c8ddbb30bb460b60aa4e3a4f70af90d0ff8a",
    ),
    "hint_h2": (
        dict(phase="hint", band="novice", ceiling=Rung.H2, item_prompt="What stops f(0)?", item_format="free"),
        "58d16dd89fd963b3b486290ac295357e7c8dfb1b22d370301fdd651a3c5e8eb8",
        "833a6cfc0bff873d487a09b0c5aa5948b7ab3eb95d5660ca1284261e55d0cc84",
        "5558a60dc0a69b2f51df6e3ca3f807cab72e1f9ca73c4afcb651916434d8b6ba",
    ),
    "feedback_correct_h0": (
        dict(phase="feedback", band="profic", ceiling=Rung.H0, item_prompt="Q?", item_format="free", verdict="correct"),
        "7b46bbcf73de44028471944c55f0580eeff6dcefca0148ec4a53927db2d320af",
        "a71f3b8d02aba99455927b3f6b2c46f7c054a0d5e1c3661f27f8027ee0c007f2",
        "fa74b4b444265ca1b6558e9aa248c8ddbb30bb460b60aa4e3a4f70af90d0ff8a",
    ),
    "feedback_correct_h1": (
        dict(phase="feedback", band="profic", ceiling=Rung.H1, item_prompt="Q?", item_format="free", verdict="correct"),
        "6d1bd93f9a468c6c2b5458cb3e9087afddf74ae7bd63cd3907bb1457ceb8b9f9",
        "a72c7f28a3fe0f4ba04f9cdc1dc87a71288bb0765eb2706021e63dc467c243b5",
        "fa74b4b444265ca1b6558e9aa248c8ddbb30bb460b60aa4e3a4f70af90d0ff8a",
    ),
    "feedback_released": (
        dict(phase="feedback", band="develop", ceiling=Rung.H6, item_prompt="Q?", item_format="mc_reason",
             verdict="not_yet", answer_released=True),
        "7f38e7a90bd7d727cf1c5af637bc15eee98f402b87b91bb14b444c3c57e32a69",
        "3bf7c1de68575fb7e16d9f54cd252c1edfa81426fb3d50b6afbbc34655a54127",
        "3c24a7aa85b7920ddbf3fe0a9a9c83201a513997549d04e97542c8fc4f81f5b9",
    ),
    "feedback_idk": (
        dict(phase="feedback", band="novice", ceiling=Rung.H6, item_prompt="Q?", item_format="free",
             verdict="idk", answer_released=True),
        "2fa641323db29ae4fe2ea094c2978449971a03fd8720c9f26bae7e3e6ffc3aa5",
        "a07e8af2dd921f7496937045e636122f8ef99ff38afddf82c5c79d7a414f130d",
        "3c24a7aa85b7920ddbf3fe0a9a9c83201a513997549d04e97542c8fc4f81f5b9",
    ),
}

# ── the v2 variant, pinned so an edit to it is a deliberate one ──────────────
# (no recording exists yet; a change here only re-pins what its first live
# recording will be made against)

V2_INSTRUCTIONS_SHA256 = "5178da7e0786109d41907b60856c7bab5ae978a10234c1b585f847c45d29a8e0"
V2_OUTPUT_TEMPLATE_SHA256 = "8b38d332747a9209a396200a37eef5a34ad498cdc537c2506689dfee3ca89acf"
#: LoopTurnOutV2's JSON schema (what the eval's schema_hash is taken over)
#: and the output object's schema as the request carries it
V2_SCHEMA_SHA256 = "ee2a0f1f177fea6961205f9ee748f7698f3794c5557cd19058dae5da35fb0549"
V2_WIRE_SCHEMA_SHA256 = "54b75b0589cd5f8fc1a1363f7fc9be226c66cdb0d1545218f80e98da814b6125"
V2_PROMPT_VERSION = "bfcbabd1a4c0"  # sha256(system prompt, instructions, template)[:12]
ANSWER_CHECK_LINE_SHA256 = "b728e683c5e002bfbffe5b0200062b3cfdb270c3db1619ff634ca1c32438bcb4"
PLAN_FOCUS_REASONS_SHA256 = "d01b9552b709862b07dc6f4005620273df0bbf4333598494ad0f0b59613d8a70"


def _capture(prefix_kwargs: dict, limits, run_args: dict | None = None, turn: dict | None = None):
    """Run the real agent in function mode and capture what it sends the model:
    the instructions, the user prompt, the output mode, template and object
    (schema, title, description), the tools, and the run's metadata."""
    prefix = lt.phase_prefix(**prefix_kwargs)
    message = lt.assemble_turn_message(prefix=prefix, blocks=["CTX"], nonce=_NONCE, student_text="my answer")
    seen: dict = {}

    def handler(messages, info):
        params = info.model_request_parameters
        od = params.output_object
        seen.update(
            instructions=info.instructions,
            user=[p.content for m in messages for p in getattr(m, "parts", []) if p.part_kind == "user-prompt"],
            output_mode=params.output_mode,
            template=params.prompted_output_template,
            schema=od.json_schema,
            name=od.name,
            description=od.description,
            tools=sorted(t.name for t in info.function_tools),
        )
        return ModelResponse(parts=[TextPart(content=json.dumps(turn or _TURN))])

    clear_function_handlers()
    register_function_handler("loop_tutor", handler)
    deps = SaplingDeps(user_id="u", course_id="c", supabase=None, request_id="r")
    deps.loop_turn = limits
    try:
        result = lt.loop_tutor_agent.run_sync(
            message, deps=deps, model=model_for("loop_tutor"), **(run_args or {})
        )
    finally:
        clear_function_handlers()
    return prefix, seen, result


@pytest.mark.parametrize("case", sorted(PRE_A121_CASES))
def test_flag_off_request_is_byte_identical_to_7fa9cd0e(monkeypatch, case):
    monkeypatch.setenv("SAPLING_MODEL_MODE", "function")
    kwargs, prefix_sha, user_sha, retry_sha = PRE_A121_CASES[case]
    released = bool(kwargs.get("answer_released"))
    limits = turn_limits(kwargs["phase"], kwargs["ceiling"], released)
    prefix, seen, result = _capture(kwargs, limits, lt.variant_run_args(False))
    assert lt.variant_run_args(False) == {}
    assert _sha(prefix) == prefix_sha
    assert _sha(seen["user"]) == user_sha
    assert _sha(seen["instructions"]) == PRE_A121_INSTRUCTIONS_SHA256
    assert seen["output_mode"] == "prompted"
    assert _sha(seen["template"]) == PRE_A121_OUTPUT_TEMPLATE_SHA256
    assert _sha(seen["schema"]) == PRE_A121_SCHEMA_SHA256
    assert seen["name"] == PRE_A121_OUTPUT_NAME
    assert _sha(seen["description"]) == PRE_A121_DESCRIPTION_SHA256
    assert seen["tools"] == ["read_graph_neighborhood", "search_course_materials"]
    assert result.metadata == {"prompt_version": PRE_A121_PROMPT_HASH, "agent": "loop_tutor"}
    assert result.output == _TURN
    assert _sha(lt._retry_message(_PROBLEMS, limits)) == retry_sha


def test_flag_off_prompt_schema_and_check_posing_turn_are_7fa9cd0e_s():
    """The hashes the eval cassettes pin, and the check-posing directive: off,
    a turn that poses a check sends the same prefix and retry wording as any
    other (its render drops the question instead)."""
    assert lt._PROMPT_HASH == PRE_A121_PROMPT_HASH
    assert _sha(lt._LOOP_SYSTEM_PROMPT) == PRE_A121_SYSTEM_PROMPT_SHA256
    assert _sha(lt.LOOP_OUTPUT_TEMPLATE) == PRE_A121_OUTPUT_TEMPLATE_SHA256
    assert "answer_verdict" not in TypeAdapter(LoopTurnOut).json_schema()["properties"]
    plain = dict(phase="teach", band="develop", ceiling=Rung.H3)
    assert lt.phase_prefix(**plain, poses_check=True) == lt.phase_prefix(**plain)
    posing = turn_limits("teach", Rung.H3, False, question=False)
    assert _sha(lt._retry_message(_PROBLEMS, posing)) == PRE_A121_CASES["teach_h3"][3]
    with pytest.raises(ValueError, match="v2 variant"):
        lt.phase_prefix(**plain, answer_check=True)


def test_flag_on_request_adds_its_instructions_schema_template_and_version(monkeypatch):
    monkeypatch.setenv("SAPLING_MODEL_MODE", "function")
    kwargs = dict(phase="teach", band="develop", ceiling=Rung.H3, v2=True, poses_check=True,
                  answer_check=True)
    limits = turn_limits("teach", Rung.H3, False, question=False, answer_check=True, v2=True)
    answered = {"answer_verdict": "correct", **_TURN}
    prefix, seen, result = _capture(kwargs, limits, lt.variant_run_args(True), answered)
    assert lt.ANSWER_CHECK_LINE in prefix and 'question: leave it empty ("")' in prefix
    assert seen["instructions"].startswith(lt._LOOP_SYSTEM_PROMPT)  # unchanged, then the amendment
    assert lt.V2_INSTRUCTIONS in seen["instructions"]
    assert _sha(lt.V2_INSTRUCTIONS) == V2_INSTRUCTIONS_SHA256
    assert _sha(seen["template"]) == V2_OUTPUT_TEMPLATE_SHA256 != PRE_A121_OUTPUT_TEMPLATE_SHA256
    assert list(seen["schema"]["properties"]) == ["answer_verdict", "key_idea", "body", "question"]
    assert _sha(seen["schema"]) == V2_WIRE_SCHEMA_SHA256 != PRE_A121_SCHEMA_SHA256
    assert _sha(TypeAdapter(LoopTurnOutV2).json_schema()) == V2_SCHEMA_SHA256
    assert seen["name"] == "LoopTurnOutV2"
    assert result.metadata == {"prompt_version": V2_PROMPT_VERSION, "agent": "loop_tutor"}
    assert lt._V2_PROMPT_HASH == V2_PROMPT_VERSION != PRE_A121_PROMPT_HASH
    assert _sha(lt.ANSWER_CHECK_LINE) == ANSWER_CHECK_LINE_SHA256
    assert result.output == answered, "the variant's output keeps answer_verdict"
    # off, the same answer is read through 7fa9cd0e's schema: the verdict is dropped
    _, _, off = _capture(dict(phase="teach", band="develop", ceiling=Rung.H3),
                         turn_limits("teach", Rung.H3, False), {}, answered)
    assert off.output == _TURN


def test_the_plan_focus_is_a_v2_teach_line_that_never_names_the_concept():
    """Spec §13 A121 (v2): a teach turn's [PLAN FOCUS] line carries only the
    cursor's REASON, in fixed route words; the concept's name is data in the
    plan_concept untrusted block. Off the variant, or outside teach, it is refused."""
    teach = dict(phase="teach", band="develop", ceiling=Rung.H3)
    for reason in lt.PLAN_FOCUS_REASONS:
        prefix = lt.phase_prefix(**teach, v2=True, plan_reason=reason)
        assert lt.plan_focus_line(reason) in prefix
        assert prefix == lt.phase_prefix(**teach, v2=True) + "\n" + lt.plan_focus_line(reason)
    with pytest.raises(ValueError, match="v2 teach turn"):
        lt.phase_prefix(**teach, plan_reason="plan_order")  # off the variant
    with pytest.raises(ValueError, match="v2 teach turn"):
        lt.phase_prefix(phase="hint", band="develop", ceiling=Rung.H1, item_prompt="Q?",
                        v2=True, plan_reason="plan_order")
    with pytest.raises(ValueError, match="unknown plan focus reason"):
        lt.phase_prefix(**teach, v2=True, plan_reason="because")
    assert _sha(lt.PLAN_FOCUS_REASONS) == PLAN_FOCUS_REASONS_SHA256
    block = lt.plan_focus_block("Hash Tables")
    assert block.startswith("[BEGIN UNTRUSTED CONTENT source=plan_concept]") and "Hash Tables" in block
    assert "[PLAN FOCUS]" in lt.V2_INSTRUCTIONS and "plan_concept" in lt.V2_INSTRUCTIONS


def test_a_turn_that_echoes_the_plan_focus_line_is_retried():
    """[PLAN FOCUS] is a control block: a model turn that repeats it breaks the
    turn shape (control_tag), like [ANSWER CHECK] — and the eval's NoControlTags."""
    from learning.turn_shape import _CONTROL_TAG, validate_turn

    echoed = {**_TURN, "body": "[PLAN FOCUS] We are on hashing now."}
    problems = validate_turn(echoed, turn_limits("teach", Rung.H3, False))
    assert "control_tag:body" in problems
    assert _CONTROL_TAG.search("[PLAN FOCUS]")


def test_every_default_served_text_keeps_its_recorded_judgements(monkeypatch):
    """The flag-off served text of every recorded loop case is the text its rung
    (and confront) judgement was recorded on — those judgements are keyed on its
    sha256 — so a change to the DEFAULT render can never pass this lane while
    the Evals replay goes red (spec §13 A121: why the label rule and the feedback
    verdict line are v2's). Replay only: cassette and judgement reads, no model."""
    import asyncio

    monkeypatch.setenv("SAPLING_EVAL_MODE", "replay")
    loop, confront = _eval_modules()
    for mod, slots in ((loop, list(lt.LOOP_TIER_SLOTS.values())), (confront, list(confront.CONFRONT_SLOTS))):
        monkeypatch.setattr(mod, "MODE", "replay")
        for slot in slots:
            run = mod._run_for(slot, False)
            for case in mod.CASES:
                reply = asyncio.run(run(case.inputs))  # stale or missing: raises
                assert reply.judgement is not None, f"{slot}/{case.name}"


def test_the_flag_is_server_side_off_first_and_names_its_recording():
    from services.feature_flags import REGISTRY

    from services.loop.flags import TUTOR_V2_FLAG

    fd = REGISTRY[TUTOR_V2_FLAG]
    assert TUTOR_V2_FLAG == "loop_tutor_v2"
    assert fd.variants == ("off", "on") and fd.client_visible is False
    assert "LOOP_EVAL_VARIANT=v2" in fd.description
    assert "recorded" in fd.description and "byte-identical" in fd.description


def test_the_flag_is_resolved_for_the_student_and_never_without_one(monkeypatch):

    asked = []
    setattr_loop(monkeypatch, "flag_on", lambda key, user: asked.append((key, user)) or True)
    assert services.loop.flags._tutor_v2_on("u1") is True
    assert services.loop.flags._tutor_v2_on(None) is False and services.loop.flags._tutor_v2_on("") is False
    assert asked == [("loop_tutor_v2", "u1")]


def test_a_turn_resolves_the_flag_once_and_off_sends_no_variant_args(gate_on, seams):
    seams.store["doc"] = _plan_state(open_question=True)
    agent, seen = _json_agent({**_TURN})

    with (
        patch_loop("loop_tutor_agent", agent),
        patch_loop("record_agent_usage", side_effect=lambda r, **k: r),
    ):
        r = client.post("/api/learn/loop/chat", json={"session_id": "s1", "user_id": "u1", "message": "x"})
    assert r.status_code == 200, r.text
    seams.v2.assert_called_once_with("u1")
    assert not {"output_type", "instructions", "metadata"} & set(seen["kw"])
    assert "[ANSWER CHECK]" not in seen["msg"]
    seams.v2.reset_mock(return_value=True)
    seams.v2.return_value = True
    with (
        patch_loop("loop_tutor_agent", agent),
        patch_loop("record_agent_usage", side_effect=lambda r, **k: r),
    ):
        r = client.post("/api/learn/loop/chat", json={"session_id": "s1", "user_id": "u1", "message": "x"})
    assert r.status_code == 200, r.text
    seams.v2.assert_called_once_with("u1")
    assert seen["kw"]["output_type"] is lt.LOOP_V2_OUTPUT
    assert seen["kw"]["instructions"] == lt.V2_INSTRUCTIONS
    assert seen["kw"]["metadata"] == {"prompt_version": V2_PROMPT_VERSION}


def test_a_continuation_finishes_the_turn_in_its_variant():
    from services.loop.continuation import continuation_plan

    on = {"deps": object(), "model": "m", "model_settings": {"tool_choice": "none"}, **lt.variant_run_args(True)}
    plan = continuation_plan(assembled="A", run_kwargs=on, messages=[])
    assert {k: plan.run_kwargs[k] for k in ("output_type", "instructions", "metadata")} == lt.variant_run_args(True)
    off = {"deps": object(), "model": "m", "model_settings": {}}
    assert not {"output_type", "instructions", "metadata"} & set(
        continuation_plan(assembled="A", run_kwargs=off, messages=[]).run_kwargs
    )


def _eval_modules():
    """tests/evals/loop_tutor.py and misconception_confront.py, loaded the way
    their own tests load them (they prepend tests/evals to sys.path)."""
    from tests.test_learning_misconceptions import _confront_eval
    from tests.test_loop_tutor_agent import _loop_eval_module

    return _loop_eval_module(), _confront_eval()


def test_the_flag_on_eval_records_into_its_own_namespace():
    """A flag-on recording can never land on, or pass for, a default one."""
    loop, confront = _eval_modules()
    assert loop.V2 is False, "the committed datasets are the flag-off contract"
    for slot in ("loop_tutor_lite", "loop_tutor", "loop_tutor_deep"):
        assert loop.variant_namespace(slot, False) == slot
        assert loop.variant_namespace(slot, True) == f"{slot}__v2"
        assert slot in loop.VARIANTS and f"{slot}__v2" not in loop.VARIANTS
    for slot in confront.CONFRONT_SLOTS:
        assert confront._cassette_dataset(slot, True) != confront._cassette_dataset(slot, False)
        assert confront.dataset_name(slot, True) == f"misconception_confront__{slot}__v2"
    # every variant recording differs in its prompt and schema hashes; a
    # feedback case's message differs too (the variant's feedback rule)
    assert loop.prompt_hash_for(True) == V2_PROMPT_VERSION != loop.prompt_hash_for(False)
    assert loop.schema_hash_for(True) != loop.schema_hash_for(False) == loop.OUTPUT_SCHEMA_HASH
    feedback = next(c for c in loop.CASES if c.inputs[0] == "feedback")
    assert loop.input_sha256("loop_tutor", feedback.inputs, True) != loop.input_sha256(
        "loop_tutor", feedback.inputs, False
    )
    # a v2 teach case carries the route's plan focus; its default message does not
    for mod, assembled in ((loop, loop._assembled), (confront, confront.assembled)):
        for teach in (c for c in mod.CASES if c.inputs[0] == "teach"):
            concept, reason = loop.V2_PLAN_FOCUS[teach.name]  # every teach case has one
            on, off = assembled(teach.inputs, True), assembled(teach.inputs, False)
            assert lt.plan_focus_line(reason) in on and lt.plan_focus_block(concept) in on
            assert "[PLAN FOCUS]" not in off and "plan_concept" not in off
    case = loop.CASES[0]
    from pathlib import Path

    body = loop.load_cassette("loop_tutor", case.name)
    assert body is not None
    rec = loop.LoopRecording.model_validate(body)
    loop.check_fresh(rec, "loop_tutor", case.inputs, False)  # the default recording is fresh
    with pytest.raises(loop.StaleRecordingError, match="system prompt"):
        loop.check_fresh(rec, "loop_tutor", case.inputs, True)  # never a flag-on one
    root = Path(__file__).parent / "evals" / "cassettes"
    assert not (root / "loop_tutor__v2").exists(), "recorded only by the owner"
