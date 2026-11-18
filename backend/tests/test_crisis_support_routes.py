"""The crisis-support path on every student-facing AI surface
(services/crisis_support.py; docs/safety/crisis-support.md).

For each surface, with the `crisis_support` flag ON a crisis message gets the
fixed card and the route does nothing else: zero model calls, zero database
writes, no session stashed, one content-free `safety.crisis_support_shown`
event. With the flag OFF (or on an ordinary message) the route carries on to
its own next step exactly as before — each case names that step and the test
replaces it with a sentinel 418, so "behaves as before" is observed, not
assumed.

The one exception is a note's stored CONTENT (its title and body, read by
the notes agent actions): a match there never blocks. The action runs as
usual and the card rides ALONGSIDE whatever answer goes back: the result, a
429 or an error.

The learning loop's routes (/api/learn/loop/*) are covered too. Most of
them carry their rate limit as a route dependency, so their screen is a
dependency listed before it (`crisis_support.screened`); the rest screen
inline, first thing after the loop's gate.
"""

from __future__ import annotations

import inspect
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Callable
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic_ai import Agent

import db.connection as dbconn
from main import app
from services import ai_budget, crisis_support, events_service, llm_budget, posthog_client
from services import crisis_support_copy as crisis_copy
from services.feature_flags import REGISTRY
from services.tutor_sessions import PENDING_SESSIONS
from tests.split_patches import setattr_loop

client = TestClient(app)

CRISIS = "honestly I want to kill myself tonight"
CALM = "What does a hash table do on a collision?"
#: Words of CRISIS that must never be stored, logged or sent anywhere.
CRISIS_WORDS = ("kill", "myself", "tonight")
SENTINEL = 418  # the route reached its own next step (the pre-crisis-support behaviour)


@dataclass(frozen=True)
class Case:
    surface: str
    path: str
    body: Callable[[str], dict]
    next_step: str  # what the route does right after its screen
    stream: bool = False
    async_next: bool = False
    neutral: dict[str, Any] = field(default_factory=dict)
    note_field: str | None = None  # notes routes: the note field the text goes in
    #: flashcard generate: the topic is one of the student's own graph concepts
    graph_concept: bool = False

    @property
    def blocks(self) -> bool:
        """A typed message blocks; stored material (a note's content, a graph
        concept's name) shows the card alongside."""
        return self.note_field is None and not self.graph_concept

    @property
    def loop(self) -> bool:
        """A learning-loop route (/api/learn/loop/*)."""
        return self.path.startswith("/api/learn/loop/")

    @property
    def id(self) -> str:
        return f"{self.path}:{self.note_field or ('graph_concept' if self.graph_concept else self.body.__name__)}"


def _chat(text):
    return {"session_id": "s1", "user_id": "u1", "message": text}


def _start(text):
    return {"user_id": "u1", "topic": text, "course_id": "c1"}


def _start_goal(text):
    """A start whose typed text is the learning loop's goal (the topic is calm)."""
    return {"user_id": "u1", "topic": "Recursion", "course_id": "c1",
            "goal": {"text": text, "target_node_ids": ["n1"]}}


def _answer(text):
    return {"session_id": "s1", "user_id": "u1", "question_hash": "qh", "answer": text}


def _reason(text):
    return {"session_id": "s1", "user_id": "u1", "question_hash": "qh", "option": "B", "reason": text}


def _note_message(text):
    return {"user_id": "u1", "message": text}


def _note_action(_text):
    return {"user_id": "u1"}


def _suggest(text):
    return {"user_id": "u1", "description": text, "course_id": "c1"}


def _paste(text):
    return {"user_id": "u1", "source": "paste", "text": text, "count": 5}


def _cloze(text):
    return {"user_id": "u1", "paragraph": text}


def _topic(text):
    return {"user_id": "u1", "topic": text, "count": 5}


TURN = {"graph_update": {}, "mastery_changes": []}
START = {"session_id": None, "graph_state": None}

CASES: list[Case] = [
    # /api/learn/* — the tutor (and the quiz's "Ask about this" panel, which rides it)
    Case("tutor_chat", "/api/learn/chat", _chat, "services.tutor.chat", async_next=True, neutral=TURN),
    Case("tutor_chat", "/api/learn/chat/stream", _chat, "services.tutor.chat_stream",
         stream=True, async_next=True, neutral=TURN),
    Case("tutor_start", "/api/learn/start-session", _start, "services.tutor.start_session",
         async_next=True, neutral=START),
    Case("tutor_start", "/api/learn/start-session/stream", _start, "services.tutor.start_session_stream",
         stream=True, async_next=True, neutral={"session_id": None, **TURN}),
    # the learning loop's goal on a tutor start is typed text too
    Case("tutor_start", "/api/learn/start-session", _start_goal, "services.tutor.start_session",
         async_next=True, neutral=START),
    # /api/learn/loop/* — the learning loop
    Case("loop_chat", "/api/learn/loop/chat", _chat, "services.loop.teach._consume_pending_off_loop",
         async_next=True, neutral=TURN),
    Case("loop_chat", "/api/learn/loop/chat/stream", _chat, "services.loop.teach._consume_pending_off_loop",
         stream=True, async_next=True, neutral=TURN),
    Case("loop_start", "/api/learn/loop/start-session", _start, "services.loop.teach._LoopOpener",
         neutral=START),
    Case("loop_start", "/api/learn/loop/start-session/stream", _start, "services.loop.teach._LoopOpener",
         stream=True, neutral={"session_id": None, **TURN}),
    Case("loop_start", "/api/learn/loop/start-session", _start_goal, "services.loop.teach._LoopOpener",
         neutral=START),
    Case("loop_goal", "/api/learn/loop/goal",
         lambda t: {"session_id": "s1", "user_id": "u1", "goal": {"text": t, "target_node_ids": ["n1"]}},
         "services.loop.goal._probe_plan_read_limit"),
    Case("loop_check_answer", "/api/learn/loop/check/answer", _answer,
         "services.loop.grading._consume_pending_off_loop", async_next=True, neutral=TURN),
    Case("loop_check_answer", "/api/learn/loop/check/answer/stream", _answer,
         "services.loop.grading._consume_pending_off_loop", stream=True, async_next=True, neutral=TURN),
    Case("loop_check_answer", "/api/learn/loop/check/answer", _reason,
         "services.loop.grading._consume_pending_off_loop", async_next=True, neutral=TURN),
    Case("loop_step_attempt", "/api/learn/loop/step/attempt",
         lambda t: {"session_id": "s1", "user_id": "u1", "question_hash": "qh", "attempt_text": t},
         "services.loop.attempts._session_scope", neutral={"genuine": False, "counted": False}),
    Case("loop_probe_answer", "/api/learn/loop/probe/answer", _answer,
         "services.ai_budget.enforce_rate_limit_for", neutral={"graded": False}),
    Case("loop_review_answer", "/api/learn/loop/review/answer",
         lambda t: {"user_id": "u1", "session_id": "r1", "kind": "check", "item_id": "i1", "answer": t},
         "services.loop.reviews._review_course",
         neutral={"correct": None, "unavailable": True, "refused": False}),
    Case("loop_posttest_answer", "/api/learn/loop/posttest/answer",
         lambda t: {"user_id": "u1", "node_id": "n1", "question_hash": "qh", "answer": t},
         "services.loop.posttest._posttest_node", neutral={"graded": False}),
    # learning-loop spec §13 A138: a guess at the segment prequestion (free and
    # multiple choice), JSON and stream; A139: a self-explanation reply
    Case("loop_prequestion_answer", "/api/learn/loop/prequestion/answer", _answer,
         "services.loop.prequestion._consume_pending_off_loop", async_next=True, neutral=TURN),
    Case("loop_prequestion_answer", "/api/learn/loop/prequestion/answer/stream", _answer,
         "services.loop.prequestion._consume_pending_off_loop", stream=True, async_next=True, neutral=TURN),
    Case("loop_prequestion_answer", "/api/learn/loop/prequestion/answer", _reason,
         "services.loop.prequestion._consume_pending_off_loop", async_next=True, neutral=TURN),
    Case("loop_self_explain", "/api/learn/loop/self-explain",
         lambda t: {"session_id": "s1", "user_id": "u1", "prompt_id": "p1", "reply": t},
         "services.loop.self_explain._session_scope", neutral={"recorded": False}),
    # /api/notes/* — the message, or the note an agent action hands a model
    Case("note_chat", "/api/notes/n1/chat", _note_message, "routes.notes.offering_course_id",
         neutral={"degraded": False}),
    Case("note_chat", "/api/notes/n1/chat", lambda t: _note_message(CALM), "routes.notes.offering_course_id",
         neutral={"degraded": False}, note_field="body"),
    Case("note_send_to_tutor", "/api/notes/n1/send-to-tutor", _note_action,
         "routes.notes.offering_course_id", note_field="title"),
    Case("note_summarize", "/api/notes/n1/summarize", _note_action, "routes.notes._note_user_prompt",
         note_field="body"),
    Case("note_extract_concepts", "/api/notes/n1/extract-concepts", _note_action,
         "routes.notes._note_user_prompt", neutral={"concepts": [], "linked": 0}, note_field="body"),
    # /api/flashcards/* — text the student writes for a generator
    Case("flashcard_set_suggest", "/api/flashcards/sets/suggest", _suggest,
         "routes.flashcards.suggest_flashcard_set", async_next=True,
         neutral={"name": "", "concepts": [], "considered": 0, "backend": "none"}),
    Case("flashcard_import_paste", "/api/flashcards/import/generate", _paste,
         "services.flashcards.import_flow.import_generate", neutral={"cards": []}),
    Case("flashcard_import_cloze", "/api/flashcards/import/cloze", _cloze,
         "services.flashcards.import_flow.import_cloze", neutral={"cards": []}),
    # a topic that is not one of the student's graph concepts is typed: it blocks
    Case("flashcard_generate", "/api/flashcards/generate", _topic,
         "services.flashcards.generation.generate", neutral={"flashcards": []}),
    # ...one that is (the page's one-concept-per-call Start) is course material
    Case("flashcard_generate", "/api/flashcards/generate", _topic,
         "services.flashcards.generation.generate", graph_concept=True),
]
IDS = [c.id for c in CASES]
BLOCKING = [c for c in CASES if c.blocks]
BLOCKING_IDS = [c.id for c in BLOCKING]
CONTENT = [c for c in CASES if not c.blocks]
CONTENT_IDS = [c.id for c in CONTENT]
LOOP = [c for c in CASES if c.loop]
LOOP_IDS = [c.id for c in LOOP]


# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def no_rate_limit(request):
    """The learning loop's A20 rate-limit dependency reads llm_usage (route
    tests override it, as tests/test_learn_loop_routes.py does); a case that
    names the inline check as its next step patches over this. A test that
    asks for `real_limiters` gets the real dependency and inline check
    instead: this fixture steps aside rather than being patched over
    (re-patching an attribute this `patch` holds would leak the stub past
    the test)."""
    if "real_limiters" in request.fixturenames:
        yield
        return
    app.dependency_overrides[ai_budget.enforce_rate_limit] = lambda: None
    with patch("services.ai_budget.enforce_rate_limit_for", return_value=None):
        yield
    app.dependency_overrides.pop(ai_budget.enforce_rate_limit, None)


@pytest.fixture
def flag(monkeypatch):
    def _set(variant: str) -> None:
        monkeypatch.setenv("SAPLING_FLAG_CRISIS_SUPPORT", variant)

    return _set


@pytest.fixture
def model_calls(monkeypatch):
    """Every way an agent runs, recorded and refused: a crisis turn must
    make none."""
    calls: list[str] = []

    def _refuse(name):
        def _call(self, *args, **kwargs):
            calls.append(name)
            raise AssertionError(f"Agent.{name} ran on a crisis turn")

        return _call

    for name in ("run", "run_sync", "run_stream", "run_stream_events", "iter"):
        monkeypatch.setattr(Agent, name, _refuse(name))
    return calls


def _db_writes() -> int:
    fake = dbconn._client
    return fake.post.call_count + fake.patch.call_count + fake.delete.call_count


def _note(case: Case | None, text: str) -> dict:
    note = {"id": "n1", "user_id": "u1", "offering_id": "o1", "title": "Week 3", "body": "Hash tables."}
    if case is not None and case.note_field:
        note[case.note_field] = text
    return note


def _post(case: Case, text: str):
    """POST the case with `text` in its student field, its next step replaced
    by a sentinel 418. Returns (response, the sentinel mock)."""
    sentinel = HTTPException(status_code=SENTINEL, detail="reached the route's own next step")
    mock = (AsyncMock if case.async_next else MagicMock)(side_effect=sentinel)
    concepts = ["Hash tables", text] if case.graph_concept else ["Hash tables"]
    with (
        patch(case.next_step, mock),
        patch("routes.notes.get_note", AsyncMock(return_value=_note(case, text))),
        patch("services.flashcards.concept_topic._graph_concept_names", return_value=concepts),
    ):
        return client.post(case.path, json=case.body(text)), mock


