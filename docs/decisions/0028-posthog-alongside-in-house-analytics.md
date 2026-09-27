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
6. **Exceptions without state.** One capture site (the 500 handler), with the
   session user from `request.state`. `capture_exception_code_variables` and
   autocapture are off, and a `before_send` redacts the exception message and
   strips any frame locals — messages from pydantic/PostgREST errors echo
   their input.
7. **Off in tests and E2E.** No client, no span processor, no network when:
   the token is unset, `POSTHOG_DISABLED` is truthy, under pytest,
   `APP_ENV=test`, or `SAPLING_MODEL_MODE` is anything but `real`. Function
   mode is what keeps the E2E stack silent even though it reads a
   `backend/.env` that may hold a real token. Local dev with a token sends.
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
    the user id, so the mirror costs at most one read per active user per
    minute, never one per event. Not `lru_cache`: an lru entry never expires,
    and a toggle flipped through another replica must still take effect in
    bounded time. The settings PATCH and account deletion clear the entry in
    their own process. Our own `events` table is first-party observability and
    is unaffected by the opt-out or the headers.
11. **`error.4xx` is not mirrored.** Every expired-cookie 401, 404 probe and
    422 is high-volume, carries no product signal, and each row has a raw
    path. It stays in our table (the admin error rollups). `error.5xx` is
    mirrored with `path` replaced by the matched route template
    (`/api/profile/{user_id}`), or `<unmatched>` — never the raw path, whose
    segments are user/document/session ids. Our own row keeps the raw path.
12. **Deleted users are not re-created.** PostHog creates a person for any
    unseen `distinct_id`, so an event for a deleted account would undo the
    delete. The consent check reads `users.deleted_at` (the account-deletion
    route clears the cached answer), and `delete_person` drains both SDK
    queues (events, bounded 10 s; AI spans, bounded 10 s) before it issues
    `bulk_delete`.

## Consequences

- PostHog can never hold more than the events table already does, minus the
  content fingerprint and the 4xx rows — reviewing one reviews the other.
- A PostHog outage or misconfiguration costs analytics, never a request: every
  entry point swallows its failures, and capture is an enqueue for posthog's
  own consumer thread. A consent-cache miss is one synchronous PostgREST read
  on the calling thread, like the other `table()` reads in async routes.
- LLM analytics in PostHog has no prompt/response bodies. Debugging a bad
  generation still goes through Logfire.
- Exception grouping in PostHog works on type + frames; the message is only in
  our logs.
- **Remaining window after an account deletion.** Three paths can still
  deliver an event under a deleted user's id after `bulk_delete`, re-creating
  an (empty) person:
  1. another process (a second replica/worker) holding a cached "allowed"
     answer — bounded by the 60 s TTL. The Dockerfile runs one uvicorn
     process, so today this is only a multi-replica concern;
  2. a request of that user already past its consent check when the deletion
     committed, whose capture lands after the flush;
  3. a flush that hits its 10 s budget (PostHog unreachable), leaving events
     queued that the SDK delivers later.

  All three are narrow and carry only ids/counts. Closing them fully needs a
  delayed second `bulk_delete` (or PostHog-side suppression); if we see
  re-created persons in practice, add a delayed retry of the delete. An
  opt-out has the same shape of window (another process: ≤ 60 s) but does not
  delete what was already sent; deleting past data on opt-out is not part of
  this decision.
