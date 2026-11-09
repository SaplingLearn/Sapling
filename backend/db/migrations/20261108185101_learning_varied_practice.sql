-- 20261108185101_learning_varied_practice.sql
-- Learning loop varied practice (spec §13 A140, A141). Four nullable
-- check_items columns; every row stored before keeps NULL in all four and
-- reads exactly as before.
--
-- A140, surface-varied isomorphs (flag `varied_isomorphs`): the varied
-- drafter states each item's surface (learning/surface.py).
--   surface_representation — how the question presents the idea, one of
--     learning.params.SURFACE_REPRESENTATIONS. A closed enum says nothing
--     about the item's content: plaintext.
--   surface_context — a short label naming the item's scenario. That IS item
--     content: encrypted at write (services/encryption.py), decrypted at read.
--   A descriptor is whole or absent: both columns or neither.
--
-- A141, multi-concept items (flag `multi_concept_items`,
-- learning/multi_concept.py): an item combining its apex concept with one or
-- two of the apex's direct prerequisites.
--   apex_key — the apex's concept key (plaintext, like concept_key); the
--     multi-concept picker's lookup.
--   component_keys — the components' concept keys, the apex first (plaintext,
--     like concept_key).
--   Such a row's concept_key is its components joined by the ASCII unit
--     separator (chr(31)), which no concept key ever holds
--     (graph_service._normalize_concept collapses it as whitespace): no
--     per-concept read, picker, reserve or post-test ever meets one.
--
-- Deploy order: this migration may run before or after the code. No read on
-- the request path selects these columns while both flags are off, and a
-- write names them only for a flag-on drafting run.

ALTER TABLE public.check_items ADD COLUMN IF NOT EXISTS surface_representation text;
ALTER TABLE public.check_items ADD COLUMN IF NOT EXISTS surface_context text;
ALTER TABLE public.check_items ADD COLUMN IF NOT EXISTS apex_key text;
ALTER TABLE public.check_items ADD COLUMN IF NOT EXISTS component_keys text[];

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'check_items_surface_representation_known'
    ) THEN
        ALTER TABLE public.check_items ADD CONSTRAINT check_items_surface_representation_known
            CHECK (
                surface_representation IS NULL
                OR surface_representation IN ('verbal', 'symbolic', 'numeric', 'visual', 'applied')
            );
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'check_items_surface_whole') THEN
        ALTER TABLE public.check_items ADD CONSTRAINT check_items_surface_whole
            CHECK ((surface_representation IS NULL) = (surface_context IS NULL));
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'check_items_multi_concept_shape') THEN
        ALTER TABLE public.check_items ADD CONSTRAINT check_items_multi_concept_shape
            CHECK (
                (apex_key IS NULL AND component_keys IS NULL AND strpos(concept_key, chr(31)) = 0)
                OR (
                    apex_key IS NOT NULL
                    AND component_keys IS NOT NULL
                    AND cardinality(component_keys) BETWEEN 2 AND 3
                    AND component_keys[1] = apex_key
                    AND concept_key = array_to_string(component_keys, chr(31))
                )
            );
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_check_items_apex
    ON public.check_items (course_id, apex_key)
    WHERE apex_key IS NOT NULL;

-- PostgREST resolves the new columns from its schema cache; the local stack
-- does not reliably reload on DDL (docs/local-supabase.md). NOTIFY is
-- delivered at COMMIT and is a no-op with no listener.
NOTIFY pgrst, 'reload schema';
