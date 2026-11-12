"""Describe-a-set: which concepts a sentence asks for (services/flashcards/suggest.py).

Hermetic: the decision seam and the graph read are faked. What is pinned is
this module's own contract: a named concept is always in, the model adds the
rest, nothing here can raise past a domain error, and the route is the
caller's own.
"""
import asyncio
from types import SimpleNamespace

import pytest

from services import decisions
from services.flashcards import errors, suggest

NODES = [
    {"concept_name": "Pointers and Memory", "course_id": "c1"},
    {"concept_name": "Recursion", "course_id": "c1"},
    {"concept_name": "Vectors", "course_id": "c2"},
]


class _Graph:
    def __init__(self, rows):
        self.rows, self.filters = rows, None

    async def aselect(self, columns="*", filters=None, order=None, limit=None, **_):
        self.filters = filters
        course = (filters or {}).get("course_id", "").removeprefix("eq.")
        return [r for r in self.rows if not course or r["course_id"] == course]


def _answers(yes: dict[str, float]):
    """A decide() stand-in: keys in `yes` answer True at that confidence."""
    calls = []

    async def fake_decide(state, questions, **kwargs):
        calls.append({"state": state, "keys": [q.key for q in questions], **kwargs})
        answers = {
            q.key: decisions.Answer(key=q.key, value=q.key in yes, confidence=yes.get(q.key, 0.9))
            for q in questions
        }
        return decisions.DecisionResult(answers=answers, backend="jev", requested="jev", latency_ms=5)

    return fake_decide, calls


@pytest.fixture
def wired(monkeypatch):
    graph = _Graph(NODES)
    monkeypatch.setattr(suggest, "table", lambda name: graph)

    async def allow(*_a, **_k):
        return None

    monkeypatch.setattr(suggest, "acheck_rate_limit", allow)
    return SimpleNamespace(graph=graph, monkeypatch=monkeypatch)


def run(coro):
    return asyncio.run(coro)


def test_named_concepts_are_included_whatever_the_model_says(wired):
    fake, _ = _answers({})  # the model says no to everything
    wired.monkeypatch.setattr(suggest.decisions, "decide", fake)
    out = run(suggest.suggest_flashcard_set("u1", "recursion and the pointers and memory stuff"))
    assert [c["name"] for c in out["concepts"]] == ["Pointers and Memory", "Recursion"]
    assert {c["source"] for c in out["concepts"]} == {"named"}
    assert out["considered"] == 3 and out["backend"] == "jev"


def test_the_model_adds_concepts_the_description_does_not_name(wired):
    fake, calls = _answers({"c2": 0.82})
    wired.monkeypatch.setattr(suggest.decisions, "decide", fake)
    out = run(suggest.suggest_flashcard_set("u1", "everything for the linear algebra quiz"))
    assert out["concepts"] == [{"name": "Vectors", "course_id": "c2", "source": "model", "confidence": 0.82}]
    # Asked of Jev, with the student's words and the candidate names as state.
    assert calls[0]["backend"] == decisions.JEV and calls[0]["feature"] == suggest.FEATURE
    assert calls[0]["state"] == {
        "student_request": "everything for the linear algebra quiz",
        "concepts": ["Pointers and Memory", "Recursion", "Vectors"],
    }


def test_a_course_narrows_the_candidates(wired):
    fake, calls = _answers({"c0": 0.9})
    wired.monkeypatch.setattr(suggest.decisions, "decide", fake)
    out = run(suggest.suggest_flashcard_set("u1", "all of it", course_id="c2"))
    assert wired.graph.filters["course_id"] == "eq.c2"
    assert calls[0]["state"]["concepts"] == ["Vectors"]
    assert [c["name"] for c in out["concepts"]] == ["Vectors"]


