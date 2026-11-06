"""#759 — the upload SSE stream's terminal state matches what was persisted.

Workstream C of the implicit-state-machine audit. Each test pins one
finding from the issue:

  * the idempotent-replay `result` carries the SAME shape a fresh run does;
  * the replay lookup runs off the event loop, and a lost check-then-act race
    (the unique `(user_id, request_id)` index rejects the insert) adopts the
    winner's row instead of reporting "could not be saved";
  * post-roll tasks are strongly referenced and drained at shutdown;
  * the course-context refresh gets the OFFERING id, not the abstract course.

Separate file from test_documents_routes.py so parallel workstreams editing
that one do not collide.
"""
import asyncio
import io
import json
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from main import app

client = TestClient(app)

_TEXT = (
    "document. This sample body gives the upload fixture enough extracted "
    "text to look like a document that was actually read successfully."
)


def _parse_sse(raw: bytes) -> list[tuple[str, dict]]:
    events: list[tuple[str, dict]] = []
    cur: dict = {}
    for line in raw.decode("utf-8").splitlines():
        if not line.strip():
            if cur:
                events.append((cur["event"], json.loads(cur["data"])))
                cur = {}
            continue
        if line.startswith(":") or ":" not in line:
            continue
        field, _, value = line.partition(":")
        cur[field.strip()] = value.lstrip()
    if cur:
        events.append((cur["event"], json.loads(cur["data"])))
    return events


def _agent_patches():
    from agents.classifier import DocumentClassification
    from agents.concept_extraction import Concept, ConceptList
    from agents.summary import Summary

    cls = DocumentClassification(
        category="lecture_notes", is_syllabus=False, confidence=0.9, rationale="t",
    )
    summary = Summary(headline="h", abstract="Fresh abstract.", key_points=["a", "b", "c"])
    concepts = ConceptList(concepts=[Concept(name="Backprop", description="d", importance=0.9)])
    return (
        patch("routes.documents.classifier_agent.run",
              AsyncMock(return_value=SimpleNamespace(output=cls))),
        patch("routes.documents.summary_agent.run",
              AsyncMock(return_value=SimpleNamespace(output=summary))),
        patch("routes.documents.concept_extraction_agent.run",
              AsyncMock(return_value=SimpleNamespace(output=concepts))),
        patch("routes.documents.apply_concepts_to_graph", AsyncMock(return_value=0)),
    )


def _stream_upload(headers: dict | None = None) -> list[tuple[str, dict]]:
    with client.stream(
        "POST", "/api/documents/upload",
        files={"file": ("notes.pdf", io.BytesIO(b"%PDF-1.4 x"), "application/pdf")},
        data={"course_id": "c-1", "user_id": "u1"},
        headers=headers or {},
    ) as r:
        assert r.status_code == 200
        return _parse_sse(r.read())


def _steps(events):
    return [(t, d["step"]) for t, d in events]


# ── Replay payload shape ─────────────────────────────────────────────────────

class TestReplayResultShape:
    def test_replay_result_matches_the_fresh_result_shape(self):
        """A replay used to send the raw DB row (`summary` a string,
        `concept_notes`, top-level `category`) under the same `result` event a
        fresh run fills with a DocumentProcessingResult dump. One event type,
        one shape: the replay is normalised to the fresh keys."""
        existing = {
            "id": "doc-replayed",
            "user_id": "u1",
            "offering_id": "off-1",
            "file_name": "notes.pdf",
            "category": "syllabus",
            "summary": "Stored abstract.",
            "concept_notes": [{"name": "Chain Rule", "description": "d"}],
            "created_at": "2026-01-01T00:00:00Z",
            "processed_at": "2026-01-01T00:00:00Z",
        }
        with (
            patch("routes.documents._validate_user"),
            patch("routes.documents.extract_text_from_file", return_value=_TEXT),
            patch("routes.documents._existing_doc_by_request_id", return_value=existing),
        ):
            events = _stream_upload({"X-Request-ID": "trace-replay-shape-1"})

        assert _steps(events) == [("status", "start"), ("result", "finalize"), ("status", "done")]
        data = events[1][1]["data"]
        assert data["classification"]["category"] == "syllabus"
        assert data["classification"]["is_syllabus"] is True
        assert data["summary"]["abstract"] == "Stored abstract."
        assert [c["name"] for c in data["concepts"]["concepts"]] == ["Chain Rule"]
        assert data["id"] == "doc-replayed"
        assert data["replayed"] is True
        # The fresh shape has no DB-row keys.
        assert "concept_notes" not in data
        assert "category" not in data
        assert events[2][1]["data"]["document_id"] == "doc-replayed"


