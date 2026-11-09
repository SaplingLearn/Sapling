"""The crisis-support path on every student-facing AI surface
(services/crisis_support.py; docs/safety/crisis-support.md).

For each surface, with the `crisis_support` flag ON a crisis message gets the
fixed card and the route does nothing else: zero model calls, zero database
writes, no session stashed, one content-free `safety.crisis_support_shown`
event. With the flag OFF (or on an ordinary message) the route carries on to
its own next step exactly as before — each case names that step and the test
replaces it with a sentinel 418, so "behaves as before" is observed, not
assumed.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic_ai import Agent

import db.connection as dbconn
from main import app
from services import ai_budget, crisis_support, events_service, posthog_client
from services import crisis_support_copy as crisis_copy
from services.feature_flags import REGISTRY
from services.tutor_sessions import PENDING_SESSIONS
from tests.split_patches import patch_tutor

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
    next_step: str  # the first thing the route does after the screen
    stream: bool = False
    async_next: bool = False
    neutral: dict[str, Any] = field(default_factory=dict)
    note_field: str | None = None  # notes routes: the note field the text goes in

    @property
    def limited(self) -> bool:
        """Whether a rate limiter sits on this route's path (the notes routes have none)."""
        return not self.path.startswith("/api/notes/")


def _chat(text):
    return {"session_id": "s1", "user_id": "u1", "message": text}


def _start(text):
    return {"user_id": "u1", "topic": text, "course_id": "c1"}


def _start_goal(text):
    return {"user_id": "u1", "topic": "Recursion", "course_id": "c1",
            "goal": {"text": text, "target_node_ids": ["n1"]}}


def _answer(text):
    return {"session_id": "s1", "user_id": "u1", "question_hash": "qh", "answer": text}


def _reason(text):
    return {"session_id": "s1", "user_id": "u1", "question_hash": "qh", "option": "B", "reason": text}


TURN = {"graph_update": {}, "mastery_changes": []}
START = {"session_id": None, "graph_state": None}

