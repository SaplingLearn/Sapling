# Backend & Contract Bug Audit

_Generated 2026-06-07 · scope: `backend/` (FastAPI + Supabase + Pydantic AI agents) and the `frontend/` ↔ backend API contract (`frontend/src/lib/api.ts`, `types.ts`, `sse.ts`)._

This is a **functional-correctness** audit: it hunts bugs that break Sapling for a user — frontend/backend contract drift, broken encryption read/write boundaries, auth/IDOR gaps, agent-migration regressions, and knowledge-graph consistency. Every finding is cited to `file:line` and was independently re-verified against the actual code (adversarial pass). It documents what's wrong — it does not change code.

## Method

Eight domain auditors fanned out in parallel (contract diff, auth+encryption, document pipeline, agents/LLM seam, knowledge graph, frontend state, remaining routes, convention violations). Each candidate finding was then handed to a separate verifier instructed to **refute** it by reading the real code on both sides; only findings that survived are listed here. **40 candidates → 34 confirmed, 6 refuted.** Three confirmed pairs describe the same root bug and are merged below, giving **31 distinct issues**.

## Severity tally

| Severity | Count | Theme |
|----------|:-----:|-------|
| **Critical** | 2 | Cross-user data exfiltration (IDOR) + encrypted chat rendered as ciphertext |
| **High** | 6 | Encryption boundary breaks, cross-user LLM context leak, agent-migration regressions, a dead admin endpoint |
| **Medium** | 9 | Concurrency/idempotency on mastery, pipeline double-fire, empty-OCR persistence, missing usage limits, silent autosave loss |
| **Low** | 14 | Response-boundary ciphertext, off-by-ones, dedup/escaping bugs, cosmetic contract drift |
| **Total** | **31** | |

**Most urgent:** `calendar.export_to_google` (`backend/routes/calendar.py:378-407`) is a cross-user IDOR that exfiltrates other users' decrypted private assignment notes and corrupts their rows — an authenticated attacker only needs to guess assignment UUIDs.

## Executive summary

