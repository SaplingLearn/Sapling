# Streaming Tutor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stream the Learn tutor's replies token-by-token over SSE with live knowledge-graph deltas on the same stream, and migrate `start_session` onto the chat agent so its greeting streams too.

**Architecture:** One new async generator (`services/chat_stream.py::stream_agent_turn`) wraps `agent.run_stream_events()` and translates Pydantic AI events into the existing `SaplingEvent` SSE envelope, extended with three new types (`token`, `graph_update`, `done`). Two thin new routes (`/api/learn/chat/stream`, `/api/learn/start-session/stream`) hand that generator to `EventSourceResponse`. The existing JSON routes are untouched and remain the fallback. The frontend consumes it through one `streamChat()` built on the existing `streamSSE`.

**Tech Stack:** FastAPI · sse-starlette `EventSourceResponse` · Pydantic AI 1.89.1 (`run_stream_events`) · pytest · Next.js/React · vitest

**Spec:** `docs/superpowers/specs/2026-07-16-streaming-design.md`
**Issues:** #70 (token streaming), #74 (live graph deltas). Also advances #152/#151 and closes ADR-0015's `start_session` TODO.
**Branch:** `feat/streaming-tutor` (already exists, spec committed at `ea149f7`)

## Global Constraints

- **Never adopt a second SSE protocol or parser.** New event types extend `SaplingEvent` in `backend/services/agent_events.py`; the frontend consumes via `frontend/src/lib/sse.ts::streamSSE`. (ADR 0006)
- **All graph mutations flow through `graph_service.apply_graph_update`.** Streamed deltas are *read from* `deps.graph_updates` / `deps.mastery_changes`, which the tools populate. Never write the graph from the stream module. (ADR 0004)
- **Encryption boundary:** persist only via `routes/learn.py::save_message` (which calls `encrypt_if_present`). Never add a second persistence path. (ADR 0015 + CLAUDE.md)
- **Legacy fallback survives.** `_legacy_chat` and the JSON `/chat` + `/start-session` routes stay callable and behaviorally unchanged. (ADR 0001/0015)
- **Never wrap a stream route in a DBOS workflow.** (ADR 0011)
- **Never use FastAPI `BackgroundTasks` in a streaming route** — it does not fire. Use `asyncio.create_task(asyncio.to_thread(...))` if post-stream work is ever needed. (`docs/attempts/2026-05-03-vault-gap-prompts-13-14.md`)
- **No hardcoded model names** in new code. Model choice comes from `agents/_providers.py` slots; `learn.py::_resolve_model_pref` resolves the user's `model_pref`. (ADR 0008)
- **Usage limits:** every agent run passes `usage_limits=ORCHESTRATOR_LIMITS` (from `agents/__init__.py`).
- **Stamp `X-Request-ID`** on every stream; include `request_id` in every `error` payload. (ADR 0009)
- Run backend commands from `backend/` using `venv/bin/python`. Frontend commands from `frontend/`.
- `ruff check .` must pass before every backend commit.

## File Structure

| File | Responsibility |
|---|---|
| `backend/services/agent_events.py` (modify) | Add `token` / `graph_update` / `done` to `SaplingEventType`. Wire-format helper `sapling_event_to_sse` unchanged. |
| `backend/services/chat_stream.py` (create) | **New.** `stream_agent_turn()` — the only place that iterates a Pydantic AI event stream for chat, emits SaplingEvents, owns the graph-delta high-water mark, the completion/persistence handoff, and the fallback rungs. |
| `backend/routes/learn.py` (modify) | Extract `_prepare_chat_run()` from `_chat_via_agent`; add `POST /chat/stream` and `POST /start-session/stream`. Existing routes untouched. |
| `backend/tests/test_chat_stream.py` (create) | Unit tests for `stream_agent_turn` against a fake event stream. |
| `backend/tests/test_learn_stream_routes.py` (create) | Route-level tests (auth, SSE wire format, PENDING_SESSIONS). |
| `frontend/src/lib/sse.ts` (modify) | Add optional `idleTimeoutMs` stall guard. |
| `frontend/src/lib/api.ts` (modify) | Add `streamChat()` / `startSessionStream()` + `GraphDelta` / `ChatResult` types. |
| `frontend/src/lib/api.stream.test.ts` (create) | vitest for the consumer. |
| `frontend/src/components/ChatPanel.tsx` (modify) | Streaming bubble states + Stop. |
| `frontend/src/components/screens/Learn.tsx` (modify) | Call `streamChat`, reduce graph deltas, fallback to `sendChat`. |