CASES: list[Case] = [
    # /api/learn/* — the tutor (delegates to the loop when the loop is on)
    # #118 (spec §13 A149): the bodies live in services/tutor/, and the turn
    # entry check is async there (#117)
    Case("tutor_chat", "/api/learn/chat", _chat, "services.tutor.turns._require_turn_session",
         async_next=True, neutral=TURN),
    Case("tutor_chat", "/api/learn/chat/stream", _chat, "services.tutor.streams._require_turn_session",
         stream=True, async_next=True, neutral=TURN),
    Case("tutor_start", "/api/learn/start-session", _start,
         "services.ai_budget.enforce_rate_limit_for", neutral=START),
    Case("tutor_start", "/api/learn/start-session/stream", _start,
         "services.ai_budget.enforce_rate_limit_for", stream=True, neutral={"session_id": None, **TURN}),
    Case("tutor_start", "/api/learn/start-session", _start_goal,
         "services.ai_budget.enforce_rate_limit_for", neutral=START),
    # /api/learn/loop/*
    Case("loop_chat", "/api/learn/loop/chat", _chat, "routes.learn_loop._consume_pending_off_loop",
         async_next=True, neutral=TURN),
    Case("loop_chat", "/api/learn/loop/chat/stream", _chat, "routes.learn_loop._consume_pending_off_loop",
         stream=True, async_next=True, neutral=TURN),
    Case("loop_start", "/api/learn/loop/start-session", _start, "routes.learn_loop._LoopOpener",
         neutral=START),
    Case("loop_start", "/api/learn/loop/start-session/stream", _start, "routes.learn_loop._LoopOpener",
         stream=True, neutral={"session_id": None, **TURN}),
    Case("loop_start", "/api/learn/loop/start-session", _start_goal, "routes.learn_loop._LoopOpener",
         neutral=START),
    Case("loop_goal", "/api/learn/loop/goal",
         lambda t: {"session_id": "s1", "user_id": "u1", "goal": {"text": t, "target_node_ids": ["n1"]}},
         "routes.learn_loop._probe_plan_read_limit"),
    Case("loop_check_answer", "/api/learn/loop/check/answer", _answer,
         "routes.learn_loop._consume_pending_off_loop", async_next=True, neutral=TURN),
    Case("loop_check_answer", "/api/learn/loop/check/answer/stream", _answer,
         "routes.learn_loop._consume_pending_off_loop", stream=True, async_next=True, neutral=TURN),
    Case("loop_check_answer", "/api/learn/loop/check/answer", _reason,
         "routes.learn_loop._consume_pending_off_loop", async_next=True, neutral=TURN),
    Case("loop_step_attempt", "/api/learn/loop/step/attempt",
         lambda t: {"session_id": "s1", "user_id": "u1", "question_hash": "qh", "attempt_text": t},
         "routes.learn_loop._session_scope", neutral={"genuine": False, "counted": False}),
    Case("loop_probe_answer", "/api/learn/loop/probe/answer", _answer,
         "services.ai_budget.enforce_rate_limit_for", neutral={"graded": False}),
    Case("loop_review_answer", "/api/learn/loop/review/answer",
         lambda t: {"user_id": "u1", "session_id": "r1", "kind": "check", "item_id": "i1", "answer": t},
         "routes.learn_loop._review_course",
         neutral={"correct": None, "unavailable": True, "refused": False}),
    Case("loop_posttest_answer", "/api/learn/loop/posttest/answer",
         lambda t: {"user_id": "u1", "node_id": "n1", "question_hash": "qh", "answer": t},
         "routes.learn_loop._posttest_node", neutral={"graded": False}),
    # learning-loop spec §13 A138: a guess at the segment prequestion (free and
    # multiple choice), JSON and stream; A139: a self-explanation reply
    Case("loop_prequestion_answer", "/api/learn/loop/prequestion/answer", _answer,
         "routes.learn_loop._consume_pending_off_loop", async_next=True, neutral=TURN),
    Case("loop_prequestion_answer", "/api/learn/loop/prequestion/answer/stream", _answer,
         "routes.learn_loop._consume_pending_off_loop", stream=True, async_next=True, neutral=TURN),
    Case("loop_prequestion_answer", "/api/learn/loop/prequestion/answer", _reason,
         "routes.learn_loop._consume_pending_off_loop", async_next=True, neutral=TURN),
    Case("loop_self_explain", "/api/learn/loop/self-explain",
         lambda t: {"session_id": "s1", "user_id": "u1", "prompt_id": "p1", "reply": t},
         "routes.learn_loop._session_scope", neutral={"recorded": False}),
    # /api/notes/* — the message, or the note an agent action hands a model
    Case("note_chat", "/api/notes/n1/chat", lambda t: {"user_id": "u1", "message": t},
         "routes.notes.offering_course_id", neutral={"degraded": False}),
    Case("note_chat", "/api/notes/n1/chat", lambda t: {"user_id": "u1", "message": CALM},
         "routes.notes.offering_course_id", neutral={"degraded": False}, note_field="body"),
    Case("note_send_to_tutor", "/api/notes/n1/send-to-tutor", lambda t: {"user_id": "u1"},
         "routes.notes.offering_course_id", note_field="title"),
    Case("note_summarize", "/api/notes/n1/summarize", lambda t: {"user_id": "u1"},
         "routes.notes._note_user_prompt", note_field="body"),
    Case("note_extract_concepts", "/api/notes/n1/extract-concepts", lambda t: {"user_id": "u1"},
         "routes.notes._note_user_prompt", note_field="body"),
]
IDS = [f"{c.path}:{c.note_field or c.body.__name__}" for c in CASES]


# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def no_rate_limit(request):
    """The A20 dependency reads llm_usage (route tests override it, as
    tests/test_learn_loop_routes.py does); a case that names the inline check
    as its next step patches over this. A test that asks for `real_limiters`
    gets the real dependency and inline check instead: this fixture steps
    aside rather than being patched over (re-patching an attribute this
    `patch` holds would leak the stub past the test)."""
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


def _note(case: Case, text: str) -> dict:
    note = {"id": "n1", "user_id": "u1", "offering_id": "o1", "title": "Week 3", "body": "Hash tables."}
    if case.note_field:
        note[case.note_field] = text
    return note


