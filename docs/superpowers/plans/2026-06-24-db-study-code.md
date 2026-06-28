# db/study-code — repoint study artifacts onto the offering

Branch: `db/study-code` (based on `db/academics-code`).
Schema source of truth: `backend/db/migrations/0025_study_integrity.sql` (+ 0023 for graph).

## LOCKED CONTRACT recap

- The API boundary keeps the **abstract `course_id`** (catalog id). Request bodies / query
  params still send `course_id`.
- Study artifacts (`documents`, `notes`, `sessions`, `study_guides`, `flashcards`) now key on
  **`offering_id`** (a course taught in a specific term). The route resolves the abstract
  `course_id` → `offering_id` via `services.academics.resolve_offering(course_id)` (current term
  default) before reading/writing.
- The **knowledge graph** (`graph_nodes`, `apply_graph_update`) stays on the **abstract
  `course_id`** — mastery is cumulative across terms. So every `apply_graph_update(..., course_id=...)`
  call keeps passing the abstract id, NOT the offering id.

## Exact CHECK-enum value sets (from 0025 / 0023)

- `documents.category` ∈ `{syllabus, lecture_notes, slides, reading, assignment, study_guide, other}`
  (already enforced by `VALID_CATEGORIES` in routes/documents.py — matches verbatim).
- `sessions.mode` ∈ `{socratic, expository, teachback}` (NEW CHECK — validate at write).
- `quiz_attempts.difficulty` ∈ `{easy, medium, hard}` (NEW CHECK — validate at write).
- `messages.role` — left **unconstrained** in 0025 (`'user'/'assistant' set in code`). Code already
  writes only `user`/`assistant`. No new DB enum; keep code disciplined (no change needed, but
  documented).
- `graph_nodes.mastery_tier` ∈ `{unexplored, struggling, learning, mastered, subject_root}` (0023) —
  not in my write path (owned by graph slice).
- `node_mastery_events(node_id, delta, reason, created_at)` (0023) — replaces the dropped
  `graph_nodes.mastery_events` jsonb column.

## Column renames (0025): `course_id` → `offering_id`

`documents`, `notes`, `sessions`, `study_guides`, `flashcards` no longer have a `course_id` column.
`flashcards.offering_id` and `sessions.offering_id` are **nullable** (ON DELETE SET NULL);
`documents.offering_id`, `notes.offering_id`, `study_guides.offering_id` are **NOT NULL**.
`enrollments.syllabus_doc_id` FK → `documents(id)` re-added (no code change; FK only).
`note_concepts.concept_node_id` FK → `graph_nodes(id)` (no code change; FK only).

## Offering resolution helper

Add a small private helper per route module that imports
`from services.academics import resolve_offering` (imported into the route module namespace so
tests can patch `routes.<x>.resolve_offering`). The route resolves the abstract `course_id` to an
offering id once, then uses it for every artifact read/write in that request. Where a
`session`/`document` row already carries `offering_id`, use it directly (no re-resolution).

## File-by-file change map (current → new)

### services/notes_service.py
- `_SELECT_COLS`: `course_id` → `offering_id`.
- `create_note(user_id, offering_id, ...)`: param renamed `course_id` → `offering_id`; insert row
  writes `offering_id`; `_decrypt_row` unchanged. Reads filter out soft-deleted (`deleted_at` is
  NULL) — add `deleted_at: "is.null"` filter to `get_note`, `list_notes`, `_note_belongs_to_user`.
- `list_notes(user_id, offering_id=None)`: filter key → `offering_id`.
- `update_note`: `course_id` patch key → `offering_id`.
- `delete_note`: SOFT delete → `table("notes").update({"deleted_at": now}, filters=...)` instead of
  hard `.delete`.
- `list_linked_concepts`: graph_nodes still selects `course_id` (abstract graph) — unchanged.

### routes/notes.py
- `CreateNoteBody.course_id`, `UpdateNoteBody.course_id` stay (API boundary).
- `create`: resolve `offering_id = resolve_offering(body.course_id, create=True)` then
  `create_note(..., offering_id=offering_id)`. (create=True so a fresh note lands in the real
  current-term offering.)
- `list_user_notes`: when `course_id` query param present, resolve → `offering_id`; pass to
  `list_notes(offering_id=...)`.
- `patch`: if `body.course_id` set, resolve → offering and pass `offering_id` in patch.
- Agent actions (`summarize`/`extract-concepts`/`chat`/`send-to-tutor`/`generate-quiz`): the note row
  now returns `offering_id`. For graph ops (`apply_concepts_to_graph`, `_lookup_concept_nodes_by_name`)
  the graph keys on the ABSTRACT course id → translate `offering_id` → abstract via
  `services.academics.offering_course_id(offering_id)` and pass that as `course_id` to the graph
  helpers. `send-to-tutor` returns `course_id` (abstract) in its payload → translate offering→abstract.