def _sse_events(text: str) -> list[tuple[str, dict]]:
    events, name = [], None
    for line in text.splitlines():
        if line.startswith("event:"):
            name = line.split(":", 1)[1].strip()
        elif line.startswith("data:"):
            events.append((name, json.loads(line.split(":", 1)[1])))
    return events


def _crisis_rows(sink: list[dict]) -> list[dict]:
    events_service.flush_now()
    return [r for r in sink if r["event_type"] == crisis_support.EVENT]


def _card_of(case: Case, r) -> dict:
    assert r.status_code == 200, r.text
    if case.stream:
        (name, event), = _sse_events(r.text)
        assert name == "done"
        return event["data"]
    return r.json()


# ── Every surface ───────────────────────────────────────────────────────────


@pytest.mark.parametrize("case", BLOCKING, ids=BLOCKING_IDS)
def test_flag_on_a_crisis_message_gets_the_card_and_nothing_else(
    case, flag, model_calls, sink, caplog
):
    flag("on")
    writes, pending = _db_writes(), dict(PENDING_SESSIONS)
    caplog.set_level(logging.DEBUG)

    r, next_step = _post(case, CRISIS)

    assert r.status_code == 200, r.text
    if case.stream:
        assert r.headers["content-type"].startswith("text/event-stream")
        events = _sse_events(r.text)
        assert [name for name, _ in events] == ["done"], "one terminal done event, nothing else"
        assert events[0][1]["type"] == "done"
        body = events[0][1]["data"]
    else:
        body = r.json()
    payload = crisis_support.client_payload(crisis_copy.DEFAULT_CAMPUS_COUNSELING)
    assert body["crisis_support"] == payload
    assert body["reply"] == crisis_support.render_reply(payload)
    for key, value in case.neutral.items():
        assert body[key] == value, key
    if case.surface in ("tutor_start", "loop_start") and not case.stream:
        assert body["initial_message"] == body["reply"]

    next_step.assert_not_called()  # the turn never started
    assert model_calls == []  # no model, no grader, no tutor
    # no message, session, summary, concept or card row; on the loop no
    # evidence, help-ledger or session row either
    assert _db_writes() == writes
    assert dict(PENDING_SESSIONS) == pending  # no lazy session stashed

    rows = _crisis_rows(sink)
    assert len(rows) == 1
    row = rows[0]
    assert row["category"] == "system"
    assert row["user_id"] == "u1"
    assert row["payload"] == {"surface": case.surface, "category": "suicidal_ideation", "tier": "explicit"}
    assert row["content_fp"] is None
    dumped = json.dumps(row).lower()
    assert not any(word in dumped for word in CRISIS_WORDS)
    assert [r for r in sink if r["event_type"] == "chat.message_sent"] == []

    logged = " ".join(rec.getMessage().lower() for rec in caplog.records)
    assert not any(word in logged for word in CRISIS_WORDS), "the text must never be logged"


@pytest.mark.parametrize("case", CONTENT, ids=CONTENT_IDS)
def test_flag_on_crisis_note_content_runs_the_action_with_the_card_alongside(
    case, flag, model_calls, sink, caplog
):
    """The note's content never blocks: the action goes on to its own next
    step (here the sentinel, an error) and the answer that goes back, error
    or not, carries the card. One content-free event, as for any match."""
    flag("on")
    caplog.set_level(logging.DEBUG)

    r, next_step = _post(case, CRISIS)

    next_step.assert_called_once()  # the action ran
    assert r.status_code == SENTINEL, r.text  # ...and its own answer went back
    body = r.json()
    assert body["detail"].startswith("reached the route's own next step")
    assert body["crisis_support"] == crisis_support.client_payload(crisis_copy.DEFAULT_CAMPUS_COUNSELING)
    rows = _crisis_rows(sink)
    assert [row["payload"] for row in rows] == [
        {"surface": case.surface, "category": "suicidal_ideation", "tier": "explicit"}
    ]
    assert rows[0]["content_fp"] is None
    assert not any(word in json.dumps(rows).lower() for word in CRISIS_WORDS)
    logged = " ".join(rec.getMessage().lower() for rec in caplog.records)
    assert not any(word in logged for word in CRISIS_WORDS), "the text must never be logged"


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_flag_off_the_route_behaves_as_before(case, flag, model_calls, sink):
    flag("off")
    r, next_step = _post(case, CRISIS)
    assert r.status_code == SENTINEL, r.text
    next_step.assert_called_once()
    assert "crisis_support" not in r.json()
    assert _crisis_rows(sink) == []


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_flag_on_an_ordinary_message_is_untouched(case, flag, model_calls, sink):
    flag("on")
    r, next_step = _post(case, CALM)
    assert r.status_code == SENTINEL, r.text
    next_step.assert_called_once()
    assert "crisis_support" not in r.json()
    assert _crisis_rows(sink) == []


def test_every_surface_is_covered():
    assert {c.surface for c in CASES} == set(crisis_support.SURFACES)


def test_a_library_document_import_is_not_screened(flag, model_calls, sink):
    """Only PASTED text is the student's: a library document is uploaded course
    material, and screening readings would mostly flag the readings."""
    flag("on")
    sentinel = HTTPException(status_code=SENTINEL, detail="next step")
    with patch("services.flashcards.import_flow.import_generate", MagicMock(side_effect=sentinel)):
        r = client.post("/api/flashcards/import/generate",
                        json={"user_id": "u1", "source": "library_doc", "text": CRISIS, "document_id": "d1"})
    assert r.status_code == SENTINEL
    assert _crisis_rows(sink) == []


def test_an_imported_deck_is_cleaned_up_whatever_it_says(flag, model_calls, sink):
    """`/import/cleanup` rewrites an IMPORTED deck (Anki, xlsx, a URL, OCR):
    someone else's study material, not the student's writing. A nursing card
    quoting a patient is cleaned up like any other, never answered with the
    card (which would leave the deck impossible to clean up)."""
    flag("on")
    sentinel = HTTPException(status_code=SENTINEL, detail="next step")
    cards = [{"front": "Patient states I want to die. First nursing action?",
              "back": "Assess for a plan and ensure safety."},
             {"front": CRISIS, "back": "An answer."}]
    with patch("services.flashcards.import_flow.import_cleanup", MagicMock(side_effect=sentinel)):
        r = client.post("/api/flashcards/import/cleanup", json={"user_id": "u1", "cards": cards})
    assert r.status_code == SENTINEL, r.text
    assert _crisis_rows(sink) == []


def test_an_unauthenticated_cleanup_is_refused_before_any_card_is_read(flag, monkeypatch):
    """Auth comes first: a stranger's 10,000-card deck costs no screening."""
    from routes import flashcards as flashcard_routes
    from services import crisis_detection

    flag("on")
    detect = MagicMock(side_effect=AssertionError("screened before auth"))
    monkeypatch.setattr(crisis_detection, "detect", detect)
    refuse = MagicMock(side_effect=HTTPException(status_code=401, detail="no session"))
    monkeypatch.setattr(flashcard_routes, "require_self", refuse)
    cards = [{"front": CRISIS, "back": "An answer."}] * 50
    r = client.post("/api/flashcards/import/cleanup", json={"user_id": "u1", "cards": cards})
    assert r.status_code == 401
    refuse.assert_called_once()
    detect.assert_not_called()


def test_a_typed_note_chat_message_is_screened_whole_quotes_and_all(flag, model_calls, sink):
    """A quotation is just text: what the student types into the note chat
    is screened in full."""
    flag("on")
    case = next(c for c in CASES if c.surface == "note_chat" and not c.note_field)
    r, next_step = _post(case, 'PSYCH 101: a patient says "I want to kill myself"; assess for a plan.')
    assert "crisis_support" in _card_of(case, r)
    next_step.assert_not_called()


def _note_chat_with_tags(tags: list):
    """POST a calm note-chat message over a note whose only crisis text (if
    any) is in its tags; the route's next step is a sentinel 418."""
    note = {"id": "n1", "user_id": "u1", "offering_id": "o1", "title": "Week 3",
            "body": "Hash tables.", "tags": tags}
    sentinel = HTTPException(status_code=SENTINEL, detail="reached the route's own next step")
    nxt = MagicMock(side_effect=sentinel)
    with (
        patch("routes.notes.offering_course_id", nxt),
        patch("routes.notes.get_note", AsyncMock(return_value=note)),
    ):
        return client.post("/api/notes/n1/chat", json={"user_id": "u1", "message": CALM}), nxt


def test_a_crisis_phrase_only_in_the_notes_tags_rides_beside_the_note_chat(flag, model_calls, sink):
    """The note-chat agent reads the note's tags (its read_active_note tool
    serves them, and A125's integrity guard checks them:
    services/note_guard.py), so the note's content screen reads them too. A
    tag is stored material like the body: the chat runs, and the card rides
    beside its answer."""
    flag("on")
    r, nxt = _note_chat_with_tags(["midterm", CRISIS])
    nxt.assert_called_once()  # stored material never blocks
    assert r.status_code == SENTINEL, r.text
    assert r.json()["crisis_support"] == crisis_support.client_payload(crisis_copy.DEFAULT_CAMPUS_COUNSELING)
    (row,) = _crisis_rows(sink)
    assert row["payload"]["surface"] == "note_chat"
    # control: the same note with calm tags carries on without the card
    r, nxt = _note_chat_with_tags(["midterm", "hashing"])
    assert r.status_code == SENTINEL, r.text
    assert "crisis_support" not in r.json()
    nxt.assert_called_once()


def test_the_screen_authenticates_before_the_flag_and_the_event(flag, model_calls, sink, monkeypatch):
    """The screen runs before the handler's own require_self, so on a match it
    checks the caller itself, before it reads the flag or records anything:
    another student's user_id is refused, and nothing is attributed to them."""
    from services import auth_guard

    flag("on")

    def require_self(user_id, request, **_kwargs):
        if user_id != "u1":  # the session is u1's
            raise HTTPException(status_code=403, detail="Forbidden")

    monkeypatch.setattr(auth_guard, "require_self", require_self)
    flag_reads = MagicMock(return_value=True)
    monkeypatch.setattr(crisis_support, "flag_on", flag_reads)

    for path, body in (("/api/learn/chat", {**_chat(CRISIS), "user_id": "u2"}),
                       ("/api/flashcards/import/cloze", {**_cloze(CRISIS), "user_id": "u2"})):
        r = client.post(path, json=body)
        assert r.status_code == 403, path
    flag_reads.assert_not_called()
    assert _crisis_rows(sink) == []

    r = client.post("/api/learn/chat", json=_chat(CRISIS))
    assert r.status_code == 200 and "crisis_support" in r.json()
    assert [row["user_id"] for row in _crisis_rows(sink)] == ["u1"]


@pytest.mark.parametrize("path", ["/api/learn/chat/stream", "/api/learn/loop/chat/stream"])
def test_the_streamed_card_is_the_tutor_streams_own_terminal_shape(path, flag, model_calls):
    """The frontend's consumeChatStream resolves a turn from `done.data` and
    needs nothing before it; the crisis stream is exactly that one event."""
    flag("on")
    r = client.post(path, json=_chat(CRISIS))
    assert r.headers["cache-control"] == "no-store, no-transform"
    assert r.headers["x-request-id"]
    (name, event), = _sse_events(r.text)
    assert (name, event["type"], event["step"]) == ("done", "done", "reply")
    assert set(event["data"]) == {"reply", "crisis_support", "graph_update", "mastery_changes"}


# ── A note's content: the card alongside the action's own answer ───────────
#
# The four notes agent actions down their real path (the model run and the
# writes stood in), with a crisis line in the note's body: each returns its
# normal result plus the card, logs the one event, and a refusal (a spent
# note budget, the daily LLM budget) or a failure still carries the card.


class _Ran:
    """A stand-in agent result (output only; usage is recorded best-effort)."""

    def __init__(self, output):
        self.output = output


#: (path, typed body, the result keys the action answers with)
NOTE_ACTIONS = [
    ("/api/notes/n1/summarize", _note_action, {"summary": "Short summary."}),
    ("/api/notes/n1/extract-concepts", _note_action, {"concepts": ["Hash tables"], "linked": 1}),
    ("/api/notes/n1/chat", lambda: _note_message(CALM), {"reply": "An answer.", "degraded": False}),
    ("/api/notes/n1/send-to-tutor", _note_action, {"topic": "Week 3", "course_id": "c1"}),
]
NOTE_ACTION_IDS = [p.rsplit("/", 1)[1] for p, _, _ in NOTE_ACTIONS]


