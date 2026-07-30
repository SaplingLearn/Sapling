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
        self.part_delta_kind = "text"


class ThinkingPartDelta:
    """Mirrors pydantic_ai.messages.ThinkingPartDelta: same attribute name
    (`content_delta`) as TextPartDelta, discriminated only by
    `part_delta_kind`. Must never surface as a `token` event."""
    def __init__(self, content_delta):
        self.content_delta = content_delta
        self.part_delta_kind = "thinking"


class PartDeltaEvent:
    def __init__(self, content_delta, part_delta_kind="text"):
        self.delta = (
            ThinkingPartDelta(content_delta)
            if part_delta_kind == "thinking"
            else TextPartDelta(content_delta)
        )


class _TextPart:
    def __init__(self, content):
        self.content = content
        self.part_kind = "text"


class _ThinkingPart:
    """Mirrors pydantic_ai.messages.ThinkingPart: same attribute name
    (`content`) as TextPart, discriminated only by `part_kind`. Must never
    surface as a `token` event."""
    def __init__(self, content):
        self.content = content
        self.part_kind = "thinking"


class PartStartEvent:
    """First text chunk arrives here — NOT as a delta."""
    def __init__(self, content, part_kind="text"):
        self.part = _ThinkingPart(content) if part_kind == "thinking" else _TextPart(content)


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


async def collect(agent, deps, on_complete, legacy_fallback=None, on_usage=None):
    events = []
    async for ev in stream_agent_turn(
        agent=agent, user_message="hi", run_kwargs={}, deps=deps,
        on_complete=on_complete, legacy_fallback=legacy_fallback,
        on_usage=on_usage, request_id="r1",
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


def test_thinking_part_never_produces_a_token():
    """`_text_from` dispatches on event CLASS, but PartStartEvent/
    PartDeltaEvent wrap ANY part kind — a ThinkingPart/ThinkingPartDelta
    rides the identical `.part.content` / `.delta.content_delta`
    attributes a TextPart/TextPartDelta uses. Without gating on
    part_kind/part_delta_kind, reasoning content would stream into the
    student's chat bubble the moment thought summaries are enabled
    (latent today only because _build_pro_model_settings doesn't set
    include_thoughts). Text-shaped parts in the same run must still
    produce tokens normally."""
    async def run():
        agent = FakeAgent([
            PartStartEvent("Let me reason about this privately...", part_kind="thinking"),
            PartDeltaEvent(" and some more private reasoning.", part_delta_kind="thinking"),
            PartStartEvent("The answer is "),
            PartDeltaEvent("42."),
            AgentRunResultEvent("The answer is 42."),
        ])
        events = await collect(agent, make_deps(), lambda r, g, m: {})
        tokens = [e.data["delta"] for e in events if e.type == "token"]
        assert tokens == ["The answer is ", "42."], (
            "thinking-shaped parts must never be emitted as tokens, "
            "and text-shaped parts in the same run must still stream"
        )

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
            FunctionToolCallEvent("search_course_materials"),
            FunctionToolResultEvent(),          # writes nothing new
            # #149 read-only graph tool: its result event must not emit a
            # graph_update either — reads never touch deps.graph_updates/
            # mastery_changes, so there is nothing new past the high-water
            # mark.
            FunctionToolCallEvent("read_graph_neighborhood"),
            FunctionToolResultEvent(),          # read-only — writes nothing
            AgentRunResultEvent("Done."),
        ])
        events = await collect(agent, deps, lambda r, g, m: {})
        graph_events = [e for e in events if e.type == "graph_update"]
        assert len(graph_events) == 1, (
            "later tool results (incl. the read-only graph tool) added "
            "nothing — must not re-emit"
        )
        assert graph_events[0].data["nodes"] == {"new_nodes": [{"name": "Eigenvalues"}]}
        assert graph_events[0].data["mastery_changes"][0]["after"] == 0.6
        assert [e.type for e in events].index("graph_update") < [e.type for e in events].index("done")
        # The read tool still surfaces as a progress event for the UI.
        assert any(
            e.type == "progress" and e.step == "read_graph_neighborhood"
            for e in events
        )

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


