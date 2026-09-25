-- ── course_chunks: exactly one ANN index on `embedding` ─────────────────────
--
-- Every environment had drifted to TWO approximate-nearest-neighbour indexes
-- on course_chunks.embedding, and none of them matched the repo:
--
--   prod     course_chunks_embedding_idx   hnsw (m=16, ef_construction=64)
--            course_chunks_embedding_hnsw  hnsw (m=16, ef_construction=64)  -- identical
--   staging  course_chunks_embedding_idx   hnsw (m=16, ef_construction=64)
--            idx_course_chunks_embedding   ivfflat (lists=100)              -- 0039's
--   local/CI idx_course_chunks_embedding   ivfflat (lists=100)              -- 0039's only
--
-- Both HNSW indexes were created out-of-band (no migration names them). The
-- planner uses one ANN index per scan, so the second is pure write cost: every
-- row written or rewritten is inserted into both graphs. That cost is what made
-- the #484 chunk-text encryption backfill time out on prod (2026-09-25, #663).
--
-- Converge on the index retrieval actually runs on in prod and staging: one
-- HNSW with pgvector's defaults, under the name both environments already use.
-- HNSW needs no training data (ivfflat's `lists` wants tuning against real row
-- counts, per 0039's own note), so it is also the right shape for local/CI.
--
-- Idempotent in every environment: each DROP targets a name that exists in
-- some environments and not others, and the CREATE is a no-op where the index
-- already exists (prod, staging) and a small build where it does not (local/CI
-- replay from empty). Plain DROP/CREATE, not CONCURRENTLY — the runner applies
-- each file in one transaction, and at ~9-13k rows the brief lock is cheap.

DROP INDEX IF EXISTS course_chunks_embedding_hnsw;
DROP INDEX IF EXISTS idx_course_chunks_embedding;

CREATE INDEX IF NOT EXISTS course_chunks_embedding_idx
    ON course_chunks USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);
