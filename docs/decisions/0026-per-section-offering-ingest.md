# 0026: Per-section course offerings (Fall 2026 BU ingest)

- Status: accepted
- Date: 2026-08-01
- Issue: #280
- Supersedes: none (extends 0020's academics split)

## Context

Since the 0020 academics split, `course_offerings` is the (course × term) row that
enrollments, the gradebook, documents, notes, and study analytics all key on. In
practice it has been **hollow**: staging held 12,318 offerings of which exactly 4
(the demo seed) carried a section, and none carried a real meeting time or
location. Courses could not behave like a registrar.

Issue #280 ingests the operational layer for `fall-2026` from bu.edu, which
publishes, per course, one table per section:

```text
Section | Instructor | Location | Schedule | Notes
A1      | Erdos      | LSE B01  | TR 2:00 pm-3:15 pm | ...
```

Three things had to be decided to land this safely. The first has already
shipped ahead of this ADR (see below); the ADR records the reasoning for all
three because they only make sense together.

## Decision 1: `section` becomes `NOT NULL DEFAULT ''`

0020 added `UNIQUE (course_id, term_id, section)`. Postgres treats NULLs as
distinct in a unique index, so with `section` NULL on 12,314 of 12,318 rows the
constraint enforced nothing on the rows the app actually creates.

The alternative was `UNIQUE ... NULLS NOT DISTINCT` (PG15+). We chose the
non-null default because it also fixes the **application** write path, not just
the import: `services/academics.py::resolve_offering(create=True)` inserts a
section-less offering when a user enrolls in a course that has none for the
current term. Under NULL-distinct semantics two concurrent enrollments create
two offerings, and the two students end up with disjoint documents and notes for
the same class.

`''` reads as "the registrar published no section for this offering", which is
what these rows have always meant.

**Status: already applied.** This shipped as
`0033_offering_section_not_null.sql`. It reached staging out-of-band during
the #280 work and was recovered into the repo by #510 (one of the three
migrations that reconciliation covers, which is why the frozen `NNNN_` range
runs to 48).
`0036_offering_null_section_unique.sql` had meanwhile closed the same hole the
other way, with a partial unique index on `WHERE section IS NULL`; that index
became unreachable once `section` was NOT NULL and was dropped by
`20260801062439_drop_dead_null_section_index.sql`. This change therefore adds no
migration of its own — it depends on a chain that is already in place.

## Decision 2: adopt hollow offerings in place, never re-create

Staging already had 4,122 hollow `fall-2026` offerings (an earlier catalog-only
sync), and 7 enrollments plus 19 sessions pointed at them. `course_offerings` is
referenced by 8 tables with mixed delete semantics — documents/notes/study_guides
CASCADE, sessions/flashcards SET NULL — so a delete-and-reinsert import would
have destroyed or silently orphaned real rows.

`db/import_offerings.py` therefore **adopts**: for each course, the first
published section takes over the existing section-less row (updated in place, id
preserved) and only the remaining sections are inserted. Re-running matches every
section by code, finds nothing to adopt, and writes nothing.

Corollary: offerings the scrape no longer lists are **reported, never deleted**.
A partial or failed scrape must not be able to wipe a term.

## Decision 3: `resolve_offering` orders by section, not `created_at`

Once a course has one offering per section (CAS CS 330 has 7), the old
`order="created_at.asc", limit=1` was non-deterministic: the sections are written
by a single batch insert, so they share a `created_at` and the winner was left to
the planner. Two calls could hand the same user different offerings and split
their documents and notes across sections.

Ordering by `section.asc` first makes the pick stable. `''` sorts before `A1`, so
wherever a hollow offering still exists the pre-#280 behaviour is preserved.

All three of `resolve_offering`'s reads carry that order, not just the
term-filtered one: the post-409 re-select (which would otherwise be the single
path able to return a row the steady-state reader would not) and the cross-term
fallback. The fallback matters most — it is unfiltered by term, so it picks among
*every* section of the course in *every* term. That is latent only while
`current_term()` resolves to the newest seeded term; seeding a later term (terms
are maintained — see `0032_retire_summer_2026.sql`) makes it live for every
fallback caller (`routes/study_guide.py`, `routes/notes.py`, `routes/flashcards.py`).

This resolves *determinism*, not *correctness of section choice* — a student
enrolling in CAS CS 330 lands in A1 regardless of the section they actually
registered for. Letting students pick a section belongs with the API/frontend
work (#280 task 4) and is deliberately not solved here.

## Consequences

- The knowledge graph is unaffected: it keys on the abstract `courses.id`, and
  the import resolves each `course_code` to the existing catalog row rather than
  creating a parallel course. Adding sections cannot fork a course's graph
  identity.
- RAG is unaffected: `course_chunks` keys on `course_code`, not `offering_id`, so
  the shared-course-corpus property survives sections.
- The gradebook keys on `enrollment_id` and study analytics on `offering_id`;
  both keep working because adoption preserves offering ids.
- `scripts/scrape_bu_catalog.py` gained a `--rescan` mode. Sections were never
  stored by the old parser, so recovering them required re-fetching course pages;
  `--rescan` refetches only the URLs already in the JSON (no listing walk), which
  also preserves index-orphan courses that only `probe_unscraped_courses.py`
  found.
- BU publishes multiple meeting patterns for one section (a lecture block plus a
  separate exam block). The importer merges them into a single offering row
  rather than keeping the first, which would have dropped a real meeting from 308
  sections. `_merge_meetings` joins the patterns with `"; "`.