- `_deps_for`: SaplingDeps.course_id is the abstract id for graph tools → pass abstract
  (`offering_course_id(note.offering_id)`).

### routes/documents.py
- `VALID_CATEGORIES` already correct.
- `list_documents`: select `offering_id` (not `course_id`); filter out `deleted_at` (is.null).
- `delete_document`: SOFT delete → `update({"deleted_at": now})`.
- `_existing_doc_by_request_id`: select `offering_id`.
- `_persist_document(offering_id=...)`: insert row writes `offering_id`. Caller resolves
  `course_id` → offering once.
- `upload_document_sync` / `upload_document`: resolve `offering_id = resolve_offering(course_id,
  create=True)` near the top. Use offering for `_persist_document` and `_invalidate_study_guide_cache`.
  Keep passing the **abstract `course_id`** to `apply_graph_update` / `_graph_backstop` /
  `update_course_context` / `apply_concepts_to_graph` (graph + course_context key on abstract).
- `_legacy_upload_pipeline(offering_id=..., course_id=...)`: takes both — writes `offering_id` on the
  documents row, passes abstract `course_id` to `apply_graph_update` + assignment save +
  course-context.
- `_invalidate_study_guide_cache(user_id, offering_id)`: filter `offering_id`.
- `scan_document_concepts`: the doc row now has `offering_id`; graph scan keys on abstract →
  translate `offering_id` → abstract `course_id` via `offering_course_id` for
  `_scan_concepts_for_course` (which writes graph_nodes by abstract course_id — unchanged).
- `scan_course_concepts(course_id)`: course_id is abstract (graph) — unchanged (graph scan).
- `_save_orchestrator_syllabus`: assignments carry `course_id` (abstract, calendar/gradebook keyed) —
  keep abstract.

### routes/study_guide.py
- `_generate_and_insert(user_id, offering_id, exam_id)`: documents read filter → `offering_id`; insert
  row writes `offering_id`. Caller resolves abstract course_id → offering.
- `get_cached_guides`: select `offering_id`; enrich course name via
  `offering_course_id(offering_id)` → courses lookup. Response still exposes `course_id` (abstract)
  for the frontend.
- `get_guide(course_id, exam_id)`: resolve abstract `course_id` → offering for the cache lookup and
  generation.
- `regenerate_guide`: resolve abstract → offering for delete + regen.
- `get_courses` reads `courses` (abstract) — unchanged. `get_exams` reads `assignments` — unchanged.

### routes/flashcards.py
- `_get_course_documents`: documents filter `course_id` → `offering_id`; resolve the course (by name)
  → abstract course_id → offering before the documents read.
- `_get_weak_concepts`: reads `graph_nodes.subject` (abstract graph) — unchanged.
- `generate` insert: `flashcards` row has no `course_id`/`offering_id` today; leave offering NULL
  (topic-based AI generation isn't course-scoped here) — unchanged except the helper's documents read.
- `get_flashcards`: select `offering_id` (was `course_id`).
- `import_commit`: body keeps `course_id` (abstract, optional). Resolve → `offering_id`
  (create=False; None stays None). Insert writes `offering_id`. Pass the resolved offering to
  `dedup_against_existing` (its param is positionally `course_id` but filters the flashcards column;
  the column is now `offering_id` — see Out-of-scope note).

### routes/learn.py (doc-context + offering wiring)
- `_get_session_course_id` → keep name but read `sessions.offering_id`; rename to
  `_get_session_offering_id` returning the offering id.
- `_get_course_documents(user_id, offering_id)`: filter `documents.offering_id`.
- `_consume_pending`: session insert writes `offering_id` (resolve pending abstract course_id →
  offering). `sessions` has no `course_id` column.
- `start_session`: resolve abstract `course_id` (from body or topic) → offering for the documents
  read + session persistence; keep abstract `course_id` for `apply_graph_update`,
  `get_course_context`, `build_system_prompt`'s shared-context block, and `_get_course_info`.
  Store BOTH in PENDING (abstract `course_id` for graph, `offering_id` for the session row).
- `_chat_via_agent` / `_legacy_chat` / `chat`: a session row carries `offering_id`. For documents,
  read by `offering_id`. For graph + shared-context, translate `offering_id` → abstract via
  `offering_course_id` and pass that as `course_id` to `build_system_prompt`, `apply_graph_update`,
  and SaplingDeps.course_id.
- `build_system_prompt`: **resolve the TODO** — it already takes an abstract `course_id` and calls
  `get_course_context(course_id)`. The fix is upstream: pass the session's offering→abstract course
  id so shared context resolves. The signature stays `course_id` (abstract); callers now derive it
  from the session's offering. (course_context_service is out of scope; it keys on abstract course_id
  per the academics slice, so passing the abstract id is correct — the `{}`-degrade TODO is removed.)
