# Library summary editor — design

Status: approved for planning
Date: 2026-10-11
Scope: Library document summaries only (the separate Notes feature and its summaries are explicitly out of scope).

## 1. Problem

Today, `documents.summary` is a single static TEXT field generated once by `summary_agent` at upload time (`backend/routes/documents.py`) and shown read-only in the Library drawer (`frontend/src/components/screens/Library.tsx:538-545`). There is no way to edit it, no way to base it on more than one source document, and no history. This redesign replaces it with a fully editable, student-friendly document per upload, with AI-assisted editing via highlight + comment, undo/redo, multi-source support, and version history.

## 2. Product flow

**Upload → editable doc.** When a document finishes uploading, the existing pipeline (which already runs `summary_agent`) creates a **summary doc**: a rich-text document seeded with the AI's initial summary, with exactly one source (the uploaded document) — the document that "owns" it in the Library grid.

**The editor** is a dedicated full-page route (e.g. `/library/summaries/{id}`), not a drawer/overlay — it needs simultaneous room for the doc, a source list, and a history panel. Three zones:
- **Main column** — the rich-text doc. Type freely, select text.
- **Right rail** — two tabs, **Sources** (documents contributing to this summary; add/remove) and **History** ("Earlier versions" — restore points, newest first, previewable, restorable).
- **Ask-AI flow** — select text (or select nothing, for a whole-doc ask) → a floating "Ask" affordance appears → student types a plain instruction ("make this shorter," "pull in my lecture notes too") → the agent proposes a change shown inline (old text struck through, new text in the accent color) with **Keep it** / **Undo this** buttons at the point of change. Multiple asks can be pending across different parts of the doc at once (not one-at-a-time).

**Sources.** Adding a source only makes it available as context for future asks — it never changes existing text until the student explicitly asks the agent to use it. Removing a source is symmetric: it stops being available context; nothing already written is retroactively rewritten.

**Undo/redo** is the ordinary editor kind (ctrl+Z/Y) — session-local, covers typing and kept AI edits, cleared on reload. Free from TipTap's `prosemirror-history`. This is deliberately separate from version history (see below) — different granularity, different purpose.

**History ("Earlier versions")** is a timeline of restore points taken automatically at meaningful moments: an AI suggestion is kept, a source is added or removed, or periodically while typing (autosave). Opening an entry shows a read-only preview with a "Bring this back" action. Restoring creates a *new* restore point first, so restoring is itself undoable — never destructive.

**Deleting the source document** deletes its summary doc too. If other sources had been folded in, the student sees a plain-language warning first ("This summary also used notes from X and Y — deleting it won't affect those documents, but you'll lose this write-up").

**No standalone multi-source creation flow in v1.** A summary doc is always seeded from a single upload; multi-source is achieved by adding sources to an existing doc afterward, not by picking several documents upfront. (YAGNI — add this later only if requested.)

## 3. Customization (v1 scope)

Deliberately minimal, to avoid overwhelming new users with configuration:
- **Output style** — one **global** user preference (e.g. concise/bullets vs. full prose, formal vs. casual) applied to the initial summary and every AI suggestion by default. Lives as a new column on the existing `user_settings` table. No per-document override in v1.
- **Suggestion scope** — whether an AI edit may only touch the highlighted text, or may also adjust immediately surrounding text for flow. Exposed as a lightweight toggle in the Ask-AI flow itself (default: confined to the highlight — the safer default), not a settings-page control.

Explicitly deferred: per-source weighting/trust, per-document style overrides, real-time multi-user collaboration (confirmed single-user only — no OT/CRDT needed).

## 4. Visual design

Matches Sapling's existing visual language rather than introducing a new one:

```
┌─────────────────────────────────────────────────────────────────┐
│  ← Back to Library        Biology Lecture 4 — Summary    [Saved]│
├───────────────────────────────────────┬───────────────────────────┤
│                                       │  Sources          History  │
│  Mitosis splits one cell into two    │ ───────────────────────── │
│  identical daughter cells in four    │  📄 Biology Lecture 4.pdf   │
│  phases...                            │  📄 Ch. 7 reading notes     │
│                                        │  [+ Add a source]          │
│  ┌──────────────────────────────┐    │                            │
│  │ ~~old sentence~~               │    │                            │
│  │ new sentence (accent color)    │    │                            │
│  │   [Keep it]   [Undo this]      │    │                            │
│  └──────────────────────────────┘    │                            │
│                                        │                            │
│  The process ensures genetic...       │                            │
├───────────────────────────────────────┴───────────────────────────┤
│  [Ask about selected text ▸]                                      │
└─────────────────────────────────────────────────────────────────┘
```

