-- 0030: RAG document chunking — add extracted_text to documents
--
-- Store raw OCR-extracted text on each document row so the chunking
-- pipeline can re-index without re-running extraction.
-- The column is encrypted at the application layer.

ALTER TABLE documents
    ADD COLUMN IF NOT EXISTS extracted_text TEXT;