- **31 confirmed bugs:** 2 critical, 6 high, 9 medium, 14 low.
- Two **encryption read-boundary** breaks dominate the critical/high tier: realtime room chat renders raw ciphertext, and syllabus-extracted assignment notes are persisted as plaintext.
- **Agent-migration regressions** (mastery can no longer rise via chat, empty `concepts_covered`, missing usage limits) and the quiz route bypassing `apply_graph_update` quietly degrade the core knowledge-graph loop.
- **Recommended sequence:** patch the IDOR (#1) and the two encryption boundaries (#2, #4) first — they are data-exposure/compliance issues with small, surgical fixes — then the knowledge-graph correctness cluster (#5, #6, #9, #10), then the remaining contract/UX issues.

---

## Critical

**1. `calendar.export_to_google` cross-user IDOR leaks decrypted private assignment notes**
`backend/routes/calendar.py:378-407`
The export loop fetches each requested assignment with `filters={"id": f"eq.{aid}"}` and no `user_id` scope; `require_self` only validates the body's `user_id`, not the assignment ids. An authenticated user can pass another user's assignment UUIDs to read titles, decrypt private `notes`, push them into the *attacker's* Google Calendar, and stamp `google_event_id` onto the victim's row. Every sibling endpoint scopes by `user_id` (sync `:329`, delete `:220`, update `:198-200`).
*Fix:* add `"user_id": f"eq.{body.user_id}"` to the select filter and `continue` when no row returns; scope the follow-up update the same way.

**2. Realtime room chat renders encrypted ciphertext for incoming messages**
`frontend/src/components/screens/Social.tsx:142-159,422` · `backend/routes/social.py:335,356`
`room_messages.text` is column-encrypted at rest; only the REST read paths decrypt it. The RoomChat realtime subscription stores `{ ...row }` and renders `payload.new.text` directly, so messages from other users (which arrive only via realtime) display as unreadable ciphertext until a manual reload. The UPDATE handler has the same defect for edits.
*Fix:* treat realtime as a "something changed" signal — re-fetch affected messages through the decrypting REST endpoint (or always source text from the API) rather than trusting `payload.new.text`.

---

## High

**3. `search_course_materials` leaks other users' documents into the tutor/note-chat LLM**
`backend/agents/tools/chat_context.py:165-181,234-245` · `chat_tutor.py:102-107` · `note_chat.py:48-52`
The tool filters the `documents` table on `course_id` only, but documents are user-scoped within a shared course. It returns and decrypts `summary`/`concept_notes` for *every* enrolled user, feeding another student's private content into the requester's LLM context and answers. `ctx.deps.user_id` is available but unused.
*Fix:* thread `user_id` into the tool and add `"user_id": f"eq.{user_id}"` to the filters, matching the scoping used everywhere else.

**4. Syllabus-extracted assignment notes written to DB unencrypted**
`backend/services/calendar_service.py:55` · `backend/routes/documents.py:455,950`
`assignments.notes` is encrypted on every other write (`calendar.py:128`, `gradebook.py:252`), but `insert_new_assignments` — the document-pipeline insert path — writes `"notes": a.get("notes")` with no `encrypt_if_present`. Uploading a syllabus persists per-assignment notes/descriptions as plaintext, defeating column encryption (compliance regression) and spamming `decrypt_if_present fallback` warnings on every later read.
*Fix:* `"notes": encrypt_if_present(a.get("notes"))` in `insert_new_assignments`.

**5. Chat-tutor agent can no longer raise concept mastery**
`backend/agents/chat_tutor.py:45-53` · `agents/tools/graph.py:21-70` · `graph_service.py:404-464` · `learn.py:443-506`
The tutor prompt claims it can update mastery, but the only registered tool (`apply_graph_update_tool`) emits only `new_nodes` at `initial_mastery: 0.0` — never `updated_nodes`/`mastery_delta`, the branch that actually moves mastery. The legacy path parsed `<graph_update>` deltas and applied them. Conversational tutoring no longer contributes to mastery at all; only quizzes do.
*Fix:* add a real mastery-update tool (concept + `mastery_delta` + event_type) that forwards `updated_nodes` to `apply_graph_update`, or correct the prompt.

**6. Quiz submission writes `graph_nodes` directly, bypassing `apply_graph_update` and course-context refresh** *(merges 2 findings)*
`backend/routes/quiz.py:416` · `graph_service.py:375,522` · `course_context_service.py:143`
`submit_quiz` does a direct `table("graph_nodes").update(...)`, violating the convention that all graph mutations route through `apply_graph_update`. It re-implements mastery/event logic and, critically, skips the trailing `update_course_context(cid)` call. Quiz completion (the strongest mastery signal) leaves the shared per-course aggregate stale until some unrelated action touches the course via the sanctioned path.
*Fix:* route the change through `apply_graph_update` with an `updated_nodes` payload (`course_id` is already selected at `:390/438`), or at minimum call `update_course_context(course_id)` after the write.

**7. Optimistic message dedup compares plaintext vs ciphertext → duplicate bubbles, lost reply/reaction metadata**
`frontend/src/components/screens/Social.tsx:147-159,237-261`
`send()` appends a temp row holding plaintext; the realtime dedup keeps rows where `m.text !== row.text`. Since the tmp is plaintext and `row.text` is ciphertext, they never match, so the sender sees their message twice (one readable, one ciphertext). The realtime row also hardcodes `reply_to: null`/`reactions: []`, and the UPDATE handler overwrites edited text with ciphertext.
*Fix:* reconcile by a client correlation id echoed by the server (or replace the tmp with the decrypted POST response at `social.py:362`); preserve/refetch `reply_to`/`reactions`.

**8. Frontend calls `GET /api/admin/allowlist` but no such route exists (404)**
`frontend/src/lib/api.ts:871` · `Admin.tsx:1262` · `backend/routes/admin.py:461`
`adminListAllowlist()` hits `GET /api/admin/allowlist`, but the admin router only defines `POST /allowlist/approve` and `/revoke`. The request 404s; `load()` catches it, toasts an error, and leaves the list empty. The allowlist view never populates (approve/revoke via typed email still work).
*Fix:* add an admin-guarded `@router.get("/allowlist")` returning `{"emails": ...}` matching the FE `AllowlistEmail` shape.

---

## Medium

**9. Non-atomic read-modify-write on mastery loses concurrent graph updates**
`backend/services/graph_service.py:457-475` · `routes/quiz.py:407-425`
Both paths read `mastery_score`/`mastery_events`, compute in Python, and write the whole array back with no lock or version check. Two near-simultaneous updates to the same concept (e.g. chat + quiz, or two tabs) clobber each other — last writer wins, discarding a mastery event and delta; corrupts the 20-event history and velocity computation.
*Fix:* DB-side append (RPC/SQL), an optimistic version column with retry, or funnel all writers through one `apply_graph_update` path.

**10. Quiz submit has no idempotency — resubmission double-counts mastery/streak**
`backend/routes/quiz.py:355-436`
`submit_quiz` sets `completed_at` (`:432`) but never reads it, so re-POSTing the same `quiz_id` re-applies the mastery delta, increments `times_studied`, appends another event, and re-runs `update_streak`. A double-click or retry inflates mastery and streak.
*Fix:* if `attempt.get("completed_at")` is set, return the stored result (or 409) instead of re-scoring.

**11. Streaming `/upload` re-runs the entire legacy pipeline when persistence fails after the result event**
`backend/routes/documents.py:765-811`
The `result` event is emitted and `_save_orchestrator_syllabus` runs before `_persist_document`, all inside the broad `except` that triggers `_stream_legacy_fallback`. A post-result DB error re-runs `_process_document` (second Gemini call), re-saves assignments, and re-inserts the doc — the client gets `result` → `error` → a second `result` and `finalDoc` is overwritten by the legacy shape.
*Fix:* wrap persistence/side-effects (`772-788`) in their own try/except that emits a terminal error+done; only the orchestrator run should route to the legacy fallback.

**12. PDF OCR does not fall back when Docling returns empty text — useless document silently persisted**
`backend/services/extraction_service.py:78,146` · `routes/documents.py:225`
`extract_text_from_pdf_ocr` only falls back to tesseract when Docling *raises*; an empty/whitespace result returns `('', page_count)` with no fallback (asymmetric with the image path at `:41-50`). The pipeline never guards empty text, so a scanned PDF gets classified as "other" with an empty summary and saved as if successful.
*Fix:* fall back to tesseract on empty Docling output, and guard the pipeline against empty `extracted_text` (error like `calendar_service:130`).

**13. end-session `concepts_covered` is always empty for agent-path chats**
`backend/routes/learn.py:599-604,346-354,640-672`
The agent path calls `save_message(..., "assistant", reply)` with no `graph_update` arg, so `graph_update_json` stays NULL. `end_session` derives `concepts_covered` solely from `messages.graph_update_json`, so every agent session reports zero concepts covered (legacy path passed `graph_update`).
*Fix:* have the graph tool report what it merged back to the route and persist into `graph_update_json`, or derive `concepts_covered` from graph_nodes touched during the session.

**14. `ORCHESTRATOR_LIMITS` is dead code — tool-using agents run with no cost guardrails**
`backend/agents/__init__.py:4-23` · `learn.py:489-499` · `quiz.py:185-189` · `notes.py:204-252`
`ORCHESTRATOR_LIMITS` (8 req / 10 tool-calls / 100k tokens) is never referenced; chat_tutor, quiz, and note agents call `.run()` with no `usage_limits`. Pydantic AI's default still caps requests at 50, but the intended tool-call/token ceilings are absent — so the `UsageLimitExceeded` fallback can't fire on cost grounds, and a single conversation can spend unbounded tokens.
*Fix:* pass `usage_limits=ORCHESTRATOR_LIMITS` to the tool-using agents (worker-style limit to note_summary/note_concepts).

**15. Notetaker debounced autosave is discarded on unmount → silent data loss**
`frontend/src/app/(shell)/notetaker/page.tsx:211-249`
Edits persist via an 800ms-debounced `patchNote`, but the cleanup effect clears pending timers *without flushing*. Typing then navigating away (or clicking Send-to-tutor/Generate-quiz, which `router.push` and unmount) within the window drops the queued save — while the footer still reads "Saved".
*Fix:* flush pending saves on cleanup and on `activeId` change (synchronous patch / `keepalive` fetch / `sendBeacon`); drive the footer from the timer map.

**16. Send-to-tutor drops course context — Learn never reads the `course` query param**
`frontend/src/app/(shell)/notetaker/page.tsx:347-350` · `Learn.tsx:96-97,359`
`onSendToTutor` pushes `/learn?topic=...&course=<id>`, but `LearnInner` only reads `topic`/`mode`/`suggest`. `selectedCourseId` stays `""` and `startSession` runs with `courseId` undefined, so the note's course scoping is silently lost.
*Fix:* read `searchParams.get("course")`, seed `selectedCourseId` from it, and pass it into `startSession`.

**17. Feedback / issue-report endpoints have no auth and trust client-supplied `user_id`** *(merges 2 findings)*
`backend/routes/feedback.py:9-31`
`submit_feedback` and `submit_issue_report` take a body `user_id` and insert it verbatim with no `Request` param and no `require_self`/session check. Anyone unauthenticated can write rows attributed to any `user_id` (attribution spoofing) and spam these tables.
*Fix:* add `request: Request` and `require_self(body.user_id, request)` (or derive `user_id` from `get_session_user_id`) in both handlers.

---

## Low

**18. gradebook `create_assignment` returns ciphertext for `points`/`notes`**
`backend/routes/gradebook.py:242-255` · `db/connection.py:17`
The POST encrypts on insert then returns `inserted[0]` (representation = stored ciphertext) with no decrypt pass, unlike `get_summary`/`get_course`. Masked today only because `Course.tsx` reloads and discards the response, but the contract is broken.
*Fix:* run the inserted row through the same per-assignment decrypt helper used in `get_course`.

**19. profile `PATCH /settings` returns ciphertext `bio`/`location`**
`backend/routes/profile.py:329-349,54-64`
The update return does a raw select of `_SETTINGS_COLS` (which includes encrypted `bio`/`location`) without decrypting, unlike GET which goes through `_get_or_create_settings`. Limited impact since `Settings.tsx` ignores the return value.
*Fix:* return through `_get_or_create_settings(user_id)` or `decrypt_if_present` the row before responding.

**20. `createNote` response omits `last_summary_at` declared in FE `Note` type**
`frontend/src/lib/types.ts:402` · `api.ts:1109` · `notes_service.py:45`
`create_note`'s row lacks `last_summary`/`last_summary_at`; `_decrypt_row` sets `last_summary=None` but never adds `last_summary_at`, so the created object returns `undefined` (not `null`). Reads via `get_note`/`list_notes` are correct.
*Fix:* add `"last_summary": None, "last_summary_at": None` to the row (or `setdefault` in `_decrypt_row`).

**21. Streaming `/upload` size-limit message says 15 MB but enforces 100 MB**
`backend/routes/documents.py:603-606,56,505`
The check uses `MAX_FILE_SIZE` (100 MB) but the detail reads "File exceeds the 15 MB limit"; the sync route correctly says 100 MB.
*Fix:* reference 100 MB (or derive from `MAX_FILE_SIZE`).

**22. Blocking synchronous DB writes run on the event loop in the async streaming upload**
`backend/routes/documents.py:772,776,559,563`
`_save_orchestrator_syllabus` and `_persist_document` do synchronous PostgREST round-trips directly on the loop, contrary to the `asyncio.to_thread` pattern used for `apply_graph_update` (`agents/tools/graph.py:48`) and `_spawn_post_roll` (`:908`). Throughput-only; data is still persisted correctly.
*Fix:* wrap these and `_graph_backstop` in `asyncio.to_thread`.

**23. `note_chat` prompt references a tool name that isn't registered**
`backend/agents/note_chat.py:27-53` · `chat_context.py:234`
The bare-function registration yields tool name `search_course_materials_tool`, but the prompt instructs the model to use `search_course_materials`, steering it toward a non-existent name.
*Fix:* register with `Tool(..., name="search_course_materials")` or update the prompt to the real name.

**24. Edge dedup is directional — reciprocal A→B / B→A edges both inserted**
`backend/services/graph_service.py:504-512`
The existence check matches exact `source/target` orientation only. For symmetric "related" concepts the LLM may emit both directions, inserting duplicate logical edges that double-render and distort the graph layout.
*Fix:* normalize (sort) the id pair for undirected relationship types before the existence check, or query both orientations.

**25. Concepts from unenrolled courses become ungrouped floaters**
`backend/services/graph_service.py:344,96,152,163` · `KnowledgeGraph2D.tsx:257`
`delete_course` unenrolls but keeps `graph_nodes`; `get_graph` fetches by `user_id` yet stamps `subject`/`course_color`/subject-edges only from enrolled courses. Orphaned nodes render with `subject` undefined, collapse under an `undefined` bucket, are unfilterable, and float disconnected until re-enrollment.
*Fix:* cascade/soft-archive nodes on unenroll, or synthesize a fallback "Archived" subject in `get_graph`.

**26. notes concept lookup builds PostgREST `in.()` from raw-joined names** *(merges 2 findings)*
`backend/routes/notes.py:159-179`
`in_clause = 'in.(' + ','.join(names) + ')'` is unquoted/unescaped. Concept names containing commas, parentheses, or quotes mis-parse, so those nodes silently fail to link to the note (no error surfaced).
*Fix:* quote/escape each value, or match per-name / by normalized id returned from `apply_graph_update`.

**27. `study_guide` cached listing does N+1 course lookups and leaves Gemini errors as raw 500s**
`backend/routes/study_guide.py:116-131,99`
`get_cached_guides` issues one `courses` select per distinct `course_id` instead of one `id=in.(...)` query, and `_generate_and_insert` calls `call_gemini_json` with no try/except, surfacing a transient outage as a 500 instead of the 502 used by sibling routes.
*Fix:* batch with `id=in.(...)`; wrap the Gemini call → `HTTPException(502)`.

**28. `get_room_messages` `has_more` off-by-one**
`backend/routes/social.py:289-298`
`has_more = len(rows) == limit` reports true at exact page boundaries, causing a phantom "load more" that fetches an empty page.
*Fix:* fetch `limit+1`, set `has_more = len(rows) > limit`, truncate to `limit`.

**29. Quiz scoring awards a free point for an unanswered, no-correct-option question**
`backend/routes/quiz.py:372-379`
Both `selected` and `correct_label` default to `''`, so `is_correct = '' == ''` is True for an unanswered question on a malformed (no-correct-option) item, inflating the score and mastery delta.
*Fix:* `is_correct = bool(correct_opt) and selected == correct_label` and/or require non-empty `selected`.

**30. "Private" profile visibility still exposes name, majors, minors, year, school**
`backend/routes/profile.py:171-216`
`get_public_profile` is unauthenticated and only gates bio/location/website/achievements/stats behind non-private visibility; decrypted name, username, avatar, year, majors/minors, and school are always returned even when private.
*Fix:* return a minimal stub when `visibility == 'private'` and viewer ≠ owner, or add a stricter visibility tier.

**31. `room_reactions` realtime subscription has no room scope — reloads on every room's reactions**
`frontend/src/components/screens/Social.tsx:160-165`
The reaction INSERT/DELETE subscriptions have no filter, so any reaction in any room triggers `load()` for the open room. (A server-side `room_id` filter is impossible — `room_reactions` has only `message_id`.)
*Fix:* client-side — only reload if the affected `message_id` belongs to the currently loaded messages, or update counts incrementally from the payload.

---

## Refuted during verification

Six candidates were dropped after a verifier read the real code and could not reproduce the problem (e.g. a guard/decrypt that existed elsewhere, or a contract that matched once both sides were read). They are intentionally omitted to keep this list actionable.

## Cross-cutting patterns

- **Encryption boundaries are the most fragile seam.** Three confirmed issues (#2, #4, plus the response-boundary leaks #18/#19) are write- or read-boundary omissions. A shared per-table encrypt/decrypt helper applied at every route boundary — rather than ad-hoc per-field calls — would close this class.
- **The agent migration left correctness gaps.** Mastery-via-chat (#5), `concepts_covered` (#13), and usage limits (#14) all regressed when routes moved from the legacy `<graph_update>` parsing to Pydantic AI tools. The agent tools need to round-trip what they mutated back to the route.
- **Graph mutations leak outside `apply_graph_update`.** #6 (quiz) is a direct `graph_nodes` write; combined with the non-atomic read-modify-write (#9), the single-writer convention is worth enforcing in code, not just docs.

> This audit was generated by a multi-agent review harness; every finding was adversarially re-verified against the source. Treat it as a triage list, not a guaranteed-exhaustive sweep — re-run after the high-severity fixes land.