@pytest.fixture
def note_actions():
    """Every note action's model run and writes stood in; the note's body is
    `CRISIS`. Yields the dict of mocks."""
    mocks = {
        "summary": AsyncMock(return_value=_Ran(type("S", (), {"summary": "Short summary."})())),
        "concepts": AsyncMock(return_value=_Ran(type("C", (), {"concepts": ["Hash tables"]})())),
        "chat": AsyncMock(return_value=_Ran("An answer.")),
        "save_summary": AsyncMock(return_value={}),
    }
    note = _note(None, "") | {"body": f"Hash tables. {CRISIS}."}
    with (
        patch("routes.notes.get_note", AsyncMock(return_value=note)),
        patch("routes.notes.offering_course_id", return_value="c1"),
        patch("routes.notes.note_summary_agent.run", mocks["summary"]),
        patch("routes.notes.note_concepts_agent.run", mocks["concepts"]),
        patch("routes.notes.note_chat_agent.run", mocks["chat"]),
        patch("routes.notes.save_summary", mocks["save_summary"]),
        patch("routes.notes.apply_concepts_to_graph", AsyncMock(return_value=None)),
        patch("routes.notes._lookup_concept_nodes_by_name",
              AsyncMock(return_value=[{"id": "g1", "concept_name": "Hash tables"}])),
        patch("routes.notes.link_prechecked_concepts", AsyncMock(return_value=1)),
    ):
        yield mocks


def _note_action_body(make) -> dict:
    return make() if make.__code__.co_argcount == 0 else make(None)


@pytest.mark.parametrize("path, make, result", NOTE_ACTIONS, ids=NOTE_ACTION_IDS)
def test_crisis_note_content_gets_the_normal_result_and_the_card(path, make, result, flag, sink, note_actions):
    flag("on")
    r = client.post(path, json=_note_action_body(make))
    assert r.status_code == 200, r.text
    body = r.json()
    for key, value in result.items():
        assert body[key] == value, key
    assert body["crisis_support"] == crisis_support.client_payload(crisis_copy.DEFAULT_CAMPUS_COUNSELING)
    assert body["crisis_support_alongside"] is True
    surface = next(c.surface for c in CONTENT if c.path == path)
    assert [row["payload"]["surface"] for row in _crisis_rows(sink)] == [surface]
    if path.endswith("/summarize"):
        note_actions["save_summary"].assert_awaited_once()  # the summary was saved as usual


@pytest.mark.parametrize("path, make, result", NOTE_ACTIONS, ids=NOTE_ACTION_IDS)
def test_ordinary_note_content_gets_the_result_alone(path, make, result, flag, sink, note_actions):
    flag("on")
    with patch("routes.notes.get_note", AsyncMock(return_value=_note(None, ""))):
        r = client.post(path, json=_note_action_body(make))
    assert r.status_code == 200, r.text
    assert "crisis_support" not in r.json() and "crisis_support_alongside" not in r.json()
    assert _crisis_rows(sink) == []


@pytest.mark.parametrize("path, make, result", NOTE_ACTIONS, ids=NOTE_ACTION_IDS)
def test_a_rate_limited_note_action_still_carries_the_card(path, make, result, flag, sink, note_actions):
    """The action's own limit applies (a 429 is its answer), and the 429
    carries the card, with its Retry-After and plain detail intact."""
    flag("on")
    with patch("services.request_limits.acheck_rate_limit", AsyncMock(return_value=30)):
        r = client.post(path, json=_note_action_body(make))
    assert r.status_code == 429, r.text
    assert r.headers["Retry-After"] == "30"
    body = r.json()
    assert "Try again in" in body["detail"]
    assert body["crisis_support"] == crisis_support.client_payload(crisis_copy.DEFAULT_CAMPUS_COUNSELING)
    assert len(_crisis_rows(sink)) == 1
    for mock in note_actions.values():
        mock.assert_not_called()  # refused before any model ran


def test_a_budget_capped_note_action_still_carries_the_card(flag, sink, note_actions):
    """The daily LLM budget (its own handler, with `error.reset_at`) too."""
    flag("on")
    from datetime import datetime, timedelta, timezone

    reset_at = datetime.now(timezone.utc) + timedelta(hours=3)
    note_actions["summary"].side_effect = llm_budget.LLMBudgetExceeded(limit=10, used=10, reset_at=reset_at)
    r = client.post("/api/notes/n1/summarize", json=_note_action({}))
    assert r.status_code == 429, r.text
    assert r.json()["detail"] == llm_budget.user_message(reset_at)
    assert "Retry-After" in r.headers
    assert "crisis_support" in r.json()


def test_a_failed_note_action_still_carries_the_card(flag, sink, note_actions):
    """An unexpected failure is the generic 500, card included."""
    flag("on")
    note_actions["save_summary"].side_effect = RuntimeError("PostgREST down")
    r = TestClient(app, raise_server_exceptions=False).post(
        "/api/notes/n1/summarize", json=_note_action({}))
    assert r.status_code == 500, r.text
    assert r.json()["detail"] == "Internal server error."
    assert "crisis_support" in r.json()


def test_the_error_with_the_card_is_the_error_without_it_plus_the_card(flag, sink, note_actions):
    """`alongside` renders the error through the app's own handler, so status,
    headers (Retry-After) and body are exactly what the same refusal gets
    without a match, plus `crisis_support`."""
    flag("on")
    with patch("services.request_limits.acheck_rate_limit", AsyncMock(return_value=30)):
        with_card = client.post("/api/notes/n1/summarize", json=_note_action({}))
        with patch("routes.notes.get_note", AsyncMock(return_value=_note(None, ""))):
            without = client.post("/api/notes/n1/summarize", json=_note_action({}))
    assert with_card.status_code == without.status_code == 429
    drop = {"x-request-id", "content-length"}
    assert ({k: v for k, v in with_card.headers.items() if k not in drop}
            == {k: v for k, v in without.headers.items() if k not in drop})
    body = with_card.json()
    assert body.pop("crisis_support") == crisis_support.client_payload(crisis_copy.DEFAULT_CAMPUS_COUNSELING)
    body.pop("request_id", None)
    plain = without.json()
    plain.pop("request_id", None)
    assert body == plain


def test_an_error_the_action_converts_itself_still_carries_the_card(flag, sink, note_actions):
    """The note chat turns a model misbehaving into its own 500 detail; that
    converted answer is what goes back, card included."""
    from pydantic_ai.exceptions import UnexpectedModelBehavior

    flag("on")
    note_actions["chat"].side_effect = UnexpectedModelBehavior("garbled")
    r = client.post("/api/notes/n1/chat", json=_note_message(CALM))
    assert r.status_code == 500, r.text
    assert r.json()["detail"] == "Something went wrong answering that."
    assert "crisis_support" in r.json()


def test_a_handler_that_answers_with_a_new_error_still_carries_the_card(flag, sink, note_actions):
    """main.py answers a user-scope refusal with a fresh 404: the card is
    added to that answer, not threaded through the new exception."""
    import httpx

    from db.scope import ScopedAccessDenied

    flag("on")
    refused = httpx.Request("POST", "http://postgrest/notes")
    note_actions["save_summary"].side_effect = ScopedAccessDenied(
        "refused", request=refused, response=httpx.Response(403, request=refused))
    r = client.post("/api/notes/n1/summarize", json=_note_action({}))
    assert r.status_code == 404, r.text
    assert r.json()["detail"] == "Not found"
    assert "crisis_support" in r.json()


class _AlreadyDone(Exception):
    """An exception type main.py has no handler of its own for (yet)."""


def test_a_handler_that_knows_nothing_of_the_card_still_answers_with_it(flag, sink, note_actions, monkeypatch):
    """A handler added later needs no crisis-support code: `alongside` runs
    the app's handler for the error and adds the card to its answer."""
    from fastapi.responses import JSONResponse

    async def already_done(request, exc):
        return JSONResponse(status_code=409, content={"detail": "Already summarized."},
                            headers={"Retry-After": "7"})

    monkeypatch.setitem(app.exception_handlers, _AlreadyDone, already_done)
    monkeypatch.setattr(app, "middleware_stack", None)  # rebuilt with the new handler
    flag("on")
    note_actions["save_summary"].side_effect = _AlreadyDone()
    r = TestClient(app, raise_server_exceptions=False).post("/api/notes/n1/summarize", json=_note_action({}))
    assert r.status_code == 409, r.text
    assert r.headers["Retry-After"] == "7"
    assert r.json() == {
        "detail": "Already summarized.",
        "crisis_support": crisis_support.client_payload(crisis_copy.DEFAULT_CAMPUS_COUNSELING),
    }


def _validation_error():
    from fastapi.exceptions import RequestValidationError

    return RequestValidationError([{"type": "value_error", "loc": ("body", "x"), "msg": "bad", "input": 1}])


def _scope_unavailable():
    from db.scope import ScopeUnavailable

    return ScopeUnavailable("no user-scoped credential")


@pytest.mark.parametrize("raised, status", [
    (lambda: HTTPException(status_code=413, detail="That note is too long."), 413),
    (lambda: HTTPException(status_code=422, detail="Nothing to summarize."), 422),
    (_validation_error, 422),
    (_scope_unavailable, 503),
    (lambda: RuntimeError("PostgREST down"), 500),
], ids=["413", "422", "validation-422", "domain-503", "generic-500"])
def test_every_error_answer_is_the_same_answer_plus_the_card(raised, status, flag, sink, note_actions):
    """Whichever layer answers the error (an ExceptionMiddleware handler, or
    ServerErrorMiddleware for the generic 500), the card is added on the way
    out and nothing else about the answer changes."""
    flag("on")
    loose = TestClient(app, raise_server_exceptions=False)
    note_actions["save_summary"].side_effect = lambda *a, **k: (_ for _ in ()).throw(raised())
    with_card = loose.post("/api/notes/n1/summarize", json=_note_action({}))
    with patch("routes.notes.get_note", AsyncMock(return_value=_note(None, ""))):
        note_actions["summary"].return_value = _Ran(type("S", (), {"summary": "Short summary."})())
        without = loose.post("/api/notes/n1/summarize", json=_note_action({}))
    assert with_card.status_code == without.status_code == status, with_card.text
    drop = {"x-request-id", "content-length"}
    assert ({k: v for k, v in with_card.headers.items() if k not in drop}
            == {k: v for k, v in without.headers.items() if k not in drop})
    assert int(with_card.headers["content-length"]) == len(with_card.content)
    body, plain = with_card.json(), without.json()
    assert body.pop("crisis_support") == crisis_support.client_payload(crisis_copy.DEFAULT_CAMPUS_COUNSELING)
    for answer in (body, plain):
        answer.pop("request_id", None)
        if isinstance(answer.get("error"), dict):
            answer["error"].pop("request_id", None)
    assert body == plain


def test_an_unexpected_exception_still_reaches_the_server_and_its_log(flag, sink, note_actions, caplog, monkeypatch):
    """`alongside` re-raises: the generic handler logs the traceback once,
    PostHog gets the one exception, and the exception propagates past the
    app to the server (its error log, the trace's exception record), exactly
    as without a match."""
    flag("on")
    captured = []
    monkeypatch.setattr(posthog_client, "capture_exception", lambda exc, **kw: captured.append(exc))
    caplog.set_level(logging.ERROR, logger="main")
    boom = RuntimeError("PostgREST down")
    note_actions["save_summary"].side_effect = boom
    with pytest.raises(RuntimeError) as raised:
        TestClient(app).post("/api/notes/n1/summarize", json=_note_action({}))
    assert raised.value is boom
    logged = [r for r in caplog.records if r.name == "main" and r.getMessage() == "Unhandled exception"]
    assert len(logged) == 1 and logged[0].exc_info[1] is boom
    assert captured == [boom]


def test_the_error_card_layer_wraps_the_whole_stack_and_keeps_the_trace():
    """Outside every ServerErrorMiddleware (so the generic 500 passes it), and
    installed after the OpenTelemetry instrumentation, which is still there."""
    from starlette.middleware.errors import ServerErrorMiddleware

    stack = app.build_middleware_stack()
    assert isinstance(stack, crisis_support.ErrorCardMiddleware)
    layers, node = [], stack.app
    while node is not None and len(layers) < 30:
        layers.append(type(node).__name__)
        node = getattr(node, "app", None)
    assert isinstance(stack.app, ServerErrorMiddleware)
    assert "OpenTelemetryMiddleware" in layers


# The error-card layer on its own, over a stand-in inner app: what it holds
# back (an error JSON answer's start, until its body is whole) is always
# forwarded, card or not.

_CARD = {"title": "card"}
_JSON_500 = {"type": "http.response.start", "status": 500,
             "headers": [(b"content-type", b"application/json"), (b"content-length", b"20")]}


