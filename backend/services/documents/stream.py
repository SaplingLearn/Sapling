"""
backend/services/documents/stream.py

The streaming upload's event stream (#118, moved from routes/documents.py's
upload_document): idempotent replay, the queued relay (#116), async-OCR
extraction, the one agent pipeline, and the post-roll persistence.
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import aclosing

from pydantic_ai.exceptions import UsageLimitExceeded, UnexpectedModelBehavior

from agents.deps import SaplingDeps
from agents.document import DocumentProcessingResult
from services import document_jobs, document_pipeline, events_service
from services.agent_events import SaplingEvent, sapling_event_to_sse
from services.document_indexing import schedule_document_index
from services.documents.persistence import (
    _existing_doc_by_request_id,
    _graph_backstop,
    _persist_document,
    _replay_result_payload,
    _save_orchestrator_syllabus,
)
from services.documents.post_roll import (
    _check_upload_achievements,
    _invalidate_study_guide_cache,
    _refresh_course_context,
    _spawn_post_roll,
)
from services.documents.upload import (
    UNREADABLE_DOCUMENT_DETAIL,
    _budget_failed_frames,
    _has_usable_text,
)
from services.extraction_service import extract_text_from_file
from services.llm_budget import LLMBudgetExceeded

logger = logging.getLogger(__name__)


async def upload_event_stream(
    *,
    existing: dict | None,
    user_id: str,
    course_id: str,
    offering_id: str | None,
    request_id: str,
    filename: str,
    content_type: str | None,
    file_bytes: bytes,
    deps: SaplingDeps,
    queued: bool,
    extracted_text: str | None,
):
    """The streaming upload's SSE frames (POST /api/documents/upload; #118:
    was the route's nested ``event_stream``). Emits status/progress/result/
    error events while the pipeline runs, then a final 'done' status with the
    persisted document_id once side-effects complete."""
    try:
        yield sapling_event_to_sse(SaplingEvent(
            type="status", step="start",
            message="Document received. Processing...",
        ))

        # Idempotency (looked up above, before the gate): emit a
        # result+done pair built from the previously persisted row
        # instead — in the fresh result's shape (#759).
        if existing:
            yield sapling_event_to_sse(SaplingEvent(
                type="result", step="finalize",
                message="Already processed (idempotent replay).",
                data=_replay_result_payload(existing),
            ))
            yield sapling_event_to_sse(SaplingEvent(
                type="status", step="done",
                message="Saved.",
                data={"document_id": existing.get("id"), "request_id": request_id},
            ))
            return

        # #117: one document.upload per accepted upload attempt — AFTER
        # the idempotent-replay short-circuit (PR #465 review), so an
        # X-Request-ID retry doesn't inflate the count. char_count is
        # unknown (None) when OCR_ASYNC_ENABLED defers extraction below —
        # document.processed carries the real count once extraction ran.
        events_service.log_event(
            "document.upload",
            category="usage",
            user_id=user_id,
            request_id=request_id,
            payload={
                "course_id": course_id,
                "offering_id": offering_id,
                "char_count": len(extracted_text) if extracted_text is not None else None,
            },
        )

        # ── Queued (#116): the worker runs it; relay its progress ─────────
        if queued:
            upload_id = await asyncio.to_thread(
                document_jobs.stage_and_enqueue,
                user_id=user_id, offering_id=offering_id, course_id=course_id,
                request_id=request_id, filename=filename,
                content_type=content_type, file_bytes=file_bytes,
            )
            if upload_id is not None:
                watch = document_jobs.Watch()
                async for ev in document_jobs.stream_events(
                    upload_id, request_id=request_id, outcome=watch,
                ):
                    yield sapling_event_to_sse(ev)
                if watch.kind != document_jobs.INLINE:
                    return

        # ── Phase 0: text extraction (when OCR_ASYNC_ENABLED) ─────────────
        # Failures here can NOT fall through to the legacy fallback —
        # the legacy path uses the same extractor, and would crash on
        # `extracted_text=None`. Emit a terminal error+done pair and
        # return so the client gets a clean failure instead of a
        # double-fault.
        if extracted_text is None:
            yield sapling_event_to_sse(document_pipeline.extracting_text_event())
            try:
                extracted_text = await asyncio.to_thread(
                    extract_text_from_file, file_bytes, filename,
                    content_type or "",
                )
            except LLMBudgetExceeded as e:
                # #119: vision OCR refused by the per-user LLM budget.
                for frame in _budget_failed_frames(e, request_id):
                    yield frame
                return
            except Exception:
                logger.exception(
                    "Async text extraction failed for '%s'", filename,
                )
                yield sapling_event_to_sse(SaplingEvent(
                    type="error", step="failed",
                    message="Could not read this document. Please try a different file.",
                    data={"request_id": request_id},
                ))
                yield sapling_event_to_sse(SaplingEvent(
                    type="status", step="done",
                    message="Failed.",
                ))
                return
            yield sapling_event_to_sse(
                document_pipeline.extracted_text_event(len(extracted_text)))
            # Extraction can succeed and still yield nothing usable -- a
            # rasterized PDF has no text layer, so the except branch above
            # never fires. Stop here rather than asking the model to
            # summarize an empty document, which it answers by inventing
            # one (see MIN_EXTRACTED_CHARS). Same terminal error+done pair
            # as the extraction-failure path, so clients need no new case.
            if not _has_usable_text(extracted_text):
                logger.warning(
                    "Async extraction yielded %d usable chars for '%s' - "
                    "rejecting as unreadable",
                    len((extracted_text or "").strip()), filename,
                )
                yield sapling_event_to_sse(SaplingEvent(
                    type="error", step="failed",
                    message=UNREADABLE_DOCUMENT_DETAIL,
                    data={"request_id": request_id},
                ))
                yield sapling_event_to_sse(SaplingEvent(
                    type="status", step="done",
                    message="Failed.",
                ))
                return

        # ── Phases 1-3: the one pipeline (agents.document) ────────────────
        # classify -> summary/concepts(/syllabus) in parallel -> graph
        # merge, each boundary relayed as its progress events (#835: the
        # same steps and events a queued upload's worker records).
        final_output: DocumentProcessingResult | None = None
        async with aclosing(document_pipeline.run_document_agents(extracted_text, deps)) as steps:
            async for step in steps:
                for ev in document_pipeline.step_events(step):
                    yield sapling_event_to_sse(ev)
                if step.name == document_pipeline.DONE:
                    final_output = step.result
        yield sapling_event_to_sse(SaplingEvent(
            type="result", step="finalize",
            message="Processing complete.",
            data=final_output.model_dump(mode="json"),
        ))
    except LLMBudgetExceeded as e:
        # #119: the per-user LLM budget refused the pipeline before any
        # model call; nothing was persisted. Same terminal tail, with the
        # budget's own message instead of "please try again".
        for frame in _budget_failed_frames(e, request_id):
            yield frame
        return
    except (UsageLimitExceeded, UnexpectedModelBehavior) as e:
        # Terminal (#151b): `step="fallback"` left the SSE vocabulary
        # with the legacy pipeline (ADR 0024). Emit the exact
        # error:failed + status:done tail the deleted fallback used on
        # double-failure, so clients need no new case. Retry is safe —
        # nothing was persisted, so a retry (the modal reuses the same
        # X-Request-ID for the same file, #759) finds no row to replay
        # and re-runs the pipeline.
        logger.warning(
            "Agent guardrails tripped during stream for '%s'; failing",
            filename, exc_info=e,
        )
        yield sapling_event_to_sse(SaplingEvent(
            type="error", step="failed",
            message="Document processing failed. Please try again.",
            data={"request_id": request_id} if request_id else None,
        ))
        yield sapling_event_to_sse(SaplingEvent(
            type="status", step="done",
            message="Failed.",
        ))
        return
    except Exception:
        # Same terminal tail; a bare exception is a bug, so keep the
        # full exception log where the guardrail branch logs a WARNING.
        logger.exception("Unexpected streaming failure for '%s'", filename)
        yield sapling_event_to_sse(SaplingEvent(
            type="error", step="failed",
            message="Document processing failed. Please try again.",
            data={"request_id": request_id} if request_id else None,
        ))
        yield sapling_event_to_sse(SaplingEvent(
            type="status", step="done",
            message="Failed.",
        ))
        return

    # ── Post-roll: side effects + persistence (#132 item 11) ──────────
    # Runs AFTER the terminal `result` event is on the wire, in its own
    # try/except. A post-result failure still emits the terminal
    # error:failed + status:done pair and NEVER a second result — the
    # client already holds the processed document, and every emitter in
    # this generator sends at most one result per stream. The legacy
    # fallback this separation used to guard against re-triggering
    # (result → error → result → done, plus a second model call) is
    # GONE (#151b, ADR 0024); the separate try/except now simply keeps
    # the post-result failure tail identical to the pre-result failure
    # branches above. #154 builds on this structure — keep persistence
    # in the post-roll, after the result event.
    try:
        # Synchronous PostgREST writes — threaded so they don't block
        # the event loop serving this (and every other) SSE stream
        # (#132 item 22; same pattern as the async-OCR extraction above).
        await asyncio.to_thread(
            _save_orchestrator_syllabus,
            user_id=user_id, course_id=course_id,
            filename=filename, result=final_output,
        )
        await asyncio.to_thread(
            _graph_backstop,
            user_id=user_id, course_id=course_id,
            filename=filename, result=final_output,
        )
        try:
            doc_id, _ = await asyncio.to_thread(
                _persist_document,
                user_id=user_id, offering_id=offering_id,
                filename=filename, result=final_output,
                request_id=request_id,
                course_id=course_id,
                char_count=len(extracted_text) if extracted_text is not None else None,
                extracted_text=extracted_text,
            )
            adopted = False
        except Exception:
            # #759: the replay lookup at the top is check-then-act. Two
            # attempts sharing an X-Request-ID can both miss it; the
            # unique (user_id, request_id) index then rejects the
            # loser's insert. That document WAS saved — by the winner —
            # so adopt its row rather than report it lost.
            winner = await asyncio.to_thread(
                _existing_doc_by_request_id, user_id, request_id,
            )
            if not winner or not winner.get("id"):
                raise
            doc_id, adopted = winner["id"], True
            logger.info(
                "Upload '%s' lost the request_id race; adopting %s",
                filename, doc_id,
            )
    except Exception:
        logger.exception(
            "Post-result persistence failed for '%s' — result already "
            "sent, so no legacy fallback (it would re-run the pipeline "
            "and emit a second result)", filename,
        )
        yield sapling_event_to_sse(SaplingEvent(
            type="error", step="failed",
            message="The document was processed but could not be saved. "
                    "Please try uploading it again.",
            data={"request_id": request_id} if request_id else None,
        ))
        yield sapling_event_to_sse(SaplingEvent(
            type="status", step="done",
            message="Failed.",
        ))
        return

    # The row exists from here on, so nothing below may turn this stream
    # into error:failed — the client would show "not saved" for a
    # document sitting in the library (#759). The side effects are
    # best-effort; the winner of a request_id race already spawned them.
    #
    # BackgroundTasks runs after response close — useless for SSE since
    # the stream IS the response. _spawn_post_roll holds each task and
    # logs its exception; drain_post_roll waits for them at shutdown.
    if not adopted:
        try:
            _spawn_post_roll(
                ("invalidate_study_guide_cache", _invalidate_study_guide_cache, user_id, offering_id),
                # update_course_context aggregates an OFFERING (#759).
                ("update_course_context", _refresh_course_context, offering_id, user_id),
                ("check_upload_achievements", _check_upload_achievements, user_id),
                # #482: the id only. The indexer reads everything else off
                # the stored row, which is what lets the sweeper re-drive
                # this same work if the attempt below dies with the process.
                ("index_document", schedule_document_index, doc_id, user_id),
            )
        except Exception:
            logger.exception("Post-roll spawn failed for '%s' (document %s saved)",
                             filename, doc_id)

    yield sapling_event_to_sse(SaplingEvent(
        type="status", step="done",
        message="Saved.",
        data={"document_id": doc_id},
    ))
