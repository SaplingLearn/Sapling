import json

from services.agent_events import SaplingEvent, sapling_event_to_sse


def test_token_event_serializes_to_sse():
    ev = SaplingEvent(type="token", step="reply", message="", data={"delta": "Hi"})
    wire = sapling_event_to_sse(ev)
    assert wire["event"] == "token"
    assert json.loads(wire["data"])["data"]["delta"] == "Hi"


def test_graph_update_and_done_types_accepted():
    for t in ("graph_update", "done"):
        assert SaplingEvent(type=t, step="reply", message="").type == t
