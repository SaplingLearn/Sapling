"""Spec §13 A138 / A139: with `segment_prequestion` and
`self_explanation_prompts` OFF — the default — the loop is byte-identical to
f9eca612 (the wave-4 base, before either existed).

Each scenario below drives one loop route through the route seams of
tests/test_learn_loop_routes.py with a fixed nonce and fixed ids, and digests
everything the route produced: the tutor REQUEST (the assembled user message —
phase prefix, context blocks, envelope — and every run argument the agent got,
so the system prompt, history, output schema and variant), the SERVED text and
the whole JSON response, the transcript rows it saved and the loop-state
document it left. The digests were captured from f9eca612 by running this
same module in a `git archive` export of that commit (its seams have no flag
patches: the functions did not exist). Change them only with the change
recorded in the spec.

The scenarios are the turns A138 and A139 change when ON: a teach turn at a
segment start (the prequestion's explaining turn), a teach turn that poses a
check, an H4 hint (the worked-example juncture), a feedback turn after a first
unhelped correct answer that ends the segment (the first_correct juncture and
the next segment's prequestion), a released feedback turn (the solution
juncture), the plan approval (the first segment's prequestion), the status
read and "Check me".
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from unittest.mock import patch

import pytest

from tests import test_learn_loop_routes as _routes
from tests.test_learn_loop_routes import ITEM, _graded, _json_agent, _plan_state, _state, client
from tests.split_patches import patch_loop

gate_on, no_rate_limit, seams = _routes.gate_on, _routes.no_rate_limit, _routes.seams

_NONCE = "0" * 24
_UUID = uuid.UUID("12345678-1234-5678-1234-567812345678")

#: f9eca612, captured with this module (see the docstring).
#: hint_h4, feedback_first_correct_ends_segment and feedback_released were
#: re-captured for #866 Z07: the check item's text now reaches the tutor inside
#: the untrusted-content envelope (agents/loop_tutor.py), with either flag. The
#: three requests differ from f9eca612 by exactly those three envelope lines.
#: All five model-run scenarios were re-captured again for 877d968b (the Alvar
#: teach pedagogy, docs/learning-loop/alvar-trilogy-implementation-plan.md): the
#: loop's own teach wording changed, independent of both flags. The teach phase
#: rule and the developing band format line are the only other differences.
F9ECA612 = {
    "teach_chat": "cc30f866d54e51ddfd9255feb86c821cfd32f264e454293ca725b8aa1fa5977d",
    "teach_chat_poses_check": "333cc4672ed548cc58d7af4323ada5729de4fee823f4e15f12b4fd3e7a828e85",
    "hint_h4": "375ce264bc8af7e3c629b35c2a250c74a06ebc99a72bec06bce89ade08877d1c",
    "feedback_first_correct_ends_segment": "0c33be0c5fb957d07abbd5bc49afe115e994ac6a4fb9896aed262806ee943c49",
    "feedback_released": "a7f7e5b1646d72c1b5318ca63a66594033ff18d55f1ba51be2e59e719ef9f0e7",
    "plan_approve": "44a84b5ad5b1d9597e2f0eafe636b7d67315a6ee0ea995abe210f135e6448521",
    "status": "2c1e614faaeddec44561d80d2e8b59df9219f51790cd1cde81865fff0813c1b2",
    "check_next": "311f203195565a1f7763b80af61f459c060e3e136b37e2764868bacedef8fcb8",
}
#: The scenarios that run the tutor model: their request is part of the digest.
_MODEL_RUNS = frozenset(
    {"teach_chat", "teach_chat_poses_check", "hint_h4", "feedback_first_correct_ends_segment", "feedback_released"}
)


def _digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _run_kwargs(kw: dict) -> dict:
    """The run arguments as the model's request depends on them."""
    out = {}
    for key, value in sorted(kw.items()):
        if key == "deps":
            out[key] = {
                "loop_turn": repr(getattr(value, "loop_turn", None)),
                "feature": getattr(value, "feature", None),
            }
        elif key == "message_history":
            out[key] = [repr(m) for m in value]
        elif key == "usage_limits":
            out[key] = repr(value)
        else:
            out[key] = repr(value)
    return out


def _capture(seams, run) -> dict:
    agent, seen = _json_agent()
    with (
        patch_loop("loop_tutor_agent", agent),
        patch_loop("record_agent_usage", side_effect=lambda r, **k: r),
        patch_loop("new_nonce", return_value=_NONCE),
        patch('uuid.uuid4', return_value=_UUID),
    ):
        r = run()
    return {
        "status": r.status_code,
        "body": r.json(),
        "message": seen.get("msg"),
        "kwargs": _run_kwargs(seen.get("kw") or {}),
        # B4 (#866) passes `message_id` on every loop save; None is save_message's
        # default (the plain insert f9eca612 made), so it is left out of the
        # digest — a turn-derived id would still change it.
        "saved": [
            list(c.args) + [sorted((k, v) for k, v in c.kwargs.items() if not (k == "message_id" and v is None))]
            for c in seams.save_msg.call_args_list
        ],
        "doc": seams.store["doc"],
    }


