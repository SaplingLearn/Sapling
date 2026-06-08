# Sapling Roadmap

A working plan for the coming weeks and months. Sapling is a FastAPI + Supabase
backend that ingests student documents, runs them through an LLM to
classify/summarize/extract assignments, and serves a knowledge-graph-backed
tutoring chat to a React frontend.

_Last updated: 2026-06-08_

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

| Target          | Milestone                                                        |
| --------------- | ---------------------------------------------------------------- |
| End of June     | P0 data-exposure fixes shipped (#123/#124); doc pipeline refactored; semesters live (#142) |
| End of July     | `gemini_service` retired as primary LLM seam (#152 cutover #151) |
| End of August   | Graph-aware tutor end to end (#149); observability live          |
| End of September| Stable beta with real students                                  |

> Dates are targets, not commitments. Revisit this file at the start of each
> sprint and adjust scope before adjusting dates.