- `list_sessions` / `resume_session`: select `offering_id`; expose `course_id` (abstract) in the
  response by translating offering→abstract so the frontend contract is unchanged.

### routes/quiz.py (mastery_events fix + difficulty enum)
- `generate_quiz`: validate `body.difficulty ∈ {easy,medium,hard}` (400 otherwise). quiz_attempts
  insert already writes `difficulty` — keep, now validated.
- `_legacy_generate_quiz`: graph reads unchanged (graph_nodes keyed on abstract course_id; course
  context keyed on abstract).
- `submit_quiz` — **the mastery_events fix**:
  - STOP selecting/writing `graph_nodes.mastery_events` (DROPPED by 0023).
  - Keep the owner-scoped node read (`mastery_score,times_studied,concept_name,course_id`) — needed
    for the 404 IDOR guard and the response's `mastery_before`/`mastery_after`. 404 BEFORE any write
    (preserves IDOR test).
  - Route the mastery WRITE through `services.graph_service.apply_graph_update(user_id,
    {"updated_nodes": [{concept_name, mastery_delta, reason, event_type}]}, course_id=<abstract>)` —
    the sanctioned path. apply_graph_update looks up the node by normalized concept_name within
    (user_id, course_id), applies the same clamp, bumps times_studied, and appends the mastery event
    (the graph slice owns whether that lands in node_mastery_events vs the column — I just call it).
  - Compute `mastery_after` for the RESPONSE with the existing formula (so the response shape is
    unchanged) and derive `mastery_delta = mastery_after - mastery_before` to hand to
    apply_graph_update, so the persisted delta matches the reported one.
  - Do NOT reimplement apply_graph_update internals. Do NOT read/write the column.
  - quiz_attempts.update (score/total/answers/completed_at) unchanged.

## How each artifact resolves its offering_id

| artifact      | source of offering_id |
|---------------|------------------------|
| documents (upload) | `resolve_offering(course_id, create=True)` from the upload form's abstract course_id |
| documents (read/scan) | the document row's `offering_id`; for graph scan translate → abstract via `offering_course_id` |
| notes         | `resolve_offering(body.course_id, create=True)` on create; existing row's `offering_id` on read |
| sessions      | `resolve_offering(course_id, create=True)` at session persist; `sessions.offering_id` thereafter |
| study_guides  | `resolve_offering(course_id)` from the abstract course_id in the query/body |
| flashcards    | `resolve_offering(course_id)` (nullable) on import_commit; NULL for topic-only generate |
| graph (quiz/notes/docs) | NEVER offering — always the abstract course_id (translate offering→abstract when only the offering is in hand) |

## Test list (TDD)

- test_notes_service: rename `course_id`→`offering_id` in mocks/asserts; add soft-delete assertion
  (delete_note calls `.update({deleted_at})`, not `.delete`); add `deleted_at is.null` read filter
  assertion.
- test_notes_routes: patch `routes.notes.resolve_offering` + `routes.notes.offering_course_id`;
  create passes `offering_id`; graph lookups get abstract course_id.
- test_documents_routes: patch `routes.documents.resolve_offering`; insert row asserts `offering_id`;
  `apply_graph_update` still asserts abstract `course_id`; delete asserts soft-delete update.
- test_study_guide_routes: patch `routes.study_guide.resolve_offering` (+ `offering_course_id` for
  cached-guide enrichment); documents read + insert assert `offering_id`.
- test_flashcards / test_flashcard_import_routes: patch `routes.flashcards.resolve_offering`; import
  insert asserts `offering_id`.
- test_learn_routes: session reads/writes `offering_id`; doc context reads `offering_id`; build_system_prompt
  shared-context gets the abstract course id (no `{}` degrade). Patch `routes.learn.resolve_offering`
  + `routes.learn.offering_course_id`.
- test_quiz_routes: submit no longer references `mastery_events`; mastery write goes through
  `apply_graph_update` (patch `routes.quiz.apply_graph_update`, assert called with updated_nodes +
  abstract course_id); IDOR test still 404s with no graph write; add difficulty-enum validation test.

## Out of scope (do NOT touch)

- `services/academics.py`, `services/graph_service.py` internals (apply_graph_update body, graph_nodes
  upserts, the column-vs-node_mastery_events decision), `services/course_context_service.py`.
- gradebook, analytics, identity, ops.
- `services/flashcard_import_service.py`: its `dedup_against_existing` still filters the flashcards
  table on a column literally named `course_id`. That column is now `offering_id`. The service file is
  NOT in this slice's file list and editing it risks the flashcard_import_service tests (which pin the
  `course_id` filter key). KNOWN SEAM: the route passes the resolved offering id into the existing
  `course_id` parameter; aligning the service's filter column to `offering_id` is a one-line follow-up
  owned by whoever owns flashcard_import_service. Flagged, not fixed here.
