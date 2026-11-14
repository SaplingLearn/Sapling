"""routes/study_guide.py: the HTTP layer over services/study_guides.

Every package function is replaced on the package (where the route looks it
up), so these tests pin only what the route owns: the paths, what each
handler passes on, the caller check, the status of each domain error, the 201
on create, and the generate stream's framing and headers.
"""
from __future__ import annotations

import json

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from main import app
from models.study_guide import GuideRequest
from routes import study_guide as route
from services import study_guides
from services.agent_events import SSE_CACHE_CONTROL, SaplingEvent
from services.study_guides.errors import (
    GuideBusy,
    GuideGenerationFailed,
    GuideInvalid,
    GuideNotFound,
    GuideRateLimited,
)

# A sync PostgREST call on the event loop raises instead of only logging.
pytestmark = pytest.mark.usefixtures("no_sync_db_on_loop")

client = TestClient(app)

ME = "user_route_me"
BASE = f"/api/study-guide/{ME}"
GUIDE = f"{BASE}/guides/g1"
REQUEST = {"course_id": "course-cs", "scope_kind": "exam", "scope_id": "exam-1",
           "material_ids": ["doc-1"]}
EVENTS = [
    SaplingEvent(type="status", step="read", message="Reading your 2 materials",
                 data={"step": 1, "total": 4}),
    SaplingEvent(type="progress", step="outline", message="", data={"content": {"title": "Loops"}}),
    SaplingEvent(type="done", step="done", message="", data={"guide": {"id": "g1"}}),
]

#: (name on the package, method, path, JSON body or None): one row per endpoint.
ENDPOINTS = [
    ("alist_cards", "GET", f"{BASE}/guides", None),
    ("aget_options", "GET", f"{BASE}/options?course_id=course-cs", None),
    ("aplan", "POST", f"{BASE}/plan", REQUEST),
    ("acreate_guide", "POST", f"{BASE}/guides", REQUEST),
    ("aget_detail", "GET", GUIDE, None),
    ("apatch_guide", "PATCH", GUIDE, {"saved": True}),
    ("aprepare_generation", "POST", f"{GUIDE}/generate", {"mode": "resume"}),
    ("aregenerate_block", "POST", f"{GUIDE}/blocks/s1-i2/regenerate", None),
    ("aanswer_check", "POST", f"{GUIDE}/blocks/s1-i2/answer", {"option_id": "b"}),
]
ERRORS = [
    (GuideInvalid("Choose at least one of this class's materials."), 422),
    (GuideNotFound("Study guide not found."), 404),
    (GuideBusy("This study guide is being changed. Try again."), 409),
    (GuideRateLimited("Too many guides. Try again in a few minutes."), 429),
    (GuideGenerationFailed("The guide could not be written."), 502),
]


def _send(method: str, path: str, body):
    return client.request(method, path, json=body) if body is not None else client.request(method, path)


def _replace(monkeypatch, name: str, result=None, error: Exception | None = None) -> list:
    """Replace one package function with a stand-in that records its call."""
    calls: list = []

    async def stand_in(*args, **kwargs):
        calls.append((args, kwargs))
        if error is not None:
            raise error
        return result

    monkeypatch.setattr(study_guides, name, stand_in)
    return calls


def _stream(monkeypatch, events=EVENTS) -> list:
    """Replace `stream_generation` with one that yields `events`, and the
    charge settling after the response with one that records its call."""
    streamed: list = []

    async def stream_generation(generation):
        streamed.append(generation)
        for event in events:
            yield event

    async def asettle_charge(generation):
        streamed.append(("settled", generation))

    monkeypatch.setattr(study_guides, "stream_generation", stream_generation)
    monkeypatch.setattr(study_guides, "asettle_charge", asettle_charge)
    return streamed


def _sse(text: str) -> list[dict]:
    """The frames of an SSE body as `{event, data}`; `data` is parsed JSON."""
    frames = []
    for block in text.replace("\r\n", "\n").split("\n\n"):
        fields = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line)
        if "event" in fields:
            frames.append({"event": fields["event"], "data": json.loads(fields["data"])})
    return frames


# ── Each endpoint calls its one function ─────────────────────────────────────


