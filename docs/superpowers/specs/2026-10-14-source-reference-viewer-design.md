# Source reference viewer — design

Status: approved for planning
Date: 2026-10-14
Scope: a follow-up to the library summary editor (`docs/superpowers/specs/2026-10-11-library-summary-editor-design.md`, PR #717). Builds on that work; does not modify its Stage 1/Stage 2 cutover.

## 1. Problem

The summary editor's "Ask" flow lets a student highlight text *inside the summary* and ask the AI to rewrite it. The agent is already given the full extracted text of every attached source document when generating a suggestion (`summary_docs_service.py::_source_texts`) — so it is technically capable of pulling in material the summary doesn't yet cover. But there is no way for a student to actually *see* a source document or point at a specific part of it. `SourcesPanel` only lists file names.

This matters most for content OCR text loses or garbles — diagrams, equations, figures, handwritten annotations — which is exactly the material a student most wants to point at and say "include this." Highlighting plain extracted text doesn't solve that; the student needs to see and mark up the original rendering.

## 2. Product flow

**Opening a source.** Clicking a source in the right rail's **Sources** tab opens it as a new tab alongside **Sources** and **History**, in a split pane: the source on the left, the summary editor on the right (unchanged). Clicking that tab again (or switching to Sources/History) closes the split and returns to the plain summary view.

**PDF sources** render page-by-page (`pdfjs-dist`). A freeform "circle" (lasso) tool lets the student draw an irregular outline over any part of a page; releasing the drag crops that region — masked to the drawn outline, not just its bounding box — out of the rendered page as an image, and attaches it as a pending **reference** chip near the Ask input, replacing/joining whatever summary-text selection may also be active.

**DOCX/PPTX sources** have no rasterization pipeline (see §8, deferred) and show their already-stored `extracted_text` instead, as read-only selectable text. Selecting a range attaches that text as the reference, same chip UI, same downstream flow — just a text snippet instead of an image.

**Asking with a reference attached** always goes through the *existing* whole-document suggestion path (`anchor_from`/`anchor_to` = `null`), the same mechanism already used today for a no-selection ask. The agent receives the full current summary, the reference (image or text), the typed instruction, and the other sources' text, and returns a complete revised summary with the new material woven in whereever it best fits — placement is the agent's call, not the student's. No new anchor/insertion-point concept is introduced; the existing whole-doc suggestion card ("Keep it" / "Undo this") reviews and resolves it exactly as it does today.

**Existing documents with no stored original** (anything uploaded before this ships — the raw bytes were already discarded after OCR and can't be recovered) keep today's `SourcesPanel` behavior: name-only, no viewer, no circle tool. This is a hard limit, not a phased rollout — there is nothing to backfill.

## 3. Data model

One new column, no new tables:

- **`documents.original_storage_path`** (TEXT, nullable) — the Supabase Storage object key for the original uploaded file, set at upload time once the write succeeds; `null` for every document uploaded before this ships (see §2) and treated identically to "no original available."

New Storage bucket: **`document-originals`** — private (no public read), one object per document, keyed by `original_storage_path`.

No changes to `summary_docs`, `summary_doc_sources`, `summary_doc_versions`, or `summary_doc_suggestions` — the whole-doc suggestion row produced by this flow is indistinguishable, in storage, from one produced by today's no-selection ask.

## 4. Backend

- **Upload pipeline** (`backend/routes/documents.py`): alongside the existing extraction step, best-effort upload the raw file bytes to `document-originals/{document_id}/{filename}` and persist the resulting path on the `documents` row. Follows the same "best-effort, never fails an otherwise-successful upload" convention already used for summary-doc creation (`create_summary_doc`'s try/except) — a storage failure logs a warning and leaves `original_storage_path` null rather than 500ing the upload.
- **New route**: `GET /api/documents/{id}/original-url` (guarded by `require_self`) — returns a short-lived signed URL for the stored original, or 404 if `original_storage_path` is null. The frontend fetches this right before rendering the viewer, not on every Sources-panel render.
- **`backend/services/summary_docs_service.py::create_suggestion`**: extend the whole-doc path to accept an optional image (base64/bytes) alongside the instruction. When present, it's passed to the agent as a multimodal content part rather than folded into the text prompt.
- **`backend/agents/summary_edit.py`**: `summary_edit_agent`'s user-prompt construction accepts an optional image part (Gemini models are natively multimodal; no new model slot needed, `model_for("summary_edit")` is unchanged). System prompt gains one line clarifying that an attached image is reference material from a source document, not an instruction.
- **Document delete cascade** (`delete_document`): extend the existing best-effort cleanup (which already removes the summary doc) to also delete the Storage object at `original_storage_path`, same best-effort convention — a failed Storage delete is logged, not raised.

## 5. Frontend

- **`SourcesPanel`**: clicking a source (instead of being inert) opens it as a new tab; the tab bar grows from {Sources, History} to {Sources, History, `<filename>`} while open, closable by re-clicking.
- **New component** `SourceViewer` (PDF path): renders pages via `pdfjs-dist`, overlays a freeform lasso tool (tracks pointer-move points into a polygon path while dragging). On release: compute the polygon's bounding box, then mask it to the drawn outline via the standard canvas clip-path technique (`ctx.save()` → trace the polygon with `beginPath`/`lineTo` → `ctx.clip()` → draw the bounding-box region → `ctx.restore()`) before exporting with `toBlob`, filling the area outside the outline (but inside the bounding box) white rather than leaving it transparent, for simplest/most robust image encoding. Surfaces the crop to the parent via a callback — no separate state management beyond "there is a pending reference."
- **New component** `SourceTextViewer` (DOCX/PPTX path): plain scrollable text with native text selection; selection becomes the reference via the browser Selection API, same callback shape as `SourceViewer` (string instead of image blob) so `SummaryEditor` doesn't need to know which kind it got.
- **`SummaryEditor`**: gains a "reference" chip (next to the existing `askTarget` summary-highlight chip) showing what's attached and a way to clear it; `submitAsk` includes the reference (image blob as multipart/base64, or text) and forces `anchor_from`/`anchor_to` to `null` whenever a reference is attached, even if summary text also happens to be selected — the reference path is always whole-doc.

## 6. Security

- Storage objects are private; every read goes through a freshly-minted signed URL scoped to the requesting user via `require_self`, never a long-lived or public link.
- The cropped image is sent directly from the browser to `POST /{id}/ask` for that single request and is not persisted anywhere — the resulting `summary_doc_suggestions` row stores only `proposed_text`, exactly as it does today. No new encrypted column is needed for the reference itself.

## 7. Error handling

- Original-file upload failure: best-effort, never fails the upload (§4) — the document just has no viewer available, same as a pre-existing document.
- Signed-URL fetch failure when opening a source tab: the tab shows an inline error ("Couldn't open the original — try again") rather than a broken viewer; `SourcesPanel`'s existing error-toast pattern is reused.
- Ask-with-reference failure: identical to today's ask failure (§8 of the summary-editor design) — no doc mutation, instruction text preserved, quiet inline retry.

## 8. Explicitly out of scope (v1)

- DOCX/PPTX visual rendering (rasterization/conversion to page images) — text-select is the v1 fallback for these formats; a future task could add conversion (e.g. LibreOffice headless → PDF) if this gap is actually felt.
- Backfilling original files for documents uploaded before this ships — the bytes are gone; not recoverable.
- Multi-page selection in one crop — a circled region is scoped to a single rendered page.
- Freeform lasso editing/undo mid-draw (e.g. backing up a point) — releasing the pointer always commits the drawn path as-is; starting over means drawing again.
- Persisting the circled crop beyond the single ask request.

## 9. Key decisions (for future reference)

| Decision | Choice |
|---|---|
| What the AI sees from a circled PDF region | An image crop of the rendered page (multimodal), not just underlying text — the point is catching diagrams/equations OCR loses |
| Circle tool shape | Freeform lasso, masked to the drawn outline via canvas clip-path — not a plain bounding-box rectangle |
| DOCX/PPTX fallback | Text-select on extracted text, not image rendering (no rasterization pipeline exists; not building one now) |
| Insertion point for new content | Agent decides, via the existing whole-doc suggestion path — no new anchor/cursor-position mechanism |
| Viewer placement | Split pane (source left, summary right), opened as a closable tab next to Sources/History |
| Original-file retention | Net-new (raw bytes were previously discarded after OCR); private Storage bucket, best-effort write, best-effort cascade delete |
| Pre-existing documents | No viewer available — not backfillable, not phased, just a hard capability gap for old uploads |
