"""PKG-12 fix round (MAJOR 1): daily review sessions (`sessions.mode = 'review'`,
learning/review.py) are not tutor sessions. Every reader that treats a `sessions`
row as a tutor session excludes them — the Learn session list / Dashboard "Where
you left off" and its resume, the quiz personalization's tutor count, the profile
session count and the achievement stats — and a review session announces itself
with `review.session_started`, never `session.started` (canopy_metrics'
`tutor_sessions` counts that event)."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from services.session_modes import NOT_REVIEW, REVIEW_MODE

USER = "u1"


class _Spy:
    """table() stand-in recording every sessions read's filters."""

    def __init__(self, rows=None):
        self.filters: list[dict] = []
        self.rows = rows or []

    def __call__(self, name):
        handle = MagicMock(name=name)

        def select(columns="*", filters=None, **kw):
            if name == "sessions":
                self.filters.append(dict(filters or {}))
            return list(self.rows) if name == "sessions" else []

        def select_with_count(columns="*", filters=None, **kw):
            return select(columns, filters, **kw), len(self.rows)

        handle.select.side_effect = select
        handle.select_with_count.side_effect = select_with_count
        return handle


def test_the_mode_constant_and_filter():
    assert REVIEW_MODE == "review"
    assert NOT_REVIEW == {"mode": "neq.review"}  # sessions.mode is NOT NULL (0025)


def test_review_module_uses_the_shared_mode():
    from learning import review

    assert review._REVIEW_MODE == REVIEW_MODE


def test_list_sessions_excludes_review_sessions(monkeypatch):
    from routes import learn

    spy = _Spy()
    monkeypatch.setattr(learn, "table", spy)
    monkeypatch.setattr(learn, "require_self", lambda *a, **k: None)
    learn.list_sessions(USER, MagicMock())
    assert spy.filters and all(f.get("mode") == "neq.review" for f in spy.filters)


def test_resume_never_reopens_a_review_session(monkeypatch):
    from fastapi import HTTPException

    from routes import learn

    spy = _Spy()
    monkeypatch.setattr(learn, "table", spy)
    monkeypatch.setattr(learn, "get_session_user_id", lambda request: USER)
    with pytest.raises(HTTPException) as exc:
        learn.resume_session("sess-review", MagicMock())
    assert exc.value.status_code == 404
    assert spy.filters[-1].get("mode") == "neq.review"


def test_quiz_tutor_signal_excludes_review_sessions(monkeypatch):
    from services import quiz_signals

    spy = _Spy()
    monkeypatch.setattr(quiz_signals, "table", spy)
    quiz_signals._tutor_recency(USER, quiz_signals.CourseScope(offering_ids=["off-1"]), "Recursion")
    assert spy.filters and spy.filters[0].get("mode") == "neq.review"


def test_profile_session_count_excludes_review_sessions(monkeypatch):
    from routes import profile

    spy = _Spy()
    monkeypatch.setattr(profile, "table", spy)
    profile._get_user_stats(USER)
    assert spy.filters and all(f.get("mode") == "neq.review" for f in spy.filters)


@pytest.mark.parametrize("trigger", ["session_count", "session_minutes", "session_before_hour"])
def test_achievement_session_stats_exclude_review_sessions(monkeypatch, trigger):
    from services import achievement_service

    spy = _Spy()
    monkeypatch.setattr(achievement_service, "table", spy)
    achievement_service._get_user_stat(USER, trigger)
    assert spy.filters and all(f.get("mode") == "neq.review" for f in spy.filters)


def test_review_session_emits_its_own_start_event(monkeypatch):
    from learning import review

    handle = MagicMock()
    handle.select.return_value = []
    monkeypatch.setattr(review, "table", lambda name: handle)
    events = []
    monkeypatch.setattr(review, "log_event", lambda et, **kw: events.append((et, kw)))
    review.load_or_create_review_session(USER, None, datetime(2026, 9, 26, tzinfo=timezone.utc))
    assert [e[0] for e in events] == ["review.session_started"]
    assert "session.started" not in [e[0] for e in events]
    assert handle.insert.call_args.args[0]["mode"] == REVIEW_MODE