- Main column text uses `body-serif` (matches the reading feel used elsewhere, reinforcing this is the student's own writing, not an app console).
- Header/title uses `h-serif`, status chip uses `label-micro`.
- Right rail reuses the `Sheet` component's visual language (radius, shadow, `--ink` borders) but docked inline rather than overlaying, since it must coexist with the doc rather than cover it.
- Pending AI edits render as a soft-bordered inline card at the point of change (`--r-xs` radius, `--accent` = `--brand-forest-bright` for the proposed text) rather than a floating popover, so multiple pending edits stay scannable top-to-bottom while reading.
- The Ask bar only appears on selection, or as a single static "Ask about this doc" button when nothing is selected — no persistent toolbar of AI controls by default. This is the main lever keeping the feature from feeling overwhelming.
- A brand-new summary doc (before the agent's first pass finishes) reuses `EmptyState` (title/body/action pattern, `h-serif` + `body-serif` + `label-micro`) rather than a blank page.
- **Tone**: plain, encouraging copy throughout — no exposed jargon ("diff," "suggestion," "version," "commit"). Suggestions says "Keep it" / "Undo this," history says "Earlier versions" / "Bring this back."

## 5. Data model

New tables (migration via `python -m db.migrate`, timestamp-prefixed per repo convention):

- **`summary_docs`** — `id`, `owner_user_id`, `primary_document_id` (the "home" document; the FK cascade-deletes this row when the primary document is deleted), `content` (encrypted TEXT — serialized TipTap/ProseMirror JSON, same encrypted-JSON pattern as `study_guides.content`), `created_at`, `updated_at`.
- **`summary_doc_sources`** — join table: `summary_doc_id`, `document_id`, `added_at`. Unique on the pair. The primary document always has a row here too (not removable from the UI, since removing it would orphan the doc).
- **`summary_doc_versions`** — append-only restore points (same pattern as `node_mastery_events`): `id`, `summary_doc_id`, `content` snapshot (encrypted), `trigger` (`initial` / `ai_edit_kept` / `source_added` / `source_removed` / `autosave` / `restored`), `created_at`. Never updated or deleted.
- **`summary_doc_suggestions`** — pending/resolved AI asks: `id`, `summary_doc_id`, `anchor_from`/`anchor_to` (nullable — null means a whole-doc ask), `instruction` (encrypted), `original_text`/`proposed_text` (encrypted), `status` (`pending` / `kept` / `undone`), `created_at`, `resolved_at`.

All four follow the existing `encrypt_if_present`/`decrypt_if_present` convention — same sensitivity tier as `notes.body` and `study_guides.content`.

One new column on the existing `user_settings` table for the global output-style preference (no new table needed).

## 6. Backend

- **Agent**: new `backend/agents/summary_edit.py`, Pydantic AI, following the `note_chat`/`note_summary` pattern — takes the instruction, the selection text (or none, for whole-doc), the full current doc, and the text of all active sources; returns a proposed replacement. New model slot in `agents/_providers.py` (`model_for("summary_edit")`). The existing `summary_agent` (`backend/agents/summary.py`) still runs once at upload to seed the initial doc — unchanged.
- **Routes**: new `backend/routes/summary_docs.py`, mounted at `/api/summary-docs`, guarded by `require_self`:
  - `GET /{id}` — doc + sources + pending suggestions
  - `PATCH /{id}` — manual edits (autosave)
  - `POST /{id}/sources`, `DELETE /{id}/sources/{document_id}` — add/remove source
  - `POST /{id}/ask` — run the agent on a selection or the whole doc; returns a pending suggestion
  - `POST /{id}/suggestions/{sid}/keep` / `POST /{id}/suggestions/{sid}/undo` — resolve a suggestion; `keep` also writes a `summary_doc_versions` row
  - `GET /{id}/versions`, `POST /{id}/versions/{vid}/restore` — history panel (restore writes a new version first, never destructive)
- No standalone "create a summary doc" endpoint in v1 — creation only happens as a side effect of document upload (see §2).

## 7. Integration & cutover (nothing left half-migrated)

Every existing read/write of `documents.summary`, found by grep, with its replacement:

**Backend (`backend/routes/documents.py`):**
- L486/506 (upload pipeline writes `summary` into `documents`) → replaced with creating a `summary_docs` row + initial `summary_doc_versions` entry.
- L547 (sync upload response echoes `summary`) → replaced with the new summary doc's id/preview.
- L250, L379 (`GET /user/{user_id}` and doc-detail decrypt `documents.summary`) → replaced with a plaintext preview derived from the linked `summary_docs.content`.
- L1261 (`scan-concepts` reads `doc_summary` as agent context) → replaced with plaintext from `summary_docs.content`.

**Frontend (`Library.tsx`):**
- L120 (search filter on `d.summary`) → uses the new preview field from the API.
- L285-290, L334 (grid card / list row previews) → use the new preview field.
- L540-545 (drawer's static summary panel) → replaced by the "Open summary" button (§2).

**Rollout, two stages:**
1. **Stage 1 (this work).** Ship the new tables, agent, routes, and the full cutover above — no code reads or writes `documents.summary` after this lands. A one-time backfill script (pattern: `scripts/backfill_document_chunks.py`) creates a `summary_docs` row from every existing document's `documents.summary`, so no student's existing summary disappears. The column still physically exists in the DB but nothing touches it.
2. **Stage 2 (follow-up, gated on green pytest + Playwright + e2e oracles against Stage 1).** A new migration drops the `documents.summary` column entirely; the now-dead `encrypt_if_present`/`decrypt_if_present` calls on it are deleted; the `CLAUDE.md` gotchas-list mention of it is removed.

This keeps the cutover atomic — there is never a window where two sources of truth are both live — and makes the column drop pure cleanup with no behavior riding on it.

## 8. Error handling

- AI "ask" failures never touch the doc (suggest-mode only) — a failure just means no suggestion appears; a quiet inline retry is offered, the student's typed instruction isn't lost.
- If the text a pending suggestion anchors to is edited/deleted before being resolved, the suggestion invalidates gracefully ("This part changed — ask again?") rather than applying against stale positions.
- Autosave failure: typing is never lost — kept in local state and retried; the header status chip flips from "Saved" to a quiet "Having trouble saving — retrying" rather than a disruptive error banner.
- Two tabs open on the same doc (still single-user, no realtime collab): optimistic `updated_at` check on save; a conflict shows "This was changed in another tab — refresh to see the latest" rather than silently overwriting.

## 9. Testing

- **Backend `pytest`**: encryption roundtrip for the four new tables (mirrors `test_encryption_roundtrip.py`); cascade-delete behavior with and without extra sources; the backfill script's idempotency; the `summary_edit` agent's handling of selection vs. whole-doc asks.
- **E2E oracles**: the new encrypted columns (`summary_docs.content`, `summary_doc_versions.content`, suggestion text fields) are added to the existing `ciphertext` oracle's checked-column list.
- **Playwright (`frontend/e2e/`)**: one promoted journey covering upload → open summary → highlight + ask → keep the suggestion → add a second source → confirm doc text is unchanged until asked → restore an earlier version → delete the source document → confirm cascade delete; the multi-source deletion warning is covered as a separate assertion within the same or a follow-up journey.

## 10. Explicitly out of scope (v1)

- The Notes feature's summaries (`notes.last_summary`, `note_summary.py`) — untouched.
- Real-time multi-user collaboration (OT/CRDT, live cursors, presence).
- Per-document style overrides and per-source weighting/trust.
- A standalone "create a multi-source summary from scratch" flow not tied to an upload.
- Manual, user-named "save a version" action (automatic restore points at meaningful events cover this).

## 11. Key decisions (for future reference)

| Decision | Choice |
|---|---|
| AI edit interaction | Suggestion/diff shown inline, accept ("Keep it") / reject ("Undo this") — never direct silent replace |
| Multiple pending suggestions | Allowed — not one-at-a-time |
| Comment scope | Both highlighted-selection and whole-doc (nothing selected) asks |
| Adding a source | Never auto-incorporates; purely makes context available until explicitly asked |
| Undo/redo vs. history | Separate — undo/redo is session-local editor mechanics; history is persisted restore points |
| Collaboration | Single-user only, no real-time multi-user editing |
| Style setting scope | Global default (user_settings), not per-document |
| Editor surface | Dedicated full-page route, not a drawer/overlay |
| Delete-together behavior | Deleting the source document deletes its summary doc, with a warning if other sources were added |
| Editor framework | TipTap/ProseMirror (built-in undo/redo, mark-based anchoring for suggestions, mature suggest-mode prior art) |
| `documents.summary` column | Fully cut over in Stage 1 (no dual-write/fallback), dropped in Stage 2 once tests are green |
