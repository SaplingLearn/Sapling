"""Spec §13 A128: the learning loop is honest when its dependencies are down,
and the evidence-producing model slots are guarded.

Live, 2026-11-07: the dev Gemini key was invalid, every embed call failed
`400 API_KEY_INVALID`, indexing stored nothing, every tutor turn retried
retrieval and silently got nothing, the student was never told, and items were
drafted from extracted text with no source chunk. Each section pins one fix:

- the embeddings circuit breaker (services/rag_service.py);
- indexing and the sweeper back off while it is open;
- the loop tells a FAILED retrieval from an empty one, tags the step, and
  serves one calm note per session from a response field;
- items drafted after a failed index are stored `unsourced`, and selection
  prefers items with their sources;
- the per-document drafting status and the loop's "preparing" state;
- the unevaluated-slot guard and A22's independence check.
"""

from __future__ import annotations

import logging
import threading
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from google.genai import errors as genai_errors

from learning.checks import CheckItem, select_item
from services import rag_service
from tests import test_document_indexing as _indexing
from tests import test_learn_loop_routes as _routes
from tests.test_learn_loop_routes import (
    ITEM,
    PLAN_STATE,
    _fake_stream,
    _graded,
    _json_agent,
    _sse_events,
    client,
)

# the route suite's fixtures (no_rate_limit is autouse there, so here too)
gate_on, no_rate_limit, seams = _routes.gate_on, _routes.no_rate_limit, _routes.seams
# the indexing suite's in-memory documents table and its spies
db, events, visibility = _indexing.db, _indexing.events, _indexing.visibility


# ── the embeddings circuit breaker ──────────────────────────────────────────


def _api_key_invalid() -> genai_errors.ClientError:
    """The live failure, as google-genai raises it."""
    return genai_errors.ClientError(
        400,
        {
            "error": {
                "code": 400,
                "message": "API key not valid. Please pass a valid API key.",
                "status": "INVALID_ARGUMENT",
                "details": [
                    {
                        "@type": "type.googleapis.com/google.rpc.ErrorInfo",
                        "reason": "API_KEY_INVALID",
                        "domain": "googleapis.com",
                    }
                ],
            }
        },
    )


def _server_error() -> genai_errors.ServerError:
    return genai_errors.ServerError(
        503, {"error": {"code": 503, "message": "overloaded", "status": "UNAVAILABLE"}}
    )


def _bad_input() -> genai_errors.ClientError:
    """THIS request's problem (an oversized input), not the service's."""
    return genai_errors.ClientError(
        400, {"error": {"code": 400, "message": "too long", "status": "INVALID_ARGUMENT"}}
    )


def _vectors(n: int = 1):
    resp = MagicMock()
    resp.embeddings = [MagicMock(values=[0.1] * 768) for _ in range(n)]
    return resp


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def breaker(monkeypatch):
    """A fresh breaker on a fake monotonic clock, a scripted embed client, and
    the breaker's events captured."""
    monkeypatch.setenv("SAPLING_MODEL_MODE", "real")
    clock = _Clock()
    fresh = rag_service._EmbeddingBreaker(clock=clock)
    monkeypatch.setattr(rag_service, "_BREAKER", fresh)
    client_ = MagicMock()
    monkeypatch.setattr(rag_service, "_client", client_)
    seen: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        rag_service, "log_event", lambda event_type, **kw: seen.append((event_type, kw))
    )
    return SimpleNamespace(breaker=fresh, clock=clock, client=client_, events=seen)


def _opens(events) -> list[dict]:
    return [kw["payload"] for et, kw in events if et == "rag.embedding_breaker_open"]


def test_n_consecutive_service_failures_open_the_breaker(breaker):
    breaker.client.models.embed_content.side_effect = _server_error()
    for _ in range(rag_service.EMBED_BREAKER_FAILURES - 1):
        assert rag_service.retrieve_chunks_detailed("q", course_id="CS1").failed
        assert breaker.breaker.state() == "closed"
    assert rag_service.retrieve_chunks_detailed("q", course_id="CS1").failed
    assert breaker.breaker.state() == "open" and rag_service.embedding_blocked()
    calls = breaker.client.models.embed_content.call_count
    assert calls == rag_service.EMBED_BREAKER_FAILURES

    # while open: reported as FAILED, never as empty, and no call goes out
    got = rag_service.retrieve_chunks_detailed("q", course_id="CS1")
    assert got == rag_service.Retrieval(chunks=[], failed=True)
    assert breaker.client.models.embed_content.call_count == calls
    (opened,) = _opens(breaker.events)
    assert opened == {
        "reason": "failures",
        "trial": False,
        "error_type": "ServerError",
        "status_code": 503,
        "failures": rag_service.EMBED_BREAKER_FAILURES,
        "cooldown_s": int(rag_service.EMBED_BREAKER_COOLDOWN_S),
    }


def test_a_success_resets_the_consecutive_count(breaker):
    breaker.client.models.embed_content.side_effect = [
        _server_error(),
        _server_error(),
        _vectors(),
        _server_error(),
        _server_error(),
    ]
    with patch("services.rag_service.rpc", return_value=[]):
        for _ in range(5):
            rag_service.retrieve_chunks_detailed("q", course_id="CS1")
    assert breaker.breaker.state() == "closed", "never three failures IN A ROW"


def test_an_auth_error_opens_it_at_once(breaker, caplog):
    """API_KEY_INVALID is a 400 that no retry can fix: one call opens it."""
    breaker.client.models.embed_content.side_effect = _api_key_invalid()
    with caplog.at_level(logging.WARNING, logger="services.rag_service"):
        assert rag_service.retrieve_chunks_detailed("q", course_id="CS1").failed
    assert breaker.breaker.state() == "open"
    (opened,) = _opens(breaker.events)
    assert opened["reason"] == "auth" and opened["failures"] == 1
    assert opened["status_code"] == 400 and opened["error_type"] == "ClientError"
    warned = [r for r in caplog.records if "breaker OPEN" in r.getMessage()]
    assert len(warned) == 1 and "API_KEY_INVALID" in warned[0].getMessage()
    # never the message (it can quote input): the class, the status, the reason
    assert "not valid" not in warned[0].getMessage()


