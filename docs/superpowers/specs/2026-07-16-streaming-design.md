# Streaming the tutor: SSE token streaming + live graph deltas

**Date:** 2026-07-16
**Owner:** Andres (AndresL230)
**Issues:** #70 (streaming text in Learn), #74 (live progress card via SSE graph deltas)
**Also advances:** #152 / #151 (retire `gemini_service`), ADR-0015's `start_session` follow-up TODO
**Status:** design approved, ready for implementation plan

## Problem

The tutor chat is request/response. `POST /api/learn/chat` runs the model to completion and
returns one JSON dict, so the student watches a spinner for the whole multi-second generation.
`POST /api/learn/start-session` is worse: it blocks on the legacy `call_gemini_multiturn` while
the model composes a greeting against a full system prompt, and that spinner opens every session.

Meanwhile the Learn page's Progress card reads `graphNodes` fetched once at bootstrap. The tutor
mutates mastery mid-session through `apply_graph_update`, but the card only reflects it after a
page reload, so it feels stale exactly when the student is making progress.

SSE plumbing already exists and is proven on the document-upload path. This design wires the same
mechanism into chat, and — because both issues need the same terminal event — implements #70 and
#74 together.

## Scope

**In scope**

- SSE token streaming for `/api/learn/chat` (#70).
- Live `graph_update` deltas on that same stream (#74).
- A shared streaming seam (`services/chat_stream.py`) that both chat routes use, so a third
  surface (notes chat) is a drop-in later.
- Migrating `start_session` onto `chat_tutor_agent` and streaming its greeting.
- One frontend consumer (`streamChat`) built on the existing `streamSSE`, plus the stall timeout
  that `sse.ts` lacks today.

**Out of scope**

- `/action` and `/mode-switch` (#70 non-goals; they stay legacy).
- Notes chat, quiz generation, study-guide streaming — the foundation makes them follow-ups.
- Streaming tool-call *progress* to the UI beyond the graph deltas #74 asks for.
- Reworking mastery computation or the agent tool surface.
- Resumable streams / two-phase upload (ADR 0010's deferred design).
- Retrofitting the document-upload pipeline. Its events are unchanged.

## Constraints (from the vault — these bind the design)

| Source | Constraint |
|---|---|
| ADR 0006 | SSE runs on `sse-starlette` + the `SaplingEvent` schema + `map_to_sapling_event`. New event types **extend** that vocabulary; we do not adopt another protocol. Frontend consumption goes through `streamSSE` — no second parser. |
| ADR 0004 | All graph mutations flow through `graph_service.apply_graph_update`. Streamed deltas must be *sourced from* the tools' writes, never a parallel write path. |
| ADR 0015 + CLAUDE.md | Encryption boundary: `_load_message_history` decrypts on read, `save_message` encrypts on write. The agent never sees ciphertext, and a token stream must not create a second, unencrypted persistence path. |
| ADR 0001 / 0015 | Legacy fallback survives. `_legacy_chat` stays callable and correct; the rollback contract is that the JSON routes still work untouched. |
| ADR 0011 | **Do not** wrap SSE stream routes in DBOS workflows — the asymmetry is deliberate. Retry safety comes from client retries + `X-Request-ID` idempotency. |
| ADR 0009 | Every stream stamps `X-Request-ID`; error payloads carry it for Logfire correlation. |
| ADR 0008 | Model choice stays in `agents/_providers.py` task slots + `SAPLING_MODEL_*` overrides. No hardcoded model in the stream module. |
| `docs/attempts/2026-05-03-vault-gap-prompts-13-14.md` | FastAPI `BackgroundTasks` **does not fire** for streaming responses. Post-stream work uses `asyncio.create_task(asyncio.to_thread(...))`. |
| ADR 0012 | Its empirical gate is still unanswered: nobody has verified that our Gemini + Pydantic AI versions emit usable incremental deltas via `run_stream`. **This design opens with a spike to close that gate.** |

## Architecture

One shared generator, two thin routes, unchanged JSON endpoints beneath as fallback.

```
Learn.tsx / ChatPanel          ← token / graph_update / done / error (SSE)
  └─ api.ts streamChat()       ← wraps lib/sse.ts streamSSE (+ idle timeout)
       └─ POST /api/learn/chat/stream · /api/learn/start-session/stream
            └─ routes/learn.py (thin: auth, history load, context assembly)
                 └─ services/chat_stream.py  ← NEW: run_stream → SaplingEvents
                      └─ chat_tutor_agent (agent_for_mode)
                           └─ apply_graph_update_tool / update_mastery_tool → deps
```

Routes stay thin: `require_self`, history load, RAG/catalog/constraint assembly (all unchanged
from today), then hand an async generator to `EventSourceResponse`.

### Event vocabulary

Three new `SaplingEventType` members. Every event keeps the existing
`{type, step, message, data}` envelope, so one parser and one switch serve every stream. The
per-token envelope overhead (~40 bytes) is deliberate: uniformity beats terseness at chat volume.

| type | status | `data` payload | meaning |
|---|---|---|---|
| `status` / `progress` / `result` / `error` | existing | unchanged | upload vocabulary, untouched; chat streams reuse `status:start`, `progress:<tool>`, and `error` |
| **`token`** | new | `{"delta": "..."}`, `step="reply"` | one text delta; client appends to the live bubble |
| **`graph_update`** | new | `{"nodes": {"new_nodes": [{concept_name, initial_mastery}], "updated_nodes": [{concept_name, mastery_delta}]}, "mastery_changes": [{concept, before, after}]}` | emitted after a graph tool result (#74); client matches by **concept name** — see the correction below |
| **`done`** | new | `{"reply", "graph_update", "mastery_changes", "session_id"?}` | terminal; canonical reply reconciles token drift. Same dict the JSON route returns today |

### Turn timeline

1. Client `POST`s; stream opens; `X-Request-ID` stamped.
2. `status:start`.
3. `token` × N.
4. `progress:update_mastery` when a graph tool fires.
5. `graph_update` — the Progress card moves live.
6. `token` × N (rest of the reply).
7. Run completes → **persist**: `save_message(user)` then `save_message(assistant, graph_update)`,
   through the existing encrypting boundary, in today's order.
8. `done`.

### Persistence contract

Messages persist exactly when the agent run completes (step 7), **before** `done` is emitted —
`done` delivery is best-effort. Consequences, stated explicitly:

- Disconnect **during** generation: the generator is cancelled at its current `yield`,
  `on_complete` never runs, nothing persists. The student resends. No partial replies in history.
- Disconnect **after** completion but before `done` lands: the turn is saved; a history refetch
  recovers it. No double-write, because persistence is keyed to run completion, not to delivery.

## Backend

### `services/chat_stream.py`

```python
async def stream_agent_turn(
    *,
    agent,                # agent_for_mode(mode)
    user_message: str,    # already RAG/context/constraint-assembled
    run_kwargs: dict,     # deps, message_history, usage_limits, model, model_settings
    deps: SaplingDeps,    # watched for graph-tool accumulation
    on_complete,          # (reply, merged_graph_update, mastery_changes) -> dict | None
                          #   persists + returns extra `done` data
    legacy_fallback,      # () -> dict | None — the route's own pre-agent path,
                          #   used only by Rung 1; owns its persistence
) -> AsyncIterator[SaplingEvent]
```

- **Context assembly stays in `learn.py`.** Today's `_chat_via_agent` splits into
  `_prepare_chat_run()` — RAG retrieval, catalog block, shared-context constraint, model-pref
  resolution — shared verbatim by the JSON and stream paths, and the run itself. No duplicated
  prompt logic.
- **Token deltas:** iterate the Pydantic AI stream (exact API pinned by the spike), yield `token`
  events. This extends the `map_to_sapling_event` mapper family rather than replacing it; the
  mapper keeps dispatching on `type(event).__name__` so version churn stays absorbed there.
- **Graph deltas:** after each tool-result event, diff `deps.graph_updates` / `deps.mastery_changes`
  against a high-water mark; yield one `graph_update` per new accumulation. The data originates
  from `apply_graph_update` via the tools (ADR 0004).
- **Completion:** build the same `{reply, graph_update, mastery_changes}` dict `_chat_via_agent`
  returns today (including the `setdefault(...).extend(...)` merge of `deps.graph_updates`), call
  `on_complete` (the route's persistence closure), yield `done`.
- **Cancellation:** client disconnect cancels the generator at its current `yield`; `on_complete`
  hasn't run, so nothing persists. No `BackgroundTasks`.
- **No DBOS wrap** (ADR 0011).

### Routes

`POST /api/learn/chat/stream` and `POST /api/learn/start-session/stream`, both
`EventSourceResponse`, both `require_self`-gated, both stamping `X-Request-ID`.

`start_session` migrates onto `chat_tutor_agent`:

- Same prompt assembly; `agent_for_mode(mode)`; greeting streams through `stream_agent_turn`.
- Graph writes happen in-band via tools (and their deltas ride the stream) instead of via
  `<graph_update>`-tag parsing.
- `on_complete` stashes `PENDING_SESSIONS[session_id]` — the lazy-materialization contract and
  `_consume_pending` are untouched.
- `done` carries `{session_id, reply, graph_update, mastery_changes, graph_state}`.

The JSON `/start-session` and `/chat` stay exactly as they are (ADR 0001/0015 rollback contract).

### Fallback ladder

1. **Agent fails before the first token** (`UsageLimitExceeded`, `UnexpectedModelBehavior`, any
   exception) → run the route's legacy path *inside* the stream and emit its reply as a single
   `token` plus a normal `done`. The client cannot tell the difference.

   Each route supplies its own legacy callable, since the two differ: `/chat/stream` falls back to
   `_legacy_chat` (which persists its own user + assistant rows); `/start-session/stream` falls
   back to the existing `start_session` body (`call_gemini_multiturn` → `extract_graph_update` →
   `apply_graph_update` → stash `PENDING_SESSIONS`).

   **When Rung 1 fires, `on_complete` must not run** — the legacy callable already owns its
   persistence, and calling both would double-write. `stream_agent_turn` therefore treats the
   legacy callable and `on_complete` as mutually exclusive branches: exactly one runs per turn.
2. **Failure mid-stream** (tokens already sent) → terminal `error` event carrying `request_id`;
   persist nothing; client marks the bubble interrupted and offers Retry. No silent auto-retry
   once text has been shown.
3. **Stream fails to open** (HTTP/network/proxy) → `streamChat` throws before any event; Learn
   transparently retries the turn via non-streaming `sendChat`, which keeps its own agent→legacy
   ladder.

## Frontend

### `api.ts`

```ts
streamChat(sessionId, userId, message, mode, useSharedContext, modelPref, {
  onToken:       (delta: string) => void,
  onGraphUpdate: (u: GraphDelta) => void,
  signal:        AbortSignal,
}): Promise<ChatResult>   // resolves on `done`; rejects on `error`, stall, or open failure
```

- Built on the existing `streamSSE`, which gains one optional `idleTimeoutMs` (default 45s): no
  event within the window aborts the reader and rejects. That is the streaming half of #192; the
  error-classification half stays in #192.
- `IS_LOCAL_MODE` never opens a stream — today's mock `sendChat` path is preserved.
- `startSessionStream` mirrors the shape and resolves with the session payload.

### `ChatPanel` — assistant bubble states

| state | behavior |
|---|---|
| **waiting** | stream open, no token yet: typing indicator; composer disabled; Stop visible |
| **streaming** | text grows per token through `MarkdownChat`; re-renders batched via `requestAnimationFrame` (one paint per frame, not per token) |
| **final** | on `done`, swap to the canonical `reply`; re-enable composer |
| **failed / stopped** | mid-stream `error` or user Stop: keep the partial text visually, mark it interrupted, offer Retry (nothing was persisted, so Retry re-sends the turn) |

Cleanup: unmount and session-switch abort the in-flight reader through the same `AbortSignal`,
guarding the #131/#133 leaked-stream bug class at one seam.

### `Learn.tsx` — graph reducer (#74)

`onGraphUpdate` upserts into `graphNodes`, and the Progress card recomputes through its existing
`useMemo` — zero extra HTTP round-trips per turn, which is #74's acceptance criterion.
`mastery_changes` accumulate in session state for the end-of-session summary, matching what the
JSON path returns today.

> **CORRECTION (2026-07-16, found during implementation — this design was wrong).**
> This spec originally specified "upsert by node id" against a payload of
> `{id, name, course_id, mastery_score, mastery_tier}`. **That payload does not exist.** The graph
> tools (`backend/agents/tools/graph.py`) append `{"new_nodes": [{concept_name, initial_mastery}]}`
> and `{"updated_nodes": [{concept_name, mastery_delta}]}` — there is **no node id** and **no
> absolute mastery score** anywhere in them. Only the sibling `mastery_changes` array carries
> authoritative absolute values, as `{concept, before, after}`.
>
> The shipped reducer therefore:
> - **matches by concept name** (case/whitespace-normalized, mirroring the backend's
>   `_normalize_concept`), keeping an id path only for forward compatibility;
> - treats **`mastery_changes` as the authority** for score updates — `mastery_delta` has no safe
>   client-side baseline to apply it against;
> - inserts unknown concepts as a `stream-<slug>` placeholder, resolving color/subject/course and
>   an edge to the subject root from the same `cardCourseId` the manual `addConcept` path uses
>   (a placeholder without those renders black and orphaned in the 3D rail);
> - ignores `new_edges` / `recommended_next` — the `GraphUpdate` type declares them, but only the
>   legacy fallback path ever populates them.
>
> Consequence worth knowing: a turn that only *adds* concepts (`new_nodes`) moves no score, because
> no `mastery_changes` are emitted. Only `update_mastery_tool` on an existing concept moves the
> Progress card.

### Rollout

Default-on with automatic fallback. No feature flag: the fallback ladder is the safety mechanism,
staging exists for pre-prod verification, and a flag would leave a cleanup chore behind.

## Testing

| Layer | Tool | What it proves |
|---|---|---|
| **Spike (first)** | throwaway script against a staging key | ADR-0012's gate: our Pydantic AI + Gemini versions really do emit incremental text deltas and mid-run tool events via `run_stream`. Pins which API the module uses. **Everything downstream depends on this.** |
| chat_stream unit | pytest + fake agent stream | event ordering (`start` → `token` → `graph_update` → `done`); persistence fires exactly once, after completion; cancel-before-completion persists nothing; Rung-1 fallback emits the legacy reply as one token; graph-delta high-water-mark diffing (no re-emission) |
| route | pytest + httpx, conftest mock Supabase | SSE wire format parses; `require_self` enforced on both stream routes; start-session stashes `PENDING_SESSIONS`; JSON routes behave identically to before |
| frontend unit | vitest (following `sse.test.ts`) | `streamChat` token accumulation, `done` resolution, mid-stream error rejection, stall timeout; reducer upsert for both existing and new nodes |
| e2e smoke | staging, manual checklist | a real tutor turn streams; the Progress card moves mid-turn; Stop works; killing the backend mid-turn yields a failed bubble and **no phantom message** in history |

## Risks

- ~~**The spike could fail**~~ — **RESOLVED 2026-07-16. ADR-0012's gate is closed.** Measured
  against `gemini-2.5-pro` via `Agent.run_stream_events`, prompt "Explain what an eigenvalue is in
  two sentences":

  ```
  EVENT COUNTS: {'PartStartEvent': 1, 'FinalResultEvent': 1, 'PartDeltaEvent': 2,
                 'PartEndEvent': 1, 'AgentRunResultEvent': 1}
  FIRST TEXT FROM: PartStartEvent -> 'An eigenvalue is the special number that tells you how much a'
  ```

  Text is genuinely incremental (multiple deltas, not one blob), so #70's premise holds. The spike
  also caught two carrier traps that would have shipped as bugs, now encoded in the plan and
  regression-tested:

  1. The reply's **first** chunk arrives on `PartStartEvent`, not `PartDeltaEvent` — handling only
     deltas drops the opening (here, the whole first sentence).
  2. `PartEndEvent` carries the **full assembled reply** on the same `part.content` attribute —
     emitting a token for it duplicates the entire reply (`"hello world"` → `"hello worldhello
     world"`, reproduced live).

  Hence `_text_from` dispatches on class name rather than duck-typing attributes.

  Note the granularity is coarse (~4 chunks for two sentences), so the win is "text appears in
  stages within ~1s" rather than a per-word typewriter. That is still a large improvement over a
  multi-second spinner, but it is worth confirming against a long reply during the Task 9 smoke.
- **Token-render cost** — a long reply re-rendering Markdown per token could jank. Mitigation:
  rAF batching, measured during the e2e smoke.
- **`learn.py` churn overlaps other work** — the file is active. Mitigation: land the spike and
  `chat_stream.py` first (additive), then the route changes in a focused diff.

## Acceptance

- #70: a tutor turn renders tokens as they arrive; Stop aborts cleanly; nothing partial persists;
  the legacy path still serves a correct turn when the agent trips.
- #74: during a live session, a model-triggered graph update moves the Progress card with no page
  reload and no extra REST round-trip.
- `start_session` runs on `chat_tutor_agent`, streams its greeting, and keeps the
  `PENDING_SESSIONS` contract intact.
- The JSON `/chat` and `/start-session` routes remain byte-compatible for non-streaming clients.
