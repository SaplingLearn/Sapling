"""Unit tests for services/chat_stream.py against a fake event stream.

No live LLM: FakeAgent yields stand-ins whose CLASS NAMES and attribute
shapes match Pydantic AI 1.89.1 (verified by inspection), which is all
stream_agent_turn dispatches on.
"""
import asyncio

from agents.deps import SaplingDeps
from services.chat_stream import merge_graph_updates, stream_agent_turn


# ── Fakes mirroring pydantic_ai event shapes ──────────────────────────────

class TextPartDelta:
    def __init__(self, content_delta):
        self.content_delta = content_delta


class PartDeltaEvent:
    def __init__(self, content_delta):
        self.delta = TextPartDelta(content_delta)


class _TextPart:
    def __init__(self, content):
        self.content = content


class PartStartEvent:
    """First text chunk arrives here — NOT as a delta."""
    def __init__(self, content):
        self.part = _TextPart(content)


class PartEndEvent:
    """Carries the FULL assembled text on the same `.part.content`
    attribute PartStartEvent uses. Must NOT produce a token."""
    def __init__(self, content):
        self.part = _TextPart(content)


class _ToolPart:
    def __init__(self, tool_name):
        self.tool_name = tool_name


class FunctionToolCallEvent:
    def __init__(self, tool_name):
        self.part = _ToolPart(tool_name)


class FunctionToolResultEvent:
    def __init__(self, on_fire=None):
        # Simulates the tool having written to deps during its execution.
        if on_fire:
            on_fire()


class _Result:
    def __init__(self, output):
        self.output = output


class AgentRunResultEvent:
    def __init__(self, output):
        self.result = _Result(output)


class FakeAgent:
    def __init__(self, events, raise_after=None):
        self._events = events
        self._raise_after = raise_after

    async def run_stream_events(self, user_message, **kwargs):
        for i, ev in enumerate(self._events):
            if self._raise_after is not None and i == self._raise_after:
                raise RuntimeError("model blew up")
            yield ev


def make_deps():
    return SaplingDeps(
        user_id="u1", course_id="c1", supabase=None,
        request_id="r1", session_id="s1",
    )


async def collect(agent, deps, on_complete, legacy_fallback=None):
    events = []
    async for ev in stream_agent_turn(
        agent=agent, user_message="hi", run_kwargs={}, deps=deps,
        on_complete=on_complete, legacy_fallback=legacy_fallback,
        request_id="r1",
    ):
        events.append(ev)
    return events


# ── merge ─────────────────────────────────────────────────────────────────

def test_merge_concatenates_and_never_clobbers():
    merged = merge_graph_updates(
        [{"new_nodes": [{"n": 1}]}, {"new_nodes": [{"n": 2}]}, {"updated_nodes": [{"n": 3}]}]
    )
    assert merged == {"new_nodes": [{"n": 1}, {"n": 2}], "updated_nodes": [{"n": 3}]}


# ── happy path ────────────────────────────────────────────────────────────

def test_first_chunk_from_part_start_is_not_dropped():
    """PartStartEvent carries the reply's FIRST chunk. Regression: handling
    only PartDeltaEvent silently truncates the opening."""
    async def run():
        agent = FakeAgent([
            PartStartEvent("Hello "),
            PartDeltaEvent("world"),
            AgentRunResultEvent("Hello world"),
        ])
        saved = {}
        events = await collect(agent, make_deps(), lambda r, g, m: saved.update(reply=r) or {})
        tokens = [e.data["delta"] for e in events if e.type == "token"]
        assert tokens == ["Hello ", "world"]
        assert saved["reply"] == "Hello world"

    asyncio.run(run())


def test_part_end_event_does_not_duplicate_the_reply():
    """PartEndEvent carries the FULL assembled text on .part.content — the
    same attribute PartStartEvent uses for the FIRST chunk. Emitting a token
    for it duplicates the whole reply in the user's bubble.

    Regression: a duck-typed `getattr(event.part, 'content')` reader turns
    "hello world" into "hello worldhello world". Observed live in Task 1's
    spike."""
    async def run():
        agent = FakeAgent([
            PartStartEvent("hello "),
            PartDeltaEvent("world"),
            PartEndEvent("hello world"),      # full text — must be ignored
            AgentRunResultEvent("hello world"),
        ])
        events = await collect(agent, make_deps(), lambda r, g, m: {})
        tokens = [e.data["delta"] for e in events if e.type == "token"]
        assert tokens == ["hello ", "world"], "PartEndEvent must not re-emit the reply"
        assert "".join(tokens) == "hello world"

    asyncio.run(run())