def _run_layer(*messages: dict, raises: Exception | None = None, card: bool = True):
    """Run ErrorCardMiddleware over an inner app that sends `messages` (then
    raises `raises`); answers (what reached the server, what was raised)."""
    import asyncio

    async def inner(scope, receive, send):
        if card:
            scope["state"][crisis_support.ERROR_CARD_STATE] = _CARD
        for message in messages:
            await send(message)
        if raises is not None:
            raise raises

    sent: list[dict] = []

    async def send(message):
        sent.append(message)

    async def run():
        await crisis_support.ErrorCardMiddleware(inner)({"type": "http"}, None, send)

    try:
        asyncio.run(run())
    except Exception as exc:  # noqa: BLE001 — returned for the test to inspect
        return sent, exc
    return sent, None


def _body(more: bool, data: bytes) -> dict:
    return {"type": "http.response.body", "body": data, "more_body": more}


def test_the_error_card_layer_adds_the_card_once_the_body_is_whole():
    sent, raised = _run_layer(_JSON_500, _body(True, b'{"detail":'), _body(False, b'"boom"}'))
    assert raised is None
    start, body = sent
    assert start["status"] == 500
    assert json.loads(body["body"]) == {"detail": "boom", "crisis_support": _CARD}
    assert dict(start["headers"])[b"content-length"] == str(len(body["body"])).encode()


def test_an_exception_mid_body_forwards_what_was_held_unchanged_and_re_raises():
    """The inner app raises between the held start and the body's last chunk:
    the start and the chunks sent so far go to the server as they were (no
    card), then the exception propagates, exactly as without a card."""
    boom = RuntimeError("stream broke")
    sent, raised = _run_layer(_JSON_500, _body(True, b'{"detail":'), raises=boom)
    assert raised is boom
    assert sent == [_JSON_500, _body(True, b'{"detail":')]


def test_an_exception_before_any_body_still_forwards_the_held_start():
    boom = RuntimeError("no body")
    sent, raised = _run_layer(_JSON_500, raises=boom)
    assert raised is boom
    assert sent == [_JSON_500]


def test_an_app_that_returns_without_finishing_the_body_gets_what_it_sent():
    sent, raised = _run_layer(_JSON_500, _body(True, b'{"detail":'))
    assert raised is None
    assert sent == [_JSON_500, _body(True, b'{"detail":')]


def test_an_error_body_past_the_buffer_cap_passes_through_untouched():
    cap = crisis_support._ERROR_CARD_MAX_BODY
    first, second, last = _body(True, b"x" * cap), _body(True, b"y"), _body(False, b"z")
    sent, raised = _run_layer(_JSON_500, first, second, last)
    assert raised is None
    assert sent == [_JSON_500, first, second, last]  # no card, nothing rewritten


def test_an_error_body_at_the_cap_still_gets_the_card():
    cap = crisis_support._ERROR_CARD_MAX_BODY
    detail = "x" * (cap - len('{"detail":""}'))
    sent, _ = _run_layer(_JSON_500, _body(False, json.dumps({"detail": detail}, separators=(",", ":")).encode()))
    assert json.loads(sent[-1]["body"])["crisis_support"] == _CARD


def test_without_a_card_the_error_answer_streams_through():
    sent, _ = _run_layer(_JSON_500, _body(True, b"{}"), card=False)
    assert sent == [_JSON_500, _body(True, b"{}")]


def test_a_typed_crisis_message_still_blocks_on_a_crisis_note(flag, sink, note_actions):
    """The note chat's typed message blocks as on every other surface: the
    card INSTEAD of a reply, whatever the note says."""
    flag("on")
    r = client.post("/api/notes/n1/chat", json=_note_message(CRISIS))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["reply"] == crisis_support.render_reply(body["crisis_support"])
    assert "crisis_support_alongside" not in body
    note_actions["chat"].assert_not_called()
    assert len(_crisis_rows(sink)) == 1  # the typed message's screen; the note is never read


def test_a_note_chat_shows_the_card_every_turn_and_records_it_once_a_day(flag, sink, note_actions, monkeypatch):
    """The chat re-reads the note every turn: the card goes beside every
    answer, but the event is written once per student, note and note
    version a day (per process), not once per turn."""
    flag("on")
    note = _note(None, "") | {"body": f"Hash tables. {CRISIS}.", "updated_at": "2026-11-14T10:00:00Z"}
    clock = [1_000.0]
    monkeypatch.setattr(crisis_support.time, "monotonic", lambda: clock[0])

    def chat(n=note, user="u1"):
        with patch("routes.notes.get_note", AsyncMock(return_value=n)):
            r = client.post(f"/api/notes/{n['id']}/chat", json={"user_id": user, "message": CALM})
        assert r.status_code == 200, r.text
        assert r.json()["crisis_support_alongside"] is True  # the card, every turn
        return len(_crisis_rows(sink))

    assert chat() == 1
    assert chat() == 1  # same note, same version, same day: no second event
    assert chat(note | {"updated_at": "2026-11-14T11:00:00Z"}) == 2  # the note was edited
    assert chat(note | {"id": "n2"}) == 3  # another note
    assert chat(user="u2") == 4  # another student
    clock[0] += 24 * 3600 + 1
    assert chat() == 5  # a day later
    assert note_actions["chat"].await_count == 6  # every turn was answered


def test_other_note_actions_record_every_match(flag, sink, note_actions):
    """Only the chat (re-screened every turn) is deduplicated: each summary
    is one action the student asked for."""
    flag("on")
    for _ in range(2):
        assert client.post("/api/notes/n1/summarize", json=_note_action({})).status_code == 200
    assert len(_crisis_rows(sink)) == 2


def test_the_once_a_day_key_holds_no_content(monkeypatch, sink):
    monkeypatch.setattr(crisis_support, "flag_on", lambda key, uid: True)

    async def run():
        return await crisis_support.screen_content_async(
            _request(), "u1", "note_chat", CRISIS, once_a_day=("n1", "2026-11-14T10:00:00Z"))

    import asyncio

    asyncio.run(run())
    keys = " ".join(crisis_support._recorded_today).lower()
    assert keys and not any(word in keys for word in CRISIS_WORDS + ("n1", "u1"))


