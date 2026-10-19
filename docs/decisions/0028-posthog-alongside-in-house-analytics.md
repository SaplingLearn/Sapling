# 0028: PostHog runs alongside the in-house analytics, never instead of it

- Status: accepted
- Date: 2026-09-26 (revised 2026-09-27: one queue + one consent worker; LLM
  analytics from the usage chokepoint instead of an OTel span export)
- Relates to: #116/#117/#118 (the `events` / `llm_usage` pipeline), #375
  (admin analytics), ADR 0025 (content that must not leave the app encrypted),
  ADR 0027 / PR #672 (`decision.made`, and the Jev seam's usage — both mirrored
  automatically once both land), PR #675 (the frontend opt-out toggle +
  DNT/GPC handling)
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
2. **One taxonomy, one chokepoint per kind.** `events_service.log_event`
   mirrors every event to PostHog (`services/posthog_client.mirror_event`):
   same name, same payload, behind the same `EVENTS_LOGGING_ENABLED` kill
   switch. Routes never call PostHog. A missing event is added to
   `EVENT_TAXONOMY` so both pipelines get it (`flashcard.generated` /
   `flashcard.reviewed` were added this way). `content_fp` is not forwarded.
   The #117 category is sent as `event_category`, because several payloads
   carry a `category` of their own (`document.processed`,
   `rag.relevance_scored`) that must survive.
3. **US cloud** (`https://us.i.posthog.com` default).
4. **Every PostHog event is attributed to a consenting student, or it is not
   sent.** There are no personless events: work with no actor — the index
   sweeper, DBOS workflows, the document pipeline outside a request — sends
   nothing to PostHog (its rows still land in our own tables). A personless
   path would otherwise carry an opted-out student's out-of-request work as
   an anonymous event.

   **No PII, no content.** Distinct ids are real `users.id` values only —
   opaque TEXT (`user_<google id>`), NOT UUIDs, so the rule is "a live row in
   `users`", never a UUID regex. Nothing calls `identify` with profile data;
   GeoIP is disabled. Event payloads are the #117 ones — ids, counts, enums by
   contract.
5. **One queue, one worker — consent is decided off the request path.**
   Every send (event, `$ai_generation`, exception) goes through ONE path:
   - *On the request path* (`_submit`, no I/O): drop if PostHog is off RIGHT
     NOW (the gate is re-read, §8), the request sent `Sec-GPC: 1` /
     `DNT: 1`, or the event is `error.4xx`. Resolve the **actor**: the item's
     own user id if it is a real one; **only when that id is `None`**, the
     request's authenticated user (`request.state.user_id`); otherwise —
     no user, a placeholder (`anonymous`, `backfill`) or a malformed id —
     **drop**. A caller that names someone is never re-attributed to whoever
     happens to be signed in. The request is seen through a narrow view held
     in a contextvar — the `scope["state"]` dict (shared by the handler,
     threadpool `Depends` and BackgroundTasks) plus a route-template
     accessor. While the request is in flight the accessor reads the route
     off the scope (routing stamps it after the view is made); when the
     request ends the middleware resolves the template once and drops the
     scope, so a context copied into a task or thread never keeps the
     scope — its headers and session cookie — alive afterwards. Build the
     properties (route template for `path`/`route`, no foreign user ids,
     `event_category`), then enqueue onto a bounded in-process queue
     (`POSTHOG_QUEUE_MAX`, default 10000; a bad or non-positive value falls
     back to the default — `queue.Queue(0)` would be unbounded; full → drop
     the oldest, warn once then every 1000th).
   - *On the one daemon worker thread*: re-read the gate, then
     `analytics_consent.consent_for(actor)` — a blocking PostgREST read is
     fine here, bounded by a 3 s timeout (through `table().select(timeout=)`,
     the shared client) — then `posthog.capture` with that `distinct_id`, or
     drop.

   Consequences of the shape: no event-loop thread ever reads the database,
   and a cold consent cache only DELAYS an event on the worker; it never drops
   it. Consent **fails closed**: a denied, deleted, unknown or unreadable
   answer drops the item.
6. **LLM analytics come from the usage chokepoint, not from spans.**
   `agents/usage.py::record_agent_usage` → `events_service.log_llm_usage`
   (the single place every agent run already reports usage, including #672's
   Jev seam) mirrors each `llm_usage` row as a privacy-mode `$ai_generation`
   with ONLY `$ai_model`, `$ai_provider`, `$ai_input_tokens`,
   `$ai_output_tokens`, `$ai_total_cost_usd`, `$ai_trace_id` (the request
   id) and the feature/task name — never `$ai_input` / `$ai_output`.
   `$ai_provider` is the provider the usage row records (e.g. #672's Jev
   seam), derived from the model name only when none is given. No latency:
   the chokepoint has no timing. Same queue, same consent.

   **Why the OTel span export was removed.** The first design forwarded
   Pydantic AI's spans through an allowlisting span processor, with per-run
   attribution bound by a global `pydantic_ai.Agent.iter` wrapper. Three
   review rounds each found an opt-out leak in that machinery, and each fix
   added machinery with its own gaps: a session-user contextvar that did not
   reach BackgroundTasks or threadpool `Depends`; `posthog.distinct_id` /
   `$ai_session_id` already present on a source span passing the allowlist
   unchecked; unbound spans exported with no consent check; pending/suppress
   bookkeeping that could fail open at its cap; a loop-thread cold cache that
   dropped events and a sync-thread one that blocked. The chokepoint model has
   none of those surfaces: one row per call, one consent path, no patch of a
   library class. **The trade-off:** PostHog LLM analytics has no per-step
   agent/tool trace tree (`$ai_span` / `$ai_trace` hierarchy); per-call model,
   tokens and cost remain, grouped by request id. The step-level view stays in
   Logfire.
