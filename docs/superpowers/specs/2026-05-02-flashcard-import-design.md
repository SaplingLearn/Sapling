# Flashcard Import — Design

**Status:** Approved (brainstorming) → ready for implementation plan
**Date:** 2026-05-02
**Owner:** Sapling

## Goal

Let a Sapling user bring existing study material into their flashcard
collection without friction. Match the polish of Quizlet/Anki/Knowt for the
common case (paste a Quizlet export, get cards in their account in seconds)
and add Sapling-native AI passes (generate from library docs, cleanup,
dedup, cloze, reverse) on top.

## Non-goals

- Replacing the existing `FlashcardsMode` review UI in `Study.tsx`. Import
  is a new modal launched *from* that screen; review stays as-is.
- Spaced-repetition scheduling changes. Existing `times_reviewed` /
  `last_rating` flow is untouched.
- A full deck/set abstraction. The existing `topic` column already groups
  cards; we are not introducing `flashcard_sets`.
- Cloudflare Workers, R2, Anthropic SDK. Sapling runs FastAPI + Supabase +
  Gemini and this feature stays on that stack.

## Scope

Five import methods, all routed through one modal:

1. **Paste text** — Quizlet-style live preview with smart delimiter
   detection (tab + newline default). Configurable term/card separators
   including a custom field.
2. **File upload** — `.csv`, `.tsv`, `.txt`, `.json` parsed client-side
   via Papaparse; `.xlsx` and Anki `.apkg` parsed server-side in Python.
3. **URL import** — paste a Quizlet set URL, server fetches and best-effort
   parses. Graceful fallback if blocked.
4. **Image OCR** — drop a photo of notes, route through Sapling's existing
   `extraction_service`, then a Gemini "split into Q/A pairs" prompt.
5. **AI generation** — paste lecture notes *or* pick from existing library
   documents. User chooses count (10/25/50/auto) and difficulty
   (recall/application/conceptual).

AI passes available before commit:

- **Generate reverse cards** — checkbox on the parsed-cards table.
- **Clean up with AI** — one-click button, Gemini fixes typos, normalizes
  formatting, shortens overly long definitions.
- **Cloze deletion** — sub-mode on the Paste tab: paste a paragraph,
  Gemini returns fill-in-the-blank cards.
- **Detect duplicates** — automatic during commit, fuzzy match against
  existing cards in the same course; reported in the success toast.

## Data model

One additive migration. **No new tables.**

```sql
ALTER TABLE flashcards
  ADD COLUMN IF NOT EXISTS course_id TEXT REFERENCES courses(id);

CREATE INDEX IF NOT EXISTS idx_flashcards_user_course
  ON flashcards(user_id, course_id);
```

- Existing rows keep `course_id` NULL. `FlashcardsMode`'s current
  `topic`-based filter still works.
- New imports populate `course_id` from the modal's course picker.
- We deliberately skip `source`, `import_batch_id`, and `image_url` per
  brainstorming decision — keeps the table minimal.

Migration file: `backend/db/migration_flashcard_course_id.sql`.

## Backend

### New routes (added to `backend/routes/flashcards.py`)

| Method | Path | Body | Returns |
|--------|------|------|---------|
| `POST` | `/flashcards/import/parse` | `{user_id, source, payload, options}` | `{cards: [{front, back, row}], errors: [{row, message}]}` |
| `POST` | `/flashcards/import/commit` | `{user_id, course_id, topic, cards, dedup}` | `{inserted, skipped_duplicates}` |
| `POST` | `/flashcards/import/generate` | `{user_id, source: "paste" \| "library_doc", text?, document_id?, count, difficulty}` | `{cards}` |
| `POST` | `/flashcards/import/cleanup` | `{cards}` | `{cards}` (rewritten) |
| `POST` | `/flashcards/import/cloze` | `{paragraph}` | `{cards}` |

`source` on `/import/parse` is one of `anki | xlsx | url | ocr`.
Client-side formats (`csv`, `tsv`, `txt`, `json`, `paste`) never hit
this route — they go straight to `/import/commit`. The `source` field on
`/import/generate` is unrelated and only distinguishes paste-text vs
library-doc input for AI generation.

