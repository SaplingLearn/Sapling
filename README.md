# Sapling

An AI study companion that builds a live knowledge graph of what you know as you learn.

[![CI](https://github.com/SaplingLearn/Sapling/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/SaplingLearn/Sapling/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
![Python](https://img.shields.io/badge/-Python-3776AB?style=flat-square&logo=python&logoColor=white)
![TypeScript](https://img.shields.io/badge/TypeScript-3178C6?logo=typescript&logoColor=fff)
![Next.js](https://img.shields.io/badge/Next.js-000000?logo=nextdotjs&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)
![Supabase](https://img.shields.io/badge/Supabase-3FCF8E?logo=supabase&logoColor=fff)
![Claude](https://img.shields.io/badge/Claude-D97757?logo=anthropic&logoColor=white)

**Live site:** [saplinglearn.com](https://saplinglearn.com) · **Design:** [Figma file](https://www.figma.com/design/ToiUnUgkl5xMYvaLAqzXfr) with every desktop screen and state as clickable frames ([inventory](docs/figma/inventory/README.md))

[![Sapling landing page](docs/assets/landing.png)](docs/assets/landing.png)

## Contents

- [What Sapling does](#what-sapling-does)
- [Using Sapling](#using-sapling)
- [Features](#features)
- [Tech stack and architecture](#tech-stack-and-architecture)
- [Getting started](#getting-started)
- [Environment variables](#environment-variables)
- [Tests and CI](#tests-and-ci)
- [Repository layout](#repository-layout)
- [Contributing](#contributing)
- [Project docs](#project-docs)
- [Team](#team)
- [License](#license)

## What Sapling does

Students upload their course material (syllabi, lecture slides, notes, past exams). Sapling reads it, extracts the concepts, and grounds everything else in it: an AI tutor with three teaching modes, adaptive quizzes, flashcards, exam study guides, and a gradebook. Every session and quiz updates a per-student knowledge graph, so you can see what you have mastered and what still needs work.

Material uploaded by one student grounds the tutor and quizzes for everyone enrolled in the same course, so a class builds a shared, course-specific corpus instead of getting generic AI answers.

**Planning and tracking**

- Product scope (problem statement, MVP scope, success criteria): [Google Drive](https://drive.google.com/file/d/1sjQgW3obct6FgNlhzF1RXxDxDOU2VpNg/view?usp=sharing)
- Backlog with user stories and acceptance criteria: [Notion](https://app.notion.com/p/Sapling-3cd780cd9453802db54fe5a04ccf27a8)
- Ticket tracker, linked to the Notion backlog: [Canopy](https://canopy.saplinglearn.com/#tickets) (GitHub sign-in; open to repo collaborators)
- Code-level tasks: [GitHub Issues](https://github.com/SaplingLearn/Sapling/issues)

## Using Sapling

A typical first session, with screenshots from the app running on seeded demo data:

1. **Sign in and onboard.** Sign in with Google, then pick your school, major, year, and courses.
2. **Upload your course material.** In the **Library**, upload a syllabus or lecture PDF. Sapling streams its progress live ("Classifying...", "Extracting summary, concepts, and syllabus...", "Saved."), pulls assignments and deadlines into your calendar, and adds the concepts to your knowledge graph.
3. **Learn with the tutor.** Open **Tutor**, choose a concept, and pick a mode: *Socratic* (guided questions), *Expository* (direct explanation), or *Teach-back* (you explain, Sapling corrects). The side panel shows where the concept sits in your graph.
4. **Check yourself.** Take a **Quiz** that leans on your weakest concepts, or review **Flashcards** and rate each card Easy, Hard, or Forgot.
5. **Watch the graph grow.** The **Tree** view shows every concept across your courses. Nodes move up from Unexplored through Struggling and Learning to Mastered as you study; the **Mastery colors** toggle colors them by tier instead of by course.
6. **Prepare for exams.** Generate a **Study guide** for an upcoming exam from your uploaded material, and track your grade in **Grades**.

| Tutor | Quiz |
| --- | --- |
| ![AI tutor in Socratic mode with the concept graph beside the chat](frontend/public/gallery/shot-learn.png) | ![Adaptive quiz](frontend/public/gallery/shot-quiz.png) |
| **Knowledge graph** | **Library** |
| ![Knowledge graph tree view](frontend/public/gallery/shot-tree.png) | ![Document library](frontend/public/gallery/shot-library.png) |
| **Study guide** | **Gradebook** |
| ![Exam study guide](frontend/public/gallery/shot-guide.png) | ![Gradebook](frontend/public/gallery/shot-gradebook.png) |
| **Notetaker** | **Study rooms** |
| ![Notetaker](frontend/public/gallery/shot-notetaker.png) | ![Study rooms](frontend/public/gallery/shot-social.png) |

More screens (calendar, planner, achievements, study hub) are in [`frontend/public/gallery/`](frontend/public/gallery/). To regenerate them from a local stack, run `make gallery-shots`.

## Features

- **Dashboard:** a Today's plan built from your sessions, weak concepts, and upcoming deadlines, which ticks items off as you do them.
- **Live knowledge graph:** a 2D force-directed graph (d3-force) of every concept you've touched, colored by course and shaded by mastery, with a "Mastery colors" mode that colors nodes by tier. Updates after every session and quiz.
- **AI tutor:** Socratic, Expository, and Teach-back modes, grounded in your course's uploaded material (retrieval-augmented). Renders math (KaTeX), Mermaid diagrams, function plots, and theorem callouts.
- **Adaptive quizzes:** questions aimed at your weakest concepts and at common class misconceptions, in multiple-choice, short-answer, numeric, symbolic, or mixed format (each with its own answer input), at Easy, Medium, Hard, or Adaptive difficulty. A clickable question pager jumps between questions, and the generator is told which questions you've recently seen so it avoids repeating them.
- **Flashcards:** generate a deck from your weakest concepts, or import from pasted text, a file (CSV, TSV, TXT, JSON, Excel, or Anki `.apkg`), a URL, an AI prompt, or a photo. Rate cards Easy / Hard / Forgot (ratings are recorded; there is no review schedule yet).
- **Document library:** upload PDF, DOCX, or PPTX files up to 100 MB. Sapling extracts summaries, concept notes, and syllabus data, with OCR for scanned pages.
- **Study guides:** exam guides generated from your course material, cached per exam and regenerable.
- **Gradebook and Gradescope sync:** categories, weights, letter scales, and a current-grade calculation. Syllabus upload fills in categories and assignments. Optional Gradescope import, including BU SSO + Duo sign-in.
- **Calendar:** assignments and deadlines extracted from your syllabus.
- **Notetaker:** typed notes per course with autosave. Per note: AI summary, concept extraction into your graph, a note-grounded chat, send-to-tutor, and a quiz on the note's weakest concept.
- **Study rooms:** join by invite or browse public rooms, chat with replies and reactions, see the room's mastery on the concepts you share, and get matched with partners who are strong where you are weak.
- **Class intelligence:** an anonymized, per-class rollup of common misconceptions. It has no screen of its own; quiz generation uses it to write the wrong answers.
- **Profiles, achievements, and cosmetics:** milestones, avatar frames, name colors, and title flairs.
- **XP and leaderboard:** levels from XP, plus a weekly leaderboard (everyone, friends, or school) on the Achievements page.
- **Course planner:** a placeholder page today ("Coming soon"); semester planning is not built yet.
- **Waitlist and email:** students outside the allowlist can join a waitlist from the pending page; welcome and approval emails go out through Resend, with one-click unsubscribe.
- **Admin panel:** role-based access, user approval, feature flags (global or per student), usage analytics, and the job queue.
- **Admin tools:** seed, wipe, or copy a test account's study data; per-user daily LLM token budgets; and email broadcasts with preview and test sends.

## Tech stack and architecture

| Layer | Technology |
| --- | --- |
| Frontend | Next.js 16 (App Router, TypeScript), D3.js for the graph, Vitest + React Testing Library |
| Backend | FastAPI (Python 3.13), Pydantic AI agents for every LLM call. A Postgres-backed job queue (`python -m worker`) runs uploads, indexing, and Gradescope sync off the request path when the `jobs_queue` flag is on. |
| AI | Anthropic Claude for all agents by default (`claude-haiku-5-5` for extraction/quiz/notes, `claude-sonnet-5-5` for the tutor; [ADR 0030](docs/decisions/0030-swap-the-agents-llm-provider-from-gemini-to-anthropic-claude.md)). Google Gemini serves RAG embeddings, and any agent can be pointed back at a `gemini-*` model per task via `SAPLING_MODEL_<TASK>`. |
| Database | Supabase (PostgreSQL + pgvector), accessed through PostgREST with the service role. Row Level Security locks the public anon key out of the tables. |
| Security | Google OAuth, HMAC-signed session cookies, AES-256-GCM column encryption for PII and student content. See [SECURITY.md](SECURITY.md). |
| Streaming | Server-Sent Events (`sse-starlette`) for upload progress and the streaming tutor |
| OCR | Docling, with GOT-OCR 2.0 and Tesseract fallbacks |
| Observability | Logfire traces (with a scrubber that strips student content before export), optional PostHog analytics ([ADR 0028](docs/decisions/0028-posthog-alongside-in-house-analytics.md)), feature flags ([ADR 0029](docs/decisions/0029-feature-flags.md)) |
| Deploy | Frontend on Cloudflare Workers (`@opennextjs/cloudflare`). Backend API and job worker on Railway. Separate staging and production environments. |

```mermaid
flowchart LR
    U[Browser] --> FE["Next.js frontend<br/>(Cloudflare Workers)"]
    FE -->|"/api/* rewrite"| BE["FastAPI backend<br/>(Railway)"]
    U -->|"realtime room chat"| SB
    BE -->|PostgREST| SB[("Supabase Postgres")]
    BE -->|"enqueue jobs"| SB
    WK["Job worker<br/>(python -m worker)"] -->|"claim jobs"| SB
    BE --> AG["Pydantic AI agents"]
    AG --> CL["Anthropic Claude"]
    AG --> GE["Gemini embeddings"]
    BE --> GO["Google OAuth"]
    BE -.optional.-> GS["Gradescope"]
    BE -.optional.-> LF["Logfire"]
    BE -.optional.-> RD[("Redis cache")]
```

Request paths, the data model, and known sharp edges are in [`docs/architecture.md`](docs/architecture.md). The full route list is in [`docs/api.md`](docs/api.md), and the running backend serves interactive OpenAPI docs at `http://localhost:5000/docs`.

## Getting started

### Prerequisites

- **Python 3.13** (what CI, the Dockerfile, and `requirements.lock` use)
- **Node.js 22** with npm 10.9.x. The frontend enforces the npm version with `engine-strict` (see `frontend/.nvmrc` and `frontend/.npmrc`); on a newer npm run `npm install -g npm@10.9.2`.
- **API keys:** an [Anthropic API key](https://console.anthropic.com/) and a [Gemini API key](https://aistudio.google.com/apikey). The backend refuses to start without both.
- **Google OAuth client** (Google sign-in is the only login path). Add `http://localhost:5000/api/auth/google/callback` as an authorized redirect URI.
- **A database:** either a local Supabase stack via the Supabase CLI and Docker or Podman (Option A), or your own hosted Supabase project (Option B).

| Service | Used for | Needed locally? |
| --- | --- | --- |
| Anthropic API | Tutor, quizzes, document extraction, notes | Yes |
| Google Gemini API | RAG embeddings | Yes |
| Supabase | Postgres database, realtime room chat | Yes (local stack or hosted) |
| Google Cloud OAuth client | Sign-in, Calendar | Yes, to sign in |
| Logfire, PostHog, Redis, Gradescope | Tracing, analytics, cache, grade sync | Optional |
| Railway, Cloudflare | Hosting | No (deploy only) |

### 1. Clone

```bash
git clone https://github.com/SaplingLearn/Sapling.git
cd Sapling
```

### 2. Start a database

**Option A: local Supabase (recommended).** Follow [`docs/local-supabase.md`](docs/local-supabase.md) to start the stack (`supabase start`) and apply migrations. Its scripts run through `backend/venv`, so do the venv and `pip install` from step 3 first. The `*.env.local.example` templates are already wired to it.

**Option B: your own Supabase project.** Use the `.env.example` templates instead. In `backend/.env` set `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `ENCRYPTION_KEY`, `SUPABASE_DB_URL` (the session-mode pooler URI), and either `APP_ENV=local` or a 32+ byte `SESSION_SECRET` (the template defaults to `APP_ENV=production`, which refuses to start without one). Then create the schema with `python -m db.migrate` from `backend/` once step 3's install is done.

### 3. Run the backend

```bash
cd backend
python -m venv venv
source venv/bin/activate              # Windows PowerShell: venv\Scripts\Activate.ps1
pip install -r requirements.txt
cp .env.local.example .env            # Option B: cp .env.example .env
# Fill in ANTHROPIC_API_KEY, GEMINI_API_KEY, GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET
python main.py                        # http://localhost:5000  (API docs at /docs)
```

Optional extras: `pip install -r requirements-worker.txt` for Docling/torch OCR of scanned PDFs, and `playwright install chromium` for Gradescope BU SSO sync.

**Job worker:** the `jobs_queue` feature flag (off by default) moves uploads, document indexing, and Gradescope sync onto a Postgres job queue. If you turn it on, also run `python -m worker` from `backend/` (same venv and `.env`) in a second terminal. Without a worker, uploads and syncs fall back to running inline after a short wait, and other queued work waits.

### 4. Run the frontend

```bash
cd frontend
npm ci
cp .env.local.example .env.local      # Option B: cp .env.example .env.local
npm run dev                           # http://localhost:3000
```

Open http://localhost:3000 and sign in with Google.

### Or run everything with Docker

Docker Compose works with a hosted Supabase project (Option B) only: inside a container, `127.0.0.1` is the container itself, so it cannot reach a local Supabase stack. Fill in `backend/.env`, put the frontend variables in `frontend/.env` (Compose reads that file, not `.env.local`), export `ENCRYPTION_KEY` in your shell (Compose passes it through and would otherwise blank it), then:

```bash
docker compose up
```

### Troubleshooting

- **`RuntimeError: Missing required configuration`** on backend start: a required key in `backend/.env` is empty. The message names it.
- **401 after Google sign-in succeeds:** `SESSION_SECRET` differs between `backend/.env` and `frontend/.env.local`. They must match.
- **`npm ci` fails with `EBADENGINE`:** you're not on npm 10.9. Run `nvm use` in `frontend/`, then `npm install -g npm@10.9.2`.
- **Backend tests fail in `test_extraction_backends`, `test_docling_integration`, or `test_ocr_pipeline`:** those need the OCR stack (`requirements-worker.txt`) and network access. Use the command under [Tests and CI](#tests-and-ci), which skips them like CI does.

Setup last verified from a fresh clone on 2026-11-09 (Python 3.13, Node 22, npm 10.9): backend install, boot, and test suite; frontend `npm ci`, typecheck, lint, and `npm run build`. Docker Compose and the local Supabase stack were not re-run that day.

## Environment variables

Copy the example files as described above. The job worker (`python -m worker`, from `backend/`) reads the same `backend/.env`. Never commit real `.env` files; only the `*.example` templates are tracked. Each template documents its variables inline. These are the ones you will touch most:

**`backend/.env`**

| Variable | Required | Description |
| --- | --- | --- |
| `ANTHROPIC_API_KEY` | Yes | Anthropic key. Every agent runs on Claude by default. |
| `GEMINI_API_KEY` | Yes | Gemini key. Used for RAG embeddings and any agent slot pointed at a `gemini-*` model. |
| `SUPABASE_URL` | Yes | Supabase project URL |
| `SUPABASE_SERVICE_KEY` | Yes | Supabase service role key |
| `ENCRYPTION_KEY` | Yes | AES-256-GCM key, 64 hex chars. Generate with `python -c "import secrets; print(secrets.token_hex(32))"` |
| `SESSION_SECRET` | Outside local dev | HMAC secret for session tokens (32+ bytes). Must match the frontend. |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | To sign in | Google OAuth client |
| `GOOGLE_AUTH_REDIRECT_URI` | | Sign-in callback (default `http://localhost:5000/api/auth/google/callback`) |
| `GOOGLE_REDIRECT_URI` | | Calendar callback (default `http://localhost:5000/api/calendar/callback`) |
| `APP_ENV` | | `local` for development (relaxes `SESSION_SECRET`), `staging`, or `production` (default, fail-closed) |
| `PORT` / `FRONTEND_URL` | | Backend port (default `5000`) and allowed CORS origin (default `http://localhost:3000`) |
| `ALLOWED_EMAIL_DOMAINS` | | Comma-separated sign-in allowlist (default `bu.edu`; empty allows any domain) |
| `SUPABASE_DB_URL` | For migrations | Session-mode pooler URI (port 5432). Used only by `python -m db.migrate`. |
| `SAPLING_MODEL_<TASK>` | | Per-agent model override, e.g. `SAPLING_MODEL_CHAT_TUTOR=claude-sonnet-5-5`. One per agent task (`CLASSIFIER`, `SUMMARY`, `QUIZ`, `CHAT_TUTOR`, `STUDY_GUIDE`, `FLASHCARD`, ...); the full list and defaults are `_DEFAULTS` in `backend/agents/_providers.py`. |
| `OCR_ENGINE` | | `docling` (default), `auto` (adds GOT-OCR for math), or `tesseract` |
| `GOT_OCR_ENABLED`, `GEMINI_VISION_OCR_ENABLED`, `GEMINI_VISION_OCR_MAX_PAGES` | | OCR fallbacks for handwriting/math and scanned pages |
| `LOGFIRE_TOKEN`, `POSTHOG_PROJECT_TOKEN`, `REDIS_URL` | | Optional tracing, analytics, and cross-worker cache. Unset means off. |
| `RESEND_API_KEY` | | Optional. Sends welcome, waitlist-approval, and broadcast email through Resend. Unset records the email as skipped and sends nothing. |

**`frontend/.env.local`**

| Variable | Required | Description |
| --- | --- | --- |
| `BACKEND_URL` | Yes | Backend origin for the `/api/*` rewrite (locally `http://localhost:5000`) |
| `SESSION_SECRET` | Yes | Same value as the backend |
| `NEXT_PUBLIC_SUPABASE_URL` / `NEXT_PUBLIC_SUPABASE_ANON_KEY` | Yes | Supabase realtime for study-room chat |
| `NEXT_PUBLIC_API_URL` | | Leave empty so API calls stay same-origin |
| `NEXT_PUBLIC_POSTHOG_KEY` | | Optional product analytics |

## Tests and CI

**Backend:** pytest with mocked Supabase and LLM calls, plus ruff.

```bash
cd backend
python -m pytest tests/ -q --ignore=tests/evals \
  --ignore=tests/test_docling_integration.py \
  --ignore=tests/test_ocr_pipeline.py \
  --ignore=tests/test_extraction_backends.py
ruff check .
lint-imports                          # import-boundary contracts (backend/.importlinter)
```

The three ignored files need the heavy OCR stack and network access; CI skips them too.

**Frontend:** Vitest. Logic tests run in node; component tests use jsdom + React Testing Library.

```bash
cd frontend
npm run lint
npm run typecheck
npm test
```

**Agent evals:** accuracy checks for the LLM agents, replayed offline from recorded cassettes and gated against committed baselines. See [`backend/tests/evals/README.md`](backend/tests/evals/README.md).

```bash
cd backend
python tests/evals/run_all.py
```

**CI/CD** (GitHub Actions, `.github/workflows/`):

| Workflow | Runs | What it checks |
| --- | --- | --- |
| `CI` | Every PR and push to `main` | Backend pytest + ruff (from the hash-pinned `requirements.lock`, including a code-size ratchet test), frontend eslint + typecheck + vitest |
| `PR hygiene` | Every PR | A type (Conventional Commits title or `type/` branch) and filled-in acceptance criteria; warns on a `feat`/`fix` PR with no user story; adds a type label |
| `integration (local supabase)` | PRs and pushes to `main` | Backend against a real local Supabase stack |
| `e2e (browser lane)` | Pushes to `main`, manual | Playwright end-to-end tests against the full stack |
| `Evals` | PRs touching agents | Offline agent eval harness |
| `Migrate (staging)` | Pushes to `main` that add migrations | Applies new migrations to staging |
| `CodeQL` (GitHub code scanning) | PRs and pushes to `main` | Static security analysis of the Python and JavaScript/TypeScript code |
| `loadtest` | Manual, and nightly when `LOADTEST_TARGET_URL` is set | Locust load test against a deployed backend, gated on p95 latency |

Deploys: the frontend is built and deployed by Cloudflare Workers Builds on push. Production releases go through `make promote` (preflight, backup, migrate, merge `main` into `production`, verify). See [`backend/promotion/README.md`](backend/promotion/README.md).

## Repository layout

```
Sapling/
├── backend/                FastAPI app
│   ├── main.py             App setup and router mounts
│   ├── routes/             HTTP endpoints, one module per area (learn, quiz, documents, ...)
│   ├── services/           Business logic (graph, RAG, encryption, academics, ...)
│   ├── agents/             Pydantic AI agents; model routing in _providers.py
│   ├── db/                 connection.py (the only Supabase entry point), migrations/, migrate.py
│   ├── worker/             Background job worker (uploads, indexing, Gradescope sync)
│   └── tests/              pytest suite, fixtures in conftest.py, evals/
├── frontend/               Next.js app
│   └── src/
│       ├── app/            Routes (App Router)
│       ├── components/     UI, grouped by responsibility
│       └── lib/            API client, SSE consumer, shared types
├── supabase/               Local Supabase stack config
├── docs/                   Architecture, ADRs, API reference, runbooks
│   ├── assets/             Images used by this README
│   ├── audits/             Point-in-time frontend and backend audits
│   └── design/             Design docs for cross-cutting changes
├── specs/                  Feature specs referenced by code and CI
├── scripts/                Local stack, E2E, and screenshot scripts
├── loadtest/               Locust load tests
├── .github/                CI workflows, PR and issue templates
├── Makefile                E2E, screenshot, promotion, and backup shortcuts
└── docker-compose.yml      Backend + frontend containers
```

## Contributing

Read [CONTRIBUTING.md](CONTRIBUTING.md) before opening a PR. In short:

- One branch per issue, named `<type>/<short-name>` (`feat/quiz-pager`, `fix/graph-links`).
- Conventional Commit messages and PR titles: `type(scope): subject`.
- Every ready PR fills in acceptance criteria; `feat` and `fix` PRs add a user story, and UI changes add screenshots (the PR template has the sections).
- A teammate approves every PR and CI passes before it merges (merge commit or squash).

Conventions that keep the codebase consistent:

- All Supabase access goes through `backend/db/connection.py::table()`.
- Schema changes are new migrations in `backend/db/migrations/` (UTC timestamp prefix). Never edit an applied one or run DDL in the dashboard. See [`backend/db/migrations/README.md`](backend/db/migrations/README.md).
- Every LLM call is a Pydantic AI agent under `backend/agents/`.
- Sensitive columns are encrypted. Use the helpers in `backend/services/encryption.py` at read and write boundaries.

## Project docs

- [`docs/architecture.md`](docs/architecture.md): current system overview
- [`docs/api.md`](docs/api.md): the main backend routes, plus a complete route index
- [`docs/decisions/`](docs/decisions/): Architectural Decision Records (30 so far), append-only
- [`docs/attempts/`](docs/attempts/): things that didn't work, and what to try next
- [`docs/local-supabase.md`](docs/local-supabase.md): local database setup
- [`docs/e2e-exploration.md`](docs/e2e-exploration.md): the Playwright E2E lane and its oracles
- [`docs/program.md`](docs/program.md): state of the cleanup-and-hardening program
- [`docs/design/`](docs/design/) and [`docs/audits/`](docs/audits/): design docs and point-in-time audits
- [`docs/staging/`](docs/staging/), [`docs/deploy/`](docs/deploy/), [`docs/releases/`](docs/releases/): environments, deploys, and release plans
- [`docs/security/`](docs/security/) and [SECURITY.md](SECURITY.md): security controls and how to report a vulnerability
- [`docs/README.md`](docs/README.md): index of everything else in `docs/`

## Team

Built in Boston University's XC 475 Spark! Innovation Program (Fall 2026).

| Name | Role | GitHub |
| --- | --- | --- |
| Andres Lopez | CEO, engineering | [@AndresL230](https://github.com/AndresL230) |
| Jack He | Engineering | [@Darkest-Teddy](https://github.com/Darkest-Teddy) |
| Luke Cooper | Engineering | [@lpcooper-arch](https://github.com/lpcooper-arch) |
| Jose Gael Cruz-Lopez | Engineering | [@Jose-Gael-Cruz-Lopez](https://github.com/Jose-Gael-Cruz-Lopez) |
| Azaria Gonzales | Design | [@azariagonzales89](https://github.com/azariagonzales89) |
| Aerim Lee | Design | [@alee7-7](https://github.com/alee7-7) |
| Brady | Mentor | |
| Ziba Cranmer | Instructor | |
| James Grady | Instructor | |

## License

[MIT](LICENSE) © 2026 Andres Lopez, Jack He, Luke Cooper, and Jose Gael Cruz-Lopez

The MIT license covers the code in this repository. It does not cover the Gummi heading font (`frontend/src/app/fonts/Gummi-*`), which is a commercially licensed third-party font that may not be redistributed; its terms are in [`frontend/src/app/fonts/Gummi-LICENSE.md`](frontend/src/app/fonts/Gummi-LICENSE.md).