def test_on_complete_raising_yields_error_not_unhandled_exception():
    """Persistence failing AFTER the reply fully streamed must surface as a
    structured `error` event (ADR-0020 interrupted-turn treatment), never an
    unhandled exception — sse_starlette has already flushed headers by then,
    so a propagated exception aborts the response with no closing event at
    all and the client sees an unstructured network failure."""
    async def run():
        agent = FakeAgent(
            [PartStartEvent("hi"), AgentRunResultEvent("hi")]
        )
        legacy_calls = []

        def failing_persist(reply, graph_update, mastery_changes):
            raise RuntimeError("db write failed")

        async def fake_legacy():
            legacy_calls.append(1)
            return {"reply": "nope"}

        events = await collect(
            agent, make_deps(),
            on_complete=failing_persist,
            legacy_fallback=fake_legacy,
        )
        assert events[-1].type == "error"
        assert events[-1].data["request_id"] == "r1"
        assert all(e.type != "done" for e in events), "no done after failed persistence"
        assert legacy_calls == [], "reply already streamed — never re-run legacy"

    asyncio.run(run())


# ── on_usage hook (#118) ──────────────────────────────────────────────────

def test_on_usage_called_once_with_run_result_before_done():
    """The success path hands the final AgentRunResult to on_usage exactly
    once — the seam the routes use to record streamed-tutor token usage."""
    async def run():
        agent = FakeAgent([
            PartStartEvent("Hi"),
            AgentRunResultEvent("Hi"),
        ])
        usage_calls = []
        events = await collect(
            agent, make_deps(), lambda r, g, m: {},
            on_usage=lambda res: usage_calls.append(res),
        )
        assert len(usage_calls) == 1, "on_usage must fire exactly once"
        assert usage_calls[0].output == "Hi", "hook receives the run result itself"
        assert events[-1].type == "done"

    asyncio.run(run())


def test_on_usage_failure_never_breaks_the_stream():
    """Instrumentation must not turn a fully-streamed reply into an error:
    a raising on_usage is swallowed and the turn still persists + dones."""
    async def run():
        agent = FakeAgent([
            PartStartEvent("Hi"),
            AgentRunResultEvent("Hi"),
        ])
        persisted = []

        def bad_usage(res):
            raise RuntimeError("usage capture blew up")

        events = await collect(
            agent, make_deps(), lambda r, g, m: persisted.append(r) or {},
            on_usage=bad_usage,
        )
        assert persisted == ["Hi"], "persistence still runs after a usage slip"
        assert events[-1].type == "done"

    asyncio.run(run())


def test_on_usage_not_called_on_error_rungs_or_legacy_fallback():
    """No result event was seen on Rung 1/2, and the legacy fallback's usage
    is captured inside call_gemini_multiturn — the hook must stay silent."""
    async def run():
        usage_calls = []

        async def fake_legacy():
            return {"reply": "legacy"}

        # Rung 1: failure before any token → legacy fallback.
        events = await collect(
            FakeAgent([AgentRunResultEvent("x")], raise_after=0),
            make_deps(), lambda r, g, m: {},
            legacy_fallback=fake_legacy,
            on_usage=lambda res: usage_calls.append(res),
        )
        assert events[-1].type == "done" and events[-1].data["reply"] == "legacy"
        assert usage_calls == [], "legacy fallback must not trigger on_usage"

        # Rung 2: failure after tokens streamed → terminal error.
        events = await collect(
            FakeAgent([PartStartEvent("Hi"), AgentRunResultEvent("x")], raise_after=1),
            make_deps(), lambda r, g, m: {},
            on_usage=lambda res: usage_calls.append(res),
        )
        assert events[-1].type == "error"
        assert usage_calls == [], "an aborted run has no result to record"

    asyncio.run(run())