def _post(case: Case, text: str):
    """POST the case with `text` in its student field, its next step replaced
    by a sentinel 418. Returns (response, the sentinel mock)."""
    sentinel = HTTPException(status_code=SENTINEL, detail="reached the route's own next step")
    mock = (AsyncMock if case.async_next else MagicMock)(side_effect=sentinel)
    patches = [patch(case.next_step, mock)]
    if case.path.startswith("/api/notes/"):
        patches.append(patch("routes.notes.get_note", AsyncMock(return_value=_note(case, text))))
    for p in patches:
        p.start()
    try:
        return client.post(case.path, json=case.body(text)), mock
    finally:
        for p in reversed(patches):
            p.stop()


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


# ── Every surface ───────────────────────────────────────────────────────────


@pytest.mark.parametrize("case", CASES, ids=IDS)
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
    assert _db_writes() == writes  # no message, evidence, ledger, session or summary row
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


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_flag_off_the_route_behaves_as_before(case, flag, model_calls, sink):
    flag("off")
    r, next_step = _post(case, CRISIS)
    assert r.status_code == SENTINEL, r.text
    next_step.assert_called_once()
    assert _crisis_rows(sink) == []


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_flag_on_an_ordinary_message_is_untouched(case, flag, model_calls, sink):
    flag("on")
    r, next_step = _post(case, CALM)
    assert r.status_code == SENTINEL, r.text
    next_step.assert_called_once()
    assert _crisis_rows(sink) == []


def test_every_surface_is_covered():
    assert {c.surface for c in CASES} == set(crisis_support.SURFACES)


def _note_chat_with_tags(tags: list, flag_variant: str, flag):
    """POST a calm note-chat message over a note whose only crisis text (if any)
    is in its tags; the route's next step is a sentinel 418."""
    flag(flag_variant)
    note = {"id": "n1", "user_id": "u1", "offering_id": "o1", "title": "Week 3",
            "body": "Hash tables.", "tags": tags}
    sentinel = HTTPException(status_code=SENTINEL, detail="reached the route's own next step")
    nxt = MagicMock(side_effect=sentinel)
    with (
        patch("routes.notes.offering_course_id", nxt),
        patch("routes.notes.get_note", AsyncMock(return_value=note)),
    ):
        return client.post("/api/notes/n1/chat", json={"user_id": "u1", "message": CALM}), nxt


def test_a_crisis_phrase_only_in_the_notes_tags_gets_the_card_on_note_chat(flag, model_calls, sink):
    """The note-chat agent reads the note's tags (its read_active_note tool
    serves them, and A125's integrity guard checks them), so the crisis screen
    reads them too: a crisis phrase that is ONLY in a tag gets the card."""
    r, nxt = _note_chat_with_tags(["midterm", CRISIS], "on", flag)
    assert r.status_code == 200, r.text
    assert r.json()["crisis_support"] and r.json()["degraded"] is False
    nxt.assert_not_called()
    assert model_calls == []
    (row,) = _crisis_rows(sink)
    assert row["payload"]["surface"] == "note_chat"
    # control: the same note with calm tags carries on to the route's next step
    r, nxt = _note_chat_with_tags(["midterm", "hashing"], "on", flag)
    assert r.status_code == SENTINEL, r.text
    nxt.assert_called_once()


# ── Screening precedes every rate limit, budget and quota ───────────────────
#
# A student in crisis must never be answered with a 429 or a pause instead of
# the card. These run the REAL limiters (the loop's rate-limit dependency, the
# inline checks, the in-process probe/plan limiter) with nothing replaced but
# their verdict, and the real path up to them.


