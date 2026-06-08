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

- **#113** — Frontend UI audit (10/20) — owner **Jose** — `docs/frontend-ui-audit.md`
- **#136** — Backend & contract bug audit (31 findings) — owner **Luke**, with the `agents`
  items (#125, #127) to **Jack** — `docs/backend-contract-bug-audit.md`
- **Observability** cohort #115–#122 — owner **Luke**; dashboard UI to **Jose** —
  `docs/observability-logging-tracking.md` _(no `[EPIC]` issue yet — consider opening one for parity)_

> **P0s take precedence over the sprint plan below.** The backend audit surfaced two P0
> data-exposure bugs — #123 (calendar export IDOR) and #124 (realtime chat ciphertext) —
> that should be fixed before continuing feature work.

---

## Now → Next 2 Weeks (through ~2026-06-21)

Goal: stabilize the document pipeline and lay the groundwork for the agent migration.

- **Jack** — Build on the existing notetaker agents (`note_summary`,
  `note_concepts`, `note_chat` in `backend/agents/`). Extend the same
  Pydantic AI pattern to the document pipeline: spike a classify agent behind
  the existing `gemini_service` seam so it can be swapped without route changes.
  Keep model slots centralized in `agents/_providers.py`.
- **Luke** — Refactor `routes/documents.py::_process_document` (the single-call
  classify/summarize/extract) into discrete, testable steps. Backfill tests in
  `backend/tests/`.
- **Jose** — Polish the tutoring chat (SSE streaming) and the notetaker UI;
  surface document processing status to the user. Tighten loading/error states.
- **Andres** — Set up a lint/format baseline (the `# TODO` in CLAUDE.md — pick
  ruff + black), wire CI, and review the agent-seam and refactor PRs.

## Weeks 3–4 (~2026-06-22 → 2026-07-05)

Goal: first real agent in production path; pipeline hardening.

- **Jack** — Migrate the classify step fully to a Pydantic AI agent; begin the
  summarize agent. Make `apply_graph_update` callable as an agent tool.
- **Luke** — Harden `upload_document` upload pipeline; review OCR engine routing
  in `extraction_service.py` (Docling / GOT-OCR / Tesseract) and pick sane
  defaults. Verify encryption boundaries on all sensitive columns.
- **Jose** — Knowledge-graph visualization improvements; reflect extracted
  assignments and concepts in the UI.
- **Andres** — Integration testing across the new agent + frontend; keep the
  Gemini fallback path working during migration.

---

## July — Agent Migration

Goal: retire `gemini_service.py` as the primary LLM seam.

- **Jack** — Summarize + extract agents live; consolidate prompts; add eval
  harness for extraction accuracy. Deprecate `call_gemini*` helpers.
- **Luke** — Quiz endpoints (`routes/quiz.py`) move onto the agent layer;
  session/scoring cleanup. Data migrations as needed.
- **Jose** — Quiz-taking UI and results; graph-driven study suggestions.
- **Andres** — Decision records in `docs/decisions/` for the migration;
  performance pass; release coordination.

## August — Tutoring & Knowledge Graph Depth

Goal: make the tutor genuinely graph-aware.

- **Jack** — Graph-grounded retrieval for the tutor system prompt
  (`build_system_prompt`); tool-use loop for on-the-fly graph updates.
- **Luke** — Scale the graph data model; query performance on
  `graph_nodes`/`graph_edges`; rate limiting and cost controls on LLM calls.
- **Jose** — Interactive graph navigation; per-concept mastery views.
- **Andres** — End-to-end QA, telemetry/observability, beta feedback loop.

## September — Polish & Beta

Goal: a stable beta for real students.

- **Jack** — Quality tuning from real usage; guardrails and prompt-injection
  hardening on student-supplied content.
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

| Target          | Milestone                                              |
| --------------- | ------------------------------------------------------ |
| End of June     | Document pipeline refactored; first agent in path      |
| End of July     | `gemini_service` retired as primary LLM seam           |
| End of August   | Graph-aware tutor end to end                           |
| End of September| Stable beta with real students                         |

> Dates are targets, not commitments. Revisit this file at the start of each
> sprint and adjust scope before adjusting dates.
