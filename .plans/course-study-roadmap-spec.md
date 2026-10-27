# Course Study Roadmap — Spec

**Status:** interview complete. All decisions below are either chosen by the user
or decided by me where the user delegated (those are marked **[delegated]** with
their rationale).
**Last worked:** 2026-10-27.

---

## 1. What this is

Clicking a course node on the knowledge graph (`/tree`) opens a study roadmap for
that course. The roadmap lists the topics the student needs to review, each
broken into subtopics. Every subtopic carries a mastery level that only quizzes
can raise. A readiness ring scores how prepared the student is for a chosen exam.

Everything shown is a view of the student's existing knowledge graph. There is no
second curriculum store. Every edit made on the roadmap is a graph write, so it
appears on `/tree` immediately.

Two reference layouts were supplied and are composed into one page:

1. A study-plan page — ordered accordion of topics and subtopics in the main
   column, with a sidebar carrying progress, syllabus, and exam dates.
2. A Khan-Academy-style sidebar — one progress ring plus a skill breakdown of
   segmented bars, one row per topic.

Sapling branding throughout; the references supply structure, not styling.

---

## 2. Grounding — what already exists

Verified by reading the code on 2026-10-27.

| Thing | Where | Notes |
| --- | --- | --- |
| Graph nodes | `graph_nodes` (`db/migrations/0023_graph_integrity.sql:8`) | `concept_name`, `course_id` (abstract course, nullable), `mastery_score` double, `mastery_tier` in `unexplored/struggling/learning/mastered/subject_root`, `times_studied`, `last_studied_at`, `color`. |
| Graph edges | same migration, `:42` | `relationship_type` in `related / prerequisite / builds_on / part_of`; UNIQUE on `(user_id, source_node_id, target_node_id, relationship_type)`. |
| Mastery history | `node_mastery_events` | Append-only since 0023. |
| Graph writes | `services/graph_service.py::apply_graph_update` (`:461`) | The only sanctioned mutation path. |
| Course root nodes | synthesized `subject_root__{course_id}` | Not real rows; `is_subject_root` set on the payload. |
| Tier thresholds | `backend/config.py::get_mastery_tier`, mirrored in `src/lib/graph/nodeStyle.ts::tierFor` | mastered ≥ 0.75, learning ≥ 0.45, struggling ≥ 0.1. Pinned by a table test. |
| **Mastery colour encoding** | **`src/lib/graph/nodeStyle.ts`** | `shadeFor(courseColor, nodeId)` + `TIER_OPACITY { mastered 1, learning .78, struggling .55, unexplored .28 }` + `opacityFor`. Already shared by the 2D and 3D renderers and pinned by `e2e/graph.spec.ts`. |
| Current course-node click | `src/components/screens/Tree.tsx:299` | Opens a detail panel with Learn and Quiz. |
| Exams | `assignments` (`0021_gradebook.sql:30`) | `assignment_type` includes `'exam'`; keyed on `enrollment_id`; `due_date DATE`; encrypted `notes` and `points_*`. |
| Per-question quiz data | `quiz_responses` (`20260812214402_quiz_responses.sql`) | `question_index`, `selected_index`, `is_correct`, `time_ms`, `confidence`, `answered_at`. Written **per answer** by `POST /api/quiz/attempts/{id}/answer`, UNIQUE on `(attempt_id, question_index)`. All plaintext scalars by design; no student text. |
| Quiz question model | `agents/quiz.py:44` `QuizQuestion`, `:71` `concept: str` | A concept **name**. Stored into `questions_json` as `concept_tested` (`routes/quiz.py:539`) but **not** used to award mastery. |
| **How mastery is awarded today** | `routes/quiz.py:2525–2572` | **Whole-attempt.** One `mastery_after(before, score, total)` from `services/quiz_config.py:106` (`+0.03` per correct, `−0.02` per wrong, clamped to [0,1]), applied as a single `updated_nodes` entry on `attempt["concept_node_id"]`. Re-submit is explicitly guarded against double-applying (`:2399`). |
| `apply_graph_update` node resolution | `routes/quiz.py:2553–2556` | Resolves by **normalized `concept_name` within `(user_id, course_id)`**, not by node id, and owns the clamp, `times_studied`, `last_studied_at`, the `node_mastery_events` row, and the streak. |
| Event types | `routes/quiz.py:2544–2550` | From whole-attempt score ratio: `quiz_correct` ≥ 0.7, `quiz_partial` ≥ 0.4, else `quiz_confusion`. The column has two writers and no CHECK, so producer prefixes matter. |
| Tutor's mastery writer | `agents/tools/graph.py:156` `update_mastery_tool` | Writes positive **and negative** deltas with event types `tutor_interaction / tutor_correction / tutor_quiz`. This is the thing §3.5 switches off. |
| Attempt scope | `quiz_attempts.concept_node_id`, plus `mastery_before` / `mastery_after` | One nullable node — the "launched from" concept — and a single before/after pair per attempt. |
| Node dedup | `graph_nodes` UNIQUE `NULLS NOT DISTINCT (user_id, course_id, concept_name)` | Constrains rename and merge (§3.11). |
| Exam proximity | `20260822090747_quiz_attempts_exam_days_away.sql` | Attempts already record days-to-exam. |
| Syllabus parsing | `agents/syllabus_extraction.py` | Runs on upload. |
| Term resolution | `services/academics.py` | `current_term`, `resolve_offering`, `term_for_offering`. |
| Route precedent | `src/app/(shell)/gradebook/[courseId]/page.tsx` | The existing per-course page shape. |