def test_event_order_and_single_persistence():
    async def run():
        agent = FakeAgent([
            PartStartEvent("Hi"),
            AgentRunResultEvent("Hi"),
        ])
        calls = []
        events = await collect(agent, make_deps(), lambda r, g, m: calls.append(r) or {"extra": 1})
        assert [e.type for e in events] == ["status", "token", "done"]
        assert calls == ["Hi"], "on_complete must fire exactly once"
        done = events[-1]
        assert done.data["reply"] == "Hi"
        assert done.data["extra"] == 1, "on_complete's return merges into done"

    asyncio.run(run())


def test_graph_update_emitted_once_per_new_write():
    """High-water mark: an already-emitted delta must not re-emit on the
    next tool result."""
    async def run():
        deps = make_deps()

        def first_write():
            deps.graph_updates.append({"new_nodes": [{"name": "Eigenvalues"}]})
            deps.mastery_changes.append({"concept": "Eigenvalues", "before": 0.1, "after": 0.6})

        agent = FakeAgent([
            FunctionToolCallEvent("update_mastery_tool"),
            FunctionToolResultEvent(on_fire=first_write),
            PartStartEvent("Done."),
            FunctionToolCallEvent("search_course_materials_tool"),
            FunctionToolResultEvent(),          # writes nothing new
            AgentRunResultEvent("Done."),
        ])
        events = await collect(agent, deps, lambda r, g, m: {})
        graph_events = [e for e in events if e.type == "graph_update"]
        assert len(graph_events) == 1, "second tool result added nothing — must not re-emit"
        assert graph_events[0].data["nodes"] == {"new_nodes": [{"name": "Eigenvalues"}]}
        assert graph_events[0].data["mastery_changes"][0]["after"] == 0.6
        assert [e.type for e in events].index("graph_update") < [e.type for e in events].index("done")

    asyncio.run(run())


# ── failure rungs ─────────────────────────────────────────────────────────

def test_rung1_failure_before_any_token_uses_legacy_and_skips_on_complete():
    async def run():
        agent = FakeAgent([PartStartEvent("x")], raise_after=0)
        on_complete_calls = []

        async def fake_legacy():
            # async because the real routes' legacy paths are (_legacy_chat)
            return {"reply": "legacy reply", "graph_update": {}, "mastery_changes": []}

        events = await collect(
            agent, make_deps(),
            on_complete=lambda r, g, m: on_complete_calls.append(r),
            legacy_fallback=fake_legacy,
        )
        assert [e.type for e in events] == ["status", "token", "done"]
        assert events[1].data["delta"] == "legacy reply"
        assert events[-1].data["reply"] == "legacy reply"
        assert on_complete_calls == [], "legacy owns persistence — on_complete must NOT run"

    asyncio.run(run())


def test_rung2_failure_after_tokens_errors_and_persists_nothing():
    async def run():
        agent = FakeAgent([PartStartEvent("Half a th"), PartDeltaEvent("ought")], raise_after=1)
        on_complete_calls = []
        legacy_calls = []

        async def fake_legacy():
            legacy_calls.append(1)
            return {"reply": "nope"}

        events = await collect(
            agent, make_deps(),
            on_complete=lambda r, g, m: on_complete_calls.append(r),
            legacy_fallback=fake_legacy,
        )
        assert events[-1].type == "error"
        assert events[-1].data["request_id"] == "r1"
        assert on_complete_calls == [], "nothing may persist after a mid-stream failure"
        assert legacy_calls == [], "never silently re-run once text was shown"

    asyncio.run(run())


def test_cancel_mid_stream_persists_nothing():
    """Client disconnect cancels the generator at its current yield."""
    async def run():
        agent = FakeAgent([PartStartEvent("a"), PartDeltaEvent("b"), AgentRunResultEvent("ab")])
        on_complete_calls = []
        gen = stream_agent_turn(
            agent=agent, user_message="hi", run_kwargs={}, deps=make_deps(),
            on_complete=lambda r, g, m: on_complete_calls.append(r), request_id="r1",
        )
        await gen.__anext__()   # status
        await gen.__anext__()   # first token
        await gen.aclose()      # disconnect
        assert on_complete_calls == [], "a partial reply must never persist"

    asyncio.run(run())
