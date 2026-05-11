# 0017: Notetaker dynamic frontend + backend

- Status: accepted
- Date: 2026-05-11

## Context

The notetaker page (`frontend/src/app/(shell)/notetaker/page.tsx`) shipped as a static wireframe with hard-coded `SEED_NOTES` / `COURSES`. This decision records the contracts chosen when wiring it to a real backend (two encrypted tables, three Pydantic AI agents, one new router under `/api/notes`, and an API-driven page replacing the mocks).

Plan: `docs/superpowers/plans/2026-05-11-notetaker-dynamic.md`.

## Decision

### Schema

Two tables added (see `backend/db/migration_notes.sql`):

- `notes (id, user_id, course_id, title*, body*, tags text[], last_summary*, last_summary_at, created_at, updated_at)` — `*` columns are AES-GCM encrypted at the application layer via `services/encryption.py`. `tags` stays plaintext so PostgREST array filters work.
- `note_concepts (note_id REFERENCES notes ON DELETE CASCADE, concept_node_id, created_at)` — junction table linking notes to `graph_nodes`. **`concept_node_id` is intentionally not a hard FK** because `graph_nodes` uses application-managed TEXT ids; this matches the pattern already used by `graph_edges.source_node_id` / `target_node_id`.

`notes.last_summary` is denormalized on the note row rather than a separate table — single-summary-per-note is sufficient today; revisit if summary history becomes a feature.

### Agents

Three small-output-type agents under `backend/agents/`, registered in `_providers.py` (env-overridable via `SAPLING_MODEL_NOTE_*`):

- `note_summary` — flash-lite; output type `NoteSummary { summary: str }`.
- `note_concepts` — flash-lite; output type `NoteConcepts { concepts: list[str] }`.
- `note_chat` — flash; freeform `str` output; tools = `[read_active_note, search_course_materials, apply_graph_update_tool]`.

Each agent's output schema is one field (the lesson from `docs/attempts/2026-05-03-orchestrator-schema-complexity.md`). The `read_active_note` tool lives at `agents/tools/note_context.py`.

**`note_id` rides on `SaplingDeps.session_id`** for the chat agent — the route sets it before running the agent, and the tool reads `ctx.deps.session_id` for the active note. This avoids inflating the deps type with a notetaker-specific field while keeping the LLM from choosing which note to read.

### Routes

`routes/notes.py` (mounted at `/api/notes` in `main.py`):

- CRUD: `GET /user/{user_id}`, `POST ""`, `GET /{note_id}`, `PATCH /{note_id}`, `DELETE /{note_id}`.
- Concept links: `GET /{note_id}/concepts`, `POST /{note_id}/concepts`, `DELETE /{note_id}/concepts/{concept_node_id}`.
- Agent-backed: `POST /{note_id}/summarize`, `POST /{note_id}/extract-concepts`, `POST /{note_id}/chat`, `POST /{note_id}/send-to-tutor`, `POST /{note_id}/generate-quiz`.

`/generate-quiz` is a thin selector — it picks the lowest-mastery linked concept and returns `{concept_node_id, concept_name}`. **The frontend then calls the existing `/api/quiz/generate`** separately rather than the notes router proxying. Keeps the quiz client as the single source of truth for quiz state.

The chat route returns JSON, not SSE — matches `routes/learn.py::chat`. Streaming is a future iteration.

### Frontend

`frontend/src/app/(shell)/notetaker/page.tsx` keeps its component structure but the page now:

- Loads `getCourses(userId)` + `listNotes(userId)` on mount; renders `<EmptyNotetaker>` when the user has no notes.
- Debounced autosave (800ms) on title/body/tags changes via `patchNote`.
- `<ConceptPickerModal>` queries the user's graph via `getGraph` and filters by active course.
- Four action buttons (summarize / extract-concepts / generate-quiz / send-to-tutor) with a shared `busy` state. Generate-quiz and send-to-tutor `router.push` to `/quiz?concept=...` and `/learn?topic=...&course=...`; **deep-link param parsing on those destination pages is a follow-up task** — pushing the URL is the notetaker side's responsibility.
- `<AIChatPanel>` posts to `/api/notes/{id}/chat` and resets on `noteId` change.

## Consequences

- The notetaker feature surface is shipped: 35 new backend tests pass, frontend `tsc` is clean. Browser smoke testing remains (Task 20 in the plan).
- **No RLS** on `notes`/`note_concepts` — the rest of the schema runs RLS-disabled with route-code `require_self` ownership checks. Project-wide RLS is a separate concern (flagged in the Supabase MCP advisory at plan time).
- **No agent evals yet** for `note_summary` / `note_concepts` / `note_chat`. Refactors #1–#4 shipped evals; this is brand-new surface and leans on unit tests + smoke. Add `tests/evals/note_*.py` in a follow-up.
- **No SSE / streaming chat** today.
- **No tag autocomplete** — tags are free-form per-note strings.
- **No autosave retry UI** — failures stay silent; a toast wiring task is a future polish.
