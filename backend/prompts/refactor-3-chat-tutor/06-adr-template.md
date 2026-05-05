# 0014 — Template for ADR after refactor #3 ships

After sub-agents A-D land on `main`, write `docs/decisions/0014-refactor-3-chat-tutor-shipped.md`
using this skeleton. Mirror the shape of `docs/decisions/0013-refactor-2-quiz-shipped.md`
(what shipped, what surprised us, consequences, what to carry forward).

```markdown
# 0014: Refactor #3 (chat_tutor) shipped

- Status: accepted
- Date: <YYYY-MM-DD>
- Supersedes: refines 0001 (the migration plan)

## Context

ADR 0001 picked Pydantic AI as the agent framework. ADR 0005 named
chat tutor as refactor #3, deferred behind quiz to learn the streaming
machinery on a smaller surface first. With quiz on main and the eval
infra proven, this ADR captures what shipped for chat tutor.

## Decision

`chat_tutor_agent` lives at `backend/agents/chat_tutor.py` with three
mode-specific instances (Socratic, Expository, TeachBack), all sharing
the same tool surface (`search_course_materials`, `read_session_history`,
`read_user_progress`, `apply_graph_update_tool`). Output type is `str`
(plain Markdown reply). `routes/learn.py` dispatches to the right mode
via `agent_for_mode(body.mode)`, with the same orchestrator-vs-legacy
fallback pattern PR #67 and #71 established.

Prompt versions: <fill in three sha256[:12] hashes from agent metadata>.

Per-task model defaults to `gemini-2.5-pro` (matching main's chat
behavior post-PR #73). Override via `SAPLING_MODEL_CHAT_TUTOR`. Body's
`model_pref="fast"|"smart"` field overrides per call (already on the
chat body since PR #73; the agent path now honors it).

## What shipped

- `backend/agents/chat_tutor.py` — three Agent[SaplingDeps, str] instances.
- `backend/agents/tools/chat_context.py` — three new context tools.
- `backend/agents/_providers.py` — added `chat_tutor` task slot.
- `backend/routes/learn.py` — `_chat_via_agent` (new) and `_legacy_chat`
  (preserved). `chat`, `start_session`, `action` migrated.
- `backend/tests/evals/chat_tutor.py` — 15 cases (5 per mode), 5 evaluators.
- `backend/tests/test_chat_tutor_imports.py` — agent import smokes.
- `backend/tests/test_chat_context_tools.py` — tool unit tests.
- `backend/tests/test_learn_routes.py` — agent-success + agent-fallback
  tests added; existing tests kept by forcing legacy via autouse fixture.

## What surprised us

<Fill in during/after the refactor — typical categories:>
- Pydantic AI's `message_history` shape needed an adapter from the
  `messages` table.
- Streaming via `run_stream_events` produced X events the frontend
  doesn't render today; we either map them to existing SSE event types
  or document the gap.
- `gemini-2.5-pro`'s thinking config had to be re-enabled per
  message (commit `e146125` already did this for the legacy path; the
  agent path needs the equivalent in the model config).
- Encryption boundary on `messages.content` — every load decrypts;
  every save encrypts; agent never sees ciphertext.

## Consequences

- (+) Tutor's data lookups (course materials, progress, history) are
  observable in Logfire — replaces `build_system_prompt`'s opaque
  string augmentation.
- (+) Per-mode prompt versioning (three distinct hashes) lets us A/B
  prompt changes per mode independently.
- (+) Model selection is symmetric with quiz route — same `model_pref`
  body field, same `_resolve_model_pref` helper, same SAPLING_MODEL_*
  env-var override.
- (+) After this PR, `services/gemini_service.py::call_gemini_multiturn`
  is dead code. The only remaining caller is the quiz fallback (which
  is itself dead code on the happy path). A follow-up PR can delete
  `services/gemini_service.py` per ADR 0001's migration plan.
- (−) Three agent instances at module load instead of one. Memory cost
  is negligible (Pydantic AI agents are lightweight); just noting.
- (−) Streaming + tool calls increase round-trips vs the old single
  multi-turn call. Latency may go up; will measure in Logfire after
  ~50 chats.
- (−) Eval cassettes (15) need recording before the workflow leaves
  workflow_dispatch-only mode.

## What I'd carry into the next refactor

<Fill in based on actual experience. Likely items:>
- Encryption-aware `_load_message_history` deserves a shared helper
  (probably belongs in `services/messages.py`).
- The mode-specific agent instances pattern (build three at module
  load, dispatch via `agent_for_mode`) is reusable for any route with
  modal behavior — tutor today, future quiz-style routes tomorrow.
- The `_resolve_model_pref` helper is now duplicated across quiz and
  learn — extract to `services/model_pref.py` if a third caller appears.

## Pre-existing test failures (not caused by this refactor)

<Carry forward the same baseline as PR #67/#71:>
- `test_skips_self_edges` (live Supabase 409 in graph_service)
- `test_save_to_db`, `test_full_pipeline` (live Supabase in OCR pipeline)
```