def test_review_session_started_is_in_the_taxonomy():
    from services.events_service import EVENT_TAXONOMY

    assert "review.session_started" in EVENT_TAXONOMY


# ── PKG-08's phase lock and review sessions ───────────────────────────────────
# A review session's loop_state has no `phase` (its keys are sr/review/open), and
# `_loop_phase` reads a phase-less document as "probe". So a review session must never
# reach a loop-session route: `_session_scope` (every probe/plan/teach/check route's
# ownership read) excludes mode='review' rows — a review session id is a 404 there —
# and the review routes never consult the phase.


def test_loop_session_scope_never_resolves_a_review_session(monkeypatch):
    from fastapi import HTTPException

    from routes import learn_loop

    spy = _Spy()
    monkeypatch.setattr(learn_loop, "table", spy)
    with pytest.raises(HTTPException) as exc:
        learn_loop._session_scope("sess-review", USER)
    assert exc.value.status_code == 404
    assert spy.filters[-1].get("mode") == "neq.review"


def test_probe_next_on_a_review_session_id_writes_nothing(monkeypatch):
    """The failure the scope guard prevents: /probe/next would read the phase-less
    review document as probing and write a probe into it."""
    from fastapi.testclient import TestClient
    from unittest.mock import patch

    from main import app

    class _ReviewRow(_Spy):
        """The review session's row — returned unless the read excludes mode=review."""

        def __call__(self, name):
            handle = super().__call__(name)
            inner = handle.select.side_effect

            def select(columns="*", filters=None, **kw):
                inner(columns, filters, **kw)
                if name == "sessions" and (filters or {}).get("mode") != "neq.review":
                    return [{"user_id": USER, "offering_id": "off-1", "mode": "review"}]
                return []

            handle.select.side_effect = select
            return handle

    monkeypatch.setattr("routes.learn_loop.table", _ReviewRow())
    monkeypatch.setattr("routes.learn_loop._load_loop_state", lambda sid: {"sr": {}, "review": {}})
    monkeypatch.setattr("routes.learn_loop._probe_course_has_items", lambda cid: False)
    monkeypatch.setattr("routes.learn_loop.offering_course_id", lambda oid: "c1")
    writes = []
    monkeypatch.setattr(
        "routes.learn_loop._update_loop_state", lambda *a, **k: writes.append(a) or {}
    )
    with (
        patch("routes.learn_loop.require_self", return_value=None),
        patch("routes.learn_loop.learning_loop_for_request", return_value=True),
        patch("routes.learn_loop._probe_plan_read_limit", return_value=None),
        patch("routes.learn_loop._consume_pending", return_value=None),
    ):
        r = TestClient(app).post(
            "/api/learn/loop/probe/next", json={"session_id": "sess-review", "user_id": USER}
        )
    assert r.status_code == 404 and writes == []


def test_review_routes_never_consult_the_loop_phase():
    """Review is its own session and mode: no /review/* handler (nor learning/review.py)
    reads the probe/plan/teach phase or the teaching lock."""
    import ast
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[1]
    tree = ast.parse((root / "routes" / "learn_loop.py").read_text())
    handlers = {"review_next", "review_answer", "review_summary", "review_active"}
    lock = {
        "_loop_phase",
        "_require_teaching",
        "_teaching_open",
        "_require_phase",
        "_session_scope",
    }
    found = set()
    for fn in ast.walk(tree):
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) and fn.name in handlers:
            found.add(fn.name)
            names = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)}
            assert not names & lock, (fn.name, names & lock)
    assert found == handlers
    review_src = (root / "learning" / "review.py").read_text()
    assert '"phase"' not in review_src and "_loop_phase" not in review_src


