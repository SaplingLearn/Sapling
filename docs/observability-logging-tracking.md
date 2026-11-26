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

## Logfire (activated in #119)

Logfire is our external ops/error/LLM tracing tool. It is **complementary** to
the owned Supabase `events`/`llm_usage` tables — it is not a replacement and
does not write to them, so enabling it cannot double-count anything (the two
capture paths share no code).

### What Logfire captures

- FastAPI **request traces**: method, route template (`/api/notes/{note_id}`),
  status code, and latency — one span per request (`instrument_fastapi`).
- Pydantic AI **agent spans**: the agent run, tool calls, and **live per-call
  LLM token usage** (`instrument_pydantic_ai`).

### How to enable

1. Create a **write token** in the Logfire UI: https://logfire.pydantic.dev →
   your project → Settings → Write tokens.
2. Set `LOGFIRE_TOKEN=<token>` in the environment (see `backend/.env.example`).
3. Restart the backend. Request and agent spans now stream to Logfire.

With **no token**, Logfire is dormant: `logfire.configure(...)` uses
`send_to_logfire="if-token-present"`, so nothing egresses and the app behaves
exactly as before. `service_name="sapling-backend"` identifies the service in
the Logfire UI. Both settings live in `backend/main.py`.

### What is scrubbed / kept out of egress

**No student content (prompts, completions, tool arguments/results, uploaded
document text, query strings) leaves the process.** Content is kept only as a
length and a 16-hex `sha256` fingerprint, never a preview. Layers, all in
`backend/main.py` + `services/logfire_scrubber.py` (module docstring has the
details and the exact pydantic-ai 1.107 / logfire 4.37 attribute names):

- **Agent content at the source**: `instrument_pydantic_ai(include_content=False,
  include_binary_content=False)`. This is the layer that matters: Logfire's
  scrubber treats `gen_ai.input.messages`, `gen_ai.output.messages`,
  `gen_ai.system_instructions`, `pydantic_ai.all_messages` and
  `model_request_parameters` as safe keys and never routes them to a callback.
  It also removes `final_result`, tool arguments/results (`tool_arguments` /
  `tool_response`, or `gen_ai.tool.call.arguments` / `gen_ai.tool.call.result`
  on instrumentation v3+) and exception messages.
- **Content-free tracer boundary**: the pinned SDK still serializes
  instructions inside `model_request_parameters` (a key Logfire exempts from
  callback scrubbing), so `instrument_pydantic_ai` is also handed
  `tracer_provider=content_free_tracer_provider()` (`services/ai_trace_privacy.py`).
  It wraps the public OpenTelemetry tracer API with a finite metadata allowlist
  for initial/later attributes, links, generic span names, events and
  exceptions, keeping provider/model/token/cost/trace/tool identifiers while
  omitting bodies, schemas, arbitrary keys, exception text and stack traces.
  The grader's explicit instrumentation settings use this same boundary.
- **Scrubbing callback**: every attribute Logfire routes whose name looks like
  content (`EXTRA_PATTERNS`) is replaced whole by
  `[redacted, type:…, length:…, sha256:…]`; URL attributes lose their query
  string. Logfire's built-in patterns (`password`, `secret`, `api_key`, …) are
  still fully redacted.
- **Query strings**: `QueryStringStripProcessor` (an additional span processor)
  rewrites `http.url` / `http.target` / `url.full` to the path and redacts
  `url.query` when a span STARTS, before Logfire snapshots the pending span it
  also exports (whose message would otherwise read `GET /path ? q='…'`). The
  FastAPI `server_request_hook` repeats it on the request span.
- **Request bodies + params** (`fastapi.arguments.values`): dropped entirely via
  a `request_attributes_mapper` that returns `None`.
- **Headers**: not captured (`capture_headers=False`).
- **Uvicorn access log** (stdout → Railway logs): `services/access_log.py`'s
  `StripQueryStringFilter` logs the path without its query string.

The AI-specific tracer does not sanitize arbitrary application/third-party logs
or exception messages outside AI spans. Parent trace identifiers and incoming
OpenTelemetry TraceState are preserved for correlation, not certified as
content-free. Do not put learner data in these fields or arbitrary telemetry
labels. The finite accounting bridge below avoids exporting those record fields.

### Verifying the scrubbing

`backend/tests/test_logfire_scrubber.py` runs real spans (a pydantic-ai agent
run with a tool call; a FastAPI request with a body and a query string)
through Logfire configured as main.py configures it, pending spans included,
and asserts no 12-character run of any content string survives. AST guards fail
if main.py drops any layer. `test_ai_trace_privacy.py` exercises the
content-free tracer boundary with short answers, synthetic PII, dynamic object
keys, tool arguments/results, binary input, grader output, exception text and
parent/child traces. These hermetic tests make no collector/provider calls;
they do not establish external delivery, routing, billing completeness or uptime.

### Controlled accounting signals

`services/ops_logging.py` adds an idempotent handler only to the finite source
loggers it recognizes. It exports six exact accounting-hook failure templates,
the queue-full/aggregate-flush-drop warnings, the usage-row-drop error and the
platform-spend warning. Exported events have fixed messages and finite
`sapling.signal`/`sapling.stage` metadata. Counts and known table names are
validated; spend components are finite nonnegative decimal strings. Malformed
records and unknown templates are ignored, and exporter failure does not change
the caller or stderr delivery. Original exception text, stack, formatting args
and arbitrary record extras are never forwarded.

The per-row delivery DEBUG traceback is deliberately excluded; its existing
aggregate WARNING is covered. The unstructured platform-read-failure warning
also remains stderr-only. This is not a root-logger/third-party log bridge.

Set an actual collector rule on the fixed `sapling.signal` values and verify
receipt at the selected destination with a bounded synthetic failure drill.
`LOGFIRE_TOKEN` alone configures export, not an alert rule or recipient. Railway
captures stderr separately; seeing a line there does not prove a Logfire alert
was delivered or acknowledged. Keep source/deployment IDs, a unique synthetic
request ID, collector event ID, delivery status and acknowledgement time; do not
include learner/model prose or credentials.

## Conventions honored

- Supabase access only via `db/connection.py::table()`.
- No raw sensitive content stored; fingerprints reuse the Logfire scrubber helper.
- New tests in `backend/tests/` against the mocked Supabase/Gemini fixtures.
- Frontend follows `.impeccable.md` (light-mode, brand green `#1B6C42`, no
  glassmorphism/gradient-text).
