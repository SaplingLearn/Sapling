# 0028: PostHog runs alongside the in-house analytics, never instead of it

- Status: accepted
- Date: 2026-09-26
- Relates to: #116/#117/#118 (the `events` / `llm_usage` pipeline), #375
  (admin analytics), ADR 0025 (content that must not leave the app encrypted),
  ADR 0027 / PR #672 (`decision.made` — mirrored automatically once both land),
  PR #675 (the frontend opt-out toggle + DNT/GPC handling)
- Supersedes: none

## Context

The PostHog setup wizard produced a working but unsafe integration: PostHog
was *required* when `APP_ENV` was local/dev (breaking every teammate's boot
and the E2E lane, whose `.env.local.example` has no PostHog vars), it added a
second event taxonomy of nine ad-hoc `posthog.capture(...)` calls in routes
under names that duplicated existing #117 events, it forwarded every
Pydantic AI span to PostHog relying on Logfire's pattern scrubber (and on
processor ordering in the pinned Logfire version) to keep prompts out, and it
shipped a second OTLP pipeline for three lifecycle log lines.

This app decrypts names, notes, chat messages and document text into prompts.
Anything that forwards spans or exception state is on the student-data path.

## Decision

1. **Alongside, not instead.** The `events` / `llm_usage` tables stay the
   system of record: admin analytics (`/api/admin/analytics`) and the Canopy
   metrics keep reading them. PostHog adds funnels, retention, LLM analytics
   and error tracking on top.
2. **One taxonomy, one chokepoint.** `events_service.log_event` mirrors every
   event to PostHog (`services/posthog_client.mirror_event`): same name, same
   payload, `distinct_id` = the user id, behind the same
   `EVENTS_LOGGING_ENABLED` kill switch. Routes never call PostHog. A missing
   event is added to `EVENT_TAXONOMY` so both pipelines get it
   (`flashcard.generated` / `flashcard.reviewed` were added this way).
   `content_fp` is not forwarded. The #117 category is sent as
   `event_category`, because several payloads carry a `category` of their own
   (`document.processed`, `rag.relevance_scored`) that must survive.
3. **US cloud** (`https://us.i.posthog.com` default).
4. **No PII, no content.** Distinct ids are real `users.id` values only —
   opaque TEXT (`user_<google id>`), NOT UUIDs, so the rule is "a live row in
   `users`", never a UUID regex. Placeholders callers pass when there is no
   actor (`anonymous`, `backfill`, ...) mean "no actor": the event is sent
   personless and an AI run unattributed. Nothing calls `identify` with profile
   data; GeoIP is disabled. Event payloads are the #117 ones — ids, counts,
   enums by contract.
