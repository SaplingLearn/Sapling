# Feature · Library (Documents)

> Covers: `/library/page.tsx` + `DocumentUploadModal.tsx`. `UploadZone.tsx` exists but has no importers — candidate dead code.

---

## 1. Overview

Library is a document repository keyed by course + category. Users upload PDFs, DOCX, or PPTX. The backend classifies them, extracts summaries + key takeaways + flashcards, and the library surfaces them for study.

Layout:
- Top bar: course pills (+ an Upload button on the right).
- Left: category pills (`syllabus` / `lecture_notes` / `slides` / `reading` / `assignment` / `study_guide` / `other`) — filters the grid.
- Main: grid of document cards (with category chips + file name + created date).
- Right: detail panel when a card is clicked. Shows summary, key takeaways, flashcards (with "Reveal" interaction), and a delete button.

Categories, colors, and labels are centralized at the top of `library/page.tsx:22-45`.

---

## 2. User flows

### 2.1 Flow: load library

- Mount: `Promise.all([getCourses, getDocuments])` (confirm from `page.tsx`).
- `activeCourse = 'all'`, `activeCategory = 'all'` by default.
- Filters combine: a doc matches the view if its `course_id` matches `activeCourse` (or 'all') AND its `category` matches `activeCategory` (or 'all').

### 2.2 Flow: open a doc detail panel

- `openPanel(doc)` sets `panelDoc`, clears `revealedCards`, clears `confirmDelete`.
- Detail panel shows:
  - Summary (paragraph).
  - Key takeaways (bulleted list, if present).
  - Flashcards (Q/A pairs) — each card has a "Reveal" button that toggles the answer. `revealedCards: Set<number>` tracks open ones.
  - Delete button (two-step: first press → "Confirm Delete?" toggle; second press calls `deleteDocument(doc.id, userId)` → filter out of local state + close panel).

### 2.3 Flow: upload (`DocumentUploadModal`)

Two steps: **pick** → **reviewing**.

#### Step: pick (`DocumentUploadModal.tsx:318-453`)

- Drag-and-drop zone or click-to-browse. Accepts `.pdf, .docx, .pptx`. Max 5 files, 15 MB each (`MAX_FILES=5`, `MAX_BYTES=15*1024*1024`).
- `validateAndSetMultiple(files)` enforces type + size constraints; errors joined (up to first 2 shown + "(+N more)").
- Course picker (`CustomSelect`) + inline **+ Add course** affordance:
  - Expands an inline form with a name input + Add button.
  - `handleAddCourse`: picks next unused `PRESET_COURSE_COLORS`, calls `addCourse(userId, name, color)`. On `already_existed:true` shows error; otherwise refreshes `courses` and auto-selects the newly added one.
- Upload button disabled until files + course are picked.

#### Step: reviewing

- `handleUpload` builds a `UploadItem` per file with `status='uploading'` and fires concurrent `uploadDocumentWithTimeout(fd)` calls. 4-minute `AbortController` timeout per file. AbortError → friendly message.
- UI reviews uploads one at a time (`reviewIndex`). Each has:
  - Status: `uploading` (spinner), `done` (show summary + category dropdown + takeaways + flashcards), `error` (error text + Retry).
  - **Category override**: `CustomSelect` lets the user change the AI-picked category before confirming.
  - **Re-analyze**: re-uploads the same file; if the new upload produces a different `doc.id`, the old one is `deleteDocument`'d first to avoid duplicates.
  - **Skip** / **Confirm**: Skip advances; Confirm commits the category change (via `updateDocument`), appends to `confirmedDocs`, advances, and closes on last.
- Modal closes via `closeModal(uploaded[])` — resets state and fires the parent `onClose(uploaded)` callback.
- During `hasActiveUploads` the X and backdrop-click close are disabled (`DocumentUploadModal.tsx:310-316`) so you can't abort mid-upload.

### 2.4 Flow: upload side-effects

- `/calendar` reuses `DocumentUploadModal` to ingest syllabi. After close, if any `uploaded` doc has `category === 'syllabus'`, `/calendar` refetches assignments (`calendar/page.tsx:357-364`) and re-runs after 1.5s to catch insert races.

---