@pytest.mark.parametrize(
    "exc",
    [
        genai_errors.ClientError(401, {"error": {"code": 401, "status": "UNAUTHENTICATED"}}),
        genai_errors.ClientError(403, {"error": {"code": 403, "status": "PERMISSION_DENIED"}}),
        RuntimeError("wrapped: 400 INVALID_ARGUMENT API_KEY_INVALID"),
    ],
)
def test_every_auth_class_failure_opens_at_once(breaker, exc):
    breaker.breaker.failed(exc)
    assert breaker.breaker.state() == "open"


def test_a_request_specific_400_never_opens_it(breaker):
    """One oversized document must not pause every student's retrieval."""
    breaker.client.models.embed_content.side_effect = _bad_input()
    for _ in range(rag_service.EMBED_BREAKER_FAILURES + 2):
        rag_service.retrieve_chunks_detailed("q", course_id="CS1")
    assert breaker.breaker.state() == "closed" and _opens(breaker.events) == []


def test_it_cools_down_then_one_trial_closes_it(breaker):
    breaker.client.models.embed_content.side_effect = _api_key_invalid()
    rag_service.retrieve_chunks_detailed("q", course_id="CS1")
    assert breaker.breaker.state() == "open"

    breaker.clock.now += rag_service.EMBED_BREAKER_COOLDOWN_S - 1
    assert rag_service.retrieve_chunks_detailed("q", course_id="CS1").failed
    assert breaker.client.models.embed_content.call_count == 1, "still cooling down"

    breaker.clock.now += 1
    assert breaker.breaker.state() == "half_open" and not rag_service.embedding_blocked()
    breaker.client.models.embed_content.side_effect = None
    breaker.client.models.embed_content.return_value = _vectors()
    with patch("services.rag_service.rpc", return_value=[]):
        got = rag_service.retrieve_chunks_detailed("q", course_id="CS1")
        assert got.failed is False and got.chunks == []  # an empty result, honestly empty
        assert breaker.breaker.state() == "closed"
        rag_service.retrieve_chunks_detailed("q", course_id="CS1")
    assert breaker.client.models.embed_content.call_count == 3
    assert len(_opens(breaker.events)) == 1


def test_a_failed_trial_re_opens_it_with_one_more_event(breaker):
    breaker.client.models.embed_content.side_effect = _api_key_invalid()
    rag_service.retrieve_chunks_detailed("q", course_id="CS1")
    breaker.clock.now += rag_service.EMBED_BREAKER_COOLDOWN_S
    breaker.client.models.embed_content.side_effect = _server_error()
    assert rag_service.retrieve_chunks_detailed("q", course_id="CS1").failed
    assert breaker.breaker.state() == "open", "a failed trial re-opens at once"
    first, second = _opens(breaker.events)
    assert first["reason"] == "auth" and second["trial"] is True
    assert breaker.client.models.embed_content.call_count == 2


def test_only_one_trial_goes_out_while_half_open(breaker):
    breaker.breaker.failed(_api_key_invalid())
    breaker.clock.now += rag_service.EMBED_BREAKER_COOLDOWN_S
    breaker.breaker.before_call()  # the trial, in flight
    assert rag_service.embedding_blocked(), "the sweeper waits for the trial"
    with pytest.raises(rag_service.EmbeddingUnavailable):
        breaker.breaker.before_call()


def test_a_failure_that_lands_after_the_open_reports_nothing_more(breaker):
    """A call that began before the breaker opened and fails after it is the
    same outage: one log, one event per open."""
    for _ in range(rag_service.EMBED_BREAKER_FAILURES + 3):
        breaker.breaker.failed(_server_error())
    assert len(_opens(breaker.events)) == 1