@pytest.fixture
def real_limiters(monkeypatch):
    """Every limiter on a covered path, live: the real rate-limit dependency and
    inline check (the autouse `no_rate_limit` steps aside for this fixture) and
    the probe/plan window, with only their verdict replaced. Set `limited`;
    `consulted` logs every read (empty = no limiter was even read)."""
    state: dict[str, Any] = {"limited": True, "consulted": []}

    def rate_limit_decision(user_id):
        state["consulted"].append("ai_budget.rate_limit")
        decision = ai_budget.BudgetDecision(
            level="hard", tier_ceiling="none", scope="rate_limit", reset_at=None,
        )
        return (decision if state["limited"] else None), None

    def probe_plan_window(key, *, limit, window_sec):
        state["consulted"].append("request_limits.check_rate_limit")
        return 30 if state["limited"] else None

    monkeypatch.setattr(ai_budget, "_rate_limit_decision", rate_limit_decision)
    monkeypatch.setattr("routes.learn_loop.check_rate_limit", probe_plan_window)
    return state


def _post_real(case: Case, text: str):
    """POST the case down its real path (no sentinel). Only what precedes the
    limiters and needs a database row is stood in: the student's note, and the
    legacy tutor's owned-and-open session check."""
    with (
        patch("routes.notes.get_note", AsyncMock(return_value=_note(case, text))),
        patch_tutor("_require_turn_session", return_value=None),
    ):
        return client.post(case.path, json=case.body(text))


