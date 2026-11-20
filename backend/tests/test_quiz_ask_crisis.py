"""#866 K12: the quiz "Ask about this" panel's first message QUOTES the quiz
question (docs/safety/crisis-support.md).

The panel opens a tutor session and sends one composed message: the question's
stem, the option the student chose (or what they wrote), the key and the
explanation. A nursing, psychology or literature question can quote a patient
or a character ("I have a plan to end my life"); screened as typed text, that
message got the crisis card INSTEAD of the explanation, every time, and Retry
re-sent the same message.

The message names the question it quotes (`quiz_attempt_id`,
`quiz_question_index`, as the session start does). Text of that question on the
student's own attempt found in the message is stored
material: the turn runs and the card rides BESIDE the reply, its event once a
day. Everything else in the message is typed and blocks as before — the answer
the student WROTE ("I wrote: …") included, and a stored text found only inside
typed words — and a quote that is not the student's, or not in the message,
changes nothing.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from main import app
from services import crisis_support, events_service
from services import crisis_support_copy as crisis_copy

client = TestClient(app)

STEM = 'A patient tells the nurse: "I have a plan to end my life." What is the nurse\'s first action?'
OPTIONS = ["Ask about the plan directly", "Change the subject", "Leave to find help", "Document it later"]
EXPLANATION = "Asking directly about a plan assesses the immediate risk."
QUESTION = {
    "id": 1, "type": "multiple_choice", "question": STEM, "explanation": EXPLANATION,
    "options": [{"label": "ABCD"[i], "text": t, "correct": i == 0} for i, t in enumerate(OPTIONS)],
}
#: The panel's first message, as frontend AskPanel.tsx `composeAskMessage` writes it.
SEED = "\n".join([
    "I got this quiz question wrong and want to understand why.",
    "",
    f"Question: {STEM}",
    f"I chose B: {OPTIONS[1]}",
    f"The correct answer is A: {OPTIONS[0]}",
    f"Explanation given: {EXPLANATION}",
    "",
    "Help me understand why.",
])
TYPED_CRISIS = "honestly I want to kill myself tonight"
REPLY = {"reply": "Asking about the plan first tells the nurse how close the danger is.",
         "graph_update": {}, "mastery_changes": []}
CARD = crisis_support.client_payload(crisis_copy.DEFAULT_CAMPUS_COUNSELING)


def _turn(message: str = SEED, *, quoted: bool = True) -> dict:
    body = {"session_id": "s1", "user_id": "u1", "message": message}
    if quoted:
        body |= {"quiz_attempt_id": "att1", "quiz_question_index": 0}
    return body


@pytest.fixture
def flag(monkeypatch):
    def _set(variant: str) -> None:
        monkeypatch.setenv("SAPLING_FLAG_CRISIS_SUPPORT", variant)

    return _set


@pytest.fixture
def stored(monkeypatch):
    """The student's attempt, as services/quiz_ask.py reads it (decryption
    stood in). Yields the table factory's call log and a dict to change the
    attempt's owner or question with."""
    state = {"owner": "u1", "question": QUESTION}
    reads: list[str] = []

    def table(name):
        reads.append(name)
        handle = MagicMock()
        handle.select.return_value = (
            [{"user_id": state["owner"], "questions_json": [state["question"]]}] if name == "quiz_attempts" else []
        )
        return handle

    with (
        patch("services.quiz_ask.table", side_effect=table),
        patch("services.quiz_ask.decrypt_json_column", side_effect=lambda value, **_: value),
    ):
        yield {"reads": reads, "state": state}


@pytest.fixture
def tutor():
    """The tutor's own turn stood in: the JSON reply, and a stream of one
    token and its `done`."""
    from sse_starlette.sse import EventSourceResponse

    from services.agent_events import SaplingEvent, sapling_event_to_sse

    async def stream(body, request, **_route_kwargs):
        async def events():
            yield sapling_event_to_sse(SaplingEvent(type="token", step="reply", message="Asking",
                                                    data={"delta": "Asking"}))
            yield sapling_event_to_sse(SaplingEvent(type="done", step="reply", message="Complete.", data=REPLY))

        return EventSourceResponse(events())

    mocks = {"chat": AsyncMock(return_value=dict(REPLY)), "stream": AsyncMock(side_effect=stream)}
    with (
        patch("services.tutor.chat", mocks["chat"]),
        patch("services.tutor.chat_stream", mocks["stream"]),
    ):
        yield mocks


def _events(text: str) -> list[tuple[str, dict]]:
    out, name = [], None
    for line in text.splitlines():
        if line.startswith("event:"):
            name = line.split(":", 1)[1].strip()
        elif line.startswith("data:"):
            out.append((name, json.loads(line.split(":", 1)[1])))
    return out


def _shown(sink) -> list[dict]:
    events_service.flush_now()
    return [r["payload"] for r in sink if r["event_type"] == crisis_support.EVENT]