**Task order rationale:** Task 1 is a spike that gates everything (ADR-0012's open question). Tasks 2–5 are backend, bottom-up. Tasks 6–9 are frontend. Each task ends green and committed.

---

### Task 1: Spike — prove the provider streams incrementally

**This gates the whole plan.** ADR 0012 deferred concept streaming partly because nobody verified Gemini emits usable incremental output through our stack. Confirm it before writing production code. Nothing here ships.

**Files:**
- Create (throwaway, deleted in Step 4): `backend/spike_stream.py`

**Interfaces:**
- Consumes: nothing.
- Produces: a written finding that pins which events carry text and whether tool events interleave. Task 2 depends on the answer.

- [ ] **Step 1: Write the spike script**

```python
# backend/spike_stream.py  — THROWAWAY. Deleted at the end of this task.
import asyncio

from agents import ORCHESTRATOR_LIMITS
from agents.chat_tutor import agent_for_mode
from agents.deps import SaplingDeps


async def main():
    agent = agent_for_mode("expository")
    deps = SaplingDeps(
        user_id="spike-user",
        course_id=None,
        supabase=None,
        request_id="spike",
        session_id=None,
    )
    counts: dict[str, int] = {}
    first_text_event: str | None = None
    async for event in agent.run_stream_events(
        "Explain what an eigenvalue is in two sentences.",
        deps=deps,
        usage_limits=ORCHESTRATOR_LIMITS,
    ):
        name = type(event).__name__
        counts[name] = counts.get(name, 0) + 1
        # Which event class first carries text?
        if first_text_event is None:
            delta = getattr(getattr(event, "delta", None), "content_delta", None)
            part = getattr(getattr(event, "part", None), "content", None)
            if delta or part:
                first_text_event = f"{name} -> {(delta or part)!r}"
    print("EVENT COUNTS:", counts)
    print("FIRST TEXT FROM:", first_text_event)


asyncio.run(main())
```

- [ ] **Step 2: Run it against a real key**

Run from `backend/`:

```bash
venv/bin/python spike_stream.py
```

Expected: a `PartDeltaEvent` count well above 1 (proving incremental text, not one blob), and `FIRST TEXT FROM: PartStartEvent -> '...'`.

- [ ] **Step 3: Record the finding**

**If `PartDeltaEvent` count is > 1:** the gate is closed — proceed. Append the observed counts to the spec's Risks section, replacing the "spike could fail" hypothetical with the measured result.

**If it is 0 or 1** (one blob, no incremental deltas): **stop and report to Andres before continuing.** #70's premise does not hold on this provider/version, and the plan needs rescoping. Write the finding to `docs/attempts/2026-07-16-gemini-incremental-streaming.md` per the `log-attempt` convention.

- [ ] **Step 4: Delete the spike and commit the finding**

```bash
rm backend/spike_stream.py
git add docs/superpowers/specs/2026-07-16-streaming-design.md
git commit -m "docs(spec): record streaming spike results — close ADR-0012 gate"
```

---

### Task 2: Extend the SaplingEvent vocabulary

**Files:**
- Modify: `backend/services/agent_events.py:15` (the `SaplingEventType` Literal)
- Test: `backend/tests/test_agent_events.py` (create if absent)

**Interfaces:**
- Consumes: existing `SaplingEvent`, `sapling_event_to_sse`.
- Produces: `SaplingEventType` now accepts `"token" | "graph_update" | "done"`. Task 3 constructs these.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_agent_events.py
import json

from services.agent_events import SaplingEvent, sapling_event_to_sse


def test_token_event_serializes_to_sse():
    ev = SaplingEvent(type="token", step="reply", message="", data={"delta": "Hi"})
    wire = sapling_event_to_sse(ev)
    assert wire["event"] == "token"
    assert json.loads(wire["data"])["data"]["delta"] == "Hi"


def test_graph_update_and_done_types_accepted():
    for t in ("graph_update", "done"):
        assert SaplingEvent(type=t, step="reply", message="").type == t
```

- [ ] **Step 2: Run it to verify it fails**

Run: `venv/bin/python -m pytest tests/test_agent_events.py -q`
Expected: FAIL — pydantic `ValidationError`, `"token"` is not a permitted `SaplingEventType`.

- [ ] **Step 3: Extend the Literal**

In `backend/services/agent_events.py`, replace line 15:

```python
SaplingEventType = Literal["status", "progress", "result", "error"]
```

with:

```python
# "status"/"progress"/"result" are the document-pipeline vocabulary (ADR 0006).
# "token"/"graph_update"/"done" extend it for chat streams; "error" is shared.
SaplingEventType = Literal[
    "status", "progress", "result", "error", "token", "graph_update", "done"
]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `venv/bin/python -m pytest tests/test_agent_events.py -q && ruff check .`
Expected: 2 passed, ruff clean.

- [ ] **Step 5: Commit**

```bash
git add backend/services/agent_events.py backend/tests/test_agent_events.py
git commit -m "feat(events): extend SaplingEvent vocabulary with token/graph_update/done (#70)"
```

---

### Task 3: `services/chat_stream.py` — the generator

The heart of the change. Everything it does is proven by Task 4's tests against a fake stream; no live LLM.

**Files:**
- Create: `backend/services/chat_stream.py`

**Interfaces:**
- Consumes: `SaplingEvent` (Task 2); `SaplingDeps` (`agents/deps.py`) — specifically `deps.graph_updates: list` and `deps.mastery_changes: list`, which `agents/tools/graph.py` appends to at `:117` (`{"new_nodes": [...]}`), `:169` (`{"updated_nodes": [...]}`), and `:171` (mastery changes).
- Produces:
  - `async def stream_agent_turn(*, agent, user_message, run_kwargs, deps, on_complete, legacy_fallback) -> AsyncIterator[SaplingEvent]`
  - `def merge_graph_updates(updates: list[dict]) -> dict`
  Task 5 (routes) calls both.

**Pydantic AI 1.89.1 event shapes** (verified by inspection — do not guess):

| Event class | Fields | Carries |
|---|---|---|
| `PartStartEvent` | `index, part, previous_part_kind, event_kind` | **the first text chunk**, at `event.part.content` |
| `PartDeltaEvent` | `index, delta, event_kind` | subsequent text at `event.delta.content_delta` |
| `FunctionToolCallEvent` | `part, args_valid, event_kind` | tool name at `event.part.tool_name` |
| `FunctionToolResultEvent` | `result, content, event_kind` | tool finished — **check deps here** |
| `AgentRunResultEvent` | `result, event_kind` | final output at `event.result.output` |

> **Trap:** the first chunk of text arrives on `PartStartEvent`, *not* `PartDeltaEvent`. Handling only deltas silently drops the reply's opening. Task 4 Step 1 has a regression test for exactly this.

- [ ] **Step 1: Write the module**

```python
# backend/services/chat_stream.py
"""Translate a Pydantic AI chat run into Sapling SSE events.

The single seam for streaming chat turns (ADR 0006 vocabulary). Iterates
`agent.run_stream_events()` — the only API that yields BOTH text deltas and
mid-run tool events in one pass — and emits:

    status:start -> token* -> (progress:<tool> -> graph_update)* -> done

Graph deltas are READ from `deps.graph_updates` / `deps.mastery_changes`,
which the graph tools populate as they write through
`graph_service.apply_graph_update` (ADR 0004). This module never writes the
graph and never persists a message: persistence is the route's, via
`on_complete`.

Exactly one of `on_complete` / `legacy_fallback` runs per turn — see
`stream_agent_turn` for the rungs.
"""

from __future__ import annotations

import logging
from typing import Any, AsyncIterator, Awaitable, Callable

from pydantic_ai.exceptions import UnexpectedModelBehavior, UsageLimitExceeded

from services.agent_events import SaplingEvent

logger = logging.getLogger(__name__)


def merge_graph_updates(updates: list[dict]) -> dict:
    """Merge tool-emitted payloads into one {key: [items]} dict.

    Mirrors the merge in `routes.learn._chat_via_agent` verbatim: keys
    concatenate (setdefault + extend), never clobber.
    """
    merged: dict = {}
    for gu in updates:
        for key, items in gu.items():
            merged.setdefault(key, []).extend(items)
    return merged


def _text_from(event: Any) -> str | None:
    """Extract a text chunk from a stream event, or None.

    Handles BOTH carriers: PartStartEvent puts the first chunk on
    `part.content`; PartDeltaEvent puts the rest on `delta.content_delta`.
    Missing either one truncates the reply.
    """
    delta = getattr(getattr(event, "delta", None), "content_delta", None)
    if isinstance(delta, str) and delta:
        return delta
    part_content = getattr(getattr(event, "part", None), "content", None)
    if isinstance(part_content, str) and part_content:
        return part_content
    return None


def _tool_name_from(event: Any) -> str | None:
    for path in ("part.tool_name", "tool_name", "result.tool_name"):
        obj: Any = event
        try:
            for attr in path.split("."):
                obj = getattr(obj, attr)
            if isinstance(obj, str):
                return obj
        except AttributeError:
            continue
    return None


async def stream_agent_turn(
    *,
    agent: Any,
    user_message: str,
    run_kwargs: dict,
    deps: Any,
    on_complete: Callable[[str, dict, list], dict | None],
    legacy_fallback: Callable[[], Awaitable[dict]] | None = None,
    request_id: str = "",
) -> AsyncIterator[SaplingEvent]:
    """Stream one agent turn as SaplingEvents.

    on_complete(reply, merged_graph_update, mastery_changes) -> extra `done`
    data. It persists; it is called exactly once, after the run completes and
    BEFORE `done` is yielded, so a mid-generation disconnect (which cancels
    this generator at its current yield) persists nothing.

    legacy_fallback() -> awaitable returning the route's pre-agent result,
    used ONLY when the agent fails before emitting any text (Rung 1). It is
    async because the routes' legacy paths are (`_legacy_chat`). It owns its
    own persistence, so on_complete is NOT called on that branch — calling
    both double-writes.
    """
    yield SaplingEvent(type="status", step="start", message="Starting.")

    chunks: list[str] = []
    final_output: str | None = None
    # High-water marks: how much of deps.* we have already emitted.
    graph_hw = 0
    mastery_hw = 0

    try:
        async for event in agent.run_stream_events(user_message, **run_kwargs):
            text = _text_from(event)
            if text:
                chunks.append(text)
                yield SaplingEvent(
                    type="token", step="reply", message="", data={"delta": text}
                )
                continue

            cls_name = type(event).__name__

            if cls_name == "FunctionToolCallEvent":
                tool = _tool_name_from(event) or "tool"
                yield SaplingEvent(
                    type="progress", step=tool, message=f"Calling {tool}."
                )
                continue

            if cls_name == "FunctionToolResultEvent":
                # A graph tool may have just written. Emit only what is new.
                new_nodes = merge_graph_updates(deps.graph_updates[graph_hw:])
                new_mastery = deps.mastery_changes[mastery_hw:]
                graph_hw = len(deps.graph_updates)
                mastery_hw = len(deps.mastery_changes)
                if new_nodes or new_mastery:
                    yield SaplingEvent(
                        type="graph_update",
                        step="graph",
                        message="Knowledge graph updated.",
                        data={"nodes": new_nodes, "mastery_changes": new_mastery},
                    )
                continue

            if cls_name == "AgentRunResultEvent":
                output = getattr(getattr(event, "result", None), "output", None)
                if isinstance(output, str):
                    final_output = output

    except (UsageLimitExceeded, UnexpectedModelBehavior, Exception) as exc:
        if chunks:
            # Rung 2: text already shown. Never silently re-run — the user
            # would see the reply restart. Terminal error; persist nothing.
            logger.warning("Chat stream failed mid-generation", exc_info=exc)
            yield SaplingEvent(
                type="error",
                step="reply",
                message="The tutor was interrupted. Please retry.",
                data={"request_id": request_id},
            )
            return

        # Rung 1: nothing shown yet — degrade to the route's legacy path.
        logger.warning("Chat agent failed before first token; using legacy", exc_info=exc)
        if legacy_fallback is None:
            yield SaplingEvent(
                type="error",
                step="reply",
                message="The tutor is unavailable. Please retry.",
                data={"request_id": request_id},
            )
            return
        try:
            legacy = await legacy_fallback()
        except Exception:
            logger.exception("Legacy fallback also failed")
            yield SaplingEvent(
                type="error",
                step="reply",
                message="The tutor is unavailable. Please retry.",
                data={"request_id": request_id},
            )
            return
        # legacy_fallback persisted its own rows; do NOT call on_complete.
        yield SaplingEvent(
            type="token", step="reply", message="",
            data={"delta": legacy.get("reply", "")},
        )
        yield SaplingEvent(
            type="done", step="reply", message="Complete.", data=legacy
        )
        return

    reply = final_output if final_output is not None else "".join(chunks)
    merged = merge_graph_updates(deps.graph_updates)
    mastery = list(deps.mastery_changes)

    extra = on_complete(reply, merged, mastery) or {}

    yield SaplingEvent(
        type="done",
        step="reply",
        message="Complete.",
        data={
            "reply": reply,
            "graph_update": merged,
            "mastery_changes": mastery,
            **extra,
        },
    )
```

- [ ] **Step 2: Verify it imports and lints**

Run from `backend/`:

```bash
venv/bin/python -c "from services.chat_stream import stream_agent_turn, merge_graph_updates; print('ok')" && ruff check services/chat_stream.py
```

Expected: `ok`, ruff clean. (Behavior is proven in Task 4 — this step only catches syntax/import errors.)

- [ ] **Step 3: Commit**

```bash
git add backend/services/chat_stream.py
git commit -m "feat(chat): add stream_agent_turn — Pydantic AI run → SaplingEvents (#70, #74)"
```

---

### Task 4: Test `stream_agent_turn`

**Files:**
- Create: `backend/tests/test_chat_stream.py`

**Interfaces:**
- Consumes: `stream_agent_turn`, `merge_graph_updates` (Task 3).
- Produces: nothing consumed downstream.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_chat_stream.py
"""Unit tests for services/chat_stream.py against a fake event stream.

No live LLM: FakeAgent yields stand-ins whose CLASS NAMES and attribute
shapes match Pydantic AI 1.89.1 (verified by inspection), which is all
stream_agent_turn dispatches on.
"""
import pytest

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

@pytest.mark.asyncio
async def test_first_chunk_from_part_start_is_not_dropped():
    """PartStartEvent carries the reply's FIRST chunk. Regression: handling
    only PartDeltaEvent silently truncates the opening."""
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


@pytest.mark.asyncio
async def test_event_order_and_single_persistence():
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


@pytest.mark.asyncio
async def test_graph_update_emitted_once_per_new_write():
    """High-water mark: an already-emitted delta must not re-emit on the
    next tool result."""
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


# ── failure rungs ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_rung1_failure_before_any_token_uses_legacy_and_skips_on_complete():
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


@pytest.mark.asyncio
async def test_rung2_failure_after_tokens_errors_and_persists_nothing():
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


@pytest.mark.asyncio
async def test_cancel_mid_stream_persists_nothing():
    """Client disconnect cancels the generator at its current yield."""
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
```

- [ ] **Step 2: Run to verify they fail meaningfully**

Run: `venv/bin/python -m pytest tests/test_chat_stream.py -q`
Expected: all pass if Task 3 is correct. **If `test_first_chunk_from_part_start_is_not_dropped` fails**, `_text_from` is not reading `part.content` — fix Task 3's helper, do not weaken the test.

If `pytest-asyncio` errors on the `@pytest.mark.asyncio` marks, check `pytest.ini`/`pyproject` for `asyncio_mode`; if it is `auto`, drop the marks.

- [ ] **Step 3: Run the full suite for regressions**

Run: `venv/bin/python -m pytest tests/ -q 2>&1 | tail -5 && ruff check .`
Expected: no NEW failures. Known pre-existing on clean main: 2 `storage_service`, 1 OCR event-loop flake.

- [ ] **Step 4: Commit**

```bash
git add backend/tests/test_chat_stream.py
git commit -m "test(chat): cover stream_agent_turn ordering, deltas, and fallback rungs (#70, #74)"
```

---

### Task 5: Wire the two stream routes

**Files:**
- Modify: `backend/routes/learn.py` — extract `_prepare_chat_run()` from `_chat_via_agent` (currently `:501-601`); add two routes after `chat()` (`:658-714`).
- Test: `backend/tests/test_learn_stream_routes.py` (create)

**Interfaces:**
- Consumes: `stream_agent_turn`, `merge_graph_updates` (Task 3).
- Produces: `POST /api/learn/chat/stream`, `POST /api/learn/start-session/stream`.

- [ ] **Step 1: Extract `_prepare_chat_run` and keep `_chat_via_agent` on it**

The context assembly currently inside `_chat_via_agent` (`learn.py:530-581`: deps, catalog chunk, RAG, shared-context constraint, model override, model settings) must be shared verbatim by both paths — not copy-pasted. Add above `_chat_via_agent`:

```python
def _prepare_chat_run(
    *,
    user_id: str,
    session_id: str,
    course_id: str,
    mode: str,
    user_message: str,
    message_history: list,
    use_shared_context: bool,
    request_id: str,
    model_pref: str | None = None,
) -> tuple:
    """Build (agent, assembled_message, run_kwargs, deps) for a chat turn.

    Shared verbatim by the JSON path (`_chat_via_agent`) and the streaming
    route so prompt assembly never forks. Extracted from `_chat_via_agent`;
    behavior is unchanged.
    """
    agent = agent_for_mode(mode)

    deps = SaplingDeps(
        user_id=user_id,
        course_id=course_id or None,
        supabase=None,
        request_id=request_id,
        session_id=session_id,
    )

    bu_code = _get_course_info(course_id).get("course_code") if course_id else None
    context_blocks: list[str] = []
    if bu_code:
        catalog_text = _get_catalog_chunk(bu_code)
        if catalog_text:
            context_blocks.append("COURSE CATALOG INFO (official BU course data):\n\n" + catalog_text)

        from services.rag_service import retrieve_chunks, format_rag_context
        rag_chunks = retrieve_chunks(user_message, course_id=bu_code, k=5)
        rag_block = format_rag_context(rag_chunks)
        if rag_block:
            context_blocks.append(rag_block)

    if context_blocks:
        user_message = "\n\n".join(context_blocks) + "\n\n[STUDENT QUESTION]\n" + user_message

    if not use_shared_context:
        user_message = (
            user_message
            + "\n\n[Constraint: do not call any class-aggregate tool — "
            "student opted out of shared context.]"
        )

    model_override = _resolve_model_pref(model_pref)
    run_kwargs: dict = {
        "deps": deps,
        "message_history": message_history,
        "usage_limits": ORCHESTRATOR_LIMITS,
    }
    if model_override is not None:
        run_kwargs["model"] = model_override
    if model_pref != "fast":
        run_kwargs["model_settings"] = _build_pro_model_settings()

    return agent, user_message, run_kwargs, deps
```

Then replace the body of `_chat_via_agent` from `agent = agent_for_mode(mode)` through the `run_kwargs` construction with:

```python
    agent, user_message, run_kwargs, deps = _prepare_chat_run(
        user_id=user_id,
        session_id=session_id,
        course_id=course_id,
        mode=mode,
        user_message=user_message,
        message_history=message_history,
        use_shared_context=use_shared_context,
        request_id=request_id,
        model_pref=model_pref,
    )
```

Leave the rest of `_chat_via_agent` (the `await agent.run(...)`, merge, and return) exactly as it is.

- [ ] **Step 2: Verify the JSON path still passes**

Run: `venv/bin/python -m pytest tests/test_learn_routes.py tests/test_chat_context_tools.py -q`
Expected: PASS — a pure extraction must not change behavior.

- [ ] **Step 3: Add the imports and the two routes**

Add to the imports at the top of `learn.py`:

```python
from sse_starlette.sse import EventSourceResponse

from services.agent_events import sapling_event_to_sse
from services.chat_stream import stream_agent_turn
```

Add after `chat()` (i.e. after `learn.py:714`):

```python
@router.post("/chat/stream")
async def chat_stream(body: ChatBody, request: Request):
    """SSE token-streaming chat turn (#70) with live graph deltas (#74).

    The JSON /chat route stays the non-streaming fallback (ADR 0001). No DBOS
    wrap here — stream routes are deliberately outside durable execution
    (ADR 0011); retries are client-driven and idempotent via X-Request-ID.
    """
    require_self(body.user_id, request)
    _consume_pending(body.session_id, body.user_id)

    request_id = (
        getattr(request.state, "request_id", None)
        or current_request_id()
        or str(uuid.uuid4())
    )

    offering_id = _get_session_offering_id(body.session_id)
    course_id = offering_course_id(offering_id) if offering_id else ""
    # Load prior turns BEFORE the new user row is written, so history is
    # conversation state up to (not including) this turn.
    message_history = _load_message_history(body.session_id)

    agent, assembled, run_kwargs, deps = _prepare_chat_run(
        user_id=body.user_id,
        session_id=body.session_id,
        course_id=course_id,
        mode=body.mode,
        user_message=body.message,
        message_history=message_history,
        use_shared_context=body.use_shared_context,
        request_id=request_id,
        model_pref=body.model_pref,
    )

    def _persist(reply: str, graph_update: dict, mastery_changes: list) -> dict:
        # Mirrors chat()'s ordering: user row, then assistant row. Runs only
        # after the agent run completes, so a disconnect mid-generation
        # persists nothing. Encryption happens inside save_message.
        save_message(body.session_id, "user", body.message)
        save_message(body.session_id, "assistant", reply, graph_update or None)
        return {}

    async def _legacy() -> dict:
        # Rung 1 only (agent failed before any token). _legacy_chat persists
        # its own user + assistant rows, so _persist must not also run —
        # stream_agent_turn enforces that exclusivity.
        return await _legacy_chat(body, request)

    async def event_stream():
        async for ev in stream_agent_turn(
            agent=agent,
            user_message=assembled,
            run_kwargs=run_kwargs,
            deps=deps,
            on_complete=_persist,
            legacy_fallback=_legacy,
            request_id=request_id,
        ):
            yield sapling_event_to_sse(ev)

    return EventSourceResponse(
        event_stream(), headers={"X-Request-ID": request_id}
    )
```

- [ ] **Step 4: Verify the chat stream route end to end at the unit level**

Run: `venv/bin/python -m pytest tests/test_chat_stream.py -q && ruff check routes/learn.py services/chat_stream.py`
Expected: PASS, ruff clean. (Route tests land in Step 6.)

- [ ] **Step 5: Add the start-session stream route**

```python
@router.post("/start-session/stream")
async def start_session_stream(body: StartSessionBody, request: Request):
    """Streamed session opener — closes ADR-0015's start_session TODO by
    running chat_tutor_agent instead of call_gemini_multiturn, and removes a
    legacy call site on the primary path (#152/#151).

    The JSON /start-session route is unchanged and remains the fallback.
    PENDING_SESSIONS lazy materialization is preserved exactly: the row is
    still written on first chat, by _consume_pending.
    """
    require_self(body.user_id, request)
    request_id = (
        getattr(request.state, "request_id", None)
        or current_request_id()
        or str(uuid.uuid4())
    )
    session_id = str(uuid.uuid4())

    course_id = body.course_id or _get_course_id_for_topic(body.topic, body.user_id)
    offering_id = resolve_offering(course_id, create=True) if course_id else ""

    user_message = (
        f"Student wants to learn about: {body.topic}\n\n"
        "Begin the session with a warm greeting and your first question or explanation."
    )

    agent, assembled, run_kwargs, deps = _prepare_chat_run(
        user_id=body.user_id,
        session_id=session_id,
        course_id=course_id,
        mode=body.mode,
        user_message=user_message,
        message_history=[],
        use_shared_context=body.use_shared_context,
        request_id=request_id,
        model_pref=body.model_pref,
    )

    def _stash(reply: str, graph_update: dict, mastery_changes: list) -> dict:
        # Same lazy contract as the JSON route: nothing hits `sessions` until
        # the first chat turn calls _consume_pending.
        PENDING_SESSIONS[session_id] = {
            "user_id": body.user_id,
            "mode": body.mode,
            "topic": body.topic,
            "course_id": course_id,
            "offering_id": offering_id,
            "use_shared_context": body.use_shared_context,
            "assistant_reply": reply,
            "graph_update": graph_update,
        }
        return {"session_id": session_id, "graph_state": get_graph(body.user_id)}

    async def event_stream():
        async for ev in stream_agent_turn(
            agent=agent,
            user_message=assembled,
            run_kwargs=run_kwargs,
            deps=deps,
            on_complete=_stash,
            legacy_fallback=None,
            request_id=request_id,
        ):
            yield sapling_event_to_sse(ev)

    return EventSourceResponse(
        event_stream(), headers={"X-Request-ID": request_id}
    )
```

> `legacy_fallback=None` here is deliberate: the JSON `/start-session` remains reachable, and the client's Rung-3 fallback covers this route. A `None` fallback yields a terminal `error`, which the client handles.

- [ ] **Step 6: Write route tests**

```python
# backend/tests/test_learn_stream_routes.py
"""Route-level tests for the SSE chat streams."""
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def _sse_events(text: str) -> list[str]:
    """Event names from a raw SSE body."""
    return [
        line.split("event:", 1)[1].strip()
        for line in text.splitlines()
        if line.startswith("event:")
    ]


class TestChatStream:
    def test_streams_tokens_then_done(self):
        async def fake_stream(**kwargs):
            from services.agent_events import SaplingEvent
            yield SaplingEvent(type="status", step="start", message="Starting.")
            yield SaplingEvent(type="token", step="reply", message="", data={"delta": "Hi"})
            kwargs["on_complete"]("Hi", {}, [])
            yield SaplingEvent(type="done", step="reply", message="Complete.",
                               data={"reply": "Hi", "graph_update": {}, "mastery_changes": []})

        saved = []
        with patch("routes.learn.stream_agent_turn", fake_stream), \
             patch("routes.learn._prepare_chat_run",
                   return_value=(MagicMock(), "msg", {}, MagicMock())), \
             patch("routes.learn._consume_pending"), \
             patch("routes.learn._get_session_offering_id", return_value="off-1"), \
             patch("routes.learn.offering_course_id", return_value="c1"), \
             patch("routes.learn._load_message_history", return_value=[]), \
             patch("routes.learn.save_message", side_effect=lambda *a, **k: saved.append(a)):
            r = client.post("/api/learn/chat/stream", json={
                "session_id": "s1", "user_id": "u1", "message": "hello", "mode": "socratic",
            })

        assert r.status_code == 200
        assert "text/event-stream" in r.headers["content-type"]
        assert _sse_events(r.text) == ["status", "token", "done"]
        assert [a[1] for a in saved] == ["user", "assistant"], "user row persists before assistant"

    def test_requires_self(self):
        with patch("routes.learn.require_self",
                   side_effect=Exception("forbidden")), \
             patch("routes.learn._consume_pending"):
            try:
                r = client.post("/api/learn/chat/stream", json={
                    "session_id": "s1", "user_id": "someone-else",
                    "message": "hi", "mode": "socratic",
                })
                assert r.status_code >= 400
            except Exception:
                pass  # guard raised before the response — also acceptable


class TestStartSessionStream:
    def test_stashes_pending_session_and_does_not_write_db(self):
        async def fake_stream(**kwargs):
            from services.agent_events import SaplingEvent
            extra = kwargs["on_complete"]("Welcome!", {}, [])
            yield SaplingEvent(type="done", step="reply", message="Complete.",
                               data={"reply": "Welcome!", **extra})

        from routes.learn import PENDING_SESSIONS
        PENDING_SESSIONS.clear()

        with patch("routes.learn.stream_agent_turn", fake_stream), \
             patch("routes.learn._prepare_chat_run",
                   return_value=(MagicMock(), "msg", {}, MagicMock())), \
             patch("routes.learn._get_course_id_for_topic", return_value="c1"), \
             patch("routes.learn.resolve_offering", return_value="off-1"), \
             patch("routes.learn.get_graph", return_value={"nodes": []}), \
             patch("routes.learn.table") as tbl:
            r = client.post("/api/learn/start-session/stream", json={
                "user_id": "u1", "topic": "Eigenvalues", "mode": "socratic",
            })

        assert r.status_code == 200
        assert len(PENDING_SESSIONS) == 1, "session must be stashed, not written"
        stashed = next(iter(PENDING_SESSIONS.values()))
        assert stashed["assistant_reply"] == "Welcome!"
        assert stashed["topic"] == "Eigenvalues"
        tbl.assert_not_called()
```

- [ ] **Step 7: Run the tests**

Run: `venv/bin/python -m pytest tests/test_learn_stream_routes.py -q`
Expected: PASS. If TestClient blocks on the stream, confirm the route returns `EventSourceResponse` (TestClient buffers SSE bodies fine; an infinite generator would hang — these fakes are finite).

- [ ] **Step 8: Full suite + lint, then commit**

```bash
venv/bin/python -m pytest tests/ -q 2>&1 | tail -5
ruff check .
git add backend/routes/learn.py backend/services/chat_stream.py backend/tests/test_learn_stream_routes.py backend/tests/test_chat_stream.py
git commit -m "feat(learn): SSE streaming routes for chat + start-session (#70, #74)"
```

---

### Task 6: `streamSSE` stall guard

**Files:**
- Modify: `frontend/src/lib/sse.ts:29-40`
- Test: `frontend/src/lib/sse.test.ts` (extend)

**Interfaces:**
- Consumes: existing `streamSSE(url, init)`.
- Produces: `streamSSE(url, init, opts?: { idleTimeoutMs?: number })`. Task 7 passes `{ idleTimeoutMs: 45000 }`.

- [ ] **Step 1: Write the failing test**

Append to `frontend/src/lib/sse.test.ts`:

```ts
it('rejects when no event arrives within idleTimeoutMs', async () => {
  const stalledBody = new ReadableStream({
    start() { /* never enqueues, never closes */ },
  });
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(
    new Response(stalledBody, { status: 200 }) as never,
  );

  const iterate = async () => {
    // eslint-disable-next-line @typescript-eslint/no-unused-vars
    for await (const _e of streamSSE('/x', {}, { idleTimeoutMs: 20 })) { /* drain */ }
  };
  await expect(iterate()).rejects.toThrow(/stalled/i);
});
```

- [ ] **Step 2: Run it to verify it fails**

Run from `frontend/`: `npx vitest run src/lib/sse.test.ts`
Expected: FAIL — the test times out or errors on the unexpected third argument.

- [ ] **Step 3: Implement the guard**

In `frontend/src/lib/sse.ts`, change the signature and the read loop:

```ts
export async function* streamSSE<T = unknown>(
  url: string,
  init: RequestInit,
  opts: { idleTimeoutMs?: number } = {},
): AsyncGenerator<SSEEvent<T>> {
  const res = await fetch(url, init);
  // ... unchanged through `const reader = res.body.getReader();`
```

Then wrap each `reader.read()`:

```ts
      // A stalled stream (proxy dropped it, backend wedged) otherwise hangs
      // the composer forever with no error. Race each read against a timer.
      const { value, done } = opts.idleTimeoutMs
        ? await Promise.race([
            reader.read(),
            new Promise<never>((_, reject) =>
              setTimeout(
                () => reject(new Error('Stream stalled — no data received.')),
                opts.idleTimeoutMs,
              ),
            ),
          ])
        : await reader.read();
```

The existing `finally { await reader.cancel(); reader.releaseLock(); }` already releases the reader when the race rejects.

- [ ] **Step 4: Run tests**

Run: `npx vitest run src/lib/sse.test.ts && npm run typecheck`
Expected: PASS, including the pre-existing sse tests.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/sse.ts frontend/src/lib/sse.test.ts
git commit -m "feat(sse): add optional idleTimeoutMs stall guard to streamSSE (#70)"
```

---

### Task 7: `streamChat()` consumer

**Files:**
- Modify: `frontend/src/lib/api.ts` (add near `sendChat`, `:112-130`)
- Test: `frontend/src/lib/api.stream.test.ts` (create)

**Interfaces:**
- Consumes: `streamSSE` with `idleTimeoutMs` (Task 6).
- Produces:
  ```ts
  type GraphDelta = { nodes: Record<string, unknown[]>; mastery_changes: MasteryChange[] };
  type ChatResult = { reply: string; graph_update: any; mastery_changes: any[]; session_id?: string; graph_state?: any };
  streamChat(sessionId, userId, message, mode, useSharedContext, modelPref, handlers): Promise<ChatResult>
  ```
  Task 9 (Learn.tsx) calls it.

- [ ] **Step 1: Write the failing test**

```ts
// frontend/src/lib/api.stream.test.ts
import { describe, it, expect, vi, afterEach } from 'vitest';

function sseBody(blocks: string[]): ReadableStream {
  const enc = new TextEncoder();
  return new ReadableStream({
    start(c) {
      for (const b of blocks) c.enqueue(enc.encode(b));
      c.close();
    },
  });
}

const ev = (name: string, data: unknown) =>
  `event: ${name}\ndata: ${JSON.stringify(data)}\n\n`;

afterEach(() => vi.restoreAllMocks());

describe('streamChat', () => {
  it('accumulates tokens, surfaces graph deltas, resolves on done', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(
        sseBody([
          ev('status', { type: 'status', step: 'start', message: '' }),
          ev('token', { type: 'token', step: 'reply', message: '', data: { delta: 'Hel' } }),
          ev('token', { type: 'token', step: 'reply', message: '', data: { delta: 'lo' } }),
          ev('graph_update', {
            type: 'graph_update', step: 'graph', message: '',
            data: { nodes: { new_nodes: [{ name: 'Eigen' }] }, mastery_changes: [] },
          }),
          ev('done', {
            type: 'done', step: 'reply', message: '',
            data: { reply: 'Hello', graph_update: {}, mastery_changes: [] },
          }),
        ]),
        { status: 200 },
      ) as never,
    );

    const { streamChat } = await import('./api');
    const tokens: string[] = [];
    const deltas: unknown[] = [];
    const result = await streamChat('s1', 'u1', 'hi', 'socratic', true, undefined, {
      onToken: (t) => tokens.push(t),
      onGraphUpdate: (d) => deltas.push(d),
    });

    expect(tokens).toEqual(['Hel', 'lo']);
    expect(deltas).toHaveLength(1);
    expect(result.reply).toBe('Hello');
  });

  it('rejects on a mid-stream error event', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(
        sseBody([
          ev('token', { type: 'token', step: 'reply', message: '', data: { delta: 'Half' } }),
          ev('error', { type: 'error', step: 'reply', message: 'Interrupted.', data: { request_id: 'r1' } }),
        ]),
        { status: 200 },
      ) as never,
    );
    const { streamChat } = await import('./api');
    await expect(
      streamChat('s1', 'u1', 'hi', 'socratic', true, undefined, { onToken: () => {} }),
    ).rejects.toThrow(/interrupted/i);
  });

  it('rejects when the stream never sends done', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(
        sseBody([ev('token', { type: 'token', step: 'reply', message: '', data: { delta: 'x' } })]),
        { status: 200 },
      ) as never,
    );
    const { streamChat } = await import('./api');
    await expect(
      streamChat('s1', 'u1', 'hi', 'socratic', true, undefined, { onToken: () => {} }),
    ).rejects.toThrow(/without a done/i);
  });
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `npx vitest run src/lib/api.stream.test.ts`
Expected: FAIL — `streamChat` is not exported.

- [ ] **Step 3: Implement**

Add to `frontend/src/lib/api.ts` below `sendChat`:

```ts
export interface MasteryChange { concept: string; before: number; after: number }

export interface GraphDelta {
  nodes: Record<string, Array<Record<string, unknown>>>;
  mastery_changes: MasteryChange[];
}

export interface ChatResult {
  reply: string;
  graph_update: any;
  mastery_changes: MasteryChange[];
  session_id?: string;
  graph_state?: any;
}

interface StreamEvent {
  type: string;
  step: string;
  message: string;
  data?: Record<string, any> | null;
}

export interface StreamChatHandlers {
  onToken?: (delta: string) => void;
  onGraphUpdate?: (delta: GraphDelta) => void;
  signal?: AbortSignal;
}

const STREAM_IDLE_MS = 45_000;

async function consumeChatStream(
  path: string,
  payload: Record<string, unknown>,
  { onToken, onGraphUpdate, signal }: StreamChatHandlers,
): Promise<ChatResult> {
  const { streamSSE } = await import('./sse');
  let result: ChatResult | null = null;

  for await (const e of streamSSE<StreamEvent>(
    `${API_URL}${path}`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
      credentials: 'include',
      signal,
    },
    { idleTimeoutMs: STREAM_IDLE_MS },
  )) {
    const ev = e.data;
    if (ev.type === 'token') onToken?.(String(ev.data?.delta ?? ''));
    else if (ev.type === 'graph_update') onGraphUpdate?.(ev.data as unknown as GraphDelta);
    else if (ev.type === 'error') throw new Error(ev.message || 'The tutor was interrupted.');
    else if (ev.type === 'done') result = ev.data as unknown as ChatResult;
  }

  if (!result) throw new Error('Chat stream ended without a done event.');
  return result;
}

export const streamChat = (
  sessionId: string,
  userId: string,
  message: string,
  mode: string,
  useSharedContext = true,
  modelPref?: ModelPref,
  handlers: StreamChatHandlers = {},
) =>
  consumeChatStream(
    '/api/learn/chat/stream',
    {
      session_id: sessionId,
      user_id: userId,
      message,
      mode,
      use_shared_context: useSharedContext,
      ...(modelPref ? { model_pref: modelPref } : {}),
    },
    handlers,
  );

export const startSessionStream = (
  userId: string,
  topic: string,
  mode: string,
  useSharedContext = true,
  courseId?: string,
  modelPref?: ModelPref,
  handlers: StreamChatHandlers = {},
) =>
  consumeChatStream(
    '/api/learn/start-session/stream',
    {
      user_id: userId,
      topic,
      mode,
      use_shared_context: useSharedContext,
      course_id: courseId,
      ...(modelPref ? { model_pref: modelPref } : {}),
    },
    handlers,
  );
```

- [ ] **Step 4: Run tests**

Run: `npx vitest run src/lib/api.stream.test.ts && npm run typecheck`
Expected: 3 passed, typecheck clean.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/api.ts frontend/src/lib/api.stream.test.ts
git commit -m "feat(api): add streamChat/startSessionStream SSE consumers (#70, #74)"
```

---

### Task 8: ChatPanel streaming bubble

**Files:**
- Modify: `frontend/src/components/ChatPanel.tsx`

**Interfaces:**
- Consumes: nothing new from earlier tasks directly — Learn.tsx (Task 9) drives it via props.
- Produces: `ChatPanel` accepts `streamingText?: string | null` and `onStop?: () => void`. Task 9 passes both.

Read the file first — its existing message/props shape decides the exact edit.

- [ ] **Step 1: Add the props and render the live bubble**

Add to the component's props interface:

```ts
  /** Assistant text arriving token-by-token; null when not streaming.
   *  Rendered as a live bubble below the settled messages, then replaced by
   *  the real message once the `done` event lands. */
  streamingText?: string | null;
  /** Abort the in-flight turn. Shown only while streaming. */
  onStop?: () => void;
```

Render after the settled-message list, before the composer, following the file's existing assistant-bubble markup (reuse `MarkdownChat` exactly as settled messages do — do not fork the renderer):

```tsx
{streamingText !== null && streamingText !== undefined && (
  <div className="chat-bubble chat-bubble--assistant" aria-live="polite">
    {streamingText === ''
      ? <TypingIndicator />
      : <MarkdownChat>{streamingText}</MarkdownChat>}
  </div>
)}
```

If no `TypingIndicator` exists in the codebase, use the file's existing loading affordance rather than inventing one.

- [ ] **Step 2: Disable the composer and show Stop while streaming**

Where the send button/composer disabled state is computed, include `streamingText !== null && streamingText !== undefined`. Render the Stop control next to send when streaming:

```tsx
{onStop && streamingText !== null && streamingText !== undefined && (
  <button type="button" className="btn btn--sm" onClick={onStop}>Stop</button>
)}
```

- [ ] **Step 3: Verify**

Run from `frontend/`: `npm run typecheck && npx eslint src/components/ChatPanel.tsx`
Expected: clean.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/ChatPanel.tsx
git commit -m "feat(chat): streaming assistant bubble + stop control (#70)"
```

---

### Task 9: Wire Learn.tsx — stream, reduce deltas, fall back

**Files:**
- Modify: `frontend/src/components/screens/Learn.tsx` (the send handler at `:300` calls `sendChat` today; `graphNodes` state at `:128,147`)

**Interfaces:**
- Consumes: `streamChat`, `GraphDelta`, `ChatResult` (Task 7); `ChatPanel`'s `streamingText` / `onStop` (Task 8).
- Produces: end-user behavior. Terminal task.

- [ ] **Step 1: Add streaming state and the graph reducer**

```tsx
  const [streamingText, setStreamingText] = React.useState<string | null>(null);
  const streamAbort = React.useRef<AbortController | null>(null);

  // Upsert streamed graph deltas into graphNodes so the Progress card's
  // existing useMemo recomputes — no refetch, no extra round-trip (#74).
  const applyGraphDelta = React.useCallback((delta: GraphDelta) => {
    const incoming = Object.values(delta.nodes ?? {}).flat() as Array<Record<string, any>>;
    if (!incoming.length) return;
    setGraphNodes((prev) => {
      const byId = new Map(prev.map((n) => [n.id, n]));
      for (const node of incoming) {
        const id = node.id ?? node.node_id;
        if (!id) continue;
        const existing = byId.get(id);
        byId.set(id, existing ? { ...existing, ...node } : (node as any));
      }
      return Array.from(byId.values());
    });
  }, []);
```

Import `streamChat` and the types alongside the existing `sendChat` import.

- [ ] **Step 2: Stream the turn, with the Rung-3 fallback**

Replace the `const res = await sendChat(...)` call at `:300` with:

```tsx
      const controller = new AbortController();
      streamAbort.current = controller;
      setStreamingText('');
      let sawToken = false;
      let res: ChatResult;
      try {
        res = await streamChat(sessionId, userId, userText, mode, sharedCtx, modelPref, {
          onToken: (delta) => {
            sawToken = true;
            setStreamingText((t) => (t ?? '') + delta);
          },
          onGraphUpdate: applyGraphDelta,
          signal: controller.signal,
        });
      } catch (err) {
        if (controller.signal.aborted) throw err;   // user pressed Stop
        if (sawToken) throw err;                    // Rung 2: interrupted, surface it
        // Rung 3: the stream never produced text — retry non-streaming.
        res = await sendChat(sessionId, userId, userText, mode, sharedCtx, modelPref);
      } finally {
        setStreamingText(null);
        streamAbort.current = null;
      }
```

The existing code after this point — appending the assistant message from `res.reply`, handling `res.mastery_changes` — is unchanged, because `done` returns the same shape the JSON route does.

- [ ] **Step 3: Wire Stop and unmount cleanup**

Pass to `<ChatPanel>`: `streamingText={streamingText}` and `onStop={() => streamAbort.current?.abort()}`.

Add the cleanup effect (guards the #131/#133 leaked-stream class):

```tsx
  React.useEffect(() => () => streamAbort.current?.abort(), []);
```

- [ ] **Step 4: Verify**

Run from `frontend/`: `npm run typecheck && npx eslint src/components/screens/Learn.tsx && npx vitest run`
Expected: all clean.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/screens/Learn.tsx
git commit -m "feat(learn): stream tutor replies with live graph deltas (#70, #74)"
```

- [ ] **Step 6: Manual e2e smoke (required before the PR)**

Run the backend (`venv/bin/python main.py`) and frontend (`npm run dev`), then verify each:

1. A tutor turn renders text progressively — not one blob at the end.
2. When the tutor moves mastery, the Progress card updates **mid-turn**, with no refetch in the Network tab.
3. Stop mid-generation halts the text; the message does not appear in history after a reload.
4. Kill the backend mid-generation → the bubble shows interrupted; after restart+reload, **no phantom partial message** in history.
5. Point the frontend at a backend with the stream route disabled (or return 500 from it) → the turn still completes via the JSON fallback.

Record the results in the PR body. If #2 fails, check `deps.graph_updates` is actually populated at tool-result time — that is the #74 acceptance.

- [ ] **Step 7: Open the PR**

```bash
git push -u origin feat/streaming-tutor
gh pr create --base main \
  --title "feat(learn): stream tutor replies over SSE with live graph deltas (#70, #74)" \
  --body "Implements docs/superpowers/specs/2026-07-16-streaming-design.md.

Closes #70
Closes #74

Also: migrates start_session onto chat_tutor_agent (closes ADR-0015's TODO, removes a legacy call_gemini_multiturn site from the primary path — progress on #152/#151).

## Verification
<paste the Step 6 smoke results>

🤖 Generated with [Claude Code](https://claude.com/claude-code)"
```

---

## Self-Review

**Spec coverage:** every spec section maps to a task — event vocabulary → 2; `chat_stream.py` incl. high-water marks, persistence contract, cancellation → 3, 4; `_prepare_chat_run` extraction, both routes, start-session `PENDING_SESSIONS` contract → 5; stall timeout → 6; consumer → 7; bubble states → 8; reducer, rollout with fallback, e2e smoke → 9. The ADR-0012 gate → 1.

**Known gaps, deliberately left to the implementer:**
- Task 8's exact JSX depends on `ChatPanel.tsx`'s current markup, which the task says to read first. The props contract is pinned; the markup is not.
- The `failed/stopped` bubble state from the spec is implemented as "clear the streaming bubble and surface the error through Learn's existing error handling" rather than a bespoke interrupted-bubble UI. If the spec's "keep the partial text, mark it interrupted" affordance is wanted verbatim, it needs a follow-up task once ChatPanel's error surface is known.

**Type consistency:** `stream_agent_turn`'s signature is identical across Tasks 3, 4, and 5 — `legacy_fallback` is `Callable[[], Awaitable[dict]] | None` everywhere, awaited in the module, async in the tests, and satisfied by `_legacy_chat` in the route. `GraphDelta` / `ChatResult` are defined in Task 7 and consumed with matching shapes in Task 9. `merge_graph_updates` is named identically throughout.

**Verified against the installed stack, not assumed:** pydantic-ai is 1.89.1 in `backend/venv`; `Agent.run_stream_events` exists and yields both text and tool events; the event dataclass fields in Task 3's table came from `dataclasses.fields()` inspection. `requirements.txt` pins only `>=0.0.20`, so if a future bump changes these class names, `_text_from` / `_tool_name_from` degrade to returning `None` (silent truncation) rather than raising — Task 4's `test_first_chunk_from_part_start_is_not_dropped` is the canary.