def _card_of(case: Case, r) -> dict:
    assert r.status_code == 200, r.text
    if case.stream:
        (name, event), = _sse_events(r.text)
        assert name == "done"
        return event["data"]
    return r.json()


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_a_rate_limited_student_gets_the_card_and_ordinary_text_still_gets_the_429(
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

    if case.limited:
        r = _post_real(case, CALM)
        assert r.status_code == 429, r.text
        assert consulted, "the limiter answered the ordinary request"


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_a_budget_capped_student_gets_the_card(case, flag, model_calls, sink, monkeypatch):
    flag("on")
    budget = MagicMock(return_value=ai_budget.BudgetDecision(
        level="hard", tier_ceiling="none", scope="daily_usd", reset_at=None, pause_novice=True,
    ))
    monkeypatch.setattr(ai_budget, "check", budget)

    body = _card_of(case, _post_real(case, CRISIS))
    assert "crisis_support" in body
    assert "budget" not in body
    budget.assert_not_called()  # the cap was never consulted, so it could not pause the student


def test_the_budget_cap_is_live_for_ordinary_text(flag, model_calls, monkeypatch):
    """Control for the test above: the same cap does refuse an ordinary opener
    (the legacy kill-switch path reads it first), and the crisis text gets the card."""
    import config

    flag("on")
    monkeypatch.setattr(config, "LEARNING_LOOP_ENABLED", False)
    budget = MagicMock(return_value=ai_budget.BudgetDecision(
        level="hard", tier_ceiling="none", scope="daily_usd", reset_at=None, pause_novice=True,
    ))
    monkeypatch.setattr(ai_budget, "check", budget)
    assert client.post("/api/learn/start-session", json=_start("Recursion")).status_code == 429
    r = client.post("/api/learn/start-session", json=_start(CRISIS))
    assert r.status_code == 200 and "crisis_support" in r.json()
    assert budget.call_count == 1  # the ordinary opener's read only


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_a_crisis_turn_consumes_no_rate_limit_unit(
    case, flag, model_calls, sink, live_accounts, real_limiters, monkeypatch
):
    """Nothing a limiter counts moves: no tutor call is counted (in process or
    in the database), no llm_usage row is logged, no sliding-window slot is
    taken, and no limiter is even read."""
    from services import request_limits

    flag("on")
    real_limiters["limited"] = False
    consulted = real_limiters["consulted"]
    tutor_calls = MagicMock(wraps=ai_budget.count_tutor_call)
    usage_rows = MagicMock(wraps=events_service.log_llm_usage)
    monkeypatch.setattr(ai_budget, "count_tutor_call", tutor_calls)
    monkeypatch.setattr(events_service, "log_llm_usage", usage_rows)
    windows = {k: list(v) for k, v in request_limits._rate_state.items()}
    local_calls = dict(ai_budget._tutor_calls_local)
    writes = _db_writes()

    _card_of(case, _post_real(case, CRISIS))

    assert consulted == []
    tutor_calls.assert_not_called()
    usage_rows.assert_not_called()
    assert {k: list(v) for k, v in request_limits._rate_state.items()} == windows
    assert dict(ai_budget._tutor_calls_local) == local_calls
    assert _db_writes() == writes  # the tutor-call RPC is a write too


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


#: Every covered route whose limiter is a route dependency (`_RATE_LIMITED`).
SCREENED_BY_DEPENDENCY = {
    "/api/learn/loop/chat", "/api/learn/loop/chat/stream",
    "/api/learn/loop/check/answer", "/api/learn/loop/check/answer/stream",
    "/api/learn/loop/posttest/answer", "/api/learn/loop/step/attempt",
    "/api/learn/loop/start-session", "/api/learn/loop/start-session/stream",
    # spec §13 A138 / A139
    "/api/learn/loop/prequestion/answer", "/api/learn/loop/prequestion/answer/stream",
    "/api/learn/loop/self-explain",
}
#: Every covered route whose limiters are all inline: (path, the screen's call,
#: the limiter calls it must precede in the handler's source).
# The /api/learn rows read the tutor body (services/tutor/, #118), whose
# limiters hop off the event loop: `asyncio.to_thread(<limiter>, ...)` (A149).
SCREENED_INLINE = [
    ("/api/learn/chat", "crisis_support.screen_async", ("_require_turn_session(", "enforce_rate_limit_for,")),
    ("/api/learn/chat/stream", "crisis_support.screen_async", ("_require_turn_session(", "enforce_rate_limit_for,")),
    ("/api/learn/start-session", "crisis_support.screen_async", ("enforce_rate_limit_for,", "_kill_switch_budget,")),
    ("/api/learn/start-session/stream", "crisis_support.screen_async",
     ("enforce_rate_limit_for,", "_kill_switch_budget,")),
    ("/api/learn/loop/goal", "crisis_support.screen(", ("_probe_plan_read_limit(",)),
    ("/api/learn/loop/probe/answer", "crisis_support.screen_async", ("enforce_rate_limit_for(",)),
    ("/api/learn/loop/review/answer", "crisis_support.screen_async", ("enforce_rate_limit_for(",)),
]


def _mounted_routes():
    """(full path, route) for the covered routers, read off each module's own
    router (fastapi 0.138 keeps an included router as ONE app.routes entry; the
    house helpers in test_cutover_removals / test_learn_loop_routes do the same)."""
    from routes import learn, learn_loop, notes

    for prefix, router in (("/api/learn/loop", learn_loop.router), ("/api/learn", learn.router),
                           ("/api/notes", notes.router)):
        for route in router.routes:
            if "POST" in getattr(route, "methods", set()):
                yield prefix + route.path, route


def _api_route(path: str):
    return next(route for full, route in _mounted_routes() if full == path)


def test_a_screen_dependency_precedes_every_rate_limit_dependency():
    """Structural pin: on every route that carries both, the crisis screen comes
    before the rate limit, and after only the kill switch."""
    from routes import learn_loop

    screened_paths = set()
    for path, route in _mounted_routes():
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
def test_an_inline_screen_precedes_every_inline_limiter(path, screen_call, limiters):
    """Structural pin for the routes whose limiters are inline: the screen is
    called before each of them in the handler, and no limiter is a dependency."""
    import inspect

    route = _api_route(path)
    calls = [d.call for d in route.dependant.dependencies]
    assert ai_budget.enforce_rate_limit not in calls, path
    endpoint = route.endpoint
    if not path.startswith("/api/learn/loop/"):
        import services.tutor as tutor  # #118: the thin wrapper's body (spec §13 A149)

        endpoint = getattr(tutor, route.endpoint.__name__)
    source = inspect.getsource(endpoint)
    for limiter in limiters:
        assert limiter in source, (path, limiter)
        assert source.index(screen_call) < source.index(limiter), (path, limiter)


def test_the_streamed_card_is_the_tutor_streams_own_terminal_shape(flag, model_calls):
    """The frontend's consumeChatStream resolves a turn from `done.data` and
    needs nothing before it; the crisis stream is exactly that one event."""
    flag("on")
    r = client.post("/api/learn/loop/chat/stream", json=_chat(CRISIS))
    assert r.headers["cache-control"] == "no-store, no-transform"
    assert r.headers["x-request-id"]
    (name, event), = _sse_events(r.text)
    assert (name, event["type"], event["step"]) == ("done", "done", "reply")
    assert set(event["data"]) == {"reply", "crisis_support", "graph_update", "mastery_changes"}


# ── The screen itself ───────────────────────────────────────────────────────


def test_an_ordinary_message_never_reads_the_flag(monkeypatch):
    read = MagicMock(return_value=True)
    monkeypatch.setattr(crisis_support, "flag_on", read)
    assert crisis_support.screen("u1", "loop_chat", CALM, None, "") is None
    read.assert_not_called()


def test_flag_off_means_no_card_and_no_event(monkeypatch, sink):
    monkeypatch.setattr(crisis_support, "flag_on", lambda key, uid: False)
    assert crisis_support.screen("u1", "loop_chat", CRISIS) is None
    assert _crisis_rows(sink) == []


def test_the_flag_is_resolved_for_the_student(monkeypatch, sink):
    seen = []
    monkeypatch.setattr(crisis_support, "flag_on", lambda key, uid: seen.append((key, uid)) or True)
    support = crisis_support.screen("u7", "note_chat", CRISIS)
    assert seen == [("crisis_support", "u7")]
    assert support.surface == "note_chat" and support.category == "suicidal_ideation"
    assert "category" not in support.payload  # the client is never told what matched


def test_an_unknown_surface_is_a_programming_error(monkeypatch):
    monkeypatch.setattr(crisis_support, "flag_on", lambda key, uid: True)
    with pytest.raises(ValueError):
        crisis_support.screen("u1", "room_chat", CRISIS)


def test_the_most_severe_field_is_reported(monkeypatch, sink):
    monkeypatch.setattr(crisis_support, "flag_on", lambda key, uid: True)
    crisis_support.screen("u1", "loop_start", "I want to hurt myself", "I took a bunch of pills")
    assert _crisis_rows(sink)[0]["payload"]["category"] == "acute_danger"


def test_async_screen_scans_long_text_off_the_event_loop(monkeypatch, sink):
    import asyncio

    monkeypatch.setattr(crisis_support, "flag_on", lambda key, uid: True)
    threads: list[str] = []
    real = crisis_support.detect_any

    def spy(texts):
        import threading

        threads.append(threading.current_thread().name)
        return real(texts)

    monkeypatch.setattr(crisis_support, "detect_any", spy)
    long_note = "Lecture notes. " * 1000 + CRISIS

    async def main():
        loop_thread = __import__("threading").current_thread().name
        assert await crisis_support.screen_async("u1", "note_summarize", long_note) is not None
        assert await crisis_support.screen_async("u1", "loop_chat", CRISIS) is not None
        return loop_thread

    loop_thread = asyncio.run(main())
    assert threads[0] != loop_thread  # the long note: in a worker thread
    assert threads[1] == loop_thread  # a chat message: inline, it is microseconds


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
        crisis_support.screen("user_1", "loop_chat", CRISIS)
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
    (the legacy kill-switch opener, the shortest real model path) proves the
    harness does see a model call when one is made."""
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
            patch_tutor("_get_course_id_for_topic", return_value=""),
            patch_tutor("get_graph", return_value={"nodes": [], "edges": []}),
            patch("routes.notes.get_note", AsyncMock(return_value=_note(CASES[-1], CRISIS))),
        ):
            for case in CASES:
                r = client.post(case.path, json=case.body(CRISIS))
                assert r.status_code == 200 and "crisis_support" in r.text, case.path
            assert calls == [], "the scripted model must never run on a crisis message"

            monkeypatch.setattr(config, "LEARNING_LOOP_ENABLED", False)
            r = client.post("/api/learn/start-session", json={"user_id": "u1", "topic": "Recursion"})
            assert r.status_code == 200
            assert r.json()["initial_message"] == "scripted reply"
            assert calls == ["chat_tutor"], "control: the seam is observed when a model runs"
    finally:
        clear_function_handlers()
        PENDING_SESSIONS.clear()