def test_concurrent_failures_open_it_once(breaker):
    """Thread-safe: request threads, the indexing post-roll and the sweeper
    all embed through the one per-process breaker."""
    gate = threading.Barrier(16)

    def fail():
        gate.wait()
        breaker.breaker.failed(_server_error())

    threads = [threading.Thread(target=fail) for _ in range(16)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert breaker.breaker.state() == "open" and len(_opens(breaker.events)) == 1


def test_function_mode_never_reaches_the_breaker(breaker, monkeypatch):
    """The #439 seam is a configured mode: skipped, never failed, and the
    breaker never counts it — function-mode behaviour is unchanged."""
    monkeypatch.setenv("SAPLING_MODEL_MODE", "function")
    for _ in range(5):
        assert rag_service.retrieve_chunks_detailed("q", course_id="CS1") == rag_service.Retrieval(
            chunks=[]
        )
    breaker.client.models.embed_content.assert_not_called()
    assert breaker.breaker.state() == "closed"


def test_indexing_shares_the_breaker_and_stops_at_the_refused_batch(breaker):
    """The query side opened it; the indexer is refused without a call."""
    breaker.breaker.failed(_api_key_invalid())
    with patch("services.rag_service.table") as tbl:
        got = rag_service.index_document_chunks_detailed(
            "CS1", "doc-1", "u1", ["one", "two"], visibility="private", category="lecture_notes"
        )
    assert got.embedding_unavailable is True and got.upserted == 0
    assert got.embed_error == "EmbeddingUnavailable"
    breaker.client.models.embed_content.assert_not_called()
    tbl.assert_not_called()
    assert [et for et, _ in breaker.events] == ["rag.embedding_breaker_open"], (
        "a refused index is a wait the breaker already reported: no chunks_dropped event"
    )


def test_a_breaker_that_opens_mid_document_skips_the_remaining_batches(breaker, monkeypatch):
    texts = [f"chunk {i}" for i in range(120)]  # three embed batches of <= 50
    breaker.client.models.embed_content.side_effect = _api_key_invalid()
    asked = []
    real_before_call = breaker.breaker.before_call
    monkeypatch.setattr(
        breaker.breaker, "before_call", lambda: asked.append(1) or real_before_call()
    )
    got = rag_service.index_document_chunks_detailed(
        "CS1", "doc-1", "u1", texts, visibility="private", category="lecture_notes"
    )
    assert breaker.client.models.embed_content.call_count == 1, "batch 1 went out and failed"
    assert len(asked) == 2, "batch 2 refused, batch 3 never even asked"
    assert got.embedding_unavailable is True and got.embed_error == "ClientError"


# ── indexing and the sweeper back off ───────────────────────────────────────


def test_an_attempt_that_meets_an_open_breaker_spends_nothing(
    db, events, visibility, monkeypatch, caplog
):
    """The process's outage, not the document's failure: the row is put back
    exactly as found — no attempt spent, nothing terminal — and the sweeper
    re-drives it once the breaker closes. No rag.index_failed per document."""
    from services import document_indexing as di

    row = _indexing._doc(db)
    before = dict(row)
    calls = _indexing._rag(monkeypatch, _indexing._Chunks(4, 4))
    monkeypatch.setattr(di, "embedding_blocked", lambda: True)

    with caplog.at_level(logging.INFO, logger="services.document_indexing"):
        out = di.index_document("doc-1")

    assert out.error == di.EMBEDDINGS_UNAVAILABLE
    assert calls == [], "no embed attempt while the breaker is open"
    for col in ("index_status", "index_attempts", "index_error", "index_leased_at"):
        assert row[col] == before[col], col
    assert [e for e, _ in events] == []
    assert any("breaker is open" in r.getMessage() for r in caplog.records)


def test_a_sweeper_claimed_attempt_meeting_the_breaker_is_refunded(
    db, events, visibility, monkeypatch
):
    from services import document_indexing as di

    row = _indexing._doc(
        db, index_status="indexing", index_attempts=2, index_leased_at="2026-11-08T00:00:00Z"
    )
    monkeypatch.setattr(di, "embedding_blocked", lambda: True)
    di.index_document("doc-1", claimed=True)
    assert row["index_status"] == "pending" and row["index_attempts"] == 1
    assert row["index_leased_at"] is None and row["index_error"] is None


def test_a_breaker_that_opens_during_the_attempt_ends_its_retries(
    db, events, visibility, monkeypatch
):
    """This document's own calls may have opened it: the attempt is spent as
    usual (so a document whose content breaks the service still runs out of
    attempts), but it is not retried into a refusal — one try, no sleep."""
    from services import document_indexing as di

    row = _indexing._doc(db)

    @_indexing.dataclass
    class _Refused(_indexing._Chunks):
        embedding_unavailable: bool = True

    calls = _indexing._rag(monkeypatch, _Refused(0, 4, embed_error="ClientError"))
    out = di.index_document("doc-1")
    assert len(calls) == 1
    assert out.status == "failed" and out.error == "ClientError"
    assert row["index_attempts"] == 1 and row["index_status"] == "failed"
    assert [e for e, _ in events] == ["rag.index_failed"]


@pytest.fixture
def sweeper(monkeypatch):
    from services import index_sweeper

    monkeypatch.setenv("SAPLING_MODEL_MODE", "real")
    monkeypatch.delenv("INDEX_SWEEPER_ENABLED", raising=False)
    queue = {"rows": [{"id": f"d{i}"} for i in range(5)], "claims": 0}

    def fake_rpc(fn, params):
        queue["claims"] += 1
        taken, queue["rows"] = queue["rows"][:1], queue["rows"][1:]
        return taken

    monkeypatch.setattr(index_sweeper, "rpc", fake_rpc)
    return index_sweeper, queue


def test_the_sweeper_claims_nothing_while_the_breaker_is_open(sweeper, monkeypatch):
    index_sweeper, queue = sweeper
    monkeypatch.setattr(index_sweeper, "embedding_blocked", lambda: True)
    driven = []
    monkeypatch.setattr(index_sweeper, "index_document", lambda d, **kw: driven.append(d))
    assert index_sweeper.sweep_once() == 0
    assert queue["claims"] == 0 and driven == [], "no attempt spent on an outage"


def test_a_deferred_document_ends_the_pass_instead_of_hot_looping(sweeper, monkeypatch):
    """The deferred row is put back unclaimed, so the next claim could hand
    it straight back: the pass ends on the first deferral."""
    from services.document_indexing import EMBEDDINGS_UNAVAILABLE, IndexOutcome

    index_sweeper, queue = sweeper
    driven = []

    def deferred(doc_id, **kw):
        driven.append(doc_id)
        return IndexOutcome("failed", error=EMBEDDINGS_UNAVAILABLE)

    monkeypatch.setattr(index_sweeper, "index_document", deferred)
    assert index_sweeper.sweep_once() == 0
    assert driven == ["d0"] and queue["claims"] == 1


def test_the_sweeper_drives_the_queue_once_the_breaker_closes(sweeper, monkeypatch):
    from services.document_indexing import IndexOutcome

    index_sweeper, queue = sweeper
    monkeypatch.setattr(
        index_sweeper, "index_document", lambda d, **kw: IndexOutcome("indexed", 3)
    )
    assert index_sweeper.sweep_once() == 5


# ── the loop: a failed retrieval is not an empty one ────────────────────────


def test_context_blocks_tell_a_failed_retrieval_from_an_empty_one():
    from learning import policy
    from routes.learn_loop import _context_blocks
    from services.rag_service import Retrieval

    teach = policy.ContextPolicy(3, False, 0, False, "none")
    kw = dict(user_id="u1", course_id="c1", user_message="hi", item=None, context=teach)
    with patch("routes.learn_loop._get_course_info", return_value={"course_code": "CS111"}):
        for got, want in (
            (Retrieval(chunks=[], failed=True), {"retrieval": "failed"}),
            (Retrieval(chunks=[]), {}),
            (Retrieval(chunks=[{"chunk_text": "r", "similarity": 0.9}]), {}),
        ):
            out: dict = {}
            with patch("routes.learn_loop.retrieve_chunks_detailed", return_value=got):
                blocks = _context_blocks(**kw, out=out)
            assert out == want
            assert bool(blocks) is bool(got.chunks), "a failure never blocks the turn"


def _failing_retrieval(**kw):
    """`_context_blocks` as it runs when the retrieval failed."""
    kw["out"]["retrieval"] = "failed"
    return ["CTX"]


def _teach_json_turn(message="hi"):
    agent, _ = _json_agent()
    with (
        patch("routes.learn_loop.loop_tutor_agent", agent),
        patch("routes.learn_loop.record_agent_usage", side_effect=lambda r, **k: r),
    ):
        return client.post(
            "/api/learn/loop/chat", json={"session_id": "s1", "user_id": "u1", "message": message}
        )


def test_a_failed_retrieval_serves_the_turn_and_the_note_once_per_session(gate_on, seams):
    seams.store["doc"] = {"phase": "teach", "concept": "node-1"}
    seams.blocks.side_effect = _failing_retrieval

    first = _teach_json_turn()
    assert first.status_code == 200 and first.json()["reply"], "never blocks the turn"
    assert first.json()["materials_unavailable"] is True
    doc = seams.store["doc"]
    assert doc["materials_notice"] is True and doc["retrieval_failed"] == ["node-1"]

    second = _teach_json_turn("and then?")
    assert second.status_code == 200 and "materials_unavailable" not in second.json()
    assert seams.store["doc"]["retrieval_failed"] == ["node-1"], "one mark per concept"


def test_a_clean_or_empty_retrieval_serves_no_note(gate_on, seams):
    seams.store["doc"] = {"phase": "teach", "concept": "node-1"}
    r = _teach_json_turn()  # seams' _context_blocks reports nothing: clean
    assert "materials_unavailable" not in r.json()
    assert "materials_notice" not in seams.store["doc"]
    assert "retrieval_failed" not in seams.store["doc"]


def test_the_streamed_turn_carries_the_note_on_done(gate_on, seams):
    seams.store["doc"] = {"phase": "teach", "concept": "node-1"}
    seams.blocks.side_effect = _failing_retrieval
    with patch("routes.learn_loop.stream_structured_turn", _fake_stream()):
        r = client.post(
            "/api/learn/loop/chat/stream",
            json={"session_id": "s1", "user_id": "u1", "message": "hi"},
        )
    done = _sse_events(r.text)[-1]["data"]
    assert done["materials_unavailable"] is True and done["reply"]


def test_the_failed_concept_tags_the_step_it_activates(gate_on, seams):
    """The teaching before a check ran without its course material: the step
    the next activation opens says so, and the mark is consumed."""
    from learning.params import LOOP_TEACH_TURNS_BEFORE_CHECK

    seams.store["doc"] = {
        **PLAN_STATE,
        "plan": dict(PLAN_STATE["plan"]),
        "phase": "teach",
        "teach_turns": LOOP_TEACH_TURNS_BEFORE_CHECK - 1,
    }
    seams.list_items.return_value = [ITEM]
    seams.blocks.side_effect = _failing_retrieval
    r = _teach_json_turn()
    assert r.json()["check"]["question_hash"] == ITEM.question_hash
    doc = seams.store["doc"]
    assert doc["steps"][ITEM.question_hash]["retrieval"] == "failed"
    assert "retrieval_failed" not in doc, "consumed: the concept's NEXT check starts clean"


def test_the_activation_after_clean_teaching_carries_no_tag(gate_on, seams):
    from learning.params import LOOP_TEACH_TURNS_BEFORE_CHECK

    seams.store["doc"] = {
        **PLAN_STATE,
        "plan": dict(PLAN_STATE["plan"]),
        "phase": "teach",
        "teach_turns": LOOP_TEACH_TURNS_BEFORE_CHECK - 1,
    }
    seams.list_items.return_value = [ITEM]
    _teach_json_turn()
    assert "retrieval" not in seams.store["doc"]["steps"][ITEM.question_hash]


@pytest.mark.parametrize("tag,want", [("failed", "failed"), (None, None)])
def test_zpd_step_carries_the_step_retrieval_tag(gate_on, seams, tag, want):
    seams.store["doc"] = _graded("not_yet", **({"retrieval": tag} if tag else {}))
    with patch("routes.learn_loop.stream_structured_turn", _fake_stream("Not yet. Try again?")):
        client.post(
            "/api/learn/loop/chat/stream",
            json={"session_id": "s1", "user_id": "u1", "message": "ok"},
        )
    seams.zpd.emit_zpd_step.assert_called_once()
    assert seams.zpd.emit_zpd_step.call_args.kwargs["retrieval"] == want


def test_emit_zpd_step_payload_key_is_omitted_unless_failed(monkeypatch):
    from learning import zpd_events
    from learning.ladder import Rung

    seen = []
    monkeypatch.setattr(zpd_events, "log_event", lambda et, **kw: seen.append(kw["payload"]))
    base = dict(
        user_id="u1", request_id="r1", concept_id="n1", question_hash="qh", phase="check",
        channel="free_response", band="develop", ceiling=Rung.H3, ceiling_reason="develop",
        first_attempt_correct=True, n_attempts=1, max_rung_used=Rung.H0, rungs=[],
        time_to_first_attempt_ms=1, time_to_correct_ms=1, independent_time_ms=1,
        assisted=False, confidence=0.9, fsrs_rating=3, p_known_before=0.5,
        p_known_after=0.6, r_before=None, item_difficulty=2,
    )
    zpd_events.emit_zpd_step(**base)
    zpd_events.emit_zpd_step(**base, retrieval="failed")
    assert "retrieval" not in seen[0] and seen[1]["retrieval"] == "failed"


def test_the_opener_carries_the_note_into_the_lazy_session(gate_on, seams):
    """A MODEL opener whose retrieval failed — since spec §13 A121, a quiz-ask
    session's first teach turn (A99) — serves the note and carries its key into
    the lazy session. A121's probe-phase opener is a template: it runs no
    model and assembles no context, so it never retrieves and never serves
    the note."""
    from routes.learn_loop import PENDING_SESSIONS
    from tests.test_quiz_ask_session import _opener

    seams.blocks.side_effect = _failing_retrieval
    agent, _ = _json_agent("Welcome. Ready?")
    r, _record = _opener("/api/learn/loop/start-session", agent=agent)
    body = r.json()
    assert body["materials_unavailable"] is True
    pending = PENDING_SESSIONS.pop(body["session_id"])
    assert pending["loop_state"]["materials_notice"] is True, (
        "the materialised session never serves the note a second time"
    )

    seams.blocks.reset_mock()
    topic_p, offering_p, graph_p = _routes._opener_patches()
    with topic_p, offering_p, graph_p:
        r = client.post(
            "/api/learn/loop/start-session", json={"user_id": "u1", "topic": "Recursion"}
        )
    body = r.json()
    assert "materials_unavailable" not in body
    seams.blocks.assert_not_called()  # the template opener assembles no context
    PENDING_SESSIONS.pop(body["session_id"])


# ── unsourced items: provenance, the queue, selection ───────────────────────


def _item(qh: str, *, difficulty: int = 2, flags=None, created="2026-11-01") -> CheckItem:
    return ITEM.model_copy(
        update={
            "id": f"id-{qh}",
            "question_hash": qh,
            "difficulty": difficulty,
            "lint_flags": flags,
            "created_at": created,
        }
    )


def test_selection_prefers_an_item_with_its_sources_at_the_same_difficulty():
    older_unsourced = _item("a", flags=["unsourced"], created="2026-10-01")
    sourced = _item("b", flags=[], created="2026-11-01")
    assert select_item([older_unsourced, sourced], format="free", difficulty=2) is sourced
    # difficulty stays first: the band's target is a learning requirement
    near = _item("c", difficulty=3, flags=[])
    assert select_item([older_unsourced, near], format="free", difficulty=2) is older_unsourced
    # an unsourced item is still served when it is all there is
    assert select_item([older_unsourced], format="free", difficulty=2) is older_unsourced


def test_the_probe_ranks_an_unsourced_item_after_an_equal_sourced_one():
    from learning import probe
    from routes.learn_loop import _BoundItem

    a = _BoundItem(_item("a", flags=["unsourced"]), "n1")
    b = _BoundItem(_item("b", flags=[]), "n1")
    assert a.unsourced is True and b.unsourced is False
    pick = probe.next_probe_item(
        {"n1": 0.5}, [a, b], [], channel_for_format={"free": "free_response"}
    )
    assert pick is b


def test_the_post_test_tiers_put_an_unsourced_item_after_a_clean_one():
    from learning.checks import lint_rank

    assert lint_rank(_item("a", flags=["unsourced"])) > lint_rank(_item("b", flags=[]))


def test_the_flag_survives_a_relint_and_reaches_the_review_queue():
    from learning.item_alignment import kept_flags, merge_flags
    from services.check_item_service import QUEUE_FLAGS, lint_update

    assert "unsourced" in QUEUE_FLAGS
    assert merge_flags(["unsourced"], ["negative_stem"]) == ["negative_stem", "unsourced"]
    assert kept_flags(["unsourced", "correct_longest"]) == ["unsourced"]
    assert lint_update(_item("a", flags=["unsourced"])) is None, "nothing to rewrite"


def test_unsourced_is_no_hold_and_a_hold_still_withdraws_an_unsourced_item():
    """A128 × A123/A124: `unsourced` is provenance, never a hold. An unsourced
    item is servable and its queue entry is not held; a staff or key hold on
    the same item still withdraws it. The stored order puts the staff holds
    last, where the database's check_item_hold_flags appends them, so a write
    and the trigger agree."""
    from learning.checks import (
        HOLD_FLAGS,
        KEY_DISPUTED,
        REPORTS_THRESHOLD,
        STAFF_RETIRED,
        UNSOURCED,
        held_flags,
        is_servable,
    )
    from learning.item_alignment import kept_flags, merge_flags

    assert UNSOURCED not in HOLD_FLAGS
    assert not held_flags([UNSOURCED], False)
    assert is_servable(_item("a", flags=[UNSOURCED]))
    for hold in (REPORTS_THRESHOLD, STAFF_RETIRED):
        assert held_flags([UNSOURCED, hold], True), hold  # a confirmed key lifts no staff hold
        assert not is_servable(_item("b", flags=[UNSOURCED, hold])), hold
    assert held_flags([UNSOURCED, KEY_DISPUTED], False)
    assert not is_servable(_item("c", flags=[UNSOURCED, KEY_DISPUTED]))
    stored = merge_flags([REPORTS_THRESHOLD], [UNSOURCED, "negative_stem"], [KEY_DISPUTED])
    assert stored == ["negative_stem", KEY_DISPUTED, UNSOURCED, REPORTS_THRESHOLD]
    assert kept_flags(stored) == [KEY_DISPUTED, UNSOURCED, REPORTS_THRESHOLD]


def _draft(chunk_ids=()):
    from learning.checks import CheckItemDraft

    return CheckItemDraft(
        concept="Recursion",
        format="free",
        difficulty=2,
        prompt="What stops factorial(0) from recursing?",
        reference_answer="The base case returns 1 when n is 0. Final answer: The base case returns 1.",
        final_answer="The base case returns 1",
        rubric=["Names the base case.", "Says it returns 1."],
        wrong_keys=["no_base"],
        wrong_texts=["Thinks there is no base case."],
        chunk_ids=list(chunk_ids),
    )


def test_a_draft_of_a_failed_index_is_stored_unsourced():
    from services.check_item_service import _build_row

    row = _build_row("c1", "recursion", "doc-1", _draft(), allowed=set(), source_docs=["doc-1"],
                     unsourced=True)
    assert "unsourced" in row["lint_flags"] and row["source_chunk_ids"] == []
    # a draft that cites an indexed chunk has its source, whatever the call showed
    cited = _build_row("c1", "recursion", "doc-1", _draft(["ch-1"]), allowed={"ch-1"},
                       source_docs=["doc-1"], unsourced=True)
    assert "unsourced" not in cited["lint_flags"] and cited["source_chunk_ids"] == ["ch-1"]
    # a skipped index (the #439 seam) drafts unmarked
    clean = _build_row("c1", "recursion", "doc-1", _draft(), allowed=set(), source_docs=["doc-1"])
    assert "unsourced" not in clean["lint_flags"]


def test_a_call_over_failed_index_passages_is_unsourced():
    from services.check_item_service import _call_sources

    failed = {"id": None, "chunk_index": 0, "chunk_text": "t", "doc_id": "d1", "unsourced": True}
    skipped = {"id": None, "chunk_index": 0, "chunk_text": "t", "doc_id": "d2", "unsourced": False}
    indexed = {"id": "ch-1", "chunk_index": 0, "chunk_text": "u", "doc_id": "d3"}
    assert _call_sources([[failed, indexed]]).unsourced is True
    assert _call_sources([[skipped, indexed]]).unsourced is False
    assert _call_sources([[indexed]]).unsourced is False


# ── the drafting status and the "preparing" state ───────────────────────────


@pytest.fixture
def documents(monkeypatch):
    """The documents table as check_item_service writes and reads it."""
    import config
    from services import check_item_service as svc

    monkeypatch.setattr(config, "LEARNING_LOOP_ENABLED", True)
    writes: list[tuple[dict, dict]] = []
    reads: list[dict] = []
    state = {"rows": []}

    class _T:
        def update(self, data, filters, *, prefer_return_minimal=False):
            writes.append((dict(data), dict(filters)))
            return []

        def select(self, columns, filters=None, **kw):
            reads.append(dict(filters or {}))
            return state["rows"]

    monkeypatch.setattr(svc, "table", lambda name: _T())
    return SimpleNamespace(svc=svc, writes=writes, reads=reads, state=state)


def _statuses(documents) -> list[str]:
    return [data["check_items_status"] for data, _ in documents.writes]


@pytest.mark.parametrize(
    "outcome,want",
    [
        ((3, 2, 0, 0), "done"),
        ((0, 0, 0, 2), "done"),  # every concept already full: done, nothing to draft
        ((2, 3, 1, 0), "unavailable"),  # a model or check unavailable for a concept
    ],
)
def test_a_drafting_run_records_how_it_ended(documents, monkeypatch, outcome, want):
    from services.check_item_service import GenerationOutcome

    monkeypatch.setattr(
        documents.svc, "_generate_for_document", lambda *a, **k: GenerationOutcome(*outcome)
    )
    documents.svc.generate_for_document(
        "doc-1", user_id="u1", course_id="c1", concept_names=["A"], flex=True
    )
    assert _statuses(documents) == [want]
    data, filters = documents.writes[0]
    assert filters == {"id": "eq.doc-1"} and data["check_items_at"].endswith("Z")


def test_a_drafting_run_that_raises_records_failed_and_re_raises(documents, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("storage down")

    monkeypatch.setattr(documents.svc, "_generate_for_document", boom)
    with pytest.raises(RuntimeError):
        documents.svc.generate_for_document(
            "doc-1", user_id="u1", course_id="c1", concept_names=["A"], flex=True
        )
    assert _statuses(documents) == ["failed"]


def test_the_loop_off_records_nothing(documents, monkeypatch):
    import config

    monkeypatch.setattr(config, "LEARNING_LOOP_ENABLED", False)
    documents.svc.generate_for_document(
        "doc-1", user_id="u1", course_id="c1", concept_names=["A"], flex=True
    )
    assert documents.writes == []


def test_a_status_write_that_fails_never_fails_drafting(monkeypatch, caplog):
    from services import check_item_service as svc

    def broken(name):
        raise RuntimeError("PGRST204: column check_items_status does not exist")

    monkeypatch.setattr(svc, "table", broken)
    with caplog.at_level(logging.WARNING, logger="sapling.services.check_items"):
        svc.mark_drafting("doc-1", svc.DRAFTING_PENDING)  # no raise: code ahead of migration
    assert any("not recorded" in r.getMessage() for r in caplog.records)
    with pytest.raises(ValueError):
        svc.mark_drafting("doc-1", "drafting")  # never an unknown status


def test_the_upload_hook_marks_pending_before_indexing(monkeypatch):
    """pending → (index) → the run's own end; a queue that refuses the run is
    recorded failed."""
    import routes.documents as docs

    order: list[str] = []
    monkeypatch.setattr(docs, "model_mode", lambda: "real")
    monkeypatch.setattr(docs, "mark_drafting", lambda d, s: order.append(f"mark:{s}"))
    monkeypatch.setattr(docs, "index_document", lambda d: order.append("index"))
    monkeypatch.setattr(
        docs, "queue_generation_for_document", lambda *a, **k: order.append("queue")
    )
    docs._index_then_check_items("doc-1", "u1", "c1", ["A"])
    assert order == ["mark:pending", "index", "queue"]

    order.clear()

    def refused(*a, **k):
        raise RuntimeError("cannot schedule new futures after shutdown")

    monkeypatch.setattr(docs, "queue_generation_for_document", refused)
    docs._index_then_check_items("doc-1", "u1", "c1", ["A"])
    assert order == ["mark:pending", "index", "mark:failed"]


def test_drafting_pending_reads_the_students_own_fresh_pending_uploads(documents, monkeypatch):
    now = datetime(2026, 11, 8, 12, 0, tzinfo=UTC)
    monkeypatch.setattr(documents.svc, "_utcnow", lambda: now)
    monkeypatch.setattr(documents.svc, "course_offering_ids", lambda c: ["off-1", "off-2"])
    documents.state["rows"] = [{"id": "doc-1"}]
    assert documents.svc.drafting_pending("u1", "c1") is True
    (filters,) = documents.reads
    ttl = timedelta(seconds=documents.svc.CHECK_ITEM_DRAFT_PENDING_TTL_S)
    assert filters == {
        "user_id": "eq.u1",
        "offering_id": 'in.("off-1","off-2")',
        "check_items_status": "eq.pending",
        "check_items_at": f"gt.{(now - ttl).strftime('%Y-%m-%dT%H:%M:%SZ')}",
        "deleted_at": "is.null",
    }
    documents.state["rows"] = []
    assert documents.svc.drafting_pending("u1", "c1") is False


def test_drafting_pending_fails_to_not_preparing(monkeypatch):
    from services import check_item_service as svc

    monkeypatch.setattr(svc, "course_offering_ids", lambda c: None)
    assert svc.drafting_pending("u1", "c1") is False  # offerings unknown
    monkeypatch.setattr(svc, "course_offering_ids", lambda c: ["off-1"])

    def broken(name):
        raise RuntimeError("down")

    monkeypatch.setattr(svc, "table", broken)
    assert svc.drafting_pending("u1", "c1") is False
    assert svc.drafting_pending("u1", None) is False


@pytest.mark.parametrize("pending,want", [(True, True), (False, None)])
def test_probe_next_says_preparing_while_the_upload_is_drafted(gate_on, seams, pending, want):
    seams.store["doc"] = {}
    with (
        patch("routes.learn_loop.course_has_items", return_value=False),
        patch("routes.learn_loop.drafting_pending", return_value=pending) as read,
    ):
        r = client.post("/api/learn/loop/probe/next", json={"session_id": "s1", "user_id": "u1"})
    body = r.json()
    assert body["done"] is True and body["no_check_items"] is True
    assert body.get("preparing") is want
    read.assert_called_once_with("u1", "c1")


def test_check_next_says_preparing_only_when_the_course_has_no_item(gate_on, seams):
    seams.store["doc"] = {**PLAN_STATE, "plan": dict(PLAN_STATE["plan"]), "phase": "teach",
                          "current": None, "steps": {}}
    for has_items, want in ((False, True), (True, None)):
        with (
            patch("routes.learn_loop.course_has_items", return_value=has_items),
            patch("routes.learn_loop.drafting_pending", return_value=True),
        ):
            r = client.post(
                "/api/learn/loop/check/next", json={"session_id": "s1", "user_id": "u1"}
            )
        assert r.status_code == 200 and r.json()["check"] is None
        assert r.json().get("preparing") is want


def test_an_unreadable_preparing_state_is_the_pre_a128_answer(gate_on, seams):
    seams.store["doc"] = {**PLAN_STATE, "plan": dict(PLAN_STATE["plan"]), "phase": "teach",
                          "current": None, "steps": {}}
    with patch("routes.learn_loop.course_has_items", side_effect=RuntimeError("down")):
        r = client.post("/api/learn/loop/check/next", json={"session_id": "s1", "user_id": "u1"})
    assert r.status_code == 200 and "preparing" not in r.json()


# ── the evidence-slot guard (unevaluated models, A22 independence) ──────────


@pytest.fixture
def slot_events(monkeypatch):
    seen: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        "services.events_service.log_event",
        lambda event_type, **kw: seen.append((event_type, kw)),
    )
    monkeypatch.setenv("SAPLING_MODEL_MODE", "real")
    return seen


def test_the_defaults_are_evaluated_and_independent(slot_events):
    from agents import _providers as p

    for task in p.EVIDENCE_SLOTS:
        assert p._DEFAULTS[task] in p.EVALUATED_MODELS[task], task
        if task in p.LOOP_SLOTS_PENDING_CLAUDE_EVAL:
            assert not any(m.startswith("claude-") for m in p.EVALUATED_MODELS[task]), task
    assert set(p.EVALUATED_MODELS) == set(p.EVIDENCE_SLOTS)
    assert p.check_slot_guards() == [] and slot_events == []


@pytest.mark.parametrize(
    "slot,model,reason",
    [
        ("grader", "claude-haiku-5-5", "pending_claude_eval"),  # A111: pending on claude-*
        ("loop_tutor_deep", "claude-opus-5-5", "pending_claude_eval"),
        ("grader", "gemini-2.5-pro", "not_evaluated"),  # a Gemini model it was not recorded on
        ("check_items_solve", "claude-sonnet-5-5", "not_evaluated"),
    ],
)
def test_an_env_flip_warns_once_and_emits_one_event(
    slot_events, monkeypatch, caplog, slot, model, reason
):
    from agents import _providers as p

    monkeypatch.setenv(f"SAPLING_MODEL_{slot.upper()}", model)
    with caplog.at_level(logging.WARNING, logger="agents._providers"):
        p.check_slot_guards()  # boot
        p.model_for(slot)  # where the slot's model is resolved (per run)
        p.model_for(slot)
    warned = [r for r in caplog.records if "outside its evaluated models" in r.getMessage()]
    assert len(warned) == 1 and model in warned[0].getMessage()
    unevaluated = [(et, kw) for et, kw in slot_events if et == "system.unevaluated_slot"]
    assert unevaluated == [
        (
            "system.unevaluated_slot",
            {"category": "system", "payload": {"slot": slot, "model": model, "reason": reason}},
        )
    ]
    assert {"kind": "unevaluated", "slot": slot, "model": model, "reason": reason} in (
        p.slot_warnings()
    )


def test_resolving_a_flipped_slot_warns_with_no_boot_check(slot_events, monkeypatch, caplog):
    """The env can be read after boot (a per-run slot like the deep tier or
    the second opinion resolves its model on every run): the resolution site
    warns on its own."""
    from agents import _providers as p

    monkeypatch.setenv("SAPLING_MODEL_LOOP_TUTOR_DEEP", "claude-opus-5-5")
    with caplog.at_level(logging.WARNING, logger="agents._providers"):
        p.model_for("loop_tutor_deep")
    assert [kw["payload"] for et, kw in slot_events if et == "system.unevaluated_slot"] == [
        {"slot": "loop_tutor_deep", "model": "claude-opus-5-5", "reason": "pending_claude_eval"}
    ]
    assert any("outside its evaluated models" in r.getMessage() for r in caplog.records)


def test_the_guard_never_blocks_and_ignores_non_evidence_slots(slot_events, monkeypatch):
    from agents import _providers as p

    monkeypatch.setenv("SAPLING_MODEL_GRADER", "claude-haiku-5-5")
    monkeypatch.setenv("SAPLING_MODEL_QUIZ", "gemini-2.5-flash")  # not an evidence slot
    assert p.model_for("grader") is not None  # the model is still built and served
    assert p.unevaluated_reason("quiz", "gemini-2.5-flash") is None
    assert [w["slot"] for w in p.unevaluated_slots()] == ["grader"]


def test_a_qualified_model_name_is_judged_by_its_bare_name(slot_events, monkeypatch):
    from agents import _providers as p

    assert p.unevaluated_reason("grader", "google-gla:gemini-2.5-flash-lite") is None
    assert p.unevaluated_reason("grader", "anthropic:claude-haiku-5-5") == "pending_claude_eval"


def test_function_mode_has_no_slot_warnings(monkeypatch):
    from agents import _providers as p

    monkeypatch.setenv("SAPLING_MODEL_MODE", "function")
    monkeypatch.setenv("SAPLING_MODEL_GRADER", "claude-haiku-5-5")
    assert p.slot_warnings() == [] and p.check_slot_guards() == []


@pytest.mark.parametrize(
    "env,slot,partner",
    [
        ({"SAPLING_MODEL_GRADER_SECOND": "gemini-2.5-flash-lite"}, "grader_second", "grader"),
        ({"SAPLING_MODEL_GRADER": "gemini-2.5-flash"}, "grader_second", "grader"),
        ({"SAPLING_MODEL_CHECK_ITEMS": "claude-haiku-5-5"}, "check_items_solve", "check_items"),
    ],
)
def test_a_second_opinion_on_its_partners_model_is_an_error_at_boot(
    slot_events, monkeypatch, caplog, env, slot, partner
):
    """A22: the second opinion runs on a DIFFERENT model; A124 (f): the key
    solve must not run on the drafter's model. Warn (ERROR) — never block."""
    from agents import _providers as p

    for k, v in env.items():
        monkeypatch.setenv(k, v)
    with caplog.at_level(logging.ERROR, logger="agents._providers"):
        p.check_slot_guards()
        p.check_slot_guards()  # once per process
    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert len(errors) == 1 and "not independent" in errors[0].getMessage()
    model = p._bare_model_name(p.model_name_for(slot))
    independence = [kw["payload"] for et, kw in slot_events if et == "system.slot_not_independent"]
    assert independence == [{"slot": slot, "model": model, "independent_of": partner}]
    kinds = {(w["kind"], w["slot"]) for w in p.slot_warnings()}
    assert ("not_independent", slot) in kinds


def test_the_lifespan_runs_the_boot_check():
    import inspect

    import main

    source = inspect.getsource(main._lifespan)
    assert "check_slot_guards()" in source
    assert source.index("freeze_model_mode()") < source.index("check_slot_guards()")


def test_the_admin_learning_loop_panel_lists_the_active_warnings(monkeypatch):
    from routes import admin_analytics

    warnings = [
        {"kind": "unevaluated", "slot": "grader", "model": "claude-haiku-5-5",
         "reason": "pending_claude_eval"},
        {"kind": "not_independent", "slot": "grader_second", "model": "gemini-2.5-flash",
         "independent_of": "grader", "rule": "A22"},
    ]
    monkeypatch.setattr(admin_analytics, "slot_warnings", lambda: warnings)
    monkeypatch.setattr(admin_analytics, "require_admin", lambda request: None)
    monkeypatch.setattr(admin_analytics, "_scan_range", lambda *a, **k: ([], False))
    monkeypatch.setattr(admin_analytics, "quiz_ask_session_ids", lambda *a, **k: set())
    monkeypatch.setattr(admin_analytics, "table", MagicMock())
    from fastapi.testclient import TestClient

    from main import app

    r = TestClient(app).get("/api/admin/analytics/learning-loop")
    assert r.status_code == 200
    got = r.json()["slot_warnings"]
    assert [(w["kind"], w["slot"]) for w in got] == [
        ("unevaluated", "grader"),
        ("not_independent", "grader_second"),
    ]
    assert got[0]["reason"] == "pending_claude_eval" and got[1]["independent_of"] == "grader"