All routes use `require_self` from `services/auth_guard.py` (matches
existing flashcard routes).

### New service: `backend/services/flashcard_import_service.py`

Pure functions (no Supabase or HTTP coupling beyond the Gemini wrapper):

- `parse_anki_apkg(file_bytes) -> list[Card]` — `zipfile` + builtin
  `sqlite3` against `collection.anki2`; `notes.flds` is `\x1f`-separated;
  strip HTML to plain text.
- `parse_xlsx(file_bytes) -> list[Card]` — `openpyxl`, first two columns.
- `scrape_quizlet_url(url) -> list[Card]` — HTTP GET, parse the
  `window.Quizlet` JSON blob; raise `QuizletBlocked` on login wall, bot
  challenge, or missing payload. Best-effort by design.
- `extract_cards_from_image(file_bytes) -> list[Card]` — pipe through
  existing `extraction_service`, then a Gemini split prompt.
- `gemini_generate_cards(source_text, count, difficulty) -> list[Card]`
- `gemini_cleanup_cards(cards) -> list[Card]`
- `gemini_cloze(paragraph) -> list[Card]`
- `dedup_against_existing(user_id, course_id, cards) -> (keep, skipped)`
  — lowercase + strip-punctuation, then Levenshtein ≤ 3 on `front`
  against existing rows in the same `(user_id, course_id)` (or
  `(user_id, topic)` when course_id is NULL).

### New prompts in `backend/prompts/`

- `flashcard_generation.txt` — N cards from notes, with difficulty knob.
- `flashcard_cleanup.txt` — fix typos, normalize, shorten definitions.
- `flashcard_cloze.txt` — paragraph → fill-in-the-blank cards.
- `flashcard_ocr_split.txt` — markdown → Q/A pairs.

### Rate limiting

Simple in-memory dict in `flashcard_import_service` keyed by `user_id`:
five AI generation / cleanup / cloze calls per rolling minute. Returns
HTTP 429 with `Retry-After` header. Resets across deploys; acceptable
because abuse is low and the existing app has no Redis.

### File-size cap

Backend rejects uploads >5MB with HTTP 413. Frontend mirrors the limit
client-side and shows a "split this file" hint.

## Frontend

### New files

```
frontend/src/components/flashcards/
  FlashcardImportModal.tsx
  ParsedCardsTable.tsx
  tabs/
    PasteTab.tsx                # term/card delimiters + a "Cloze deletion" sub-mode
    UploadTab.tsx
    UrlTab.tsx
    AiTab.tsx
    PhotoTab.tsx

frontend/src/lib/
  flashcardParsers.ts
```

### `FlashcardImportModal.tsx`

- Shell with course picker (defaults to current `FlashcardsMode` filter
  if a single course is selected, else first enrolled course), tab
  switcher (Paste · Upload · URL · AI · Photo), parsed-cards staging
  area, footer with `Import N cards` button (disabled when zero valid
  cards).
- Owns `cards: ParsedCard[]` state shared across tabs — switching tabs
  preserves what's been parsed so the user can mix sources before
  committing.
- On commit success, calls the parent's `onImported(count)`, which
  triggers `load()` in `FlashcardsMode` and shows the toast.

### `ParsedCardsTable.tsx`

- Columns: row#, Term (editable), Definition (editable), action (delete row).
- Invalid rows (missing front or back, oversized) get a left red border
  and a tooltip with the parser error message.
- Above the table: `Generate reverse cards` toggle, `Clean up with AI`
  button (calls `/import/cleanup`, replaces card list on success).

### `lib/flashcardParsers.ts`

Pure, browser-safe, unit-testable:

- `detectDelimiters(text) -> {term: string, card: string}` — sniff the
  most likely separators when 80%+ of lines parse cleanly.
- `splitByDelimiters(text, term, card) -> ParsedCard[]`
- `parseCSV(text) -> ParsedCard[]` — Papaparse wrapper.
- `parseTSV(text) -> ParsedCard[]`
- `parseJSON(text) -> ParsedCard[]` — accept `[{front, back}]` and
  `[{term, definition}]` shapes.
