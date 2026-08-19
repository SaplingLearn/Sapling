# Encryption coverage gaps — design (epic #522)

**Date:** 2026-08-05 · **Issues:** #518 #519 #520 #521 (parent #522) · **Status:** approved design

Column-level AES-256-GCM encryption (`backend/services/encryption.py`) covers a deliberate
set of columns; the 2026-08-02 audit found four clusters of the same sensitivity class in
plaintext. This spec fixes three clusters and documents the fourth as an intentional
exception. `course_chunks.chunk_text` stays in #484 (its embedding caveat makes it a
separate decision).

## Decisions taken

| # | Decision | Reasoning |
|---|---|---|
| #519 | `newsletter_emails.email` **stays plaintext, documented** (ADR) | Value-keyed `UNIQUE` + index + two upserts (`routes/newsletter.py:27` subscribe, `routes/admin.py:478` allowlist approve) make naive encryption a correctness break. The table doubles as the beta-allowlist workflow, so "stop storing it" is not viable. Subscription/allowlist addresses with no other user data attached; 4 prod rows. The HMAC-lookup-column alternative is recorded as rejected: cost (migration + key derivation + two-route rewrite) buys little for this table's sensitivity. |
| #520 | Encrypt + **new admin read surface** | `feedback`/`issue_reports` are write-only in the app today; the only reader is the Supabase dashboard, which encryption blinds. Admin endpoints + a portal tab replace it. |
| Delivery | **Four stacked PRs**, one per issue | `main ← A(#519 docs) ← B(#520) ← C(#521) ← D(#518)`. Each gets `/code-review` + the e2e lanes before its merge. CodeRabbit skips stacked PRs (base ≠ main), so `/code-review` is the only real review on B–D until retarget. |

**No schema migrations anywhere in the stack** — the #519 decision removed the only one.
Every change is code + backfill.

## Rollout-safety invariant

Code merges before backfill runs, so every read path must tolerate both plaintext
(legacy) and ciphertext rows:

- Text: `decrypt_if_present` already falls back to the raw value on decrypt failure.
- JSONB: reads use the dict-passthrough guard — `isinstance(value, str)` → `decrypt_json`
  (which itself falls back to `json.loads`), dict/list → legacy plaintext row, use as-is.
  Pattern: `routes/documents.py:251`.

Backfill runs staging → prod after each merge:
`dotenv -f .env.staging run -- python -m db.backfill_encryption --apply --table <t>`
(then `.env.production`).

## PR A — #519: ADR + documented exception (no code)

- ADR in `docs/decisions/`: `newsletter_emails.email` plaintext-by-decision, with the
  rejected HMAC alternative recorded.
- `CLAUDE.md`: one line next to the encrypted-columns list naming the intentional
  exception so the gap is not re-filed.
- This spec document.

## PR B — #520: `feedback` + `issue_reports`

**Encrypt at write** (`routes/feedback.py:35,55`) via `encrypt_if_present`:
`feedback.comment`, `feedback.topic`, `issue_reports.topic`, `issue_reports.description`.
`rating`, `type`, `selected_options` (fixed enum set), `session_id`, `screenshot_urls`
stay plaintext/queryable.

**Admin read surface** (new — none exists today):

- `GET /api/admin/feedback`, `GET /api/admin/issue-reports` in `routes/admin.py`:
  `require_admin`, newest-first, decrypt the four columns server-side, resolve reporter
  display names via `services/profiles.get_display_names` (batch, matching the users tab).