5. **AI spans are allowlisted, not scrubbed.** `services/ai_observability.py`
   rebuilds each Pydantic AI span before PostHog's exporter sees it, keeping
   only model/provider/operation, numeric token usage, `operation.cost`,
   agent and tool *names*, status code, `error.type` (the class), latency
   (timestamps) and the user-id attribution. Prompts, completions, system
   instructions, tool args/results, span events and status descriptions are
   dropped — a new attribute is dropped until someone allowlists it. Only
   spans from the `pydantic-ai` tracer are considered at all. PostHog
   receives privacy-mode `$ai_generation`s: model, tokens, cost, no
   `$ai_input`/`$ai_output`. A test drives a real Pydantic AI run with
   content in every slot, across every instrumentation data-format version,
   and asserts none of it arrives.
   - **Attribution is per span and per run.** PostHog's OTLP capture resolves
     `distinct_id` per span, span attributes first and resource attributes as
     the per-process fallback (`rust/capture/src/otel/identity.rs`,
     `extract_distinct_id_for_span`, PostHog/posthog@8a89abc0c9). A resource is
     per process, so `posthog.distinct_id` goes on each exported span.
   - It is bound around each agent run — a wrapper on `pydantic_ai.Agent.iter`,
     the entry `run`/`run_stream`/`run_stream_events` share, installed only when
     PostHog is on — and reset when the run ends. It was a side effect of the
     `SaplingDeps` constructor with no reset, which leaked the attribution into
     every later run and BackgroundTask in the same context. A deps-less run
     binds the request's authenticated user (noted by `auth_guard`), if any.
     The binding records only WHO the run is for and warms that user's consent
     answer in the background; it does no I/O on the event loop.
   - **Consent is re-checked when each span ENDS**, against the cached answer,
     so a deletion or opt-out that lands mid-run stops that run's later spans.
     A span whose bookkeeping entry is missing at end (evicted at the
     `_MAX_PENDING` cap, or never seen) is dropped, never exported
     unattributed — suppression cannot fail open.
   - **Why a class-level wrapper and not a helper at the call sites.** The run
     helpers (`agents/_run.py::run_agent_sync`, `services/chat_stream.py`)
     cover a minority of runs: ~20 sites `await agent.run(...)` directly
     (documents, learn, notes, quiz, graph, calendar, ...). A `with` at each
     would be forgettable — a new call site would silently lose the binding —
     while `Agent.iter` is the public entry every run mode already passes
     through. The wrapper only adds a context around the original call
     (arguments and the yielded run untouched), is idempotent, is installed
     only when PostHog is on, and is pinned by tests against the installed
     pydantic-ai (`<2` in requirements). If pydantic-ai grows a global
     run-lifecycle hook that runs before the agent-run span starts, move to it.
6. **Exceptions without state.** One capture site (the 500 handler), with the
   session user from `request.state`. `capture_exception_code_variables` and
   autocapture are off, and a `before_send` redacts the exception message and
   strips any frame locals — messages from pydantic/PostgREST errors echo
   their input.
7. **Off in tests and E2E.** No client, no span processor, no network when:
   the token is unset, `POSTHOG_DISABLED` is truthy, under pytest,
   `APP_ENV=test`, or the seam's mode (`agents._providers.model_mode()` — the
   one normalisation, not a second parser) is anything but `real`. The local
   E2E and explore stacks do not rely on that inference — `make e2e-up` does
   not force function mode and runs `APP_ENV=local` against a `backend/.env`
   that may hold a real token — so `scripts/e2e-up.sh` and
   `scripts/explore.sh` export `POSTHOG_DISABLED=1` explicitly. Local dev with
   a token sends.
8. **Account deletion deletes the PostHog person** (`bulk_delete` with
   `delete_events`) as a post-response BackgroundTask. Needs
   `POSTHOG_PERSONAL_API_KEY` (scope `person:write`) + `POSTHOG_PROJECT_ID`;
   unset or failing → WARN, never a failed deletion. The personal key is only
   ever sent to a PostHog app host: `POSTHOG_API_HOST` if set, otherwise one
   derived from the two cloud ingestion hosts (`us`/`eu.i.posthog.com` →
   `us`/`eu.posthog.com`). Any other `POSTHOG_HOST` without an explicit
   `POSTHOG_API_HOST` → WARN + skip, never a guessed host.
9. The wizard's OTLP log export (`posthog_logs.py`) was removed: three log
   lines did not justify a second export pipeline.
