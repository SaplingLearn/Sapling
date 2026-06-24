-- Migration: foreign-key integrity for graph_edges + notes
-- Run once in the Supabase SQL editor (idempotent — safe to re-run).
--
-- Closes the orphan-row gaps where a user_id/course_id is a bare TEXT column
-- with no REFERENCES, inconsistent with every sibling table:
--   #179  graph_edges.user_id  -> users(id)
--   #180  notes.user_id        -> users(id)
--   #180  notes.course_id      -> courses(id)
--
-- Each constraint is added behind the same pg_constraint guard the codebase
-- already uses in migration_gradebook.sql, because Postgres has no
-- ADD CONSTRAINT IF NOT EXISTS. Pre-existing orphan rows are deleted first so
-- the ALTER TABLE can validate.
--
-- ON DELETE semantics: these FKs have no ON DELETE clause, so they default to
-- NO ACTION (RESTRICT). A referenced users/courses row cannot be hard-deleted
-- while a graph_edges/notes row still points at it. This guarantees no orphans
-- but does NOT cascade-delete dependents. Today nothing hard-deletes
-- users/courses (delete_account is a soft delete; delete_course only removes
-- the user_courses enrollment row), so RESTRICT never actually fires. Switch
-- to ON DELETE CASCADE (and add a hard-delete path) if cleanup is ever wanted.

-- #179 graph_edges.user_id: remove edges whose user_id has no users row, then
-- add the FK other learning tables already enforce.
DELETE FROM graph_edges
 WHERE user_id NOT IN (SELECT id FROM users);

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'graph_edges_user_id_fkey'
  ) THEN
    ALTER TABLE graph_edges
      ADD CONSTRAINT graph_edges_user_id_fkey
      FOREIGN KEY (user_id) REFERENCES users(id);
  END IF;
END $$;

-- Index the FK referencing column: Postgres does not auto-index the
-- referencing side of a foreign key, and sibling tables index this path.
CREATE INDEX IF NOT EXISTS idx_graph_edges_user_id ON graph_edges(user_id);

-- #180 notes.user_id / notes.course_id: notes is core user data but both
-- columns are bare TEXT. Remove rows pointing at a non-existent user or course
-- (e.g. notes left dangling after a course delete) before adding the FKs.
DELETE FROM notes
 WHERE user_id   NOT IN (SELECT id FROM users)
    OR course_id NOT IN (SELECT id FROM courses);

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'notes_user_id_fkey'
  ) THEN
    ALTER TABLE notes
      ADD CONSTRAINT notes_user_id_fkey
      FOREIGN KEY (user_id) REFERENCES users(id);
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'notes_course_id_fkey'
  ) THEN
    ALTER TABLE notes
      ADD CONSTRAINT notes_course_id_fkey
      FOREIGN KEY (course_id) REFERENCES courses(id);
  END IF;
END $$;
