# E2E bug queue — fixes paired with Chapter 1 promotions

Burn down the open E2E-adjacent bug queue (#355, #446, #430, #435, #439, #436,
#441). Every product fix is paired with a promoted Chapter 1 regression where
applicable — the Chapter 2 epic's success bar (≥3 findings promoted into
Chapter 1 journeys) is met as a side effect by Tasks 1–3.

Process shape: each task is an independent branch off origin/main and becomes
its own PR (fix + promotion in one PR). Implementers work in isolated
worktrees; the controller pushes the branch, opens the PR, runs /code-review
(gates the merge), runs stack verification (Chapter 1 Playwright lane + e2e
oracles) under the machine-singleton stack lock, and merges on green.

## Global Constraints

- All Supabase access goes through `backend/db/connection.py::table()` — never
  instantiate httpx clients or import supabase directly (exception: db/migrate.py).
- The HTTP boundary keeps the abstract `course_id`; term/offering/enrollment
  resolution goes through `backend/services/academics.py`
  (`offering_course_id`, `user_offering_ids_for_course`, …).
- Knowledge-graph mutations go through
  `backend/services/graph_service.py::apply_graph_update` — routes never write
  `graph_nodes`/`graph_edges` directly.
- Chapter 1 journey style (docs/e2e-exploration.md §8): fixtures-based `test`
  from `frontend/e2e/support/fixtures.ts` (never raw Playwright boilerplate);
  DB assertions via `frontend/e2e/support/db.ts`; any new `data-testid`
  follows `docs/frontend-testids.md` "Adding a surface" (doc row + the
  `eslint.config.mjs` `files`-array update). `npm run lint:baseline` is only
  for legacy debt — new surfaces never lean on it.
- Function-handler constants sync contract: handler constants in
  `backend/agents/function_handlers_e2e.py` ↔ Chapter 1 spec assertions ↔
  `backend/tests/test_e2e_function_handlers.py` must stay in sync; the spec
  asserts the exported constant values, not paraphrases.
- `quiz_context` stays deliberately unregistered in
  `function_handlers_e2e.py` (post-response BackgroundTask handlers fail fast
  rather than race the truncate). Only request-path handlers get registered.
- Never touch `frontend/middleware.ts` (Cloudflare edge-only constraint).
- Never remove the dummy-`GEMINI_API_KEY` forcing in `scripts/explore.sh` or
  `.github/workflows/e2e.yml`, and never remove the e2e_oracles logscan
  allowlist entry for `[RAG] _index_document_chunks failed` — after #439's fix
  they stop being load-bearing but stay as defense in depth.
- Column encryption: use `encrypt_if_present` at write boundaries and
  `decrypt_if_present`/`decrypt_numeric` at read boundaries (see CLAUDE.md
  Gotchas for the encrypted-column list).
- Hermetic backend suite must pass:
  `cd backend && python -m pytest tests/ -q` (venv lives ONLY at
  `/home/andresl/Projects/sapling/backend/venv`; `GEMINI_API_KEY` must be SET
  — a dummy value is fine, unset is never viable).
- Implementers do NOT run the local E2E stack, Playwright, `make e2e-up`,
  `make explore`, or the oracles — the stack is a machine singleton and the
  controller runs those lanes under the flock
  (`/tmp/claude-1000/sapling-e2e-stack.lock`).
- Bare `find`/`grep` are shadowed and silently truncate — use the Grep/Glob
  tools or `/usr/bin/grep`.

## Task 1: #355 — dedupe subject-root synthesis in the graph read + un-fixme the graph journey

**Issue:** `GET /api/graph/{user_id}` returns the subject-root node
(`subject_root__<course>`) duplicated when a user has two offerings of the
same abstract course — subject-root synthesis iterates ENROLLMENTS, not
distinct courses (`backend/services/graph_service.py` around line 234).
Frontend renders `<li key={n.id}>` (KnowledgeGraph2D.tsx:685) → React
duplicate-key warnings. The e2e_oracles graph check reproduces it on every
run against the rich seed (dup id `subject_root__rich-course-cs101`, node
count +1, edge count +5).

