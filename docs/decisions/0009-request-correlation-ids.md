# 0009: Request correlation IDs (X-Request-ID)

- Status: accepted
- Date: 2026-05-04
- Supersedes: none

## Context

Until this ADR, debugging "why did Alice's upload fail at 3:42pm?" required scrolling Logfire by timestamp and hoping nothing else fired in the same window. The `request_id` field on `SaplingDeps` was generated per-route ad-hoc and never surfaced to the client. Error responses (HTTP 4xx/5xx, SSE error events) carried no correlation handle. A user's bug report was disconnected from the trace that captured the failure.

## Decision

Stamp every request with a correlation ID via a `RequestIDMiddleware` (added in `backend/services/request_context.py`). The middleware reads `X-Request-ID` from the incoming request — accepting caller-supplied IDs that match `^[A-Za-z0-9_\-]{8,128}$`, generating a fresh uuid4 otherwise — and:

1. Stashes the ID on `request.state.request_id`.
2. Sets a `contextvars.ContextVar` so downstream code (loggers, error handlers) can read it without parameter threading via `current_request_id()`.
3. Echoes the ID back as `X-Request-ID` on every response (success and error).

Three global exception handlers (`StarletteHTTPException`, `RequestValidationError`, bare `Exception`) include `request_id` in the JSON error body and the response header.

The streaming `/upload` route's SSE error events also carry the middleware ID in their `data` field, so a user pasting an error toast can be correlated to the Logfire span that produced it.

The middleware is added LAST in `backend/main.py` so it runs OUTERMOST — every response, including ones that fail inside CORS, gets tagged.

## Consequences

- (+) "User reports an error" → "engineer searches Logfire by request_id" is a one-step lookup. Same correlation handle in browser DevTools, server logs, and traces.
- (+) Caller-supplied IDs (when they pass validation) let frontend retries collapse to the same ID, helpful for tracing flakiness.
- (+) No code changes required at agent or service layers — the contextvar pattern means any code path can read the current ID without plumbing.
- (+) Tests verify three behaviors: header-on-response, caller-supplied ID passthrough, invalid-ID replacement, and error-body inclusion (4 tests in `TestRequestIDPropagation`).
- (−) The streaming route's `SaplingDeps.request_id` is still a separate uuid4 generated inline (not the middleware ID). Today they diverge. A future small refactor should make `SaplingDeps.request_id = current_request_id()` so agent traces correlate too. Tracked in code as the only remaining gap; the SSE error event payload already uses the middleware ID, which is the user-visible correlation point.
- (−) Caller-supplied ID validation is generous (8–128 chars, hex-and-uuid-ish). Adversarial input could collide with a generated ID. Acceptable because: (a) collision risk is negligible at our scale, (b) the ID is for debugging, not auth, (c) we don't trust caller-supplied IDs for any privileged decision.
