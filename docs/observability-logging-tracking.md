# Site Logging & Usage Tracking — Epic Overview

The full story of how Sapling gets **site logging and usage tracking**: what we're
building, why, the decisions behind it, and the eight GitHub issues that deliver
it. This is the map; each issue is the territory.

_Status: planned. Created 2026-06-07._

## Goal

Track what users actually do across the site (usage analytics), what the LLMs
cost (token + dollar accounting), what breaks (errors), and who did what
(audit) — and **own that data** in our own Supabase so we can query it, roll it
up, and eventually dashboard it.

## Key decisions (already made)

| Decision | Choice | Why |
|---|---|---|
| Where data lives | **Own Supabase DB** | We own/query the data; foundation for an admin dashboard |
| Event granularity | **Curated domain events** | High signal-to-noise; user-usage analytics, not raw access logs |
| Deliverable scope | **Backend capture + tables + admin API**, then frontend dashboard | Phased; dashboard split out for the frontend |
| Sensitive content | **Metadata + SHA-256 fingerprints** | Analytics without storing student content; respects existing encryption posture |
| Write path | **Fire-and-forget async** | Logging never adds latency and never breaks a request |
| Ops / LLM tracing | **Activate Logfire** (already wired) | Don't rebuild request tracing & live token usage in-house |

## Two systems, complementary

- **Logfire** (external, already wired — just needs a token): request traces,
  latency, errors, and live per-call LLM token usage. Great for ops/debugging.
- **Supabase events** (owned, built here): user-usage analytics, audit trail,
  and LLM cost rollups we query and dashboard.

| Concern | Tool |
|---|---|
| Ops / error traces / latency / debugging | Logfire |
| Live per-call LLM token usage | Logfire |
| User usage analytics (counts, trends) | Supabase `events` |
| Audit / security trail | Supabase `events` |
| LLM cost rollups per user/feature/model | Supabase `llm_usage` |

## Data model

- **`events`** — flexible firehose: `event_type`, `category` (`usage`/`audit`/`error`),
  `user_id`, `request_id`, `payload jsonb`, `content_fp` (fingerprint only), `created_at`.
- **`llm_usage`** — structured cost rows: `user_id`, `feature`, `task`, `model`,
  `provider`, token counts, `cost_usd`, `created_at`.

No raw content is ever stored — only fingerprints.

## The issues

| # | Issue | Owner | Role | Depends on |
|---|---|---|---|---|
| [#115](https://github.com/SaplingLearn/Sapling/issues/115) | Create `events` + `llm_usage` tables (migration) | Luke | Backend | — |
| [#116](https://github.com/SaplingLearn/Sapling/issues/116) | `events_service` async fire-and-forget write path | Luke | Backend | #115 |
| [#117](https://github.com/SaplingLearn/Sapling/issues/117) | Instrument capture seams (middleware, auth, feature routes) | Andres | Fullstack | #115, #116 |
| [#118](https://github.com/SaplingLearn/Sapling/issues/118) | Capture LLM token usage + cost (agents + Gemini) | Jack | AI Eng | #115, #116 |
| [#119](https://github.com/SaplingLearn/Sapling/issues/119) | Activate Logfire for ops/error/LLM tracing | Jack | AI Eng | — |
| [#120](https://github.com/SaplingLearn/Sapling/issues/120) | Admin analytics + cost API (`/api/admin/analytics`) | Andres | Fullstack | #115, #116 |
| [#121](https://github.com/SaplingLearn/Sapling/issues/121) | Frontend admin analytics data layer (client + hooks + route) | Jose | Frontend | #120 |
| [#122](https://github.com/SaplingLearn/Sapling/issues/122) | Admin analytics dashboard UI (charts/visualizations) | Jose | Frontend | #121 |

### Load (even split — 2 issues each)

- **Luke** (Backend): #115, #116
- **Andres** (Fullstack): #117, #120
- **Jack** (AI Engineer): #118, #119
- **Jose** (Frontend): #121, #122

## Dependency graph

```text
#115 (tables)
  └─> #116 (write path)
        ├─> #117 (capture seams)        [Andres]
        ├─> #118 (LLM usage + cost)     [Jack]
        └─> #120 (admin API)
              └─> #121 (FE data layer)
                    └─> #122 (dashboard UI)

#119 (Logfire activation)  — independent, ship anytime
```

## Suggested build order

1. **#115** tables → **#116** write path (unblocks everything backend).
2. In parallel once #116 lands: **#117** (capture seams), **#118** (LLM usage).
   **#119** (Logfire) can go anytime.
3. **#120** admin API (against seeded rows in parallel; verify after #117/#118).
4. **#121** → **#122** frontend data layer then dashboard.

## What "done" looks like

- User actions, auth/security events, and errors land in `events` (metadata +
  fingerprints, no raw content).
- Every LLM call — Pydantic AI agents and direct Gemini — writes a `llm_usage`
  row with tokens and computed cost.
- Logfire shows live request/agent traces when a token is set.
- Admins can query usage, per-user activity, LLM cost rollups, and errors via
  `/api/admin/analytics`, and view them in an admin dashboard.

## Conventions honored

- Supabase access only via `db/connection.py::table()`.
- No raw sensitive content stored; fingerprints reuse the Logfire scrubber helper.
- New tests in `backend/tests/` against the mocked Supabase/Gemini fixtures.
- Frontend follows `.impeccable.md` (light-mode, brand green `#1B6C42`, no
  glassmorphism/gradient-text).