def test_list_guides(monkeypatch):
    calls = _replace(monkeypatch, "alist_cards", [{"id": "g1"}, {"id": "g2"}])
    r = client.get(f"{BASE}/guides")
    assert (r.status_code, r.json()) == (200, {"guides": [{"id": "g1"}, {"id": "g2"}]})
    assert calls == [((ME,), {})]


def test_options_pass_the_course_and_term(monkeypatch):
    calls = _replace(monkeypatch, "aget_options", {"scopes": [], "materials": []})
    r = client.get(f"{BASE}/options", params={"course_id": "course-cs", "semester": "Fall 2026"})
    assert (r.status_code, r.json()) == (200, {"scopes": [], "materials": []})
    assert calls == [((ME, "course-cs", "Fall 2026"), {})]

    client.get(f"{BASE}/options", params={"course_id": "course-cs"})
    assert calls[1] == ((ME, "course-cs", None), {})


def test_options_need_a_course():
    assert client.get(f"{BASE}/options").status_code == 422


def test_plan_passes_the_request(monkeypatch):
    calls = _replace(monkeypatch, "aplan", {"sections": [], "minutes": 0})
    r = client.post(f"{BASE}/plan", json=REQUEST)
    assert (r.status_code, r.json()) == (200, {"sections": [], "minutes": 0})
    assert calls == [((ME, GuideRequest(**REQUEST)), {})]


def test_create_answers_201_with_the_new_id(monkeypatch):
    calls = _replace(monkeypatch, "acreate_guide", "guide-new")
    r = client.post(f"{BASE}/guides", json=REQUEST)
    assert (r.status_code, r.json()) == (201, {"id": "guide-new"})
    assert calls == [((ME, GuideRequest(**REQUEST)), {})]


def test_create_refuses_a_malformed_request_before_the_package(monkeypatch):
    calls = _replace(monkeypatch, "acreate_guide", "guide-new")
    assert client.post(f"{BASE}/guides", json={**REQUEST, "depth": "endless"}).status_code == 422
    assert client.post(f"{BASE}/guides", json={"scope_kind": "course"}).status_code == 422
    assert calls == []


def test_get_guide(monkeypatch):
    calls = _replace(monkeypatch, "aget_detail", {"id": "g1", "title": "Loops"})
    r = client.get(GUIDE)
    assert (r.status_code, r.json()) == (200, {"id": "g1", "title": "Loops"})
    assert calls == [((ME, "g1"), {})]


def test_patch_guide_passes_only_what_was_sent(monkeypatch):
    state = {"read_sections": ["s1"], "saved_at": None, "feedback": None}
    calls = _replace(monkeypatch, "apatch_guide", state)
    r = client.patch(GUIDE, json={"read_sections": ["s1"]})
    assert (r.status_code, r.json()) == (200, state)
    ((user_id, guide_id, patch), _), = calls
    assert (user_id, guide_id) == (ME, "g1")
    assert patch.model_dump() == {"read_sections": ["s1"], "saved": None, "feedback": None}


def test_regenerate_block(monkeypatch):
    block = {"type": "formula", "id": "s1-i2", "name": "Passes"}
    calls = _replace(monkeypatch, "aregenerate_block", block)
    r = client.post(f"{GUIDE}/blocks/s1-i2/regenerate")
    assert (r.status_code, r.json()) == (200, {"block": block})
    assert calls == [((ME, "g1", "s1-i2"), {})]


def test_answer_passes_the_option_and_defers_work_until_after_the_response(monkeypatch):
    result = {"correct": True, "correct_id": "b", "explanation": "Four.", "counted": True,
              "mastery": None}
    ran: list = []

    async def aanswer_check(user_id, guide_id, block_id, option_id, *, defer):
        defer(lambda: ran.append("deferred"))
        ran.append((user_id, guide_id, block_id, option_id))
        return result

    monkeypatch.setattr(study_guides, "aanswer_check", aanswer_check)
    r = client.post(f"{GUIDE}/blocks/s1-i2/answer", json={"option_id": "b"})
    assert (r.status_code, r.json()) == (200, result)
    # The deferred task ran, and only after the handler had returned.
    assert ran == [(ME, "g1", "s1-i2", "b"), "deferred"]