def test_many_concepts_are_asked_in_chunks_with_stable_keys(wired, monkeypatch):
    rows = [{"concept_name": f"Concept {i}", "course_id": "c1"} for i in range(suggest.CHUNK + 5)]
    monkeypatch.setattr(suggest, "table", lambda name: _Graph(rows))
    fake, calls = _answers({f"c{suggest.CHUNK + 1}": 0.9})
    monkeypatch.setattr(suggest.decisions, "decide", fake)
    out = run(suggest.suggest_flashcard_set("u1", "the later topics"))
    assert len(calls) == 2
    assert calls[1]["keys"][0] == f"c{suggest.CHUNK}"  # keys continue across chunks
    assert [c["name"] for c in out["concepts"]] == [f"Concept {suggest.CHUNK + 1}"]


def test_a_failing_decision_degrades_to_named_concepts_only(wired):
    async def boom(*_a, **_k):
        raise RuntimeError("seam bug")

    wired.monkeypatch.setattr(suggest.decisions, "decide", boom)
    out = run(suggest.suggest_flashcard_set("u1", "just recursion"))
    assert [c["name"] for c in out["concepts"]] == ["Recursion"]
    assert out["backend"] == "none"


def test_no_concepts_yet_is_an_empty_suggestion_not_an_error(wired, monkeypatch):
    monkeypatch.setattr(suggest, "table", lambda name: _Graph([]))
    fake, calls = _answers({})
    monkeypatch.setattr(suggest.decisions, "decide", fake)
    out = run(suggest.suggest_flashcard_set("u1", "anything at all"))
    assert out["concepts"] == [] and out["considered"] == 0 and calls == []


@pytest.mark.parametrize("text", ["", "  ", "ab", "x" * (suggest.DESCRIPTION_MAX + 1)])
def test_description_bounds(wired, text):
    with pytest.raises(errors.FlashcardSetInvalid):
        run(suggest.suggest_flashcard_set("u1", text))


def test_rate_limited_requests_are_refused_before_any_model_call(wired):
    async def limited(*_a, **_k):
        return 12

    wired.monkeypatch.setattr(suggest, "acheck_rate_limit", limited)
    fake, calls = _answers({})
    wired.monkeypatch.setattr(suggest.decisions, "decide", fake)
    with pytest.raises(errors.FlashcardSetRateLimited) as exc:
        run(suggest.suggest_flashcard_set("u1", "recursion please"))
    assert exc.value.status_code == 429 and calls == []


def test_named_in_matches_whole_words_only():
    assert suggest.named_in("the Recursion unit", "recursion")
    assert suggest.named_in("pointers & memory, please", "Pointers and Memory") is False  # "&" is not "and"
    assert suggest.named_in("recursions", "Recursion") is False
    assert suggest.named_in("anything", "") is False


def test_suggested_name_is_the_description_tidied():
    assert suggest.suggested_name("  the pointer stuff for the midterm.  ") == "The pointer stuff for the midterm"
    long = "review " + "very " * 30 + "long"
    name = suggest.suggested_name(long)
    assert len(name) <= suggest.NAME_MAX and not name.endswith(" ")


def test_route_is_the_callers_own_and_maps_domain_errors(monkeypatch):
    from fastapi.testclient import TestClient

    import main
    from routes import flashcards as route

    seen = {}

    async def fake_suggest(user_id, description, course_id=None):
        seen.update(user_id=user_id, description=description, course_id=course_id)
        if description == "bad":
            raise errors.FlashcardSetInvalid("description must be 3 to 300 characters.")
        return {"name": "Recursion", "concepts": [], "considered": 0, "backend": "none"}

    monkeypatch.setattr(route, "suggest_flashcard_set", fake_suggest)
    monkeypatch.setattr(route, "require_self", lambda user_id, request: None)
    client = TestClient(main.app)
    ok = client.post("/api/flashcards/sets/suggest", json={"user_id": "u1", "description": "recursion", "course_id": "c1"})
    assert ok.status_code == 200 and ok.json()["name"] == "Recursion"
    assert seen == {"user_id": "u1", "description": "recursion", "course_id": "c1"}
    bad = client.post("/api/flashcards/sets/suggest", json={"user_id": "u1", "description": "bad"})
    assert bad.status_code == 422 and "description" in bad.json()["detail"]
