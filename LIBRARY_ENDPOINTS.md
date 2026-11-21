# Library endpoint audit

Written before the Library redesign (README §2). Column **New home** says where
each existing capability lives in the redesigned page — nothing in the old page
is dropped.

Old page: `frontend/src/components/screens/Library.tsx`, route
`frontend/src/app/(shell)/library/page.tsx`.

## 1. What the old page called

| # | Client fn (`src/lib/api.ts`) | HTTP | Used for | New home |
|---|---|---|---|---|
| 1 | `getDocuments(userId)` | `GET /api/documents/user/{user_id}` | The document list (id, course_id, file_name, category, summary, concept_notes, created_at, processed_at) | Same call. Feeds rows, panel cards, counts, search, the type filter and the sort. |
| 2 | `getCourses(userId)` | `GET /api/graph/{user_id}/courses` | Course rail + per-course counts; `color`, `course_code`, `course_name`; deduped per abstract `course_id` (#449) | Same call, same dedupe. Feeds the course switcher dropdown, the course dots and the upload modal's course picker. |
| 3 | `deleteDocument(id, userId)` | `DELETE /api/documents/doc/{id}` | Delete from the detail modal (soft delete: stamps `deleted_at`) | Row `⋯` → **Move to Trash**, bulk **Move to Trash**, and drag-onto-Trash. Shows the Undo toast. |
| 4 | `scanDocumentConcepts(id, userId)` | `POST /api/documents/doc/{id}/scan-concepts` | "Scan" in the detail panel — extends the knowledge graph from one document | Row `⋯` → **Scan to Knowledge Graph**. (The v2 design drops the old preview panel; the action moves into the row menu so it is not lost.) |
| 5 | `scanCourseConcepts(courseId, userId)` | `POST /api/documents/course/{id}/scan-concepts` | "Scan <COURSE>" button in the TopBar, shown only on a course filter | Course-scope header: shown next to the course switcher when a single course is open. |
| 6 | `uploadDocumentStream(formData, onEvent, signal, requestId)` | `POST /api/documents/upload` (SSE) | Streaming upload with progress, per-file retry, abort, request-id surfacing | Upload split button and drag-and-drop. The "Where Does This Belong?" dialog picks the course and folder, then shows each file's progress; `useUploadQueue` keeps `DocumentUploadModal`'s engine (the 4-minute timeout, per-file cancel, and the #759 retry that reuses the attempt's `X-Request-ID` so a document the server saved is replayed, not processed twice). |
| 7 | `uploadDocument(formData, signal)` | `POST /api/documents/upload/sync` | Non-streaming fallback | Unchanged, still exported. |
| 8 | `updateDocumentCategory(id, userId, category)` | `PATCH /api/documents/doc/{id}` | Category change | Row `⋯` → **Type**. Extended (see §3) to also carry `file_name`, `folder_id` and `course_id`. |
| 9 | `listGuides(userId)` via `useLibraryGuides` | `GET /api/study-guides/user/{id}` | Saved study guides shown inside the Library | `LibraryGuides` keeps rendering above the documents, inside the new list; guides follow the course filter, the search and the "Study Guide" type chip exactly as before. |

Non-API behaviour the old page owned, and where it now lives:

| Old behaviour | New home |
|---|---|
| Category filter pills (`all`, `lecture_notes`, `syllabus`, `reading`, `slides`, `study_guide`, `assignment`) | **Type** dropdown in the search bar, same seven values plus `other`. |
| Course rail (All / Uncategorized / per course, with counts) | Course switcher dropdown on the section heading: All Documents / each course / No Course, each with its count. |
| Grid ⇄ List toggle | **Panel** ⇄ **List** toggle, right of the filter row. |
| Search over `file_name` + `summary` | Search over title, summary, concepts and course code, with `/` to focus, Esc to clear and match highlighting. |
| Detail modal: summary, key concepts (expand/collapse, markdown), concept scan, delete | Row `⋯` dialog: Open, Rename, Download Notes, Move (course), Add to Folder, Type, Scan to Knowledge Graph, Move to Trash. Summary and concepts show in the dialog body. |
| Mobile: course rail hidden | Course switcher is a dropdown, so it works at every width. |
| Load error + retry (`#769`) | Kept verbatim, same `data-testid`s. |
| Latest-request guard on overlapping loads (`#769`) | Kept (`useLatestRequest`). |
| Syllabus re-poll 1.5 s after upload | Kept in the upload completion handler. |

`data-testid`s kept, so the behaviours they pin keep being pinned:
`library-search`, `library-upload`, `library-course-scan`,
`library-doc-<id>`, `library-detail-scan`, `library-detail-delete`,
`library-load-error`, `library-load-retry`.

Retired with the control they named, because the v2 design has no preview
panel and no course rail: `library-course-filter-*` (the course switcher is
`library-course-switcher`, and its options are `role="option"`),
`library-detail-close`, `library-concepts-toggle-all`,
`library-concept-toggle-<i>`. The two tests that used them were ported onto
the new controls rather than deleted — see §8.

## 2. Backend routes that already exist

`backend/routes/documents.py`

| Route | Notes |
|---|---|
| `GET /user/{user_id}` | `services/documents/library.py::list_user_documents` — filters `deleted_at is.null`, decrypts `summary`/`concept_notes`, resolves offering → abstract `course_id`. |
| `DELETE /doc/{document_id}` | `soft_delete_document` — stamps `deleted_at`, withdraws chunks (#758). **Soft delete already exists**, so Trash needs only a read and a restore. |
| `PATCH /doc/{document_id}` | Only `category` today. |
| `POST /upload/sync`, `POST /upload` | Upload. PDF/DOCX/PPTX only, size-capped. |
| `POST /doc/{id}/scan-concepts`, `POST /course/{id}/scan-concepts` | Graph extension. |

`backend/routes/notes.py` is the **standalone** notes feature (free-standing
notes with their own concepts, chat and quiz). It is **not** per-document notes
and is left alone; the new page adds its own routes under `documents`.

## 3. What the redesign needs that did not exist

Added in this change, following the existing patterns
(`services/documents/*.py` + `routes/documents.py`, RLS bucket A migration):

| Purpose | Added |
|---|---|
| Rename a document | `PATCH /api/documents/doc/{id}` now also accepts `file_name`. |
| Move to a course | `PATCH /api/documents/doc/{id}` now also accepts `course_id` (resolved to the user's offering for that course). |
| Move to a folder | `PATCH /api/documents/doc/{id}` now also accepts `folder_id`. |
| Folders CRUD | `GET/POST /api/documents/folders`, `PATCH/DELETE /api/documents/folders/{id}`. |
| Trash list | `GET /api/documents/user/{user_id}/trash`. |
| Restore | `POST /api/documents/doc/{id}/restore`. |
| Delete forever | `DELETE /api/documents/doc/{id}?hard=1`. |
| Notes for a document (generate on first read) | `GET /api/documents/doc/{id}/notes`. |
| Save notes | `PUT /api/documents/doc/{id}/notes` `{ title, content, final }`. |
| Regenerate notes | `POST /api/documents/doc/{id}/notes/regenerate`. |
| Ask Clov about the notes | `POST /api/documents/doc/{id}/notes/ask` `{ message, quote, history }`. |
| "New Document" (an empty document to write in) | `POST /api/documents/blank`. |

Export (HTML / Markdown / PDF) is done client-side from the editor DOM, as in
the prototype — no endpoint needed, and it keeps working offline. PDF goes
through the print dialog's "Save as PDF", which is what the design's PDF item
means; there is no PDF writer in the browser.

### Where the old page's content went

The v2 design drops the preview panel, and its row dialog shows only controls.
The old panel's **summary** and **key concepts** therefore had nowhere to land
by default — and the handoff is explicit that nothing may be dropped (README
§2.3: keep it, in the closest matching spot). The summary is the row's own
subtitle, and both are in the row's `⋯` dialog, under the design's own mono-caps
headings; a concept's description is its chip's tooltip, since the dialog is
240px wide and the full text belongs on the Notes page the dialog's Open leads
to. `Library.carryover.test.tsx` walks every old capability and finds it.

### Two things the design assumes that the backend could not give it

- **Download original.** The prototype's row menu has a "Download" that only
  closes the menu. There is no stored original to hand back: the uploaded
  bytes live in `document_uploads.file_data` and are cleared at a terminal
  stage, by design. The item is therefore **Download Notes** and says so.
- **Undo after Delete Forever.** The prototype offers one; it is undoing its
  own mock array. A purge removes the row, so that toast has no Undo — the
  Trash's two-step confirm stands in for it.

## 4. Storage added

`db/migrations/20261119120000_library_folders_and_document_notes.sql` adds:

- `document_folders` (id, user_id, course_id, name, timestamps) — `name` is a
  plaintext label, like `flashcard_sets.name`.
- `documents.folder_id` — `ON DELETE SET NULL`, so deleting a folder keeps
  every document in it, unfiled.
- `documents.page_count` — the Library's Pages column and its "Most Pages"
  sort. Counted from the uploaded bytes at upload time
  (`services/documents/page_count.py`: PDF page objects, PPTX slide parts) and
  `NULL` when it cannot be known — a DOCX has no pages until something lays it
  out, and a document uploaded before this column has none. Those render as an
  em dash and sort last.
- `document_notes` (document_id, user_id, title🔒, content🔒, final,
  timestamps) — one row per document, cascading from it.

Both new tables are RLS bucket A (own-row policies, the `flashcard_sets`
shape). `document_notes.title`/`content` are AES-GCM encrypted like other
study content; the folder label is not, like other labels.

Registered where a new per-user table has to be:
`services/account_wipe.py` (both are wiped — `document_notes` by cascade) and
`services/account_bundle.py` (both are copied; `document_notes.title`/`content`
are in `ENCRYPTED`, `document_folders.course_id` is remapped).


## 5. Where the backend code lives

The repo's rule is that a route is the HTTP surface only (#118: no route file
over 600 lines, each handler body under its own name in its service package).
These additions follow it:

| Module | What it owns |
|---|---|
| `services/documents/library_api.py` | The Library's own handler bodies: the Trash guard, resolving a move's course and folder, what a PATCH validates (before auth) and what it resolves (after). |
| `services/documents/folders.py` | Folders: the reads and writes, plus the four handler bodies behind `/folders`. |
| `services/documents/blank.py` | "New Document" — the one row that is born with a terminal index status, because there is nothing to index. |
| `services/documents/doc_notes.py` | The notes row: the encryption boundary, the source text a generation reads, and the honest fallback. |
| `services/documents/notes_api.py` | The notes handler bodies: the two agent runs, their prompts, and the generate-once rule. |
| `services/documents/page_count.py` | Counting pages off the uploaded bytes. |
| `agents/document_notes.py` | The two agents, on the existing `note_summary` / `note_chat` model slots. |

Moved while here, for the same ceiling: `scan_document_concepts`'s body is now
`services/documents/scan.py::scan_for_document`. `tests/split_patches.py`'s
`DOCUMENTS_MODULES` gains the new modules so `patch_documents` still reaches
every name.

## 6. What was verified

- `backend/tests/test_library_redesign_routes.py` — 29 tests over the new
  routes, including the two guards that matter: a hard delete is Trash-only,
  and a move resolves its offering through `require_course_enrollment` so it
  cannot file a document into a course the student is not taking.
- `frontend/src/components/library/designParity.test.tsx` — 44 tests that read
  the design handoff's own markup (kept as a fixture) and assert the rebuilt
  pages carry the same literals: the colour palette, the radii, the copy, the
  icon path data, the fonts and every keyframe. A later edit that drifts from
  the design fails rather than passing quietly.
- `frontend/src/components/library/libraryModel.test.ts` (20),
  `src/lib/notes/mathSlots.test.ts` (24), `src/lib/notes/graphs.test.ts` (27) —
  the pure logic behind the filter/sort pipeline, in-place equation editing,
  and the plot/chart renderer.
- `Library.guides.test.tsx` and `Library.races.test.tsx` — the pre-redesign
  Library's own behaviours (#769: a failed load is not an empty library; a scan
  started on one document never marks another done; saved study guides follow
  the scope and the search), ported onto the v2 controls.
- `frontend/src/components/library/Library.carryover.test.tsx` — 16 tests that
  walk the old page's capabilities one by one and find each of them in the new
  layout: the summary, the key concepts, both concept scans, the category
  change, delete, search over summaries and concepts, `/` and Escape, and the
  List ⇄ Panel toggle. Plus the redesign's own Trash, rename-in-place and bulk
  bar, end to end.
- `frontend/src/components/notes/Notes.test.tsx` — loading, debounced autosave,
  "Not saved" on failure, Finalize, Regenerate's confirmation, Ask Clov, and
  the flush that stops a pending save being lost on the way back to the Library.
- `frontend/src/components/library/designCoverage.test.tsx` — the complement of
  the parity tests: rather than checking values the rebuild must carry, it
  asserts that **no** declaration in either prototype was dropped. Every
  `style="…"` declaration in the handoff must appear in the rendered DOM or in
  the rebuild's source — the latter because a menu, modal, Trash view or
  skeleton is not mounted in a single render. It knows that a transition list
  means the same thing in any order, and that `SQUEEZE` expands to the design's
  380ms easing. 318 Library and 275 Notes declarations, all accounted for.

### The two deliberate deviations

`designCoverage.test.tsx::EXPECTED_DEVIATIONS` is the only allowlist, and it
holds exactly two classes:

1. **Font families.** The design writes `font-family: 'Aleo', serif` and
   `'SUSE', system-ui, sans-serif`. `next/font/local` registers a GENERATED
   family name, so a bare `'Aleo'` silently renders Times. The rebuild uses
   `var(--font-serif | --font-sans | --font-mono)`, which resolve to the same
   faces. Porting these verbatim would look right in the prototype and wrong in
   the app.
2. **The artboard.** The prototype letterboxes itself into a fixed canvas
   (`position: absolute; transform: {{ fitT }}; transform-origin: 0 0;
   width: 1920px; height: 1080px`) so it can be previewed at any window size.
   The real page is responsive inside the repo's own shell, so that wrapper has
   no counterpart.

Everything else in both prototypes is carried verbatim.