def test_answer_refuses_an_option_letter_outside_a_to_d(monkeypatch):
    calls = _replace(monkeypatch, "aanswer_check", {})
    assert client.post(f"{GUIDE}/blocks/s1-i2/answer", json={"option_id": "e"}).status_code == 422
    assert calls == []


# ── The caller check and the domain errors ───────────────────────────────────


@pytest.mark.parametrize("name,method,path,body", ENDPOINTS)
def test_another_users_session_is_refused_before_the_package(monkeypatch, name, method, path, body):
    def refuse(user_id, request):
        assert user_id == ME
        raise HTTPException(status_code=403, detail="Forbidden")

    monkeypatch.setattr(route, "require_self", refuse)
    calls = _replace(monkeypatch, name, {})
    assert _send(method, path, body).status_code == 403
    assert calls == []


@pytest.mark.parametrize("error,status", ERRORS, ids=[type(error).__name__ for error, _ in ERRORS])
@pytest.mark.parametrize("name,method,path,body", ENDPOINTS, ids=[e[0] for e in ENDPOINTS])
def test_a_domain_error_answers_with_its_status_and_detail(
    monkeypatch, name, method, path, body, error, status,
):
    _replace(monkeypatch, name, error=error)
    r = _send(method, path, body)
    assert r.status_code == status
    assert r.json()["detail"] == error.detail


# ── Generate ─────────────────────────────────────────────────────────────────


def test_generate_streams_the_runs_events_as_sse(monkeypatch):
    prepared = _replace(monkeypatch, "aprepare_generation", "the-generation")
    streamed = _stream(monkeypatch)
    r = client.post(f"{GUIDE}/generate", json={"mode": "update"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    assert prepared == [((ME, "g1", "update"), {})]
    # The stream is given exactly what prepare returned, and the charge is
    # settled once the response is over (a stream that never started gives
    # it back there).
    assert streamed == ["the-generation", ("settled", "the-generation")]
    assert _sse(r.text) == [
        {"event": event.type, "data": event.model_dump(mode="json")} for event in EVENTS
    ]


def test_generate_stream_is_not_cached_or_compressed_and_names_its_request(monkeypatch):
    _replace(monkeypatch, "aprepare_generation", "the-generation")
    _stream(monkeypatch)
    r = client.post(f"{GUIDE}/generate", json={"mode": "resume"}, headers={"X-Request-ID": "guide-trace-1234"})
    assert r.headers["cache-control"] == SSE_CACHE_CONTROL
    assert r.headers["x-request-id"] == "guide-trace-1234"


def test_generate_defaults_to_resume(monkeypatch):
    prepared = _replace(monkeypatch, "aprepare_generation", "the-generation")
    _stream(monkeypatch)
    assert client.post(f"{GUIDE}/generate", json={}).status_code == 200
    assert prepared == [((ME, "g1", "resume"), {})]


def test_generate_refuses_an_unknown_mode(monkeypatch):
    prepared = _replace(monkeypatch, "aprepare_generation", "the-generation")
    assert client.post(f"{GUIDE}/generate", json={"mode": "rewrite"}).status_code == 422
    assert prepared == []


def test_generate_answers_409_and_opens_no_stream_while_another_run_holds_the_claim(monkeypatch):
    _replace(monkeypatch, "aprepare_generation", error=GuideBusy("Another tab is writing this guide."))
    streamed = _stream(monkeypatch)
    r = client.post(f"{GUIDE}/generate", json={"mode": "resume"})
    assert r.status_code == 409
    assert r.headers["content-type"].startswith("application/json")
    assert r.json()["detail"] == "Another tab is writing this guide."
    assert streamed == []


# ── What the old surface left behind ─────────────────────────────────────────


@pytest.mark.parametrize("method,path", [
    ("GET", f"{BASE}/cached"),
    ("GET", f"{BASE}/courses"),
    ("GET", f"{BASE}/exams?course_id=course-cs"),
    ("GET", f"{BASE}/guide?course_id=course-cs&exam_id=exam-1"),
    ("POST", "/api/study-guide/regenerate"),
])
def test_the_old_endpoints_are_gone(method, path):
    assert client.request(method, path).status_code in (404, 405)