# ── Replay lookup: off-loop, and the race the unique index arbitrates ───────

class TestReplayLookup:
    def test_replay_lookup_runs_off_the_event_loop(self):
        """`_existing_doc_by_request_id` is a synchronous PostgREST round trip;
        calling it inline blocked the loop serving every other stream."""
        on_loop: list[bool] = []

        def lookup(_user_id, _request_id):
            try:
                asyncio.get_running_loop()
                on_loop.append(True)
            except RuntimeError:
                on_loop.append(False)
            return None

        a, b, c, d = _agent_patches()
        with (
            patch("routes.documents._validate_user"),
            patch("routes.documents.extract_text_from_file", return_value=_TEXT),
            patch("routes.documents._existing_doc_by_request_id", side_effect=lookup),
            a, b, c, d,
            patch("routes.documents._persist_document", return_value=("doc-1", {})),
            patch("routes.documents._spawn_post_roll"),
        ):
            _stream_upload()

        assert on_loop and not any(on_loop)

    def test_insert_losing_the_request_id_race_adopts_the_winner(self):
        """Check-then-act: two attempts with one X-Request-ID both miss the
        lookup; the unique (user_id, request_id) index rejects the loser's
        insert. That document WAS saved — by the other attempt — so the loser
        reports it as saved instead of telling the student it was lost."""
        winner = {"id": "doc-winner", "summary": None, "concept_notes": []}
        lookups = iter([None, winner])
        a, b, c, d = _agent_patches()
        with (
            patch("routes.documents._validate_user"),
            patch("routes.documents.extract_text_from_file", return_value=_TEXT),
            patch("routes.documents._existing_doc_by_request_id",
                  side_effect=lambda *_: next(lookups)),
            a, b, c, d,
            patch("routes.documents._persist_document",
                  side_effect=RuntimeError("409 duplicate key value (23505)")),
            patch("routes.documents._spawn_post_roll") as spawn,
        ):
            events = _stream_upload({"X-Request-ID": "trace-race-1"})

        assert ("error", "failed") not in _steps(events)
        assert events[-1][0] == "status" and events[-1][1]["step"] == "done"
        assert events[-1][1]["data"]["document_id"] == "doc-winner"
        # The winner already spawned the side effects for its row.
        spawn.assert_not_called()

    def test_persist_failure_with_no_winner_is_still_terminal_failure(self):
        a, b, c, d = _agent_patches()
        with (
            patch("routes.documents._validate_user"),
            patch("routes.documents.extract_text_from_file", return_value=_TEXT),
            patch("routes.documents._existing_doc_by_request_id", return_value=None),
            a, b, c, d,
            patch("routes.documents._persist_document", side_effect=RuntimeError("boom")),
            patch("routes.documents._spawn_post_roll") as spawn,
        ):
            events = _stream_upload()

        assert _steps(events)[-2:] == [("error", "failed"), ("status", "done")]
        assert "document_id" not in (events[-1][1].get("data") or {})
        spawn.assert_not_called()


# ── Post-roll spawning: a spawn failure is not a save failure ───────────────

class TestPostRollAfterPersist:
    def test_spawn_failure_after_persist_still_reports_saved(self):
        """The row exists once `_persist_document` returns. A failure spawning
        the best-effort side effects must not flip the stream to error:failed
        — the client would show "not saved" for a document in the library."""
        a, b, c, d = _agent_patches()
        with (
            patch("routes.documents._validate_user"),
            patch("routes.documents.extract_text_from_file", return_value=_TEXT),
            patch("routes.documents._existing_doc_by_request_id", return_value=None),
            a, b, c, d,
            patch("routes.documents._persist_document", return_value=("doc-saved", {})),
            patch("routes.documents._spawn_post_roll", side_effect=RuntimeError("no loop")),
        ):
            events = _stream_upload()

        assert ("error", "failed") not in _steps(events)
        assert events[-1][1]["data"]["document_id"] == "doc-saved"


