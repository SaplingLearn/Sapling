# Study guide redesign

Status: built on `feat/study-guide-redesign`, stacked on #870 (`feat/study-page`); in review.
Design reference: Trov artifact `sapling-study-guide-redesign-study-guide-reader` (reader screen).
The Study Guides home and the New study guide modal have no artifact; they follow the written spec in Trov handoff #30.

A study guide used to be a cache: one row per student, class and exam, deleted whenever the class's documents changed, holding a flat list of topics. It is now the student's own durable document: many per class, for an exam, an assignment or the whole course, written as prose with typed blocks inline.

## 1. Audit: what the design needs against what exists

| Design element | State | Where it comes from |
|---|---|---|
| Sticky top bar, back link, AI chip | exists | `TopBar`, `BackLink`, `AIDisclaimerChip` |
| Read / Skim toggle | exists | `Toggle` (`components/ui`) |
| Dialog shell for the modal | exists | `Dialog`, `StudyModal` |
| Mastery colours and labels | exists | `--state-*` tokens, `studyModel.ts` `TC` / `SC` / `ST_LABEL` |
| Mastery per concept | exists | `graph_nodes.mastery_score` / `mastery_tier`, `config.get_mastery_tier` |
| Mastery write from one answer | exists | `graph_service.apply_graph_update`, `quiz.config.mastery_after` |
| Quiz mistakes per concept | exists | `quiz_context.context_json` (`common_mistakes`), read per concept node |
| Exams and assignments of a class | extend | `assignments` by enrollment; today's `/exams` filters to exams only |
| The class's documents | exists | `documents` (plaintext `file_name`, `category`, `created_at`) |
| Markdown and math in prose | exists | `MarkdownChat` (KaTeX) |
| Streamed responses | exists | `sse_starlette` + `agent_events.SaplingEvent`, `lib/sse.ts` |
| Tutor hand-off | exists | `askTurn.ts` (`openTutorSession`, `chatWithFallback`), `/learn?resume=` |
| Guide storage | extend | `study_guides` gains columns; the per-exam unique key and the delete-on-upload go |
| Guide generation | new | outline agent + section writer + block rewriter, one `services/study_guides` package |
| Typed blocks (8 kinds) | new | `models/study_guide.py` discriminated union |
| Citations and a sources list | new | document-level only (see section 8) |
| Chart rendering | new | hand-drawn SVG; no chart library is added |
| Progress ring, mastery bar, cards grid, sort menu, search field | new | small components under `components/studyGuide` |
| Read state, saved state, stale banner, previous version | new | columns on `study_guides` |
| Saved guide in the Library | new | the Library lists documents only today; it gains a guide card kind |
| Export PDF | new | the browser's print dialog with a print stylesheet |
| Function-mode handler | new | none exists for `study_guide` today, so E2E could never generate |

Nothing in the design needs existing user data to be dropped. Rows written before this change stay, and are upgraded when read (section 2).

## 2. Data model

One table, reshaped in place. No new table.

`study_guides` after the migration:

| Column | Type | Notes |
|---|---|---|
| `id`, `user_id`, `offering_id` | as before | |
| `exam_id` | TEXT, now nullable | The `assignments` row the guide is for (an exam or an assignment). NULL for a whole-course guide. Name kept so code deployed before the migration keeps working. |
| `scope_kind` | TEXT, default `exam` | `exam` / `assignment` / `course`. CHECK: `course` exactly when `exam_id` is NULL. |
| `goal` | TEXT, default `exam_prep` | `practice` / `review` / `exam_prep` |
| `depth` | TEXT, default `standard` | `cram` / `standard` / `deep` |
| `use_history` | BOOLEAN, default true | |
| `status` | TEXT, default `ready` | `generating` / `ready` / `failed` |
| `format` | SMALLINT, default 1 | 1 = a pre-redesign row (`{exam, due_date, overview, topics}`), 2 = `GuideContent` |
| `content` | JSONB, encrypted | as before; the shape depends on `format` |
| `previous_content` | JSONB, encrypted, nullable | the version replaced by the last Update or Regenerate |
| `material_ids` | JSONB, default `[]` | the document ids the guide was made from |
| `read_sections` | JSONB, default `[]` | section ids marked read |
| `answers` | JSONB, encrypted, nullable | `{block_id: {option_id, correct}}` |
| `feedback` | TEXT, nullable | `yes` / `no` |
| `saved_at` | TIMESTAMPTZ, nullable | set = saved to the Library |
| `generating_at` | TIMESTAMPTZ, nullable | the generation claim's heartbeat |
| `generated_at` | as before, now nullable | NULL until the first generation finishes; then when a run last made the guide (section 5, step 6) |
| `created_at`, `updated_at` | TIMESTAMPTZ | `created_at` backfilled from `generated_at`; `updated_at` by the shared trigger |

