# Architecture hardening plan

As of 2026-11-08. Tracked in Trov (org `saplinglearn`): sprint #28, tickets #114 to #119. The code is well tested and documented, but one process does everything and authorization lived only in route code. This plan fixes both in six phases, about 12 weeks for 1 to 2 engineers part-time.

## Where it stands

Next.js on Cloudflare Workers calls a single FastAPI container on Railway, which reads and writes Supabase Postgres with the service-role key.

Keep: the single LLM chokepoint (`agents/_providers.py`) with function mode and evals; about 3,760 backend and 1,810 frontend tests with integration, e2e and CodeQL lanes; 30 ADRs; `X-Request-ID` idempotency; correlation IDs; feature flags; the promotion runner; AES-256-GCM column encryption.

## Main risks, ranked

| # | Risk | Evidence | Cost |
| --- | --- | --- | --- |
| 1 | Authorization only in app code | Service-role key bypasses RLS; `user_id` filters repeated across ~200 endpoints. (Step 1, #807, closed the anon-key exposure.) | One missed filter leaks another student's data |
| 2 | One process does everything | API container also runs torch/Docling OCR, Chromium for Gradescope SSO, the index sweeper; one uvicorn process | A big PDF slows chat for everyone; one crash takes everything down |
| 3 | Blocking I/O | ~410 sync route handlers; sync `httpx.Client`, 30 s timeout | Capacity tops out early |
| 4 | Slow work on the request path | Upload pipeline and course-context aggregation run inline; DBOS off | Provider blips become 502s; deploys kill in-flight work |
| 5 | In-process state | Rate limiter and flag cache in memory | Blocks a second instance |
| 6 | Logic in routes | `quiz.py` 2,220 lines, `learn.py` 1,657; 12 functions above complexity 30 | Slow, risky changes |
| 7 | Config drift, CVEs, no backups | Railway settings only in the UI; dependency advisories (#808); Supabase Free plan has no backups or PITR | Drift, exposed CVEs, no rollback |

## Target architecture

- **API service:** FastAPI, fully async, stateless, 2+ replicas. Auth, CRUD, chat streaming. Enqueues slow work.
- **Worker service (new):** Docling/OCR, Gradescope (Chromium), RAG indexing, course context, achievements. Only this image carries torch and Chromium.
- **Supabase Postgres:** RLS on every table with real policies, a `jobs` table claimed with `SKIP LOCKED`, rate limits, usage, flags, backups.
- **LLM gateway (`agents/_providers.py`):** retries, timeouts, circuit breaker, cross-provider fallback, per-user token budget.

## Phases

| Phase | Weeks | Ticket | Done when | Status (2026-11-09, `main`) |
| --- | --- | --- | --- | --- |
| 0. Hygiene: CVEs, Railway config in repo, backups | 1 | #114 | No critical/high prod advisories; a restore has been tested | Code shipped: CVE upgrades (#808), `pg_dump` before every promote (#810), `.railway/railway.ts` (#836, unapplied). Open: paid plan / PITR decision. |
| 1. Authorization in the database (`docs/security/rls-step2-plan.md`) | 2 to 4 | #115 | Every table has policies; cross-user matrix runs in CI | Code shipped (waves 1–2): RLS policies, the matrix in CI, `db_user_scope` and `realtime_rls` (flags off). Open: the step 2d signing key, then the flag rollouts. |
| 2. Job queue and worker service | 3 to 6 | #116 | API image has no torch/Chromium; a 50-page PDF upload doesn't move chat latency | Code shipped (waves 1–3): `jobs` queue, `python -m worker`, uploads, indexing, Gradescope and course context on it behind `jobs_queue`; `api`/`worker` image targets. Open: the Railway worker service, the flag rollout, the API image cut-over. |
| 3. Async, stateless API on 2 replicas | 5 to 8 | #117 | 2 replicas serve prod; nightly load test meets targets | Code shipped (#839, #850): async DB seam, sync-DB-on-loop allowlist empty, `stateless_*` flags, nightly load test. Open (human): the flags on, `API_REPLICAS = 2`, the `LOADTEST_TARGET_URL` variable. |
| 4. Domain modules | 7 to 10 | #118 | No route file over 600 lines; no function over complexity 25 | **Met** (#840, #851): the code-size baseline is empty; import-linter contracts in CI. Open: drop the re-export shims, lower `max-complexity` in steps. |
| 5. LLM resilience and cost | 9 to 12 | #119 | A forced provider outage in staging falls back with no user-facing errors | Code shipped (#814, #838): retries, timeouts, breaker, `llm_fallback`, `llm_budget`, cost signal, `llm_outage_drill`. Open: the staging drill itself. |

None of it is on production yet: prod still runs `6ed0f13c`, and one promote ships waves 1–4 (`docs/releases/2026-11-architecture-hardening-wave3.md`).

Phase 4's target layout, split order and the ratchet that holds both numbers until then: `docs/design/domain-modules.md`.

## What not to do

- No microservices or Kubernetes.
- No Redis, Kafka or Celery until metrics show Postgres can't carry it.
- Don't run DBOS and a jobs table side by side (ADR 0011 keeps DBOS off).
- No big-bang ORM or framework rewrite; convert router by router behind `table()`.

## Targets

| Measure | Target | Source |
| --- | --- | --- |
| API availability | 99.5% monthly | Uptime check on `/api/health` |
| p95 latency, non-LLM endpoints | Under 300 ms | Logfire request spans |
| Chat time to first token, p95 | Under 3 s | `chat_stream` spans |
| Upload job finished, p95 | Under 2 min | `jobs` timestamps |
| Jobs failed after all retries | Under 1% | Dead-letter count |
| Cross-user access | 0 failures | Authz matrix in CI |
| LLM cost per MAU | Weekly, alert on a 2x jump | Agent usage table |