## 3. State

### `LibraryPage`

- `courses`, `docs`, `loading`.
- `activeCourse`, `activeCategory` (filters).
- `panelDoc`, `revealedCards`, `confirmDelete`, `deleting`.
- `showUpload`.

### `DocumentUploadModal`

- `uploadStep`: `'pick' | 'reviewing'`.
- `pickedFiles`, `fileError`, `dragging`.
- `selectedCourseId`.
- `uploadItems: UploadItem[]` (per-file), `reviewIndex`, `confirmedDocs`.
- `showAddCourse`, `newCourseName`, `courseAdding`, `courseAddError`.

---

## 4. API calls

Library:
- `getCourses(userId)` → `GET /api/graph/:userId/courses`
- `getDocuments(userId)` → `GET /api/documents/user/:userId`
- `deleteDocument(documentId, userId)` → `DELETE /api/documents/doc/:id?user_id=`

Upload modal:
- `uploadDocument(formData)` → `POST /api/documents/upload` (raw fetch, multipart, with `AbortController` 4-min timeout)
- `updateDocument(id, {category, user_id})` → `PATCH /api/documents/doc/:id`
- `addCourse(userId, courseName, color)` → `POST /api/graph/:userId/courses`
- `getCourses(userId)` → refetch after add

---

## 5. Components involved

- `DocumentUploadModal` — the upload + review flow. Portal'd by being a fixed-position overlay (not actually using React portal).
- `CustomSelect` — course picker, category picker per-review, inline add-course.
- `getCourseColor` from `lib/graphUtils.ts` — course pill coloring.
- `UploadZone` — **exists but is unused** (no importers). Candidate dead code.

---

## 6. Edge cases

1. **4-minute upload timeout** (`UPLOAD_TIMEOUT_MS`). Files that take longer are aborted with a specific user-friendly message.
2. **Backdrop click and X both disabled while uploads are in-flight** — prevents accidental data loss.
3. **Re-analyze orphans the previous document server-side** via a separate `deleteDocument` call. If that delete fails, the old doc leaks. Fine for rebuild to improve.
4. **`UploadedDoc.flashcards`** can be null (older backend) — the detail panel must handle both.
5. **Upload + syllabus race in `/calendar`** mitigated by a 1.5s delayed refetch.
6. **Category dropdown override path**: if `resultCategory === result.category` no `updateDocument` call is made (avoids a no-op PATCH). Good.
7. **`pickedFiles` state** is an array of raw `File` objects — held in memory. Closing the modal clears them; the browser will release.

---

## 7. Interactive patterns

| Pattern | Impl |
|---|---|
| Drag-and-drop upload zone | `onDrop` / `onDragOver` (`preventDefault`) / `onDragLeave`; multi-file supported |
| Per-file concurrent uploads with shared progress view | individual promises, shared `uploadItems[]` state |
| AbortController-based timeout | `setTimeout(() => controller.abort(), 4min)` wrapped in `try/finally` |
| Reveal-on-click flashcard answers | `Set<number>` of revealed indices |
| Two-step delete confirm | `confirmDelete: boolean` |
| Inline add-course within upload modal | expandable form; auto-picks next preset color |

---

## 8. Things to preserve in the rebuild

- Multi-file upload (up to 5), 15 MB each, PDF/DOCX/PPTX only.
- 4-minute per-file timeout with a friendly abort message.
- Per-file review UI with AI-picked category override + Re-analyze option.
- Disallow closing the modal during active uploads.
- Inline "+ Add course" without leaving the upload flow.
- Syllabus-upload → Calendar refresh side-effect (`/calendar` refetches after close).
- Category pill colors from `CATEGORY_COLORS` (preserve at least the vocabulary; styling can change).
- Delete is two-step (guard against accidental delete of a doc containing weeks of notes).
- Reveal-flashcards-by-click pattern in the detail panel.

## 9. Things to rework

- Remove `UploadZone.tsx` (unused).
- Consider a dedicated "re-process" affordance *outside* the upload flow (i.e., re-OCR an existing doc).
- Surface upload errors via Toast in addition to inline per-item rows — the user may not look at the right item.
- Add an "upload history" filter (e.g., "uploaded this week").
