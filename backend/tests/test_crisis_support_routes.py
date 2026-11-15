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
from services import crisis_support, events_service, llm_budget, posthog_client
from services import crisis_support_copy as crisis_copy
from services.feature_flags import REGISTRY
from services.tutor_sessions import PENDING_SESSIONS

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

    @property
    def blocks(self) -> bool:
        """A typed message blocks; a note's stored content shows the card alongside."""
        return self.note_field is None

    @property
    def id(self) -> str:
        return f"{self.path}:{self.note_field or self.body.__name__}"


def _chat(text):
    return {"session_id": "s1", "user_id": "u1", "message": text}


def _start(text):
    return {"user_id": "u1", "topic": text, "course_id": "c1"}


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
    Case("flashcard_generate", "/api/flashcards/generate", _topic,
         "services.flashcards.generation.generate", neutral={"flashcards": []}),
]
IDS = [c.id for c in CASES]
BLOCKING = [c for c in CASES if c.blocks]
BLOCKING_IDS = [c.id for c in BLOCKING]
CONTENT = [c for c in CASES if not c.blocks]
CONTENT_IDS = [c.id for c in CONTENT]


# ── Fixtures ────────────────────────────────────────────────────────────────


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
    with (
        patch(case.next_step, mock),
        patch("routes.notes.get_note", AsyncMock(return_value=_note(case, text))),
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
    if case.surface == "tutor_start" and not case.stream:
        assert body["initial_message"] == body["reply"]

    next_step.assert_not_called()  # the turn never started
    assert model_calls == []  # no model
    assert _db_writes() == writes  # no message, session, summary, concept or card row
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


def test_the_streamed_card_is_the_tutor_streams_own_terminal_shape(flag, model_calls):
    """The frontend's consumeChatStream resolves a turn from `done.data` and
    needs nothing before it; the crisis stream is exactly that one event."""
    flag("on")
    r = client.post("/api/learn/chat/stream", json=_chat(CRISIS))
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


# ── Screening precedes every rate limit, budget and quota ───────────────────
#
# A student in crisis must never be answered with a 429 instead of the card.
# These run the REAL limiters on the covered paths with nothing replaced but
# their verdict, and the real path up to them.


@pytest.fixture
def real_limiters(monkeypatch):
    """Every limiter on a covered path, live, with only its verdict replaced:
    the flashcard import window, the set-suggest window and the per-user LLM
    budget at the model chokepoint. Set `limited`; `consulted` logs every read
    (empty = no limiter was even read)."""
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

    monkeypatch.setattr(import_flow, "check_rate_limit", import_window)
    monkeypatch.setattr(suggest, "acheck_rate_limit", suggest_window)
    monkeypatch.setattr(suggest, "_candidates", candidates)
    monkeypatch.setattr(llm_budget, "check_before_request", budget)
    return state


#: The covered routes with a rate limiter of their own on main (the tutor and
#: notes routes and flashcard generation are budgeted at the model chokepoint
#: only).
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
    case, flag, model_calls, sink, real_limiters, monkeypatch
):
    """Nothing a limiter counts moves: no limiter is even read, no llm_usage
    row is logged, and no sliding-window slot is taken."""
    from services import request_limits

    flag("on")
    real_limiters["limited"] = False
    usage_rows = MagicMock(wraps=events_service.log_llm_usage)
    monkeypatch.setattr(events_service, "log_llm_usage", usage_rows)
    windows = {k: list(v) for k, v in request_limits._rate_state.items()}
    writes = _db_writes()

    _card_of(case, _post_real(case, CRISIS))

    assert real_limiters["consulted"] == []
    usage_rows.assert_not_called()
    assert {k: list(v) for k, v in request_limits._rate_state.items()} == windows
    assert _db_writes() == writes


def _covered_routes():
    """(full path, route) for every covered POST route, read off each module's
    own router (an included router is one app.routes entry)."""
    from routes import flashcards, learn, notes

    covered = {c.path.replace("/n1/", "/{note_id}/") for c in CASES}
    for prefix, router in (("/api/learn", learn.router), ("/api/notes", notes.router),
                           ("/api/flashcards", flashcards.router)):
        for route in router.routes:
            full = prefix + route.path
            if "POST" in getattr(route, "methods", set()) and full in covered:
                yield full, route


#: A call that reads as a limiter: rate limit, budget, quota, throttle.
_LIMITER_CALL = re.compile(r"\b\w*(?:limit|budget|quota|throttle)\w*\s*\(", re.IGNORECASE)


def test_every_covered_route_is_found():
    assert {path for path, _ in _covered_routes()} == {c.path.replace("/n1/", "/{note_id}/") for c in CASES}


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
    (a tutor session opener, the shortest real model path) proves the harness
    does see a model call when one is made."""
    from typing import get_args

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

            r = client.post("/api/learn/start-session", json={"user_id": "u1", "topic": "Recursion"})
            assert r.status_code == 200, r.text
            assert r.json()["initial_message"] == "scripted reply"
            assert calls == ["chat_tutor"], "control: the seam is observed when a model runs"
    finally:
        clear_function_handlers()
        PENDING_SESSIONS.clear()
