# 0031: Run RAG embeddings locally instead of on gemini-embedding-001

- Status: proposed
- Date: 2026-11-02
- Supersedes: none (amends ADR 0025's "embeddings stay on `gemini-embedding-001`"
  and closes the embeddings carve-out ADR 0030 left open)

## Context

ADR 0030 moved every agent slot to Anthropic Claude but could not move
embeddings, because Anthropic ships no embeddings endpoint. That left exactly
one Google dependency in the request path: `services/rag_service.py` built a
raw `google.genai.Client` and called `gemini-embedding-001` with
`output_dimensionality=768` and the `RETRIEVAL_QUERY` / `RETRIEVAL_DOCUMENT`
task types, writing into `course_chunks.embedding VECTOR(768)`.

The practical cost of that carve-out is a whole provider account kept alive for
one call. It is also a silent single point of failure: the key in `backend/.env`
had been dead for some time (Google answers `400 API_KEY_INVALID`), and because
every caller wraps its embed in a broad try/except to degrade gracefully (#439),
nothing surfaced. Document indexing simply never happened, and the tutor
retrieved nothing from uploaded material — with no error anywhere a developer
would look.

The alternatives were a second hosted provider (Voyage, Anthropic's recommended
embeddings partner — another key, another bill, and 1024-d, so a column and ANN
index migration), or running the encoder in-process. `torch` and `transformers`
are already hard dependencies for the Docling/GOT-OCR pipeline, so the second
option adds no new package.

## Decision

Embeddings run locally, in-process, on **`BAAI/bge-base-en-v1.5`**.

- **768-d, so nothing migrates.** `course_chunks.embedding` stays `VECTOR(768)`
  and its ANN index is untouched. This is the main reason bge-*base* was chosen
  over the already-cached bge-*small* (384-d), which would have forced a column
  and index rewrite on staging and production.
- **Query/passage asymmetry is preserved.** bge expects an instruction prefix on
  the query side only (`_QUERY_PREFIX`), which is the direct analogue of the
  `RETRIEVAL_QUERY` / `RETRIEVAL_DOCUMENT` task types. Dropping it costs recall,
  so it is commented as load-bearing rather than left to look like decoration.
- **CLS pooling, then L2 normalisation**, which is what bge was trained to
  produce. `match_course_chunks` ranks on cosine (`<=>`), so unit vectors make
  the stored dot product and the cosine the same number. Note this is a change
  from Gemini's output, which was *not* unit-normalised.
- **The `model_mode()` gate is unchanged.** `_encode()` is reachable only through
  an `_embed_*` function, after its `model_mode() != "real"` check, so a
  function-mode run (the hermetic E2E default, ADR 0019) still never loads
  weights and never touches the network. Import stays cheap: `torch` is imported
  inside `_get_encoder`, not at module scope.
- **The encoder loads once per process, under a lock**, because
  `retrieve_chunks()` runs inline on the request path and uvicorn serves
  concurrently.

### Vectors from two models do not mix

This is the part that fails silently if ignored. Embeddings from different
models do not share a vector space, so a row still holding a Gemini vector is
not "stale" — it is noise that `match_course_chunks` will rank against fresh
query vectors without complaint. **Every row must be re-embedded in one pass**,
which is what `scripts/reembed_course_chunks.py` is for. It rewrites only the
`embedding` column, so the `chunk_text` ciphertext is never touched and the
content-hash `id` (which hashes the PLAINTEXT) stays valid.

## Consequences

- **No embeddings API key is needed at all.** `GEMINI_API_KEY` is no longer read
  by any request-path code. The sanctioned raw `google.genai.Client` sites drop
  from three to two, both offline scripts (`scripts/_raw_gemini.py`,
  `scripts/ingest_catalog.py`).
- **First embed in a process pays a one-off model load** (~440MB of weights from
  the HuggingFace cache, a few seconds). Deployments must either ship the cache
  or allow the first-run download; air-gapped environments need the weights
  baked into the image.
- **Embedding moves from a network call to CPU work** on the request path.
  Latency is comparable for single queries on a warm process, but a large batch
  index now consumes local CPU instead of API quota.
- **`min_similarity=0.55` was re-checked, not assumed.** Measured on the seeded
  corpus: on-topic query 0.87, related-but-different chunk 0.61, off-topic 0.44.
  The threshold still separates them, so it is unchanged.
- **Retrieval quality is not claimed to be identical.** bge-base-en-v1.5 is
  English-only and has a 512-token window. Longer chunks truncate — as they did
  on the hosted API — but a corpus with substantial non-English material would
  regress and should go back to a hosted model via a new slot.

## Alternatives considered

- **Voyage AI (`voyage-3`).** Anthropic's recommended partner and likely the
  strongest retrieval quality. Rejected for this change: it needs a new API key,
  a new dependency, and is 1024-d, so it forces a `VECTOR` column + ANN index
  migration across every environment. That is a bigger, riskier change to make
  while the goal was removing a key, not adding one.
- **Keep Gemini, issue a fresh key.** Zero code change and the documented
  architecture. Rejected because it keeps an entire provider account alive for
  one call and preserves the silent-failure mode that hid the dead key.
- **`bge-small-en-v1.5`** (already cached locally via Docling). Rejected: 384-d
  forces the migration that bge-base avoids.
