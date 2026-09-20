"""Shape-faithful stand-ins for a Pydantic AI `AgentRunResult`.

`SimpleNamespace(output="...")` was good enough while the routes only read
`.output`. It is not any more: `routes/learn.py` must distinguish "this run
produced text" from "`.output` resolved back into `message_history`" (a
textless model response makes `.output` hand back the PREVIOUS turn's
assistant message), and it does that by walking `result.new_messages()`.

A fake that only carries `.output` would make the routes raise AttributeError
on every turn while the tests still went green through the 502 catch-all —
the exact class of blind spot that let the replay bug ship. So the fake
carries both, and `textless_run_result` is the one shape that reproduces the
bug: a real `.output` string with no text part among this run's messages.
"""
from __future__ import annotations

from pydantic_ai.messages import ModelResponse, TextPart, ThinkingPart, ToolCallPart


class FakeRunResult:
    """Mirrors the two `AgentRunResult` members `routes/learn.py` reads.

    `new_messages()` returns only the messages produced by THIS run — that is
    the real contract (Pydantic AI 1.89.1: "Messages provided via
    `message_history` and messages from older runs are excluded"), and it is
    what makes the stale-output read detectable.
    """

    def __init__(self, output: str, new_messages: list):
        self.output = output
        self._new_messages = new_messages

    def new_messages(self, **_kwargs) -> list:
        return list(self._new_messages)


def run_result(output: str) -> FakeRunResult:
    """A normal turn: the model emitted `output` as its final text part."""
    return FakeRunResult(output, [ModelResponse(parts=[TextPart(content=output)])])


def textless_run_result(stale_output: str) -> FakeRunResult:
    """The replay shape: the model ended its turn after a tool call, emitting
    NO text part, so `.output` resolved out of `message_history` and carries
    a fully-formed reply from an EARLIER turn.

    Thinking parts and tool calls are included because that is what such a
    turn really contains — and because neither is output text, so neither may
    count as "this turn produced a reply".
    """
    return FakeRunResult(
        stale_output,
        [
            ModelResponse(
                parts=[
                    ThinkingPart(content="I should look at the graph first."),
                    ToolCallPart(tool_name="read_graph_neighborhood", args={}),
                ]
            )
        ],
    )