10. **Students can opt out, and browser privacy signals are honoured.**
    Nothing reaches PostHog — no event, no exception, no AI span, not even an
    anonymous one — for:
    - a student with `user_settings.analytics_opt_out = true` (the settings
      toggle, PATCH `/api/profile/{user_id}/settings`; the frontend also sets
      it when the browser sends Do Not Track / Global Privacy Control);
    - any request carrying `Sec-GPC: 1` or `DNT: 1` (captured per request in
      `services/request_context.py`), whoever the user is;
    - a request whose authenticated user opted out, even for events that name
      no user.

    The decision lives in `services/analytics_consent.consent_for`, which
    **fails closed**: an unreadable answer is a "no". It is one PostgREST read
    (`users` + embedded `user_settings`) cached per process for 60 s, keyed on
    the user id and refreshed in the background once past half its life, so
    the mirror costs at most one read per active user per ~30 s, never one per
    event. Not `lru_cache`: an lru entry never expires, and a toggle flipped
    through another replica must still take effect in bounded time. The
    settings PATCH and account deletion clear the entry in their own process;
    each clear bumps a per-user generation, and a read that was in flight
    across the clear neither stores nor returns its possibly-stale answer
    (it returns "no").

    **No event-loop thread ever blocks on it.** The read is a synchronous
    PostgREST call; a slow Supabase must not freeze a worker. On a thread
    running an asyncio loop (async routes, the async 500 handler,
    RequestIDMiddleware's `error.5xx`, agent runs and their span ends) a cache
    miss answers "no" immediately and warms the entry on a 2-thread pool; only
    loop-free threads (sync handlers in the threadpool, the sweeper) read
    inline. Cost: the first event(s) of a user whose answer is cold in this
    process, emitted from async code, are not mirrored (the run boundary warms
    ahead, so AI spans rarely hit this). Our own `events` table is first-party
    observability and is unaffected by any of this.
11. **`error.4xx` is not mirrored.** Every expired-cookie 401, 404 probe and
    422 is high-volume, carries no product signal, and each row has a raw
    path. It stays in our table (the admin error rollups).
    **No raw path reaches PostHog from any event.** Every mirrored `path` /
    `route` payload key is replaced by the current request's matched route
    template (`/api/profile/{user_id}`, from the ASGI scope `RequestIDMiddleware`
    records) or `<unmatched>`: raw segments are user/document/session ids —
    `auth.permission_denied`'s raw `route` put ANOTHER user's id into the
    acting user's event. Payload keys that name a second user (`user_id`,
    `target_user_id`, ...) are dropped from mirrored properties; an audit of
    today's taxonomy found none (the admin role/achievement `user_id`s go to
    `admin_audit_log`, not `log_event`), so this is a guard for future
    payloads. Our own rows keep the raw values.
12. **Deleted users are not re-created.** PostHog creates a person for any
    unseen `distinct_id`, so an event for a deleted account would undo the
    delete. The consent check reads `users.deleted_at` (the account-deletion
    route clears the cached answer) and runs at ENQUEUE for every event and at
    END for every AI span. `delete_person` drains both SDK queues (events,
    bounded 10 s; AI spans, bounded 10 s) and issues `bulk_delete`, then
    schedules a **second** flush + `bulk_delete` after the consent TTL + 30 s
    (a daemon timer), by which time every process's cached "allowed" has
    expired and its queues have delivered.

## Consequences

- PostHog can never hold more than the events table already does, minus the
  content fingerprint and the 4xx rows — reviewing one reviews the other.
- A PostHog outage or misconfiguration costs analytics, never a request: every
  entry point swallows its failures, and capture is an enqueue for posthog's
  own consumer thread. A consent-cache miss never blocks an event loop (it
  answers "no" and warms in the background).
- LLM analytics in PostHog has no prompt/response bodies. Debugging a bad
  generation still goes through Logfire.
- Exception grouping in PostHog works on type + frames; the message is only in
  our logs.
- **Remaining window after an account deletion.** The second `bulk_delete`
  (TTL + 30 s later) removes anything re-created by another process's stale
  cached "allowed" or by a run in flight at deletion time. What can still
  re-create an (empty, ids/counts-only) person after the second pass:
  1. the process that ran the deletion exits before its daemon timer fires
     (deploy/restart within ~90 s) — the second pass is lost; the scheduling
     log line says so;
  2. an SDK queue that could not deliver within that window (PostHog
     unreachable, retries still pending) and delivers later;
  3. an in-flight request whose event was enqueued before its process's
     answer expired but delivered after the second pass — needs a > 30 s
     delivery delay.

  If re-created persons show up in practice, move the second pass to a durable
  job (DBOS is already in the stack). An opt-out has the same shape of window
  (another process: ≤ 60 s) but does not delete what was already sent;
  deleting past data on opt-out is not part of this decision.
