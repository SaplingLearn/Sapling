# Sapling Roadmap

A working plan for the coming weeks and months. Sapling is a FastAPI + Supabase
backend that ingests student documents, runs them through an LLM to
classify/summarize/extract assignments, and serves a knowledge-graph-backed
tutoring chat to a React frontend.

_Last updated: 2026-06-24_

## Team & Responsibilities

| Person     | Role          | Owns                                                                 |
| ---------- | ------------- | ------------------------------------------------------------------- |
| **Jose**   | Frontend      | React app in `frontend/`, chat UI, knowledge-graph views, UX        |
| **Jack**   | AI Engineer   | LLM layer, Pydantic AI agent migration, prompts, extraction quality |
| **Luke**   | Backend       | FastAPI routes, Supabase data layer, auth, encryption, infra        |
| **Andres** | Fullstack     | Cross-cutting glue, integration, code review, unblocking, releases  |

---

## Issue tracking — tags & ownership

_Added 2026-06-08. All work is tracked as GitHub issues in `SaplingLearn/Sapling`._

### Title convention

Every issue title is prefixed with a priority tag, or `[EPIC]` for trackers. Domain and
type are carried by **labels**, not the title.

```text
[P0] <imperative summary>     [P1] …     [P2] …     [P3] …     [EPIC] <name>
```

### Priority tags

| Tag | Meaning | Response |
| --- | ------- | -------- |
| **P0** | Critical / blocker — data exposure, security, or a broken core flow | Drop everything; fix before new feature work |
| **P1** | High — significant bug or feature on the critical path | Land within the current sprint |
| **P2** | Medium — real bug or valued enhancement, not blocking | Scheduled into a sprint |
| **P3** | Low — polish, cleanup, nice-to-have | Opportunistic / good first issue |

### Type & domain labels

| Label | Meaning |
| ----- | ------- |
| `bug` / `enhancement` | Something broken / a new feature or improvement |
| `epic` | Tracking issue that groups related work |
| `frontend` | React app (`frontend/`) |
| `backend` | FastAPI routes, services, data layer (`backend/`) |
| `agents` | Pydantic AI agents / LLM layer (`backend/agents/`, `gemini_service`) |
| `security` | Data exposure, auth / IDOR, encryption boundaries |
| `accessibility` | WCAG / a11y |
| `design-debt` | Brand / design-system drift |
| `performance` | Runtime / bundle / query performance |
| `observability` | Logging, usage tracking & analytics |
| `infrastructure` | Deploy, staging, CI, migrations |
| `documentation` | Docs / audits |

### Ownership

Owner = the person accountable for the issue landing (they may delegate or pair). Maps to
the roles in the table above.

