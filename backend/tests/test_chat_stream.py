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


async def collect(agent, deps, on_complete, nonstream_fallback=None, on_usage=None):
    events = []
    async for ev in stream_agent_turn(
        agent=agent, user_message="hi", run_kwargs={}, deps=deps,
        on_complete=on_complete, nonstream_fallback=nonstream_fallback,
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

def test_rung1_failure_before_any_token_uses_nonstream_fallback_and_skips_on_complete():
    async def run():
        agent = FakeAgent([PartStartEvent("x")], raise_after=0)
        on_complete_calls = []

        async def fake_fallback():
            # async because the routes' nonstream turns are (_chat_turn_json)
            return {"reply": "fallback reply", "graph_update": {}, "mastery_changes": []}

        events = await collect(
            agent, make_deps(),
            on_complete=lambda r, g, m: on_complete_calls.append(r),
            nonstream_fallback=fake_fallback,
        )
        assert [e.type for e in events] == ["status", "token", "done"]
        assert events[1].data["delta"] == "fallback reply"
        assert events[-1].data["reply"] == "fallback reply"
        assert on_complete_calls == [], "the fallback owns persistence — on_complete must NOT run"

    asyncio.run(run())


def test_rung1_failure_with_writes_is_terminal_error_and_skips_fallback():
    """#470 generalized to EVERY fallback entry: an agent that WROTE (graph
    upsert / append-only mastery event) and then failed before any text must
    NOT hand the turn to the nonstream fallback — the fallback re-runs the
    whole turn and its tools would apply the writes AGAIN. Terminal error
    instead, marked retryable: False so the client skips its own JSON-rung
    too (§2d: a client retry re-runs the same double-apply)."""
    async def run():
        deps = make_deps()

        def write():
            deps.mastery_changes.append({"concept": "Slope", "before": 0.2, "after": 0.4})

        agent = FakeAgent([
            FunctionToolCallEvent("update_mastery_tool"),
            FunctionToolResultEvent(on_fire=write),
            PartStartEvent("never reached"),
        ], raise_after=2)
        on_complete_calls = []
        fallback_calls = []

        async def fake_fallback():
            fallback_calls.append(1)
            return {"reply": "nope"}

        events = await collect(
            agent, deps,
            on_complete=lambda r, g, m: on_complete_calls.append(r),
            nonstream_fallback=fake_fallback,
        )
        assert events[-1].type == "error"
        assert events[-1].data["request_id"] == "r1"
        assert events[-1].data["retryable"] is False
        assert fallback_calls == [], (
            "a fallback after real tool writes would double-apply mastery"
        )
        assert on_complete_calls == []
        assert all(e.type != "done" for e in events)
        # The write the tool made stays — it was a real action.
        assert deps.mastery_changes

    asyncio.run(run())


def test_rung2_failure_after_tokens_errors_and_persists_nothing():
    async def run():
        agent = FakeAgent([PartStartEvent("Half a th"), PartDeltaEvent("ought")], raise_after=1)
        on_complete_calls = []
        fallback_calls = []

        async def fake_fallback():
            fallback_calls.append(1)
            return {"reply": "nope"}

        events = await collect(
            agent, make_deps(),
            on_complete=lambda r, g, m: on_complete_calls.append(r),
            nonstream_fallback=fake_fallback,
        )
        assert events[-1].type == "error"
        assert events[-1].data["request_id"] == "r1"
        assert events[-1].data["retryable"] is True, (
            "no writes landed — the client may retry the turn"
        )
        assert on_complete_calls == [], "nothing may persist after a mid-stream failure"
        assert fallback_calls == [], "never silently re-run once text was shown"

    asyncio.run(run())


def test_rung2_failure_after_writes_marks_error_not_retryable():
    """Rung 2 with writes: the error event must carry retryable: False —
    a retry would re-run the turn and re-apply the landed writes."""
    async def run():
        deps = make_deps()

        def write():
            deps.graph_updates.append({"new_nodes": [{"name": "Slope"}]})

        agent = FakeAgent([
            FunctionToolCallEvent("apply_graph_update_tool"),
            FunctionToolResultEvent(on_fire=write),
            PartStartEvent("Half a th"),
            PartDeltaEvent("ought"),
        ], raise_after=3)
        events = await collect(agent, deps, on_complete=lambda r, g, m: {})
        assert events[-1].type == "error"
        assert events[-1].data["retryable"] is False

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
        fallback_calls = []

        def failing_persist(reply, graph_update, mastery_changes):
            raise RuntimeError("db write failed")

        async def fake_fallback():
            fallback_calls.append(1)
            return {"reply": "nope"}

        events = await collect(
            agent, make_deps(),
            on_complete=failing_persist,
            nonstream_fallback=fake_fallback,
        )
        assert events[-1].type == "error"
        assert events[-1].data["request_id"] == "r1"
        assert events[-1].data["retryable"] is True, "no writes landed — retry is safe"
        assert all(e.type != "done" for e in events), "no done after failed persistence"
        assert fallback_calls == [], "reply already streamed — never re-run the fallback"

    asyncio.run(run())


# ── degenerate blank reply (#153, ADR-0023 follow-up) ─────────────────────
#
# Observed live while recording the #149 eval cassettes: with the "call
# update_mastery at the END of the turn" guidance, gemini-2.5-pro sometimes
# follows the final tool return with a bare-newline text part (2/3 rolls on
# one expository case). Without special handling that whitespace becomes the
# run OUTPUT, and the turn persists an empty assistant row + streams a blank
# bubble. The rungs below pin the fix.

def test_blank_final_output_falls_back_to_streamed_chunks():
    """A whitespace-only final output after tool activity must not clobber
    the real reply text that already streamed earlier in the turn."""
    async def run():
        agent = FakeAgent([
            PartStartEvent("The slope tells you the direction. "),
            FunctionToolCallEvent("update_mastery_tool"),
            FunctionToolResultEvent(),
            PartStartEvent("\n"),               # the degenerate final text
            AgentRunResultEvent("\n"),          # output == bare newline
        ])
        saved = {}
        events = await collect(agent, make_deps(), lambda r, g, m: saved.update(reply=r) or {})
        assert events[-1].type == "done"
        assert saved["reply"] == "The slope tells you the direction. \n", (
            "the joined streamed chunks are the real reply — the blank "
            "output must not be persisted in their place"
        )
        assert events[-1].data["reply"] == saved["reply"]

    asyncio.run(run())


def test_blank_reply_after_tool_call_with_writes_is_terminal_error():
    """Tool call (which WROTE mastery) then only whitespace text: the
    nonstream fallback must NOT run — it would re-run the turn and its tools
    would apply the writes AGAIN, double-counting one student turn in the
    append-only mastery ledger (PR #470 review). Terminal error instead: the
    tool writes stay, nothing persists to the transcript, the client offers
    Retry.

    This pins the NO-CONTINUATION configuration. Since #646 the routes wire a
    `continuation`, which gets first refusal on this rung; the terminal error
    below is what remains when none is wired or it produces nothing."""
    async def run():
        deps = make_deps()

        def write():
            deps.mastery_changes.append({"concept": "Slope", "before": 0.2, "after": 0.4})

        agent = FakeAgent([
            FunctionToolCallEvent("update_mastery_tool"),
            FunctionToolResultEvent(on_fire=write),
            PartStartEvent("\n"),
            AgentRunResultEvent("\n"),
        ])
        on_complete_calls = []
        usage_calls = []
        fallback_calls = []

        async def fake_fallback():
            fallback_calls.append(1)
            return {"reply": "fallback reply", "graph_update": {}, "mastery_changes": []}

        events = await collect(
            agent, deps,
            on_complete=lambda r, g, m: on_complete_calls.append(r),
            nonstream_fallback=fake_fallback,
            on_usage=lambda res: usage_calls.append(res),
        )
        assert events[-1].type == "error"
        assert events[-1].data["retryable"] is False, (
            "writes landed — the client must not re-run this turn either"
        )
        assert fallback_calls == [], (
            "a fallback after real tool writes would double-apply mastery"
        )
        assert on_complete_calls == [], (
            "nothing persists to the transcript on the terminal-error rung"
        )
        # The agent run completed and billed tokens even though its reply was
        # blank — its usage is still recorded.
        assert len(usage_calls) == 1
        # The mastery write the tool made is untouched — it was a real action.
        assert deps.mastery_changes

    asyncio.run(run())


def test_blank_reply_with_no_writes_still_takes_nonstream_fallback():
    """The no-writes twin: a blank turn whose tools wrote NOTHING degrades to
    the nonstream fallback exactly as before — re-running is safe when there
    is nothing to double-apply."""
    async def run():
        deps = make_deps()
        agent = FakeAgent([
            PartStartEvent("\n"),
            AgentRunResultEvent("\n"),
        ])
        on_complete_calls = []

        async def fake_fallback():
            return {"reply": "fallback reply", "graph_update": {}, "mastery_changes": []}

        events = await collect(
            agent, deps,
            on_complete=lambda r, g, m: on_complete_calls.append(r),
            nonstream_fallback=fake_fallback,
        )
        assert events[-1].type == "done"
        assert events[-1].data["reply"] == "fallback reply"
        assert on_complete_calls == []

    asyncio.run(run())


def test_blank_reply_without_fallback_errors_and_persists_nothing():
    async def run():
        agent = FakeAgent([
            FunctionToolCallEvent("update_mastery_tool"),
            FunctionToolResultEvent(),
            PartStartEvent("\n"),
            AgentRunResultEvent("\n"),
        ])
        on_complete_calls = []
        events = await collect(
            agent, make_deps(),
            on_complete=lambda r, g, m: on_complete_calls.append(r),
        )
        assert events[-1].type == "error"
        assert events[-1].data["request_id"] == "r1"
        assert events[-1].data["retryable"] is True, "no writes landed — retry is safe"
        assert all(e.type != "done" for e in events)
        assert on_complete_calls == [], "an empty assistant row must never persist"

    asyncio.run(run())


def test_blank_reply_fallback_failure_is_terminal_error():
    """Blank agent turn + a nonstream fallback that itself raises → structured
    error, nothing persisted (mirrors the Rung-1 fallback-failure contract)."""
    async def run():
        agent = FakeAgent([PartStartEvent("\n"), AgentRunResultEvent("\n")])
        on_complete_calls = []

        async def bad_fallback():
            raise RuntimeError("fallback also down")

        events = await collect(
            agent, make_deps(),
            on_complete=lambda r, g, m: on_complete_calls.append(r),
            nonstream_fallback=bad_fallback,
        )
        assert events[-1].type == "error"
        assert events[-1].data["retryable"] is True, "no writes landed — retry is safe"
        assert all(e.type != "done" for e in events)
        assert on_complete_calls == []

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


def test_on_usage_not_called_on_error_rungs_or_nonstream_fallback():
    """No result event was seen on Rung 1/2, and the nonstream fallback
    captures its own usage (record_agent_usage inside the route's JSON turn)
    — the hook must stay silent."""
    async def run():
        usage_calls = []

        async def fake_fallback():
            return {"reply": "fallback"}

        # Rung 1: failure before any token → nonstream fallback.
        events = await collect(
            FakeAgent([AgentRunResultEvent("x")], raise_after=0),
            make_deps(), lambda r, g, m: {},
            nonstream_fallback=fake_fallback,
            on_usage=lambda res: usage_calls.append(res),
        )
        assert events[-1].type == "done" and events[-1].data["reply"] == "fallback"
        assert usage_calls == [], "the nonstream fallback must not trigger on_usage"

        # Rung 2: failure after tokens streamed → terminal error.
        events = await collect(
            FakeAgent([PartStartEvent("Hi"), AgentRunResultEvent("x")], raise_after=1),
            make_deps(), lambda r, g, m: {},
            on_usage=lambda res: usage_calls.append(res),
        )
        assert events[-1].type == "error"
        assert usage_calls == [], "an aborted run has no result to record"

    asyncio.run(run())



def test_fallback_that_wrote_then_failed_marks_error_not_retryable():
    """PR #472 review: the writes-guard protects ENTRY to the fallback, but
    the fallback is itself a tool-calling agent run — if ITS tools wrote and
    it then failed, the terminal error must carry retryable: False so the
    client cannot re-run the turn a third time and re-apply the writes. The
    route helpers stamp `sapling_wrote` on the raised exception."""
    async def run():
        deps = make_deps()
        agent = FakeAgent([PartStartEvent("x")], raise_after=0)

        async def fallback_that_wrote_then_failed():
            exc = RuntimeError("fallback blank after tool write")
            exc.sapling_wrote = True
            raise exc

        events = await collect(
            agent, deps,
            on_complete=lambda r, g, m: (_ for _ in ()).throw(AssertionError("persisted")),
            nonstream_fallback=fallback_that_wrote_then_failed,
        )
        assert events[-1].type == "error"
        assert events[-1].data["retryable"] is False

    asyncio.run(run())


def test_fallback_failure_without_writes_stays_retryable():
    """The no-writes twin: a fallback that failed before any tool write
    keeps retryable: True — the client's JSON retry is safe and wanted."""
    async def run():
        deps = make_deps()
        agent = FakeAgent([PartStartEvent("x")], raise_after=0)

        async def clean_failure():
            raise RuntimeError("network blip")

        events = await collect(
            agent, deps,
            on_complete=lambda r, g, m: None,
            nonstream_fallback=clean_failure,
        )
        assert events[-1].type == "error"
        assert events[-1].data["retryable"] is True

    asyncio.run(run())


def test_textless_turn_never_replays_the_previous_turns_reply():
    """A turn whose model response carries NO text part must not persist the
    PREVIOUS turn's reply.

    `run_result.output` resolves out of the run's message list, and that list
    includes `message_history` — so a tool-only turn hands back the last
    assistant message from an EARLIER turn: fully formed, non-blank, and
    therefore invisible to the blank-reply ladder below. Taking it verbatim
    makes the tutor answer a follow-up with a byte-identical copy of its own
    previous answer (observed live on gemini-2.5-flash-lite; ~25% of turns
    when the model ends its turn after tool calls).

    Nothing streamed this turn, so there is no reply of this turn's to
    persist: the turn degrades exactly like any other blank one.
    """
    PRIOR = "A Markov chain is a stochastic model describing a sequence of events."

    async def run():
        agent = FakeAgent([
            FunctionToolCallEvent("read_graph_neighborhood"),
            FunctionToolResultEvent(),          # no writes landed
            AgentRunResultEvent(PRIOR),         # stale: from message_history
        ])
        on_complete_calls = []

        async def fake_fallback():
            return {"reply": "fresh reply", "graph_update": {}, "mastery_changes": []}

        events = await collect(
            agent, make_deps(),
            on_complete=lambda r, g, m: on_complete_calls.append(r),
            nonstream_fallback=fake_fallback,
        )
        assert on_complete_calls == [], "prior-turn text must never persist as this turn's reply"
        assert all(
            PRIOR not in (e.data or {}).get("delta", "") for e in events if e.type == "token"
        ), "prior-turn text must never reach the student's bubble"
        assert events[-1].data["reply"] == "fresh reply"
        assert events[-1].data["reply"] != PRIOR

    asyncio.run(run())


def test_textless_turn_with_writes_is_a_terminal_error_not_a_replay():
    """The LIKELIER shape of a textless turn: a tool WROTE first.

    Every tutor agent registers `apply_graph_update_tool` and
    `update_mastery_tool` (agents/chat_tutor.py), and a model that ends its
    turn after tool calls has by definition just called tools — so the
    textless turn usually arrives with `deps.graph_updates` /
    `deps.mastery_changes` already populated. That lands on the
    write-guard rung, not Rung 1: re-running the turn would apply the same
    mastery event twice (PR #470 review), so the honest degrade is a terminal
    `retryable: False` error.

    Also pins the no-continuation configuration — see #646 and
    `test_textless_turn_with_writes_is_rescued_by_the_continuation` for the
    wired behaviour that supersedes this rung in production.

    Distinct from `test_blank_reply_after_tool_call_with_writes_is_terminal_error`,
    which streams a whitespace text part. Here NOTHING streams and
    `run_result.output` is a fully-formed reply from an EARLIER turn — the
    shape that sails through a bare `if not reply.strip()` guard.
    """
    PRIOR = "Gradient descent walks downhill along the steepest direction."

    async def run():
        deps = make_deps()

        def write():
            deps.mastery_changes.append(
                {"concept": "Gradient descent", "before": 0.3, "after": 0.5}
            )

        agent = FakeAgent([
            FunctionToolCallEvent("update_mastery_tool"),
            FunctionToolResultEvent(on_fire=write),   # the write lands
            AgentRunResultEvent(PRIOR),               # stale: from message_history
        ])
        on_complete_calls = []
        fallback_calls = []

        async def fake_fallback():
            fallback_calls.append(1)
            return {"reply": "fresh reply", "graph_update": {}, "mastery_changes": []}

        events = await collect(
            agent, deps,
            on_complete=lambda r, g, m: on_complete_calls.append(r),
            nonstream_fallback=fake_fallback,
        )
        assert events[-1].type == "error"
        assert events[-1].data["retryable"] is False, (
            "mastery already moved this turn — neither the server fallback "
            "nor a client retry may re-run it"
        )
        assert fallback_calls == [], (
            "a fallback after real tool writes would double-apply mastery"
        )
        assert on_complete_calls == [], (
            "the prior turn's reply must not be persisted as this turn's"
        )
        assert all(
            PRIOR not in (e.data or {}).get("delta", "")
            for e in events if e.type == "token"
        ), "prior-turn text must never reach the student's bubble"
        # The write was a real tool action — it stays.
        assert deps.mastery_changes

    asyncio.run(run())


# ── textless-with-writes continuation (#646) ──────────────────────────────
#
# The rung above is the COMMON case, not an edge: by #562's measurements
# roughly 25-40% of gemini-2.5-flash-lite turns end textless, and Flash-Lite
# is the UI default (Pro is opt-in). Failing those turns outright shows the
# student "The tutor was interrupted" after the tutor has already done the
# work, and the only recovery offered — a manual retry — re-runs the tools
# and can apply the same mastery event twice.
#
# A continuation asks the model to finish the turn it abandoned, passing the
# run's own messages back. The tool results are already IN those messages, so
# the model writes its reply from them instead of calling the tools again.


async def collect_with_continuation(
    agent, deps, on_complete, continuation, nonstream_fallback=None, on_usage=None
):
    events = []
    async for ev in stream_agent_turn(
        agent=agent, user_message="hi", run_kwargs={}, deps=deps,
        on_complete=on_complete, nonstream_fallback=nonstream_fallback,
        on_usage=on_usage, request_id="r1", continuation=continuation,
    ):
        events.append(ev)
    return events


def _textless_agent_with_write(deps, stale_output="PRIOR TURN REPLY"):
    """A run that calls a tool (which writes), then ends with no text part —
    `run_result.output` resolving to an earlier turn's reply."""
    def write():
        deps.mastery_changes.append(
            {"concept": "Gradient descent", "before": 0.3, "after": 0.5}
        )

    return FakeAgent([
        FunctionToolCallEvent("update_mastery_tool"),
        FunctionToolResultEvent(on_fire=write),
        AgentRunResultEvent(stale_output),
    ])


def test_textless_turn_with_writes_is_rescued_by_the_continuation():
    """The #646 fix: instead of a terminal error, finish the turn.

    The student gets the reply the tutor had already earned, the transcript
    gets a row, and the tools ran exactly once — so there is nothing left for
    a retry to double-apply."""
    async def run():
        deps = make_deps()
        agent = _textless_agent_with_write(deps)
        on_complete_calls = []
        fallback_calls = []
        continuation_calls = []

        async def fake_continuation(run_result):
            continuation_calls.append(run_result)
            return "Gradient descent steps opposite the gradient."

        async def fake_fallback():
            fallback_calls.append(1)
            return {"reply": "fallback", "graph_update": {}, "mastery_changes": []}

        events = await collect_with_continuation(
            agent, deps,
            on_complete=lambda r, g, m: on_complete_calls.append(r) or {},
            continuation=fake_continuation,
            nonstream_fallback=fake_fallback,
        )

        assert events[-1].type == "done", "the turn completes instead of erroring"
        assert events[-1].data["reply"] == "Gradient descent steps opposite the gradient."
        assert on_complete_calls == ["Gradient descent steps opposite the gradient."], (
            "the rescued reply is persisted to the transcript"
        )
        assert len(continuation_calls) == 1, "continuation runs once"
        assert fallback_calls == [], (
            "the nonstream fallback re-runs the TURN and would re-apply the "
            "mastery write — the continuation exists precisely to avoid it"
        )
        # The mastery write stays exactly once: the continuation replays no tools.
        assert len(deps.mastery_changes) == 1
        # The student must actually SEE the text, not just get it in `done`.
        streamed = "".join(
            (e.data or {}).get("delta", "") for e in events if e.type == "token"
        )
        assert streamed == "Gradient descent steps opposite the gradient."

    asyncio.run(run())


def test_continuation_that_is_also_textless_falls_through_to_terminal_error():
    """The contract is unchanged when the rescue fails: #470's writes-guard
    still holds, so the turn ends `retryable: False` and persists nothing."""
    async def run():
        deps = make_deps()
        agent = _textless_agent_with_write(deps)
        on_complete_calls = []
        fallback_calls = []

        async def empty_continuation(run_result):
            return ""

        async def fake_fallback():
            fallback_calls.append(1)
            return {"reply": "fallback", "graph_update": {}, "mastery_changes": []}

        events = await collect_with_continuation(
            agent, deps,
            on_complete=lambda r, g, m: on_complete_calls.append(r),
            continuation=empty_continuation,
            nonstream_fallback=fake_fallback,
        )

        assert events[-1].type == "error"
        assert events[-1].data["retryable"] is False
        assert on_complete_calls == []
        assert fallback_calls == [], "still never safe after a write"

    asyncio.run(run())


def test_continuation_raising_degrades_to_the_terminal_error():
    """A continuation is a second model call: it can time out or blow up.
    That must land on the same terminal rung, never escape as a 500."""
    async def run():
        deps = make_deps()
        agent = _textless_agent_with_write(deps)

        async def exploding_continuation(run_result):
            raise RuntimeError("continuation model call failed")

        events = await collect_with_continuation(
            agent, deps,
            on_complete=lambda r, g, m: None,
            continuation=exploding_continuation,
        )

        assert events[-1].type == "error"
        assert events[-1].data["retryable"] is False

    asyncio.run(run())


def test_continuation_never_replays_the_previous_turns_reply():
    """The continuation carries `message_history` too, so it inherits the
    very stale-read hazard #562 fixed: its own `.output` can resolve back to
    an earlier assistant message. Whatever the caller injects must be
    narrowed to THIS run's text — a continuation that produced nothing is
    textless, however non-blank `.output` looks."""
    PRIOR = "Gradient descent walks downhill along the steepest direction."

    async def run():
        deps = make_deps()
        agent = _textless_agent_with_write(deps, stale_output=PRIOR)
        on_complete_calls = []

        async def stale_continuation(run_result):
            # What a correct caller returns when the continuation run added
            # no text of its own: None, NOT run_result.output.
            return None

        events = await collect_with_continuation(
            agent, deps,
            on_complete=lambda r, g, m: on_complete_calls.append(r),
            continuation=stale_continuation,
        )

        assert events[-1].type == "error"
        assert on_complete_calls == [], "a stale reply must never be persisted"
        assert all(
            PRIOR not in (e.data or {}).get("delta", "")
            for e in events if e.type == "token"
        )

    asyncio.run(run())


def test_no_continuation_supplied_keeps_the_pre_646_contract():
    """`continuation` is optional: every existing caller (and every test
    above) must keep the terminal-error behaviour without passing one."""
    async def run():
        deps = make_deps()
        agent = _textless_agent_with_write(deps)
        events = await collect(agent, deps, on_complete=lambda r, g, m: None)
        assert events[-1].type == "error"
        assert events[-1].data["retryable"] is False

    asyncio.run(run())


def test_continuation_is_not_attempted_when_nothing_was_written():
    """The no-writes twin still belongs to Rung 1: re-running the whole turn
    is SAFE there and produces a better answer than nudging a model that
    just declined to speak. The continuation is a writes-guard escape hatch,
    not a general blank-reply handler."""
    async def run():
        deps = make_deps()
        agent = FakeAgent([AgentRunResultEvent("")])
        continuation_calls = []
        fallback_calls = []

        async def fake_continuation(run_result):
            continuation_calls.append(1)
            return "should not be used"

        async def fake_fallback():
            fallback_calls.append(1)
            return {"reply": "fallback reply", "graph_update": {}, "mastery_changes": []}

        events = await collect_with_continuation(
            agent, deps,
            on_complete=lambda r, g, m: None,
            continuation=fake_continuation,
            nonstream_fallback=fake_fallback,
        )

        assert continuation_calls == []
        assert fallback_calls == [1]
        assert events[-1].type == "done"

    asyncio.run(run())


# ── stream_structured_turn (PKG-07 unblock S1) ──────────────────────────────
#
# Driven through a REAL pydantic-ai run (agent.iter + node.stream) against a
# FunctionModel that streams the turn's JSON in small chunks: the structured
# path dispatches on pydantic-ai's graph nodes, not on event class names, so a
# fake would only test itself.

import json  # noqa: E402

import pytest  # noqa: E402
from pydantic_ai import Agent, PromptedOutput  # noqa: E402
from pydantic_ai.models.function import DeltaToolCall, FunctionModel  # noqa: E402

from learning.ladder import Rung  # noqa: E402
from learning.turn_shape import LoopTurnOut, render_turn, turn_limits  # noqa: E402
from services.chat_stream import stream_structured_turn  # noqa: E402

_TURN = {
    "key_idea": "A base case is where a recursive function stops.",
    "body": "Without one, every call makes another call and the stack overflows.",
    "question": "Which input should make factorial stop?",
}
_BAD_TURN = {  # two questions: the loop tutor's output validator retries it
    "key_idea": "A base case is where a recursive function stops.",
    "body": "Without one, every call makes another call and the stack overflows.",
    "question": "Which input stops it? Or is there none?",
}


def _streamed_model(turns, *, fail_at=None, chunk=6, tool_first=None):
    """One FunctionModel request per entry of `turns` (a dict → its JSON), each
    streamed in `chunk`-char deltas. fail_at=(request, delta) raises there;
    tool_first=<name> makes the FIRST request a call to that tool."""
    calls = {"n": 0}

    async def stream_fn(messages, info):
        i = calls["n"]
        calls["n"] += 1
        if tool_first and i == 0:
            yield {0: DeltaToolCall(name=tool_first, json_args="{}", tool_call_id="t1")}
            return
        body = turns[i - (1 if tool_first else 0)]
        text = body if isinstance(body, str) else json.dumps(body)
        for j in range(0, len(text), chunk):
            if fail_at is not None and (i, j // chunk) == fail_at:
                raise RuntimeError("model blew up")
            yield text[j : j + chunk]

    def fn(messages, info):  # the non-stream path is never used here
        raise AssertionError("stream_structured_turn must stream")

    return FunctionModel(fn, stream_function=stream_fn), calls


def _loop_deps(limits=None):
    deps = make_deps()
    deps.loop_turn = limits or turn_limits("teach", Rung.H3, False)
    return deps


async def collect_structured(
    agent, deps, model, on_complete, *, nonstream_fallback=None, on_usage=None, transform=None
):
    events = []
    async for ev in stream_structured_turn(
        agent=agent,
        user_message="hi",
        run_kwargs={"deps": deps, "model": model},
        deps=deps,
        on_complete=on_complete,
        nonstream_fallback=nonstream_fallback,
        on_usage=on_usage,
        request_id="r1",
        transform=transform,
    ):
        events.append(ev)
    return events


def _tokens(events):
    return "".join(e.data["delta"] for e in events if e.type == "token")


def _loop_agent():
    from agents.loop_tutor import loop_tutor_agent

    return loop_tutor_agent


def test_structured_stream_emits_rendered_sentences_not_json():
    model, _ = _streamed_model([_TURN])
    persisted, usage = [], []
    deps = _loop_deps()

    def on_complete(reply, gu, mc):
        persisted.append(reply)
        return {"message_id": "m1"}

    events = asyncio.run(
        collect_structured(_loop_agent(), deps, model, on_complete, on_usage=usage.append)
    )
    types = [e.type for e in events]
    assert types[0] == "status" and types[-1] == "done"
    assert "error" not in types and "retract" not in types
    tokens = [e.data["delta"] for e in events if e.type == "token"]
    assert len(tokens) >= 3  # streamed sentence by sentence, not one blob at the end
    assert _tokens(events) == render_turn(_TURN)
    for t in tokens:  # never the raw JSON
        assert "{" not in t and '"key_idea"' not in t and '"body"' not in t
    # the first token is the completed key idea sentence, before the body finished
    assert tokens[0].startswith("Key idea: A base case")
    assert persisted == [render_turn(_TURN)]
    done = events[-1]
    assert done.data["reply"] == render_turn(_TURN) and done.data["message_id"] == "m1"
    assert len(usage) == 1 and usage[0].output == _TURN  # on_usage gets run.result


def test_structured_stream_retract_on_retry():
    model, calls = _streamed_model([_BAD_TURN, _TURN])
    persisted = []
    events = asyncio.run(
        collect_structured(
            _loop_agent(), _loop_deps(), model, lambda r, g, m: persisted.append(r) or {}
        )
    )
    types = [e.type for e in events]
    assert calls["n"] == 2
    assert types.count("retract") == 1
    at = types.index("retract")
    assert "token" in types[:at]  # the bad turn had streamed before it was superseded
    assert events[at].data["reason"] == "retry"
    after = "".join(e.data["delta"] for e in events[at + 1 :] if e.type == "token")
    assert after == render_turn(_TURN)
    assert types[-1] == "done" and events[-1].data["reply"] == render_turn(_TURN)
    assert persisted == [render_turn(_TURN)]


def test_structured_stream_fallback_before_first_token():
    """The fallback is handed the failed run's messages (PKG-07 review round 3,
    m2) so the caller can continue from them instead of replaying the turn."""
    model, _ = _streamed_model([_TURN], fail_at=(0, 0))
    persisted, fallback_calls, usage = [], [], []

    async def fallback(messages):
        fallback_calls.append(1)
        prompts = [p.content for m in messages for p in m.parts if p.part_kind == "user-prompt"]
        assert prompts, "the failed run's own request is among the messages"
        return {"reply": "Fallback reply.", "message_id": "fb"}

    events = asyncio.run(
        collect_structured(
            _loop_agent(),
            _loop_deps(),
            model,
            lambda r, g, m: persisted.append(r) or {},
            nonstream_fallback=fallback,
            on_usage=usage.append,
        )
    )
    assert [e.type for e in events] == ["status", "token", "done"]
    assert events[1].data["delta"] == "Fallback reply."
    assert events[-1].data["message_id"] == "fb"
    assert fallback_calls == [1] and persisted == [] and usage == []


def test_structured_stream_fallback_before_first_token_without_fallback_errors():
    model, _ = _streamed_model([_TURN], fail_at=(0, 0))
    events = asyncio.run(
        collect_structured(_loop_agent(), _loop_deps(), model, lambda r, g, m: {})
    )
    assert [e.type for e in events] == ["status", "error"]
    assert events[-1].data["retryable"] is True


def test_structured_stream_error_after_tokens():
    text = json.dumps(_TURN)
    late = (len(text) // 6) - 2  # well after the key idea sentence completed
    model, _ = _streamed_model([_TURN], fail_at=(0, late))
    persisted, fallback_calls = [], []

    async def fallback(messages):
        fallback_calls.append(1)
        return {"reply": "x"}

    events = asyncio.run(
        collect_structured(
            _loop_agent(),
            _loop_deps(),
            model,
            lambda r, g, m: persisted.append(r) or {},
            nonstream_fallback=fallback,
        )
    )
    types = [e.type for e in events]
    assert "token" in types
    assert types[-1] == "error" and "done" not in types
    assert events[-1].message == "The tutor was interrupted. Please retry."
    assert events[-1].data == {"request_id": "r1", "retryable": True}
    assert fallback_calls == [] and persisted == []  # never re-run, never persisted


def test_structured_stream_applies_transform_before_emit():
    """The caller's transform (the loop route passes strip_leak) runs on the
    CUMULATIVE text before anything is emitted: the raw span never reaches a
    token, and done.reply is the transformed render. on_complete gets the RAW
    render so the route's own leak accounting still sees what the model wrote."""
    model, _ = _streamed_model([_TURN])
    persisted = []

    def transform(text):
        return text.replace("stack overflows", "[withheld]")

    events = asyncio.run(
        collect_structured(
            _loop_agent(),
            _loop_deps(),
            model,
            lambda r, g, m: persisted.append(r) or {"reply": "route text"},
            transform=transform,
        )
    )
    assert all("stack overflows" not in e.data["delta"] for e in events if e.type == "token")
    assert _tokens(events) == transform(render_turn(_TURN))
    assert events[-1].type == "done"
    assert events[-1].data["reply"] == transform(render_turn(_TURN))
    assert persisted == [render_turn(_TURN)]


def test_structured_stream_retracts_when_the_transform_rewrites_shown_text():
    """A transform that changes text it already let through (a leak only
    detectable once more text arrived) retracts and re-sends the whole text."""
    model, _ = _streamed_model([_TURN])

    def transform(text):  # rewrites the KEY IDEA only once the question exists
        return text.replace("A base case", "[withheld]") if "factorial" in text else text

    events = asyncio.run(
        collect_structured(_loop_agent(), _loop_deps(), model, lambda r, g, m: {}, transform=transform)
    )
    types = [e.type for e in events]
    assert "retract" in types
    at = len(types) - 1 - types[::-1].index("retract")
    assert events[at].data["reason"] == "transform"
    after = "".join(e.data["delta"] for e in events[at + 1 :] if e.type == "token")
    assert after == transform(render_turn(_TURN))
    assert events[-1].data["reply"] == transform(render_turn(_TURN))


def test_structured_stream_tool_round_emits_progress():
    agent = Agent(output_type=PromptedOutput(LoopTurnOut), deps_type=SaplingDeps)

    @agent.tool_plain
    def search_course_materials() -> str:
        return "Base cases stop recursion."

    model, calls = _streamed_model([_TURN], tool_first="search_course_materials")
    events = asyncio.run(collect_structured(agent, _loop_deps(), model, lambda r, g, m: {}))
    types = [e.type for e in events]
    assert calls["n"] == 2
    assert "progress" in types and events[types.index("progress")].step == "search_course_materials"
    assert types.index("progress") < types.index("token")
    assert "retract" not in types  # the tool round streamed no text
    assert _tokens(events) == render_turn(_TURN)


def test_structured_stream_cancel_persists_nothing():
    model, _ = _streamed_model([_TURN])
    persisted = []

    async def run():
        gen = stream_structured_turn(
            agent=_loop_agent(),
            user_message="hi",
            run_kwargs={"deps": _loop_deps(), "model": model},
            deps=_loop_deps(),
            on_complete=lambda r, g, m: persisted.append(r) or {},
        )
        async for ev in gen:
            if ev.type == "token":
                break
        await gen.aclose()

    asyncio.run(run())
    assert persisted == []


def test_structured_stream_consumer_cancel_stops_the_run():
    """A disconnect cancels the consuming task: the cancellation propagates,
    the producer task running the agent is cancelled with it, nothing persists."""
    persisted, gate = [], {}

    async def stream_fn(messages, info):
        text = json.dumps(_TURN)
        for j in range(0, len(text), 6):
            if j > len(text) // 2:
                gate["waiting"] = True
                await asyncio.sleep(3600)  # the model stalls mid-turn
            yield text[j : j + 6]

    def fn(messages, info):
        raise AssertionError

    model = FunctionModel(fn, stream_function=stream_fn)

    async def run():
        deps = _loop_deps()

        async def consume():
            async for _ev in stream_structured_turn(
                agent=_loop_agent(),
                user_message="hi",
                run_kwargs={"deps": deps, "model": model},
                deps=deps,
                on_complete=lambda r, g, m: persisted.append(r) or {},
            ):
                pass

        task = asyncio.create_task(consume())
        while not gate.get("waiting"):
            await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await asyncio.sleep(0)
        others = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        assert all(t.done() for t in others)

    asyncio.run(run())
    assert persisted == []


def test_stream_agent_turn_is_untouched_by_the_structured_path():
    """stream_agent_turn keeps its run_stream_events contract byte-identical."""
    import inspect

    from services import chat_stream

    src = inspect.getsource(chat_stream.stream_agent_turn)
    assert "run_stream_events" in src and "transform" not in src and "retract" not in src


@pytest.mark.parametrize("bad", ['{"key_idea": "x"', "not json at all"])
def test_structured_stream_invalid_output_after_retries_is_a_terminal_error(bad):
    """Output retries exhausted: text had streamed from the first bad attempt
    (or not) — either way no fallback re-run after tokens, never a persist."""
    model, _ = _streamed_model([bad, bad, bad])
    persisted = []
    events = asyncio.run(
        collect_structured(
            _loop_agent(), _loop_deps(), model, lambda r, g, m: persisted.append(r) or {}
        )
    )
    assert events[-1].type == "error" and persisted == []