Also in the migration: drop the index `study_guides_user_offering_exam_key` if an environment has it, and drop `ensure_study_guides_unique_key()`. Existing rows are not touched beyond the defaults.

Decisions:

- **Reshape, not new tables.** Guide state is small and always read with the guide. One row keeps wipe, bundle, RLS and oracles on a table they already know.
- **No uniqueness.** A student can keep several guides for the same exam.
- **No invalidation.** `_invalidate_study_guide_cache` and its three callers are deleted. A guide made before new lectures arrived shows a banner instead (`new_materials`).
- **Old rows.** A format-1 row is read through `legacy.content_from_topics`, which turns each topic into a section. It shows on the home like any guide; Regenerate rewrites it as format 2. The account seeder and the rich seed use the same function, so the seed packs keep their `overview` + `topics` content.
- **One previous version.** `previous_content` holds the version before the last Update or Regenerate. The design mentions a history but shows no screen for one, so a single step back is stored and nothing lists it yet.

## 3. The contract

`backend/models/study_guide.py` owns every shape; `frontend/src/lib/studyGuide/types.ts` mirrors it; `backend/tests/fixtures/study_guide_contract.json` pins the two (a backend test validates it, the frontend reader tests render it).

A guide's `content` is a `GuideContent`: title, deck, three takeaways, sources, and sections. A section has a title, the graph concept it teaches, the mastery tier and share of the guide it had when written, a one-line essence, and `items`: an ordered list of `prose` passages and blocks.

Blocks: `chart`, `mistakes`, `formula`, `worked_example`, `comparison`, `concept_map`, `key_terms`, `check`. There is no flashcards block.

`parse_items` validates each item on its own, so one malformed block is rejected without losing its section.

## 4. API

All under `/api/study-guide`, all `require_self` on `{user_id}`, mounted behind `hide_study` as today.