---

## 3. Decisions

### 3.1 Topics come from the graph, not a plan table

A **topic** is a `graph_node` that has `part_of` children. A **subtopic** is such
a child. There is no curriculum table; the graph owns both structure and mastery,
so nothing can drift out of sync.

A concept with no `part_of` relationship in either direction is **unfiled**. The
page always renders an "Unfiled concepts" group at the bottom, collapsed when
empty, so no concept can ever become invisible.

**There is no such thing as a childless topic.** An earlier draft said one would
"render as a topic containing itself"; implementing §3.1 showed that to be
unreachable. In a pure `part_of` model, a node with no children has no `part_of`
edges at all, which makes it indistinguishable from an unfiled concept — because
it *is* one. Such nodes render in the Unfiled group, and the way out is to file
them under a topic, not to promote them.

A node that is both a parent and someone else's child is treated as a **topic**:
it owns children, which is what the page needs to render, and its own parent
link is ignored rather than nesting a third level. The layout is two deep by
design (§4).

### 3.2 Order is computed, not stored

Topic order is a **topological sort over `prerequisite` and `builds_on` edges**
between topic nodes (Kahn's algorithm). Subtopic order inside a topic is the same
sort scoped to siblings.

- Tie-break, applied at every level for determinism: `created_at` ascending, then
  `concept_name` ascending.
- **Cycles must never raise.** When Kahn stalls, the remaining nodes are appended
  in tie-break order and flagged `in_cycle: true`, which the UI surfaces as a
  quiet "circular prerequisite" note on those rows.
- A course with no prerequisite edges at all sorts entirely by the tie-break,
  which is stable across loads.

"Start learning here" marks the first topic in order that is not fully mastered.

### 3.3 Exam scope is agent-inferred and student-correctable

A new join table maps exams to topics:

```sql
exam_topics (
  id            TEXT PRIMARY KEY,
  user_id       TEXT NOT NULL REFERENCES users(id)       ON DELETE CASCADE,
  assignment_id TEXT NOT NULL REFERENCES assignments(id) ON DELETE CASCADE,
  node_id       TEXT NOT NULL REFERENCES graph_nodes(id) ON DELETE CASCADE,
  in_scope      BOOLEAN NOT NULL DEFAULT TRUE,
  weight        NUMERIC,          -- NULL → 1.0 in the readiness formula
  source        TEXT NOT NULL CHECK (source IN ('agent','user')),
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (user_id, assignment_id, node_id)
)
```

`syllabus_extraction` is extended to emit exam coverage, written with
`source='agent'`. A student correction writes `source='user'`, which always wins:
a later agent pass must never overwrite a user-sourced row.

### 3.4 One course map; exams are overlays

A single route per course. Selecting an exam re-prioritises and **dims**
out-of-scope topics; it never removes them from the page. A wrong inference can
therefore reduce emphasis but can never hide something that is actually on the
test. The roadmap is fully usable for a course with no exams recorded.

### 3.5 Quizzes are the only thing that raises mastery; staleness is shown, not subtracted

- Scored quiz attempts are the only positive writer of `mastery_score`.
- Tutor sessions keep creating nodes and edges through `apply_graph_update`, and
  keep updating `last_studied_at`, but no longer move mastery. **Concretely: the
  tutor's `agents/tools/graph.py:156 update_mastery_tool` is removed from the
  tutor agent's toolset**, along with the prompt text that instructs it to adjust
  mastery. `apply_graph_update_tool` stays — node and edge creation is unaffected.
  Existing `tutor_*` event rows stay in the ledger as history.
- **Time decay is display-only.** No scheduled job ever writes a negative
  `node_mastery_events` row, and `mastery_score` never falls because days passed.
- Freshness is a derived display factor only (§3.7).

**Two separate channels, and they must not be conflated:**

| | What it measures | Who writes it | Can it fall? |
| --- | --- | --- | --- |
| `mastery_score` | Whether you know it | Scored quiz attempts only | **Yes** — on contrary evidence (a wrong answer). **Never** from time passing. |
| Freshness `f` | How recently you proved it | Nothing — derived at read (§3.7) | Yes, with time. Stored nowhere. |

So `services/quiz_config.py:103`'s `MASTERY_DELTA_PER_WRONG = 0.02` **stays**.
The tuned scoring model is unchanged; a student who fails a topic they had
mastered does see the number fall, because that is fresh evidence rather than
the mere passage of time. What is removed is any writer that lowers mastery
*because days elapsed* — that job belongs entirely to freshness, which is
separate information and is never persisted.

### 3.6 The readiness ring

Shows readiness for the selected exam; with no exam selected or recorded it falls
back to course readiness over all topics. The component never changes shape.

```
readiness = Σ(wᵢ · mᵢ · fᵢ) / Σ wᵢ        over in-scope subtopics

  mᵢ = mastery_score            0–1, the stored high-water mark
  fᵢ = freshness                1.0 → 0.6 floor (§3.7)
  wᵢ = exam_topics.weight       1.0 when NULL or when no exam is selected
```

Clicking the ring opens a breakdown with one row per topic showing its mastered
count, its freshness multiplier, its weight, and its resulting contribution, then
the overall figure. Every number on that panel must be reproducible from the row
data the same endpoint returns.

Topic-level figures shown in the UI are **counts** (`4 of 8 mastered`), never
averages, so the topic bar and its subtopic segments cannot disagree.

### 3.7 Freshness

Freshness is **exam-relative**. With no exam selected, `f = 1.0` for everything
and no stale markers appear.

The clock's source is `quiz_responses` — `max(answered_at) WHERE is_correct AND
concept_node_id = node` — once §3.13 puts `concept_node_id` on that table. Rows
written before that migration have no node, so freshness falls back to the
attempt-level `quiz_attempts.completed_at` for its `concept_node_id`, and the
breakdown labels those rows as approximate rather than pretending otherwise.

```
d  = days since the subtopic's last CORRECT quiz answer
     (a wrong answer does not reset the clock; an unattempted subtopic
      has m = 0, so f is immaterial)
D  = days until the selected exam, floored at 1

staleness = clamp(d / D, 0, 1)
f         = 1.0 − 0.4 · staleness          → floor 0.6
stale marker shown when staleness ≥ 0.5
```

This reads plainly in the breakdown: "you last proved this 20 days ago and the
exam is in 9 days." The same subtopic's freshness differs per exam, which is
correct and must be stated in the breakdown copy.

### 3.8 Mastery colour **[user-specified]**

Mastery is encoded exactly as the knowledge graph already encodes it, by reusing
`src/lib/graph/nodeStyle.ts` rather than inventing a parallel scale:

- Base hue = the course colour, the same value `/tree` uses.
- Per-node variation = `shadeFor(courseColor, nodeId)`.
- Mastery = the `TIER_OPACITY` ramp through `opacityFor(tier)`
  (`mastered 1 · learning .78 · struggling .55 · unexplored .28`).

So a subtopic segment, an accordion row marker, and that concept's node on
`/tree` are the same colour at the same strength. Retuning the ramp changes both
surfaces at once, and `e2e/graph.spec.ts`'s `TIER_OPACITY` mirror already guards
it.

Two additions are required because opacity alone is weak at segment scale:

- A redundant tier glyph on each accordion row — `○` unexplored, `◔/◐` struggling
  and learning, `●` mastered — so the state survives greyscale and small sizes.
- The stale marker is a **hatch or outline, never a hue**, so it cannot be
  confused with a mastery level.

Each bar is also labelled with its count in text, which is what the second
reference image does and what screen readers read.

### 3.9 Edits exposed on the roadmap

All go through `apply_graph_update` and appear on `/tree` immediately.

- **Rename** a topic or subtopic.
- **Reparent** — drag a subtopic to another topic; rewrites its `part_of` edge.
- **Reorder** — see §3.10.
- **Unfile** ("remove from roadmap") — deletes the `part_of` edge only. The
  concept moves to the Unfiled group; the node and its entire mastery history
  survive, and re-parenting restores it. **Nothing on this page ever deletes a
  node.** Real deletion stays on the Tree page.
- **Merge duplicates** — see §3.11.
- **Exam-scope correction** — inline on the topic row while an exam filter is
  active (§3.12).

Creating new concepts is **not** offered here; that stays with the extraction
agents and the Tree page's existing add-concept path (#330).

### 3.10 Reorder conflicts: the drag is refused, with a one-click fix

Dragging topic B above topic A when a `prerequisite` edge says A comes first does
not silently rewrite the graph. The drop is refused and a dialog explains:

> "Cell Structure builds on Proteins & Nucleic Acids. Remove that prerequisite?"

Confirming deletes the edge through `apply_graph_update`; the list then re-sorts
naturally. Order stays purely derived — no pin storage, no override column — and
the structural change is always explicit.

### 3.11 Merge

Survivor is the node with the **higher `mastery_score`**; ties break to the older
`created_at`. The merge is one new `graph_service` function, `merge_nodes`, and
must re-point every reference before deleting the loser:

1. `node_mastery_events.node_id` → survivor (histories concatenate; the ledger
   stays complete and auditable).
2. `graph_edges` — rewrite both endpoints, and on a UNIQUE
   `(user_id, source, target, type)` collision keep the row with the greater
   `strength` and drop the other. Self-edges produced by the rewrite are dropped.
3. `quiz_attempts.concept_node_id`, `quiz_responses.concept_node_id` (§3.13),
   `quiz_context.concept_node_id`, `note_concepts`, and `exam_topics` (on a
   UNIQUE collision, a `source='user'` row wins over an `'agent'` one).
4. Delete the loser.

The survivor's `mastery_score` is `max(a, b)`. `times_studied` sums;
`last_studied_at` takes the later. `quiz_attempts.mastery_before` /
`mastery_after` on re-pointed rows are **left as written** — they are a
historical record of what that attempt did, and rewriting them would falsify the
ledger.

Both the merge and the rename must respect `graph_nodes`'s UNIQUE
`NULLS NOT DISTINCT (user_id, course_id, concept_name)`. Merge cannot violate it
(two same-named nodes in one course could not both exist), but **rename can** —
renaming a concept onto an existing sibling's name must be caught and offered as
a merge instead of failing with a constraint error.

### 3.12 Exam-scope correction UI

Inline, where the student notices the error. With an exam filter active, each
topic row carries a small scope affordance — dimmed rows read "not on this exam ·
add", in-scope rows offer "remove". Each writes an `exam_topics` row with
`source='user'`. No separate editor screen in v1.

### 3.13 Quiz attribution: per question **[partly delegated]**

Each question's result credits the node that question tested, so a mixed-topic
quiz moves several subtopics correctly.

**This is a restructure of the submit path, not a lookup detail.** Today
`routes/quiz.py:2525–2572` makes exactly one `apply_graph_update` call, with one
`mastery_delta` from `mastery_after(before, score, total)`, against the attempt's
single `concept_node_id`. Per-question attribution turns that into N grouped
updates. **[delegated]** My decision:

1. **Store attribution at the grain where it happens.** Add a nullable
   `concept_node_id TEXT REFERENCES graph_nodes(id) ON DELETE SET NULL` to
   `quiz_responses`. `quiz_attempts.concept_node_id` keeps its current meaning —
   the concept the attempt was launched from — and stays the fallback when a
   question cannot be attributed.
2. **Resolve the name once, at answer time, then persist the id.** When
   `POST /api/quiz/attempts/{id}/answer` writes the response row, resolve that
   question's `concept_tested` against the course's node names and store the
   resulting id. Reuse the normalisation `apply_graph_update` already applies —
   the existing seam is itself name-based (`routes/quiz.py:2553–2556`), so this
   introduces no new matching rule, only an earlier and persisted one.
   Persisting is what makes it durable: a later rename or merge re-points the
   stored id (§3.11), where resolving on read would silently rot.
3. **Group by node at submit, then apply once per node.** Partition the
   attempt's responses by `concept_node_id` and emit one `updated_nodes` entry
   per distinct node in a **single** `apply_graph_update` call — the function
   already accepts a list, so the existing re-submit guard (`:2399`) and the
   one-write-per-submit property both survive unchanged.
4. **Per-node score, same model.** For node *n* with `cₙ` correct of `tₙ`
   questions, the delta is `mastery_after(beforeₙ, score=cₙ, total=tₙ) −
   beforeₙ`, reusing `services/quiz_config.py` untouched. The event type uses
   the existing ratio thresholds applied to `cₙ/tₙ`. Note the consequence: with
   one question on a node the ratio is only ever 0 or 1, so `quiz_partial` can
   no longer occur for single-question nodes. That is honest, not a bug, but the
   analytics that read `event_type` must expect the shifted distribution.
5. **`quiz_attempts.mastery_before` / `mastery_after` keep their current
   meaning** — the launched-from node's pair — because they are a single pair
   and cannot represent N nodes. The per-node numbers live in
   `node_mastery_events`, which is already the auditable record.
6. **A miss moves nothing, and is never silent.** An unresolved name routes
   through `services/tool_signals.py::report_empty_result`
   (`feature="quiz_attribution"`), per the project's silent-empty convention.
   The question is reported to the student as uncredited rather than credited to
   the wrong concept.
7. **Do not change the agent schema yet.** Adding `concept_node_id` to
   `QuizQuestion` touches `agents/quiz.py`, the E2E function handlers, and every
   fixture, for a correctness gain step 2 already delivers. The miss rate logged
   in step 6 is exactly the signal that decides whether it becomes worth it.

Mastery credit never propagates to parent topics. Topic figures are counts of
mastered children (§3.6), so there is nothing to double-count.

### 3.14 Entry point

- A **course node** (`subject_root`) on `/tree` navigates to the roadmap.
- A **concept node** keeps the existing detail panel (`Tree.tsx:299–362`)
  unchanged.
- Course nodes need a visual cue that they behave differently — a chevron or
  equivalent affordance on the node, decided during build.

### 3.15 Subtopic actions

Two buttons on every subtopic row: **Learn** and **Quiz**, mirroring the Tree
detail panel and reusing its existing routing helpers (`learnHrefForNode`,
`buildQuizHref`). Learn resumes the most recent session for that concept when one
exists, otherwise starts a new one. No hidden state machine.

### 3.16 First-run and empty states

| State | What renders |
| --- | --- |
| Concepts exist, no hierarchy | A flat, ungrouped list of the course's concepts with full mastery encoding and Learn/Quiz on each — immediately useful — plus a prominent **Organise into topics** action. |
| Hierarchy exists | The composed layout (§4). |
| No concepts at all | Pointer to upload documents or start a tutor session; no Organise button, since there is nothing to organise. |
| No exams recorded | Ring shows course readiness; no exam card, no stale markers (§3.7). |

### 3.17 The Organise flow: propose a diff, then apply

**Organise into topics** calls a new agent that reads the course's concept nodes
plus its syllabus and returns a **proposed grouping** — nothing is written yet.
The student sees "14 concepts → 4 topics" with each proposed topic expandable,
and accepts per topic or all at once. Only accepted groups are written, as
`part_of` and `prerequisite` edges through `apply_graph_update`.

Rejecting costs nothing, and the student's graph is never mutated by a background
pass they did not ask for. This matches the suggestion pattern the summary editor
already uses.

Re-proposing as new documents arrive is **deferred** — see §8.

---

## 4. Layout

```
┌─ BIOL 101 · Study Roadmap ──────────────┬──────────────────┐
│                                         │  READINESS       │
│ ▸ START HERE                            │   ╭────╮         │
│                                         │   │ 63%│ Midterm2│
│ ▼ Proteins & Nucleic Acids       ▮▮▮▯▯  │   ╰────╯ in 9d   │
│   ○ The Nucleus & Chromatin             │   why? ▸         │
│       ▰▰▰▰▱▱  Learn │ Quiz              │                  │
│   ◐ Ribosomes & Protein Synth   ·stale  │  SKILL BREAKDOWN │
│       ▰▰▰▰▰▰  Learn │ Quiz              │  Proteins        │
│   ● Peptide Bonds                       │   ▮▮▮▮▯▯▯  4/8   │
│       ▰▰▰▰▰▰  Learn │ Quiz              │  Cell Structure  │
│                                         │   ▮▮▯▯▯▯▯  2/6   │
│ ▶ Cell Structure & Organelles    ▮▮▯▯▯  │  Metabolism      │
│ ▶ Metabolism                     ▯▯▯▯▯  │   ▯▯▯▯▯▯▯  0/5   │
│ ▶ Unfiled concepts (3)                  │                  │
└─────────────────────────────────────────┴──────────────────┘
```

- **Main column** — ordered accordion. One row per subtopic, carrying the tier
  glyph, the name, the stale marker, the mastery bar, and Learn/Quiz. This is
  where the student acts.
- **Sidebar** — readiness ring with its "why?" link, then the skill breakdown:
  one segmented bar per topic with its count. This is where the student scans.
- Both views read from the same payload, so they cannot disagree. Segment fill
  and row glyph both come from `nodeStyle.ts` (§3.8).
- Below the breakdown: the syllabus card and the exam-dates card from reference 1.
  Selecting an exam there applies the overlay.

Responsive: below the sidebar breakpoint the ring moves to a compact header strip
above the accordion and the breakdown collapses into a disclosure, so the acting
surface keeps the full width.

---

## 5. Backend

New router `backend/routes/roadmap.py`, mounted at `/api/roadmap` in the
`main.py:150–169` block.

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/roadmap/{course_id}` | Topics, subtopics, unfiled, order, mastery, freshness, exams, readiness. Optional `?exam_id=`. |
| GET | `/api/roadmap/{course_id}/readiness` | The "why?" breakdown rows. Optional `?exam_id=`. |
| POST | `/api/roadmap/{course_id}/structure/propose` | Runs the structure agent; returns a proposal. Writes nothing. |
| POST | `/api/roadmap/{course_id}/structure/apply` | Writes the accepted groups via `apply_graph_update`. |
| PATCH | `/api/roadmap/nodes/{node_id}` | Rename and/or reparent. |
| DELETE | `/api/roadmap/nodes/{node_id}/parent` | Unfile (drops the `part_of` edge only). |
| POST | `/api/roadmap/merge` | `{survivor_id, merged_id}` → `graph_service.merge_nodes`. |
| PUT | `/api/roadmap/exams/{assignment_id}/topics` | Scope corrections; writes `source='user'` rows. |

Rules:

- All reads and writes go through `db/connection.py::table()`; graph mutations go
  through `graph_service`, never direct table writes.
- `require_self` on every route.
- Exam titles and notes are encrypted — read through `decrypt_if_present`, and
  `points_possible` through `decrypt_numeric`.
- Course and offering resolution goes through `services/academics.py`; the HTTP
  boundary keeps the abstract `course_id`.
- Any read that can return zero rows for a student who plausibly should have data
  routes through `report_empty_result`.

### Ordering and readiness live in one service

`backend/services/roadmap.py` owns the topological sort, the freshness function,
and the readiness formula. Pure functions over already-fetched rows, so they are
unit-testable without a database and the frontend never re-derives them.

### Caching

The GET routes use `services/http_cache.py::cached_json` with
`Cache-Control: private` — these payloads are user-scoped and app-decrypted and
must never reach a shared proxy. The ETag is built from cheap change-keys, not
the rendered body: `max(graph_nodes.updated/last_studied_at)`, node count, edge
count, `max(exam_topics.updated_at)`, and the selected `exam_id`.

### New agent

`backend/agents/roadmap_structure.py`, with its own slot in
`agents/_providers.py::model_for`. Because it is request-path, it needs a handler
registered in `agents/function_handlers_e2e.py` or the E2E lanes raise
`UnregisteredHandlerError`. Keep the handler constants, the spec assertions, and
`tests/test_e2e_function_handlers.py` in sync.

`agents/syllabus_extraction.py` is extended to emit exam→topic coverage; it is
already registered.

### Migrations

Append-only, UTC-timestamp-prefixed (`date -u +%Y%m%d%H%M%S`), per
`db/migrations/README.md`:

1. `…_exam_topics.sql` — the table in §3.3 plus indexes on
   `(user_id, assignment_id)` and `(user_id, node_id)`.
2. `…_quiz_responses_concept_node.sql` — the nullable `concept_node_id` column
   and its index (§3.13).

---

## 6. Frontend

- Route `src/app/(shell)/roadmap/[courseId]/page.tsx`, following the
  `gradebook/[courseId]` precedent.
- Screen `src/components/screens/Roadmap/` — `Roadmap.tsx`, `TopicAccordion.tsx`,
  `SubtopicRow.tsx`, `ReadinessRing.tsx`, `ReadinessBreakdown.tsx`,
  `SkillBreakdown.tsx`, `ExamCard.tsx`, `OrganiseProposal.tsx`, `MergeDialog.tsx`.
- Mastery visuals import from `src/lib/graph/nodeStyle.ts`. **No new colour or
  opacity constants.** A new tier glyph map is added to that same file so both
  surfaces share it.
- `Tree.tsx:299` changes from "select the root" to "navigate to the roadmap".
  Existing concept-node behaviour is untouched, so the current Tree tests should
  still pass apart from that one case.
- Testids follow `docs/frontend-testids.md` "Adding a surface".

---

## 7. Testing

- **Backend unit** — `tests/test_roadmap_service.py`: topological sort including
  a deliberate cycle, tie-break determinism, freshness at `d=0`, `d=D/2`, `d>D`,
  and no-exam `f=1.0`; the readiness formula against hand-computed values;
  `merge_nodes` against the UNIQUE edge collision, self-edge, and
  history-concatenation cases.
- **Backend route** — auth, encryption at the boundary, ETag and 304, and that a
  user-sourced `exam_topics` row survives a later agent pass.
- **Attribution** — a quiz whose question names an unknown concept credits
  nothing and emits the `report_empty_result` signal.
- **Frontend unit** — accordion ordering, the refused-drag dialog, glyph and
  opacity mapping against `nodeStyle.ts`, and the empty states in §3.16.
- **E2E** — `frontend/e2e/roadmap.spec.ts`: navigate from a course node, see
  topics in order, run a quiz, watch one subtopic's mastery and the ring move,
  then confirm the same change on `/tree`. Fixtures-based `test` from
  `support/fixtures.ts`; DB asserts through `support/db.ts`.
- Verify against the hermetic suite, the Playwright lane, and the oracles before
  merge. Serialize all local-stack use under the `flock` on
  `/tmp/claude-<uid>/sapling-e2e-stack.lock`, one invocation per whole
  up→test→down cycle.

---

## 8. Phasing

All four pieces ship; this is the order, each phase independently releasable.

| Phase | Contents | Gate |
| --- | --- | --- |
| **P1 — Read path** | Route, composed layout, topics from `part_of`, topological order, mastery grid on `nodeStyle.ts`, readiness ring and breakdown, flat-list and no-concept empty states, Tree entry point, caching. The Organise button is not yet rendered. | Useful on its own for any student whose graph already has structure. |
| **P2 — Structure proposals** | The `roadmap_structure` agent, the propose/apply endpoints, and the proposal UI. Lights up the Organise button. | Without this, existing users with flat graphs only ever see the flat list. Highest user-visible value after P1. |
| **P3 — Exam overlay** | `exam_topics`, syllabus-extraction exam coverage, the filter, exam-relative freshness and stale markers, inline scope correction. | Depends on new agent output that needs validating, so it follows the paths that do not. |
| **P4 — Structural edits** | Rename, reparent, refused-drag reorder with the prerequisite fix, unfile, and merge. | Merge is the most expensive single item in the spec and gates nothing else. |

Per-question attribution (§3.13) lands in **P1**, because the readiness figure is
wrong without it and the migration is small.

---

## 9. Risks

1. **Hierarchy quality.** The whole page is only as good as the `part_of` edges
   the structure agent proposes. P2's accept/reject loop is the mitigation, and
   the accept rate is the metric worth watching.
2. **Attribution miss rate.** If `QuizQuestion.concept` frequently fails to
   resolve to a node, mastery stops moving and the ring stalls. §3.13's logged
   signal is what tells us, and the fix is already identified.
3. **Two surfaces, one encoding.** The accordion and the sidebar draw the same
   data twice. Both must read from one payload and one style module; any
   divergence is a bug, not a design choice.
4. **Freshness changes with the filter.** The same subtopic can be stale for
   Friday's midterm and fresh for the final. This is correct but surprising, and
   the breakdown copy has to say so plainly.
5. **Mastery-writer change.** §3.5 stops tutor sessions moving mastery. Existing
   users will notice. Needs a clear in-product explanation of what raises the
   number now.
6. **Merge is destructive-adjacent.** It deletes a node. Every reference listed
   in §3.11 must be re-pointed, and the test for each belongs in the same PR.
7. **The submit path is hot and already guarded.** §3.13 rewrites the mastery
   application inside a route carrying an explicit re-submit guard, a streak
   bump, and background tasks. The one-call, grouped-updates shape in §3.13
   step 3 exists to keep every one of those properties; a version that loops
   `apply_graph_update` per node would break the guard and double-count streaks.
8. **`event_type` distribution shifts.** Per §3.13 step 4, `quiz_partial`
   becomes impossible for single-question nodes. Anything reading that column —
   analytics rollups, the tutor's view of past performance — should be checked
   before P1 ships.

---

## 10. Verification of this spec against the code

Re-checked on 2026-10-27 after the interview. Claims that held:

- `graph_nodes.updated_at` exists, so the §5 ETag change-key is available.
- `relationship_type` accepts `part_of`, `prerequisite`, `builds_on` (CHECK in
  0023), so §3.1 and §3.2 need no schema change.
- `services/academics.py` exposes `user_offering_ids_for_course` and
  `enrollment_id_for`, so resolving a `course_id` to the enrollments that own its
  exams is a solved path.
- `src/lib/graph/nodeStyle.ts` is a real shared module with `tierFor`,
  `shadeFor`, `TIER_OPACITY` and `opacityFor`, already mirrored by
  `e2e/graph.spec.ts`, so §3.8 is reuse rather than new work.
- `quiz_responses` carries `is_correct` and `answered_at`, which is exactly the
  freshness input §3.7 needs.

Claims that were **wrong and have been corrected**:

- *"The route already uses `QuizQuestion.concept` to award mastery."* It does
  not. `concept_tested` is stored in `questions_json` and never read for
  mastery; awarding is whole-attempt against `quiz_attempts.concept_node_id`.
  §3.13 was rewritten accordingly and is a larger change than first stated.
- *"Per-question attribution is a name-resolution detail."* It is a restructure
  of `routes/quiz.py`'s submit block, with consequences for `event_type`,
  `mastery_before`/`mastery_after`, and the re-submit guard. Now spelled out.
- *"Tutor mastery writes"* had no named target. They are
  `agents/tools/graph.py:156 update_mastery_tool`, which also writes negative
  deltas — which is what surfaced the §11 question.

## 11. Resolved: mastery and freshness are separate channels

**Settled 2026-10-27.** The high-water-mark rule governs **time only**.

- Freshness is what tracks time, and it is separate information — derived at
  read, stored nowhere, never written back into `mastery_score`.
- `mastery_score` responds to evidence in both directions.
  `MASTERY_DELTA_PER_WRONG = 0.02` stays; the tuned model in
  `services/quiz_config.py` is unchanged.
- What is removed is the *passive* lowering of mastery: no scheduled decay job,
  and no tutor-driven negative deltas once `update_mastery_tool` is retired
  (§3.5).

The practical test for any future change: if the number moved because the
student did something, it belongs in `mastery_score`; if it moved because the
calendar did, it belongs in freshness.

No open decisions remain in this spec.

## 12. Deferred

- Re-proposing structure as new documents arrive.
- A bulk "what's on this exam?" editor (v1 corrects inline only).
- Per-topic exam weights set by the student (`exam_topics.weight` exists and
  defaults to 1.0; nothing writes it yet).
- Adding `concept_node_id` to the `QuizQuestion` agent schema (§3.13 step 4).
- Pace-aware readiness — projecting where the student lands on exam day.
- Embedding a filtered mini-graph in the roadmap page.
- Reaching the roadmap from the dashboard and gradebook as well as `/tree`.
- Creating concepts from the roadmap.
