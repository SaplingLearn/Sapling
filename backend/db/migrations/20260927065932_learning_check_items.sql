-- 20260927065932_learning_check_items.sql
-- Learning loop series PKG-04: ingest-time check items per course concept.
-- prompt / reference_answer / rubric_json / common_wrong_json / options_json /
-- correct_option / canonical_answer are encrypted (services/encryption.py);
-- question_hash is the plaintext lookup key.
-- Check items are COURSE assets, not per-student rows. graph_nodes is keyed per
-- (user, course, concept_name), so a node_id FK would bind an item to the
-- uploader. Key on (course_id, concept_key) instead, where concept_key =
-- services/graph_service._normalize_concept(concept_name). A student's node maps
-- to its items via _normalize_concept(graph_nodes.concept_name). (Amendment A2.)
CREATE TABLE IF NOT EXISTS check_items (
  id                text PRIMARY KEY,
  course_id         text NOT NULL,
  concept_key       text NOT NULL,
  document_id       text,
  format            text NOT NULL CHECK (format IN ('free','teachback','mc_reason')),
  difficulty        smallint NOT NULL CHECK (difficulty BETWEEN 1 AND 3),
  prompt            text NOT NULL,          -- encrypted
  reference_answer  text NOT NULL,          -- encrypted
  rubric_json       text NOT NULL,          -- encrypted JSON: [{"id": "...", "text": "..."}], >= CHECK_ITEM_MIN_RUBRIC
  common_wrong_json text NOT NULL,          -- encrypted JSON: [{"key": "...", "text": "..."}]; key is the plaintext id used elsewhere
  options_json      text,                   -- encrypted JSON [{"letter","text","wrong_key"}]; mc_reason only; exactly 1 correct (A22)
  correct_option    text,                   -- encrypted letter; mc_reason only (A22)
  answer_kind       text NOT NULL DEFAULT 'free' CHECK (answer_kind IN ('free','numeric')),   -- A22
  canonical_answer  text,                   -- encrypted; numeric only; parseable (A22)
  tolerance         double precision,       -- numeric only (A22)
  canonical_verified boolean NOT NULL DEFAULT false,  -- true ONLY on independent second-model agreement or instructor confirmation (A22)
  stepwise          boolean NOT NULL DEFAULT false,   -- reference has >= 2 numbered steps; H4 sibling eligibility (A17)
  source_chunk_ids  text[] NOT NULL DEFAULT '{}',
  source_document_ids text[] NOT NULL DEFAULT '{}',  -- documents whose passages drafted this item; withdrawal deletes by these (A23)
  question_hash     text NOT NULL,          -- sha256 of PLAINTEXT prompt (ADR 0025 pattern)
  graded            boolean NOT NULL DEFAULT false,   -- graded coursework flag; false on every generated item. Ungraded is not "practice" (H6 predicates, §3.3, A32)
  created_at        timestamptz NOT NULL DEFAULT now(),
  UNIQUE (course_id, concept_key, question_hash)
);
CREATE INDEX IF NOT EXISTS check_items_concept_idx ON check_items (course_id, concept_key, format, difficulty);
CREATE INDEX IF NOT EXISTS check_items_source_docs_idx ON check_items USING gin (source_document_ids);