7. **Exceptions without state.** One capture site (the 500 handler), with the
   session user from `request.state`, through the same queue and consent
   rule. The handler is async, so the request path does no file I/O: it
   takes a plain frame SUMMARY (each chained exception's type and module, and
   its frames' file/line/function/module, read off the traceback — no
   linecache, no message, no locals; on a very deep stack the INNERMOST
   frames are kept, raise site included), and the worker builds the
   SDK-shaped `$exception_list` from it (source context via linecache,
   module-relative file names like `services/foo.py` — never the server's
   absolute paths) and scrubs it.
   The queue never holds the exception, its traceback or its frames, which
   would keep every local (decrypted content) alive while the item waits. `capture_exception_code_variables` and autocapture are off,
   and `before_send` scrubs again. The handler runs outside
   `RequestIDMiddleware`, so it reads DNT/GPC off the request headers.
8. **Off in tests and E2E.** No client, no queue, no network when: the token is
   unset, under pytest, `APP_ENV=test`, or the seam's mode
   (`agents._providers.model_mode()` — the one normalisation, not a second
   parser) is anything but `real`. The gate is decided ONCE, at boot: no
   client is built, and with no client nothing is ever enqueued (the request
   path does not re-run it per submit, nor the worker per delivery). The local
   E2E and explore stacks do not rely on that inference — `make e2e-up` does
   not force function mode and runs `APP_ENV=local` against a `backend/.env`
   that may hold a real token — so `scripts/e2e-up.sh` and
   `scripts/explore.sh` blank `POSTHOG_PROJECT_TOKEN` explicitly, and
   `POSTHOG_PERSONAL_API_KEY` too (erasure is not gated by capture, §9).
   Local dev with a token sends. **The runtime switch is the
   `product_analytics` feature flag** (ADR 0029, `off` | `on`, seeded `on`):
   the worker resolves it per student just before the consent read and sends
   nothing — including items already queued — for a student it is off for.
   The read is the feature-flag resolver's own (ADR 0029): a warm cache
   answers with no I/O, a cold one is bounded (`STORE_TIMEOUT_S`), and an
   unreadable store is remembered as off for `STORE_UNREADABLE_TTL_S` — so an
   outage cannot stall the worker (or the flush before an erasure) for 30 s
   per item. One student's invalid stored variant fails closed for that
   student's items only; only a store-read failure is an outage. It is editable from /admin without a
   deploy, and `SAPLING_FLAG_PRODUCT_ANALYTICS=off` is its env kill switch.
   (An earlier draft also had a bespoke `POSTHOG_DISABLED` env gate re-read
   on every submit; the flag plus "no token, no client" cover every case it
   served, and the codebase rule is flags, not new env vars. It is
   deprecated: a truthy leftover still fails CLOSED — no client is built —
   with a startup WARNING naming `SAPLING_FLAG_PRODUCT_ANALYTICS=off`.) Like an unset
   token, it stops capture, never erasure.
9. **Account deletion deletes the PostHog person** (`bulk_delete` with
   `delete_events`) as a post-response BackgroundTask. Needs
   `POSTHOG_PERSONAL_API_KEY` (scope `person:write`) + `POSTHOG_PROJECT_ID`;
   failing → WARN, never a failed deletion. **Erasure is not capture:** the
   delete runs whenever the personal key, project id and API host are
   configured — even with the flag off or no project token, since those stop
   sending, not deleting what was sent before. Only pytest,
   `APP_ENV=test` and a non-real seam mode block it. Unconfigured: a WARN
   where PostHog was ever configured (a token or a personal key is set — a
   skipped delete there is a privacy to-do), silence where it never was.
   The personal key is only
   ever sent to a PostHog app host: `POSTHOG_API_HOST` if set, otherwise one
   derived from the two cloud ingestion hosts (`us`/`eu.i.posthog.com` →
   `us`/`eu.posthog.com`). Any other `POSTHOG_HOST` without an explicit
   `POSTHOG_API_HOST` → WARN + skip, never a guessed host. The call uses
   `httpx` directly — a third-party REST API, not Supabase, listed in
   CLAUDE.md beside the OAuth exchange.
10. The wizard's OTLP log export (`posthog_logs.py`) was removed: three log
    lines did not justify a second export pipeline.