def test_once_a_day_forgets_expired_keys_oldest_first(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(crisis_support.time, "monotonic", lambda: clock[0])
    assert crisis_support._first_today(("a",)) is True
    clock[0] = 10.0
    assert crisis_support._first_today(("b",)) is True
    clock[0] = crisis_support._ONCE_A_DAY_S + 5  # a's day is over, b's is not
    assert crisis_support._first_today(("c",)) is True
    assert len(crisis_support._recorded_today) == 2  # a went, from the front
    assert crisis_support._first_today(("b",)) is False
    assert crisis_support._first_today(("a",)) is True  # recorded again, now the newest
    assert list(crisis_support._recorded_today.values()) == sorted(crisis_support._recorded_today.values())


def test_once_a_day_at_the_cap_drops_the_oldest_key(monkeypatch):
    monkeypatch.setattr(crisis_support, "_ONCE_A_DAY_MAX", 3)
    clock = [0.0]
    monkeypatch.setattr(crisis_support.time, "monotonic", lambda: clock[0])
    for i, name in enumerate("abc"):
        clock[0] = float(i)
        assert crisis_support._first_today((name,)) is True
    clock[0] = 3.0
    assert crisis_support._first_today(("d",)) is True  # over the cap: a goes
    assert len(crisis_support._recorded_today) == 3
    assert crisis_support._first_today(("b",)) is False
    assert crisis_support._first_today(("c",)) is False
    assert crisis_support._first_today(("d",)) is False
    assert crisis_support._first_today(("a",)) is True  # forgotten, so recorded again (b goes)
    assert crisis_support._first_today(("b",)) is True


def test_once_a_day_at_the_cap_does_not_scan_every_key(monkeypatch):
    """Eviction is amortized O(1): an insert at the cap touches the front of
    the map only, never every key (or a min() over them)."""
    monkeypatch.setattr(crisis_support, "_ONCE_A_DAY_MAX", 1_000)
    clock = [0.0]
    monkeypatch.setattr(crisis_support.time, "monotonic", lambda: clock[0])
    for i in range(1_000):
        crisis_support._first_today(("k", i))
    visited = [0]  # keys walked over, across every iteration of the map
    real = crisis_support._recorded_today

    def _counted(it):
        for item in it:
            visited[0] += 1
            yield item

    class _Counting(type(real)):
        def items(self):
            return _counted(super().items())

        def keys(self):
            return _counted(super().keys())

        def values(self):
            return _counted(super().values())

        def __iter__(self):
            return _counted(super().__iter__())

    counted = _Counting(real)
    monkeypatch.setattr(crisis_support, "_recorded_today", counted)
    for i in range(1_000, 1_100):
        assert crisis_support._first_today(("k", i)) is True
    assert len(counted) == 1_000
    assert visited[0] <= 2 * 100  # a peek at the front per insert, not a walk over 1,000 keys


# ── Flashcard generate: a graph concept's name, not something typed ────────
#
# The Flashcards page generates one concept per call with the concept's name
# as the topic. A name the student's graph holds is course material (a nursing
# course's "Feeling suicidal"): its cards are made, the card beside them. A
# name that is not one of their concepts is screened as typed and blocks.

CONCEPT_CARDS = {"flashcards": [{"id": "f1", "front": "Q", "back": "A"}]}


@pytest.fixture
def concept_generate():
    """The generation itself stood in; the student's graph concepts are
    `names` (in the request's course). Yields the mocks."""
    mocks = {
        "generate": MagicMock(return_value=dict(CONCEPT_CARDS)),
        "names": MagicMock(return_value=["Hash tables", "Feeling suicidal"]),
    }
    with (
        patch("services.flashcards.generation.generate", mocks["generate"]),
        patch("services.flashcards.concept_topic._graph_concept_names", mocks["names"]),
    ):
        yield mocks


def _generate_body(topic: str) -> dict:
    return {"user_id": "u1", "topic": topic, "count": 5, "course_id": "c1"}


def test_a_graph_concept_topic_makes_its_cards_with_the_card_beside_them(flag, sink, concept_generate):
    flag("on")
    r = client.post("/api/flashcards/generate", json=_generate_body("feeling  Suicidal"))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["flashcards"] == CONCEPT_CARDS["flashcards"]  # the cards were made
    assert body["crisis_support"] == crisis_support.client_payload(crisis_copy.DEFAULT_CAMPUS_COUNSELING)
    assert body["crisis_support_alongside"] is True
    concept_generate["generate"].assert_called_once()
    concept_generate["names"].assert_called_once_with("u1", "c1", "feeling suicidal")  # the student's own, in this course
    assert [row["payload"]["surface"] for row in _crisis_rows(sink)] == ["flashcard_generate"]


def test_a_typed_topic_that_is_not_a_graph_concept_still_blocks(flag, sink, concept_generate):
    flag("on")
    r = client.post("/api/flashcards/generate", json=_generate_body(CRISIS))
    assert r.status_code == 200, r.text
    assert r.json()["flashcards"] == [] and "crisis_support_alongside" not in r.json()
    concept_generate["generate"].assert_not_called()


def test_a_failed_concept_read_blocks_as_typed(flag, sink, concept_generate):
    flag("on")
    concept_generate["names"].side_effect = RuntimeError("PostgREST down")
    r = client.post("/api/flashcards/generate", json=_generate_body("Feeling suicidal"))
    assert r.status_code == 200, r.text
    assert r.json()["flashcards"] == [] and "crisis_support" in r.json()
    concept_generate["generate"].assert_not_called()


def test_a_refused_graph_concept_generation_still_carries_the_card(flag, sink, concept_generate):
    from datetime import datetime, timezone

    flag("on")
    concept_generate["generate"].side_effect = llm_budget.LLMBudgetExceeded(
        limit=1, used=1, reset_at=datetime.now(timezone.utc))
    r = client.post("/api/flashcards/generate", json=_generate_body("Feeling suicidal"))
    assert r.status_code == 429, r.text
    assert "crisis_support" in r.json()


def test_a_calm_topic_never_reads_the_graph(flag, sink, concept_generate):
    flag("on")
    r = client.post("/api/flashcards/generate", json=_generate_body("Hash tables"))
    assert r.status_code == 200, r.text
    assert r.json() == CONCEPT_CARDS
    concept_generate["names"].assert_not_called()


def test_the_graph_concept_read_is_the_students_own(monkeypatch):
    from services.flashcards import concept_topic

    calls = []

    class _Nodes:
        def select(self, cols, filters, limit=None):
            calls.append((cols, filters, limit))
            return [{"concept_name": "Feeling Suicidal"}, {"concept_name": "Feeling very suicidal"}]

    monkeypatch.setattr(concept_topic, "table", lambda name: _Nodes())
    assert concept_topic.topic_is_graph_concept("u1", "feeling  suicidal", "c1") is True
    assert concept_topic.topic_is_graph_concept("u1", "suicidal", None) is False
    assert concept_topic.topic_is_graph_concept("u1", "   ", None) is False
    # Filtered server-side to the candidate name (case-insensitive, any run
    # of spacing between its words), bounded, and confirmed in Python.
    assert calls == [
        ("concept_name", {"user_id": "eq.u1", "course_id": "eq.c1",
                          "or": '(concept_name.ilike."feeling%suicidal")'}, concept_topic._CANDIDATE_LIMIT),
        ("concept_name", {"user_id": "eq.u1", "or": '(concept_name.ilike."suicidal")'},
         concept_topic._CANDIDATE_LIMIT),
    ]


def test_the_graph_concept_pattern_matches_a_like_metacharacter_verbatim(monkeypatch):
    from services.flashcards import concept_topic

    seen = []

    class _Nodes:
        def select(self, cols, filters, limit=None):
            seen.append(filters["or"])
            return [{"concept_name": "100% over it"}]

    monkeypatch.setattr(concept_topic, "table", lambda name: _Nodes())
    assert concept_topic.topic_is_graph_concept("u1", "100% over_it", None) is False
    assert seen == ['(concept_name.ilike."100\\\\%%over\\\\_it")']


def test_a_graph_concept_past_postgrests_row_cap_is_still_found(monkeypatch):
    """A student with more nodes than PostgREST's max-rows (1000): an
    unfiltered read would drop the matching node; the name filter finds it."""
    import re

    from services.flashcards import concept_topic

    nodes = [f"Concept {i}" for i in range(1500)] + ["Feeling suicidal"]

    def _ilike(pattern: str, value: str) -> bool:
        rx = "".join(".*" if c == "%" else re.escape(c) for c in pattern)
        return re.fullmatch(rx, value, flags=re.IGNORECASE) is not None

    class _CappedNodes:
        def select(self, cols, filters, limit=None):
            rows = nodes
            tree = filters.get("or")
            if tree:
                m = re.fullmatch(r'\(concept_name\.ilike\."(.*)"\)', tree)
                rows = [n for n in rows if _ilike(m.group(1), n)]
            cap = min(1000, limit or 1000)
            return [{"concept_name": n} for n in rows[:cap]]

    monkeypatch.setattr(concept_topic, "table", lambda name: _CappedNodes())
    assert concept_topic.topic_is_graph_concept("u1", "FEELING suicidal", None) is True


# ── Send to tutor's topic: the note's title, not something typed ───────────
#
# Send to tutor opens /learn with the note's title as the topic. The student
# already got the card beside that action; a start whose topic IS that title
# (`from_note_id`, re-checked against the student's own note) is stored
# material too, so the session starts with the card beside it. A topic the
# student typed, or one that does not match their note, still blocks.

#: A note titled with the crisis line; Send to tutor's topic is its first line.
CRISIS_NOTE = {"id": "n1", "user_id": "u1", "offering_id": "o1", "title": f"{CRISIS}\nweek 3", "body": ""}
GREETING = {"session_id": "s9", "initial_message": "Let's begin.", "graph_state": {"nodes": []}}
DONE_DATA = {"session_id": "s9", "reply": "Let's begin.", "graph_update": {}, "mastery_changes": []}


def _note_start(**overrides) -> dict:
    return {"user_id": "u1", "topic": CRISIS, "course_id": "c1", "from_note_id": "n1", **overrides}


async def _greeting_stream(body, request, **_route_kwargs):  # the route also hands the loop's `loop_handler`
    from sse_starlette.sse import EventSourceResponse

    from services.agent_events import SaplingEvent, sapling_event_to_sse

    async def events():
        yield sapling_event_to_sse(SaplingEvent(type="token", step="reply", message="Let's", data={"delta": "Let's"}))
        yield sapling_event_to_sse(SaplingEvent(type="done", step="reply", message="Complete.", data=DONE_DATA))

    return EventSourceResponse(events())


@pytest.fixture
def note_start():
    """The two start routes' own work stood in (a greeting); the student's
    note is CRISIS_NOTE. Yields the mocks."""
    mocks = {
        "start": AsyncMock(return_value=dict(GREETING)),
        "stream": AsyncMock(side_effect=_greeting_stream),
        "get_note": AsyncMock(return_value=dict(CRISIS_NOTE)),
    }
    with (
        patch("services.tutor.start_session", mocks["start"]),
        patch("services.tutor.start_session_stream", mocks["stream"]),
        patch("services.tutor.note_topic.get_note", mocks["get_note"]),
    ):
        yield mocks


def test_a_note_titled_topic_starts_the_session_with_the_card_beside_it(flag, sink, note_start):
    flag("on")
    r = client.post("/api/learn/start-session", json=_note_start())
    assert r.status_code == 200, r.text
    body = r.json()
    assert {k: body[k] for k in GREETING} == GREETING  # the session started
    assert body["crisis_support"] == crisis_support.client_payload(crisis_copy.DEFAULT_CAMPUS_COUNSELING)
    assert body["crisis_support_alongside"] is True
    note_start["start"].assert_awaited_once()
    note_start["get_note"].assert_awaited_once_with(note_id="n1", user_id="u1")
    assert [row["payload"]["surface"] for row in _crisis_rows(sink)] == ["tutor_start"]


def test_a_note_titled_topic_streams_the_greeting_with_the_card_in_done(flag, sink, note_start):
    flag("on")
    r = client.post("/api/learn/start-session/stream", json=_note_start())
    assert r.status_code == 200, r.text
    events = _sse_events(r.text)
    assert [name for name, _ in events] == ["token", "done"]  # the greeting streamed as usual
    done = events[-1][1]["data"]
    assert {k: done[k] for k in DONE_DATA} == DONE_DATA
    assert done["crisis_support"] == crisis_support.client_payload(crisis_copy.DEFAULT_CAMPUS_COUNSELING)
    assert done["crisis_support_alongside"] is True
    assert "crisis_support" not in events[0][1]["data"]


def test_a_refused_note_titled_start_still_carries_the_card(flag, sink, note_start):
    flag("on")
    note_start["start"].side_effect = HTTPException(status_code=429, detail="Slow down.",
                                                    headers={"Retry-After": "12"})
    r = client.post("/api/learn/start-session", json=_note_start())
    assert r.status_code == 429, r.text
    assert r.headers["Retry-After"] == "12"
    assert "crisis_support" in r.json()


@pytest.mark.parametrize("why, body, note", [
    ("no note named", {"from_note_id": None}, CRISIS_NOTE),
    ("not the student's note (or gone)", {}, None),
    ("the student edited the topic", {"topic": f"{CRISIS} please"}, CRISIS_NOTE),
    ("a different note's title", {}, {**CRISIS_NOTE, "title": "Week 3"}),
], ids=lambda v: v if isinstance(v, str) else "")
@pytest.mark.parametrize("path", ["/api/learn/start-session", "/api/learn/start-session/stream"])
def test_a_topic_that_is_not_the_notes_title_blocks_as_typed(why, body, note, path, flag, sink, note_start):
    flag("on")
    note_start["get_note"].return_value = note
    r = client.post(path, json=_note_start(**body))
    assert r.status_code == 200, r.text
    card = _sse_events(r.text)[-1][1]["data"] if path.endswith("/stream") else r.json()
    assert card["session_id"] is None and "crisis_support" in card  # the card INSTEAD of a session
    assert "crisis_support_alongside" not in card
    note_start["start"].assert_not_called()
    note_start["stream"].assert_not_called()


def test_a_failed_note_read_blocks_as_typed_rather_than_failing(flag, sink, note_start):
    flag("on")
    note_start["get_note"].side_effect = RuntimeError("PostgREST down")
    r = client.post("/api/learn/start-session", json=_note_start())
    assert r.status_code == 200, r.text
    assert r.json()["session_id"] is None and "crisis_support" in r.json()
    note_start["start"].assert_not_called()


def test_a_stranger_naming_a_note_is_refused_before_it_is_read(flag, sink, note_start, monkeypatch):
    from services import auth_guard

    flag("on")

    def require_self(user_id, request, **_kwargs):
        if user_id != "u1":
            raise HTTPException(status_code=403, detail="Forbidden")

    monkeypatch.setattr(auth_guard, "require_self", require_self)
    r = client.post("/api/learn/start-session", json=_note_start(user_id="u2"))
    assert r.status_code == 403
    note_start["get_note"].assert_not_called()
    assert _crisis_rows(sink) == []


def test_a_calm_note_titled_topic_starts_as_usual(flag, sink, note_start):
    flag("on")
    note_start["get_note"].return_value = {**CRISIS_NOTE, "title": "Week 3"}
    r = client.post("/api/learn/start-session", json=_note_start(topic="Week 3"))
    assert r.status_code == 200, r.text
    assert r.json() == GREETING
    assert _crisis_rows(sink) == []
    note_start["get_note"].assert_not_called()  # the note is read only when the topic matched


def _send_to_tutor(note: dict):
    with (
        patch("routes.notes.get_note", AsyncMock(return_value=note)),
        patch("routes.notes.offering_course_id", return_value="c1"),
    ):
        r = client.post(f"/api/notes/{note['id']}/send-to-tutor", json={"user_id": "u1"})
    assert r.status_code == 200, r.text
    assert r.json()["crisis_support_alongside"] is True
    return r


def _surfaces(sink) -> list[str]:
    return [row["payload"]["surface"] for row in _crisis_rows(sink)]


@pytest.mark.parametrize("path", ["/api/learn/start-session", "/api/learn/start-session/stream"])
def test_the_start_send_to_tutor_hands_over_records_no_second_card(path, flag, sink, note_start):
    """Send to tutor showed (and recorded) the card for this note version; the
    /learn start it hands over shows the card beside the session again but
    records nothing new that day."""
    flag("on")
    note = {**CRISIS_NOTE, "updated_at": "2026-11-14T10:00:00Z"}
    note_start["get_note"].return_value = dict(note)
    _send_to_tutor(note)
    r = client.post(path, json=_note_start())
    assert r.status_code == 200, r.text
    assert "crisis_support" in r.text  # the card still rides beside the session
    assert _surfaces(sink) == ["note_send_to_tutor"]


def test_a_note_titled_start_records_once_a_day_per_note_version(flag, sink, note_start, monkeypatch):
    flag("on")
    clock = [1_000.0]
    monkeypatch.setattr(crisis_support.time, "monotonic", lambda: clock[0])
    note = {**CRISIS_NOTE, "updated_at": "2026-11-14T10:00:00Z"}

    def start(n=note):
        note_start["get_note"].return_value = dict(n)
        r = client.post("/api/learn/start-session", json=_note_start(from_note_id=n["id"]))
        assert r.status_code == 200, r.text
        assert r.json()["crisis_support_alongside"] is True  # the card, every start
        return len(_crisis_rows(sink))

    assert start() == 1
    assert start() == 1  # the same note version, the same day
    assert start(note | {"updated_at": "2026-11-14T11:00:00Z"}) == 2  # the note was edited
    clock[0] += 24 * 3600 + 1
    assert start() == 3  # a day later
    assert _surfaces(sink) == ["tutor_start"] * 3


def test_send_to_tutor_itself_still_records_every_match(flag, sink, note_start):
    flag("on")
    note = {**CRISIS_NOTE, "updated_at": "2026-11-14T10:00:00Z"}
    _send_to_tutor(note)
    _send_to_tutor(note)
    assert _surfaces(sink) == ["note_send_to_tutor"] * 2


def test_a_typed_crisis_topic_still_blocks_and_records_every_start(flag, sink, note_start):
    """Typed topics are unaffected: no dedupe, the card instead of a session."""
    flag("on")
    note = {**CRISIS_NOTE, "updated_at": "2026-11-14T10:00:00Z"}
    _send_to_tutor(note)
    for _ in range(2):
        r = client.post("/api/learn/start-session", json=_note_start(from_note_id=None))
        assert r.status_code == 200, r.text
        assert r.json()["session_id"] is None
    assert _surfaces(sink) == ["note_send_to_tutor", "tutor_start", "tutor_start"]
    note_start["start"].assert_not_called()


def test_the_handoff_key_holds_no_content_or_id(flag, sink, note_start):
    flag("on")
    _send_to_tutor({**CRISIS_NOTE, "updated_at": "2026-11-14T10:00:00Z"})
    keys = " ".join(crisis_support._recorded_today).lower()
    assert keys and not any(word in keys for word in CRISIS_WORDS + ("n1", "u1"))


# ── The same hand-over on the learning loop's start routes (C4) ─────────────
#
# With the loop on, LoopLearn starts on /api/learn/loop/start-session[/stream]
# directly; Send to tutor names its note there too. The topic is the note's
# title, so it is stored material: the loop session opens with the card
# beside it, exactly as on the legacy route, instead of the card twice and no
# session.

LOOP_START = "/api/learn/loop/start-session"
LOOP_START_STREAM = "/api/learn/loop/start-session/stream"


@pytest.fixture
def loop_note_start():
    """The loop's two start bodies stood in (a greeting); the student's note
    is CRISIS_NOTE. Yields the mocks."""
    mocks = {
        "start": AsyncMock(return_value=dict(GREETING)),
        "stream": AsyncMock(side_effect=_greeting_stream),
        "get_note": AsyncMock(return_value=dict(CRISIS_NOTE)),
    }
    with (
        patch("services.loop.start_session", mocks["start"]),
        patch("services.loop.start_session_stream", mocks["stream"]),
        patch("services.tutor.note_topic.get_note", mocks["get_note"]),
    ):
        yield mocks


def test_a_note_titled_loop_start_opens_the_session_with_the_card_beside_it(flag, sink, loop_note_start):
    flag("on")
    r = client.post(LOOP_START, json=_note_start())
    assert r.status_code == 200, r.text
    body = r.json()
    assert {k: body[k] for k in GREETING} == GREETING  # the session started
    assert body["crisis_support"] == crisis_support.client_payload(crisis_copy.DEFAULT_CAMPUS_COUNSELING)
    assert body["crisis_support_alongside"] is True
    loop_note_start["start"].assert_awaited_once()
    loop_note_start["get_note"].assert_awaited_once_with(note_id="n1", user_id="u1")
    assert len(_crisis_rows(sink)) == 1  # one card shown, one event


def test_a_note_titled_loop_start_streams_the_greeting_with_the_card_in_done(flag, sink, loop_note_start):
    flag("on")
    r = client.post(LOOP_START_STREAM, json=_note_start())
    assert r.status_code == 200, r.text
    events = _sse_events(r.text)
    assert [name for name, _ in events] == ["token", "done"]
    done = events[-1][1]["data"]
    assert {k: done[k] for k in DONE_DATA} == DONE_DATA
    assert done["crisis_support_alongside"] is True
    assert "crisis_support" not in events[0][1]["data"]


@pytest.mark.parametrize("path", [LOOP_START, LOOP_START_STREAM])
def test_the_loop_start_send_to_tutor_hands_over_records_no_second_card(path, flag, sink, loop_note_start):
    flag("on")
    note = {**CRISIS_NOTE, "updated_at": "2026-11-14T10:00:00Z"}
    loop_note_start["get_note"].return_value = dict(note)
    _send_to_tutor(note)
    r = client.post(path, json=_note_start())
    assert r.status_code == 200, r.text
    assert "crisis_support" in r.text  # the card rides beside the session
    assert _surfaces(sink) == ["note_send_to_tutor"]


def test_a_rate_limited_note_titled_loop_start_still_carries_the_card(
    flag, sink, loop_note_start, live_accounts, real_limiters,
):
    """The loop's rate limit is a route dependency, after the screen: its 429
    goes back with the card on it, and the session is not started."""
    flag("on")
    real_limiters["limited"] = True
    r = client.post(LOOP_START, json=_note_start())
    assert r.status_code == 429, r.text
    assert r.json()["crisis_support"] == crisis_support.client_payload(crisis_copy.DEFAULT_CAMPUS_COUNSELING)
    loop_note_start["start"].assert_not_called()


@pytest.mark.parametrize("why, body, note", [
    ("no note named", {"from_note_id": None}, CRISIS_NOTE),
    ("not the student's note (or gone)", {}, None),
    ("the student edited the topic", {"topic": f"{CRISIS} please"}, CRISIS_NOTE),
], ids=lambda v: v if isinstance(v, str) else "")
@pytest.mark.parametrize("path", [LOOP_START, LOOP_START_STREAM])
def test_a_loop_topic_that_is_not_the_notes_title_blocks_as_typed(why, body, note, path, flag, sink, loop_note_start):
    flag("on")
    loop_note_start["get_note"].return_value = note
    r = client.post(path, json=_note_start(**body))
    assert r.status_code == 200, r.text
    card = _sse_events(r.text)[-1][1]["data"] if path.endswith("/stream") else r.json()
    assert card["session_id"] is None and "crisis_support" in card  # the card INSTEAD of a session
    assert "crisis_support_alongside" not in card
    loop_note_start["start"].assert_not_called()
    loop_note_start["stream"].assert_not_called()


def test_a_typed_crisis_goal_still_blocks_a_note_titled_loop_start(flag, sink, loop_note_start):
    flag("on")
    goal = {"text": CRISIS, "target_node_ids": ["n1"]}
    r = client.post(LOOP_START, json=_note_start(topic="Week 3", goal=goal))
    assert r.status_code == 200, r.text
    assert r.json()["session_id"] is None and "crisis_support" in r.json()
    loop_note_start["start"].assert_not_called()
    assert _surfaces(sink) == ["loop_start"]


def test_a_calm_note_titled_loop_start_starts_as_usual_without_reading_the_note(flag, sink, loop_note_start):
    flag("on")
    r = client.post(LOOP_START, json=_note_start(topic="Week 3"))
    assert r.status_code == 200, r.text
    assert r.json() == GREETING
    assert _crisis_rows(sink) == []
    loop_note_start["get_note"].assert_not_called()


def test_a_stranger_naming_a_note_on_the_loop_is_refused_before_it_is_read(flag, sink, loop_note_start, monkeypatch):
    from services import auth_guard

    flag("on")

    def require_self(user_id, request, **_kwargs):
        if user_id != "u1":
            raise HTTPException(status_code=403, detail="Forbidden")

    monkeypatch.setattr(auth_guard, "require_self", require_self)
    r = client.post(LOOP_START, json=_note_start(user_id="u2"))
    assert r.status_code == 403
    loop_note_start["get_note"].assert_not_called()
    assert _crisis_rows(sink) == []


# ── Screening precedes every rate limit, budget and quota ───────────────────
#
# A student in crisis must never be answered with a 429 instead of the card.
# These run the REAL limiters on the covered paths with nothing replaced but
# their verdict, and the real path up to them.


@pytest.fixture
def real_limiters(monkeypatch):
    """Every limiter on a covered path, live, with only its verdict replaced:
    the flashcard import window, the set-suggest window, the per-user LLM
    budget at the model chokepoint, and the learning loop's rate-limit
    dependency, inline check and probe/plan window (the autouse
    `no_rate_limit` steps aside for this fixture). Set `limited`; `consulted`
    logs every read (empty = no limiter was even read)."""
    from services.flashcards import import_flow, suggest

    state: dict[str, Any] = {"limited": True, "consulted": []}

    def import_window(user_id):
        state["consulted"].append("flashcards.import_window")
        return 30 if state["limited"] else None

    async def suggest_window(key, *, limit, window_sec):
        state["consulted"].append("flashcards.suggest_window")
        return 30 if state["limited"] else None

    async def budget(messages):
        state["consulted"].append("llm_budget")
        if state["limited"]:
            raise llm_budget.LLMBudgetExceeded(detail="budget reached")

    async def candidates(user_id, course_id):  # the suggest limiter only guards a model call
        return [{"concept_name": "Hash tables", "course_id": "c1", "mastery_tier": "learning"}]

    def loop_rate_limit(user_id):
        state["consulted"].append("ai_budget.rate_limit")
        decision = ai_budget.BudgetDecision(
            level="hard", tier_ceiling="none", scope="rate_limit", reset_at=None,
        )
        return (decision if state["limited"] else None), None

    def probe_plan_window(key, *, limit, window_sec):
        state["consulted"].append("request_limits.check_rate_limit")
        return 30 if state["limited"] else None

    monkeypatch.setattr(ai_budget, "_rate_limit_decision", loop_rate_limit)
    setattr_loop(monkeypatch, "check_rate_limit", probe_plan_window)
    monkeypatch.setattr(import_flow, "check_rate_limit", import_window)
    monkeypatch.setattr(suggest, "acheck_rate_limit", suggest_window)
    monkeypatch.setattr(suggest, "_candidates", candidates)
    monkeypatch.setattr(llm_budget, "check_before_request", budget)
    return state


#: The covered routes with a rate limiter of their own on main (the tutor and
#: notes routes and flashcard generation are budgeted at the model chokepoint
#: only). The learning loop's routes are limited too: see the LOOP tests below.
RATE_LIMITED = [c for c in CASES
                if c.path.startswith("/api/flashcards/") and c.path != "/api/flashcards/generate"]


def _post_real(case: Case, text: str):
    """POST the case down its real path (no sentinel). Only the student's note
    is stood in (a database row)."""
    with patch("routes.notes.get_note", AsyncMock(return_value=_note(case, text))):
        return client.post(case.path, json=case.body(text))


@pytest.mark.parametrize("case", RATE_LIMITED, ids=[c.id for c in RATE_LIMITED])
def test_a_rate_limited_student_gets_the_card_and_ordinary_text_still_gets_the_429(
    case, flag, model_calls, sink, real_limiters
):
    flag("on")
    real_limiters["limited"] = True
    consulted = real_limiters["consulted"]

    body = _card_of(case, _post_real(case, CRISIS))
    assert "crisis_support" in body
    assert consulted == []  # the limiter was not even read

    r = _post_real(case, CALM)
    assert r.status_code == 429, r.text
    assert consulted, "the limiter answered the ordinary request"
    assert model_calls == []


@pytest.mark.parametrize("case", BLOCKING, ids=BLOCKING_IDS)
def test_a_budget_capped_student_gets_the_card(case, flag, model_calls, sink, real_limiters):
    """The per-user LLM budget is read at the model chokepoint, which a crisis
    turn never reaches: an exhausted budget cannot answer it with a 429."""
    flag("on")
    real_limiters["limited"] = True
    body = _card_of(case, _post_real(case, CRISIS))
    assert "crisis_support" in body
    assert real_limiters["consulted"] == []


@pytest.mark.parametrize("case", BLOCKING, ids=BLOCKING_IDS)
def test_a_crisis_turn_consumes_no_rate_limit_or_budget_unit(
    case, flag, model_calls, sink, live_accounts, real_limiters, monkeypatch
):
    """Nothing a limiter counts moves: no limiter is even read, no llm_usage
    row is logged, no sliding-window slot is taken, and no tutor call is
    counted (in process or in the database: the loop's A20 unit)."""
    from services import request_limits

    flag("on")
    real_limiters["limited"] = False
    usage_rows = MagicMock(wraps=events_service.log_llm_usage)
    tutor_calls = MagicMock(wraps=ai_budget.count_tutor_call)
    monkeypatch.setattr(events_service, "log_llm_usage", usage_rows)
    monkeypatch.setattr(ai_budget, "count_tutor_call", tutor_calls)
    windows = {k: list(v) for k, v in request_limits._rate_state.items()}
    local_calls = dict(ai_budget._tutor_calls_local)
    writes = _db_writes()

    _card_of(case, _post_real(case, CRISIS))

    assert real_limiters["consulted"] == []
    usage_rows.assert_not_called()
    tutor_calls.assert_not_called()
    assert {k: list(v) for k, v in request_limits._rate_state.items()} == windows
    assert dict(ai_budget._tutor_calls_local) == local_calls
    assert _db_writes() == writes  # the tutor-call RPC is a write too


# ── The learning loop's limiters ────────────────────────────────────────────
#
# Most loop routes carry their rate limit as a ROUTE DEPENDENCY
# (`_RATE_LIMITED`), which runs before any handler code, so their screen is a
# dependency too (`crisis_support.screened`), listed between the loop's kill
# switch and the rate limit. The rest (goal, probe, review) screen inline,
# first thing after the loop's gate.


@pytest.mark.parametrize("case", LOOP, ids=LOOP_IDS)
def test_a_rate_limited_loop_student_gets_the_card_and_ordinary_text_still_gets_the_429(
    case, flag, model_calls, sink, live_accounts, real_limiters
):
    flag("on")
    real_limiters["limited"] = True
    consulted = real_limiters["consulted"]

    body = _card_of(case, _post_real(case, CRISIS))
    assert "crisis_support" in body
    assert "budget" not in body  # no pause notice rides on the card
    assert consulted == []  # the limiter was not even read
    events_service.flush_now()
    assert [r for r in sink if r["event_type"] == "ai.budget_capped"] == []  # no cap recorded

    r = _post_real(case, CALM)
    assert r.status_code == 429, r.text
    assert consulted, "the limiter answered the ordinary request"


@pytest.mark.parametrize("case", LOOP, ids=LOOP_IDS)
def test_a_budget_capped_loop_student_gets_the_card(case, flag, model_calls, sink, monkeypatch):
    """The loop's AI budget (A20) is never consulted on a crisis turn, so it
    cannot pause the student instead of showing the card."""
    flag("on")
    budget = MagicMock(return_value=ai_budget.BudgetDecision(
        level="hard", tier_ceiling="none", scope="daily_usd", reset_at=None, pause_novice=True,
    ))
    monkeypatch.setattr(ai_budget, "check", budget)

    body = _card_of(case, _post_real(case, CRISIS))
    assert "crisis_support" in body
    assert "budget" not in body
    budget.assert_not_called()


def test_the_screen_dependency_authenticates_before_the_flag_and_the_event(flag, model_calls, sink, monkeypatch):
    """The dependency runs before the handler's own require_self, so it checks
    the caller itself, before it reads the flag or records anything: another
    student's user_id is refused, and nothing is attributed to them."""
    from services import auth_guard

    flag("on")

    def require_self(user_id, request, **_kwargs):
        if user_id != "u1":  # the session is u1's
            raise HTTPException(status_code=403, detail="Forbidden")

    monkeypatch.setattr(auth_guard, "require_self", require_self)
    flag_reads = MagicMock(return_value=True)
    monkeypatch.setattr(crisis_support, "flag_on", flag_reads)

    r = client.post("/api/learn/loop/chat", json={**_chat(CRISIS), "user_id": "u2"})
    assert r.status_code == 403
    flag_reads.assert_not_called()
    assert _crisis_rows(sink) == []

    r = client.post("/api/learn/loop/chat", json=_chat(CRISIS))
    assert r.status_code == 200 and "crisis_support" in r.json()
    assert [row["user_id"] for row in _crisis_rows(sink)] == ["u1"]


def test_a_body_naming_no_student_is_screened_as_the_session_user(flag, model_calls, sink):
    """posttest/answer's body may omit user_id (resolved from the session); the
    screen does the same, so the card and the event are the session user's."""
    flag("on")
    r = client.post("/api/learn/loop/posttest/answer",
                    json={"node_id": "n1", "question_hash": "qh", "answer": CRISIS})
    assert r.status_code == 200 and "crisis_support" in r.json()
    assert [row["user_id"] for row in _crisis_rows(sink)] == ["user_andres"]  # conftest's session stub


def test_the_screen_dependency_reads_no_flag_for_ordinary_text(flag, model_calls, monkeypatch):
    flag("on")
    flag_reads = MagicMock(return_value=True)
    monkeypatch.setattr(crisis_support, "flag_on", flag_reads)
    case = next(c for c in CASES if c.path == "/api/learn/loop/chat")
    r, _ = _post(case, CALM)
    assert r.status_code == SENTINEL
    flag_reads.assert_not_called()


#: Every covered loop route whose limiter is a route dependency (`_RATE_LIMITED`).
SCREENED_BY_DEPENDENCY = {
    "/api/learn/loop/chat", "/api/learn/loop/chat/stream",
    "/api/learn/loop/check/answer", "/api/learn/loop/check/answer/stream",
    "/api/learn/loop/posttest/answer", "/api/learn/loop/step/attempt",
    "/api/learn/loop/start-session", "/api/learn/loop/start-session/stream",
    # spec §13 A138 / A139
    "/api/learn/loop/prequestion/answer", "/api/learn/loop/prequestion/answer/stream",
    "/api/learn/loop/self-explain",
}
#: Every covered loop route whose limiters are all inline: (path, the screen's
#: call, the limiter calls it must precede in the handler's source).
SCREENED_INLINE = [
    ("/api/learn/loop/goal", "crisis_support.screen(", ("_probe_plan_read_limit(",)),
    # #117: the loop's limiter read hops off the event loop, as the tutor's does
    ("/api/learn/loop/probe/answer", "crisis_support.screen_async", ("enforce_rate_limit_for,",)),
    ("/api/learn/loop/review/answer", "crisis_support.screen_async", ("enforce_rate_limit_for,",)),
]


def _loop_routes():
    """(full path, route) for every POST route of the loop's own router (an
    included router is one app.routes entry)."""
    from routes import learn_loop

    for route in learn_loop.router.routes:
        if "POST" in getattr(route, "methods", set()):
            yield "/api/learn/loop" + route.path, route


def test_every_covered_loop_route_is_pinned():
    assert {c.path for c in LOOP} == SCREENED_BY_DEPENDENCY | {p for p, _, _ in SCREENED_INLINE}


def test_a_screen_dependency_precedes_every_rate_limit_dependency():
    """Structural pin: on every loop route that carries both, the crisis screen
    comes before the rate limit, and after only the kill switch."""
    from routes import learn_loop

    screened_paths = set()
    for path, route in _loop_routes():
        calls = [d.call for d in route.dependant.dependencies]
        screens = [i for i, call in enumerate(calls) if crisis_support.is_screen(call)]
        if not screens:
            continue
        screened_paths.add(path)
        assert len(screens) == 1, path
        assert ai_budget.enforce_rate_limit in calls, path
        assert calls.index(learn_loop._kill_switch_first) < screens[0] < calls.index(
            ai_budget.enforce_rate_limit
        ), path
    assert screened_paths == SCREENED_BY_DEPENDENCY


@pytest.mark.parametrize("path, screen_call, limiters", SCREENED_INLINE)
def test_an_inline_loop_screen_precedes_every_inline_limiter(path, screen_call, limiters):
    """Structural pin for the loop routes whose limiters are inline: the screen
    is called before each of them in the handler, and no limiter is a
    dependency."""
    route = next(r for full, r in _loop_routes() if full == path)
    assert ai_budget.enforce_rate_limit not in [d.call for d in route.dependant.dependencies], path
    import services.loop as loop  # #118: the thin route wrapper's body

    source = inspect.getsource(getattr(loop, route.endpoint.__name__, route.endpoint))
    for limiter in limiters:
        assert limiter in source, (path, limiter)
        assert source.index(screen_call) < source.index(limiter), (path, limiter)


def _covered_routes():
    """(full path, route) for every covered POST route, read off each module's
    own router (an included router is one app.routes entry)."""
    from routes import flashcards, learn, notes

    covered = {c.path.replace("/n1/", "/{note_id}/") for c in CASES if not c.loop}
    for prefix, router in (("/api/learn", learn.router), ("/api/notes", notes.router),
                           ("/api/flashcards", flashcards.router)):
        for route in router.routes:
            full = prefix + route.path
            if "POST" in getattr(route, "methods", set()) and full in covered:
                yield full, route


#: A call that reads as a limiter: rate limit, budget, quota, throttle.
_LIMITER_CALL = re.compile(r"\b\w*(?:limit|budget|quota|throttle)\w*\s*\(", re.IGNORECASE)


def test_every_covered_route_is_found():
    assert {path for path, _ in _covered_routes()} == {
        c.path.replace("/n1/", "/{note_id}/") for c in CASES if not c.loop
    }


@pytest.mark.parametrize("path, route", list(_covered_routes()), ids=lambda v: v if isinstance(v, str) else "")
def test_the_screen_precedes_every_limiter_on_the_route(path, route):
    """Structural pin, for whatever limiter a later change adds: no route
    dependency runs ahead of the handler (a limiter dependency would run before
    the screen), and in the handler's source the screen comes before every
    call that reads as a limiter, budget or quota. Move the screen up, never a
    limiter above it."""
    assert route.dependant.dependencies == [], (
        f"{path} has a route dependency; it would run BEFORE the crisis screen"
    )
    source = inspect.getsource(route.endpoint)
    screen = source.index("crisis_support.screen")
    early = [m.group(0) for m in _LIMITER_CALL.finditer(source) if m.start() < screen]
    assert early == [], (path, early)


# ── The inventory: no student text reaches a model unscreened ──────────────
#
# Every write route in a module that fronts a model, whose body carries free
# text (a string that is not an id), is either SCREENED (its handler calls
# crisis_support.screen and it has a Case above) or listed in NOT_SCREENED
# with why no model reads that text as the student's message. A new route
# with a text field fails here until it is one or the other. (Routes that
# read STORED text, like the notes agent actions, have no text field: they
# are pinned by CASES and test_every_covered_route_is_found, and their screen
# is the NON-blocking one, `screen_content_async`: the card alongside the
# action's answer, pinned by the CONTENT cases.)

#: The route modules whose handlers run a model on the student's request.
MODEL_ROUTE_MODULES = ("learn", "notes", "flashcards", "quiz", "graph", "study_guide")

NOT_SCREENED: dict[str, str] = {
    "learn PATCH /sessions/{session_id}": "renames a session; no model",
    "notes POST ": "creates a note; no model (its agent actions screen the stored note)",
    "notes PATCH /{note_id}": "edits a note; no model (its agent actions screen the stored note)",
    "flashcards POST /sets": "saves a set's name and concepts; no model",
    "flashcards POST /import/commit": "writes the reviewed cards; no model",
    "flashcards POST /import/parse": "uploaded course material (a file or URL), not screened (docs)",
    "flashcards POST /import/cleanup": (
        "imported third-party study material, not the student's own writing; the student's own "
        "words reach a screen on the tutor, notes and flashcard-generate surfaces"
    ),
    "quiz POST /generate": "a difficulty choice, not text",
    "quiz POST /attempts/{attempt_id}/answer": "graded deterministically; owner decision (docs)",
    "quiz POST /submit": "the chosen options' labels, not text",
    "graph POST /{user_id}/courses": "a course colour",
    "graph PATCH /{user_id}/courses/{course_id}/color": "a course colour",
    "graph POST /{user_id}/nodes": "adds a concept to the map; no model",
    "graph PATCH /{user_id}/nodes/{node_id}/color": "a concept colour",
    "graph POST /{user_id}/concept-description": "a concept name off the student's map (docs)",
    "study_guide POST /{user_id}/plan": "ids and choices (course, term, scope, materials)",
    "study_guide POST /{user_id}/guides": "ids and choices (course, term, scope, materials)",
}


def _free_text_fields(model, prefix: str = "") -> list[str]:
    """The str fields of a body model (nested models and lists of them too),
    ids (`models.Id`) left out."""
    import typing

    from pydantic import BaseModel

    from models import ID_MAX

    def models_in(annotation):
        return [a for a in (annotation, *typing.get_args(annotation))
                if inspect.isclass(a) and issubclass(a, BaseModel)]

    found: list[str] = []
    for name, f in model.model_fields.items():
        args = (f.annotation, *typing.get_args(f.annotation))
        if str in args:
            if [m.max_length for m in f.metadata if hasattr(m, "max_length")] != [ID_MAX]:
                found.append(prefix + name)
            continue
        for arg in args:
            for nested in models_in(arg):
                found += _free_text_fields(nested, f"{prefix}{name}.")
    return found


def _text_routes():
    """(key, route, free-text fields) for every write route of the model route
    modules whose body carries free text, read off each module's own router."""
    import importlib
    import typing

    from pydantic import BaseModel

    for module in MODEL_ROUTE_MODULES:
        router = importlib.import_module(f"routes.{module}").router
        for route in router.routes:
            for method in sorted(getattr(route, "methods", set()) & {"POST", "PUT", "PATCH"}):
                hints = typing.get_type_hints(route.endpoint)
                fields = [f for hint in hints.values()
                          if inspect.isclass(hint) and issubclass(hint, BaseModel)
                          for f in _free_text_fields(hint)]
                if fields:
                    yield f"{module} {method} {route.path}", route, list(dict.fromkeys(fields))


def test_no_student_text_reaches_a_model_unscreened():
    covered = {c.path.replace("/n1/", "/{note_id}/") for c in CASES}
    unscreened, untested, seen = [], [], set()
    for key, route, fields in _text_routes():
        seen.add(key)
        screened = "crisis_support.screen" in inspect.getsource(route.endpoint)
        module, _, path = key.split(" ", 2)
        prefix = "/api/" + module.replace("_", "-")
        if screened and prefix + path not in covered:
            untested.append(key)
        if not screened and key not in NOT_SCREENED:
            unscreened.append((key, fields))
    assert unscreened == [], (
        "these routes take student text and do not call crisis_support.screen: screen them "
        "(docs/safety/crisis-support.md, 'Adding a surface') or say in NOT_SCREENED why no "
        f"model reads it: {unscreened}"
    )
    assert untested == [], f"screened but no Case in CASES: {untested}"
    stale = sorted(k for k in NOT_SCREENED if k not in seen)
    assert stale == [], f"NOT_SCREENED names routes that no longer take text: {stale}"
    screened_now = sorted(
        k for k, route, _ in _text_routes()
        if k in NOT_SCREENED and "crisis_support.screen" in inspect.getsource(route.endpoint)
    )
    assert screened_now == [], f"screened now, drop from NOT_SCREENED: {screened_now}"


# ── The screen itself ───────────────────────────────────────────────────────


def _request():
    return MagicMock(name="Request")


def test_an_ordinary_message_never_reads_the_flag_or_authenticates(monkeypatch):
    from services import auth_guard

    read = MagicMock(return_value=True)
    auth = MagicMock()
    monkeypatch.setattr(crisis_support, "flag_on", read)
    monkeypatch.setattr(auth_guard, "require_self", auth)
    assert crisis_support.screen(_request(), "u1", "tutor_chat", CALM, None, "") is None
    read.assert_not_called()
    auth.assert_not_called()


def test_flag_off_means_no_card_and_no_event(monkeypatch, sink):
    monkeypatch.setattr(crisis_support, "flag_on", lambda key, uid: False)
    assert crisis_support.screen(_request(), "u1", "tutor_chat", CRISIS) is None
    assert _crisis_rows(sink) == []


def test_the_flag_is_resolved_for_the_student(monkeypatch, sink):
    seen = []
    monkeypatch.setattr(crisis_support, "flag_on", lambda key, uid: seen.append((key, uid)) or True)
    support = crisis_support.screen(_request(), "u7", "note_chat", CRISIS)
    assert seen == [("crisis_support", "u7")]
    assert support.surface == "note_chat" and support.category == "suicidal_ideation"
    assert "category" not in support.payload  # the client is never told what matched


def test_an_unknown_surface_is_a_programming_error(monkeypatch):
    monkeypatch.setattr(crisis_support, "flag_on", lambda key, uid: True)
    with pytest.raises(ValueError):
        crisis_support.screen(_request(), "u1", "room_chat", CALM)


def test_the_most_severe_field_is_reported(monkeypatch, sink):
    monkeypatch.setattr(crisis_support, "flag_on", lambda key, uid: True)
    crisis_support.screen(_request(), "u1", "note_summarize", "I want to hurt myself", "I took a bunch of pills")
    assert _crisis_rows(sink)[0]["payload"]["category"] == "acute_danger"


def test_async_screen_scans_long_text_off_the_event_loop(monkeypatch, sink):
    import asyncio
    import threading

    monkeypatch.setattr(crisis_support, "flag_on", lambda key, uid: True)
    threads: list[str] = []
    real = crisis_support.detect_any

    def spy(texts, **kwargs):
        threads.append(threading.current_thread().name)
        return real(texts, **kwargs)

    monkeypatch.setattr(crisis_support, "detect_any", spy)
    long_note = "Lecture notes. " * 1000 + CRISIS

    async def main():
        loop_thread = threading.current_thread().name
        assert await crisis_support.screen_async(_request(), "u1", "note_summarize", long_note) is not None
        assert await crisis_support.screen_async(_request(), "u1", "tutor_chat", CRISIS) is not None
        return loop_thread

    loop_thread = asyncio.run(main())
    assert threads[0] != loop_thread  # the long note: in a worker thread
    assert threads[1] == loop_thread  # a chat message: inline, it is microseconds


async def _a_result() -> dict:
    return {"summary": "Short summary."}


def test_a_stored_material_screen_can_only_ride_alongside(monkeypatch, sink):
    """`screen_content_async` answers with a `ContentScreen`, never a
    `CrisisSupport`: every blocking builder refuses it (a note can never be
    answered with the card INSTEAD of its result), and `alongside` refuses
    anything else (a typed message's card cannot be slipped beside a result)."""
    import asyncio

    monkeypatch.setattr(crisis_support, "flag_on", lambda key, uid: True)

    async def screens():
        return [await crisis_support.screen_content_async(_request(), "u1", "note_summarize", text)
                for text in (CRISIS, CALM)]

    for screen in asyncio.run(screens()):
        assert isinstance(screen, crisis_support.ContentScreen)
        for build in (crisis_support.json_body, crisis_support.turn_json, crisis_support.start_json):
            with pytest.raises(TypeError):
                build(screen)
        with pytest.raises(TypeError):
            crisis_support.sse_response(screen, _request())

    typed = crisis_support.screen(_request(), "u1", "note_chat", CRISIS)
    for not_a_content_screen in (typed, None):
        with pytest.raises(TypeError):
            asyncio.run(crisis_support.alongside(not_a_content_screen, _a_result()))


def test_a_calm_stored_material_screen_returns_the_result_alone(monkeypatch, sink):
    import asyncio

    monkeypatch.setattr(crisis_support, "flag_on", lambda key, uid: True)

    async def main():
        screen = await crisis_support.screen_content_async(_request(), "u1", "note_summarize", CALM)
        return await crisis_support.alongside(screen, _a_result())

    assert asyncio.run(main()) == {"summary": "Short summary."}
    assert _crisis_rows(sink) == []


# ── Campus counseling: one config spot, per school ─────────────────────────


def test_no_school_configured_means_the_default_and_no_read(monkeypatch):
    """Today (CAMPUS_COUNSELING empty) the crisis path makes no school read at
    all. Asserted on the mock, not by raising: a failed read is swallowed by
    design (it falls back to the default)."""
    read = MagicMock()
    monkeypatch.setattr(crisis_support, "table", read)
    assert crisis_copy.CAMPUS_COUNSELING == {}
    assert crisis_support.counseling_for("u1") == crisis_copy.DEFAULT_CAMPUS_COUNSELING
    read.assert_not_called()


def test_a_configured_school_gets_its_own_counseling_entry(monkeypatch):
    bu = crisis_copy.CampusCounseling(name="Test Counseling", detail="Walk in 9-5.",
                                      phone="555-0100", url="https://example.edu/counseling")
    monkeypatch.setitem(crisis_copy.CAMPUS_COUNSELING, "bu", bu)
    read = MagicMock()
    read.return_value.select.return_value = [
        {"course_offerings": {"courses": {"schools": None}}},
        {"course_offerings": {"courses": {"schools": {"slug": "bu"}}}},
    ]
    monkeypatch.setattr(crisis_support, "table", read)
    assert crisis_support.counseling_for("u1") == bu
    read.assert_called_once_with("enrollments")
    payload = crisis_support.client_payload(bu)
    campus = next(r for r in payload["resources"] if r["id"] == "campus_counseling")
    assert campus["name"] == "Test Counseling"
    assert {a["href"] for a in campus["actions"]} == {"tel:555-0100", "https://example.edu/counseling"}


@pytest.mark.parametrize("rows, error", [
    ([{"course_offerings": {"courses": {"schools": {"slug": "elsewhere"}}}}], None),
    ([], None),
    (None, RuntimeError("PostgREST down")),
])
def test_an_unknown_school_or_a_failed_read_falls_back_to_the_default(monkeypatch, rows, error):
    monkeypatch.setitem(crisis_copy.CAMPUS_COUNSELING, "bu", crisis_copy.DEFAULT_CAMPUS_COUNSELING)
    read = MagicMock()
    read.return_value.select.side_effect = error
    read.return_value.select.return_value = rows
    monkeypatch.setattr(crisis_support, "table", read)
    assert crisis_support.counseling_for("u1") == crisis_copy.DEFAULT_CAMPUS_COUNSELING


# ── The copy (pending owner review) ─────────────────────────────────────────


def test_the_copy_is_pending_owner_review():
    """Flipping this is the owner's last checklist step — a deliberate change."""
    assert crisis_copy.REVIEW_STATUS == "pending_owner_review"


def test_the_card_carries_every_required_resource():
    payload = crisis_support.client_payload(crisis_copy.DEFAULT_CAMPUS_COUNSELING)
    hrefs = {a["href"] for r in payload["resources"] for a in r["actions"]}
    assert {"tel:988", "sms:988", "sms:741741?body=HOME", "tel:911", "https://findahelpline.com"} <= hrefs
    ids = [r["id"] for r in payload["resources"]]
    assert ids == ["lifeline_988", "crisis_text_line", "campus_counseling", "emergency", "international"]
    intro = " ".join(payload["intro"])
    assert "study tool" in intro and "not a crisis service" in intro
    assert "keep studying" in " ".join(payload["closing"])
    reply = crisis_support.render_reply(payload)
    for resource in payload["resources"]:
        assert resource["name"] in reply
    assert "988" in reply and "741741" in reply and "911" in reply and "findahelpline.com" in reply


def test_the_frontend_fixture_has_the_payload_shape():
    """frontend/src/test-utils/crisisSupport.json is what the vitest suites
    render the card from. Its SHAPE (keys at every level) is pinned to the
    payload here, so the two cannot drift; its wording may lag a copy edit."""
    from pathlib import Path

    fixture_path = Path(__file__).resolve().parents[2] / "frontend/src/test-utils/crisisSupport.json"
    fixture = json.loads(fixture_path.read_text())
    payload = crisis_support.client_payload(crisis_copy.DEFAULT_CAMPUS_COUNSELING)

    def shape(value):
        if isinstance(value, dict):
            return {k: shape(v) for k, v in value.items()}
        if isinstance(value, list):
            return sorted({json.dumps(shape(v), sort_keys=True) for v in value})
        return type(value).__name__

    assert shape(fixture) == shape(payload)
    assert [r["id"] for r in fixture["resources"]] == [r["id"] for r in payload["resources"]]


def test_every_link_is_a_safe_scheme():
    payload = crisis_support.client_payload(crisis_copy.DEFAULT_CAMPUS_COUNSELING)
    for resource in payload["resources"]:
        for action in resource["actions"]:
            assert action["href"].split(":", 1)[0] in {"tel", "sms", "https"}, action


# ── Flag, event and PostHog ─────────────────────────────────────────────────


def test_the_flag_ships_off_server_side():
    fd = REGISTRY["crisis_support"]
    assert fd.variants == ("off", "on")
    assert fd.client_visible is False
    assert "OFF" in fd.description and "review" in fd.description


def test_the_flag_defaults_off(monkeypatch):
    """No stored default, no rule, no env override: the path is off."""
    from services import feature_flags

    monkeypatch.delenv("SAPLING_FLAG_CRISIS_SUPPORT", raising=False)
    assert feature_flags.flag_on("crisis_support", "u1") is False


def test_the_event_is_in_the_taxonomy_and_never_mirrored():
    assert crisis_support.EVENT in events_service.EVENT_TAXONOMY
    assert crisis_support.EVENT in posthog_client._NOT_MIRRORED


def test_the_event_never_reaches_posthog(monkeypatch, sink):
    """Behavioural, with a live (fake) PostHog client: an ordinary event is
    captured, the crisis event is not — it stays in our own table."""
    from services import analytics_consent
    from services.analytics_consent import Consent

    fake = MagicMock(name="PosthogClient")
    monkeypatch.setattr(posthog_client, "disabled_reason", lambda **k: None)
    monkeypatch.setattr(posthog_client, "_product_analytics_on", lambda actor: True)
    monkeypatch.setattr(analytics_consent, "_lookup", lambda uid: Consent.ALLOWED)
    analytics_consent.clear_analytics_consent_cache()
    posthog_client.set_client_for_tests(fake)
    try:
        monkeypatch.setattr(crisis_support, "flag_on", lambda key, uid: True)
        crisis_support.screen(_request(), "user_1", "tutor_chat", CRISIS)
        events_service.log_event("note.created", category="usage", user_id="user_1")
        assert posthog_client.flush_queue(timeout_seconds=5)
    finally:
        posthog_client.set_client_for_tests(None)
        analytics_consent.clear_analytics_consent_cache()
    captured = [c.kwargs.get("event") or c.args[0] for c in fake.capture.call_args_list]
    assert "note.created" in captured  # the fake client is live
    assert crisis_support.EVENT not in captured
    assert len(_crisis_rows(sink)) == 1  # our own row is kept


# ── The function-mode seam ──────────────────────────────────────────────────


def test_function_mode_the_scripted_model_is_never_called_on_a_crisis_message(monkeypatch, flag):
    """Under SAPLING_MODEL_MODE=function a crisis turn needs no handler: the
    path makes no model call, so the scripted model is never reached. A
    handler is registered for EVERY task, counting calls; the control turn
    (a tutor session opener with the learning loop off, the shortest real
    model path) proves the harness does see a model call when one is made."""
    from typing import get_args

    import config

    from pydantic_ai.messages import ModelResponse, TextPart

    from agents._providers import (
        AgentTask, clear_function_handlers, model_for, register_function_handler,
    )
    from agents.chat_tutor import socratic_agent

    monkeypatch.setenv("SAPLING_MODEL_MODE", "function")
    monkeypatch.delenv("SAPLING_FUNCTION_HANDLERS", raising=False)
    flag("on")
    calls: list[str] = []

    def handler_for(task):
        def handler(messages, info):
            calls.append(task)
            return ModelResponse(parts=[TextPart(content="scripted reply")])

        return handler

    clear_function_handlers()
    for task in get_args(AgentTask):
        register_function_handler(task, handler_for(task))
    try:
        with (
            socratic_agent.override(model=model_for("chat_tutor")),
            patch("services.tutor.course._get_course_id_for_topic", AsyncMock(return_value="")),
            patch("routes.notes.get_note", AsyncMock(return_value=_note(None, CRISIS) | {"body": CRISIS})),
        ):
            for case in BLOCKING:
                r = client.post(case.path, json=case.body(CRISIS))
                assert r.status_code == 200 and "crisis_support" in r.text, case.path
            assert calls == [], "the scripted model must never run on a crisis message"

            # with the loop on, the tutor start delegates to the loop's opener
            monkeypatch.setattr(config, "LEARNING_LOOP_ENABLED", False)
            r = client.post("/api/learn/start-session", json={"user_id": "u1", "topic": "Recursion"})
            assert r.status_code == 200, r.text
            assert r.json()["initial_message"] == "scripted reply"
            assert calls == ["chat_tutor"], "control: the seam is observed when a model runs"
    finally:
        clear_function_handlers()
        PENDING_SESSIONS.clear()
