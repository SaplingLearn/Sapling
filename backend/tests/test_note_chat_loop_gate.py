"""#866 Z26: the notes assistant's ACADEMIC INTEGRITY rule rides only a
learning-loop student's run.

Spec §13 A125 (g) gives `note_chat` an integrity rule as defence in depth for
the route's guard; (i) says the guard is part of the loop, so with the loop off
"§11.6 restores the pre-loop app". The rule used to sit in the agent's static
system prompt, so every student got it: with the loop off (the default) a
student asking for help with homework written in a note was told to refuse and
to open "that question's card in their learning session", which they do not
have. The rule is now per-run instructions, sent when the route's gate is on.
"""

from __future__ import annotations

import hashlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from pydantic_ai.messages import ModelRequest, ModelResponse, SystemPromptPart, TextPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from agents import note_chat
from agents.deps import SaplingDeps
from main import app
from tests.test_notes_routes import fake_get_note

client = TestClient(app)

#: `agents/note_chat.py::_PROMPT_HASH` on origin/main (07482f33), the pre-loop
#: app: a loop-off run must send exactly that system prompt.
PRE_LOOP_PROMPT_VERSION = "816c32506f40"


def _deps() -> SaplingDeps:
    return SaplingDeps(user_id="u1", course_id="c1", supabase=None, request_id="r", session_id="n1")


def test_the_system_prompt_is_the_pre_loop_prompt():
    assert "ACADEMIC INTEGRITY" not in note_chat._PROMPT
    assert note_chat._PROMPT_HASH == PRE_LOOP_PROMPT_VERSION
    assert hashlib.sha256(note_chat._PROMPT.encode()).hexdigest()[:12] == PRE_LOOP_PROMPT_VERSION


def test_the_integrity_rule_is_a_loop_run_argument():
    assert note_chat.integrity_run_args(False) == {}
    on = note_chat.integrity_run_args(True)
    assert set(on) == {"instructions", "metadata"}
    rule = on["instructions"]
    assert rule.startswith("ACADEMIC INTEGRITY (non-negotiable)")
    assert "learning session" in rule and "one step at a time" in rule
    # its own prompt version, so a loop run's llm_usage row says which prompt ran
    assert on["metadata"]["prompt_version"] != PRE_LOOP_PROMPT_VERSION


@pytest.mark.parametrize("loop_on", [False, True])
def test_the_model_sees_the_rule_only_on_a_loop_run(loop_on):
    """Through the real agent: the system prompt is the same either way, and
    the rule arrives as the run's instructions only with the loop on."""
    seen: dict = {}

    def model(messages, info: AgentInfo) -> ModelResponse:
        request = messages[0]
        assert isinstance(request, ModelRequest)
        seen["system"] = [p.content for p in request.parts if isinstance(p, SystemPromptPart)]
        seen["instructions"] = request.instructions
        return ModelResponse(parts=[TextPart(content="ok")])

    result = note_chat.note_chat_agent.run_sync(
        "Can you help me with question 3 of my homework?",
        deps=_deps(),
        model=FunctionModel(model),
        **note_chat.integrity_run_args(loop_on),
    )
    assert result.output == "ok"
    assert seen["system"] == [note_chat._PROMPT]
    if loop_on:
        assert seen["instructions"] == note_chat.INTEGRITY_INSTRUCTIONS
    else:
        assert not seen["instructions"]


@pytest.mark.parametrize("loop_on", [False, True])
def test_the_route_passes_the_rule_only_when_the_loop_is_on(loop_on):
    run = AsyncMock(return_value=SimpleNamespace(output="Here is a hint."))
    with (
        patch("routes.notes.learning_loop_for_request", return_value=loop_on) as gate,
        patch("routes.notes.note_chat_agent.run", run),
        patch("routes.notes.offering_course_id", return_value="c1"),
        patch("routes.notes.get_note", side_effect=fake_get_note(body="Homework 3: prove it.")),
        patch("services.loop.posed.posed_items", return_value=([], None)),
    ):
        r = client.post("/api/notes/n1/chat", json={"user_id": "u1", "message": "Help with question 3?"})
    assert r.status_code == 200, r.text
    assert r.json() == {"reply": "Here is a hint.", "degraded": False}
    gate.assert_called_once_with("u1")  # read once: the guard and the run share it
    kwargs = run.await_args.kwargs
    if loop_on:
        assert kwargs["instructions"] == note_chat.INTEGRITY_INSTRUCTIONS
    else:
        assert "instructions" not in kwargs and "metadata" not in kwargs
