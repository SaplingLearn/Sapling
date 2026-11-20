"""#866 K38: a streamed start beside a note's crisis card keeps the card when
it ends in an `error` event.

docs/safety/crisis-support.md: "The student never gets a refusal without the
card." A tutor start on Send to tutor's note title starts through
`crisis_support.alongside`, which put the card on the stream's `done` event
and, through ErrorCardMiddleware, on an error answered BEFORE the stream; an
error the stream itself ends with (the per-user LLM budget, a failure after
the greeting started, a failed fallback) went out with no card. The loop's
start (`routes/learn_loop.py::_beside_note_card`) streams through the same
wrapper.
"""

from __future__ import annotations

import asyncio
import json

from services import crisis_support
from services import crisis_support_copy as crisis_copy
from tests import test_crisis_support_routes as _routes
from tests.test_crisis_support_routes import _note_start, _sse_events, client

# the crisis route tests' fixtures: the flag, the start routes stood in, no A20 read
flag, note_start, no_rate_limit = _routes.flag, _routes.note_start, _routes.no_rate_limit

CARD = crisis_support.client_payload(crisis_copy.DEFAULT_CAMPUS_COUNSELING)
ERROR_DATA = {"request_id": "r1", "retryable": False, "code": "LLM_BUDGET_EXCEEDED"}


async def _greeting_then_error(body, request, **_route_kwargs):
    from sse_starlette.sse import EventSourceResponse

    from services.agent_events import SaplingEvent, sapling_event_to_sse

    async def events():
        yield sapling_event_to_sse(SaplingEvent(type="token", step="reply", message="", data={"delta": "Let's"}))
        yield sapling_event_to_sse(
            SaplingEvent(type="error", step="reply", message="The tutor is unavailable.", data=dict(ERROR_DATA))
        )

    return EventSourceResponse(events())


def test_a_note_titled_start_that_ends_in_an_error_carries_the_card(flag, sink, note_start):
    flag("on")
    note_start["stream"].side_effect = _greeting_then_error
    r = client.post("/api/learn/start-session/stream", json=_note_start())
    assert r.status_code == 200, r.text
    events = _sse_events(r.text)
    assert [name for name, _ in events] == ["token", "error"]
    error = events[-1][1]
    assert error["message"] == "The tutor is unavailable."  # the error is the stream's own
    assert {k: error["data"][k] for k in ERROR_DATA} == ERROR_DATA
    assert error["data"]["crisis_support"] == CARD
    assert "crisis_support" not in events[0][1]["data"]


def test_with_the_flag_off_the_error_is_untouched(flag, sink, note_start):
    flag("off")
    note_start["stream"].side_effect = _greeting_then_error
    r = client.post("/api/learn/start-session/stream", json=_note_start())
    events = _sse_events(r.text)
    assert events[-1][1]["data"] == ERROR_DATA


def test_the_wrapper_puts_the_card_on_done_and_on_error_only():
    """`_stream_with_card` directly: every other event passes as it came."""

    async def events():
        yield {"event": "token", "data": json.dumps({"type": "token", "data": {"delta": "a"}})}
        yield {"event": "done", "data": json.dumps({"type": "done", "data": {"reply": "a"}})}
        yield {"event": "error", "data": json.dumps({"type": "error", "data": None})}

    async def collect():
        return [item async for item in crisis_support._stream_with_card(events(), CARD)]

    token, done, error = asyncio.run(collect())
    assert json.loads(token["data"])["data"] == {"delta": "a"}
    assert json.loads(done["data"])["data"] == {
        "reply": "a", "crisis_support": CARD, crisis_support.ALONGSIDE: True,
    }
    assert json.loads(error["data"])["data"] == {"crisis_support": CARD}
