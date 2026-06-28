-- 0019: shared conventions + term/school entities (additive, non-breaking)
-- Part of the DB modular redesign (docs/superpowers/specs/2026-06-23-db-modular-redesign-design.md).
-- Nothing here breaks existing code; later migrations build on the terms entity + trigger.

-- Reusable updated_at trigger. Every later mutable table attaches this so updated_at
-- can never be forgotten by application code.
CREATE OR REPLACE FUNCTION set_updated_at() RETURNS trigger AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Schools (optional namespacing for the catalog). Free-text courses.school is retired in 0020.
CREATE TABLE IF NOT EXISTS schools (
    id         TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    name       TEXT NOT NULL,
    slug       TEXT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Structured, orderable term entity. "Current term" is date-derived (today in [start,end]).
CREATE TABLE IF NOT EXISTS terms (
    id         TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    term       TEXT NOT NULL CHECK (term IN ('Fall','Spring','Summer','Winter')),
    year       INTEGER NOT NULL,
    label      TEXT NOT NULL,                       -- e.g. 'Spring 2026' (matches legacy courses.semester)
    start_date DATE NOT NULL,
    end_date   DATE NOT NULL,
    sort_key   INTEGER NOT NULL,                    -- year*10 + term ordinal (Spring=1,Summer=2,Fall=3,Winter=4)
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (term, year)
);

-- Seed canonical terms. The legacy catalog default is 'Spring 2026'; the surrounding terms
-- give date-derived "current" something to resolve to and establish ordering.
-- NOTE: contiguous, non-overlapping ranges so exactly one term contains any given date.
INSERT INTO terms (id, term, year, label, start_date, end_date, sort_key) VALUES
    ('fall-2025',   'Fall',   2025, 'Fall 2025',   '2025-08-25', '2026-01-04', 20253),
    ('spring-2026', 'Spring', 2026, 'Spring 2026', '2026-01-05', '2026-05-17', 20261),
    ('summer-2026', 'Summer', 2026, 'Summer 2026', '2026-05-18', '2026-08-23', 20262),
    ('fall-2026',   'Fall',   2026, 'Fall 2026',   '2026-08-24', '2027-01-03', 20263)
ON CONFLICT (term, year) DO NOTHING;

-- Before promoting to prod: SELECT DISTINCT semester FROM courses; and add a terms row
-- (matching label) for any value not covered above, or 0020's term mapping will fail loudly.