def test_the_seed_gets_the_explanation_with_the_card_beside_it(flag, sink, stored, tutor):
    flag("on")
    r = client.post("/api/learn/chat", json=_turn())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["reply"] == REPLY["reply"]  # the tutor explained the question
    assert body["crisis_support"] == CARD and body["crisis_support_alongside"] is True
    tutor["chat"].assert_awaited_once()
    assert [p["surface"] for p in _shown(sink)] == ["tutor_chat"]


def test_the_streamed_seed_streams_the_explanation_with_the_card_in_done(flag, sink, stored, tutor):
    flag("on")
    r = client.post("/api/learn/chat/stream", json=_turn())
    assert r.status_code == 200, r.text
    events = _events(r.text)
    assert [name for name, _ in events] == ["token", "done"]
    done = events[-1][1]["data"]
    assert done["reply"] == REPLY["reply"]
    assert done["crisis_support"] == CARD and done["crisis_support_alongside"] is True
    assert "crisis_support" not in events[0][1]["data"]


def test_a_retry_of_the_seed_shows_the_card_again_and_records_it_once(flag, sink, stored, tutor):
    flag("on")
    for _ in range(2):
        r = client.post("/api/learn/chat", json=_turn())
        assert r.status_code == 200 and r.json()["crisis_support_alongside"] is True
    assert len(_shown(sink)) == 1


@pytest.mark.parametrize("message, quoted, change", [
    pytest.param(TYPED_CRISIS, False, {}, id="a typed follow-up"),
    pytest.param(f"{SEED}\n{TYPED_CRISIS}", True, {}, id="typed words beside the quote"),
    pytest.param(SEED, True, {"owner": "u2"}, id="another student's attempt"),
    pytest.param(SEED, True, {"question": {**QUESTION, "question": "Another stem?"}},
                 id="a question the message does not quote"),
])
@pytest.mark.parametrize("path", ["/api/learn/chat", "/api/learn/chat/stream"])
def test_what_the_question_does_not_hold_is_typed_and_blocks(message, quoted, change, path, flag, sink,
                                                             stored, tutor):
    flag("on")
    stored["state"].update(change)
    r = client.post(path, json=_turn(message, quoted=quoted))
    assert r.status_code == 200, r.text
    body = _events(r.text)[-1][1]["data"] if path.endswith("stream") else r.json()
    assert body["crisis_support"] == CARD and "crisis_support_alongside" not in body
    tutor["chat"].assert_not_awaited()
    tutor["stream"].assert_not_awaited()
    assert len(_shown(sink)) == 1


def _written_seed(question: dict, wrote: str) -> str:
    return "\n".join(["I got this quiz question wrong and want to understand why.", "",
                      f"Question: {question['question']}", f"I wrote: {wrote}",
                      f"The correct answer is: {question['correct_answer']}",
                      f"Explanation given: {question['explanation']}", "", "Help me understand why."])


@pytest.mark.parametrize("path", ["/api/learn/chat", "/api/learn/chat/stream"])
def test_a_written_answer_is_the_students_own_typed_text_and_blocks(path, flag, sink, stored, tutor):
    """The panel quotes what the student wrote ("I wrote: …"). That is text
    they typed, not the question's material: a crisis phrase in it gets the
    card INSTEAD of the turn, as it would anywhere else they type, and nothing
    of quiz_responses is read to unblock it."""
    flag("on")
    written = {**QUESTION, "type": "short_answer", "options": [], "correct_answer": "Ask about the plan"}
    stored["state"]["question"] = written
    r = client.post(path, json=_turn(_written_seed(written, TYPED_CRISIS)))
    assert r.status_code == 200, r.text
    body = _events(r.text)[-1][1]["data"] if path.endswith("stream") else r.json()
    assert body["crisis_support"] == CARD and "crisis_support_alongside" not in body
    tutor["chat"].assert_not_awaited()
    tutor["stream"].assert_not_awaited()
    assert "quiz_responses" not in stored["reads"]


def test_with_the_flag_off_the_seed_runs_as_before_and_nothing_is_read(flag, sink, stored, tutor):
    flag("off")
    r = client.post("/api/learn/chat", json=_turn())
    assert r.status_code == 200, r.text
    assert "crisis_support" not in r.json()
    tutor["chat"].assert_awaited_once()
    assert stored["reads"] == [] and _shown(sink) == []


def test_an_ordinary_seed_reads_nothing(flag, sink, stored, tutor):
    flag("on")
    calm = SEED.replace(STEM, "What does a hash table do on a collision?")
    r = client.post("/api/learn/chat", json=_turn(calm))
    assert r.status_code == 200 and "crisis_support" not in r.json()
    assert stored["reads"] == []


def test_a_quote_names_a_whole_question():
    r = client.post("/api/learn/chat", json={**_turn(quoted=False), "quiz_attempt_id": "att1"})
    assert r.status_code == 422
