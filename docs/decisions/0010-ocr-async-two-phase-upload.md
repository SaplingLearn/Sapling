# 0010: OCR async / two-phase upload (partial: feature flag shipped)

- Status: partial (in-process async behind feature flag; full two-phase deferred)
- Date: 2026-05-04
- Supersedes: none

## Update (2026-05-04)

A lightweight version shipped behind the `OCR_ASYNC_ENABLED` env var:

- When false (default), behavior is unchanged — `extract_text_from_file`
  runs synchronously before the SSE stream opens.
- When true, the SSE stream opens immediately, emits a
  `progress:extracting_text` event, runs OCR via `asyncio.to_thread` so
  it doesn't block the event loop, then emits `progress:extracted_text`
  and continues with the classifier/workers pipeline.

This delivers most of the user-visible benefit (no blank spinner before
classification starts) without requiring queue infrastructure. The full
two-phase upload — separate `POST /upload` returning 202 + `GET
/upload/<id>/events` for the live stream — remains deferred per the
original design below, since it needs a worker tier to survive crashes
and a documents.processing_status state machine.

The current flag is safe: a worker crash during OCR still loses the
upload, same as today, but no worse. Pair with ADR 0011 (DBOS) for
crash recovery.

## Context

`backend/services/extraction_service.py::extract_text_from_file` currently runs synchronously inside the upload route. A 14-page scanned PDF blocks the request for 3–5s before any agent runs. Bad scans can hold the connection for 20s+. The user sees nothing during this phase — the SSE stream hasn't even opened.

The agentic pipeline downstream is observable, streamed, and bounded; OCR is the remaining blocking step on the upload critical path.

## Proposed design (not implemented)

Two-phase upload:

1. **Phase 1 — synchronous accept (sub-second)**: client POSTs the file. Backend writes the raw bytes to Supabase Storage, inserts a `documents` row with `processing_status='pending'`, returns `{document_id, status: "queued"}` with HTTP 202.

2. **Phase 2 — background processing**: a worker (Celery/RQ/Dramatiq, or a Vercel Sandbox if the project is moving that direction) picks up the queued job, runs OCR, then runs the agent pipeline, then writes results back to the row.

3. **Live updates**: client opens a follow-up SSE connection at `GET /api/documents/<id>/events` that streams `progress` events for OCR and agent steps in real time. When `processing_status='complete'`, the stream emits `result` and closes.

## Why this is deferred, not built

- Adds queue infrastructure (Celery/RQ) we don't currently run — this is a deployment surface, not just a code change.
- Requires a `processing_status` enum on `documents` and a state machine for transitions (`pending → ocr → classifying → extracting → graph_updating → complete | failed`).
- The frontend SSE consumer (`uploadDocumentStream`) needs to support resumption — connecting to a stream for an upload that's already in progress, possibly missing earlier events.
- Crash recovery semantics (related to 0011 below): what happens if the worker crashes mid-OCR? The status row is the durability surface; a separate ADR covers durable execution.
- We have no production data on actual OCR latency distribution. Could be that 95% of uploads take <2s and the optimization is theoretical.

## When to revisit

- After the next 200 uploads, pull p95 OCR latency from Logfire. If p95 > 5s, build this. If p95 < 2s, defer indefinitely.
- If we see browser timeouts on uploads (no events, then `network error`), that's the trigger to ship even with worse latency numbers.
- If we add file size limits beyond 15MB, OCR latency will scale and this becomes load-bearing.

## What I'd try next (if implementing)

1. Add `processing_status` column and state machine to `documents`.
2. Pick a queue: Dramatiq is the lowest-overhead option for FastAPI today.
3. Move `extract_text_from_file` and `process_document` into a single Dramatiq actor.
4. Add `GET /api/documents/<id>/events` that polls the row state and yields SSE events, closing when terminal.
5. Update `uploadDocumentStream` in `frontend/src/lib/api.ts`: phase 1 returns the doc_id, phase 2 opens the events stream against `<id>/events`.
6. Wire idempotency keys (`X-Request-ID` already in place per ADR 0009) so client retries don't double-queue.