class TestPostRollTaskLifetime:
    def test_spawned_tasks_are_strongly_referenced_until_done(self):
        """A bare create_task result is only weakly referenced by the loop and
        can be garbage-collected mid-flight. The module keeps each one in a
        set and drops it once it finishes."""
        from routes import documents

        release = threading.Event()
        ran: list[str] = []

        def work(tag):
            release.wait(5)
            ran.append(tag)

        async def run():
            documents._spawn_post_roll(("work", work, "a"))
            held = [t for t in documents._POST_ROLL_TASKS if not t.done()]
            assert len(held) == 1
            release.set()
            await documents.drain_post_roll(timeout=5)
            return held[0]

        task = asyncio.run(run())
        assert task.done()
        assert ran == ["a"]
        assert task not in documents._POST_ROLL_TASKS

    def test_drain_is_bounded_and_never_raises(self):
        from routes import documents

        release = threading.Event()

        def stuck():
            release.wait(5)

        async def run():
            documents._spawn_post_roll(("stuck", stuck))
            await documents.drain_post_roll(timeout=0.05)
            pending = [t for t in documents._POST_ROLL_TASKS if not t.done()]
            release.set()
            await documents.drain_post_roll(timeout=5)
            return pending

        assert len(asyncio.run(run())) == 1

    def test_drain_with_nothing_spawned_is_a_noop(self):
        from routes import documents

        asyncio.run(documents.drain_post_roll(timeout=0.01))

    def test_app_lifespan_drains_post_roll_on_shutdown(self):
        drain = AsyncMock()
        with (
            patch("routes.documents.drain_post_roll", new=drain),
            patch("main.ensure_bucket_exists", new=AsyncMock()),
            patch("main.start_sweeper"),
            patch("main.stop_sweeper", new=AsyncMock()),
        ):
            with TestClient(app):
                drain.assert_not_called()
            drain.assert_awaited_once()


# ── Course-context refresh keys on the offering ─────────────────────────────

class TestCourseContextOffering:
    def test_streaming_upload_refreshes_the_offering_context(self):
        """update_course_context(offering_id) reads enrollments by offering.
        Passing the abstract course id matched no enrollment, so the refresh
        purged nothing useful and cleared the whole cache instead."""
        from routes import documents

        a, b, c, d = _agent_patches()
        with (
            patch("routes.documents._validate_user"),
            patch("routes.documents.resolve_offering", return_value="off-7"),
            patch("routes.documents.extract_text_from_file", return_value=_TEXT),
            patch("routes.documents._existing_doc_by_request_id", return_value=None),
            a, b, c, d,
            patch("routes.documents._persist_document", return_value=("doc-1", {})),
            patch("routes.documents._spawn_post_roll") as spawn,
        ):
            _stream_upload()

        tasks = {task[0]: task[1:] for task in spawn.call_args.args}
        assert tasks["update_course_context"] == (documents.update_course_context, "off-7")

    def test_sync_upload_refreshes_the_offering_context(self):
        from agents.document import DocumentProcessingResult
        from agents.classifier import DocumentClassification
        from agents.concept_extraction import Concept, ConceptList
        from agents.summary import Summary

        result = DocumentProcessingResult(
            classification=DocumentClassification(
                category="lecture_notes", is_syllabus=False, confidence=0.9, rationale="t",
            ),
            summary=Summary(headline="h", abstract="a.", key_points=["a", "b", "c"]),
            concepts=ConceptList(concepts=[Concept(name="X", description="d", importance=0.5)]),
            graph_updated=True,
        )
        refresh = MagicMock()
        with (
            patch("routes.documents._validate_user"),
            patch("routes.documents.resolve_offering", return_value="off-7"),
            patch("routes.documents.extract_text_from_file", return_value=_TEXT),
            patch("routes.documents._existing_doc_by_request_id", return_value=None),
            patch("routes.documents.process_document", AsyncMock(return_value=result)),
            patch("routes.documents._persist_document", return_value=("doc-1", {"id": "doc-1"})),
            patch("routes.documents.update_course_context", refresh),
            patch("routes.documents._invalidate_study_guide_cache"),
            patch("routes.documents._check_upload_achievements"),
            patch("routes.documents.index_document"),
        ):
            r = client.post(
                "/api/documents/upload/sync",
                files={"file": ("notes.pdf", io.BytesIO(b"%PDF-1.4 x"), "application/pdf")},
                data={"course_id": "c-1", "user_id": "u1"},
            )
        assert r.status_code == 200
        refresh.assert_called_once_with("off-7")