11. **Students can opt out, and browser privacy signals are honoured.**
    Nothing reaches PostHog — no event, no exception, no `$ai_generation`,
    not even a personless one — for:
    - a student with `user_settings.analytics_opt_out = true` (the settings
      toggle, PATCH `/api/profile/{user_id}/settings`). Only the student
      sets it: nothing writes it from a Do Not Track / Global Privacy Control
      signal. (Corrected 2026-10-19: an earlier wording said the frontend sets
      it under DNT/GPC; nothing ever did);
    - any request carrying `Sec-GPC: 1` or `DNT: 1`, whoever the user is —
      **per request only**. Under the signal the browser loads no posthog-js
      (no pageviews), and the backend drops every event captured during that
      request, including its BackgroundTasks. Work that runs outside the
      request (the index sweeper's `rag.index_failed` / `rag.index_recovered`
      / `rag.relevance_scored`, DBOS-resumed pipelines, scripts) has no
      browser signal and follows the stored `analytics_opt_out` alone, so it
      is still sent under the student's id unless they opted out. This is a
      known, deliberate limitation: persisting a header would turn a browser signal into a
      stored choice the student never made. The frontend's toggle, which
      also defaults on under DNT/GPC, is how a student makes it stored;
    - an opted-out student's request, even for events that name no user —
      including their BackgroundTasks and threadpool dependencies, because the
      actor comes from the request scope they all share.

    `consent_for` is one PostgREST read (`users` + embedded `user_settings`)
    cached per process for 60 s. Not `lru_cache`: an lru entry never expires,
    and a toggle flipped through another replica must still take effect in
    bounded time. The settings PATCH and account deletion clear the entry in
    their own process; any clear bumps one counter, and a read in flight
    across a clear does not store its possibly-stale answer (it is re-read;
    still racing → "no"). Our own `events` table is first-party observability
    and is unaffected by the opt-out or the headers.

    **Deploy order.** The column ships in its own migration
    (`20261016064813_analytics_opt_out.sql`) and migrations apply before or
    at merge — staging migrates on merge (#619), prod runs `db.migrate` in
    `make promote` before merging — so the code assumes the column exists.
    An earlier draft tolerated a missing column (retry-without-column reads,
    a 503 PATCH, an ETag schema version); that machinery went once the
    promotion order made the window not worth carrying code for. Should the
    column ever be missing anyway, the consent lookup errors and fails
    closed: nobody is sent.
12. **No raw path, no second user, no `error.4xx`.** `error.4xx` (every
    expired-cookie 401, 404 probe and 422) stays in our table only. Every
    mirrored `path` / `route` payload key becomes the current request's
    matched route template (`/api/profile/{user_id}`) or `<unmatched>` — raw
    segments are ids, and `auth.permission_denied`'s raw `route` put ANOTHER
    user's id into the acting user's event. Payload keys that name a second
    user (`user_id`, `target_user_id`, ...) are dropped; an audit of today's
    taxonomy found none (the admin role/achievement `user_id`s go to
    `admin_audit_log`, not `log_event`). Our own rows keep the raw values.
13. **Deleted users are not re-created.** PostHog creates a person for any
    unseen `distinct_id`, so an event for a deleted account would undo the
    delete. Consent reads `users.deleted_at` at SEND time on the worker (the
    deletion route clears the cached answer), so even items queued before the
    deletion are dropped once it lands. Each `delete_person` pass drains OUR
    queue, then posthog's (bounded 10 s each), then issues `bulk_delete`; a
    **second** pass runs after the consent TTL + 30 s (a daemon timer), by
    which time every process's cached "allowed" has expired and its queues
    have delivered.

## Consequences

- PostHog can never hold more than the events and llm_usage tables already
  do, minus the content fingerprint and the 4xx rows — reviewing one reviews
  the other.
- A PostHog outage or misconfiguration costs analytics, never a request: the
  request path only enqueues, the worker swallows its failures, and a full
  queue drops the oldest items.
- LLM analytics in PostHog has no prompt/response bodies and no per-step
  agent/tool tree. Debugging a bad generation, or a run's steps, still goes
  through Logfire.
- Exception grouping in PostHog works on type + frames; the message is only in
  our logs.
- **Remaining window after an account deletion.** The second `bulk_delete`
  (TTL + 30 s later) removes anything re-created by another process's stale
  cached "allowed". What can still re-create an (empty, ids/counts-only)
  person after it:
  1. the process that ran the deletion exits before its daemon timer fires
     (deploy/restart within ~90 s) — the second pass is lost; the scheduling
     log line says so;
  2. an SDK queue that could not deliver within that window (PostHog
     unreachable, retries still pending) and delivers later;
  3. another process's item consent-checked just before its cached answer
     expired and delivered more than 30 s later;
  4. PostHog-side ingestion lag, or the SDK's retry backoff during an outage:
     an event handed to the SDK just before the deletion can be ingested after
     the second pass and re-create the person.

  The complete fix is a **periodic reconciliation** that deletes every
  PostHog person whose `users` row is soft-deleted (a follow-up issue); a
  durable second pass (DBOS is already in the stack) would close only (1). An opt-out has the same shape of window
  (another process: ≤ 60 s) but does not delete what was already sent;
  deleting past data on opt-out is not part of this decision.
