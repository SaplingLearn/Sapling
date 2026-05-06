# Sub-agent E — Wire chat_tutor SSE events into the Learn screen (optional)

Optional follow-up — can ship as a separate PR after sub-agents A-D land
on main. The backend route in sub-agent C may already work end-to-end with
the existing frontend (chat reply streams in normally because the agent's
output type is `str`). This sub-agent adds visibility for the new tool-call
events (so the user sees "Looking up your course materials..." while the
agent is mid-flight), mirroring what document upload already does.

Repo: `/Users/josegaelcruzlopez/Documents/Startup_Projects /Sapling`
Branch: typically `refactor/3-chat-tutor-frontend` (separate PR)

## Why

Without this, the chat tutor's tool calls (`search_course_materials`,
`read_user_progress`, `apply_graph_update`) are silent — the user sees
the same "AI is thinking..." spinner whether the agent's mid-tool-call
or mid-token-generation. With this, each tool call surfaces as a
discrete progress label, same way `DocumentUploadModal.tsx` shows
"Classifying..." → "Extracting..." → "Saved.".

## What to read first

- `frontend/src/components/screens/Learn.tsx` — current Learn screen.
  Find the `sendChat` call site and the spinner/progress UX.
- `frontend/src/lib/sse.ts` — `streamSSE` is generic and reusable as-is.
- `frontend/src/lib/api.ts::sendChat` — currently a JSON POST. Add a new
  `sendChatStream(formData|body, onEvent, signal)` mirroring
  `uploadDocumentStream` from PR #67.
- `frontend/src/components/DocumentUploadModal.tsx` — pattern for
  `onEvent` callbacks updating live progress labels.
- Backend's emitted event names (defined by sub-agent C in
  `backend/services/agent_events.py::map_to_sapling_event`):
  `progress:tool_start`, `progress:tool_done`, `progress:streaming`,
  `result:reply`, `error:fallback`, `error:failed`.

## What to write

### 1. New API helper: `sendChatStream`

In `frontend/src/lib/api.ts`, add:

```ts
export type ChatEvent =
  | { type: "progress"; step: "tool_start" | "tool_done" | "streaming";
      message: string; data?: { tool?: string; tokens?: number } }
  | { type: "result"; step: "reply"; data: { reply: string; ... } }
  | { type: "error"; step: "fallback" | "failed"; message: string };

export async function sendChatStream(
  body: { session_id: string; user_id: string; message: string;
          mode: string; use_shared_context?: boolean;
          model_pref?: "fast" | "smart" | null },
  onEvent: (event: ChatEvent) => void,
  signal?: AbortSignal,
): Promise<{ reply: string; ... }> {
  // Mirror uploadDocumentStream's shape: streamSSE async generator,
  // collect final result, return when stream closes.
  ...
}
```

Don't remove the existing `sendChat` (legacy callers may still want
non-streaming JSON). Add the new one alongside it; the chat UI opts in.

### 2. Update Learn.tsx

In the `Learn` component's chat-send handler, replace `sendChat(...)`
with `sendChatStream(...)` and add an `onEvent` callback that updates
the existing typing-indicator state.

Recommended UX:
- `tool_start` event → swap "Sapling is typing..." for the tool's
  human-readable label ("Looking up your course materials...",
  "Checking your progress...", "Updating your knowledge graph...").
- `tool_done` event → revert to the typing indicator.
- `streaming` event → keep the typing indicator visible; optionally
  pre-render partial tokens if Pydantic AI streams them through.
- `result:reply` → swap the indicator for the actual rendered Markdown.
- `error:fallback` → toast.warn "Switching to legacy tutor..."
  (degraded, not failed).
- `error:failed` → toast.error "Could not get a response. Please try
  again." Keep the user's message in the input so they can retry.

### 3. Tool-name → human-label mapping

```ts
const TOOL_LABELS: Record<string, string> = {
  search_course_materials_tool: "Looking up your course materials...",
  read_user_progress_tool: "Checking your progress...",
  read_session_history_tool: "Reading earlier in this conversation...",
  apply_graph_update_tool: "Updating your knowledge graph...",
};
```

Live this near the `Learn.tsx` chat handler, not in `api.ts` — it's UX
copy, not API shape.

### 4. Tests

Add component tests to `frontend/src/components/screens/Learn.test.tsx`
(or wherever the screen tests live; create the file if needed):

- `sendChatStream` is called with the correct body fields when the user
  hits send.
- An incoming `tool_start` event with `data.tool="search_course_materials_tool"`
  surfaces the matching human-readable label.
- An incoming `error:failed` event triggers a toast and keeps the user's
  input.
- `sendChatStream`'s fetch is called with `credentials: 'include'` (auth
  cookie crosses subdomain — mirrors the contract test from PR #67).

Mirror the test patterns from `frontend/src/components/DocumentUploadModal.test.tsx`
and `frontend/src/lib/api.test.ts`.

## Verify
```bash
cd "/Users/josegaelcruzlopez/Documents/Startup_Projects /Sapling/frontend"
npm run typecheck
npm test
```

Both must pass. Add at least 3 new component/lib tests.

## Constraints

- DO NOT modify `frontend/src/lib/sse.ts` (the SSE helper is generic and
  reused — don't fork it).
- DO NOT remove `sendChat`. Some callers (e.g. session-replay flows) may
  still want the non-streaming JSON shape. The streaming variant is opt-in.
- DO NOT change the `messages` table shape or the backend's wire contract.
- DO NOT commit. No ADRs.

## Report

- Files changed/added with line counts.
- Whether streaming actually shows a difference in UX (you'll only be
  able to test the wire shape; live token-streaming behavior depends on
  Gemini and the route's `run_stream_events`).
- Test count + pass/fail.