**Fix requirements:**
- Dedup at the SOURCE (the graph read): synthesize one subject root per
  distinct abstract course, not per enrollment/offering. The API must never
  return two nodes with the same id — and must not return surplus hub-spoke
  edges either (the dup currently adds +5 edges, so the fan-out includes the
  spokes, not just the node).
- Backend test: `/api/graph/{user_id}` (or the service-level read) returns
  unique `nodes[].id` for a user with TWO offerings of the same abstract
  course — build that shape in the mock-Supabase fixtures. Follow TDD: the
  test must fail on the pre-fix code.

**Promotion (this is promotion #1 of 3):**
- `frontend/e2e/graph.spec.ts:181` already carries the acceptance test as
  `test.fixme(...)` ("renders exactly one node per DB graph node plus one
  subject root per enrolled course, and one edge per DB edge plus one hub
  spoke per course node"). Un-fixme it (change `test.fixme` → `test`) and
  update the file's header comments (lines ~32–43 and ~177–180) and any
  companion-test comments that describe #355 as open — they explain the fixme
  and become stale once the bug is fixed. Do not relax the assertions.

**Files:** `backend/services/graph_service.py`, a backend test file (follow
existing graph-service test placement), `frontend/e2e/graph.spec.ts`.

## Task 2: #446 — register a function-mode `concept_describe` handler + promote a concept-description journey

**Issue:** Tutor-resume 500s in function mode. `POST
/api/graph/{user}/concept-description` →
`agents/_providers.py::_dispatch` raises
`LookupError("SAPLING_MODEL_MODE=function but no handler is registered for
task 'concept_describe'...")` because `agents/function_handlers_e2e.py`
registers six tasks (`chat_tutor`, `quiz`, `classifier`, `summary`,
`concepts`, `course_summary`) but not `concept_describe`.
`routes/graph.py`'s handler catches `(AgentRunError, httpx.HTTPError,
ValidationError)` only, so the LookupError escapes as a 500.

**Fix requirements:**
- Register a fixed `concept_describe` handler in
  `backend/agents/function_handlers_e2e.py`, exporting its constant(s) in the
  same style as `E2E_TUTOR_REPLY` (this is request-path, so registering is
  safe; the `quiz_context` stay-unregistered precedent applies only to
  post-response BackgroundTask handlers — do NOT register `quiz_context`).
  Match the agent's output shape — read `backend/agents/concept_describe.py`
  to see whether it's plain text or structured output, and mirror how the
  existing handlers emit (`_structured_output` vs `TextPart`).
- Separately decide route-level robustness: `routes/graph.py` should degrade
  gracefully if a task has no registered handler (LookupError) instead of
  500ing — a misconfigured seam shouldn't take down the route. Add
  `LookupError` to the caught exceptions with the same degradation path the
  route already uses for AgentRunError, and cover it with a backend test.
- Extend `backend/tests/test_e2e_function_handlers.py` to cover the new
  handler (constants sync contract).

**Promotion (promotion #2 of 3):**
- Extend `frontend/e2e/tutor.spec.ts` (or add a focused journey if tutor.spec
  doesn't fit) to exercise the concept-description path in function mode
  through the real UI, asserting the fixed handler constant appears. Keep the
  constants sync contract: the spec asserts the exported constant value.

**Files:** `backend/agents/function_handlers_e2e.py`,
`backend/routes/graph.py`, `backend/tests/test_e2e_function_handlers.py`,
`frontend/e2e/tutor.spec.ts` (or new spec).

## Task 3: #430 — UserContext falls back to /api/auth/me + cookie-only-session journey

**Issue:** A browser holding a valid `sapling_session` cookie but NO
`sapling_user` localStorage entry loads `/dashboard` → middleware admits the
request → infinite loading skeleton. `UserContext` bootstraps identity ONLY
from localStorage (`sapling_user`, written solely by sign-in flows via
`setActiveUser`) and never falls back to cookie-based `GET /api/auth/me` —
even though the OAuth callback already calls that endpoint cookie-only.

**Fix requirements:**
- On bootstrap with no localStorage identity: call `/api/auth/me` (through
  the `lib/api.ts` `fetchJSON` same-origin convention — cross-origin fetch
  drops the cookie), hydrate the context on 200, write-through
  `setActiveUser`, and fall back to a signed-out state on 401. Do not add a
  new identity source — this is a fallback for the existing one.
- Respect the existing local-mode behavior (`NEXT_PUBLIC_LOCAL_MODE` /
  `localData.ts` mock user) — don't break local dev bootstrap.

**Promotion (promotion #3 of 3):**
- New journey (or extension where it fits) minting a cookie-ONLY
  storageState: `frontend/e2e/support/session.ts::mintStorageState` is the
  base — add the ability to deliberately omit the localStorage half (e.g. an
  option), mint cookie-only state, load `/dashboard`, and assert the
  dashboard hydrates (user identity visible, skeleton resolves) instead of
  spinning forever. Keep the existing default (cookie + localStorage) for all
  other journeys.

**Files:** the UserContext provider under `frontend/src/` (locate it),
`frontend/e2e/support/session.ts`, a new/extended spec under `frontend/e2e/`.

## Task 4: #435 — /api/documents/user returns the abstract course_id so Library filters work

**Issue:** `GET /api/documents/user/{id}` returns `offering_id` but not
`course_id`, while `frontend/src/components/screens/Library.tsx` filters and
labels on `d.course_id` — uploads never match a course filter and always
count as "Uncategorized".

**Fix requirements:**
- Backend resolves and includes the abstract `course_id` in each document row
  of the `/api/documents/user/{id}` response, via
  `services/academics.py::offering_course_id` (repo convention: the HTTP
  boundary keeps the abstract course_id). Batch/cached resolution, not one
  lookup per row if the resolver is per-call — check how other routes do it.
- Check Library.tsx against the enriched payload — only touch it if something
  is genuinely still broken with `course_id` present (the issue's expectation
  is that the frontend already filters on `course_id` correctly).
- Backend test covering the enriched response shape (document rows carry
  `course_id` resolved from their `offering_id`).

**Promotion:**
- Add a library-filter assertion to a journey: after the existing upload
  journey's document exists (see the upload spec under `frontend/e2e/`),
  filter the Library by the seeded course and assert the uploaded document
  matches the filter (and is not "Uncategorized").

**Files:** `backend/routes/documents.py`, a backend test file,
`frontend/e2e/` upload/library spec.

## Task 5: #439 — put the RAG embedding path behind the SAPLING_MODEL_MODE seam

**Issue:** `services/rag_service.py` (`_embed_query`,
`_embed_documents_batch`) and `routes/documents.py::_index_document_chunks`
(~:1088–1109, incl. the catalog-relevance gate) construct raw
`google.genai.Client`s directly, predating the #391 seam — so live
`gemini-embedding-001` calls fire even in function mode (one per upload, one
per quiz generate, one per tutor turn with a `course_code`). The "hermetic"
E2E lane silently bills when a real key is present.

**Fix requirements:**
- Gate every embedding call site on the seam: in non-`real` model mode
  (`agents/_providers.py::_model_mode()` or an equivalent seam-aware helper),
  no `google.genai.Client` may be constructed and no network call attempted —
  return deterministic empty/no-op results (matching what the swallowed
  failure path already produces today, so function-mode behavior is unchanged
  but now by design, not by swallowed exception).
- Prefer routing through `agents/_providers.py` if a clean seam function
  exists or is a small addition; a direct `_model_mode() == "real"` gate at
  the call sites is acceptable if cleaner.
- Backend tests: in function mode, the embed paths return the deterministic
  no-op result WITHOUT constructing a client (assert via monkeypatching the
  client constructor to raise/count).
- Do NOT remove the interim mitigations (dummy-key forcing in
  `scripts/explore.sh` / `.github/workflows/e2e.yml`, the e2e_oracles logscan
  allowlist for `[RAG] _index_document_chunks failed`) — they become defense
  in depth.

**Promotion:** none required (the ≥3 bar is met by Tasks 1–3); hermetic
backend tests are the regression coverage here.

**Files:** `backend/services/rag_service.py`, `backend/routes/documents.py`,
backend test file(s).

## Task 6: #436 — fix the 'Event loop is closed' flake (test_ocr_pipeline::test_save_to_db)

**Issue:** `backend/tests/test_ocr_pipeline.py::test_save_to_db` errors with
'Event loop is closed' on untouched main (1082 passed, 23 skipped, 1 error).
Almost certainly the #354 loop-affinity bug: a module-level
GoogleProvider/client binds to the first `asyncio.run` loop and dies with it,
so every second real call through `run_agent_sync` fails. A fix existed in PR
#358 but never merged.

**Fix requirements:**
- FIRST check PR #358 (`gh pr view 358`, `gh pr diff 358`): is it salvageable
  against current main? If yes, adapt/rebase its approach; if not, write a
  fresh fix informed by why it went stale. Note what you decided and why in
  your report.
- The fix must address the root cause (provider/client lifetime vs event-loop
  lifetime — e.g. per-loop or per-call provider construction), not just the
  symptom in this one test. #354 is the root-cause issue; the PR should say
  "Fixes #436" and reference #354 (close #354 too if the root cause is truly
  fixed).
- Prove the flake is gone: run the previously-failing test (and the full
  hermetic suite) enough times to demonstrate the every-second-call pattern
  no longer reproduces (e.g. run the OCR pipeline test file 3× in one pytest
  session and the full suite twice back-to-back).

**Promotion:** none (test-infra fix; not a UI journey).

**Files:** likely `backend/agents/_providers.py` and/or the OCR pipeline
service/tests — follow the root cause.

## Task 7: #441 — close the PG17 (local/CI) vs PG15 (staging/prod) skew

**Decision (made by the controller for this plan): pin local/CI to PG15**,
matching staging/prod — the deterministic lane should test what production
runs, the epic recorded a PG15 leaning, and bumping hosted staging/prod
Postgres is an outward-facing ops action this session won't take unilaterally.
PR #440's "stack-consistency" choice (local dev ≡ CI) is preserved: both move
to 15 together, since both are pinned by `supabase/config.toml`.

**Fix requirements:**
- Pin `supabase/config.toml` `major_version = 15` (verify the Supabase CLI
  supports it and whether any other config keys are version-sensitive).
- Add one test that asserts the server major version so drift is loud —
  placement: the opt-in integration suite (`RUN_INTEGRATION=1`, see
  `backend/tests/integration/`) and/or the e2e lane's DB helper — pick the
  spot where it actually runs in CI (the e2e.yml lane boots the stack;
  a version assert in the Chapter 1 `support/db.ts` setup or an oracle-style
  check is acceptable if the integration suite doesn't run in CI).
- Update `docs/local-supabase.md` (and any other doc that names PG17) plus a
  note that existing local stacks need a reset
  (`scripts/local-db-reset.sh` / `supabase db reset`) after the pin.
- Verify the migration chain replays from empty on PG15 — the CI lane does
  this from scratch, and the controller will run the full stack verification;
  call out anything in migrations that is PG16+-only.

**Files:** `supabase/config.toml`, one test file, `docs/local-supabase.md`,
possibly `.github/workflows/*.yml` if a version is named there.
