"""W8.3: Study Hub learner-next (GET /api/study/{user_id}/next).

Thin route over ``services.study.get_next`` → ``services.learner_next``.
Gated like the quiz plan (``learning_loop`` + ``quiz_concept_plan``).
"""
from __future__ import annotations

from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

import routes.study as route
from services.study import get_next

_app = FastAPI()
_app.include_router(route.router, prefix="/api/study")
client = TestClient(_app)

BUCKETS = {
    "due": [
        {
            "node_id": "a",
            "concept_name": "Alpha",
            "course_id": "c1",
            "reason": "due",
            "p_known": 0.96,
            "band": "profic",
            "due_at": "2026-11-07T12:00:00+00:00",
            "open_misconceptions": 0,
        }
    ],
    "misconceptions": [],
    "ready": [
        {
            "node_id": "b",
            "concept_name": "Beta",
            "course_id": "c1",
            "reason": "ready",
            "p_known": 0.4,
            "band": "novice",
            "due_at": None,
            "open_misconceptions": 0,
        }
    ],
}


def test_get_next_returns_learner_next_buckets():
    with (
        patch("services.study.next.quiz_learning.quiz_flags", return_value=(True,)),
        patch("services.study.next.ln.learner_next", return_value=BUCKETS) as ln,
    ):
        assert get_next("u1", "c1") == BUCKETS
    ln.assert_called_once_with("u1", "c1")


def test_get_next_404_when_flags_off():
    with patch("services.study.next.quiz_learning.quiz_flags", return_value=(False,)):
        from fastapi import HTTPException

        try:
            get_next("u1", "c1")
            raise AssertionError("expected 404")
        except HTTPException as exc:
            assert exc.status_code == 404
            assert "not enabled" in exc.detail


def test_get_next_503_when_state_read_fails():
    with (
        patch("services.study.next.quiz_learning.quiz_flags", return_value=(True,)),
        patch("services.study.next.ln.learner_next", side_effect=RuntimeError("db")),
    ):
        from fastapi import HTTPException

        try:
            get_next("u1")
            raise AssertionError("expected 503")
        except HTTPException as exc:
            assert exc.status_code == 503


def test_next_route_shape_and_course_id():
    with (
        patch("routes.study.require_self", return_value=None),
        patch("services.study.next.quiz_learning.quiz_flags", return_value=(True,)),
        patch("services.study.next.ln.learner_next", return_value=BUCKETS) as ln,
    ):
        r = client.get("/api/study/u1/next?course_id=c1")
    assert r.status_code == 200
    body = r.json()
    assert list(body) == ["due", "misconceptions", "ready"]
    assert body["due"][0]["node_id"] == "a"
    assert body["ready"][0]["reason"] == "ready"
    ln.assert_called_once_with("u1", "c1")


def test_next_route_404_when_off():
    with (
        patch("routes.study.require_self", return_value=None),
        patch("services.study.next.quiz_learning.quiz_flags", return_value=(False,)),
    ):
        r = client.get("/api/study/u1/next")
    assert r.status_code == 404


def test_next_route_requires_self():
    from fastapi import HTTPException

    def refuse(*_a, **_k):
        raise HTTPException(status_code=403, detail="forbidden")

    with patch("routes.study.require_self", side_effect=refuse):
        r = client.get("/api/study/u1/next")
    assert r.status_code == 403