- Frontend: a **"feedback" tab** in `components/screens/Admin.tsx` — slots into the
  existing `Tab` union at `Admin.tsx:26` and the tab list at `:58`. Two sections:
  feedback entries (rating / type / topic / comment) and issue reports (topic /
  description / links to the already-private screenshot URLs, #231). Fetchers in
  `lib/api.ts` via `fetchJSON` (same-origin convention). Testids per
  `docs/frontend-testids.md` "Adding a surface".

No SQL filters or search touch these columns (verified — the app never reads the tables),
so nothing is lost to encryption.

## PR C — #521: quiz performance data

**Writes** — `encrypt_json` at three sites:

| Column | Site |
|---|---|
| `quiz_attempts.questions_json` | insert, `routes/quiz.py:352` |
| `quiz_attempts.answers_json` | score update, `routes/quiz.py:486` |
| `quiz_context.context_json` | `services/quiz_context_service.py:18` upsert — conflict target is `(user_id, concept_node_id)`, never the JSON; untouched |

**Reads** — decrypt at four sites, always before any prompt or cache:

- `routes/quiz.py:383` submit path — the existing `isinstance(str) → json.loads` becomes
  the decrypt-aware guard.
- `services/quiz_context_service.py:8` `get_quiz_context`.
- `agents/tools/quiz_history.py:111` — before the payload reaches the agent prompt.
- `services/course_context_service.py:265` `_fetch_quiz_context_rows` — decrypt **before**
  the lru-cached value is built, so the cache holds plaintext dicts exactly as now.

Scalars `score` / `total` / `difficulty` / `completed_at` untouched — the quiz-history
tool (`agents/tools/quiz_history.py:132`) and `admin_analytics` rollups read only those
(verified).

## PR D — #518: derived content

- **`flashcards.front` / `.back`** — encrypt at both insert sites (topic-generated
  `routes/flashcards.py:250`, offering/import `:411`); decrypt at the list read (`:290`).
  The rate path (`:337`) touches only counters — no change. **Import dedupe**
  (`services/flashcard_import_service.py:78`) decrypts existing `front` values before
  normalize/Levenshtein; per-user-per-offering counts are small, stays in-process.
- **`study_guides.content`** — `encrypt_json` at insert (`routes/study_guide.py:203`);
  decrypt at the list (`:211`) and cached read (`:322`). ETags derive from
  `id + generated_at`, not content (`study_guide.py:221`) — unaffected.
- **`room_summaries.summary`** — encrypt in `services/social_cache_service.py:34`
  `save_summary`; decrypt in `get_cached_summary` (`:24`). Cache validity compares only
  `member_hash` — unaffected.

## Cross-cutting — in every code PR (B–D), for its own columns

| Artifact | Change |
|---|---|
| `db/backfill_encryption.py` | new `backfill_*` functions off the existing `_encrypt_text_column` / `_encrypt_json_column` helpers; register in `main()` |
| `e2e_oracles/gather.py` `_CIPHERTEXT_MANIFEST` | add each new column — the ciphertext oracle then enforces encrypted-at-rest forever |
| `db/seed_local_rich.py` | seed writes these columns **encrypted**; add rows for the unseeded tables (`feedback`, `issue_reports`, `quiz_context`, `room_summaries`) |
| `tests/integration/test_encryption_roundtrip.py` | one raw-SQL round-trip entry per column (ciphertext at rest + decrypt back to seeded plaintext) |
| Hermetic tests | per write boundary: stored value is ciphertext ≠ plaintext and decrypts back; per read boundary: plaintext reaches the response/prompt; legacy-plaintext-row case covered explicitly |
| `CLAUDE.md` | encrypted-columns list grows per PR |

Canopy's `sapling-infrastructure` encrypted-columns table gets **one** staged doc update
at the end of the epic (re-based against whatever version is then current), not four
conflicting staged versions.

## Failure modes and their answers

| Risk | Answer |
|---|---|
| Ciphertext reaches an LLM prompt or the UI | Read-boundary tests assert plaintext on exactly those paths; the function-mode e2e lane exercises quiz / flashcard / study-guide journeys end to end |
| Legacy rows before backfill | Graceful-degrade fallbacks in the helpers + the JSONB dict-passthrough guard; hermetic tests cover the plaintext-row case |
| Silent decrypt regression corrupting data | Roundtrip integration test + ciphertext oracle, both extended per PR — not at the end |
| Losing the ability to read feedback | PR B's admin endpoints + portal tab land **in the same PR** as the encryption |

## Epic definition-of-done mapping

- Every child closed or deferred with reasoning → A closes #519 (deferral), B–D close #520/#521/#518; #484 stays open by design.
- `CLAUDE.md` + Canopy table match reality → per-PR CLAUDE.md updates + one staged Canopy update.
- Raw-SQL round-trip per new column → per-PR roundtrip entries.
- Deliberate plaintext documented → PR A's ADR + CLAUDE.md exception line (also covers epic-recorded `job_applications` deletion decision — out of scope here).