| Domain / label | Primary owner | Notes |
| -------------- | ------------- | ----- |
| `frontend`, `accessibility`, `design-debt` | **Jose** | All UI work, incl. the frontend UI audit (#113) |
| `backend`, `infrastructure`, backend `performance` | **Luke** | Routes, Supabase, auth, encryption, migrations, staging |
| `agents` + the LLM layer | **Jack** | Agent migration, prompts, extraction quality |
| `security` | **Luke** + **Andres** | Luke implements (auth / encryption); Andres signs off on the review |
| `observability` | **Luke** (backend/data) · **Jose** (dashboard UI) | Cohort #115–#122; the FE pieces (#121, #122) go to Jose |
| `documentation`, `epic` coordination | **Andres** | Audits, decision records, keeping this roadmap current |
| Cross-cutting / integration / releases | **Andres** | Unblocking, code review, merge coordination |

### Active epics

All work below is filed as GitHub issues and assigned. Counts as of 2026-06-08:
**Jose 20 · Jack 16 · Luke 14 · Andres 13.**

- **#113** — Frontend UI audit (10/20) — owner **Jose** — `docs/frontend-ui-audit.md`
- **#136** — Backend & contract bug audit (31 findings) — owner **Luke**, `agents` items
  (#125, #127) to **Jack** — `docs/backend-contract-bug-audit.md`
- **#142** — Semesters (view grades & classes by term) — backbone (#137/#138) to **Andres**,
  UI (#139/#140) to **Jose**
- **#152** — Agent migration (retire `gemini_service` as the LLM seam) — owner **Jack**
  (#143–#151 + hardening #153/#154)
- **Observability** cohort #115–#122 — **Luke** (data) · **Jack** (#118/#119) · **Jose** (#121/#122)
  · **Andres** (#117/#120) — `docs/observability-logging-tracking.md` _(no `[EPIC]` issue yet)_

> **P0s take precedence over the sprint plan below.** The backend audit surfaced two P0
> data-exposure bugs — #123 (calendar export IDOR, Luke) and #124 (realtime chat ciphertext,
> Andres) — that should be fixed before continuing feature work.

---

## Now → Next 2 Weeks (through ~2026-06-21)

Goal: ship the two P0 data-exposure fixes, then the first tranche of audit + feature work.
(The agents are already wired — the migration is now about retiring the remaining
`gemini_service` call sites, tracked under epic #152, not spiking new agents.)

- **Andres** — P0 #124 (realtime chat ciphertext, fullstack); start streaming chat #70 +
  SSE deltas #74; semesters DB migration #137. Plus the lint/format + CI baseline
  (the `# TODO` in CLAUDE.md — ruff + black) and reviewing the audit/migration PRs.
- **Luke** — P0 #123 (calendar IDOR) + encryption boundaries #126; refactor
  `routes/documents.py::_process_document` into discrete, testable steps (coordinate with
  #132 + Jack's #143); backend audit P1s #130/#134.
- **Jose** — frontend audit P0s #102/#103/#104; fix the Social page #131 (pairs with
  Andres's #124); notetaker data-loss #133.
- **Jack** — agent-migration kickoff: #143 (document classify agent) + #153 (output-retry
  hardening); fix #125 (cross-user doc leak) and #127 (tutor mastery tool + usage limits).

## Weeks 3–4 (~2026-06-22 → 2026-07-05)

Goal: feature surfaces off the Gemini seam; semesters shipped; pipeline hardening.

- **Jack** — Migration surfaces #144 (calendar extraction) / #145 (quiz + course-context)
  / #146 (flashcards) / #147 (remaining one-shots); extraction-accuracy eval harness #148.
- **Luke** — Perf/caching #97–#99 and staging env #100; calendar sync #61, Class-Intel
  write-gating #72; review OCR routing in `extraction_service.py` defaults (ties to #132).
- **Jose** — frontend audit P1s #105–#110; semesters UI #139 (gradebook switcher +
  transcript) / #140 (dashboard grouping + Archive).
- **Andres** — semesters API + GPA #138; document-pipeline robustness #132; integration
  testing across the migrated agents + frontend.

---

## July — Agent Migration

Goal: retire `gemini_service.py` as the primary LLM seam (epic #152).

- **Jack** — Final cutover #151 (remove `call_gemini*` + `gemini_service.py`, retire the
  ADR-0001 legacy chat fallback last); platform hardening #153/#154 (output retries +
  DBOS durability / crash-safe streaming).
- **Luke** — Quiz scoring & idempotency #129; session/scoring cleanup; data migrations as
  needed; remaining backend audit P2/P3 (#135).
- **Jose** — Quiz-taking UI and results; graph-driven study suggestions; frontend audit P2s
  #111/#112.
- **Andres** — Decision record in `docs/decisions/` for the migration cutover; performance
  pass; release coordination.

## August — Tutoring & Knowledge Graph Depth

Goal: make the tutor genuinely graph-aware.

- **Jack** — Graph-grounded tutor retrieval + tool-use loop #149 (depends on #127);
  graph/study-tools archive toggle #141.
- **Luke** — Scale the graph data model; query performance on
  `graph_nodes`/`graph_edges` (with #128); rate limiting and cost controls on LLM calls.
- **Jose** — Interactive graph navigation; per-concept mastery views.
- **Andres** — End-to-end QA; observability wrap-up #117/#120; beta feedback loop.

## September — Polish & Beta

Goal: a stable beta for real students.

- **Jack** — Quality tuning from real usage; prompt-injection hardening on
  student-supplied content #150.
- **Luke** — Production readiness: backups, monitoring, auth/security review,
  load testing.
- **Jose** — Accessibility, mobile/responsive pass, onboarding flow.
- **Andres** — Beta launch, bug triage, roadmap review for Q4.

---

## Cross-Cutting Tracks (ongoing, all)

- **Testing** — keep `pytest` green; new code ships with tests in
  `backend/tests/`.
- **Docs** — log architecture decisions in `docs/decisions/`, dead ends in
  `docs/attempts/`, keep `docs/architecture.md` current.
- **Security** — respect column-level encryption (`services/encryption.py`);
  encrypt at write, decrypt before AI prompts.
- **Conventions** — Supabase only via `db/connection.py::table()`; graph writes
  only via `apply_graph_update`; new LLM code as Pydantic AI agents.

## Milestones

| Target          | Milestone                                                        | Status |
| --------------- | ---------------------------------------------------------------- | ------ |
| End of June     | P0 data-exposure fixes shipped (#123/#124); doc pipeline refactored; semesters live (#142) | ✅ P0s shipped (#123/#124); semesters folded into the DB modular redesign (offering/term split, migrations 0019–0028) — validated on staging, awaiting `epic → main` cutover |
| End of July     | `gemini_service` retired as primary LLM seam (#152 cutover #151) | ⏳ on track |
| End of August   | Graph-aware tutor end to end (#149); observability live          | ⏳ |
| End of September| Stable beta with real students                                  | ⏳ |

> Dates are targets, not commitments. Revisit this file at the start of each
> sprint and adjust scope before adjusting dates.

---

## Shipped log

_Append-only. Newest first. Cite the work, not the file dumps._

### 2026-06-24 — DB modular redesign (epic, migrations 0019–0028)

The dominant work this window. A full target-schema sweep on
`epic/db-modular-redesign`, landed as eight reviewed domain slices and validated
end to end (full mocked suite green + 14/14 service checks against live staging).
Remaining step: deploy-to-staging smoke test, then the `epic → main` cutover.

- **Catalog / offering / term split** — the abstract `courses` table is now split
  into `courses` / `course_offerings` / `terms` with `enrollments`; the app is
  rewired onto it via the new `services/academics.py` resolver. This is where the
  long-standing **semesters (#142)** goal landed — term-scoped grades and classes
  fall out of the offering/term model. (`788e8df`, `34f3241`, `72443e9`, `c26ecf4`)
- **Identity split** — profile fields moved into `user_profiles`, `users` slimmed,
  with cross-domain `users.name` readers/writers reconciled after the split.
  (`310c4ac`, `16af571`)
- **Enrollment-keyed gradebook** — semester-aware gradebook on the enrollment-keyed
  schema (curve + drop-lowest). (`3c67fde`)
- **Offering-keyed analytics** — social / students repointed off the abstract
  `courses` table; study artifacts repointed onto the offering. (`736abc1`, `20e08bc`)
- **Knowledge-graph integrity** — UNIQUE-backed upserts + an append-only
  `node_mastery_events` log; graph writes still flow through `apply_graph_update`.
  (`10f4081`)
- **Ops cleanup** — text/uuid PKs on `feedback` / `issue_reports`; FK fixes
  (`0028` drops the vestigial `course_offerings.course_code NOT NULL`). (`d87313e`,
  `fc7ae87`)
- **Idempotent staging seed** — `db/seed_staging.py` builds a fake demo dataset on
  the new schema; `_exists_by` filters on the selected column (#258). (`0234ca3`,
  `703b5a7`)

### 2026-06-24 — Migration runner

Migrations moved into an ordered `db/migrations/` dir with an apply/baseline
runner + CLI on `psycopg` (#197); cosmetics FK constraints made idempotent (#196).
(`d13fe3b`, `977d8f6`, `b6a9080`, `3541cb9`)

### 2026-06-24 — Staging environment (#100)

Staging frontend Worker env (`wrangler.toml`, Phase 4) and a configurable
sign-in email-domain allowlist with staging templates. Staging is a separate
Supabase project with its own `ENCRYPTION_KEY`. (`df34f77`, `43c6bc6`)

### 2026-06-24 — Security wave (backend audit #136 P0/P1s)

Both P0 data-exposure bugs closed plus a wave of related hardening:
- **P0 #123** — calendar export scoped by `user_id` (cross-user IDOR closed),
  with write-filter defense-in-depth. (`488a201`, `0cb7589`)
- **P0 #124** — realtime chat now re-fetches room messages via decrypting REST so
  ciphertext is never displayed. (`d7e0586`, FE PR #230)
- **#125** cross-user doc leak (`search_course_materials` user-scoped, `59b2bac`);
  **#126** encryption boundaries (encrypt syllabus notes at write, decrypt
  gradebook/profile responses — `538478f`, `dae4179`); **#174** fail-closed config
  validation (`9a456e5`); **#182** OCR auth + size cap + rate limit (`ff1d670`);
  **#189/#190** profile-route gating + cookie-domain CSRF (`6437ca4`, `3e56d52`);
  **#198/#199** gate gemini-test, bound careers/newsletter (`f4344b9`, `5bd3cbe`);
  **#231** Phase 2a issue-screenshot upload routed through an auth-gated backend
  (`6d6226f`).

### 2026-06-24 — Frontend design + a11y waves; CI lint baseline

- **Design wave 2** — removed the Liquid Glass system for solid panel surfaces,
  consolidated brand greens into tokens, dropped fabricated hero stat cards
  (#102/#103/#104/#106/#112). (`871aa42`, `f69c6ca`, `c4cd2dd`)
- **A11y wave 2** — WCAG AA contrast on shared tokens, visible focus / accessible
  names / modal focus, neutral rarity text (#107/#108). (`40d476e`, `6112b9b`)
- **CI** — added the ruff lint ratchet + CI gate (#193/#194, `0f630d2`); frontend
  eslint bulk-suppressions baseline so the Frontend check passes (`a8fa5db`,
  `2369d8a`).
- **Notetaker data-loss #133** — debounced autosave is now flushed, not dropped
  (`5330b70`); plus social realtime correctness fixes (`a3d05c1`, `2d196cf`).