| Method and path | Body | Returns |
|---|---|---|
| `GET /{user_id}/guides` | | `{guides: GuideCard[]}`, newest first |
| `GET /{user_id}/options?course_id=&semester=` | | `GuideOptions` (scopes with suggested materials, the class's materials) |
| `POST /{user_id}/plan` | `GuideRequest` | `GuidePlan` (no model call) |
| `POST /{user_id}/guides` | `GuideRequest` | 201 `{id}`; the row is `generating` with no sections yet |
| `GET /{user_id}/guides/{guide_id}` | | `GuideDetail` |
| `PATCH /{user_id}/guides/{guide_id}` | `GuidePatch` | `GuideState` |
| `POST /{user_id}/guides/{guide_id}/generate` | `GenerateBody` | SSE stream (below); 409 when another run holds the claim |
| `POST /{user_id}/guides/{guide_id}/blocks/{block_id}/regenerate` | | `{block}` |
| `POST /{user_id}/guides/{guide_id}/blocks/{block_id}/answer` | `AnswerBody` | `AnswerResult` |

Removed: `/cached`, `/courses`, `/exams`, `/guide`, `/regenerate`.

The generate stream uses `services.agent_events.SaplingEvent` (`{type, step, message, data}`):

- `status`: `message` is the label ("Reading your 6 materials", "Writing section 2 of 4: Loops", "Checking citations and blocks"); `data` is `{step, total}`.
- `progress`, step `outline`: `data.content` is the `GuideContent` with every section `queued`.
- `progress`, step `section`: `data.section` is one written `Section`.
- `done`: `data.guide` is the finished `GuideDetail`.
- `error`: `message` is the reason; `data.retryable`.

Modes: `resume` writes whatever is still queued (a new guide, or one whose stream was cut); `update` folds in the lectures added since and keeps the sections they do not touch; `regenerate` rewrites everything, and reads those new lectures too. `update` and `regenerate` copy the last finished `content` to `previous_content` in the same write that saves their first new section, once per run, and only when the guide being replaced was readable.

## 5. Generation

1. **Claim.** `generating_at` is the claim. The request is refused with 409 while a claim is held; the stream then takes the claim as its first act (so a client that disconnects before the stream starts leaves nothing held), and a run that loses that race ends with an `error` event. A run takes it when it is NULL or older than fifteen minutes (longer than the slowest model call with its retries), refreshes it after every section, and clears it on exit, including a cancelled stream. The claim's timestamp is the run's token: a run that finds its token gone was overtaken and stops without writing. A second request while a claim is fresh gets 409; the reader re-reads the guide, waits, and asks to resume again.
2. **Read.** The chosen documents' `summary`, `concept_notes` and `extracted_text`, budgeted (30 documents, 10k characters each, 60k in total) and wrapped with `prompt_safety.wrap_untrusted`. Each source gets a short label (`S1`, `S2`, ...). With history on: the student's mastery per concept and their `quiz_context` mistakes for those concepts.
3. **Outline.** `study_guide_outline_agent` (structured, small): title, deck, takeaways, and sections as `{title, concept, one_line, keep_id}`. `concept` must be one of the student's concept names or null. The server, not the model, sets each section's tier and weight from mastery: struggling 5, learning 3, unexplored 3, mastered 1, scaled to 100. With history off every section weighs the same. The server also sets each section's id: a new section is numbered after every id the guide has, on an Update and on a Regenerate alike, so an id never names two pieces of text and an answer or read mark sent by a tab still showing the old guide finds nothing to land on. For a new guide the outline is saved and sent before any section is written. An Update or Regenerate of a finished guide sends the outline but saves nothing until its first section is written, so a run that fails early leaves the guide exactly as it was.
4. **Sections, one at a time.** `study_guide_section_agent` is a text agent. It writes prose with fenced JSON blocks; `services/study_guides/markup.py` turns the text into items and maps `[S1]` to source ids. A rejected block is rewritten once by `study_guide_block_agent`, then dropped. Each section is saved as soon as it is written, so a cut stream resumes at the next queued section.
5. **Check.** `verify.py` drops citations to unknown sources, stamps each mistake's evidence from the real quiz history (and drops one that cites none), drops a check question whose answer is not among its options, clears concept names the student's tree does not have, and decides every chart's `illustrative` flag.
6. **Finish.** `status = ready`, `generated_at = now`, and the claim cleared, all in one write; then the `done` event, so the guide is free the moment the reader hears it is ready. `generated_at` is stamped by every run that planned the guide and by a `resume` that makes it ready from `generating` or `failed` (a first generation, an Update or a Regenerate that was cut short). A `resume` that only fills in failed sections of a guide that stayed `ready` leaves it alone: it read nothing new.

   A section the writer could not write is marked `failed` and the run goes on; `resume` tries it again. The guide itself is saved as `failed` in two cases, and only while its row holds this run's content and says `generating` (a new guide, a resumed one, or an Update or Regenerate after its first saved section):

   - the run reached its end and no section at all was written;
   - the run stopped part way on an error (the outline could not be planned, an unexpected exception, a daily-budget refusal). The sections it had already written stay on the failed guide, and `resume` writes the rest.

   A run leaves the guide as it was when it had not replaced it yet (an Update or Regenerate before its first saved section), when it was filling in sections of a guide that stayed `ready`, and when it was overtaken and lost its claim.

`update` gives the outline agent the current outline and the new documents; a section it returns with `keep_id` is kept as written, with its read state. Everything else is written fresh.

All three agents run on the existing `study_guide` slot. One function-mode handler serves them, so the E2E lanes generate deterministically.

## 6. Package layout

`backend/services/study_guides/`, one job per file:

| File | Job |
|---|---|
| `errors.py` | domain errors with a status and a detail |
| `store.py` | the request path's only reader and writer of `study_guides` (the account wipe, bundle and seeder, the rich seed and the encryption backfill touch the table too): rows to `GuideRow`, encryption, the generation claim, the once-only answer write |
| `legacy.py` | a format-1 row's content as `GuideContent` |
| `scopes.py` | course to offering and enrollments; what a guide can be for; a scope's title and date |
| `materials.py` | the class's documents, the suggested set per scope, source text for the prompt, the new-materials count |
| `signals.py` | mastery tier per concept; quiz mistakes per concept |
| `plan.py` | the planned outline and section weights |
| `limits.py` | the hourly limits on creating, generating and rewriting, each overridable by env |
| `inputs.py` | what one run reads: sources, mastery and quiz mistakes, as the writer's brief |
| `outline.py` | how many sections a guide may have, and turning the model's outline into sections |
| `markup.py` | the section writer's text as items |
| `prompts.py` | the user messages for the three agents |
| `writer.py` | runs the agents, records usage, retries a rejected block |
| `verify.py` | the citation and block check |
| `generation.py` | one generation run as a stream of events: prepare, the claim, the steps, failure handling |
| `blocks.py` | regenerate one block |
| `create.py` | validate a `GuideRequest` and insert the row |
| `options.py` | what a new guide for a class can be for, and from which materials |
| `cards.py` | `GuideRow` to `GuideCard` |
| `detail.py` | `GuideRow` to `GuideDetail` |
| `state.py` | apply a `GuidePatch` |
| `answers.py` | grade a check answer and move mastery once |

`routes/study_guide.py` becomes async handlers that call one function each and map the package's errors.

Frontend, under `frontend/src/components/studyGuide/`: `shared/` (tier styling, the space bar), `home/` (toolbar, cards, the modal and its parts), `reader/` (top bar, header, sections, one file per block, rail, generation banner). Routes: `/study/guide` (home) and `/study/guide/[guideId]` (reader).

## 7. Build waves

| Wave | Owner | Files |
|---|---|---|
| 0 | lead | the contract, the fixture, this document |
| 1 | data | migration, `store.py`, `legacy.py`, `errors.py`, removal of the upload invalidation, account wipe / bundle / seed / backfill, rich seed, oracles |
| 1 | agents | `agents/study_guide.py`, `markup.py`, function-mode handler, agent pins |
| 1 | inputs | `scopes.py`, `materials.py`, `signals.py`, `plan.py` |
| 1 | reader | `components/studyGuide/reader/`, the reader route |
| 1 | home | `components/studyGuide/home/`, the home route, removal of the old screen, Study hub and Library links |
| 2 | generation | `prompts.py`, `writer.py`, `verify.py`, `generation.py`, `blocks.py` |
| 2 | serving | `cards.py`, `detail.py`, `state.py`, `answers.py`, `create.py`, the route, pins and docs |
| 2 | frontend integration | testids, lint block, tutor hand-off, print stylesheet, review fixes |
| 3 | lanes | the Playwright journey, oracles, full suites |

A reviewer that wrote none of the code reviews each wave against the handoff.

## 8. Decisions flagged for review

- **Citations name a document, not a page.** Extraction returns one string per file and no page or slide provenance is stored anywhere, so a "p. 4" would be invented. Page-level citations need an extraction change and a re-upload of existing files.
- **Guides are private and built only from the student's own documents.** Generation reads the student's `documents` rows, never the shared `course_chunks` pool, so a classmate's material cannot appear in a guide or its sources, and a student who opted out of sharing loses nothing. Guide content is never shared with the class.
- **Charts.** A chart counts as plotted from data only when every number in it appears in the text of the source it cites. Otherwise it is labelled "Illustrative shape, not plotted from data" and drawn without axis numbers.
- **Quiz mistakes.** The model is given the student's recorded mistakes with ids and may only cite those; the evidence line is written by the server. The design's "Quiz 4, question 3" is not available: mistakes are stored per concept, not per question.
- **Export PDF** is the browser's print dialog over a print stylesheet. No PDF library is added on either side.
- **Planned outline** in the modal is computed from the chosen materials' concepts and the student's mastery, with no model call. The outline the model then writes may merge or rename sections.
- **Takeaways** arrive with the outline, not after the last section as in the mockup's animation.
- **Check questions** withhold the answer until the student picks one. Only the first answer moves mastery; later picks are graded but not counted.
- **Tutor.** "Ask about this guide" starts a tutor session on the guide's title and sends the question with the section outline as the first message, then opens the tutor on that session. A true attachment field on the tutor API was not added.
- **Back link.** The reader's back link goes to the Study Guides home and is labelled "Study Guides". The handoff's mockup says "Study", but the hub is one more step back and the home is where the student's guides are.
- **PR #735** (draft, 907 commits behind) edits the old route and adds a separate saved-plans table. It conflicts with this rebuild and was not built on.
