# HANDOFF-04 — check-items

Written by the session that executed `PKG-04-check-items.md`. Read by every later package that depends on 04. Keep every heading, even if the answer is "none".

## What changed

The `check_items` table exists (migration `20260927065932_learning_check_items.sql`, spec §4's PKG-04 DDL verbatim): items are course assets keyed on `(course_id, concept_key)` with no `graph_nodes` FK (A2), the seven text columns encrypted, `question_hash` the plaintext lookup key, the A22 answer structure (`options_json`, `correct_option`, `answer_kind`, `canonical_answer`, `tolerance`, `canonical_verified`), A17's `stepwise`, A23's `source_document_ids` (GIN-indexed) and A32's `graded`. `learning/checks.py` holds the pure models, identity (`question_hash`, `item_id`), selection (`select_item`, `posttest_reserve_hash`), code-side draft validation (`validate_draft`, `leak_in_prompt`, `clean_chunk_ids`) and deterministic passage ranking (`rank_chunks_for_concept`). `services/check_item_service.py` stores items encrypted at write and decrypts them at one read boundary, reads sources only from shared `course_material` documents through `chunk_visibility.decide_visibility` (A23), and drafts items for course concepts that still lack them — skip-covered before any agent call, up to `CHECK_ITEM_CONCEPTS_PER_CALL` concepts per call, a failed call reported as `learn.check_items_failed`. `agents/check_items.py` is one flat-output flash-lite agent (task `check_items`) that runs on Gemini's Flex tier for background prefill and repeats the same run on a 429/503. With `LEARNING_LOOP_ENABLED` true both upload routes index and then draft in one ordered post-roll task (inline in function mode, where the new `check_items` E2E handler serves it); with it off they schedule `index_document` exactly as before. Deleting a document or turning `share_class_context` off deletes the items drafted from that text, whatever the flag says. `scripts/backfill_check_items.py` covers concepts that predate the package (the launch runbook step) and prints per-course coverage; `tests/evals/check_items.py` scores the generator offline (6 cassettes, baselined). Invariants 6, 9 and 12 are asserted (`10 passed, 3 skipped`).

## Symbols added

- Table `check_items` — spec §4 DDL; UNIQUE `(course_id, concept_key, question_hash)`; indexes `check_items_concept_idx (course_id, concept_key, format, difficulty)` and `check_items_source_docs_idx USING gin (source_document_ids)`. Migration `backend/db/migrations/20260927065932_learning_check_items.sql`.
- `backend/learning/checks.py::RubricItem(id, text)`, `::WrongReason(key, text)`, `::Option(letter, text, wrong_key: str | None = None)` — `wrong_key` is None on the correct option.
- `backend/learning/checks.py::CheckItem` — the DECRYPTED row: `id, course_id, concept_key, document_id, format, difficulty, prompt, reference_answer, rubric: list[RubricItem], common_wrong: list[WrongReason], options: list[Option] | None, correct_option, answer_kind: Literal["free","numeric"], canonical_answer, tolerance: float | None, canonical_verified, stepwise, source_chunk_ids, question_hash, graded, created_at`. It does NOT carry `source_document_ids` (a storage/withdrawal column no reader needs).
- `backend/learning/checks.py::CheckItemDraft` — the agent's FLAT per-item output (17 str/int/bool/list[str] fields: `concept, format, difficulty, prompt, reference_answer, rubric, wrong_keys, wrong_texts, option_letters, option_texts, option_wrong_keys, correct_option, answer_kind, canonical_answer, tolerance, stepwise, chunk_ids`). Never carries `canonical_verified`.
- `backend/learning/checks.py::normalize(value) -> str` — whitespace runs collapsed, casefolded (a copy of the quiz_identity idea, versioned apart).
- `::question_hash(prompt_plaintext) -> str` — full sha256 hex of `CHECK_HASH_VERSION + "\x1f" + normalize(prompt)`; reads the version at call time.
- `::item_id(course_id, concept_key, question_hash) -> str` — sha256 hex of the three joined by `"\x1f"`; a re-run upserts onto the same row.
- `::leak_in_prompt(prompt, reference_answer) -> bool` — the reference's word sequence (normalized, punctuation dropped) occurs as whole words inside the prompt's; an empty reference never leaks.
- `::validate_draft(draft) -> list[str]` — every reason a draft is unusable; each reason contains its rule word (`format`, `difficulty`, `prompt`, `reference`, `rubric`, `wrong`, `leak`, `answer_kind`, `option`, `canonical`, `tolerance`, `stepwise`). See Deviations for the rules beyond Behaviour 4.
- `::parse_tolerance(draft) -> float | None` — the stored `tolerance` (numeric items with one only).
- `::clean_chunk_ids(draft, allowed) -> list[str]` — cited ids in `allowed`, cited order, deduplicated.
- `::rank_chunks_for_concept(concept_name, chunks, *, limit, min_score=0) -> list[dict]` — score = distinct casefolded name tokens of length >= `_MIN_TOKEN_LEN` (3), English function words (`_STOPWORDS`: "the", "and", "for", "with", …) excluded, that occur as WORDS in the chunk (a name with no such token scores 1 when its whole word sequence occurs); below `min_score` dropped; order `(score desc, chunk_index asc, id)`; first `limit`.
- `::select_item(items, *, format, difficulty, exclude_hashes=()) -> CheckItem | None` — exact format only; the exact difficulty first (ties by `(created_at or "", id)`), else the nearest (lower first on ties).
- `::posttest_reserve_hash(items) -> str | None` — lowest hash among `free` items at `CHECK_ITEM_DIFFICULTIES[1]`, else the lowest overall, else None (A23).
- `backend/services/check_item_service.py::concept_key(name)` — `graph_service._normalize_concept`, imported.
- `::create_items(course_id, concept_key, document_id, drafts, *, allowed_chunk_ids=(), source_document_ids=()) -> list[str]` — validates (invalid → dropped + WARNING), de-duplicates same-hash drafts, upserts every valid row in ONE call `on_conflict="course_id,concept_key,question_hash"`; `source_document_ids` stored sorted and de-duplicated, `[document_id]` when none are passed; raises on a PostgREST failure.
- `::list_items(course_id, concept_key, *, format=None, difficulty=None) -> list[CheckItem]` — filters on those plaintext columns only, `order="created_at,id"`; a bad row is skipped or degraded, never raised.
- `::items_for_concepts(course_id, concept_keys) -> dict[str, list[CheckItem]]` — ONE `in.(...)` select (values through `pg_quote_value`); every requested key present (`[]` when it has none); `{}` and no read for no keys.
- `::course_has_items(course_id) -> bool` — one `select("id", limit=1)`; feeds PKG-08's `no_check_items` and the A26 empty state.
- `::count_items(course_id, concept_key) -> int` — a select of ids.
- `::coverage(course_id) -> (with_items, concepts)` — over the course's `graph_nodes` concept keys; both reads page with `order="id"` (graph_nodes through the read-only handle `_GraphNodesRead`, see Deviations).
- `::chunks_for_document(document_id) -> list[dict]` — `course_chunks` rows `id, chunk_index, chunk_text, visibility, doc_id` by `doc_id`, read through `page_all(..., order="chunk_index,id")` (a document past PostgREST's 1000-row cap is read whole), `chunk_text` decrypted.
- `::document_is_item_source(row) -> bool` — `shareability == COURSE_MATERIAL` AND `decide_visibility(...) == SHARED`.
- `::source_chunks(doc_row) -> list[dict]` — not a source → `[]` (INFO); indexed → its SHARED rows only (none → `[]`, never the fallback); unindexed → `[{"id": None, "chunk_index": 0, "chunk_text": <decrypted extracted_text>, "doc_id": <id>}]` or `[]` (WARNING) when blank. Every passage carries `doc_id`.
- `::answerable_hook: Callable[[list[str], str, str], bool] | None = None` — the A24 stub; nothing sets or calls it.
- `::GenerationOutcome(items_created, concepts_attempted, unavailable, concepts_skipped, concepts_unmatched=0)` — a NamedTuple; compare it with FIVE-element tuples.
- `::generate_for_concepts(*, user_id, course_id, concept_names, chunks, flex, document_id=None, max_concepts=None, min_chunk_score=0) -> GenerationOutcome` — Behaviour 8; zeros with no read when the flag is off or `chunks` is empty; synchronous (`run_agent_sync`); `user_id=None` records usage against the system actor; every concept of one agent call stores the SAME `source_document_ids` (every document the call showed) and cites only passages the call showed (see Deviations). Right before a call's writes it re-reads that call's source documents (`_withdrawn_sources`: `id in.(…)`, `deleted_at is.null`, then `document_is_item_source`) and drops the call's drafts when any was deleted or opted out while the agent ran; a failed re-read drops them too (`StorageError` event). After the writes it re-reads once more and retires any source withdrawn in between; a failure there is reported (`StorageError`), never answered by deleting.
- `::generate_for_document(document_id, *, user_id, course_id, concept_names, flex) -> GenerationOutcome` — the upload hook: the `documents` row, `source_chunks`, then at most `CHECK_ITEM_MAX_CONCEPTS_PER_DOC` concepts.
- `::queue_generation_for_document(document_id, *, user_id, course_id, concept_names) -> Future` — submits `generate_for_document(..., flex=True)` (in a copy of the caller's contextvars; a failure logged, never raised) to `_draft_pool()`, a lazily built module `ThreadPoolExecutor(max_workers=CHECK_ITEM_DRAFT_WORKERS, thread_name_prefix="check-items")`, and returns at once.
- `::retire_items_for_documents(document_ids) -> int` — DELETEs every item whose `source_document_ids` overlaps (`ov.{...}`, 50 ids per call, `select=id`); logs the count; `0` and no call for no ids. NOT flag-gated.
- `::_withdrawn_sources(document_ids) -> list[str]` — the ids that are no longer item sources (deleted, or `document_is_item_source` false); one `in.(…)` documents read per 50 ids; raises on a PostgREST failure.
- `::retire_items_for_uploader(user_id) -> int` — every document the user uploaded (soft-deleted included, `page_all`) → `retire_items_for_documents`. NOT flag-gated. Raises nothing (it is a post-response BackgroundTask): a failure logs ERROR, emits `learn.check_items_failed` with `reason="WithdrawalError"` (`document_id`/`course_id` null) and returns 0; re-running it is safe.
- `backend/agents/check_items.py::CheckItemsOutput(items: list[CheckItemDraft])`, `::CheckItemsUnavailable(reason: str)`, `::check_items_agent` (the one `Agent[...]`, `retries=CHECK_ITEM_OUTPUT_RETRIES`, one `system_prompt`), `::build_prompt(concept_names, passages) -> str` (`[chunk <id>]` / `[passage]` markers, fenced as data), `::draft_items(concept_names, passages, *, deps, flex) -> CheckItemsOutput | CheckItemsUnavailable` (never raises; records usage with `user_id=deps.user_id or None`), `::_flex_settings() -> ModelSettings` (`{"service_tier": "flex", "timeout": FLEX_TIMEOUT_S}`), `::_backoff(attempt)`.
- `AgentTask` literal `"check_items"`; `_DEFAULTS["check_items"] = "gemini-2.5-flash-lite"`; env override `SAPLING_MODEL_CHECK_ITEMS`.
- Function-mode handler `register_function_handler("check_items", …)` in `backend/agents/function_handlers_e2e.py` with `E2E_CHECK_ITEM_PROMPT_TEMPLATE`, `E2E_CHECK_ITEM_REFERENCE`, `E2E_CHECK_ITEM_RUBRIC`, `E2E_CHECK_ITEM_WRONG_KEY`, `E2E_CHECK_ITEM_WRONG_TEXT`, `E2E_CHECK_ITEM_OPTION_LETTERS`, `E2E_CHECK_ITEM_OPTION_TEXTS`, `E2E_CHECK_ITEM_CORRECT_OPTION`, `E2E_CHECK_ITEM_MC_WRONG_KEYS`, `E2E_CHECK_ITEM_MC_WRONG_TEXTS`, `E2E_CHECK_ITEM_MC_REFERENCE` (one item per format at difficulty 1 for each `E2E_DOC_CONCEPTS` name: 6 items).
- Event `learn.check_items_failed` (`category="error"`; payload `document_id, course_id, reason` — the exception class name, `StorageError`, or `WithdrawalError` for a failed opt-out withdrawal) in `EVENT_TAXONOMY` and the pin test.
- `backend/routes/documents.py::_index_then_check_items(doc_id, user_id, course_id, concept_names)` — `index_document`, then the drafting: `generate_for_document(..., flex=True)` in the calling thread when `model_mode() == "function"`, else `queue_generation_for_document(...)` (real mode never drafts on the shared post-roll thread); each step logged and never raised. Scheduled by both upload routes only under the flag (SSE label `index_then_check_items`); inline (`await asyncio.to_thread`) when `model_mode() == "function"`. `delete_document` calls `retire_items_for_documents([document_id])` after the soft delete.
- `backend/routes/profile.py` — the settings PATCH adds `background_tasks.add_task(retire_items_for_uploader, user_id)` beside the chunk-visibility resync when `share_class_context` becomes `False`.
- `backend/scripts/backfill_check_items.py::main(argv)`, `::_project_ref()` — `(--course <id> | --all-courses) --project <ref> [--dry-run] [--function-mode]`; Behaviour 11.
- `backend/tests/evals/check_items.py` — dataset `check_items` (6 cases, 6 evaluators), in `run_all.py` `DATASETS` and `baselines.json`.
- `backend/tests/test_agent_output_schemas.py::PER_OBJECT_EXCEPTIONS = {"CheckItemDraft": 17}`, `::test_per_object_exceptions_are_exact`; `check_items_agent` in `EXPECTED_STRUCTURED_AGENTS`.
- `backend/tests/test_learning_loop_invariants.py` — `SERIES_AGENT_TASKS`, `SERIES_AGENT_MODULES`, `STUBBED_AGENT_MODULES`, `ENCRYPTED_LEARNING_COLUMNS`, `_FILTER_ON_ENCRYPTED`, `_backend_py_files()`; `test_inv_06/09/12` real.
- Tests: `backend/tests/test_learning_check_items.py` (120), one test in `tests/test_e2e_function_handlers.py`, one in `tests/test_agent_output_schemas.py`.

## Constants chosen

- `CHECK_ITEM_FORMATS = ("free", "teachback", "mc_reason")` — defined by PKG-01 (spec §3.4)
- `CHECK_ITEM_DIFFICULTIES = (1, 2, 3)` — defined by PKG-01 (spec §3.4)
- `CHECK_ITEM_MIN_RUBRIC = 2` — defined by PKG-01 (spec §3.4)
- `CHECK_ITEM_MIN_WRONG = 1` — defined by PKG-01 (spec §3.4)
- `CHECK_ITEM_MAX_CHUNKS = 8` † (§13 A6)
- `CHECK_ITEM_MAX_CONCEPTS_PER_DOC = 10` † (§13 A6, A23; per upload, the backfill is uncapped)
- `CHECK_ITEM_OUTPUT_RETRIES = 2` (§13 A6)
- `CHECK_HASH_VERSION = "v1"` (§4 `question_hash` pattern)
- `CHECK_ITEM_INITIAL_PER_CONCEPT = 9` † (§3.5, A23; `= 3 × 3`)
- `CHECK_ITEM_CONCEPTS_PER_CALL = 3` † (§3.5, A23)
- `FLEX_TIMEOUT_S = 900` (§3.5, A23)
- `CHECK_ITEM_ANSWER_KINDS = ("free", "numeric")` (§3.5, A22)
- `CHECK_ITEM_STEPWISE_MIN_STEPS = 2` † (A17/A22 "≥ 2 numbered steps"; spec lacks the name)
- `CHECK_ITEM_FLEX_RETRIES = 2` † (A23 "retries on 503/429"; spec lacks the count)
- `CHECK_ITEM_BACKFILL_MIN_CHUNK_SCORE = 1` † (§3.5, A23 relevance floor)
- `CHECK_ITEM_DRAFT_WORKERS = 2` † (review round 1; spec lacks it: upload-time drafting runs on its own bounded pool, see `queue_generation_for_document`)

Module-level, not loop tuning: `learning/checks.py::_MIN_TOKEN_LEN = 3` (tokenizer floor the prompt allows), `learning/checks.py::_STOPWORDS` (function words that never count toward the relevance floor), `agents/check_items.py::_FLEX_RETRY_STATUS = {429, 503}`, `services/check_item_service.py::_DOC_ID_BATCH = 50` (URL-length bound, #629's `_ID_BATCH` rationale).

## Deviations from spec

- Branch `feat/learning-loop-04-check-items` cut from `feat/learning-loop` (b099fef, PR #673's branch) → session override: the series integrates on `feat/learning-loop`; no push, no PR (Task 9 skipped; the integrator merges).
- Full suite `pytest tests/ -q` → run with `-p no:cacheprovider --ignore=tests/evals --ignore=tests/test_docling_integration.py --ignore=tests/test_ocr_pipeline.py --ignore=tests/test_extraction_backends.py` → OCR stack not installed (session override; CI's ignore set). N₀ = 3355 passed, 141 skipped; after PKG-04, 3482 passed, 138 skipped (+124 new test ids, 3 invariants un-skipped; zero failures, no new skips).
- SoW `ls backend/db/migrations | tail -1` prints `README.md` → the latest migration is `20260927035346_learning_flashcards_fsrs.sql`; `20260927065932_learning_check_items.sql` sorts after it. Not a red row (PKG-03/11 recorded the same).
- `CHECK_ITEM_STEPWISE_MIN_STEPS`, `CHECK_ITEM_FLEX_RETRIES` → spec lacks; added.
- Task 2's params code block lists ten names and omits `CHECK_ITEM_BACKFILL_MIN_CHUNK_SCORE` → appended eleven (the §Named constants table and spec §3.5 define it; Behaviour 11 consumes it).
- Test-module imports arrive with the task that first uses them (`json`, `MagicMock`, `patch`, `pytest`) → ruff F401 fails a module that imports them unused (PKG-11 did the same).
- The prompt's test literals for `chunks_for_document` and the extracted-text fallback lack `doc_id` → the tests assert `doc_id` → Behaviour 7 ("every passage dict carries `doc_id`") and Behaviour 6 (`source_document_ids` from passage `doc_id`s) need it.
- The prompt's generation tests compare the outcome with FOUR-element tuples (`out == (8, 4, 0, 0)`) → five-element tuples → `GenerationOutcome` has five fields (the default keeps four-argument construction valid, but a 5-field NamedTuple never equals a 4-tuple).
- The prompt's route tests read `fn.__name__` off scheduled callables → a `_fn_name` helper (patched callables are MagicMocks with no `__name__`); the SSE helper patches `record_agent_usage` with the identity (the route uses its return value). SSE hook tests added (`TestSseUploadHook`).
- Invariant 1 (PKG-03's ast half) flags `page_all(table("graph_nodes"), …)` — a graph-table handle passed on → `coverage` and the backfill read graph_nodes through `_GraphNodesRead`, a `page_all` handle whose every page is a direct `table("graph_nodes").select_with_count(...)` (commit 32108b4). Paging is unchanged; inv_01 is untouched.
- `tests/test_agent_output_schemas.py` (pre-series, outside the Files lists) freezes the agent roster and the #153 budget of ≤ 8 properties per object; the prompt's flat `CheckItemDraft` has 17 → `check_items_agent` joins `EXPECTED_STRUCTURED_AGENTS`, and `CheckItemDraft` gets a named, exact per-object exception (`PER_OBJECT_EXCEPTIONS`, pinned by `test_per_object_exceptions_are_exact`); depth, total (18 ≤ 20), no-optional-nested and enum rules still apply. Gemini (2.5-flash-lite, tool output) accepted the schema in all three live recordings (commit 24bbd45).
- `leak_in_prompt` "normalized reference appears verbatim inside the normalized prompt" → the same check on word sequences (punctuation dropped, whole-word match) → the prompt's own leak test has a reference ending in "." inside a longer prompt sentence, which a plain normalized substring check misses.
- `validate_draft` rules beyond Behaviour 4, each named in its reason: a blank wrong key (`wrong`); blank rubric entries do not count toward the minimum (`rubric`); duplicate option letters, the correct option carrying a wrong_key, and an `mc_reason` item with no distractor (`option`); a non-finite `canonical_answer` (`nan`, `inf`) or `tolerance` (`canonical`, `tolerance`).
- `create_items` also drops a second draft with the same normalized prompt in one batch → PostgREST rejects an upsert that names one row twice.
- Passage de-duplication keys an id-less fallback passage by its document, not by `id` → the backfill can pass several unindexed documents' fallbacks, and "the None-id passage passes through once" would drop all but one.
- Task 5 / Behaviour 8: "each concept's `source_document_ids` = the distinct `c["doc_id"]` of ITS ranked chunks" and `allowed_chunk_ids={c["id"] for c in chunks}` → every concept of a call records the documents of EVERY passage the call showed, and `allowed_chunk_ids` is the ids the call showed → spec §13 A23 ("records every document whose passages drafted an item") wins: one call shows the model the union of its batch's passages, so in a multi-document backfill batch an item could use or cite another concept's document and survive that document's withdrawal (review round 1, critical).
- `_index_then_check_items` logs and swallows each step's exception (the prompt's body had no guard) → in function mode it runs inline, and a failure must not fail the upload; an indexing failure still drafts (from the extracted text).
- Behaviour 10's real-mode post-roll `_index_then_check_items` = index then `generate_for_document` on the same thread → index on the post-roll thread, then QUEUE the drafting on `check_item_service`'s own pool (`CHECK_ITEM_DRAFT_WORKERS` †) → review round 1 (major): the post-roll runs on the loop's default executor (`min(32, cpus + 4)` threads) or Starlette's 40-token request threadpool, and one upload's Flex drafting can hold its thread for minutes (hours worst case), so a handful of concurrent uploads would starve every other threaded call in the process. Function mode is unchanged (inline).
- `retire_items_for_documents` sends at most 50 ids per `ov.{…}` and adds `select=id` to the delete → bounded URL length (the #629 `_ID_BATCH` rationale) and ids-only return rows.
- Eval `_run` records through `_replay._run_with_retry` (transient 503 retry), not a bare `agent.run`.
- Eval Step 2: the first recording scored DraftValid 0.222 and WrongReasonCount 0.333 (< 0.5) → `_PROMPT` revised twice (the nine pairs in order; wrong reasons on every format; one `option_wrong_keys` entry per option with a shape example) and four `CheckItemDraft` fields gained short schema descriptions; baselined from the third recording (commits 5ca2b33, 916eef7).
- Self-check 5 (E2E) → run as `e2e_cycle` (session override), exporting `LEARNING_LOOP_ENABLED=false` for the flag-off cycle and `true` for the flag-on smoke → an exported variable beats `backend/.env` (python-dotenv never overrides), so the flag-on smoke needed no stack-script change and is not a Known gap.
- Acceptance 14 `git diff --stat main...HEAD` → measured as `git diff --stat feat/learning-loop..HEAD` → the lane is cut from the series branch; the paths are the listed ones plus `backend/tests/test_agent_output_schemas.py` (above).

## Known gaps

- `canonical_verified` is always `false` — no agreement check exists, so every numeric answer goes to the rubric grader (A22).
- A course with no shared `course_material` gets no items (A23 coverage cost); `course_has_items` lets PKG-08/13 say so.
- A partially covered concept (1 to `CHECK_ITEM_INITIAL_PER_CONCEPT` − 1 items) receives a full fresh set on the next upload or backfill that names it, so it can end above `CHECK_ITEM_INITIAL_PER_CONCEPT`. This is common in practice: in the baseline recording 10 of 18 `mc_reason` drafts have fewer `option_wrong_keys` than options (7 omit the correct option's `""`, 3 leave the list empty) and `validate_draft` drops them, so a concept lands at 6–9 items after one call (per case: 6, 6, 9, 7, 6, 9).
- `answerable_hook` is an unwired A24 stub.
- Real student wrong reasons are not harvested yet (PKG-10); `wrong_keys` are model-invented.
- The eval baseline is a first recording (DraftValid 0.796, RubricCount 0.833, the rest 1.0).
- Coverage after launch depends on the owner's nightly `--all-courses` job (spec §11.7 step 11) — the upload hook drafts at most `CHECK_ITEM_MAX_CONCEPTS_PER_DOC` concepts per upload and nothing else adds items.
- Withdrawal DELETES items; re-sharing restores nothing until a later upload or backfill drafts afresh. An item drafted from several documents (a backfill batch can mix passages of several uploaders) is deleted when any one of them is withdrawn — and every item of one agent call records every document that call showed, so withdrawing one uploader's document also retires the call's items for the other concepts of its batch (the price of A23 provenance at call granularity).
- A concept whose name no shared passage contains as a word is never backfilled (`unmatched`, A23 relevance floor). Matching is whole-token, so an inflected name ("Derivatives" vs a passage saying "derivative") counts as unmatched. Function words never count (review round 1: "Causes of the French Revolution" met the floor against a CS passage through "the"), so an off-topic name must share a content word with a shared passage to be drafted — one shared content word still suffices (spec's floor is 1).
- The extracted-text fallback passage is the document's whole text (unbounded length). It is used only for an unindexed source document — always in function mode, and in real mode only when indexing failed or wrote nothing.
- Real-mode upload drafting is an in-process queue (`CHECK_ITEM_DRAFT_WORKERS` at a time): a restart drops what is queued or in flight, and a burst of uploads waits its turn. The nightly `--all-courses` backfill drafts whatever was dropped.
- The function-mode handler serves only the two `E2E_DOC_CONCEPTS` names; a function-mode backfill of any other concept drops its drafts with a WARNING (seen in the live probe: `unmatched 5`, 6 items re-upserted idempotently).
- Self-check 1's `ruff format --check learning tests/test_learning_*.py` reports one file, `tests/test_learning_flashcards_fsrs.py` (PKG-11's, pre-existing, untouched here); every PKG-04 file is formatted and `ruff check .` passes.
- Flakes observed: none (`e2e/gradebook.spec.ts:35` passed in the full cycle).

E2E, run on this branch (all `exit 0`, oracles 0 findings):
- Full lane, `E2E_FRESH_DB=1`, `LEARNING_LOOP_ENABLED=false`: 71 migrations replayed from an empty PG15 volume (including `20260927065932_learning_check_items.sql`); Playwright 89 passed, 13 skipped, 0 failed; `check_items` rows after the run: 0 (the hook is inert with the flag off).
- Flag-on smoke, `LEARNING_LOOP_ENABLED=true`, `e2e/upload.spec.ts`: 2 passed; the inline chain drafted 6 items (2 concepts × 3 formats) from the extracted-text fallback, every row with `source_document_ids` set, `canonical_verified = false`, `graded = false`, distinct hashes; 0 `UnregisteredHandlerError`, 0 failure lines.
- Flag-on smoke + live-DB probe (same spec, 2 passed): backfill `--dry-run` printed `Project: local`, per-course coverage (`rich-course-cs101 2/7`) and the two keys it would draft; a `--function-mode` backfill of cs101 re-upserted the same 6 rows (`items 6 attempted 2 unmatched 5`, exit 0); `--project someprodref` refused before any read; `list_items` decrypted, the `mc_reason` item had 4 options and correct letter `A`, `items_for_concepts`/`count_items`/`coverage` agreed; `retire_items_for_documents([doc])` deleted all 6 through the real `ov.{…}` filter and `course_has_items` then read `False`.

## Verify commands

```
cd backend && venv/bin/python -m pytest tests/test_learning_check_items.py -q                   → N passed (N ≥ 14)
ls backend/db/migrations/*_learning_check_items.sql                                              → 1 file
grep -c '"check_items"' backend/agents/_providers.py backend/agents/function_handlers_e2e.py     → ≥ 1 each
grep -ohE "options_json|correct_option|answer_kind|canonical_answer|canonical_verified|stepwise" backend/db/migrations/*_learning_check_items.sql | sort -u | wc -l → 6
grep -c -- "--all-courses" backend/scripts/backfill_check_items.py                               → ≥ 1
cd backend && SAPLING_EVAL_MODE=replay venv/bin/python tests/evals/check_items.py                → every evaluator ≥ baseline
cd backend && venv/bin/python -m pytest tests/test_learning_loop_invariants.py -q -k "inv_06 or inv_09 or inv_12" → 3 passed
```

(Observed at hand-off: `120 passed`, `backend/db/migrations/20260927065932_learning_check_items.sql`, `2` / `1`, `6`, `2`, every evaluator at baseline, `3 passed, 10 deselected`.)

## Open questions for the series owner

- Should upload-time generation usage stay attributed to the uploader (it counts toward their A20 daily spend), or move to a NULL `user_id` like the backfill? Taken option: the uploader (Behaviour 8).
- The flat 17-field `CheckItemDraft` is the one structured output above the #153 per-object budget (a named exception). Gemini accepted it live; if a model change starts rejecting it, the fallback is splitting the call (items first, options second), which the one-prompt-stack invariant (spec §8.12) would have to admit. Taken option: keep the flat draft.
- More than half of the recorded `mc_reason` drafts (10 of 18) have fewer `option_wrong_keys` than options, so they are dropped (Known gaps). For the 7 that list exactly one key per distractor a code-side repair is unambiguous (map the keys to the distractors in order), but Behaviour 4 makes a length mismatch invalid. Taken option: follow Behaviour 4 and keep dropping them.

## Post-hoc changes

(Appended by later packages that modified this package's code. Format: `PKG-MM <date>: <what> — commit <sha>`.)