def _post(path: str, body: dict):
    return lambda: client.post(f"/api/learn/loop{path}", json=body)


_CHAT = {"session_id": "s1", "user_id": "u1"}


def _scenario(name: str, seams) -> dict:
    seams.list_items.return_value = [ITEM]
    if name == "teach_chat":
        seams.store["doc"] = _plan_state()
        return _capture(seams, _post("/chat", {**_CHAT, "message": "Teach me about recursion."}))
    if name == "teach_chat_poses_check":
        seams.store["doc"] = _plan_state(teach_turns=1)
        return _capture(seams, _post("/chat", {**_CHAT, "message": "What next?"}))
    if name == "hint_h4":
        st = _plan_state()
        st.update(_state(rung=4))
        seams.store["doc"] = st
        return _capture(seams, _post("/action", {**_CHAT, "action_type": "hint"}))
    if name == "feedback_first_correct_ends_segment":
        st = _plan_state(concept_checks=1)
        st.update(_graded("correct"))
        st["steps"]["qh-1"].update(max_rung=0, assisted=False)  # no help: unhelped
        seams.store["doc"] = st
        return _capture(seams, _post("/chat", {**_CHAT, "message": "ok"}))
    if name == "feedback_released":
        st = _plan_state()
        st.update(_graded("not_yet"))
        seams.store["doc"] = st
        return _capture(seams, _post("/chat", {**_CHAT, "message": "ok"}))
    if name == "plan_approve":
        seams.store["doc"] = {
            "phase": "plan",
            "plan": {"proposed": ["node-1", "node-2"], "proposed_kinds": {"node-1": "new", "node-2": "new"}},
        }
        with patch_loop("store_brief"):
            return _capture(seams, _post("/plan/approve", {**_CHAT, "concept_ids": ["node-1", "node-2"]}))
    if name == "status":
        seams.store["doc"] = _plan_state()
        return _capture(seams, lambda: client.get("/api/learn/loop/status?user_id=u1&session_id=s1"))
    if name == "check_next":
        seams.store["doc"] = _plan_state(teach_turns=1)
        return _capture(seams, _post("/check/next", _CHAT))
    raise ValueError(name)


@pytest.mark.parametrize("name", sorted(F9ECA612))
def test_flag_off_every_scenario_is_byte_identical_to_f9eca612(name, gate_on, seams):
    captured = _scenario(name, seams)
    assert captured["status"] == 200, captured["body"]
    assert (captured["message"] is not None) == (name in _MODEL_RUNS), "the request is digested"
    if name == "status":
        # 2c607ca0 (Tutor V2) added `approved_plan` to /status so the session
        # panel lists the plan after a reload. It does not depend on either
        # flag, so it is checked here and left out of the f9eca612 digest,
        # which stays the one captured from that commit.
        assert captured["body"].pop("approved_plan") == {
            "concepts": [
                {"node_id": "node-1", "concept_name": "", "kind": "new"},
                {"node_id": "node-2", "concept_name": "", "kind": "new"},
            ],
            "cursor": 0,
        }
    if name == "feedback_first_correct_ends_segment":
        # #866 K08: a turn that moves the plan's cursor says where it is now, so
        # the Tutor's current concept follows it. Like `approved_plan` on
        # /status it does not depend on either flag: checked here, left out of
        # the f9eca612 digest.
        assert captured["body"].pop("approved_plan") == {
            "concepts": [
                {"node_id": "node-1", "concept_name": "", "kind": "new"},
                {"node_id": "node-2", "concept_name": "", "kind": "new"},
            ],
            "cursor": 1,
        }
    # #866 K07 / K52 add flag-independent fields too: a correct check answer's
    # `credit` (+ `credit_reasons`, and the step's `credit_weight` /
    # `credit_factors`) and `measured: false` on a concept with no stored
    # state. No scenario here grades a check through /check/answer or turns on
    # an unmeasured concept, so none reaches the f9eca612 digest; this keeps
    # a re-capture from baking one in unnoticed (pop and check it above first).
    flat = json.dumps(captured, default=str)
    for key in ("credit", "credit_reasons", "credit_weight", "credit_factors", "measured"):
        assert f'"{key}"' not in flat, (name, key)
    digest = _digest(captured)
    if os.environ.get("TEACH_PROMPTS_CAPTURE"):
        print(f"\nCAPTURE {name} {digest}")
        return
    assert digest == F9ECA612[name], (name, json.dumps(captured, default=str)[:4000])