def test_a_phase_less_review_document_still_serves(monkeypatch):
    """The review queue works on a document with no `phase` (what _loop_phase would
    read as probing) — and on one that somehow carries phase=probe."""
    from learning import review

    for doc in ({"sr": {}, "review": {}}, {"phase": "probe", "sr": {}, "review": {}}):
        item = review.ReviewItem(
            kind="flashcard",
            id="f1",
            r=0.5,
            stability=1.0,
            cost_s=15,
            sr_stage="acquire",
            sr_target=3,
        )
        payload = review.serve(item, card_row={"front": "Q", "back": "A"}, loop_state=doc)
        assert payload["kind"] == "flashcard"


# ── Round 2: legacy id-keyed tutor routes refuse a review session ─────────────
# /review/next returns the review session id, so a client holds it. Ending it would
# award session XP and write summary_json; deleting it would wipe today's review
# state (an unlimited daily budget); renaming or mode-switching would treat it as a
# tutor session. Each route's id read excludes mode='review' → 404, nothing written.


class _Recorder(_Spy):
    """The review session's row on any read that does not exclude mode=review;
    every write recorded."""

    def __init__(self):
        super().__init__()
        self.writes: list[tuple[str, str]] = []

    def __call__(self, name):
        handle = super().__call__(name)
        inner = handle.select.side_effect

        def select(columns="*", filters=None, **kw):
            inner(columns, filters, **kw)
            if name == "sessions" and (filters or {}).get("mode") != "neq.review":
                return [
                    {
                        "user_id": USER,
                        "topic": "Daily review",
                        "mode": "review",
                        "started_at": "2026-09-29T00:00:00+00:00",
                        "offering_id": None,
                    }
                ]
            return []

        handle.select.side_effect = select
        for op in ("insert", "update", "upsert", "delete"):
            getattr(handle, op).side_effect = lambda *a, _op=op, _n=name, **k: (
                self.writes.append((_n, _op)) or []
            )
        return handle


@pytest.fixture
def legacy(monkeypatch):
    from routes import learn

    rec = _Recorder()
    monkeypatch.setattr(learn, "table", rec)
    monkeypatch.setattr(learn, "require_self", lambda *a, **k: None)
    monkeypatch.setattr(learn, "learning_loop_for_request", lambda uid: False)
    monkeypatch.setattr(
        learn, "save_message", lambda *a, **k: rec.writes.append(("messages", "insert"))
    )
    monkeypatch.setattr(learn, "get_user_name", lambda uid: "Andres")
    monkeypatch.setattr(learn, "_consume_pending", lambda *a, **k: None)
    return learn, rec


def _refused(call, rec, *, filtered=True):
    """404 and no write. `filtered`: the id read excludes mode=review; otherwise
    (delete, mode-switch — which keep their tolerance of a missing row) the read
    selects `mode` and the route refuses a review row itself."""
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        call()
    assert exc.value.status_code == 404, exc.value.detail
    assert rec.writes == []
    if filtered:
        assert rec.filters and rec.filters[-1].get("mode") == "neq.review"


def test_end_session_refuses_a_review_session(legacy):
    from models import EndSessionBody

    learn, rec = legacy
    _refused(
        lambda: learn.end_session(
            EndSessionBody(session_id="sess-review", user_id=USER), MagicMock()
        ),
        rec,
    )


def test_delete_session_refuses_a_review_session(legacy):
    learn, rec = legacy
    _refused(
        lambda: learn.delete_session("sess-review", MagicMock(), user_id=USER), rec, filtered=False
    )


def test_rename_session_refuses_a_review_session(legacy):
    from models import RenameSessionBody

    learn, rec = legacy
    _refused(
        lambda: learn.rename_session(
            "sess-review", RenameSessionBody(user_id=USER, topic="x"), MagicMock()
        ),
        rec,
    )


def test_mode_switch_refuses_a_review_session(legacy):
    from models import ModeSwitchBody

    learn, rec = legacy
    _refused(
        lambda: learn.mode_switch(
            ModeSwitchBody(session_id="sess-review", user_id=USER, new_mode="expository"),
            MagicMock(),
        ),
        rec,
        filtered=False,
    )