- `validateCard(card) -> {valid: boolean, error?: string}`

### Wiring

`Study.tsx` `FlashcardsMode` (line ~454) gets a second action button
next to "Generate cards":

```tsx
<button className="btn btn--sm" onClick={() => setImportOpen(true)}>
  <Icon name="import" size={12} /> Import
</button>
```

After commit, `load()` re-fetches and a toast renders via the existing
`ToastProvider`.

### Dependencies

Add to `frontend/package.json`:
- `papaparse`
- `@types/papaparse`

(Backend `openpyxl` is already pulled by `pandas`; verify in plan and add
explicitly to `requirements.txt` if not.)

## Data flow

1. User clicks **Import** in `FlashcardsMode` → modal opens.
2. User picks a course (required) and a tab.
3. Per-tab input → parsing fires (debounced for paste; on-submit for
   file/url/photo/AI).
4. Parsed cards land in `ParsedCardsTable` — user can inline-edit,
   delete rows, toggle reverse, run cleanup.
5. **Import N cards** → `POST /flashcards/import/commit` with
   `{course_id, topic, cards, dedup: true}`.
6. Toast: `"Imported 47 cards. 3 skipped (duplicates)."` → modal closes
   → `FlashcardsMode` reloads.

## Error handling

| Scenario | Handling |
|----------|----------|
| Parser hits malformed row | Row marked invalid, table shows red border + tooltip; valid rows still importable. |
| File >5MB | Frontend blocks with hint; backend returns 413 as defense-in-depth. |
| Quizlet URL blocked / login wall | Backend raises `QuizletBlocked`; UrlTab swaps in a hint card linking to Quizlet's export docs and pointing at the Paste tab. |
| Gemini failure (any AI route) | 502 to client; toast surfaces error; user input preserved for retry. |
| Gemini rate limit hit | 429 with `Retry-After`; toast tells user to wait N seconds. |
| Anki `.apkg` corrupt or unsupported version | Caught in `parse_anki_apkg`, returns 422 with "Couldn't read this Anki file. Try re-exporting." |
| Network failure mid-commit | Toast with retry button; nothing partial-committed because commit is one bulk insert. |

## Testing

### Backend (`backend/tests/`)

- `test_flashcard_parsers.py` — paste delimiter combos (tab/comma/custom
  × newline/semicolon/blank/custom), quoted multi-line CSV, unicode +
  emoji, single-column rows, smart-delimiter detection accuracy.
- `test_flashcard_import_service.py` — Anki `.apkg` fixture (small
  synthetic SQLite-in-zip), `.xlsx` fixture, dedup fuzzy match,
  cleanup/cloze with mocked Gemini.
- `test_flashcard_import_routes.py` — route integration with mocked
  Supabase + Gemini; 401 without auth; 413 on oversized; 429 on rate limit.

### Frontend

Per `CLAUDE.md` there is no automated test suite on this branch.
Verification gate is:

- `npx tsc --noEmit` for type safety.
- Manual smoke matrix:
  - Paste 50-row Quizlet export (tab/newline) — appears in preview, all valid.
  - Paste with semicolon card-separator — auto-detect works after change.
  - Upload `.csv` with quoted multi-line definitions — preserved.
  - Upload Anki `.apkg` — cards extracted, HTML stripped.
  - Quizlet URL — verifies graceful fallback when blocked.
  - Photo OCR — handwritten note → Q/A pairs.
  - AI from library doc — pick existing doc, generate 25 cards.
  - Reverse-cards toggle — both directions present after commit.
  - Cleanup pass — typos fixed.
  - Dedup — re-importing a subset shows "X skipped (duplicates)".

## Open follow-ups (not in this scope)

- A streaming progress UI for very large imports (the spec mentioned
  "Parsed 234/1200 cards…"). Today the bottleneck for 200-card paste is
  ~milliseconds, so we ship without SSE and revisit if real users hit
  files large enough to need it.
- Audio-on-card support (would need `audio_url` column + TTS pipeline).
- A real `flashcard_sets` table if/when users want named decks distinct
  from `topic`.
