# 0025: Encrypt `course_chunks.chunk_text` — restore the encryption boundary, but the embedding stays plaintext

- Status: accepted
- Date: 2026-07-31
- Relates to: #484 (this decision), #483 (blocked on it), #482 (RAG hardening),
  #231 (storage/RLS lockdown), migration 0030 (`documents.extracted_text`),
  migration 0039 (the vector store)
- Supersedes: none

## Context

#484 names a real asymmetry. `documents.extracted_text` is encrypted (0030)
because it is student-uploaded content; `course_chunks.chunk_text` holds *the
same text, chunked*, in plaintext. One column is treated as PII and the other
isn't, for no reason anyone wrote down.

**The issue's stated premise is wrong, and it matters.** It assumes "pgvector
similarity can't run over ciphertext." `match_course_chunks` (0039) computes
`1 - (c.embedding <=> query_embedding)`, orders by `c.embedding <=>
query_embedding`, and filters `WHERE c.embedding IS NOT NULL`. `chunk_text` is
only ever SELECTed as payload — the ranking never reads it. Nothing in the
codebase queries it by content either (no `ILIKE` / `LIKE` / FTS; verified
across `services/`, `routes/`, `scripts/`). So encryption does not block
retrieval at all, and this decision is far cheaper than the issue implies.

But the correction cuts both ways, and this is the part worth recording: **the
reason it's cheap is the reason it's partial.** The `embedding` column cannot
be encrypted — pgvector must compute distance over it — and an embedding is a
lossy but real representation of its source text; embedding-inversion
techniques recover substantial content from vectors alone. Encrypting
`chunk_text` therefore does *not* make the row opaque.

Threat model, for calibration: the backend connects with the service-role key
and RLS locks out `anon`/`authenticated` (#231), so direct table reads imply a
Supabase credential compromise or an insider. `ENCRYPTION_KEY` is a separate
secret held in the app environment, so column encryption genuinely raises the
bar against a database-only compromise — the same bar every other encrypted
column is already set at.

## Decision

Encrypt `chunk_text` for **every** row in `course_chunks` — document *and*
catalog — through the standard `encrypt_if_present` / `decrypt_if_present`
helpers, and compute content-addressed ids on the **plaintext, before
encryption**.

Uniform rather than scoped to document chunks, even though catalog chunks are
public BU course-catalog text with nothing to protect:

- One invariant — "`chunk_text` is always ciphertext" — is assertable by the
  existing `ciphertext` e2e oracle. A per-category rule is not.
- `decrypt_if_present` returns the **raw value** when it cannot decrypt. In a
  mixed table that makes a genuine decrypt failure indistinguishable from a
  legitimately-plaintext catalog row, which is precisely the kind of silent
  degradation #482 was about.
- The cost is ~5 AES-GCM decrypts per retrieval (`k=5`). Immaterial.

Ids stay keyed on plaintext because AES-GCM uses a random nonce per call: the
same plaintext encrypts to different ciphertext every time, so ciphertext can
never be a dedup key. `chunk_id(course, text)` remains the merge key, and
re-uploads of identical content still converge on one row.

**This ADR does not claim chunk confidentiality.** It restores boundary
consistency and removes trivially-readable plaintext. The embedding remains,
and it is the residual exposure.

## Consequences

- (+) The encryption boundary is consistent: the same student text is
  protected in `documents.extracted_text` and in the chunks derived from it.
- (+) Retrieval is unaffected — ranking never touched `chunk_text`.
- (+) Unblocks #483. Notes indexing would otherwise write decrypted note
  bodies (`notes.body` is encrypted) into a plaintext column, deepening the
  very asymmetry this closes.
- (+) A uniform invariant the `ciphertext` oracle can assert, so a future
  regression fails a lane instead of sitting unnoticed.
- (−) **Residual exposure: the embedding stays plaintext and is partially
  invertible.** This is defense in depth, not confidentiality. Anyone reading
  this ADR to answer "is chunk content protected?" must read this line.
- (−) `scripts/dedupe_course_chunks.py:70` re-derives ids from the **stored**
  `chunk_text`. Run against encrypted rows it would hash ciphertext and
  destroy content-addressing. It must decrypt before hashing, or be retired —
  its own docstring calls it a one-time migration.
- (−) A backfill is required for existing rows (the
  `db/backfill_encryption.py` precedent). Until it completes the table is
  mixed, carried by `decrypt_if_present`'s raw-value fallback.
- (−) Catalog chunks pay encryption cost for no privacy benefit. Accepted as
  the price of the uniform invariant.

## Implementation (not done here)

Write sites: `services/rag_service.py::index_document_chunks` and
`scripts/ingest_catalog.py`. Read site:
`services/rag_service.py::retrieve_chunks`, decrypting each returned chunk
before `format_rag_context`. Plus the dedupe-script fix above, a backfill, and
extending the `ciphertext` oracle to cover the column.
