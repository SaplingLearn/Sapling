# 0028: PostHog runs alongside the in-house analytics, never instead of it

- Status: accepted
- Date: 2026-09-26
- Relates to: #116/#117/#118 (the `events` / `llm_usage` pipeline), #375
  (admin analytics), ADR 0025 (content that must not leave the app encrypted),
  ADR 0027 / PR #672 (`decision.made` — mirrored automatically once both land)
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
   payload, `distinct_id` = the user UUID, behind the same
   `EVENTS_LOGGING_ENABLED` kill switch. Routes never call PostHog. A missing
   event is added to `EVENT_TAXONOMY` so both pipelines get it
   (`flashcard.generated` / `flashcard.reviewed` were added this way).
   `content_fp` is not forwarded.
3. **US cloud** (`https://us.i.posthog.com` default).
4. **No PII, no content.** Distinct ids are user UUIDs only; nothing calls
   `identify` with profile data; GeoIP is disabled. Event payloads are the
   #117 ones — ids, counts, enums by contract.
5. **AI spans are allowlisted, not scrubbed.** `services/ai_observability.py`
   rebuilds each Pydantic AI span before PostHog's exporter sees it, keeping
   only model/provider/operation, numeric token usage, `operation.cost`,
   agent and tool *names*, status code, `error.type` (the class), latency
   (timestamps) and the UUID attribution. Prompts, completions, system
   instructions, tool args/results, span events and status descriptions are
   dropped — a new attribute is dropped until someone allowlists it. PostHog
   receives privacy-mode `$ai_generation`s: model, tokens, cost, no
   `$ai_input`/`$ai_output`. A test drives a real Pydantic AI run with
   content in every slot, across every instrumentation data-format version,
   and asserts none of it arrives.
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
   unset or failing → WARN, never a failed deletion.
9. The wizard's OTLP log export (`posthog_logs.py`) was removed: three log
   lines did not justify a second export pipeline.

## Consequences

- PostHog can never hold more than the events table already does, minus the
  content fingerprint — reviewing one reviews the other.
- A PostHog outage or misconfiguration costs analytics, never a request: every
  entry point swallows its failures, and capture is an enqueue for posthog's
  own consumer thread.
- LLM analytics in PostHog has no prompt/response bodies. Debugging a bad
  generation still goes through Logfire.
- Exception grouping in PostHog works on type + frames; the message is only in
  our logs.
