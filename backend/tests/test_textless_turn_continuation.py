"""#646: finishing a turn the model abandoned after its tools ran.

These tests drive a REAL `pydantic_ai.Agent` against a `FunctionModel`, not
the hand-built event fakes in `test_chat_stream.py`. That is deliberate and
is the point of the file: every guarantee `_continuation_text` relies on is
pydantic-ai's, not Sapling's —

  * `.output` recovers text by walking the whole message list, INCLUDING the
    `message_history` passed in (the #562 stale-read hazard),
  * `new_messages()` excludes that history,
  * `all_messages()` carries the tool calls AND their results,
  * `override(tools=[], toolsets=[])` leaves the model no tools to call —
    and a run-level `toolsets=[]` does NOT (it adds rather than replaces,
    which is how the first draft of this fix silently kept every tool).

Fakes whose `.output` is pre-set pin Sapling's handling but would not notice
if any of the four changed under us. The local venv (1.89.1) and
requirements.lock (1.107.0) differ, so this is a live seam, not a hypothetical.
"""
from __future__ import annotations

import asyncio

import pytest
from pydantic_ai import Agent
from pydantic_ai.messages import (
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel

from agents.deps import SaplingDeps
from routes.learn import _continuation_text, _new_run_text

PRIOR_REPLY = "Gradient descent walks downhill along the steepest direction."
RESCUED_REPLY = "You moved from 0.3 to 0.5 on gradient descent — nice work."


def _deps() -> SaplingDeps:
    return SaplingDeps(
        user_id="u1", course_id="c1", supabase=None,
        request_id="r1", session_id="s1",
    )


def _history():
    """A prior exchange, so `.output` has something stale to recover."""
    from pydantic_ai.messages import ModelRequest, UserPromptPart

    return [
        ModelRequest(parts=[UserPromptPart(content="what is gradient descent?")]),
        ModelResponse(parts=[TextPart(content=PRIOR_REPLY)]),
    ]


class _Recorder:
    """Drives the two runs and records what each one was handed."""

    #: FunctionModel reads `__name__` off whatever it is given, which a
    #: callable INSTANCE does not have.
    __name__ = "textless_then_rescued"

    def __init__(self, rescue_text: str | None = RESCUED_REPLY):
        self.rescue_text = rescue_text
        self.tool_calls = 0
        self.tools_seen: list[list[str]] = []
        self.continuation_saw_tool_return = False

    def __call__(self, messages, info: AgentInfo) -> ModelResponse:
        self.tools_seen.append(sorted(t.name for t in info.function_tools))

        called = any(
            isinstance(p, ToolReturnPart)
            for m in messages
            for p in getattr(m, "parts", [])
        )
        # The continuation is the run with no tools available.
        if not info.function_tools:
            self.continuation_saw_tool_return = called
            if self.rescue_text is None:
                # The model declines a second time: an empty response, which
                # is exactly the shape that makes `.output` go stale again.
                return ModelResponse(parts=[])
            return ModelResponse(parts=[TextPart(content=self.rescue_text)])

        if not called:
            return ModelResponse(
                parts=[ToolCallPart(tool_name="record_mastery", args={"concept": "gd"})]
            )
        # Tools have run; end the turn saying NOTHING. This is the ~25-40%
        # Flash-Lite shape the whole issue is about.
        return ModelResponse(parts=[])


def _agent(recorder: _Recorder, deps: SaplingDeps) -> Agent:
    agent = Agent(
        FunctionModel(recorder),
        deps_type=SaplingDeps,
        output_type=str,
        system_prompt="tutor",
    )

    @agent.tool_plain
    def record_mastery(concept: str) -> str:
        """Stand-in for update_mastery_tool: it WRITES."""
        recorder.tool_calls += 1
        deps.mastery_changes.append(
            {"concept": concept, "before": 0.3, "after": 0.5}
        )
        return "mastery recorded"

    return agent


def _textless_run(recorder: _Recorder, deps: SaplingDeps):
    agent = _agent(recorder, deps)
    run_kwargs = {"deps": deps, "message_history": _history()}
    result = asyncio.run(agent.run("and how do I pick a step size?", **run_kwargs))
    return agent, result, run_kwargs


def test_the_stale_read_this_fix_rests_on_is_real():
    """Guard on the premise: a textless run's `.output` really does come back
    as the PREVIOUS turn's reply, while `_new_run_text` sees nothing.

    If pydantic-ai ever stops recovering from history, this test fails and
    the continuation rung can be reconsidered — rather than silently
    becoming dead code nobody re-examines."""
    deps = _deps()
    recorder = _Recorder()
    _, result, _ = _textless_run(recorder, deps)

    assert result.output == PRIOR_REPLY, (
        "the library no longer recovers text from message_history — "
        "re-read #562 and #646 before changing the rungs"
    )
    assert _new_run_text(result) == "", "this run produced no text of its own"
    assert recorder.tool_calls == 1
    assert len(deps.mastery_changes) == 1


def test_continuation_returns_this_runs_text_not_the_stale_reply():
    deps = _deps()
    recorder = _Recorder()
    agent, result, run_kwargs = _textless_run(recorder, deps)

    rescued = asyncio.run(_continuation_text(agent, result, run_kwargs))

    assert rescued == RESCUED_REPLY
    assert PRIOR_REPLY not in rescued


def test_continuation_runs_with_no_tools_so_it_cannot_write_again():
    """The guarantee that makes this safe after the writes-guard.

    A continuation that kept its toolset could call the mastery tool a second
    time — the very double-apply #470's guard exists to prevent, reintroduced
    under a different name. `override(tools=[], toolsets=[])` makes it
    structural.

    This assertion is not theoretical: the first implementation used a
    run-level `toolsets=[]`, which ADDS to the agent's tools instead of
    replacing them, and this test is what caught it."""
    deps = _deps()
    recorder = _Recorder()
    agent, result, run_kwargs = _textless_run(recorder, deps)

    asyncio.run(_continuation_text(agent, result, run_kwargs))

    assert recorder.tools_seen[-1] == [], (
        "the continuation was handed tools; it can re-execute a write"
    )
    assert recorder.tool_calls == 1, "the tool ran exactly once across both runs"
    assert len(deps.mastery_changes) == 1, "mastery moved once for one student turn"


def test_continuation_sees_the_tool_results_so_it_need_not_re_run_them():
    """`all_messages()` carries the ToolReturnParts — that is WHY dropping
    the toolset is not a lobotomy: the answer is already in the context."""
    deps = _deps()
    recorder = _Recorder()
    agent, result, run_kwargs = _textless_run(recorder, deps)

    asyncio.run(_continuation_text(agent, result, run_kwargs))

    assert recorder.continuation_saw_tool_return, (
        "the continuation was not given the tool results from the first run"
    )


def test_a_continuation_that_also_says_nothing_returns_none():
    """The caller must be able to tell 'rescued' from 'still textless'. The
    continuation is itself history-bearing, so a naive `.output` read here
    would hand back PRIOR_REPLY and persist a duplicate — the #562 bug,
    reintroduced one layer down."""
    deps = _deps()
    recorder = _Recorder(rescue_text=None)
    agent, result, run_kwargs = _textless_run(recorder, deps)

    rescued = asyncio.run(_continuation_text(agent, result, run_kwargs))

    assert rescued is None, (
        "a textless continuation must be None, not the recovered history"
    )


def test_continuation_does_not_forward_unexpected_run_kwargs():
    """`message_history` is REPLACED, not merged; anything outside the
    allow-list is dropped rather than forwarded blind into the second run."""
    deps = _deps()
    recorder = _Recorder()
    agent, result, run_kwargs = _textless_run(recorder, deps)
    run_kwargs["usage_limits"] = object()  # not a valid limits object

    rescued = asyncio.run(_continuation_text(agent, result, run_kwargs))

    assert rescued == RESCUED_REPLY


@pytest.mark.parametrize("text", ["   ", "\n\n"])
def test_whitespace_only_continuation_is_not_a_rescue(text):
    deps = _deps()
    recorder = _Recorder(rescue_text=text)
    agent, result, run_kwargs = _textless_run(recorder, deps)

    assert asyncio.run(_continuation_text(agent, result, run_kwargs)) is None


def test_stripping_tools_does_not_clobber_an_outer_model_override():
    """`_continuation_text` opens its own `agent.override(...)`. Both the E2E
    function-mode seam and the agent tests run inside an OUTER
    `override(model=...)`, so if the inner one reset the model the
    continuation would dial a live provider from a hermetic lane.

    Pins the composition: inner strips the tools, outer keeps the model."""
    deps = _deps()
    recorder = _Recorder()
    agent = _agent(recorder, deps)

    outer_calls: list[list[str]] = []

    def outer_model(messages, info: AgentInfo) -> ModelResponse:
        outer_calls.append(sorted(t.name for t in info.function_tools))
        if not info.function_tools:
            return ModelResponse(parts=[TextPart(content=RESCUED_REPLY)])
        called = any(
            isinstance(p, ToolReturnPart)
            for m in messages
            for p in getattr(m, "parts", [])
        )
        if not called:
            return ModelResponse(
                parts=[ToolCallPart(tool_name="record_mastery", args={"concept": "gd"})]
            )
        return ModelResponse(parts=[])

    outer_model.__name__ = "outer_model"

    with agent.override(model=FunctionModel(outer_model)):
        run_kwargs = {"deps": deps, "message_history": _history()}
        result = asyncio.run(agent.run("step size?", **run_kwargs))
        rescued = asyncio.run(_continuation_text(agent, result, run_kwargs))

    assert rescued == RESCUED_REPLY, (
        "the continuation did not reach the overridden model"
    )
    assert recorder.tools_seen == [], "the inner agent's model was used at all"
    assert outer_calls[-1] == [], "the inner override failed to strip tools"
